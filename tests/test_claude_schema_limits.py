"""Response schemas Claude's structured outputs cannot take go the prompt-JSON route."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import anthropic
from pydantic import BaseModel, ValidationError

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import AIMarkResponse
from lemely.io.llm.request import provider_fingerprint
from lemely.io.providers.anthropic_adapter import AnthropicAdapter
from lemely.io.providers.claude_schema import (
    CLAUDE_MAX_OPTIONAL_PARAMS,
    PROMPT_JSON_VERSION,
    USER_CLOSING_LINE,
    extract_json,
    json_instruction,
    json_instruction_for,
    needs_prompt_json,
    prompt_json_for,
    recursive_definitions,
    schema_budget,
    schema_rules,
    sendable_schema,
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


class _Color(BaseModel):
    name: str
    tags: list[str]
    kind: str | None = None
    note: str = ""
    parts: list[_Node] | None = None


class ExtractionTests(unittest.TestCase):
    def test_braces_in_prose(self) -> None:
        self.assertEqual(extract_json('Use {x} like so: {"a": 1} ok'), '{"a": 1}')

    def test_two_objects_last_wins(self) -> None:
        self.assertEqual(extract_json('{"a": 1} then {"a": 2}'), '{"a": 2}')

    def test_draft_fence_then_corrected_fence(self) -> None:
        text = 'draft\n```json\n{"a": 1}\n```\nfixed\n```json\n{"a": 2}\n```'
        self.assertEqual(extract_json(text), '{"a": 2}')

    def test_fence_then_prose_with_brace(self) -> None:
        self.assertEqual(extract_json('```json\n{"a": 1}\n```\nSee set {1, 2}.'), '{"a": 1}')

    def test_truncated_outer_object_is_not_an_inner_object(self) -> None:
        for text in (
            '{"a":1,"inner":{"b":2},"rows":[{"c":3},{"c":4}], "tail":',
            '```json\n{"a":1,"n":{"b":2}\n',
            '[{"a":1},{"a":2}]',
        ):
            self.assertEqual(extract_json(text), text.strip(), text)

    def test_fence_then_correction_in_prose(self) -> None:
        self.assertEqual(extract_json('```json\n{"a":1}\n```\nCorrected: {"a":2}'), '{"a":2}')

    def test_truncated_later_object_voids_earlier_draft(self) -> None:
        text = '{"a":1} then {"a":2,"b":'
        self.assertEqual(extract_json(text), text)

    def test_nested_and_string_braces(self) -> None:
        self.assertEqual(
            extract_json('x {"a": "}{", "b": {"c": 1}} y'), '{"a": "}{", "b": {"c": 1}}'
        )


class CacheTests(unittest.TestCase):
    def test_cached_routing_matches_uncached(self) -> None:
        for model in (MarkScheme, AIMarkResponse, _Node):
            sent = anthropic.transform_schema(model)
            self.assertEqual(sendable_schema(model), sent)
            self.assertEqual(prompt_json_for(model), needs_prompt_json(sent))
            self.assertEqual(
                json_instruction_for(model), json_instruction(model.model_json_schema())
            )

    def test_transform_runs_once_per_class(self) -> None:
        sendable_schema.cache_clear()
        prompt_json_for.cache_clear()
        with patch("anthropic.transform_schema", wraps=anthropic.transform_schema) as spy:
            for _ in range(3):
                prompt_json_for(AIMarkResponse)
            self.assertEqual(spy.call_count, 1)


class InstructionTests(unittest.TestCase):
    def test_nulls_in_non_nullable_optionals_fail_validation(self) -> None:
        # The rationale for "omit": an optional field is not a nullable one.
        with self.assertRaises(ValidationError):
            _Color.model_validate({"name": "r", "tags": [], "note": None})
        _Color.model_validate({"name": "r", "tags": []})

    def test_instruction_says_omit_not_null_for_absent(self) -> None:
        text = json_instruction(_Color.model_json_schema())
        self.assertIn("Omit an optional field", text)
        self.assertNotIn("use null for an absent", text)

    def test_rules_are_derived_from_schema(self) -> None:
        class Shape(BaseModel):
            id: str
            items: list[str]
            level: Literal["low", "high"]

        rules = " ".join(schema_rules(Shape.model_json_schema()))
        self.assertIn("Required top-level fields: id, items, level", rules)
        self.assertIn("items", rules)
        self.assertIn('level must be one of: "low", "high"', rules)
        self.assertIn("Rules:", json_instruction(Shape.model_json_schema()))

    def test_user_turn_closing_line_on_prompt_route_only(self) -> None:
        fake, _ = _call(_Node, '{"name": "a"}')
        (call,) = fake.messages.calls
        self.assertIn(USER_CLOSING_LINE, json.dumps(call["messages"]))
        fake2, _ = _call(AIMarkResponse, json.dumps(_VALID_MARK))
        (call2,) = fake2.messages.calls
        self.assertNotIn(USER_CLOSING_LINE, json.dumps(call2["messages"]))

    def test_version_is_in_system_text(self) -> None:
        self.assertIn(PROMPT_JSON_VERSION, json_instruction(_Node.model_json_schema()))


class BudgetTests(unittest.TestCase):
    def test_inline_and_array_item_objects_are_counted(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "inline": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                },
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"c": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                    },
                },
            },
            "required": ["inline", "rows"],
        }
        self.assertEqual(schema_budget(schema), (3, 1))


def _fp(model: str, schema: type[BaseModel] | None) -> str:
    return provider_fingerprint(
        model,
        max_output_tokens=1000,
        image_token_budget=1500,
        image_floor_px=400,
        image_enhance=False,
        response_schema=schema,
    )


class _Plain(BaseModel):
    name: str
    kind: str | None = None


class CacheKeyTests(unittest.TestCase):
    def test_prompt_json_schema_key_carries_the_version(self) -> None:
        self.assertTrue(_fp(_MODEL, _Node).endswith(f"|pj={PROMPT_JSON_VERSION}"))
        self.assertTrue(_fp(_MODEL, _wide_model()).endswith(f"|pj={PROMPT_JSON_VERSION}"))

    def test_version_bump_changes_the_key(self) -> None:
        before = _fp(_MODEL, _Node)
        with patch("lemely.io.providers.claude_schema.PROMPT_JSON_VERSION", "pj-next"):
            after = _fp(_MODEL, _Node)
        self.assertNotEqual(before, after)
        self.assertTrue(after.endswith("|pj=pj-next"))

    def test_within_limit_schema_key_has_no_pj(self) -> None:
        self.assertNotIn("|pj=", _fp(_MODEL, _Plain))
        self.assertEqual(_fp(_MODEL, _Plain), _fp(_MODEL, None))

    def test_gemini_key_unchanged(self) -> None:
        self.assertEqual(_fp("gemini-2.5-flash", _Node), "")


class ProseBracketTests(unittest.TestCase):
    def test_an_unclosed_bracket_in_prose_after_the_object_is_ignored(self) -> None:
        text = 'Here it is: {"a": 1} (see [note for the reasoning'
        self.assertEqual(extract_json(text), '{"a": 1}')

    def test_an_unclosed_brace_in_prose_is_ignored(self) -> None:
        self.assertEqual(extract_json('{"a": 1} then {x and so on'), '{"a": 1}')

    def test_a_truncated_final_object_is_still_incomplete(self) -> None:
        text = '{"a": 1} {"b": [1, 2'
        self.assertEqual(extract_json(text), text)

    def test_a_closed_prose_bracket_is_skipped_whole(self) -> None:
        for text in (
            """{ 'a': 1, 'b': {"c": 2}}""",
            """{answer: {"a": 1}}""",
            """[see {"a": 1}]""",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_json(text), text)

    def test_a_truncated_json_literal_is_still_incomplete(self) -> None:
        for text in (
            '{"a": 1} [true, 2',
            '{"a": 1} {"b": [true, 2',
            '{"a": 1} [nul',
            '{"a": 1} [true]  [false',
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_json(text), text)

    def test_a_word_starting_with_a_literal_is_prose(self) -> None:
        for word in ("nullable field", "trueness", "falsehood"):
            with self.subTest(word=word):
                self.assertEqual(extract_json('{"a": 1} (see [' + word), '{"a": 1}')
