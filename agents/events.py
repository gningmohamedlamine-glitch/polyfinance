"""Look up contemporaneous, curated public sources in a read-only CSV."""

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

EVENTS = Path(__file__).resolve().parents[1] / "data" / "market_events.csv"
SOURCES = Path(__file__).resolve().parents[1] / "data" / "sources"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_excerpt(event: dict) -> str:
    """Garde-fou : l'extrait affiché existe-t-il mot pour mot dans la source enregistrée ?

    verified        l'extrait figure dans data/sources/<source_id>.txt
    mismatch        la source est enregistrée mais ne contient pas l'extrait
    source_missing  la source n'a pas encore été téléchargée (scripts/fetch_sources.py)
    no_excerpt      aucune citation déclarée dans le catalogue
    """
    excerpt = (event.get("excerpt") or "").strip()
    if not excerpt:
        return "no_excerpt"
    source_id = (event.get("source_id") or "").strip()
    path = SOURCES / f"{source_id}.txt"
    if not source_id or not path.exists():
        return "source_missing"
    return "verified" if _normalize(excerpt) in _normalize(path.read_text(encoding="utf-8")) else "mismatch"


@lru_cache(maxsize=1)
def _read_catalog(_fingerprint):
    with EVENTS.open(newline="", encoding="utf-8-sig") as source:
        return tuple(csv.DictReader(source))


def catalog_fingerprint():
    try:
        stat = EVENTS.stat()
        sources = max((f.stat().st_mtime_ns for f in SOURCES.glob("*.txt")), default=0)
        return f"{stat.st_size}:{stat.st_mtime_ns}:{sources}"
    except OSError:
        return "missing"


def session_window(previous_date, session):
    # The cutoff is 16:00 Eastern for the US sessions in the application.
    return previous_date + "T16:00", session + "T16:00"


def _matching_events(events, ticker, previous_date, session):
    start, end = session_window(previous_date, session)
    return [
        dict(event) for event in events
        if event["ticker"] in ("*", ticker) and start < event["time_et"] <= end
    ]


def find_events(ticker, previous_date, session):
    return _matching_events(_read_catalog(catalog_fingerprint()), ticker, previous_date, session)


def previous_session_dates(ticker, sessions, price_rows):
    dates = [row["date"] if isinstance(row, dict) else row.date for row in price_rows]
    index = {day: i for i, day in enumerate(dates)}
    mapping = {}
    for session in sessions:
        idx = index.get(session)
        if idx is None or idx == 0:
            continue
        mapping[session] = dates[idx - 1]
    return mapping


def search_publications(ticker, sessions, price_rows):
    events = _read_catalog(catalog_fingerprint())
    prev_map = previous_session_dates(ticker, sessions, price_rows)
    seen_urls = set()
    results = []
    for session in sessions:
        previous = prev_map.get(session)
        if not previous:
            continue
        for event in _matching_events(events, ticker, previous, session):
            url = event.get("url", "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            row = {**event, "session": session, "excerpt_status": verify_excerpt(event)}
            results.append(row)
    results.sort(key=lambda item: (item["session"], item["time_et"], item.get("url", "")))
    return results


def publication_coverage(sessions_measured, publications):
    with_evidence = sorted({row["session"] for row in publications})
    unexplained = [session for session in sessions_measured if session not in set(with_evidence)]
    return {
        "catalog": "data/market_events.csv",
        "sessions_measured": list(sessions_measured),
        "sessions_with_evidence": with_evidence,
        "sessions_unexplained": unexplained,
        "web_search": "out_of_scope",
    }
