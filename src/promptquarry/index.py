"""Atomic SQLite indexing for recovered conversation code."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from promptquarry.content import (
    iter_messages,
    message_content_type,
    message_role,
    text_content,
)
from promptquarry.markdown import CodeFence, iter_code_fences
from promptquarry.scoring import analyze_code, normalize_code
from promptquarry.streaming import iter_archive_conversations

SCHEMA_VERSION = 1
TITLE_POLICIES = frozenset({"clear", "hash", "drop"})

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = NORMAL;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    source_member TEXT NOT NULL
);

CREATE TABLE code_blocks (
    digest TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    extension TEXT NOT NULL,
    code TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    syntax_status TEXT NOT NULL,
    sensitivity_flags TEXT NOT NULL,
    reasons TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0, 1))
);

CREATE TABLE occurrences (
    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest TEXT NOT NULL REFERENCES code_blocks(digest) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_type TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    start_line INTEGER,
    created_at TEXT,
    source_member TEXT NOT NULL
);

CREATE INDEX code_score_idx ON code_blocks(score DESC);
CREATE INDEX code_language_idx ON code_blocks(language, score DESC);
CREATE INDEX occurrences_digest_idx ON occurrences(digest);
CREATE INDEX occurrences_conversation_idx ON occurrences(conversation_id);
"""


