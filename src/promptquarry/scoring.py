"""Deterministic language inference, safety flags, and salvage scoring."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "rs": "rust",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "rscript": "r",
    "js": "javascript",
    "ts": "typescript",
    "yml": "yaml",
    "docker": "dockerfile",
}

EXTENSIONS = {
    "bash": ".sh",
    "css": ".css",
    "dockerfile": ".Dockerfile",
    "go": ".go",
    "html": ".html",
    "javascript": ".js",
    "json": ".json",
    "julia": ".jl",
    "markdown": ".md",
    "nextflow": ".nf",
    "python": ".py",
    "r": ".R",
    "rust": ".rs",
    "sql": ".sql",
    "text": ".txt",
    "typescript": ".ts",
    "unknown": ".txt",
    "yaml": ".yaml",
}

LANGUAGE_HINTS = {
    "python": (("def ", 3), ("import ", 2), ("__main__", 3), ("self.", 1)),
    "rust": (("fn main", 4), ("use std::", 3), ("impl ", 2), ("pub struct ", 3)),
    "bash": (("#!/bin/", 4), ("set -e", 3), ("$@", 2), ("case ", 1)),
    "r": (("library(", 3), (" <- ", 2), ("function(", 3), ("ggplot", 2)),
    "sql": (("select ", 2), ("create table", 4), ("insert into", 3), (" join ", 1)),
    "javascript": (("const ", 2), ("function ", 2), ("=>", 2), ("console.log", 2)),
    "typescript": (("interface ", 3), (": string", 2), ("type ", 1), ("=>", 1)),
    "go": (("package main", 4), ("func ", 3), ("fmt.", 2), ("import (", 2)),
    "nextflow": (("process ", 4), ("channel.", 3), ("workflow {", 4)),
    "dockerfile": (("from ", 3), ("run ", 2), ("entrypoint", 3), ("copy ", 2)),
}

SENSITIVE_PATTERNS = {
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "email-address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "mac-home-path": re.compile(r"/Users/[^/\s]+/"),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|password|passwd|secret|access[_-]?token)\s*[:=]\s*"
        r"['\"][^'\"\n]{6,}['\"]"
    ),
}

PLACEHOLDER_PATTERNS = (
    re.compile(r"\.\.\.\s*(?:rest|existing|implementation|code)", re.I),
    re.compile(r"(?:your|insert)[-_ ](?:code|key|token|path)[-_ ]here", re.I),
    re.compile(r"TODO\b|FIXME\b"),
    re.compile(r"pass\s*(?:#.*)?$", re.M),
)


@dataclass(frozen=True, slots=True)
class ScoredCode:
    language: str
    extension: str
    score: int
    syntax_status: str
    sensitivity_flags: tuple[str, ...]
    reasons: tuple[str, ...]


def normalize_code(code: str) -> str:
    lines = [line.rstrip() for line in code.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def infer_language(label: str, code: str) -> str:
    token = label.strip().lower().split(maxsplit=1)[0] if label.strip() else ""
    token = LANGUAGE_ALIASES.get(token, token)
    if token in EXTENSIONS and token not in {"text", "unknown"}:
        return token
    lowered = code.lower()
    scores = {
        language: sum(weight for hint, weight in hints if hint in lowered)
        for language, hints in LANGUAGE_HINTS.items()
    }
    winner, score = max(scores.items(), key=lambda item: (item[1], item[0]))
    return winner if score else "unknown"


def sensitivity_flags(code: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in SENSITIVE_PATTERNS.items() if pattern.search(code))


def _syntax_status(language: str, code: str) -> str:
    if language == "python":
        try:
            ast.parse(code)
        except SyntaxError:
            return "invalid"
        return "valid"
    if language == "json":
        try:
            json.loads(code)
        except json.JSONDecodeError:
            return "invalid"
        return "valid"
    return "unchecked"


def analyze_code(label: str, code: str, *, complete: bool = True) -> ScoredCode:
    normalized = normalize_code(code)
    language = infer_language(label, normalized)
    status = _syntax_status(language, normalized)
    flags = sensitivity_flags(normalized)
    reasons: list[str] = []
    score = 0
    line_count = len(normalized.splitlines())

    if language != "unknown":
        score += 12
        reasons.append("identified-language")
    if line_count >= 12:
        score += 8
        reasons.append("substantial-length")
    if line_count >= 40:
        score += 8
        reasons.append("project-scale-fragment")
    if re.search(r"\b(?:def|class|function|process|fn|func)\b", normalized):
        score += 10
        reasons.append("declares-behavior")
    if re.search(r"\b(?:test_|assert|unittest|pytest|#\[test\])", normalized):
        score += 8
        reasons.append("contains-tests")
    if re.search(r"(?:argparse|clap::|fn main|if __name__|getopts)", normalized):
        score += 7
        reasons.append("entry-point")
    if status == "valid":
        score += 12
        reasons.append("syntax-valid")
    elif status == "invalid":
        score -= 16
        reasons.append("syntax-invalid")
    if not complete:
        score -= 10
        reasons.append("unterminated-fence")
    placeholder_count = sum(bool(pattern.search(normalized)) for pattern in PLACEHOLDER_PATTERNS)
    if placeholder_count:
        score -= placeholder_count * 7
        reasons.append("contains-placeholders")
    if len(normalized.strip()) < 40:
        score -= 15
        reasons.append("too-short")
    if flags:
        reasons.append("requires-sensitive-data-review")

    return ScoredCode(
        language=language,
        extension=EXTENSIONS.get(language, ".txt"),
        score=max(0, min(100, score)),
        syntax_status=status,
        sensitivity_flags=flags,
        reasons=tuple(reasons),
    )
