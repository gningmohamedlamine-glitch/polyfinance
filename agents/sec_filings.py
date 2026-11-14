"""Read timestamped current reports from the SEC submissions API."""
import json
from datetime import datetime
from functools import lru_cache
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .events import session_window

CIKS = {"NVDA": 1045810, "AAPL": 320193, "MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724, "TSLA": 1318605}


@lru_cache(maxsize=12)
def submissions(ticker):
    request = Request(f"https://data.sec.gov/submissions/CIK{CIKS[ticker]:010d}.json",
                      headers={"User-Agent": "AlphaForge Datathon, Polytechnique Montreal (polyfinances.ca)"})
    with urlopen(request, timeout=4) as response:
        return json.load(response)["filings"]["recent"]


def search_filings(ticker, previous, sessions):
    try:
        filings = submissions(ticker)
    except (URLError, TimeoutError, ValueError, KeyError):
        return [], "unavailable"
    windows = [(session, *session_window(previous[session], session)) for session in sessions if session in previous]
    results = []
    for form, accession, accepted in zip(filings["form"], filings["accessionNumber"], filings["acceptanceDateTime"]):
        if form != "8-K" or not accepted:
            continue
        hour = datetime.fromisoformat(accepted).astimezone(ZoneInfo("America/New_York")).isoformat(timespec="seconds")[:19]
        for session, start, end in windows:
            if start + ":00" < hour <= end + ":00":
                url = f"https://www.sec.gov/Archives/edgar/data/{CIKS[ticker]}/{accession.replace('-', '')}/{accession}-index.html"
                results.append(dict(ticker=ticker, session=session, time_et=hour, publisher="SEC EDGAR",
                                    title=f"{ticker} · Dépôt 8-K", url=url,
                                    summary="Déclaration d’événement déposée auprès de la SEC."))
                break
    return results[:8], "searched"
