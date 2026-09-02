"""Normalization helpers for evolving conversation-export payloads."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any


def text_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := text_content(item)))
    if isinstance(value, dict):
        if "parts" in value:
            return text_content(value["parts"])
        for key in ("text", "content", "result", "code"):
            if key in value:
                return text_content(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def iter_messages(conversation: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        normalized = dict(message)
        normalized.setdefault("id", str(node_id))
        normalized["_parent_id"] = node.get("parent")
        yield normalized


def message_role(message: Mapping[str, Any]) -> str:
    author = message.get("author")
    if isinstance(author, dict):
        return text_content(author.get("role")) or "unknown"
    return "unknown"


def message_content_type(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        return text_content(content.get("content_type")) or "unknown"
    return "unknown"
