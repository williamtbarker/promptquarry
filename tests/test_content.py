from __future__ import annotations

import unittest

from promptquarry.content import (
    iter_messages,
    message_content_type,
    message_role,
    text_content,
)


class ContentTests(unittest.TestCase):
    def test_flattens_nested_content_parts(self) -> None:
        content = {"content_type": "text", "parts": ["one", {"text": "two"}, None]}
        self.assertEqual(text_content(content), "one\ntwo")

    def test_iterates_only_real_messages(self) -> None:
        conversation = {
            "mapping": {
                "one": {"message": {"content": {"parts": ["hello"]}}},
                "two": {"message": None},
                "three": "invalid",
            }
        }
        messages = list(iter_messages(conversation))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], "one")

    def test_extracts_role_and_content_type(self) -> None:
        message = {
            "author": {"role": "assistant"},
            "content": {"content_type": "code", "parts": ["print()"]},
        }
        self.assertEqual(message_role(message), "assistant")
        self.assertEqual(message_content_type(message), "code")


if __name__ == "__main__":
    unittest.main()
