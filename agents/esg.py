"""Vérification ESG du profil de Mateo : signaler les points d'attention, jamais certifier.

Le jeu de données ne contient pas de note ESG indépendante. L'outil réunit des éléments publics
et vérifiables, et déclare explicitement ce qui manque :
1. le secteur GICS du titre (assets_universe.csv), signalé s'il est souvent exclu des filtres ESG ;
2. les controverses datées : publications du dossier et, si la recherche web est activée, pistes web
   des 12 mois précédant la séance (jamais après : aucune information future) ;
3. la comparaison du titre avec ESGV, le FNB filtré ESG du jeu de départ (rendement, volatilité, baisse).
Les émissions connues figurent dans esg_emissions.csv. Si esgv_holdings.csv existe,
l'appartenance est limitée aux relevés datés et connus lors de la séance.
"""

import csv
import json
import math
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError

from markets.window import period_return, risk_indicators

from .runtime import converse
from .model_text import public_text
from .source_quality import is_official, check_source
from .temporal import availability

DATA = Path(__file__).resolve().parents[1] / "data"
ESG_REFERENCE = "ESGV"
# Secteurs fréquemment exclus ou sous-pondérés par les filtres ESG grand public (hypothèse documentée).
SENSITIVE_SECTORS = {"Energy": "énergie fossile, souvent exclue des filtres ESG"}
CONTROVERSY_TERMS = (
    "controvers", "poursuite", "lawsuit", "enquête", "investigation", "antitrust", "amende", "fine ",
    "pénalité", "penalty", "pollution", "déversement", "spill", "émissions", "emissions", "travail forcé",
    "forced labor", "discrimination", "harcèlement", "harassment", "rappel", "recall", "fuite de données",
    "data breach", "corruption", "fraude", "fraud", "sanction",
)
WEB_MODEL = "us.amazon.nova-2-lite-v1:0"


def asset_sector(ticker: str) -> str | None:
    if not (DATA / "assets_universe.csv").exists():
        return None
    with (DATA / "assets_universe.csv").open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            if row["ticker"].strip().upper() == ticker.upper():
                return row["sector"].strip() or None
    return None


def esgv_membership(ticker: str, end_date: str) -> dict:
    """Only snapshots known at the selected date; partial lists cannot prove absence."""
    path = DATA / "esgv_holdings.csv"
    if not path.exists():
        return {"status": "unavailable", "member": None}
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    eligible = []
    for row in rows:
        try:
            stamp = date.fromisoformat(row.get("as_of", ""))
            published = date.fromisoformat(row.get("published_date", ""))
        except ValueError:
            continue
        if stamp <= published < date.fromisoformat(end_date) and is_official(row.get("url", "")):
            eligible.append(row)
    if not eligible:
        return {"status": "unavailable", "member": None}
    latest = max((row['as_of'], row['published_date'], row['url']) for row in eligible)
    rows = [row for row in eligible if (row['as_of'], row['published_date'], row['url']) == latest]
    tickers = {row.get('ticker', '').strip().upper() for row in rows}
    complete = all(row.get('snapshot_complete', '').lower() == 'true' for row in rows)
    member = True if ticker.upper() in tickers else False if complete else None
    age = (date.fromisoformat(end_date) - date.fromisoformat(latest[0])).days
    return {'status': 'stale' if age > 120 else 'ok' if member is not None else 'partial',
            'member': member, 'as_of': latest[0], 'published_date': latest[1], 'url': latest[2],
            'holdings': len(tickers), 'snapshot_complete': complete, 'age_days': age,
            'notice': 'Appartenance au portefeuille à la date du relevé, sans certification ESG.'}


