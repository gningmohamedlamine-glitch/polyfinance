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


def build_tool_context(window: ResolvedWindow, notify, search_catalog: bool = True) -> ToolContext:
    """Faits obligatoires calculés en Python. En mode agent, le catalogue devient un outil du modèle."""
    notify("event", "compare_market", "running")
    returns = window_returns(window)
    notify("event", "compare_market", "done")

    if window.applied == "period":
        notify("event", "find_notable_sessions", "running")
    notable = notable_sessions(window)
    if window.applied == "period":
        notify("event", "find_notable_sessions", "done", len(notable["sessions"]))

    price_rows = stock_history(window.ticker)
    if search_catalog:
        notify("event", "search_publications", "running")
        publications = search_publications(window.ticker, window.measured_sessions, price_rows)
        notify("event", "search_publications", "done", len(publications))
    else:
        publications = []
    coverage = publication_coverage(window.measured_sessions, publications)
    return ToolContext(window, returns, notable, publications, coverage, price_rows)
