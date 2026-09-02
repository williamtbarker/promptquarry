from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from promptquarry.cli import main
from tests.helpers import conversation, message, write_archive


class CliTests(unittest.TestCase):
    def test_end_to_end_cli_workflow(self) -> None:
        code = "def answer() -> int:\n    return 42\n"
        conversations = [
            conversation(
                "one",
                "Answer code",
                [message("m1", "assistant", code, content_type="code")],
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_archive(root / "export.zip", conversations)
            database = root / "quarry.sqlite3"
            output = root / "output"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    main(
                        [
                            "build",
                            str(archive),
                            "--db",
                            str(database),
                            "--skip-archive-hash",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["summary", str(database)]), 0)
                self.assertEqual(main(["review", str(database), "--limit", "5"]), 0)
                self.assertEqual(main(["search", str(database), "answer"]), 0)
                self.assertEqual(
                    main(
                        [
                            "extract",
                            str(database),
                            str(output),
                            "--minimum-score",
                            "0",
                            "--languages",
                            "py",
                        ]
                    ),
                    0,
                )
            decoder = json.JSONDecoder()
            first, _ = decoder.raw_decode(stdout.getvalue())
            self.assertEqual(first["conversations"], 1)
            self.assertTrue((output / "manifest.json").exists())

    def test_rejects_unknown_language_at_parse_time(self) -> None:
        with self.assertRaises(SystemExit):
            main(["review", "missing.sqlite3", "--languages", "brainfuck"])


if __name__ == "__main__":
    unittest.main()
