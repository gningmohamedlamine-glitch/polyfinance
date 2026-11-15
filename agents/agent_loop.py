"""Boucle d'agent bornée : le modèle choisit l'outil suivant, le code valide et exécute.

Principe (atelier « De la consigne au pipeline », niveau 8) : le code tient la boucle,
limitée à MAX_DECISIONS appels d'outils ; le modèle ne choisit que l'outil suivant ou
conclut. Chaque appel est validé en Python avant exécution ; un appel refusé est renvoyé
au modèle comme erreur, pour qu'il corrige ou conclue.
"""

from __future__ import annotations

import json
import os

from botocore.exceptions import BotoCoreError, ClientError

from .model_text import bedrock_client, public_text

MAX_DECISIONS = 4


def model_for(agent: str) -> str | None:
    """EVENT_MODEL_ID / IMPACT_MODEL_ID, sinon BEDROCK_MODEL_ID (même modèle pour les deux agents)."""
    return os.getenv(f"{agent.upper()}_MODEL_ID") or os.getenv("BEDROCK_MODEL_ID")


def run_tool_loop(agent, model, instructions, payload, tool_specs, execute, notify, max_tokens=900):
    """Exécute la boucle et renvoie le texte final, le mode et la liste des décisions.

    execute(name, args) -> (ok: bool, result: dict | str). Une valeur ok=False est un refus.
    """
    decisions: list[dict] = []
    messages = [{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}]
    params = {
        "modelId": model,
        "system": [{"text": instructions}],
        "toolConfig": {"tools": tool_specs},
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}

    def done(text, mode, reason):
        return {"text": text, "mode": mode, "mode_reason": reason, "decisions": decisions, "usage": usage}

    try:
        for _ in range(MAX_DECISIONS + 2):
            response = bedrock_client().converse(messages=messages, **params)
            usage["model_calls"] += 1
            usage["input_tokens"] += response.get("usage", {}).get("inputTokens", 0)
            usage["output_tokens"] += response.get("usage", {}).get("outputTokens", 0)
            message = response["output"]["message"]
            stop = response.get("stopReason")
            if stop == "end_turn":
                text = public_text(message)
                if text:
                    return done(text, "bedrock", None)
                return done("", "local", "bedrock_incomplete")
            if stop != "tool_use":
                return done("", "local", "bedrock_incomplete")

            reason = public_text(message, separator=" ")
            messages.append(message)
            results = []
            for block in message.get("content", []):
                if "toolUse" not in block:
                    continue
                use = block["toolUse"]
                name, args = use["name"], use.get("input") or {}
                calls += 1
                if calls > MAX_DECISIONS:
                    ok, result = False, f"Limite de {MAX_DECISIONS} décisions atteinte : conclus avec les preuves réunies."
                else:
                    ok, result = execute(name, args)
                decisions.append({
                    "agent": agent, "tool": name, "arguments": args,
                    "accepted": ok, "reason": reason[:400] or None,
                    **({} if ok else {"refusal": result}),
                })
                if not ok:
                    notify(agent, name, "unavailable", mode="model", reason="rejected")
                results.append({"toolResult": {
                    "toolUseId": use["toolUseId"],
                    "content": [{"json": result}] if ok else [{"text": result}],
                    "status": "success" if ok else "error",
                }})
            messages.append({"role": "user", "content": results})
        return done("", "local", "bedrock_incomplete")
    except (BotoCoreError, ClientError):
        return done("", "local", "bedrock_error")
