#!/usr/bin/env python3
"""Create a tiny synthetic ChatGPT-style export for local demonstrations."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    code = """from __future__ import annotations

def fibonacci(limit: int) -> list[int]:
    values = [0, 1]
    while values[-1] < limit:
        values.append(values[-1] + values[-2])
    return [value for value in values if value <= limit]

if __name__ == "__main__":
    print(fibonacci(100))
"""
    conversation = {
        "id": "synthetic-conversation",
        "title": "Fibonacci CLI",
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_100,
        "mapping": {
            "node-1": {
                "parent": None,
                "message": {
                    "id": "message-1",
                    "author": {"role": "assistant"},
                    "create_time": 1_700_000_000,
                    "content": {
                        "content_type": "text",
                        "parts": [f"Here is the prototype:\n\n```python\n{code}```"],
                    },
                },
            }
        },
    }
    arguments.destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arguments.destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("conversations.json", json.dumps([conversation]))
    print(arguments.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
