"""When a response schema can go through Claude's ``output_config.format``.

Claude structured outputs have documented limits
(https://platform.claude.com/docs/en/build-with-claude/structured-outputs,
"JSON Schema limitations" and "Limits"): no recursive schemas, at most 24
optional parameters and 16 union-type (anyOf / type-array) parameters across
the schema, and an internal compiled-grammar cap that answers 400 "The compiled
grammar is too large". The mark-scheme model (``MarkScheme`` / ``Question``,
which nests itself through ``parts``) breaks all of them: a live probe
(2026-10-23, claude-haiku-5-5) was refused at 400 even with the recursion
unrolled (to 5 levels and to 1 level), so unrolling cannot help. For such a
schema the adapter sends no ``output_config.format``; it asks for JSON in the
system prompt (:func:`json_instruction`) and the reply is validated by the
original pydantic model, as on the structured path.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Documented caps across a whole structured-output schema.
CLAUDE_MAX_OPTIONAL_PARAMS = 24
CLAUDE_MAX_UNION_PARAMS = 16

_REF_PREFIX = "#/$defs/"

Schema = dict[str, Any]  # type: ignore[explicit-any]


def _refs(node: object) -> set[str]:
    """Definition names ``node`` references (``#/$defs/Name``)."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref[len(_REF_PREFIX) :])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _refs(item)
    return found


def recursive_definitions(schema: Schema) -> set[str]:
    """Names of ``$defs`` that can reach themselves."""
    defs: Schema = schema.get("$defs", {})
    graph = {name: _refs(body) for name, body in defs.items()}
    recursive: set[str] = set()
    for start in graph:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            name = stack.pop()
            if name == start:
                recursive.add(start)
                break
            if name in seen or name not in graph:
                continue
            seen.add(name)
            stack.extend(graph[name])
    return recursive


def schema_budget(schema: Schema) -> tuple[int, int]:
    """(optional parameters, union parameters) counted over every object in ``schema``."""
    optional = union = 0
    objects: list[Schema] = [schema, *schema.get("$defs", {}).values()]
    for obj in objects:
        required = set(obj.get("required", []))
        for prop, sub in obj.get("properties", {}).items():
            if prop not in required:
                optional += 1
            if "anyOf" in sub or isinstance(sub.get("type"), list):
                union += 1
    return optional, union


def exceeds_claude_limits(schema: Schema) -> bool:
    """Whether ``schema`` is over the documented optional / union parameter caps."""
    optional, union = schema_budget(schema)
    return optional > CLAUDE_MAX_OPTIONAL_PARAMS or union > CLAUDE_MAX_UNION_PARAMS


def needs_prompt_json(schema: Schema) -> bool:
    """Whether ``schema`` cannot be sent as ``output_config.format``.

    True for a recursive schema or one over the documented optional / union caps.
    """
    return bool(recursive_definitions(schema)) or exceeds_claude_limits(schema)


def json_instruction(schema: Schema) -> str:
    """System text asking for one JSON object matching ``schema`` and nothing else."""
    return (
        "Reply with a single JSON object that conforms to the following JSON Schema, "
        "and nothing else: no prose, no markdown fences. Include every required "
        "property; use null for an absent optional value.\n\nJSON Schema:\n"
        + json.dumps(schema, separators=(",", ":"), sort_keys=True)
    )


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def extract_json(text: str) -> str:
    """The JSON object in a free-text reply: fences stripped, else first '{' to last '}'.

    A reply with no braces comes back unchanged so the pydantic parse reports it.
    """
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return stripped
    return stripped[start : end + 1]
