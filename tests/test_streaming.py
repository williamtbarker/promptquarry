from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from promptquarry.streaming import (
    ArchiveFormatError,
    conversation_members,
    iter_archive_conversations,
    iter_json_array,
)
from tests.helpers import conversation, write_archive


class JsonArrayTests(unittest.TestCase):
    def test_streams_values_across_tiny_chunks(self) -> None:
        values = [{"name": "café", "value": index} for index in range(12)]
        payload = json.dumps(values, ensure_ascii=False)
        self.assertEqual(list(iter_json_array(io.StringIO(payload), chunk_size=3)), values)

    def test_accepts_empty_array_and_whitespace(self) -> None:
        self.assertEqual(list(iter_json_array(io.StringIO(" \n [ ] \t"), chunk_size=1)), [])

    def test_rejects_non_array_document(self) -> None:
        with self.assertRaisesRegex(ArchiveFormatError, "top-level array"):
            list(iter_json_array(io.StringIO('{"conversations": []}')))

    def test_rejects_trailing_comma(self) -> None:
        with self.assertRaisesRegex(ArchiveFormatError, "trailing comma"):
            list(iter_json_array(io.StringIO("[1,]"), chunk_size=2))

    def test_rejects_trailing_content(self) -> None:
        with self.assertRaisesRegex(ArchiveFormatError, "unexpected content"):
            list(iter_json_array(io.StringIO("[] false"), chunk_size=2))


class ArchiveTests(unittest.TestCase):
    def test_finds_nested_and_chunked_members_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "export.zip")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("nested/conversations-001.json", "[]")
                archive.writestr("conversations-000.json", "[]")
                archive.writestr("other.json", "[]")
            with zipfile.ZipFile(path) as archive:
                names = [item.filename for item in conversation_members(archive)]
            self.assertEqual(
                names,
                ["conversations-000.json", "nested/conversations-001.json"],
            )

    def test_yields_conversations_without_extracting_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_archive(
                Path(directory, "export.zip"),
                [conversation("one", "A café", [])],
                member="data/conversations.json",
            )
            records = list(iter_archive_conversations(path, chunk_size=2))
            self.assertEqual(records[0][0], "data/conversations.json")
            self.assertEqual(records[0][1]["title"], "A café")

    def test_enforces_member_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_archive(Path(directory, "export.zip"), [])
            with self.assertRaisesRegex(ArchiveFormatError, "size limit"):
                list(iter_archive_conversations(path, max_member_bytes=1))

    def test_enforces_total_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "export.zip")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("conversations-000.json", "[]")
                archive.writestr("conversations-001.json", "[]")
            with self.assertRaisesRegex(ArchiveFormatError, "total uncompressed"):
                list(iter_archive_conversations(path, max_total_bytes=3))


if __name__ == "__main__":
    unittest.main()
