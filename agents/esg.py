"""Vérification ESG du profil de Mateo : signaler les points d'attention, jamais certifier.

Le jeu de données ne contient ni note ESG ni émissions. L'outil réunit donc trois éléments publics
et vérifiables, et déclare explicitement ce qui manque :
1. le secteur GICS du titre (assets_universe.csv), signalé s'il est souvent exclu des filtres ESG ;
2. les controverses datées : publications du dossier et, si la recherche web est activée, pistes web
   des 12 mois précédant la séance (jamais après : aucune information future) ;
3. la comparaison du titre avec ESGV, le FNB filtré ESG du jeu de départ (rendement, volatilité, baisse).
Si data/esgv_holdings.csv existe (liste publiée par Vanguard), l'appartenance au filtre est aussi vérifiée.
"""

import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError

from markets.window import period_return, risk_indicators

from .model_text import public_text

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


def esgv_membership(ticker: str) -> dict:
    """Appartenance à ESGV si la liste publiée par Vanguard a été ajoutée au dépôt."""
    path = DATA / "esgv_holdings.csv"
    if not path.exists():
        return {"status": "unavailable"}
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    tickers = {(row.get("ticker") or row.get("Ticker") or "").strip().upper() for row in rows}
    as_of = next((row.get("as_of") for row in rows if row.get("as_of")), None)
    return {"status": "ok", "member": ticker.upper() in tickers, "as_of": as_of, "holdings": len(tickers)}


def matching_publications(dossier: dict) -> list[dict]:
    """Publications du dossier (sources datées) et pistes web dont le texte évoque une controverse."""
    found = []
    sources = [(item, "source datée") for item in dossier.get("publications", [])]
    sources += [(item, "piste web non vérifiée") for item in dossier.get("coverage", {}).get("web_leads", [])]
    for item, kind in sources:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        terms = sorted({term.strip() for term in CONTROVERSY_TERMS if term in text})
        if terms:
            found.append({"title": item.get("title"), "url": item.get("url"), "kind": kind, "terms": terms,
                          "published_date": item.get("published_date") or item.get("published_at")})
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
        "(one short French sentence). Copy each exact cited source URL. If none, return []."
    )
    try:
        response = client.converse(
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
                      else None, "summary": row["summary"][:400], "kind": "piste web non vérifiée"})
        if len(leads) == 4:
            break
    return leads, "found" if leads else "none_found"


def esg_screen(dossier: dict, client=None) -> dict:
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
    controversies = matching_publications(dossier)
    web_status = "disabled"
    if client is not None:
        web, web_status = web_controversies(client, ticker, selection.get("name", ticker), end_date)
        controversies += web
    membership = esgv_membership(ticker)

    missing = ["Aucune note ESG ni donnée d’émissions dans le jeu de données."]
    if membership["status"] != "ok":
        missing.append("Liste des titres d’ESGV non fournie : l’appartenance au filtre ESG n’est pas vérifiée.")
    if web_status != "found" and not controversies:
        missing.append("Aucune controverse datée trouvée dans les sources consultées : absence de preuve, "
                       "pas preuve d’absence.")
    attention = []
    if sector_flag:
        attention.append(f"Secteur {sector} : {sector_flag}.")
    if membership.get("status") == "ok" and not membership["member"]:
        attention.append("Le titre ne figure pas dans la liste publiée d’ESGV.")
    if controversies:
        attention.append(f"{len(controversies)} controverse(s) ou piste(s) à examiner, non vérifiée(s) pour les pistes web.")
    return {
        "ticker": ticker,
        "sector": sector,
        "sector_flag": sector_flag,
        "membership": membership,
        "comparison": comparison,
        "controversies": controversies,
        "web_status": web_status,
        "attention": attention,
        "missing": missing,
        # Jamais « conforme » : au mieux, aucun point d'attention relevé avec les données disponibles.
        "conclusion": "points_attention" if attention else "insuffisant",
        "notice": "Vérification indicative à partir de données publiques ; ce n’est pas une notation ESG.",
    }
