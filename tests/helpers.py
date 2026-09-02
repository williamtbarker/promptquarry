from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


def message(
    identifier: str,
    role: str,
    text: str,
    *,
    content_type: str = "text",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "author": {"role": role},
        "create_time": 1_700_000_000,
        "content": {"content_type": content_type, "parts": [text]},
    }


def conversation(
    identifier: str,
    title: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    parent = None
    for ordinal, item in enumerate(messages):
        node_id = f"node-{identifier}-{ordinal}"
        mapping[node_id] = {"id": node_id, "parent": parent, "message": item}
        parent = node_id
    return {
        "id": identifier,
        "title": title,
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_100,
        "mapping": mapping,
    }


def write_archive(
    path: Path,
    conversations: list[dict[str, Any]],
    *,
    member: str = "conversations.json",
) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, json.dumps(conversations, ensure_ascii=False))
    return path
