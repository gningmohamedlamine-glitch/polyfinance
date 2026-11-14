"""Python tools invoked by market agents."""

from __future__ import annotations

from dataclasses import dataclass

from markets.market import load_prices, stock_history
from markets.window import ResolvedWindow, notable_sessions, window_returns

from .events import publication_coverage, search_publications


MAX_TOOL_CALLS = 6

EVENT_TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "compare_market",
            "description": "Compare le rendement USD du titre avec SPY et QQQ entre deux clôtures ajustées.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "start_close_date": {"type": "string"},
                        "end_close_date": {"type": "string"},
                    },
                    "required": ["ticker", "start_close_date", "end_close_date"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "find_notable_sessions",
            "description": "Repère jusqu’à trois séances marquantes sur une période.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "start_close_date": {"type": "string"},
                        "end_close_date": {"type": "string"},
                    },
                    "required": ["ticker", "start_close_date", "end_close_date"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "search_publications",
            "description": "Cherche des publications vérifiées pour une liste de séances.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "sessions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["ticker", "sessions"],
                }
            },
        }
    },
]

IMPACT_TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "position_value_cad",
            "description": "Calcule la variation et la valeur finale d’une position en CAD.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "position_cad": {"type": "number"},
                        "cad_return": {"type": "number"},
                        "withdrawal_cad": {"type": "number"},
                    },
                    "required": ["position_cad", "cad_return"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "max_drawdown_cad",
            "description": "Calcule la baisse maximale d’une position en CAD sur une période.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "start_close_date": {"type": "string"},
                        "end_close_date": {"type": "string"},
                        "position_cad": {"type": "number"},
                    },
                    "required": ["ticker", "start_close_date", "end_close_date", "position_cad"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "direct_weight",
            "description": "Calcule les poids directs avant et après un achat simulé.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "position_cad": {"type": "number"},
                        "purchase_cad": {"type": "number"},
                        "portfolio_cad": {"type": "number"},
                    },
                    "required": ["position_cad", "purchase_cad", "portfolio_cad"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "exclusion_evidence",
            "description": "Liste les preuves ESG disponibles pour Mateo.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
]


@dataclass
class ToolContext:
    window: ResolvedWindow
    returns: dict
    notable: dict
    publications: list[dict]
    coverage: dict
    price_rows: list[dict]


def build_tool_context(window: ResolvedWindow) -> ToolContext:
    returns = window_returns(window)
    notable = notable_sessions(window)
    price_rows = stock_history(window.ticker)
    publications = search_publications(window.ticker, window.measured_sessions, price_rows)
    coverage = publication_coverage(window.measured_sessions, publications)
    return ToolContext(window, returns, notable, publications, coverage, price_rows)


def validate_event_args(name: str, args: dict, window: ResolvedWindow) -> str | None:
    if name == "compare_market":
        if args.get("ticker") != window.ticker:
            return "ticker invalide"
        if args.get("start_close_date") != window.start_close_date or args.get("end_close_date") != window.end_close_date:
            return "fenêtre invalide"
        return None
    if name == "find_notable_sessions":
        if args.get("ticker") != window.ticker:
            return "ticker invalide"
        if args.get("start_close_date") != window.start_close_date or args.get("end_close_date") != window.end_close_date:
            return "fenêtre invalide"
        return None
    if name == "search_publications":
        if args.get("ticker") != window.ticker:
            return "ticker invalide"
        sessions = args.get("sessions") or []
        allowed = set(window.measured_sessions)
        if not isinstance(sessions, list) or any(session not in allowed for session in sessions):
            return "sessions invalides"
        return None
    return "outil inconnu"


def run_event_tool(name: str, context: ToolContext, args: dict | None = None) -> dict:
    if name == "compare_market":
        return {
            "returns": context.returns,
            "benchmarks": context.returns["benchmarks"],
        }
    if name == "find_notable_sessions":
        return context.notable
    if name == "search_publications":
        sessions = (args or {}).get("sessions", list(context.window.measured_sessions))
        publications = search_publications(context.window.ticker, sessions, context.price_rows)
        return {
            "publications": publications,
            "coverage": publication_coverage(sessions, publications),
        }
    raise ValueError("outil inconnu")


def required_event_tools(window: ResolvedWindow) -> list[str]:
    tools = ["compare_market", "search_publications"]
    if window.applied == "period":
        tools.insert(1, "find_notable_sessions")
    return tools