"""Orchestrate evidence retrieval and profile-specific impact."""

import json
import os
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .events import find_events

PROFILES = {
    "amira": "Amira envisage un achat. Elle vise la croissance à long terme et veut limiter la concentration.",
    "robert": "Robert détient déjà le titre. Il préserve son capital et peut avoir un retrait à financer.",
    "mateo": "Mateo évalue un achat et applique des exclusions ESG documentées.",
}


@lru_cache(maxsize=1)
def bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=3, read_timeout=12, retries={"total_max_attempts": 1}),
    )


def synthesize(instructions, payload, fallback):
    model = os.getenv("BEDROCK_MODEL_ID")
    if not model:
        return {"text": fallback, "mode": "local"}
    try:
        response = bedrock_client().converse(
            modelId=model,
            system=[{"text": instructions + " Réponds en français en deux phrases maximum."}],
            messages=[{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
            inferenceConfig={"maxTokens": 320, "temperature": 0.1},
        )
        answer = " ".join(block["text"] for block in response["output"]["message"]["content"] if "text" in block).strip()
        if answer and response["stopReason"] == "end_turn":
            return {"text": answer, "mode": "bedrock"}
    except (BotoCoreError, ClientError):
        pass
    return {"text": fallback, "mode": "fallback"}


def event_agent(move):
    sources = find_events(move["ticker"], move["previous_date"], move["date"])
    if not sources:
        return {
            "mode": "local",
            "text": "Le catalogue de démo ne contient aucune annonce pour cette séance. Les cours et les références permettent de comparer le mouvement.",
            "sources": [],
        }

    result = synthesize(
        "Résume uniquement les publications fournies, en distinguant la chronologie d’une hypothèse sur le mouvement. "
        "Les écarts avec les indices sont descriptifs. N’affirme aucune causalité et n’ajoute aucun fait.",
        {"movement": move, "sources": sources},
        " ".join(source["summary"] for source in sources) + " La chronologie fournit du contexte. La cause du mouvement reste à établir.",
    )
    return {**result, "sources": sources}


def impact_agent(move, sources, profile, position_cad, withdrawal_cad, portfolio_cad, purchase_cad):
    metrics = []
    if profile == "robert":
        change = position_cad * move["cad_return"] if move["cad_return"] is not None else None
        if change is not None:
            metrics.append({"label": "Variation de la position", "value": change, "unit": "CAD"})
            balance = position_cad + change
            if withdrawal_cad > 0:
                metrics.append({"label": "Écart par rapport au retrait", "value": balance - withdrawal_cad, "unit": "CAD"})
        fallback = "Compare la valeur simulée de cette position au retrait prévu, en tenant compte de la variation du dollar américain."
        if change is None:
            fallback = "Le calcul en CAD nécessite un cours de change pour les deux clôtures."
    elif profile == "amira":
        metrics.extend([
            {"label": "Poids direct actuel", "value": position_cad / portfolio_cad, "unit": "%"},
            {"label": "Poids direct après l’achat", "value": (position_cad + purchase_cad) / portfolio_cad, "unit": "%"},
        ])
        fallback = "L’achat est financé par le portefeuille existant. Les poids mesurent l’exposition directe au titre. La composition des fonds serait nécessaire pour calculer l’exposition indirecte."
    else:
        fallback = "Le catalogue ne contient pas de preuve suffisante pour évaluer les exclusions ESG de Mateo. Il faut des sources portant sur les critères qu’il a définis."

    result = synthesize(
        "Explique ce que les métriques calculées et les faits sourcés changent pour la décision fictive du profil. "
        "Utilise uniquement les entrées. Ne recommande aucune transaction. "
        "Si le profil est Mateo, indique que les exclusions ESG nécessitent des preuves dédiées.",
        {"profile": PROFILES[profile], "movement": move, "metrics": metrics, "sources": sources,
         "assumptions": fallback},
        fallback,
    )
    return {**result, "metrics": metrics}
