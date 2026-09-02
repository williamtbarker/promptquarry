from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from promptquarry.index import QuarryError, QuarryIndex
from tests.helpers import conversation, message, write_archive

PYTHON_CODE = """import argparse

def greet(name: str) -> str:
    return f"Hello, {name}!"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    arguments = parser.parse_args()
    print(greet(arguments.name))

if __name__ == "__main__":
    main()
"""

RUST_CODE = """use std::env;

fn greeting(name: &str) -> String {
    format!("Hello, {name}!")
}

fn main() {
    let name = env::args().nth(1).unwrap_or_else(|| "world".to_string());
    println!("{}", greeting(&name));
}
"""

SENSITIVE_CODE = "email = 'person@example.com'\napi_key = 'example-secret-value'\n"


def sample_conversations() -> list[dict[str, object]]:
    return [
        conversation(
            "conversation-one",
            "CLI prototype",
            [
                message("m1", "assistant", f"```python\n{PYTHON_CODE}```"),
                message("m2", "user", f"```python\n{PYTHON_CODE}```"),
                message("m3", "assistant", RUST_CODE, content_type="code"),
            ],
        ),
        conversation(
            "conversation-two",
            "Credentials example",
            [message("m4", "assistant", f"```python\n{SENSITIVE_CODE}```")],
        ),
    ]


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.archive = write_archive(self.root / "export.zip", sample_conversations())
        self.database = self.root / "quarry.sqlite3"
        self.quarry = QuarryIndex(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_builds_atomic_deduplicated_index(self) -> None:
        result = self.quarry.build(self.archive)
        self.assertEqual(result.conversations, 2)
        self.assertEqual(result.messages, 4)
        self.assertEqual(result.occurrences, 4)
        self.assertEqual(result.unique_blocks, 3)
        self.assertEqual(result.duplicate_occurrences, 1)
        self.assertEqual(result.sensitive_blocks, 1)
        self.assertEqual(len(result.archive_sha256 or ""), 64)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_summary_reports_languages_and_provenance(self) -> None:
        self.quarry.build(self.archive, skip_archive_hash=True)
        summary = self.quarry.summary()
        self.assertEqual(summary["unique_blocks"], 3)
        self.assertEqual(summary["metadata"]["archive_sha256"], "skipped")
        languages = {row["language"]: row["unique_blocks"] for row in summary["languages"]}
        self.assertEqual(languages, {"python": 2, "rust": 1})

    def test_review_hides_sensitive_candidates_by_default(self) -> None:
        self.quarry.build(self.archive)
        safe = self.quarry.review(limit=10)
        all_candidates = self.quarry.review(limit=10, include_sensitive=True)
        self.assertEqual(len(safe), 2)
        self.assertEqual(len(all_candidates), 3)
        self.assertTrue(all(not row["sensitivity_flags"] for row in safe))

    def test_exports_deduplicated_candidates_and_manifest(self) -> None:
        self.quarry.build(self.archive)
        output = self.root / "candidates"
        result = self.quarry.export(output, minimum_score=0, languages=("python",))
        self.assertEqual(result["exported_blocks"], 1)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest[0]["occurrences"], 2)
        candidate = output / manifest[0]["path"]
        self.assertIn("def greet", candidate.read_text(encoding="utf-8"))
        self.assertEqual(candidate.stat().st_mode & 0o777, 0o600)

    def test_searches_titles_and_code(self) -> None:
        self.quarry.build(self.archive)
        self.assertEqual(self.quarry.search("greet")[0]["language"], "python")
        title_results = self.quarry.search("prototype")
        self.assertEqual({row["language"] for row in title_results}, {"python", "rust"})

    def test_title_policy_can_hash_or_drop_titles(self) -> None:
        self.quarry.build(self.archive, title_policy="hash")
        with sqlite3.connect(self.database) as connection:
            title = connection.execute("SELECT title FROM conversations LIMIT 1").fetchone()[0]
        self.assertTrue(title.startswith("sha256:"))
        self.quarry.build(self.archive, title_policy="drop")
        with sqlite3.connect(self.database) as connection:
            titles = {row[0] for row in connection.execute("SELECT title FROM conversations")}
        self.assertEqual(titles, {"[redacted]"})

    def test_failed_rebuild_preserves_existing_index(self) -> None:
        self.quarry.build(self.archive)
        broken = self.root / "broken.zip"
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("conversations.json", "[not valid")
        with self.assertRaisesRegex(QuarryError, "index build failed"):
            self.quarry.build(broken)
        self.assertEqual(self.quarry.summary()["unique_blocks"], 3)

    def test_missing_archive_does_not_replace_index(self) -> None:
        self.quarry.build(self.archive)
        with self.assertRaisesRegex(QuarryError, "does not exist"):
            self.quarry.build(self.root / "missing.zip")
        self.assertEqual(self.quarry.summary()["conversations"], 2)

    @unittest.skipIf(os.name == "nt", "POSIX file modes are not available")
    def test_exported_manifest_is_private(self) -> None:
        self.quarry.build(self.archive)
        output = self.root / "private"
        self.quarry.export(output, minimum_score=0)
        self.assertEqual((output / "manifest.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
