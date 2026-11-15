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
# FNB sectoriels téléchargés via yfinance (data/sector_etfs_daily.csv, facultatif).
SECTORS = {"XLK": "Technologie (XLK)", "XLE": "Énergie (XLE)", "XLF": "Finance (XLF)", "XLV": "Santé (XLV)"}
# Secteur de comparaison par titre ; None quand aucun FNB sectoriel adapté n'est disponible.
STOCK_SECTOR = {"NVDA": "XLK", "AAPL": "XLK", "MSFT": "XLK", "GOOGL": None, "AMZN": None, "TSLA": None}
# FNB filtré ESG du jeu de départ : référence de comparaison pour le profil de Mateo.
ESG_REFERENCE = {"ESGV": "Vanguard ESG U.S. Stock ETF"}
CRYPTO_REFERENCE = {'BTC-USD': 'Bitcoin', 'ETH-USD': 'Ethereum'}
REFERENCE_NAMES = BENCHMARKS | SECTORS | ESG_REFERENCE


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
    tables = {ticker: {} for ticker in STOCKS | BENCHMARKS | SECTORS | ESG_REFERENCE | CRYPTO_REFERENCE}
    files = [DATA / "prices_daily.csv"]
    if (DATA / "sector_etfs_daily.csv").exists():
        files.append(DATA / "sector_etfs_daily.csv")
    for path in files:
        _read_prices(path, tables)
    # Un FNB sectoriel absent (fichier facultatif) est retiré plutôt que laissé vide.
    return {
        ticker: tuple(table[key] for key in sorted(table))
        for ticker, table in tables.items()
        if table or ticker not in (SECTORS | CRYPTO_REFERENCE)
    }


def _read_prices(path, tables):
    with path.open(newline="", encoding="utf-8-sig") as source:
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
    from .window import movement_legacy, resolve_window, window_returns

    window = resolve_window(ticker, date=session)
    returns = window_returns(window)
    return movement_legacy(window, returns)
