"""Read and validate the input CSVs once per server process."""

import csv
import math
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
STOCKS = {
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "TSLA": "Tesla",
}
BENCHMARKS = {"SPY": "S&P 500", "QQQ": "Nasdaq-100"}


@dataclass(frozen=True)
class Price:
    date: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


@lru_cache(maxsize=1)
def load_prices():
    tables = {ticker: {} for ticker in STOCKS | BENCHMARKS}
    with (DATA / "prices_daily.csv").open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            ticker = row["ticker"].strip().upper()
            if ticker not in tables or row["currency"].strip().upper() != "USD":
                continue
            try:
                session = date.fromisoformat(row["date"]).isoformat()
                values = [float(row[field]) for field in ("open", "high", "low", "close", "adj_close")]
                volume = int(row["volume"])
            except (ValueError, TypeError):
                continue
            opening, high, low, close, adjusted = values
            if not all(math.isfinite(value) and value > 0 for value in values):
                continue
            if volume < 0 or not low <= min(opening, close) <= max(opening, close) <= high:
                continue
            price = Price(session, opening, high, low, close, adjusted, volume)
            previous = tables[ticker].setdefault(session, price)
            if previous != price:
                raise ValueError(f"Prix contradictoires pour {ticker} le {session}")
    return {ticker: tuple(table[key] for key in sorted(table)) for ticker, table in tables.items()}


@lru_cache(maxsize=1)
def load_fx():
    rates = {}
    with (DATA / "fx_usdcad_daily.csv").open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            try:
                day = date.fromisoformat(row["date"]).isoformat()
                rate = float(row["usdcad"])
            except (ValueError, TypeError):
                continue
            if math.isfinite(rate) and rate > 0:
                rates[day] = rate
    return sorted(rates), rates


def fx_at(session):
    dates, rates = load_fx()
    index = bisect_right(dates, session) - 1
    return (dates[index], rates[dates[index]]) if index >= 0 else (None, None)


def stock_history(ticker):
    return [asdict(row) for row in load_prices()[ticker]]


def movement(ticker, session):
    prices = load_prices()
    rows = prices[ticker]
    index = next((i for i, row in enumerate(rows) if row.date == session), 0)
    if index == 0:
        raise ValueError("Sélectionne une séance avec une clôture précédente.")
    previous, current = rows[index - 1:index + 1]
    usd = current.adj_close / previous.adj_close - 1
    benchmarks = {}
    for symbol, name in BENCHMARKS.items():
        closes = {row.date: row.adj_close for row in prices[symbol]}
        if previous.date in closes and session in closes:
            change = closes[session] / closes[previous.date] - 1
            benchmarks[symbol] = {"name": name, "return": change, "gap": usd - change}
    old_day, old_rate = fx_at(previous.date)
    new_day, new_rate = fx_at(session)
    fx = new_rate / old_rate - 1 if old_rate and new_rate else None

    return {
        "ticker": ticker, "date": session, "previous_date": previous.date,
        "usd_return": usd, "fx_return": fx,
        "cad_return": (1 + usd) * (1 + fx) - 1 if fx is not None else None,
        "fx_dates": [old_day, new_day], "benchmarks": benchmarks,
    }
