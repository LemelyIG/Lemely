import unittest

from lemely_mvp.parsers import GeminiMarkSchemeParser
from models import MarkScheme
from prompts.mark_scheme_parsing import PARSER_SYSTEM_PROMPT, PARSER_USER_PROMPT


class ParserHookTests(unittest.TestCase):
    def test_gemini_parser_uses_existing_prompt_and_loose_mark_scheme_schema(self):
        parser = GeminiMarkSchemeParser(model="gemini-2.5-flash")

        self.assertEqual(parser.model, "gemini-2.5-flash")
        self.assertIn("Cambridge IGCSE mark schemes", PARSER_SYSTEM_PROMPT)
        self.assertIn("Extract the following IGCSE mark scheme PDF", PARSER_USER_PROMPT)
        self.assertIn("questions", MarkScheme.model_json_schema()["properties"])


if __name__ == "__main__":
    unittest.main()
