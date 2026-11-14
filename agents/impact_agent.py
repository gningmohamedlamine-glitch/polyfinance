"""Second agent: profile-specific impact from a market dossier."""

from __future__ import annotations

import json
import os
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from markets.window import ResolvedWindow, max_drawdown_cad

from .event_agent import bedrock_client
from .tools import IMPACT_TOOL_SPECS

PROFILES = {
    "amira": "Amira envisage un achat. Elle vise la croissance à long terme et veut limiter la concentration.",
    "robert": "Robert détient déjà le titre. Il préserve son capital et peut avoir un retrait à financer.",
    "mateo": "Mateo évalue un achat et applique des exclusions ESG documentées.",
}


def _metrics_robert(dossier: dict, scenario: dict) -> tuple[list[dict], str, list[dict]]:
    cad_return = dossier["returns"].get("cad_return")
    position = scenario["position_cad"]
    metrics: list[dict] = []
    tools: list[dict] = []
    if cad_return is not None:
        change = position * cad_return
        balance = position + change
        metrics.extend(
            [
                {"label": "Variation de la position", "value": change, "unit": "CAD"},
                {"label": "Valeur finale simulée", "value": balance, "unit": "CAD"},
            ]
        )
        withdrawal = scenario.get("withdrawal_cad", 0)
        if withdrawal > 0:
            metrics.append({"label": "Écart par rapport au retrait", "value": balance - withdrawal, "unit": "CAD"})
        tools.append(
            {
                "agent": "impact",
                "name": "position_value_cad",
                "source": "local",
                "status": "executed",
                "arguments": {"position_cad": position, "cad_return": cad_return, "withdrawal_cad": withdrawal},
            }
        )
        assumptions = (
            "Compare la valeur simulée de cette position au retrait prévu, en tenant compte de la variation du dollar américain."
        )
    else:
        assumptions = "Le calcul en CAD nécessite un cours de change pour les deux clôtures."
    selection = dossier["selection"]
    if selection.get("applied") == "period" and cad_return is not None:
        window = ResolvedWindow(
            ticker=selection["ticker"],
            name=selection["name"],
            requested=selection["requested"],
            applied=selection["applied"],
            reason=selection.get("reason"),
            start_close_date=selection["start_close_date"],
            end_close_date=selection["end_close_date"],
            start_adj_close=selection["start_adj_close"],
            end_adj_close=selection["end_adj_close"],
            bounds=selection.get("bounds"),
            measured_sessions=tuple(dossier["coverage"]["sessions_measured"]),
        )
        drawdown = max_drawdown_cad(window, position)
        if drawdown:
            metrics.append(
                {
                    "label": "Baisse maximale depuis un sommet",
                    "value": drawdown["max_drawdown"],
                    "unit": "%",
                }
            )
            metrics.append(
                {
                    "label": "Valeur au creux simulé",
                    "value": drawdown["position_at_trough_cad"],
                    "unit": "CAD",
                }
            )
            tools.append(
                {
                    "agent": "impact",
                    "name": "max_drawdown_cad",
                    "source": "local",
                    "status": "executed",
                    "arguments": {
                        "ticker": window.ticker,
                        "start_close_date": window.start_close_date,
                        "end_close_date": window.end_close_date,
                        "position_cad": position,
                    },
                }
            )
            assumptions += (
                f" Baisse maximale observée du {drawdown['peak_date']} au {drawdown['trough_date']}."
            )
    return metrics, assumptions, tools


def _metrics_amira(scenario: dict) -> tuple[list[dict], str, list[dict]]:
    portfolio = scenario["portfolio_cad"]
    position = scenario["position_cad"]
    purchase = scenario["purchase_cad"]
    metrics = [
        {"label": "Poids direct actuel", "value": position / portfolio, "unit": "%"},
        {"label": "Poids direct après l’achat", "value": (position + purchase) / portfolio, "unit": "%"},
    ]
    assumptions = (
        "Le calcul porte sur le poids direct. La composition des FNB est indisponible dans les CSV, "
        "donc l’exposition indirecte n’est pas mesurée."
    )
    tools = [
        {
            "agent": "impact",
            "name": "direct_weight",
            "source": "local",
            "status": "executed",
            "arguments": {
                "position_cad": position,
                "purchase_cad": purchase,
                "portfolio_cad": portfolio,
            },
        }
    ]
    return metrics, assumptions, tools


def _metrics_mateo() -> tuple[list[dict], str, list[dict]]:
    assumptions = (
        "Le catalogue ne contient pas de preuves ESG dédiées. Les publications de marché ne suffisent pas "
        "pour conclure sur les exclusions de Mateo."
    )
    tools = [
        {
            "agent": "impact",
            "name": "exclusion_evidence",
            "source": "local",
            "status": "executed",
            "arguments": {"matched": []},
        }
    ]
    return [], assumptions, tools


def _compute(profile: str, dossier: dict, scenario: dict) -> tuple[list[dict], str, list[dict]]:
    if profile == "robert":
        return _metrics_robert(dossier, scenario)
    if profile == "amira":
        return _metrics_amira(scenario)
    return _metrics_mateo()


def _fallback_text(profile: str, metrics: list[dict], assumptions: str) -> str:
    if profile == "mateo":
        return assumptions
    if metrics:
        return f"{assumptions} Les métriques calculées restent une simulation sur le scénario fictif."
    return assumptions


def run_impact_agent(dossier: dict, profile: str, scenario: dict, trace: list[dict] | None = None) -> dict:
    metrics, assumptions, impact_tools = _compute(profile, dossier, scenario)
    payload = {
        "profile": PROFILES[profile],
        "dossier": {
            "selection": dossier["selection"],
            "returns": dossier["returns"],
            "publications": dossier["publications"],
            "notable_sessions": dossier["notable_sessions"],
        },
        "metrics": metrics,
        "assumptions": assumptions,
    }
    model = os.getenv("BEDROCK_MODEL_ID")
    mode = "local"
    mode_reason = "model_unconfigured"
    text = _fallback_text(profile, metrics, assumptions)
    if model:
        try:
            response = bedrock_client().converse(
                modelId=model,
                system=[
                    {
                        "text": (
                            "Explique ce que les métriques calculées et les faits sourcés changent pour la décision "
                            "fictive du profil. Utilise uniquement les entrées. Ne recommande aucune transaction. "
                            "Réponds en français en deux phrases maximum."
                        )
                    }
                ],
                messages=[{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
                toolConfig={"tools": IMPACT_TOOL_SPECS},
                inferenceConfig={"maxTokens": 320, "temperature": 0.1},
            )
            answer = " ".join(
                block["text"]
                for block in response["output"]["message"]["content"]
                if isinstance(block, dict) and "text" in block
            ).strip()
            if answer and response.get("stopReason") == "end_turn":
                text = answer
                mode = "bedrock"
                mode_reason = None
        except (BotoCoreError, ClientError):
            mode_reason = "bedrock_error"

    combined_trace = list(trace or []) + list(dossier.get("tools_executed", [])) + impact_tools
    return {
        "text": text,
        "mode": mode,
        "mode_reason": mode_reason,
        "metrics": metrics,
        "assumptions": assumptions,
        "trace": combined_trace,
    }