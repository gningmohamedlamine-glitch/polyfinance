"""Second agent: profile-specific impact from a market dossier."""

from __future__ import annotations

import json
import os
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from markets.window import ResolvedWindow, max_drawdown_cad, risk_indicators

from .event_agent import bedrock_client

PROFILES = {
    "amira": "Amira envisage un achat. Elle vise la croissance à long terme et veut limiter la concentration.",
    "robert": (
        "Robert s’intéresse à ce titre très médiatisé. Il préserve son capital et doit financer un retrait ; "
        "l’agent vérifie si le titre est cohérent avec son profil avant tout calcul."
    ),
    "mateo": "Mateo évalue un achat et applique des exclusions ESG documentées.",
}


# Limites fictives par profil (hypothèses documentées, pas des règles réglementaires).
PROFILE_LIMITS = {
    "amira": {"annual_volatility": 0.60, "max_drawdown": -0.60, "max_weight": 0.15, "horizon_years": 15},
    "mateo": {"annual_volatility": 0.30, "max_drawdown": -0.35, "max_weight": 0.10, "horizon_years": 10},
    "robert": {"annual_volatility": 0.20, "max_drawdown": -0.20, "max_weight": 0.05, "horizon_years": 4},
}


def profile_coherence(profile: str, ticker: str, end_date: str, weight_after: float | None = None) -> dict:
    """Garde-fou de gouvernance en Python : risque observé du titre (avant end_date) contre limites du profil.

    Le modèle ne décide pas de la cohérence ; il explique les conflits calculés ici.
    """
    limits = PROFILE_LIMITS[profile]
    risk = risk_indicators(ticker, end_date)
    conflicts: list[str] = []
    if risk.get("status") == "ok":
        if risk["annual_volatility"] > limits["annual_volatility"]:
            conflicts.append(
                f"Volatilité annuelle de {risk['annual_volatility']:.0%} sur les 12 derniers mois, "
                f"au-delà de la limite de {limits['annual_volatility']:.0%} retenue pour ce profil."
            )
        if risk["max_drawdown"] < limits["max_drawdown"]:
            conflicts.append(
                f"Baisse maximale de {risk['max_drawdown']:.0%} sur les 12 derniers mois, "
                f"au-delà de la baisse tolérée de {limits['max_drawdown']:.0%}."
            )
    if weight_after is not None and weight_after > limits["max_weight"]:
        conflicts.append(
            f"Poids direct de {weight_after:.0%} après l’achat, au-delà de la concentration maximale "
            f"de {limits['max_weight']:.0%}."
        )
    return {
        "profile": profile,
        "ticker": ticker,
        "limits": limits,
        "risk": risk,
        "conflicts": conflicts,
        "coherent": not conflicts,
        "missing": [] if risk.get("status") == "ok" else ["historique insuffisant pour mesurer le risque"],
        "notice": "Simulation : analyse de cohérence, pas un conseil financier.",
    }


def _coherence_tool(profile: str, ticker: str, end_date: str, weight_after: float | None) -> dict:
    return {
        "agent": "impact",
        "name": "profile_coherence",
        "source": "local",
        "status": "executed",
        "arguments": {"profile": profile, "ticker": ticker, "end_date": end_date, "weight_after": weight_after},
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
            "Si Robert détenait cette position, compare sa valeur simulée au retrait prévu, en tenant compte de la variation du dollar américain."
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


def _compute(profile: str, dossier: dict, scenario: dict) -> tuple[list[dict], str, list[dict], dict]:
    selection = dossier["selection"]
    weight_after = None
    if profile == "robert":
        metrics, assumptions, tools = _metrics_robert(dossier, scenario)
    elif profile == "amira":
        metrics, assumptions, tools = _metrics_amira(scenario)
        weight_after = (scenario["position_cad"] + scenario["purchase_cad"]) / scenario["portfolio_cad"]
    else:
        metrics, assumptions, tools = _metrics_mateo()
    coherence = profile_coherence(profile, selection["ticker"], selection["end_close_date"], weight_after)
    if coherence["risk"].get("status") == "ok":
        metrics = [
            {"label": "Volatilité annuelle (12 mois)", "value": coherence["risk"]["annual_volatility"], "unit": "%"},
            *metrics,
        ]
    tools = [*tools, _coherence_tool(profile, selection["ticker"], selection["end_close_date"], weight_after)]
    return metrics, assumptions, tools, coherence


def _fallback_text(profile: str, metrics: list[dict], assumptions: str, coherence: dict | None = None) -> str:
    parts = []
    if coherence and coherence["conflicts"]:
        parts.append("Incohérence avec le profil : " + " ".join(coherence["conflicts"]))
    elif coherence and coherence["risk"].get("status") == "ok":
        parts.append("Le risque observé du titre reste dans les limites retenues pour ce profil.")
    parts.append(assumptions)
    if profile != "mateo" and metrics:
        parts.append("Les métriques calculées restent une simulation sur le scénario fictif.")
    return " ".join(parts)


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
                "Appelle calculate_profile_impact avant de répondre. Si coherence.conflicts n’est pas vide, "
                "commence par signaler clairement l’incohérence avec le profil, chiffres à l’appui. "
                "Explique ensuite les résultats du scénario fictif en français, en trois phrases maximum. "
                "Utilise uniquement les données fournies, sans conseil d’achat ni de vente."
            )}],
            "inferenceConfig": {"maxTokens": 400, "temperature": 0.1},
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
                metrics, assumptions, calculations, coherence = result
                impact_tools = [{
                    "agent": "impact", "name": tool_name, "source": "model",
                    "status": "executed", "arguments": {},
                }, *calculations]
                messages.extend([message, {"role": "user", "content": [{"toolResult": {
                    "toolUseId": calls[0]["toolUseId"],
                    "content": [{"json": {"metrics": metrics, "assumptions": assumptions, "coherence": coherence}}],
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
    metrics, assumptions, _, coherence = result
    return {
        "coherence": coherence,
        "text": text or _fallback_text(profile, metrics, assumptions, coherence),
        "mode": mode,
        "mode_reason": mode_reason,
        "metrics": metrics,
        "assumptions": assumptions,
        "trace": list(dossier.get("tools_executed", [])) + impact_tools,
    }
