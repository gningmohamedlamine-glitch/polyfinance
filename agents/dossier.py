"""Build alphaforge.market_dossier.v1 payloads."""

from __future__ import annotations

from .tools import ToolContext

SCHEMA = "alphaforge.market_dossier.v1"


def selection_payload(window) -> dict:
    payload = {
        "ticker": window.ticker,
        "name": window.name,
        "requested": window.requested,
        "applied": window.applied,
        "reason": window.reason,
        "start_close_date": window.start_close_date,
        "end_close_date": window.end_close_date,
        "start_adj_close": window.start_adj_close,
        "end_adj_close": window.end_adj_close,
    }
    if window.bounds:
        payload["bounds"] = window.bounds
    return payload


def build_dossier(
    context: ToolContext,
    *,
    synthesis_text: str,
    tools_executed: list[dict],
) -> dict:
    returns = context.returns
    return {
        "schema": SCHEMA,
        "selection": selection_payload(context.window),
        "returns": {
            "usd_return": returns["usd_return"],
            "fx_return": returns["fx_return"],
            "cad_return": returns["cad_return"],
            "fx_dates": returns["fx_dates"],
            "fx_rates": returns["fx_rates"],
            "market_model": returns.get("market_model"),
        },
        "benchmarks": returns["benchmarks"],
        "notable_sessions": context.notable,
        "publications": context.publications,
        "coverage": context.coverage,
        "synthesis": {
            "text": synthesis_text,
            "mode": "local",
            "mode_reason": None,
        },
        "limits": {
            "causality": "Un écart avec SPY ou QQQ ne prouve pas une cause.",
            "figures_source": "python",
            "verified_events_source": "market_events.csv et SEC EDGAR",
            "direction": "Une publication datée ne prouve pas le sens du mouvement : les attentes du marché ne sont pas dans les sources.",
            "excerpts": "Chaque extrait du catalogue est comparé au texte de la source enregistrée dans data/sources/.",
        },
        "tools_executed": tools_executed,
    }


def local_event_text(context: ToolContext) -> str:
    window = context.window
    usd = context.returns["usd_return"]
    parts = [
        f"{window.name} passe de {window.start_adj_close:.2f} USD à {window.end_adj_close:.2f} USD "
        f"entre le {window.start_close_date} et le {window.end_close_date}, soit {usd:+.2%} en USD."
    ]
    for symbol, bench in context.returns["benchmarks"].items():
        if bench.get("status") == "ok":
            parts.append(f"L’écart avec {bench['name']} est d’environ {bench['gap_pp']:.2f} points de pourcentage.")
        elif bench.get("status") == "missing":
            parts.append(f"{symbol} n’est pas disponible sur toute la fenêtre.")
    model = context.returns.get("market_model") or {}
    if model.get("status") == "ok":
        parts.append(
            f"Avec un bêta de {model['beta']:.2f} face à QQQ (estimé avant la fenêtre), le mouvement du marché "
            f"laissait attendre {model['expected_return']:+.2%} ; la part non expliquée par le marché est de "
            f"{model['residual_pp']:+.2f} points."
        )
    if context.publications:
        titles = "; ".join(source["title"] for source in context.publications[:2])
        parts.append(f"Publications datées : {titles}.")
        parts.append("Ces publications datent la séance, mais ne prouvent pas à elles seules le sens du mouvement.")
    else:
        parts.append("Aucune publication datée pour cette fenêtre. La cause du mouvement demeure indéterminée.")
    if context.coverage["sessions_unexplained"]:
        unexplained = ", ".join(context.coverage["sessions_unexplained"][:4])
        parts.append(f"Séances sans publication datée : {unexplained}.")
    parts.append("Les écarts avec les indices restent descriptifs et n’établissent pas une cause.")
    return " ".join(parts)
