import unittest

from agents.model_text import public_text


class PublicTextTests(unittest.TestCase):
    def test_drops_reasoning_blocks_and_inline_tags(self):
        message = {"content": [
            {"reasoningContent": {"reasoningText": {"text": "internal"}}},
            {"text": "<thinking>private"},
            {"text": "notes</thinking> Les cours ont progressé."},
        ]}
        self.assertEqual(public_text(message), "Les cours ont progressé.")

    def test_drops_unclosed_thinking(self):
        self.assertEqual(public_text({"content": [{"text": "<thinking>Incomplete"}]}), "")
