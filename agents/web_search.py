"""Web news leads via AgentCore Search (dated) with Nova grounding fallback."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .model_text import public_text
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
    return boto3.client(
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
    return out


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
    """Corroboration = nombre de sites indépendants qui rapportent la même histoire (domaines distincts)."""
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


def _cluster_leads(client, ticker, name, leads: list[dict]) -> list[dict]:
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
        '"facts": ["..."], "also_urls": ["..."]}]}'
    )
    try:
        response = client.converse(
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
            "title": (story.get("title") if isinstance(story.get("title"), str) else base.get("title", "Article"))[:500],
            "published_date": published,
            "session": session,
            "source_type": source_type[:80],
            "after_session": base.get("after_session", published > session),
            "summary": ("; ".join(facts) if facts else base.get("summary", ""))[:500],
            "story_key": (story.get("story_key") if isinstance(story.get("story_key"), str) else "")[:80],
            "related_count": 1 + len(also),
            "facts": facts,
        }, also))
    if clustered:
        logger.info("Clustered %d raw lead(s) into %d story(ies) for %s", len(leads), len(clustered), ticker)
        return clustered
    return _simple_dedupe_leads(leads)


def search_agentcore_leads(ticker, name, windows, *, limit=RAW_COLLECT_MAX):
    """Dated news via Bedrock AgentCore invoke_web_search."""
    if os.getenv("MARKET_WEB_SEARCH_AGENTCORE", "1") != "1":
        return []
    queries = []
    for session, (start, end) in windows.items():
        for text in _agentcore_queries(ticker, name, start, end):
            queries.append((session, start, end, text))
    leads: list[dict] = []
    seen: set[str] = set()
    try:
        search = agentcore_client()
    except (BotoCoreError, ClientError) as error:
        logger.info("AgentCore client unavailable for %s: %s", ticker, type(error).__name__)
        return []

    for session, start, end, query in queries:
        if len(leads) >= limit:
            break
        try:
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
        except (ConnectTimeoutError, ReadTimeoutError):
            logger.warning("AgentCore web search timed out for %s (%s)", ticker, query)
            continue
        except (BotoCoreError, ClientError) as error:
            logger.info("AgentCore web search failed for %s: %s", ticker, type(error).__name__)
            continue

        for item in response.get("results") or []:
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
            title = _clean_snippet(item.get("title") if isinstance(item.get("title"), str) else "")
            if not title:
                title = "Article"
            text = item.get("text")
            summary = _clean_snippet(text) if isinstance(text, str) else ""
            if not summary:
                summary = "Extrait indisponible."
            assigned = session if start <= published <= end else _session_for_date(published, windows)
            if assigned is None:
                continue
            _append_lead(leads, seen, {
                "url": url,
                "title": title[:500],
                "published_date": published,
                "session": assigned,
                "summary": summary,
                "original_excerpt": summary,
                "source_type": "news",
                "after_session": published > assigned,
            }, limit=limit)
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


def _search_queries(ticker, name, windows):
    queries = []
    for session, (start, end) in windows.items():
        day = date.fromisoformat(session).strftime("%B %d %Y")
        queries.extend(_agentcore_queries(ticker, name, start, end)[:4])
        queries.append(f"{ticker} {name} stock news after:{start} before:{end}")
        queries.append(f'"{name}" OR {ticker} earnings analyst {start}..{end}')
        queries.append(f"{ticker} shares market news {day} Reuters OR Bloomberg OR CNBC")
        queries.append(f"{ticker} export ban sanctions tariffs after:{start} before:{end}")
        queries.append(f"war geopolitical trade tariffs semiconductor market {start}..{end}")
    return queries[:20]


def _grounding_leads(client, ticker, name, windows):
    queries = _search_queries(ticker, name, windows)
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
        response = client.converse(
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
        response = client.converse(
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


def find_web_leads(client, ticker, name, windows, moves=None):
    if os.getenv("MARKET_WEB_SEARCH") != "1":
        return [], "disabled"

    agentcore = search_agentcore_leads(ticker, name, windows)
    extra, detail = _grounding_leads(client, ticker, name, windows)
    leads = _merge_leads(sorted(agentcore + extra, key=lambda row: not is_official(row['url'])))
    if not leads:
        if detail in {"timeout", "unavailable", "not_executed", "invalid_response"}:
            return [], detail
        return [], "no_dated_sources"
    if agentcore and extra:
        source = "agentcore+grounding"
    elif agentcore:
        source = "agentcore"
    else:
        source = "grounding"

    leads = _cluster_leads(client, ticker, name, leads)

    moves = moves or {}
    judged = _judge_relevance(client, ticker, name, moves, leads)
    result, status = _apply_relevance(leads, judged)
    if result:
        logger.info("Web leads for %s via %s: %d kept", ticker, source, len(result))
    return [check_source(lead) for lead in result], status
