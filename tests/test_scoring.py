from __future__ import annotations

import unittest

from promptquarry.scoring import analyze_code, infer_language, normalize_code


class ScoringTests(unittest.TestCase):
    def test_label_alias_wins(self) -> None:
        self.assertEqual(infer_language("py", "x = 1"), "python")
        self.assertEqual(infer_language("rs", "fn main() {}"), "rust")

    def test_infers_unlabelled_languages(self) -> None:
        self.assertEqual(infer_language("", "use std::path::Path;\nfn main() {}"), "rust")
        self.assertEqual(infer_language("", "#!/bin/bash\nset -euo pipefail"), "bash")

    def test_valid_python_scores_above_invalid_python(self) -> None:
        valid = "import argparse\n\ndef main() -> None:\n    print('ok')\n"
        invalid = "def main(:\n    pass\n"
        valid_result = analyze_code("python", valid)
        invalid_result = analyze_code("python", invalid)
        self.assertEqual(valid_result.syntax_status, "valid")
        self.assertEqual(invalid_result.syntax_status, "invalid")
        self.assertGreater(valid_result.score, invalid_result.score)

    def test_flags_likely_secrets_and_private_paths(self) -> None:
        code = (
            "email = 'person@example.com'\n"
            "api_key = 'not-a-real-secret'\n"
            "path = '/Users/alice/project'\n"
        )
        flags = analyze_code("python", code).sensitivity_flags
        self.assertEqual(
            flags,
            ("email-address", "mac-home-path", "credential-assignment"),
        )

    def test_normalization_stabilizes_hash_input(self) -> None:
        self.assertEqual(normalize_code("\nvalue = 1  \r\n\r\n"), "value = 1\n")

    def test_unterminated_fence_is_penalized(self) -> None:
        code = "def useful() -> int:\n    return 42\n"
        self.assertGreater(
            analyze_code("python", code, complete=True).score,
            analyze_code("python", code, complete=False).score,
        )


if __name__ == "__main__":
    unittest.main()
