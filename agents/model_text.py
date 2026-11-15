"""Extract user-facing prose from a Bedrock Converse message."""

import json
import os
import re
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .runtime import converse
from .evidence import INSTRUCTIONS, index_evidence, explain

THINKING_BLOCK = re.compile(r"<thinking\b[^>]*>.*?(?:</thinking\s*>|\Z)", re.I | re.S)
THINKING_TAG = re.compile(r"</?thinking\b[^>]*>", re.I)


def public_text(message: dict, *, separator: str = "\n") -> str:
    parts = [block["text"] for block in message.get("content", []) if "text" in block]
    text = THINKING_BLOCK.sub("", separator.join(parts))
    # A closing tag without an opening tag can follow a truncated scratchpad.
    close_tags = list(re.finditer(r"</thinking\s*>", text, re.I))
    if close_tags:
        text = text[close_tags[-1].end():]
    return THINKING_TAG.sub("", text).strip()


@lru_cache(maxsize=2)
def bedrock_client(*, read_timeout=25):
    return boto3.session.Session().client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=3, read_timeout=read_timeout, retries={"total_max_attempts": 1}),
    )


def synthesize(agent, instructions, evidence, max_tokens, notify, *, model_id=None):
    model = model_id or os.getenv("BEDROCK_MODEL_ID")
    if not model:
        return {"text": "", "mode": "local", "mode_reason": "model_unconfigured"}

    index = index_evidence(evidence)
    evidence = {**evidence, "evidence_index": list(index)}
    instructions += INSTRUCTIONS
    notify(agent, "synthesize", "running")
    try:
        response = converse(bedrock_client(),
            modelId=model,
            system=[{"text": instructions}],
            messages=[{"role": "user", "content": [{"text": json.dumps(evidence, ensure_ascii=False)}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        usage = {"input_tokens": response.get("usage", {}).get("inputTokens", 0),
                 "output_tokens": response.get("usage", {}).get("outputTokens", 0), "model_calls": 1}
        if response.get("stopReason") == "end_turn":
            text = public_text(response["output"]["message"])
            if text:
                notify(agent, "synthesize", "done", mode="bedrock")
                return {**explain(text, index), "mode": "bedrock", "mode_reason": None, "usage": usage}
        reason = "bedrock_incomplete"
    except ClientError as error:
        reason = f"bedrock_error:{error.response.get('Error', {}).get('Code', 'ClientError')}"
    except BotoCoreError as error:
        reason = f"bedrock_error:{type(error).__name__}"
    except (KeyError, TypeError, ValueError, AttributeError):
        reason = "bedrock_invalid_response"
    notify(agent, "synthesize", "unavailable", mode="bedrock")
    return {"text": "", "mode": "local", "mode_reason": reason}
