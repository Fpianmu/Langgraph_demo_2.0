from __future__ import annotations

import json
from typing import Any


def format_sse_event(event: dict[str, Any]) -> str:
    event_id = str(event["event_id"])
    event_type = str(event["event_type"])
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
