"""Market window selection, returns, benchmarks, and notable sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .market import BENCHMARKS, STOCKS, fx_at, load_prices

NOTABLE_RULE = "abs_daily_top3_2pp"
NOTABLE_MIN_ABS = 0.02
NOTABLE_MAX_COUNT = 3


@dataclass(frozen=True)
class ResolvedWindow:
    ticker: str
    name: str
    requested: Literal["session", "period"]
    applied: Literal["session", "period"]
    reason: str | None
    start_close_date: str
    end_close_date: str
    start_adj_close: float
    end_adj_close: float
    bounds: dict[str, str] | None
    measured_sessions: tuple[str, ...]


def _rows(ticker: str):
    prices = load_prices()
    if ticker not in prices:
        raise ValueError("Action inconnue.")
    return prices[ticker]


def _session_dates(ticker: str) -> tuple[str, ...]:
    return tuple(row.date for row in _rows(ticker))


def resolve_window(
    ticker: str,
    *,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ResolvedWindow:
    if ticker not in STOCKS:
        raise ValueError("Action inconnue.")
    dates = _session_dates(ticker)
    if not dates:
        raise ValueError("Séance absente de la série du titre.")

    if date and (start_date or end_date):
        raise ValueError("Utilise date ou start_date et end_date, pas les deux.")
    if (start_date and not end_date) or (end_date and not start_date):
        raise ValueError("Fournis start_date et end_date ensemble.")

    prices = {row.date: row.adj_close for row in _rows(ticker)}

    if start_date and end_date:
        if start_date > end_date:
            raise ValueError("start_date ne peut pas être postérieure à end_date.")
        if start_date not in dates or end_date not in dates:
            raise ValueError("Séance absente de la série du titre.")
        start_idx = dates.index(start_date)
        if start_date == end_date:
            if start_idx == 0:
                raise ValueError("Sélectionne une séance avec une clôture précédente.")
            prev = dates[start_idx - 1]
            return ResolvedWindow(
                ticker=ticker,
                name=STOCKS[ticker],
                requested="period",
                applied="session",
                reason="same_session",
                start_close_date=prev,
                end_close_date=end_date,
                start_adj_close=prices[prev],
                end_adj_close=prices[end_date],
                bounds={"start_date": start_date, "end_date": end_date},
                measured_sessions=(end_date,),
            )
        measured = tuple(d for d in dates if start_date < d <= end_date)
        return ResolvedWindow(
            ticker=ticker,
            name=STOCKS[ticker],
            requested="period",
            applied="period",
            reason=None,
            start_close_date=start_date,
            end_close_date=end_date,
            start_adj_close=prices[start_date],
            end_adj_close=prices[end_date],
            bounds={"start_date": start_date, "end_date": end_date},
            measured_sessions=measured,
        )

    if not date:
        raise ValueError("Sélectionne une date valide.")
    if date not in dates:
        raise ValueError("Séance absente de la série du titre.")
    idx = dates.index(date)
    if idx == 0:
        raise ValueError("Sélectionne une séance avec une clôture précédente.")
    prev = dates[idx - 1]
    return ResolvedWindow(
        ticker=ticker,
        name=STOCKS[ticker],
        requested="session",
        applied="session",
        reason=None,
        start_close_date=prev,
        end_close_date=date,
        start_adj_close=prices[prev],
        end_adj_close=prices[date],
        bounds=None,
        measured_sessions=(date,),
    )


def _benchmark(symbol: str, start: str, end: str, usd_return: float) -> dict:
    prices = load_prices()
    closes = {row.date: row.adj_close for row in prices[symbol]}
    missing = [d for d in (start, end) if d not in closes]
    base = {
        "name": BENCHMARKS[symbol],
        "start_close_date": start,
        "end_close_date": end,
    }
    if missing:
        return {
            **base,
            "status": "missing",
            "missing_dates": missing,
            "return": None,
            "gap": None,
            "gap_pp": None,
        }
    bench_return = closes[end] / closes[start] - 1
    gap = usd_return - bench_return
    return {
        **base,
        "status": "ok",
        "return": bench_return,
        "gap": gap,
        "gap_pp": gap * 100,
    }


def window_returns(window: ResolvedWindow) -> dict:
    usd = window.end_adj_close / window.start_adj_close - 1
    old_day, old_rate = fx_at(window.start_close_date)
    new_day, new_rate = fx_at(window.end_close_date)
    fx_return = new_rate / old_rate - 1 if old_rate and new_rate else None
    cad_return = (1 + usd) * (1 + fx_return) - 1 if fx_return is not None else None
    benchmarks = {
        symbol: _benchmark(symbol, window.start_close_date, window.end_close_date, usd)
        for symbol in BENCHMARKS
    }
    return {
        "usd_return": usd,
        "fx_return": fx_return,
        "cad_return": cad_return,
        "fx_dates": [old_day, new_day],
        "fx_rates": [old_rate, new_rate] if old_rate and new_rate else [None, None],
        "benchmarks": benchmarks,
    }


def notable_sessions(window: ResolvedWindow) -> dict:
    if window.applied == "session":
        daily = window.end_adj_close / window.start_adj_close - 1
        return {
            "rule": NOTABLE_RULE,
            "concentration": "single_session",
            "top_share": 1.0,
            "notable_share": 1.0,
            "sessions": [
                {
                    "date": window.end_close_date,
                    "previous_date": window.start_close_date,
                    "daily_return": daily,
                }
            ],
        }

    rows = _rows(window.ticker)
    by_date = {row.date: row.adj_close for row in rows}
    contributors = []
    for session in window.measured_sessions:
        idx = next(i for i, row in enumerate(rows) if row.date == session)
        prev_date = rows[idx - 1].date
        daily = by_date[session] / by_date[prev_date] - 1
        contributors.append((abs(daily), session, prev_date, daily))
    if not contributors:
        return {
            "rule": NOTABLE_RULE,
            "concentration": "spread",
            "top_share": 0.0,
            "notable_share": 0.0,
            "sessions": [],
        }
    total_abs = sum(abs_ret for abs_ret, *_ in contributors)
    contributors.sort(key=lambda item: -item[0])
    candidates = [item for item in contributors if item[0] >= NOTABLE_MIN_ABS]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    picked = candidates[:NOTABLE_MAX_COUNT]
    top_share = contributors[0][0] / total_abs if total_abs else 0.0
    notable_share = sum(item[0] for item in picked) / total_abs if total_abs else 0.0
    if not picked:
        concentration = "spread"
    elif top_share >= 0.50:
        concentration = "concentrated"
    elif notable_share >= 0.60:
        concentration = "clustered"
    else:
        concentration = "spread"
    return {
        "rule": NOTABLE_RULE,
        "concentration": concentration,
        "top_share": top_share,
        "notable_share": notable_share,
        "sessions": [
            {"date": session, "previous_date": prev_date, "daily_return": daily}
            for _, session, prev_date, daily in picked
        ],
    }


def max_drawdown_cad(window: ResolvedWindow, position_cad: float) -> dict | None:
    if window.applied != "period":
        return None
    rows = _rows(window.ticker)
    by_date = {row.date: row.adj_close for row in rows}
    base = by_date[window.start_close_date]
    peak_value = position_cad
    peak_date = window.start_close_date
    max_dd = 0.0
    trough_date = window.start_close_date
    peak_at_trough = window.start_close_date
    for session in window.measured_sessions:
        value = position_cad * (by_date[session] / base)
        if value > peak_value:
            peak_value = value
            peak_date = session
        dd = value / peak_value - 1
        if dd < max_dd:
            max_dd = dd
            trough_date = session
            peak_at_trough = peak_date
    return {
        "peak_date": peak_at_trough,
        "trough_date": trough_date,
        "max_drawdown": max_dd,
        "position_at_trough_cad": position_cad * (by_date[trough_date] / base),
    }


def movement_legacy(window: ResolvedWindow, returns: dict) -> dict:
    """Shape expected by existing API consumers for a session click."""
    benchmarks = {}
    for symbol, bench in returns["benchmarks"].items():
        if bench["status"] == "ok":
            benchmarks[symbol] = {"name": bench["name"], "return": bench["return"], "gap": bench["gap"]}
        else:
            benchmarks[symbol] = {"name": bench["name"], "return": None, "gap": None}
    return {
        "ticker": window.ticker,
        "date": window.end_close_date,
        "previous_date": window.start_close_date,
        "usd_return": returns["usd_return"],
        "fx_return": returns["fx_return"],
        "cad_return": returns["cad_return"],
        "fx_dates": returns["fx_dates"],
        "benchmarks": benchmarks,
    }