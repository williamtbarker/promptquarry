"""Bounded-memory readers for JSON arrays inside ZIP archives."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

CONVERSATION_MEMBER = re.compile(r"conversations(?:-\d+)?\.json$")


class ArchiveFormatError(ValueError):
    """Raised when an archive does not match the supported export structure."""


def _read_more(handle: TextIO, buffer: str, position: int, chunk_size: int) -> tuple[str, int]:
    remainder = buffer[position:]
    chunk = handle.read(chunk_size)
    return remainder + chunk, 0


def iter_json_array(handle: TextIO, *, chunk_size: int = 64 * 1024) -> Iterator[Any]:
    """Decode a top-level JSON array without loading the complete document."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    started = False
    expect_value = True
    yielded_any = False
    eof = False

    while True:
        if position >= len(buffer) and not eof:
            buffer, position = _read_more(handle, buffer, position, chunk_size)
            eof = not buffer

        while position < len(buffer) and buffer[position].isspace():
            position += 1

        if not started:
            if position >= len(buffer):
                if eof:
                    raise ArchiveFormatError("JSON input is empty")
                buffer, position = _read_more(handle, buffer, position, chunk_size)
                continue
            if buffer[position] != "[":
                raise ArchiveFormatError("conversation JSON must be a top-level array")
            position += 1
            started = True
            continue

        while position < len(buffer) and buffer[position].isspace():
            position += 1
        if position >= len(buffer):
            if eof:
                raise ArchiveFormatError("unterminated JSON array")
            buffer, position = _read_more(handle, buffer, position, chunk_size)
            continue

        token = buffer[position]
        if token == "]":
            if expect_value and yielded_any:
                raise ArchiveFormatError("trailing comma in JSON array")
            position += 1
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer):
                    raise ArchiveFormatError("unexpected content after JSON array")
                if eof:
                    return
                buffer, position = _read_more(handle, buffer, position, chunk_size)
                if not buffer:
                    eof = True
        if not expect_value:
            if token != ",":
                raise ArchiveFormatError("expected a comma between array values")
            position += 1
            expect_value = True
            continue

        while True:
            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError as error:
                if eof:
                    raise ArchiveFormatError(f"invalid JSON array: {error.msg}") from error
                previous_length = len(buffer) - position
                buffer, position = _read_more(handle, buffer, position, chunk_size)
                if len(buffer) == previous_length:
                    eof = True
                continue
            yield value
            yielded_any = True
            position = end
            expect_value = False
            if position > chunk_size * 2:
                buffer = buffer[position:]
                position = 0
            break


def conversation_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = [
        item
        for item in archive.infolist()
        if not item.is_dir() and CONVERSATION_MEMBER.fullmatch(Path(item.filename).name)
    ]
    if not members:
        raise ArchiveFormatError("archive contains no conversations.json files")
    return sorted(members, key=lambda item: item.filename)


def iter_archive_conversations(
    archive_path: Path,
    *,
    max_member_bytes: int = 4 * 1024**3,
    max_total_bytes: int = 8 * 1024**3,
    chunk_size: int = 64 * 1024,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(member_name, conversation)`` pairs without extracting the ZIP."""

    if max_member_bytes < 1:
        raise ValueError("max_member_bytes must be positive")
    if max_total_bytes < 1:
        raise ValueError("max_total_bytes must be positive")
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ArchiveFormatError(f"cannot open archive: {error}") from error
    with archive:
        members = conversation_members(archive)
        if sum(member.file_size for member in members) > max_total_bytes:
            raise ArchiveFormatError(
                "conversation JSON exceeds the configured total uncompressed-size limit"
            )
        for member in members:
            if member.file_size > max_member_bytes:
                raise ArchiveFormatError(
                    f"{member.filename} exceeds the configured uncompressed-size limit"
                )
            try:
                with archive.open(member) as binary:
                    with io.TextIOWrapper(binary, encoding="utf-8") as text:
                        for value in iter_json_array(text, chunk_size=chunk_size):
                            if not isinstance(value, dict):
                                raise ArchiveFormatError(
                                    f"{member.filename} contains a non-object conversation"
                                )
                            yield member.filename, value
            except (UnicodeError, RuntimeError, zipfile.BadZipFile) as error:
                raise ArchiveFormatError(f"cannot read {member.filename}: {error}") from error
