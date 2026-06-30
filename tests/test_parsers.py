import unittest
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.io.gemini import GeminiClient
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.io.prompts.mark_scheme_parsing import (
    PARSER_SYSTEM_PROMPT,
    PARSER_USER_PROMPT,
    VERSION,
)


class ParserHookTests(unittest.TestCase):
    def test_gemini_parser_wires_through_client_with_correct_prompt(self):
        mock_client = MagicMock(spec=GeminiClient)
        parser = GeminiMarkSchemeParser(mock_client)
        self.assertIn("Cambridge IGCSE mark schemes", PARSER_SYSTEM_PROMPT)
        self.assertIn("Extract the following IGCSE mark scheme PDF", PARSER_USER_PROMPT)
        self.assertEqual(VERSION, "3")
        self.assertIn("questions", MarkScheme.model_json_schema()["properties"])
        self.assertIs(parser._client, mock_client)


if __name__ == "__main__":
    unittest.main()
