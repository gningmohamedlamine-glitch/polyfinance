"""Web news leads via AgentCore Search and Nova grounding."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import TimeoutError
from contextvars import copy_context
from .runtime import ContextExecutor as ThreadPoolExecutor
from datetime import date, datetime, timedelta
from itertools import batched
from threading import BoundedSemaphore, Thread
from time import monotonic
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .runtime import converse, network_call
from .model_text import public_text
from .temporal import annotate
from .source_quality import COMPANY_HOSTS, check_source, is_official

logger = logging.getLogger(__name__)
MODEL = "us.amazon.nova-2-lite-v1:0"
WEB_SEARCH_ID = "web-search.v1"
RELEVANCE_UNEVALUATED = "Pertinence non évaluée."
REQUIRED_FIELDS = ("url", "title", "published_date", "session", "summary")
SOURCE_TYPE_DEFAULT = "other"
RAW_COLLECT_MAX = int(os.getenv("MARKET_WEB_RAW_LEAD_MAX", "24"))
CLUSTER_KEEP = int(os.getenv("MARKET_WEB_CLUSTER_KEEP", "12"))
RELEVANCE_KEEP = int(os.getenv("MARKET_WEB_RELEVANCE_KEEP", "8"))
AGENTCORE_WORKERS = 3
OFFICIAL_QUERY_COUNT = 4
# Official sites plus company news. Generic geopolitical queries stay behind these.
PRIORITY_QUERY_COUNT = 8
GROUNDING_SOFT_BUDGET = 10
ARTICLE_CHECK_LIMIT = 5
_grounding_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-grounding")
_grounding_slots = BoundedSemaphore(4)


def web_windows(dates, window):
    radius = timedelta(days=5)
    anchors = dict.fromkeys(dates)
    if window.applied == "period":
        anchors[window.end_close_date] = None
    windows = {}
    for session in anchors:
        day = date.fromisoformat(session)
        start = (day - radius).isoformat()
        if window.applied == "period" and session == window.end_close_date:
            start = min(start, window.start_close_date)
        windows[session] = (start, (day + radius).isoformat())
    return windows


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    if not host:
        return url.strip()
    path = parsed.path.rstrip("/") or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://{host}{path}{query}"


def agentcore_client():
    return boto3.session.Session().client(
        "bedrock-agentcore",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=3, read_timeout=20, retries={"total_max_attempts": 1}),
    )


def _parse_json_array(answer):
    try:
        return json.loads(answer[answer.index("["):answer.rindex("]") + 1])
    except (ValueError, TypeError):
        return None


def _parse_published(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _session_for_date(published: str, windows: dict[str, tuple[str, str]]) -> str | None:
    matches = [
        session for session, (start, end) in windows.items()
        if start <= published <= end
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return min(matches, key=lambda session: abs(
        (date.fromisoformat(published) - date.fromisoformat(session)).days
    ))


def _host_blocked(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return not host


def _clean_snippet(text: str) -> str:
    """Strip markdown links and AgentCore table-like metadata from snippets."""
    if not text:
        return ""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    title_cell = re.search(r"event_title\s*\|\s*([^|\n]+)", text, re.I)
    if title_cell:
        return re.sub(r"\s+", " ", title_cell.group(1)).strip()[:500]
    if "|" in text and re.search(r"event_(date|title|domain)", text, re.I):
        cells = [cell.strip() for cell in text.split("|") if cell.strip()]
        skip = {"event_date", "event_title", "source_domain"}
        values = [
            cell for cell in cells
            if cell.lower() not in skip and not re.match(r"^event_", cell, re.I)
        ]
        if values:
            return re.sub(r"\s+", " ", "; ".join(values[:4])).strip()[:500]
    text = re.sub(r"\|\s*\w+[_\w]*\s*\|", " ", text)
    text = text.replace("|", " ")
    return re.sub(r"\s+", " ", text).strip()[:500]


def _normalize_lead(lead: dict) -> dict:
    title = _clean_snippet(str(lead.get("title", "")))
    summary = _clean_snippet(str(lead.get("summary", "")))
    out = {
        **lead,
        "title": (title or "Article")[:500],
        "summary": summary or "Extrait indisponible.",
    }
    facts = lead.get("facts")
    if isinstance(facts, list):
        cleaned = [_clean_snippet(str(fact)) for fact in facts]
        out["facts"] = [fact[:240] for fact in cleaned if fact][:5]
    relevance = lead.get("relevance")
    if isinstance(relevance, str) and relevance.strip():
        out["relevance"] = _clean_snippet(relevance)[:500]
    return annotate(out)


def _append_lead(leads: list[dict], seen: set[str], row: dict, *, limit: int) -> None:
    key = normalize_url(row["url"])
    if key in seen:
        return
    seen.add(key)
    leads.append(_normalize_lead(row))
    if len(leads) >= limit:
        return


def _agentcore_queries(ticker, name, start, end):
    return [
        f"site:{COMPANY_HOSTS.get(ticker, 'sec.gov')} {name} after:{start} before:{end}",
        f"site:sec.gov {name} after:{start} before:{end}",
        f"site:federalreserve.gov monetary after:{start} before:{end}",
        f"site:bls.gov news release after:{start} before:{end}",
        f"{ticker} {name} stock news"[:200],
        f"{ticker} {name} earnings analyst"[:200],
        f"{ticker} CEO resignation governance"[:200],
        f"{ticker} export ban sanctions tariffs chips"[:200],
        f"US China trade war tariffs semiconductor market"[:200],
        f"geopolitical conflict ban {name} sector stocks"[:200],
    ]


def _title_fingerprint(title: str) -> str:
    words = re.findall(r"\w+", (title or "").lower())
    return " ".join(words[:5]) if words else ""


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def corroborate(lead: dict, urls: list[str]) -> dict:
    """Corroboration = nombre de domaines distincts ; leur indépendance éditoriale n’est pas vérifiée."""
    domains = sorted({_domain(u) for u in [lead["url"], *urls] if _domain(u)})
    lead["domains"] = domains
    lead["corroboration"] = len(domains)
    lead["verification"] = "corroborated" if len(domains) >= 2 else "single_source"
    return lead


def _merge_leads(*batches: list[dict], limit: int = RAW_COLLECT_MAX) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for batch in batches:
        for lead in batch:
            key = normalize_url(lead["url"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(lead)
            if len(merged) >= limit:
                return merged
    return merged


def _simple_dedupe_leads(leads: list[dict], *, limit: int = CLUSTER_KEEP) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for lead in leads:
        key = _title_fingerprint(lead.get("title", "")) or normalize_url(lead["url"])
        groups.setdefault(key, []).append(lead)
    out: list[dict] = []
    for key, items in groups.items():
        best = max(items, key=lambda row: (is_official(row['url']), len(row.get("summary", ""))))
        facts = _facts_from_summary(best.get("summary", ""))
        out.append(corroborate({
            **best,
            "story_key": key[:80] or best.get("title", "")[:80],
            "related_count": len(items),
            "facts": facts,
            "summary": "; ".join(facts) if facts else best.get("summary", ""),
        }, [row["url"] for row in items]))
        if len(out) >= limit:
            break
    return out


def _facts_from_summary(text: str, *, max_facts: int = 5) -> list[str]:
    clean = _clean_snippet(text)
    if not clean:
        return []
    parts = [part.strip() for part in re.split(r"[.;]\s+", clean) if part.strip()]
    if len(parts) <= 1:
        return [clean[:240]]
    return [part[:240] for part in parts[:max_facts]]


def _cluster_leads(client, ticker, name, leads: list[dict], *, moves=None) -> list[dict]:
    if not leads:
        return []
    if len(leads) == 1:
        lead = leads[0]
        facts = _facts_from_summary(lead.get("summary", ""))
        return [{
            **lead,
            "story_key": _title_fingerprint(lead.get("title", "")) or lead.get("title", "")[:80],
            "related_count": 1,
            "facts": facts,
            "summary": "; ".join(facts) if facts else lead.get("summary", ""),
        }]
    if os.getenv("MARKET_WEB_CLUSTER", "1") != "1":
        return _simple_dedupe_leads(leads)

    prompt = (
        f"Regroupe des articles web sur {name} ({ticker}) qui racontent le même événement.\n"
        f"Entrée: {json.dumps(leads, ensure_ascii=False)}\n"
        f"Produit au plus {CLUSTER_KEEP} histoires distinctes (événements différents). "
        "Fusionne les doublons (même démission, même tarif, même rapport) en une seule entrée. "
        "Pour chaque histoire: privilégie la publication officielle pertinente si disponible, conserve title, published_date, session, "
        "source_type; liste 2 à 5 faits distincts en français (facts); cite aussi_urls pour les "
        "autres articles du même groupe.\n"
        'Réponds uniquement avec {"stories": [{"story_key": "...", "url": "...", "title": "...", '
        '"published_date": "YYYY-MM-DD", "session": "...", "source_type": "...", '
        '"facts": ["..."], "also_urls": ["..."], "relevant": true, "relevance": "..."}]}'
    )
    if moves is not None:
        prompt += (
            f"\nRendements par séance : {json.dumps(moves)}. "
            "Pour chaque histoire, donne aussi relevant (booléen) et relevance (une courte justification). "
            "Garde les événements concernant le titre, son secteur ou un facteur macro plausible pour la séance. "
            "Un suivi publié après la séance peut être utile mais ne constitue pas une cause contemporaine."
        )
    try:
        response = converse(client,
            modelId=MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1400},
        )
    except (ConnectTimeoutError, ReadTimeoutError, BotoCoreError, ClientError):
        logger.warning("Nova story cluster failed for %s", ticker)
        return _simple_dedupe_leads(leads)

    answer = public_text(response.get("output", {}).get("message", {}), separator="")
    try:
        payload = json.loads(answer[answer.index("{"):answer.rindex("}") + 1])
    except (ValueError, TypeError):
        return _simple_dedupe_leads(leads)
    stories = payload.get("stories") if isinstance(payload, dict) else None
    if not isinstance(stories, list) or not stories:
        return _simple_dedupe_leads(leads)

    by_url = {normalize_url(lead["url"]): lead for lead in leads}
    clustered: list[dict] = []
    for story in stories[:CLUSTER_KEEP]:
        if not isinstance(story, dict):
            continue
        url = story.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        base = by_url.get(normalize_url(url), {})
        if not base:
            continue  # A model cannot introduce an unfetched URL during clustering.
        facts = story.get("facts")
        if not isinstance(facts, list):
            facts = []
        facts = [str(item).strip() for item in facts if isinstance(item, str) and item.strip()][:5]
        if not facts:
            facts = _facts_from_summary(base.get("summary", ""))
        also = story.get("also_urls")
        if not isinstance(also, list):
            also = []
        also = [u for u in also if isinstance(u, str) and normalize_url(u) in by_url]
        published = base.get("published_date")
        session = base.get("session")
        if not isinstance(published, str) or not isinstance(session, str):
            continue
        source_type = story.get("source_type") if isinstance(story.get("source_type"), str) else base.get("source_type", SOURCE_TYPE_DEFAULT)
        clustered.append(corroborate({
            "url": url.strip(),
            "original_excerpt": base.get("original_excerpt", ""),
            "published_at": base.get("published_at"),
            "title": (story.get("title") if isinstance(story.get("title"), str) else base.get("title", "Article"))[:500],
            "published_date": published,
            "session": session,
            "source_type": source_type[:80],
            "after_session": base.get("after_session", published > session),
            "summary": ("; ".join(facts) if facts else base.get("summary", ""))[:500],
            "story_key": (story.get("story_key") if isinstance(story.get("story_key"), str) else "")[:80],
            "related_count": 1 + len(also),
            "facts": facts,
            **({"relevant": story["relevant"], "relevance": story.get("relevance") or RELEVANCE_UNEVALUATED}
               if moves is not None and isinstance(story.get("relevant"), bool)
               and isinstance(story.get("relevance", ""), str) else {}),
        }, also))
    if clustered:
        logger.info("Clustered %d raw lead(s) into %d story(ies) for %s", len(leads), len(clustered), ticker)
        return clustered
    return _simple_dedupe_leads(leads)


def search_agentcore_leads(ticker, name, windows, *, limit=RAW_COLLECT_MAX, moves=None, covered_sessions=()):
    """Dated news via Bedrock AgentCore invoke_web_search.

    Company and official-site queries always run. Generic geopolitical queries
    run only when those results do not yet cover every material session.
    """
    if os.getenv("MARKET_WEB_SEARCH_AGENTCORE", "1") != "1":
        return []
    priority, broad = [], []
    for session, (start, end) in windows.items():
        texts = _agentcore_queries(ticker, name, start, end)
        priority.extend((session, start, end, text) for text in texts[:PRIORITY_QUERY_COUNT])
        broad.extend((session, start, end, text) for text in texts[PRIORITY_QUERY_COUNT:])
    leads: list[dict] = []
    seen: set[str] = set()
    try:
        search = agentcore_client()
    except (BotoCoreError, ClientError) as error:
        logger.info("AgentCore client unavailable for %s: %s", ticker, type(error).__name__)
        return []

    def fetch(task):
        _, start, end, query = task
        try:
            network_call()
            response = search.invoke_web_search(
                webSearchId=WEB_SEARCH_ID,
                searchQuery=query,
                maxResults=min(10, limit),
                filters={
                    "publishedDateFilter": {
                        "publishedAfter": f"{start}T00:00:00Z",
                        "publishedBefore": f"{end}T23:59:59Z",
                    },
                },
            )
            return response.get("results") or []
        except (ConnectTimeoutError, ReadTimeoutError):
            logger.warning("AgentCore web search timed out for %s (%s)", ticker, query)
        except (BotoCoreError, ClientError) as error:
            logger.info("AgentCore web search failed for %s: %s", ticker, type(error).__name__)
        return []

    def collect(queries):
        # Keep query priority independent of network completion order. Submit one
        # batch at a time so hitting the lead limit leaves at most one batch in flight.
        with ThreadPoolExecutor(max_workers=AGENTCORE_WORKERS) as workers:
            for batch in batched(queries, AGENTCORE_WORKERS):
                if len(leads) >= limit:
                    break
                for (session, start, end, _), results in zip(batch, workers.map(fetch, batch)):
                    for item in results:
                        if len(leads) >= limit:
                            break
                        url = item.get("url")
                        if not isinstance(url, str) or not url.strip():
                            continue
                        url = url.strip()
                        if not url.startswith("https://") or _host_blocked(url):
                            continue
                        published = _parse_published(item.get("publishedAt"))
                        if not published or not start <= published <= end:
                            continue
                        title = item.get("title")
                        text = item.get("text")
                        summary = (_clean_snippet(text) if isinstance(text, str) else "") or "Extrait indisponible."
                        _append_lead(leads, seen, {
                            "url": url,
                            "title": _clean_snippet(title) if isinstance(title, str) else "Article",
                            "published_date": published,
                            "published_at": str(item.get("publishedAt")) if "T" in str(item.get("publishedAt")) or isinstance(item.get("publishedAt"), datetime) else None,
                            "session": session,
                            "summary": summary,
                            "original_excerpt": summary,
                            "source_type": "news",
                            "after_session": published > session,
                        }, limit=limit)

    collect(priority)
    covered = (
        moves is not None and bool(leads)
        and _covers_material_sessions(leads, ticker, name, windows, moves, covered_sessions)
    )
    if not covered and len(leads) < limit:
        collect(broad)
    if leads:
        logger.info("AgentCore returned %d dated lead(s) for %s", len(leads), ticker)
    return leads


def _citation_urls(blocks) -> tuple[set[str], set[str]]:
    raw = set()
    for block in blocks:
        citations = block.get("citationsContent", {}).get("citations", [])
        for citation in citations:
            url = citation.get("location", {}).get("web", {}).get("url")
            if url:
                raw.add(url)
    normalized = {normalize_url(url) for url in raw}
    return raw, normalized


def _collect_cited_leads(rows, cited_raw, cited_normalized, windows, *, limit=RAW_COLLECT_MAX):
    leads = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str) and row[field] for field in REQUIRED_FIELDS
        ):
            continue
        url = row["url"]
        norm = normalize_url(url)
        if url not in cited_raw and norm not in cited_normalized:
            continue
        if norm in seen or row["session"] not in windows:
            continue
        try:
            published = date.fromisoformat(row["published_date"]).isoformat()
        except ValueError:
            continue
        start, end = windows[row["session"]]
        if _host_blocked(url) or not start <= published <= end:
            continue
        if not url.startswith("https://"):
            continue
        seen.add(norm)
        source_type = row.get("source_type")
        if not isinstance(source_type, str) or not source_type.strip():
            source_type = SOURCE_TYPE_DEFAULT
        else:
            source_type = source_type.strip()[:80]
        leads.append(_normalize_lead({
            **{field: row[field][:500] for field in REQUIRED_FIELDS},
            "original_excerpt": row.get("original_excerpt", "")[:1000] if isinstance(row.get("original_excerpt"), str) else "",
            "url": url if url.startswith("https://") else normalize_url(url),
            "published_date": published,
            "after_session": published > row["session"],
            "source_type": source_type,
        }))
        if len(leads) >= limit:
            break
    return leads


def _search_queries(ticker, name, windows, *, macro=True):
    queries = []
    for session, (start, end) in windows.items():
        day = date.fromisoformat(session).strftime("%B %d %Y")
        queries.extend(_agentcore_queries(ticker, name, start, end)[:OFFICIAL_QUERY_COUNT])
        queries.append(f"{ticker} {name} stock news after:{start} before:{end}")
        queries.append(f'"{name}" OR {ticker} earnings analyst {start}..{end}')
        queries.append(f"{ticker} shares market news {day} Reuters OR Bloomberg OR CNBC")
        if macro:
            queries.append(f"{ticker} export ban sanctions tariffs after:{start} before:{end}")
            queries.append(f"war geopolitical trade tariffs semiconductor market {start}..{end}")
        else:
            queries.append(f"{name} {ticker} investor announcement {day}")
    return queries[:20 if macro else 12]


def _grounding_leads(client, ticker, name, windows, macro=True):
    queries = _search_queries(ticker, name, windows, macro=macro)
    prompt = (
        f"Search the public web for news and market coverage about {name} ({ticker}) "
        "around specific U.S. equity trading dates. Include company news, sector news, and "
        "macro or geopolitical drivers (wars, tariffs, export bans, sanctions) when dated "
        "in the windows. Prioritize official company investor relations, SEC press releases, "
        "Federal Reserve and BLS publications. Exclude live stock quote pages and undated pages. "
        "Never invent a publication date or substitute the trading date.\n"
        f"Queries: {json.dumps(queries)}.\n"
        f"Publication-date windows by session (YYYY-MM-DD): {json.dumps(windows)}.\n"
        "Return only a JSON array of objects with url, title, published_date, session, "
        "source_type, summary (one short French sentence), original_excerpt (a short verbatim "
        "passage in the source language, or empty if unavailable). Copy exact cited https URLs."
    )
    try:
        response = converse(client,
            modelId=MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={"tools": [{"systemTool": {"name": "nova_grounding"}}]},
            inferenceConfig={"maxTokens": 1300},
        )
    except (ConnectTimeoutError, ReadTimeoutError):
        logger.warning("Nova Web Grounding timed out for %s", ticker)
        return [], "timeout"
    except (BotoCoreError, ClientError) as error:
        logger.warning("Nova Web Grounding failed: %s", type(error).__name__)
        return [], "unavailable"

    blocks = response.get("output", {}).get("message", {}).get("content", [])
    cited_raw, cited_normalized = _citation_urls(blocks)
    if not cited_raw and not any(block.get("toolResult", {}).get("status") == "success" for block in blocks):
        tool_failed = any(block.get("toolResult", {}).get("status") == "error" for block in blocks)
        return [], "unavailable" if tool_failed else "not_executed"
    text_blocks = [
        {"text": fragment["text"]}
        for block in blocks
        for fragment in ([block] if "text" in block else block.get("citationsContent", {}).get("content", []))
        if "text" in fragment
    ]
    answer = public_text({"content": text_blocks}, separator="")
    rows = _parse_json_array(answer)
    if not isinstance(rows, list):
        return [], "invalid_response"
    leads = _collect_cited_leads(rows, cited_raw, cited_normalized, windows)
    if leads:
        logger.info("Nova grounding returned %d dated lead(s) for %s", len(leads), ticker)
    return leads, "grounding"


def _judge_relevance(client, ticker, name, moves, leads):
    session_moves = [
        {"session": lead["session"], "daily_return": moves.get(lead["session"])}
        for lead in leads
    ]
    prompt = (
        f"Tu évalues la pertinence de pistes web pour {name} ({ticker}).\n"
        f"Mouvements journaliers par séance cible: {json.dumps(session_moves, ensure_ascii=False)}\n"
        f"Pistes à juger (déjà regroupées par histoire; related_count = doublons fusionnés): "
        f"{json.dumps(leads, ensure_ascii=False)}\n"
        "Pour chaque url, décide si la source concerne cette entreprise, son secteur, "
        "un annonceur ou un événement de marché pouvant expliquer le mouvement de la séance "
        "indiquée. Conserver les départs de dirigeants, annonces de gouvernance et "
        "scandales documentés lorsqu’ils visent clairement ce titre. Conserver aussi les "
        "pistes macro et géopolitiques (guerres, tarifs, sanctions, interdictions d’export, "
        "régulation) si elles peuvent expliquer le mouvement du titre ou de son secteur.\n"
        'Réponds uniquement avec un tableau JSON d\'objets {"url": "...", "relevant": true|false, '
        '"relevance": "une courte phrase en français"} — une entrée par piste, mêmes url.'
    )
    try:
        response = converse(client,
            modelId=MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1200},
        )
    except (ConnectTimeoutError, ReadTimeoutError):
        logger.warning("Nova relevance judge timed out for %s", ticker)
        return None
    except (BotoCoreError, ClientError) as error:
        logger.warning("Nova relevance judge failed: %s", type(error).__name__)
        return None

    answer = public_text(response.get("output", {}).get("message", {}), separator="")
    rows = _parse_json_array(answer)
    if not isinstance(rows, list):
        return None

    by_url = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        relevant = row.get("relevant")
        relevance = row.get("relevance")
        if not isinstance(url, str) or not isinstance(relevant, bool):
            continue
        if not isinstance(relevance, str) or not relevance.strip():
            relevance = "Sans commentaire." if relevant else "Hors sujet."
        by_url[normalize_url(url)] = {"relevant": relevant, "relevance": relevance.strip()[:500]}
        by_url[url] = by_url[normalize_url(url)]
    return by_url


def _apply_relevance(leads, judgments):
    if judgments is None:
        return [{**lead, "relevance": RELEVANCE_UNEVALUATED} for lead in leads], "found"

    kept = []
    for lead in leads:
        verdict = judgments.get(lead["url"]) or judgments.get(normalize_url(lead["url"]))
        if verdict and verdict["relevant"]:
            kept.append(_normalize_lead({**lead, "relevance": verdict["relevance"]}))
    if kept:
        return kept[:RELEVANCE_KEEP], "found"
    return [], "no_relevant_sources"


def _covers_material_sessions(leads, ticker, name, windows, moves, covered_sessions):
    targets = set(moves) & windows.keys() or set(windows)
    company = re.compile(r"\b(?:" + "|".join(re.escape(value) for value in (ticker, name)) + r")\b", re.I)
    hosts = {session: set() for session in targets}
    for lead in leads:
        session = lead["session"]
        if session in targets and not lead.get("after_session") and company.search(lead["title"]):
            hosts[session].add(_domain(lead["url"]))
            if "relevance" in lead and lead["relevance"] != RELEVANCE_UNEVALUATED:
                hosts[session].update(lead.get("domains", ()))
    return all(session in covered_sessions or len(hosts[session]) >= 2 for session in targets)


def _check_articles(leads, *, limit=ARTICLE_CHECK_LIMIT):
    # Prioritize contemporary sources. Keep one active fetch per publisher.
    by_host = {}
    chosen = sorted(
        (i for i, lead in enumerate(leads) if is_official(lead["url"])),
        key=lambda i: bool(leads[i].get("after_session")),
    )[:limit]
    checked = [{**lead, "source_origin": "official" if is_official(lead["url"]) else "other",
                "page_status": "not_checked", "excerpt_status": "no_excerpt"} for lead in leads]
    for i in chosen:
        by_host.setdefault(_domain(leads[i]["url"]), []).append(i)

    def verify(indices):
        return [(i, check_source(leads[i])) for i in indices]

    if by_host:
        with ThreadPoolExecutor(max_workers=min(4, len(by_host))) as workers:
            for batch in workers.map(verify, by_host.values()):
                for i, row in batch:
                    checked[i] = row
    return checked


def _rank_web(client, ticker, name, moves, leads, *, combined=True):
    leads = _cluster_leads(client, ticker, name, leads, moves=moves if combined else None)
    if all("relevant" in lead for lead in leads):
        judged = {lead["url"]: {"relevant": lead["relevant"], "relevance": lead["relevance"]} for lead in leads}
    else:
        judged = _judge_relevance(client, ticker, name, moves, leads)
    public = [{key: value for key, value in lead.items() if key != "relevant"} for lead in leads]
    return _apply_relevance(public, judged)


def find_web_leads(client, ticker, name, windows, moves=None, *, covered_sessions=(), details=None, deep=False,
                   macro=True):
    if os.getenv("MARKET_WEB_SEARCH") != "1":
        return [], "disabled"

    moves = moves or {}
    started = monotonic()
    grounding = None
    if _grounding_slots.acquire(blocking=False):
        try:
            grounding = _grounding_workers.submit(
                _grounding_leads, client, ticker, name, windows, macro or deep,
            )
        except BaseException:
            _grounding_slots.release()
            raise
        grounding.add_done_callback(lambda _: _grounding_slots.release())

    agentcore = search_agentcore_leads(
        ticker, name, windows, moves=moves, covered_sessions=covered_sessions,
    )
    primary = _merge_leads(sorted(agentcore, key=lambda row: not is_official(row["url"])))
    # Rank AgentCore leads while Nova is still searching. The soft budget still
    # requires the ranked leads to cover the material sessions.
    early_rank: dict = {}
    rank_thread = None
    if primary and not deep:
        def _rank_primary():
            try:
                early_rank["value"] = _rank_web(client, ticker, name, moves, primary)
            except BaseException as error:
                early_rank["error"] = error

        rank_thread = Thread(target=copy_context().run, args=(_rank_primary,), name="web-rank", daemon=True)
        rank_thread.start()

    def ranked_primary():
        if rank_thread is None:
            return None
        rank_thread.join()
        if "error" in early_rank:
            raise early_rank["error"]
        return early_rank.get("value")

    early = None
    extra, detail = [], "busy"
    if grounding is not None:
        provisional = (
            not deep and not grounding.done() and bool(primary)
            and _covers_material_sessions(primary, ticker, name, windows, moves, covered_sessions)
        )
        if provisional:
            early = ranked_primary()
            enough = early is not None and _covers_material_sessions(
                [lead for lead in early[0] if lead.get("relevance") != RELEVANCE_UNEVALUATED],
                ticker, name, windows, moves, covered_sessions,
            )
            if not enough:
                early = None
        remaining = max(0, GROUNDING_SOFT_BUDGET - (monotonic() - started)) if early is not None else None
        try:
            extra, detail = grounding.result(timeout=remaining)
        except TimeoutError:
            detail = "budget_elapsed"
    if details is not None:
        details["grounding"] = detail
    leads = _merge_leads(sorted(agentcore + extra, key=lambda row: not is_official(row['url']))) if extra else primary
    if not leads:
        if detail in {"timeout", "unavailable", "not_executed", "invalid_response", "busy", "budget_elapsed"}:
            return [], detail
        return [], "no_dated_sources"
    if agentcore and extra:
        source = "agentcore+grounding"
    elif agentcore:
        source = "agentcore"
    else:
        source = "grounding"

    if early is not None and not extra:
        result, status = early
    elif not extra and rank_thread is not None:
        result, status = ranked_primary()
    else:
        result, status = _rank_web(client, ticker, name, moves, leads, combined=not deep)
    if result:
        logger.info("Web leads for %s via %s: %d kept", ticker, source, len(result))
    return _check_articles(result, limit=RELEVANCE_KEEP if deep else ARTICLE_CHECK_LIMIT), status
