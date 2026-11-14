"""Look up contemporaneous, curated public sources in a read-only CSV."""

import csv
from functools import lru_cache
from pathlib import Path

EVENTS = Path(__file__).resolve().parents[1] / "data" / "market_events.csv"


@lru_cache(maxsize=1)
def load_events():
    with EVENTS.open(newline="", encoding="utf-8-sig") as source:
        return tuple(csv.DictReader(source))


def find_events(ticker, previous_date, session):
    # The cutoff is 16:00 Eastern for the US sessions in the application.
    start, end = previous_date + "T16:00", session + "T16:00"
    return [
        dict(event) for event in load_events()
        if event["ticker"] in ("*", ticker) and start < event["time_et"] <= end
    ]