def emission_history(ticker: str, end_date: str) -> list[dict]:
    """Retain the latest known vintage per period/scope, never backdate a restatement."""
    path = DATA / 'esg_emissions.csv'
    if not path.exists():
        return []
    known = {}
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            try:
                period = date.fromisoformat(row['period_end'])
                published = date.fromisoformat(row['published_date'])
                value = float(row['value'])
            except (KeyError, ValueError):
                continue
            if (row.get('ticker') != ticker or not period <= published < date.fromisoformat(end_date)
                    or not is_official(row.get('url', '')) or not math.isfinite(value) or value < 0
                    or row.get('unit') != 'tCO2e' or not row.get('scope') or not row.get('methodology')):
                continue
            key = (row['period_end'], row['scope'], row['methodology'], row['metric'])
            if key not in known or row['published_date'] > known[key]['published_date']:
                known[key] = {**row, 'value': value, 'source_origin': 'official',
                              'evidence_type': 'company_disclosure', 'excerpt_status': 'not_checked'}
    return sorted(known.values(), key=lambda row: row['period_end'])[-20:]


def catalog_publications(ticker: str, end_date: str) -> list[dict]:
    """Événements publiés dans les 365 jours précédents ; date sans heure utilisable le lendemain."""
    path = DATA / "esg_publications.csv"
    if not path.exists():
        return []
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=365)
    found = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            try:
                published = date.fromisoformat(row["published_date"])
            except (ValueError, KeyError):
                continue
            if row.get("ticker") == ticker and start <= published < end:
                found.append({**row, "kind": "publication officielle cataloguée",
                              "source_origin": "official" if is_official(row["url"]) else "other",
                              "excerpt_status": "not_checked"})
    return found


def matching_publications(dossier: dict) -> list[dict]:
    """Publications du dossier (sources datées) et pistes web dont le texte évoque une controverse."""
    found = []
    sources = [(item, "source datée") for item in dossier.get("publications", [])]
    sources += [(item, "piste web non vérifiée") for item in dossier.get("coverage", {}).get("web_leads", [])]
    for item, kind in sources:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        terms = sorted({term.strip() for term in CONTROVERSY_TERMS if term in text})
        if terms:
            found.append({**item, "evidence_type": "potential_controversy" if any(
                term not in {"émissions", "emissions"} for term in terms) else "company_disclosure", "title": item.get("title"), "url": item.get("url"), "kind": kind, "terms": terms,
                          "published_date": item.get("published_date") or (item.get("time_et") or item.get("published_at") or "")[:10]})
    return found


def web_controversies(client, ticker: str, name: str, end_date: str) -> tuple[list[dict], str]:
    """Pistes web datées sur les controverses ESG, publiées dans les 12 mois avant end_date."""
    if os.getenv("MARKET_WEB_SEARCH") != "1":
        return [], "disabled"
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=365)
    prompt = (
        f"Use web search to find environmental, social or governance controversies involving {name} ({ticker}) "
        f"published between {start.isoformat()} and {end.isoformat()} inclusive: lawsuits, regulatory fines or "
        "investigations, pollution, labor or human-rights issues, data breaches, governance scandals. "
        "Prefer regulators, court records and reputable news outlets. Ignore anything published after "
        f"{end.isoformat()}. Find up to four concrete reports. Return only a JSON array of objects with url, "
        "title, published_date (YYYY-MM-DD), topic (environnement, social or gouvernance) and summary "
        "(one short French sentence), original_excerpt (an exact original-language quote, not a paraphrase). Copy each exact cited source URL. If none, return []."
    )
    try:
        response = converse(client,
            modelId=WEB_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={"tools": [{"systemTool": {"name": "nova_grounding"}}]},
            inferenceConfig={"maxTokens": 1200},
        )
    except (BotoCoreError, ClientError):
        return [], "unavailable"
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    cited = {c.get("location", {}).get("web", {}).get("url")
             for block in blocks for c in block.get("citationsContent", {}).get("citations", [])}
    text_blocks = [{"text": f["text"]} for block in blocks
                   for f in ([block] if "text" in block else block.get("citationsContent", {}).get("content", []))
                   if "text" in f]
    answer = public_text({"content": text_blocks}, separator="")
    try:
        rows = json.loads(answer[answer.index("["):answer.rindex("]") + 1])
    except (ValueError, TypeError):
        return [], "invalid_response"
    leads = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k]
                                                for k in ("url", "title", "published_date", "summary")):
            continue
        try:
            published = date.fromisoformat(row["published_date"])
        except ValueError:
            continue
        if row["url"] not in cited or urlsplit(row["url"]).scheme != "https" or not start <= published <= end:
            continue
        leads.append({"url": row["url"], "title": row["title"][:300], "published_date": published.isoformat(),
                      "topic": row.get("topic") if row.get("topic") in ("environnement", "social", "gouvernance")
                      else None, "summary": row["summary"][:400], "kind": "piste web non vérifiée", "evidence_type": "potential_controversy",
                      "original_excerpt": row.get("original_excerpt", "")})
        if len(leads) == 4:
            break
    return [check_source(lead) for lead in leads], "found" if leads else "none_found"


