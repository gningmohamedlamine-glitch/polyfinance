"""Look up contemporaneous, curated public sources in a read-only CSV."""

import csv
from functools import lru_cache
from pathlib import Path

EVENTS = Path(__file__).resolve().parents[1] / "data" / "market_events.csv"


@lru_cache(maxsize=1)
def _read_catalog(_fingerprint):
    with EVENTS.open(newline="", encoding="utf-8-sig") as source:
        return tuple(csv.DictReader(source))


def catalog_fingerprint():
    try:
        stat = EVENTS.stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}"
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
            row = {**event, "session": session}
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
