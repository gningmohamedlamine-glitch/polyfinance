"""Find cited historical leads with Amazon Nova Web Grounding."""

import json
import logging
import os
from datetime import date, timedelta
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .model_text import public_text

logger = logging.getLogger(__name__)
MODEL = "us.amazon.nova-2-lite-v1:0"


def web_windows(dates, window):
    radius = timedelta(days=3)
    anchors = dict.fromkeys(dates)
    if window.applied == "period":
        anchors[window.end_close_date] = None
    windows = {}
    for session in anchors:
        day = date.fromisoformat(session)
        start = (day - radius).isoformat()
        if window.applied == "period" and session == window.end_close_date:
            start = min(start, window.start_close_date)
        windows[session] = (start, (day + radius).isoformat())
    return windows


def find_web_leads(client, ticker, name, windows):
    if os.getenv("MARKET_WEB_SEARCH") != "1":
        return [], "disabled"
    sessions = [date.fromisoformat(day).strftime("%B %d, %Y") for day in windows]
    queries = [f'{name} {ticker} shares market news "{day}"' for day in sessions]
    prompt = (
        f"Use web search for historical news and market reactions relevant to {name} ({ticker}). "
        f"Start with these date-specific search queries: {json.dumps(queries)}. "
        "Then search the week for analyst notes, market recaps, or sector developments around those days. "
        f"These are target trading dates mapped to inclusive publication date ranges: {json.dumps(windows)}. "
        "Search around each date across the full range, including earlier announcements, market-wide "
        "news, and next-day coverage discussing the move. Prefer company releases, regulators and "
        "reputable news outlets. Find up to five concrete reports. Prioritize dated evidence at or "
        "before the trading date. Include later articles only if they discuss that move or its context. "
        "Discard results outside the publication ranges, even major company announcements. "
        "Use the actual publication date or SEC acceptance date, never the event date or report period. "
        "Return only a JSON array of objects with url, title, published_date (YYYY-MM-DD), session "
        "(a target trading date from the map), and summary (one short French sentence). Copy each "
        "exact cited source URL from the grounding results. Exclude homepages and quote pages."
    )
    try:
        response = client.converse(
            modelId=MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={"tools": [{"systemTool": {"name": "nova_grounding"}}]},
            inferenceConfig={"maxTokens": 1300},
        )
    except (ConnectTimeoutError, ReadTimeoutError):
        logger.warning("Nova Web Grounding timed out for %s (%s)", ticker, ", ".join(windows))
        return [], "timeout"
    except (BotoCoreError, ClientError) as error:
        logger.warning("Nova Web Grounding failed: %s", type(error).__name__)
        return [], "unavailable"

    blocks = response.get("output", {}).get("message", {}).get("content", [])
    cited = {
        citation.get("location", {}).get("web", {}).get("url")
        for block in blocks
        for citation in block.get("citationsContent", {}).get("citations", [])
    }
    if not cited and not any(block.get("toolResult", {}).get("status") == "success" for block in blocks):
        tool_failed = any(block.get("toolResult", {}).get("status") == "error" for block in blocks)
        return [], "unavailable" if tool_failed else "not_executed"
    # Converse can return grounded text alongside its citations in the same block.
    text_blocks = [
        {"text": fragment["text"]}
        for block in blocks
        for fragment in ([block] if "text" in block else block.get("citationsContent", {}).get("content", []))
        if "text" in fragment
    ]
    answer = public_text({"content": text_blocks}, separator="")
    try:
        rows = json.loads(answer[answer.index("["):answer.rindex("]") + 1])
    except (ValueError, TypeError):
        return [], "invalid_response"

    if not isinstance(rows, list):
        return [], "invalid_response"

    leads = []
    seen = set()
    for row in rows:
        fields = ("url", "title", "published_date", "session", "summary")
        if not isinstance(row, dict) or not all(isinstance(row.get(field), str) and row[field] for field in fields):
            continue
        url = row["url"]
        if url not in cited or url in seen or row["session"] not in windows:
            continue
        try:
            parsed = urlsplit(url)
            published = date.fromisoformat(row["published_date"]).isoformat()
        except ValueError:
            continue
        start, end = windows[row["session"]]
        if parsed.scheme != "https" or not parsed.hostname or not start <= published <= end:
            continue
        seen.add(url)
        leads.append({
            **{field: row[field][:500] for field in fields},
            "url": url,
            "published_date": published,
            "after_session": published > row["session"],
        })
        if len(leads) == 5:
            break
    return leads, "found" if leads else "no_dated_sources"
