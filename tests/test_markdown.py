from __future__ import annotations

import unittest

from promptquarry.markdown import iter_code_fences


class MarkdownTests(unittest.TestCase):
    def test_extracts_backtick_and_tilde_fences(self) -> None:
        text = "before\n```python\nprint('one')\n```\nmiddle\n~~~~ rust\nfn main() {}\n~~~~\n"
        blocks = list(iter_code_fences(text))
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].label, "python")
        self.assertEqual(blocks[0].code, "print('one')")
        self.assertEqual(blocks[1].label, "rust")
        self.assertEqual(blocks[1].ordinal, 2)

    def test_preserves_unterminated_final_fence(self) -> None:
        blocks = list(iter_code_fences("text\n```bash\necho hello\n"))
        self.assertEqual(len(blocks), 1)
        self.assertFalse(blocks[0].complete)
        self.assertEqual(blocks[0].start_line, 2)

    def test_longer_opening_requires_matching_closer(self) -> None:
        blocks = list(iter_code_fences("````python\n```\n````\n"))
        self.assertEqual(blocks[0].code, "```")
        self.assertTrue(blocks[0].complete)

    def test_ignores_inline_backticks(self) -> None:
        self.assertEqual(list(iter_code_fences("Use `print()` here.")), [])


if __name__ == "__main__":
    unittest.main()
