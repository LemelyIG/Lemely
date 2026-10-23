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


def _objects(node: object) -> list[Schema]:
    """Every object schema under ``node`` that declares ``properties``.

    Walks ``properties``, ``items``, ``anyOf``, ``allOf`` and ``oneOf`` so inline
    objects and array item objects are seen, not only the top level and ``$defs``.
    """
    found: list[Schema] = []
    if not isinstance(node, dict):
        return found
    if isinstance(node.get("properties"), dict):
        found.append(node)
        for sub in node["properties"].values():
            found.extend(_objects(sub))
    items = node.get("items")
    if isinstance(items, dict):
        found.extend(_objects(items))
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in node.get(key, []) or []:
            found.extend(_objects(sub))
    return found


def schema_budget(schema: Schema) -> tuple[int, int]:
    """(optional parameters, union parameters) counted over every object in ``schema``."""
    optional = union = 0
    roots: list[Schema] = [schema, *schema.get("$defs", {}).values()]
    for obj in (o for root in roots for o in _objects(root)):
        required = set(obj.get("required", []))
        for prop, sub in obj["properties"].items():
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


#: Bump when the wording of :func:`json_instruction` / :data:`USER_CLOSING_LINE` changes.
PROMPT_JSON_VERSION = "pj2"

#: Last line of the user turn on the prompt-JSON route.
USER_CLOSING_LINE = "Return only the JSON object described in the system prompt."


def _enum_values(sub: object) -> list[object] | None:
    """Allowed values of a property schema, looking through ``anyOf`` and array items."""
    if not isinstance(sub, dict):
        return None
    if isinstance(sub.get("enum"), list):
        return list(sub["enum"])
    for alt in sub.get("anyOf", []) or []:
        found = _enum_values(alt)
        if found:
            return found
    return _enum_values(sub.get("items"))


def _is_array(sub: dict[str, Any]) -> bool:  # type: ignore[explicit-any]
    return sub.get("type") == "array"


def schema_rules(schema: Schema) -> list[str]:
    """Short rules derived from the top-level properties of ``schema`` (generic)."""
    props: Schema = schema.get("properties", {})
    defs: Schema = schema.get("$defs", {})

    def resolve(sub: Schema) -> Schema:
        if isinstance(sub, dict):
            ref = sub.get("$ref")
            if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
                return resolve(defs.get(ref[len(_REF_PREFIX) :], {}))
            if "items" in sub:
                return {**sub, "items": resolve(sub["items"])}
        return sub

    rules: list[str] = []
    required = [p for p in props if p in set(schema.get("required", []))]
    if required:
        rules.append("Required top-level fields: " + ", ".join(required) + ".")
    arrays = [p for p, sub in props.items() if _is_array(resolve(sub))]
    if arrays:
        rules.append(
            "These fields are lists (use [] when empty, never null): " + ", ".join(arrays) + "."
        )
    for name, sub in props.items():
        values = _enum_values(resolve(sub))
        if values:
            rules.append(
                f"{name} must be one of: " + ", ".join(json.dumps(v) for v in values) + "."
            )
    return rules


def json_instruction(schema: Schema) -> str:
    """System text asking for one JSON object matching ``schema`` and nothing else."""
    rules = schema_rules(schema)
    rule_text = ("Rules:\n" + "\n".join(f"- {r}" for r in rules) + "\n\n") if rules else ""
    return (
        f"[json-route {PROMPT_JSON_VERSION}] Reply with a single JSON object that "
        "conforms to the following JSON Schema, and nothing else: no prose, no markdown "
        "fences. Include every required property. Omit an optional field that has no "
        "value; use null only where the schema explicitly allows null.\n\n"
        + rule_text
        + "JSON Schema:\n"
        + json.dumps(schema, separators=(",", ":"), sort_keys=True)
    )


_FENCED = re.compile(r"```[a-zA-Z]*[ \t]*\n(.*?)```", re.DOTALL)


def _last_object(text: str) -> str | None:
    """Text of the last complete JSON object in ``text`` (scanning every ``{``)."""
    decoder = json.JSONDecoder()
    best: tuple[int, int] | None = None
    pos = text.find("{")
    while pos != -1:
        try:
            obj, end = decoder.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            best = (pos, end)
            pos = text.find("{", end)
        else:
            pos = text.find("{", pos + 1)
    return None if best is None else text[best[0] : best[1]]


def extract_json(text: str) -> str:
    """The JSON object in a free-text reply; the final answer wins.

    Fenced blocks are tried last-first, then the whole text, taking the last complete
    object that decodes to a dict (so a draft followed by a correction yields the
    correction, and braces in surrounding prose are ignored). A reply with no such
    object comes back stripped and unchanged so the pydantic parse reports it.
    """
    stripped = text.strip()
    for block in reversed(_FENCED.findall(stripped)):
        found = _last_object(block)
        if found is not None:
            return found
    found = _last_object(stripped)
    return stripped if found is None else found