class QuarryError(RuntimeError):
    """Raised when an index cannot be built or queried safely."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    database: str
    conversations: int
    messages: int
    occurrences: int
    unique_blocks: int
    duplicate_occurrences: int
    sensitive_blocks: int
    archive_sha256: str | None


def _utc_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (OSError, TypeError, ValueError):
        return str(value)


def _sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _conversation_id(conversation: dict[str, Any]) -> str:
    explicit = conversation.get("id") or conversation.get("conversation_id")
    if explicit:
        return str(explicit)
    stable = json.dumps(conversation, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "generated-" + hashlib.sha256(stable).hexdigest()[:24]


def _protected_title(title: str, policy: str) -> str:
    if policy == "clear":
        return title or "Untitled"
    if policy == "hash":
        return "sha256:" + hashlib.sha256(title.encode("utf-8")).hexdigest()
    return "[redacted]"


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise QuarryError("count query returned no row")
    return int(row[0])


def _message_fences(text: str, content_type: str) -> Iterator[CodeFence]:
    fences = list(iter_code_fences(text))
    if fences:
        yield from fences
    elif content_type == "code" and text.strip():
        yield CodeFence("", text, 1, True, 1)


def _insert_block(
    connection: sqlite3.Connection,
    *,
    code: str,
    fence: CodeFence,
    conversation_id: str,
    message_id: str,
    role: str,
    content_type: str,
    created_at: str | None,
    source_member: str,
) -> tuple[bool, bool]:
    normalized = normalize_code(code)
    if not normalized:
        return False, False
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    analysis = analyze_code(fence.label, normalized, complete=fence.complete)
    existing = connection.execute(
        "SELECT complete FROM code_blocks WHERE digest = ?", (digest,)
    ).fetchone()
    inserted = existing is None
    if inserted:
        connection.execute(
            """
            INSERT INTO code_blocks(
                digest, language, extension, code, score, syntax_status,
                sensitivity_flags, reasons, line_count, byte_count, complete
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                digest,
                analysis.language,
                analysis.extension,
                normalized,
                analysis.score,
                analysis.syntax_status,
                json.dumps(analysis.sensitivity_flags),
                json.dumps(analysis.reasons),
                len(normalized.splitlines()),
                len(normalized.encode("utf-8")),
                int(fence.complete),
            ),
        )
    elif fence.complete and not bool(existing["complete"]):
        connection.execute(
            "UPDATE code_blocks SET score = ?, reasons = ?, complete = 1 WHERE digest = ?",
            (analysis.score, json.dumps(analysis.reasons), digest),
        )
    connection.execute(
        """
        INSERT INTO occurrences(
            digest, conversation_id, message_id, role, content_type,
            ordinal, start_line, created_at, source_member
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest,
            conversation_id,
            message_id,
            role,
            content_type,
            fence.ordinal,
            fence.start_line,
            created_at,
            source_member,
        ),
    )
    return inserted, bool(analysis.sensitivity_flags)


class QuarryIndex:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.database_path.is_file():
            raise QuarryError(f"index does not exist: {self.database_path}")
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def build(
        self,
        archive_path: Path,
        *,
        title_policy: str = "clear",
        skip_archive_hash: bool = False,
        max_member_bytes: int = 4 * 1024**3,
        max_total_bytes: int = 8 * 1024**3,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> BuildResult:
        if title_policy not in TITLE_POLICIES:
            raise ValueError(f"title_policy must be one of: {', '.join(sorted(TITLE_POLICIES))}")
        archive = archive_path.expanduser().resolve()
        if not archive.is_file():
            raise QuarryError(f"archive does not exist: {archive}")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.database_path.name}.",
            suffix=".tmp",
            dir=self.database_path.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        archive_sha256 = None if skip_archive_hash else _sha256_file(archive)
        counts: Counter[str] = Counter()

        try:
            connection = sqlite3.connect(temporary)
            connection.row_factory = sqlite3.Row
            try:
                connection.executescript(SCHEMA)
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    (
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("source_archive", archive.name),
                        ("archive_sha256", archive_sha256 or "skipped"),
                        ("title_policy", title_policy),
                        ("built_at", datetime.now(timezone.utc).isoformat()),
                    ),
                )
                for source_member, conversation in iter_archive_conversations(
                    archive,
                    max_member_bytes=max_member_bytes,
                    max_total_bytes=max_total_bytes,
                ):
                    conversation_id = _conversation_id(conversation)
                    title = _protected_title(text_content(conversation.get("title")), title_policy)
                    connection.execute(
                        """
                        INSERT INTO conversations(
                            conversation_id, title, created_at, updated_at, source_member
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(conversation_id) DO UPDATE SET
                            title = excluded.title,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at,
                            source_member = excluded.source_member
                        """,
                        (
                            conversation_id,
                            title,
                            _utc_timestamp(conversation.get("create_time")),
                            _utc_timestamp(conversation.get("update_time")),
                            source_member,
                        ),
                    )
                    counts["conversations"] += 1
                    for message in iter_messages(conversation):
                        counts["messages"] += 1
                        message_id = str(message.get("id") or "unknown")
                        role = message_role(message)
                        content_type = message_content_type(message)
                        content = text_content(message.get("content"))
                        created_at = _utc_timestamp(message.get("create_time"))
                        for fence in _message_fences(content, content_type):
                            inserted, sensitive = _insert_block(
                                connection,
                                code=fence.code,
                                fence=fence,
                                conversation_id=conversation_id,
                                message_id=message_id,
                                role=role,
                                content_type=content_type,
                                created_at=created_at,
                                source_member=source_member,
                            )
                            if not normalize_code(fence.code):
                                continue
                            counts["occurrences"] += 1
                            counts["unique_blocks"] += int(inserted)
                            counts["sensitive_blocks"] += int(inserted and sensitive)
                    if counts["conversations"] % 250 == 0:
                        connection.commit()
                        if progress is not None:
                            progress(
                                counts["conversations"],
                                counts["messages"],
                                counts["occurrences"],
                            )
                connection.commit()
                row = connection.execute("PRAGMA integrity_check").fetchone()
                if row is None or row[0] != "ok":
                    raise QuarryError("SQLite integrity check failed")
            finally:
                connection.close()
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.database_path)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise QuarryError(f"index build failed: {error}") from error

        return BuildResult(
            database=str(self.database_path),
            conversations=counts["conversations"],
            messages=counts["messages"],
            occurrences=counts["occurrences"],
            unique_blocks=counts["unique_blocks"],
            duplicate_occurrences=counts["occurrences"] - counts["unique_blocks"],
            sensitive_blocks=counts["sensitive_blocks"],
            archive_sha256=archive_sha256,
        )

    def summary(self) -> dict[str, Any]:
        with self.connect() as connection:
            languages = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT language, COUNT(*) AS unique_blocks,
                           ROUND(AVG(score), 1) AS average_score,
                           MAX(score) AS maximum_score
                    FROM code_blocks GROUP BY language
                    ORDER BY unique_blocks DESC, language
                    """
                )
            ]
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            return {
                "database": str(self.database_path),
                "conversations": _scalar(connection, "SELECT COUNT(*) FROM conversations"),
                "occurrences": _scalar(connection, "SELECT COUNT(*) FROM occurrences"),
                "unique_blocks": _scalar(connection, "SELECT COUNT(*) FROM code_blocks"),
                "sensitive_blocks": _scalar(
                    connection, "SELECT COUNT(*) FROM code_blocks WHERE sensitivity_flags != '[]'"
                ),
                "languages": languages,
                "metadata": metadata,
            }

    def review(
        self,
        *,
        limit: int = 25,
        languages: tuple[str, ...] = (),
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        where = ["1 = 1"]
        parameters: list[Any] = []
        if languages:
            placeholders = ", ".join("?" for _ in languages)
            where.append(f"b.language IN ({placeholders})")
            parameters.extend(languages)
        if not include_sensitive:
            where.append("b.sensitivity_flags = '[]'")
        parameters.append(limit)
        query = f"""
            SELECT b.digest, b.language, b.extension, b.score, b.syntax_status,
                   b.sensitivity_flags, b.reasons, b.line_count, b.byte_count,
                   b.complete, COUNT(o.occurrence_id) AS occurrences,
                   MIN(c.title) AS example_title
            FROM code_blocks AS b
            JOIN occurrences AS o USING (digest)
            JOIN conversations AS c USING (conversation_id)
            WHERE {" AND ".join(where)}
            GROUP BY b.digest
            ORDER BY b.score DESC, b.line_count DESC, b.digest
            LIMIT ?
        """
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(query, parameters)]
        for row in rows:
            row["sensitivity_flags"] = json.loads(str(row["sensitivity_flags"]))
            row["reasons"] = json.loads(str(row["reasons"]))
            row["complete"] = bool(row["complete"])
        return rows

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query cannot be empty")
        if limit < 1:
            raise ValueError("limit must be positive")
        pattern = f"%{query}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT b.digest, b.language, b.score, b.line_count,
                       c.title, o.role, o.message_id
                FROM code_blocks AS b
                JOIN occurrences AS o USING (digest)
                JOIN conversations AS c USING (conversation_id)
                WHERE b.code LIKE ? OR c.title LIKE ?
                ORDER BY b.score DESC, b.digest LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def export(
        self,
        output_directory: Path,
        *,
        minimum_score: int = 20,
        languages: tuple[str, ...] = (),
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        if not 0 <= minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100")
        output = output_directory.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        where = ["b.score >= ?"]
        parameters: list[Any] = [minimum_score]
        if languages:
            placeholders = ", ".join("?" for _ in languages)
            where.append(f"b.language IN ({placeholders})")
            parameters.extend(languages)
        if not include_sensitive:
            where.append("b.sensitivity_flags = '[]'")
        query = f"""
            SELECT b.*, COUNT(o.occurrence_id) AS occurrences,
                   MIN(c.title) AS example_title
            FROM code_blocks AS b
            JOIN occurrences AS o USING (digest)
            JOIN conversations AS c USING (conversation_id)
            WHERE {" AND ".join(where)}
            GROUP BY b.digest
            ORDER BY b.score DESC, b.line_count DESC, b.digest
        """
        manifest: list[dict[str, Any]] = []
        with self.connect() as connection:
            for row in connection.execute(query, parameters):
                folder = output / str(row["language"])
                folder.mkdir(exist_ok=True)
                filename = (
                    f"score-{int(row['score']):02d}_{str(row['digest'])[:16]}{row['extension']}"
                )
                destination = folder / filename
                _private_write(destination, str(row["code"]))
                manifest.append(
                    {
                        "digest": row["digest"],
                        "score": row["score"],
                        "language": row["language"],
                        "syntax_status": row["syntax_status"],
                        "line_count": row["line_count"],
                        "byte_count": row["byte_count"],
                        "complete": bool(row["complete"]),
                        "occurrences": row["occurrences"],
                        "example_title": row["example_title"],
                        "path": str(destination.relative_to(output)),
                    }
                )
        manifest_path = output / "manifest.json"
        _private_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        return {
            "output_directory": str(output),
            "exported_blocks": len(manifest),
            "manifest": str(manifest_path),
            "excluded_sensitive_by_default": not include_sensitive,
        }


def _private_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def build_result_json(result: BuildResult) -> str:
    return json.dumps(asdict(result), indent=2, sort_keys=True)
