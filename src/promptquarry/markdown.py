"""Markdown fence extraction that preserves incomplete recovery candidates."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

OPENING_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)$")


@dataclass(frozen=True, slots=True)
class CodeFence:
    label: str
    code: str
    ordinal: int
    complete: bool
    start_line: int


def iter_code_fences(text: str) -> Iterator[CodeFence]:
    """Yield backtick or tilde code fences, including an unterminated final fence."""

    marker = ""
    label = ""
    lines: list[str] = []
    start_line = 0
    ordinal = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not marker:
            match = OPENING_FENCE.match(line)
            if match is None:
                continue
            marker = match.group(1)
            label = match.group(2).strip()
            lines = []
            start_line = line_number
            continue

        stripped = line.strip()
        if stripped and set(stripped) == {marker[0]} and len(stripped) >= len(marker):
            ordinal += 1
            yield CodeFence(label, "\n".join(lines), ordinal, True, start_line)
            marker = ""
            label = ""
            lines = []
        else:
            lines.append(line)

    if marker:
        ordinal += 1
        yield CodeFence(label, "\n".join(lines), ordinal, False, start_line)
