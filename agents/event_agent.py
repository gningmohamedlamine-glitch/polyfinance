"""First agent: market dossier via Bedrock tool use or local fallback."""

from __future__ import annotations

import json
import os
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from markets.window import ResolvedWindow

from .dossier import build_dossier, local_event_text
from .tools import (
    EVENT_TOOL_SPECS,
    MAX_TOOL_CALLS,
    ToolContext,
    build_tool_context,
    required_event_tools,
    run_event_tool,
    validate_event_args,
)

SYSTEM = (
    "Tu es l’agent marché d’AlphaForge. Demande les outils pour obtenir les chiffres et les publications. "
    "Distingue les chiffres, les événements vérifiés et les liens plausibles. "
    "Un écart avec SPY ou QQQ ne prouve pas une cause. Réponds en français."
)


@lru_cache(maxsize=1)
def bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=3, read_timeout=25, retries={"total_max_attempts": 1}),
    )


def _tool_result_payload(record_id: str, payload) -> dict:
    return {
        "toolResult": {
            "toolUseId": record_id,
            "content": [{"json": payload}],
            "status": "success",
        }
    }


def _tool_error(record_id: str, message: str) -> dict:
    return {
        "toolResult": {
            "toolUseId": record_id,
            "content": [{"text": message}],
            "status": "error",
        }
    }


def _extract_text(message: dict) -> str:
    return " ".join(
        block["text"] for block in message.get("content", []) if isinstance(block, dict) and "text" in block
    ).strip()


def _extract_tool_uses(message: dict) -> list[dict]:
    return [
        block["toolUse"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolUse" in block
    ]


def _run_local(window: ResolvedWindow) -> dict:
    context = build_tool_context(window)
    tools_executed = []
    for name in required_event_tools(window):
        args = {
            "ticker": window.ticker,
            "start_close_date": window.start_close_date,
            "end_close_date": window.end_close_date,
        }
        if name == "search_publications":
            args = {"ticker": window.ticker, "sessions": list(window.measured_sessions)}
        tools_executed.append(
            {
                "agent": "event",
                "name": name,
                "source": "local",
                "status": "executed",
                "arguments": args,
            }
        )
    dossier = build_dossier(
        window,
        returns=context.returns,
        notable=context.notable,
        publications=context.publications,
        coverage=context.coverage,
        synthesis_text=local_event_text(context),
        synthesis_mode="local",
        mode_reason="model_unconfigured",
        tools_executed=tools_executed,
    )
    return dossier


def _guard_missing_tools(window: ResolvedWindow, context: ToolContext, executed: set[str], trace: list[dict]):
    for name in required_event_tools(window):
        if name in executed:
            continue
        args = {
            "ticker": window.ticker,
            "start_close_date": window.start_close_date,
            "end_close_date": window.end_close_date,
        }
        if name == "search_publications":
            args = {"ticker": window.ticker, "sessions": list(window.measured_sessions)}
        run_event_tool(name, context, args if name == "search_publications" else None)
        trace.append(
            {
                "agent": "event",
                "name": name,
                "source": "guard",
                "status": "executed",
                "arguments": args,
            }
        )
        executed.add(name)


def run_event_agent(window: ResolvedWindow) -> dict:
    model = os.getenv("BEDROCK_MODEL_ID")
    context = build_tool_context(window)
    if not model:
        return _run_local(window)

    trace: list[dict] = []
    executed: set[str] = set()
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": json.dumps(
                        {
                            "selection": {
                                "ticker": window.ticker,
                                "start_close_date": window.start_close_date,
                                "end_close_date": window.end_close_date,
                                "measured_sessions": list(window.measured_sessions),
                            }
                        },
                        ensure_ascii=False,
                    )
                }
            ],
        }
    ]
    synthesis_text = ""
    synthesis_mode = "bedrock"
    mode_reason = None
    tool_calls = 0

    try:
        for _ in range(4):
            response = bedrock_client().converse(
                modelId=model,
                system=[{"text": SYSTEM}],
                messages=messages,
                toolConfig={"tools": EVENT_TOOL_SPECS},
                inferenceConfig={"maxTokens": 700, "temperature": 0.1},
            )
            stop = response.get("stopReason")
            message = response["output"]["message"]
            if stop == "end_turn":
                synthesis_text = _extract_text(message)
                break
            if stop != "tool_use":
                synthesis_mode = "local"
                mode_reason = "bedrock_error"
                break

            tool_uses = _extract_tool_uses(message)
            messages.append(message)
            tool_results = []
            for tool_use in tool_uses:
                tool_calls += 1
                name = tool_use["name"]
                args = tool_use.get("input") or {}
                record_id = tool_use["toolUseId"]
                error = validate_event_args(name, args, window)
                if error or tool_calls > MAX_TOOL_CALLS:
                    trace.append(
                        {
                            "agent": "event",
                            "name": name,
                            "source": "model",
                            "status": "rejected",
                            "arguments": args,
                            "error": error or "limite d’appels atteinte",
                        }
                    )
                    tool_results.append(_tool_error(record_id, error or "limite d’appels atteinte"))
                    continue
                payload = run_event_tool(name, context, args)
                if name == "search_publications":
                    context.publications = payload["publications"]
                    context.coverage = payload["coverage"]
                trace.append(
                    {
                        "agent": "event",
                        "name": name,
                        "source": "model",
                        "status": "executed",
                        "arguments": args,
                    }
                )
                executed.add(name)
                tool_results.append(_tool_result_payload(record_id, payload))
            messages.append({"role": "user", "content": tool_results})
        if not synthesis_text:
            synthesis_mode = "local"
            mode_reason = mode_reason or "bedrock_error"
    except (BotoCoreError, ClientError):
        synthesis_mode = "local"
        mode_reason = "bedrock_error"

    if synthesis_mode == "local":
        _guard_missing_tools(window, context, executed, trace)
        dossier = build_dossier(
            window,
            returns=context.returns,
            notable=context.notable,
            publications=context.publications,
            coverage=context.coverage,
            synthesis_text=local_event_text(context),
            synthesis_mode="local",
            mode_reason=mode_reason or "bedrock_error",
            tools_executed=trace,
        )
        return dossier

    _guard_missing_tools(window, context, executed, trace)
    if not synthesis_text:
        synthesis_text = local_event_text(context)
    return build_dossier(
        window,
        returns=context.returns,
        notable=context.notable,
        publications=context.publications,
        coverage=context.coverage,
        synthesis_text=synthesis_text,
        synthesis_mode="bedrock",
        mode_reason=None,
        tools_executed=trace,
    )