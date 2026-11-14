"""Gather deterministic market evidence for the analysis pipeline."""

from dataclasses import dataclass

from markets.market import stock_history
from markets.window import ResolvedWindow, notable_sessions, window_returns

from .events import publication_coverage, search_publications


@dataclass
class ToolContext:
    window: ResolvedWindow
    returns: dict
    notable: dict
    publications: list[dict]
    coverage: dict
    price_rows: list[dict]


def build_tool_context(window: ResolvedWindow, notify) -> ToolContext:
    notify("event", "compare_market", "running")
    returns = window_returns(window)
    notify("event", "compare_market", "done")

    if window.applied == "period":
        notify("event", "find_notable_sessions", "running")
    notable = notable_sessions(window)
    if window.applied == "period":
        notify("event", "find_notable_sessions", "done", len(notable["sessions"]))

    notify("event", "search_publications", "running")
    price_rows = stock_history(window.ticker)
    publications = search_publications(window.ticker, window.measured_sessions, price_rows)
    coverage = publication_coverage(window.measured_sessions, publications)
    notify("event", "search_publications", "done", len(publications))
    return ToolContext(window, returns, notable, publications, coverage, price_rows)