def esg_screen(dossier: dict, client=None, *, web_result=None) -> dict:
    selection = dossier["selection"]
    ticker, end_date = selection["ticker"], selection["end_close_date"]
    sector = asset_sector(ticker)
    sector_flag = SENSITIVE_SECTORS.get(sector or "")

    def snapshot(symbol):
        risk = risk_indicators(symbol, end_date)
        if risk.get("status") != "ok":
            return None
        return {"symbol": symbol, "return_12m": period_return(symbol, end_date),
                "annual_volatility": risk["annual_volatility"], "max_drawdown": risk["max_drawdown"],
                "start_date": risk["start_date"], "end_date": risk["end_date"]}

    comparison = {"stock": snapshot(ticker), "reference": snapshot(ESG_REFERENCE)}
    controversies = catalog_publications(ticker, end_date) + matching_publications(dossier)
    web_status = "disabled"
    if web_result is not None:
        web, web_status = web_result
        controversies += web
    elif client is not None:
        web, web_status = web_controversies(client, ticker, selection.get("name", ticker), end_date)
        controversies += web
    # Dédupliquer et appliquer la même fenêtre à toutes les origines.
    start = (date.fromisoformat(end_date) - timedelta(days=365)).isoformat()
    controversies = list({item["url"]: item for item in reversed(controversies)
                          if item.get("url") and start <= (item.get("published_date") or "") <= end_date}.values())
    controversies = [{**item, **availability(item, end_date)} for item in controversies]
    controversies = [item for item in controversies if item["eligible_for_explanation"]]
    disclosures = [item for item in controversies if item.get("evidence_type") == "company_disclosure"]
    controversies = [item for item in controversies if item.get("evidence_type") != "company_disclosure"]
    emissions = emission_history(ticker, end_date)
    membership = esgv_membership(ticker, end_date)

    missing = ["Aucune notation ESG globale indépendante dans les données."]
    if not emissions:
        missing.append("Aucune série d’émissions connue à la date sélectionnée pour ce titre.")
    else:
        missing.append("Émissions déclarées par l’entreprise : couverture limitée aux périodes et périmètres cités.")
    if membership["status"] != "ok":
        missing.append("Composition historique d’ESGV indisponible à cette date : appartenance non vérifiée.")
    if web_status != "found" and not controversies:
        missing.append("Aucune controverse datée trouvée dans les sources consultées : absence de preuve, "
                       "pas preuve d’absence.")
    attention = []
    if sector_flag:
        attention.append(f"Secteur {sector} : {sector_flag}.")
    if membership.get("status") == "ok" and membership["member"] is False:
        attention.append("Le titre ne figure pas dans la liste publiée d’ESGV.")
    if controversies:
        attention.append(f"{len(controversies)} signalement(s) réglementaire(s) ou piste(s) de controverse à examiner. " + " ".join(item.get("summary") or item["title"] for item in controversies[:3]))
    return {
        "ticker": ticker,
        "sector": sector,
        "sector_flag": sector_flag,
        "membership": membership,
        "comparison": comparison,
        "controversies": controversies,
        "disclosures": disclosures,
        "emissions": emissions,
        "web_status": web_status,
        "attention": attention,
        "missing": missing,
        # Jamais « conforme » : au mieux, aucun point d'attention relevé avec les données disponibles.
        "conclusion": "points_attention" if attention else "insuffisant",
        "notice": "Vérification indicative à partir de données publiques ; ce n’est pas une notation ESG.",
    }
