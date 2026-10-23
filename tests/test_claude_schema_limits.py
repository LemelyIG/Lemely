"""Response schemas Claude's structured outputs cannot take go the prompt-JSON route."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import anthropic
from pydantic import BaseModel

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.providers.anthropic_adapter import AnthropicAdapter
from lemely.io.providers.claude_schema import (
    CLAUDE_MAX_OPTIONAL_PARAMS,
    extract_json,
    json_instruction,
    needs_prompt_json,
    recursive_definitions,
    schema_budget,
)
from lemely.runtime.errors import ParseError
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message

_MODEL = "claude-haiku-5-5"
_CORPUS_MS = Path(__file__).parent.parent / "corpus" / "mark-schemes" / "0580_s21_ms_31.json"


class _Node(BaseModel):
    name: str
    children: list[_Node] = []


def _wide_model() -> type[BaseModel]:
    fields = {f"f{i}": (str | None, None) for i in range(CLAUDE_MAX_OPTIONAL_PARAMS + 1)}
    from pydantic import create_model

    return create_model("Wide", **fields)  # type: ignore[call-overload]


def _call(schema: type[BaseModel], reply: str) -> tuple[_FakeAnthropic, str]:
    fake = _FakeAnthropic(_message(reply))
    out = AnthropicAdapter(fake).complete(
        model=_MODEL,
        system_prompt="sys",
        user_prompt="user",
        response_schema=schema,
        thinking=None,
        cache_prefix=None,
    )
    return fake, out.text


class RoutingTests(unittest.TestCase):
    def test_recursive_model_is_detected(self) -> None:
        sent = anthropic.transform_schema(_Node)
        self.assertEqual(recursive_definitions(sent), {"_Node"})
        self.assertTrue(needs_prompt_json(sent))

    def test_mark_scheme_is_recursive_and_over_limits(self) -> None:
        sent = anthropic.transform_schema(MarkScheme)
        self.assertEqual(recursive_definitions(sent), {"Question"})
        optional, union = schema_budget(sent)
        self.assertGreater(optional, 24)
        self.assertGreater(union, 16)

    def test_within_limit_schema_keeps_structured_outputs(self) -> None:
        self.assertFalse(needs_prompt_json(anthropic.transform_schema(AIMarkResponse)))
        fake, _ = _call(AIMarkResponse, json.dumps(_VALID_MARK))
        (call,) = fake.messages.calls
        self.assertEqual(
            call["output_config"]["format"]["schema"], anthropic.transform_schema(AIMarkResponse)
        )

    def test_over_optional_cap_goes_prompt_json(self) -> None:
        wide = _wide_model()
        self.assertTrue(needs_prompt_json(anthropic.transform_schema(wide)))

    def test_recursive_request_has_no_format_and_schema_in_system(self) -> None:
        fake, text = _call(_Node, '```json\n{"name": "a", "children": []}\n```')
        (call,) = fake.messages.calls
        self.assertNotIn("format", call["output_config"])
        system = "".join(b["text"] for b in call["system"])
        self.assertIn("JSON Schema", system)
        self.assertIn('"children"', system)
        self.assertEqual(_Node.model_validate_json(text), _Node(name="a"))

    def test_mark_scheme_request_has_no_ref_cycle_in_format(self) -> None:
        fake, _ = _call(MarkScheme, "{}")
        (call,) = fake.messages.calls
        self.assertNotIn("format", call["output_config"])
        self.assertNotIn("$defs", json.dumps(call["output_config"]))

    def test_invalid_json_raises_parse_error_via_generate(self) -> None:
        adapter = AnthropicAdapter(_FakeAnthropic(_message("sorry, no json here")))
        with self.assertRaises(ParseError):
            adapter.generate(
                model=_MODEL,
                system_prompt="sys",
                user_prompt="user",
                response_schema=_Node,
                thinking=None,
                cache_prefix=None,
            )

    @unittest.skipUnless(_CORPUS_MS.is_file(), "corpus mark scheme not present")
    def test_real_mark_scheme_roundtrips_through_prompt_route(self) -> None:
        raw = _CORPUS_MS.read_text(encoding="utf-8")
        reply = f"Here you go:\n```json\n{raw}\n```"
        _fake, text = _call(MarkScheme, reply)
        self.assertEqual(MarkScheme.model_validate_json(text), MarkScheme.model_validate_json(raw))


class HelperTests(unittest.TestCase):
    def test_extract_json_variants(self) -> None:
        self.assertEqual(extract_json('{"a": 1}'), '{"a": 1}')
        self.assertEqual(extract_json('```\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(extract_json('Sure! {"a": {"b": 2}} done'), '{"a": {"b": 2}}')
        self.assertEqual(extract_json("no braces"), "no braces")

    def test_instruction_embeds_schema(self) -> None:
        self.assertIn('"title":"_Node"', json_instruction(_Node.model_json_schema()))
