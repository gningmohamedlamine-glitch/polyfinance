"""Second agent: profile-specific impact from a market dossier."""

from __future__ import annotations

import json
import os
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from markets.window import ResolvedWindow, max_drawdown_cad

from .event_agent import bedrock_client

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


def run_impact_agent(dossier: dict, profile: str, scenario: dict) -> dict:
    model = os.getenv("BEDROCK_MODEL_ID")
    mode = "local"
    mode_reason = "model_unconfigured"
    impact_tools = []
    result = None
    text = ""
    if model:
        tool_name = "calculate_profile_impact"
        config = {"tools": [{"toolSpec": {
            "name": tool_name,
            "description": "Calcule les métriques et les hypothèses pour le profil et la sélection validés.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "additionalProperties": False}},
        }}]}
        payload = {
            "profile": PROFILES[profile],
            "selection": dossier["selection"],
            "publications": dossier["publications"],
        }
        messages = [{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}]
        params = {
            "modelId": model,
            "system": [{"text": (
                "Appelle calculate_profile_impact avant de répondre. Explique les résultats "
                "du scénario fictif en français en deux phrases maximum. "
                "Utilise uniquement les données fournies, sans conseil de transaction."
            )}],
            "inferenceConfig": {"maxTokens": 320, "temperature": 0.1},
            "toolConfig": config,
        }
        mode_reason = "bedrock_tool_missing"
        try:
            response = bedrock_client().converse(messages=messages, **params)
            message = response["output"]["message"]
            calls = [block["toolUse"] for block in message["content"] if "toolUse" in block]
            if (response.get("stopReason") == "tool_use" and len(calls) == 1
                    and calls[0]["name"] == tool_name and calls[0].get("input") == {}):
                result = _compute(profile, dossier, scenario)
                metrics, assumptions, calculations = result
                impact_tools = [{
                    "agent": "impact", "name": tool_name, "source": "model",
                    "status": "executed", "arguments": {},
                }, *calculations]
                messages.extend([message, {"role": "user", "content": [{"toolResult": {
                    "toolUseId": calls[0]["toolUseId"],
                    "content": [{"json": {"metrics": metrics, "assumptions": assumptions}}],
                }}]}])
                response = bedrock_client().converse(messages=messages, **params)
                mode_reason = "bedrock_incomplete"
                if response.get("stopReason") == "end_turn":
                    text = " ".join(
                        block["text"] for block in response["output"]["message"]["content"]
                        if "text" in block
                    ).strip()
                    if text:
                        mode = "bedrock"
                        mode_reason = None
        except (BotoCoreError, ClientError):
            mode_reason = "bedrock_error"

    if result is None:
        result = _compute(profile, dossier, scenario)
        impact_tools = result[2]
    metrics, assumptions, _ = result
    return {
        "text": text or _fallback_text(profile, metrics, assumptions),
        "mode": mode,
        "mode_reason": mode_reason,
        "metrics": metrics,
        "assumptions": assumptions,
        "trace": list(dossier.get("tools_executed", [])) + impact_tools,
    }
