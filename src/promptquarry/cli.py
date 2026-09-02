"""Command-line interface for PromptQuarry."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from promptquarry import __version__
from promptquarry.index import QuarryError, QuarryIndex, build_result_json
from promptquarry.scoring import EXTENSIONS, LANGUAGE_ALIASES


def _languages(value: str) -> tuple[str, ...]:
    languages = []
    for raw in value.split(","):
        language = raw.strip().lower()
        language = LANGUAGE_ALIASES.get(language, language)
        if not language:
            continue
        if language not in EXTENSIONS:
            raise argparse.ArgumentTypeError(f"unsupported language: {raw}")
        languages.append(language)
    if not languages:
        raise argparse.ArgumentTypeError("provide at least one language")
    return tuple(dict.fromkeys(languages))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promptquarry",
        description="Recover and rank code from ChatGPT data-export archives.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build an atomic SQLite recovery index")
    build.add_argument("archive", type=Path, help="ChatGPT data-export ZIP")
    build.add_argument("--db", type=Path, default=Path("promptquarry.sqlite3"))
    build.add_argument(
        "--title-policy",
        choices=("clear", "hash", "drop"),
        default="clear",
        help="how conversation titles are stored in the local index",
    )
    build.add_argument(
        "--skip-archive-hash",
        action="store_true",
        help="avoid a separate full pass over very large archives",
    )
    build.add_argument(
        "--max-member-gib",
        type=float,
        default=4.0,
        help="maximum uncompressed size of one conversation JSON member",
    )
    build.add_argument(
        "--max-total-gib",
        type=float,
        default=8.0,
        help="maximum total uncompressed size of all conversation JSON members",
    )

    summary = subparsers.add_parser("summary", help="summarize an existing index")
    summary.add_argument("database", type=Path)

    review = subparsers.add_parser("review", help="list top candidates without printing code")
    review.add_argument("database", type=Path)
    review.add_argument("--limit", type=int, default=25)
    review.add_argument("--languages", type=_languages, default=())
    review.add_argument("--include-sensitive", action="store_true")

    search = subparsers.add_parser("search", help="search code and stored conversation titles")
    search.add_argument("database", type=Path)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)

    extract = subparsers.add_parser("extract", help="write reviewed candidates and a manifest")
    extract.add_argument("database", type=Path)
    extract.add_argument("output", type=Path)
    extract.add_argument("--minimum-score", type=int, default=20)
    extract.add_argument("--languages", type=_languages, default=())
    extract.add_argument(
        "--include-sensitive",
        action="store_true",
        help="include blocks flagged for credentials, email addresses, or personal paths",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(arguments)
    try:
        if namespace.command == "build":
            if namespace.max_member_gib <= 0 or namespace.max_total_gib <= 0:
                raise ValueError("archive size limits must be positive")
            quarry = QuarryIndex(namespace.db)

            def show_progress(conversations: int, messages: int, occurrences: int) -> None:
                print(
                    f"indexed {conversations:,} conversations, {messages:,} messages, "
                    f"{occurrences:,} code occurrences",
                    file=sys.stderr,
                )

            result = quarry.build(
                namespace.archive,
                title_policy=namespace.title_policy,
                skip_archive_hash=namespace.skip_archive_hash,
                max_member_bytes=int(namespace.max_member_gib * 1024**3),
                max_total_bytes=int(namespace.max_total_gib * 1024**3),
                progress=show_progress,
            )
            print(build_result_json(result))
        elif namespace.command == "summary":
            quarry = QuarryIndex(namespace.database)
            print(json.dumps(quarry.summary(), indent=2, sort_keys=True))
        elif namespace.command == "review":
            quarry = QuarryIndex(namespace.database)
            candidates = quarry.review(
                limit=namespace.limit,
                languages=namespace.languages,
                include_sensitive=namespace.include_sensitive,
            )
            print(json.dumps(candidates, indent=2, ensure_ascii=False))
        elif namespace.command == "search":
            quarry = QuarryIndex(namespace.database)
            print(
                json.dumps(
                    quarry.search(namespace.query, limit=namespace.limit),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif namespace.command == "extract":
            quarry = QuarryIndex(namespace.database)
            export_result = quarry.export(
                namespace.output,
                minimum_score=namespace.minimum_score,
                languages=namespace.languages,
                include_sensitive=namespace.include_sensitive,
            )
            print(json.dumps(export_result, indent=2, sort_keys=True))
        else:
            parser.error(f"unsupported command: {namespace.command}")
    except (OSError, QuarryError, UnicodeError, ValueError) as error:
        parser.exit(1, f"promptquarry: error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
