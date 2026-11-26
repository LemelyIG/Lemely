"""The web client's header allow-list must match the backend's adopted routes, both ways.

``web/src/lib/actingTeacher.ts`` lists the routes that get ``X-Lemely-Acting-Teacher``
(``ADOPTED_ROUTES``). The list is hand-written in TypeScript, so nothing keeps it honest when a
route adopts ``require_team_permission`` (the client would send an assistant's request as
themselves) or when a route that must stay lead-only happens to match a pattern (the client
would send the header where the server must never see it). This reads the TypeScript list and
checks it against the backend registry in ``tests/test_team_permission_adoption.py``, which
``test_adopted_routes_are_exactly_the_registry`` already ties to the real route table.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_team_permission_adoption import ADOPTED, _wired

ACTING_TS = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "actingTeacher.ts"

_PARAM = "{}"


def _frontend_templates() -> list[str]:
    source = ACTING_TS.read_text(encoding="utf-8")
    match = re.search(r"export const ADOPTED_ROUTES[^=]*=\s*\[(.*?)\n\]", source, re.DOTALL)
    assert match is not None, "ADOPTED_ROUTES not found in actingTeacher.ts"
    return re.findall(r'^\s*"(/[^"]*)"', match.group(1), re.MULTILINE)


def _shape(path: str) -> str:
    """A path with every parameter segment replaced by one marker, for set comparison."""
    segments = []
    for segment in path.split("/"):
        is_param = segment.startswith(":") or (segment.startswith("{") and segment.endswith("}"))
        segments.append(_PARAM if is_param else segment)
    return "/".join(segments)


def _backend_shapes() -> set[str]:
    return {_shape(path.removeprefix("/api")) for _, path in ADOPTED}


def _frontend_patterns() -> list[re.Pattern[str]]:
    patterns = []
    for template in _frontend_templates():
        parts = [r"[^/]+" if s.startswith(":") else re.escape(s) for s in template.split("/")]
        patterns.append(re.compile("^" + "/".join(parts) + "$"))
    return patterns


def test_the_typescript_list_was_actually_read() -> None:
    templates = _frontend_templates()
    assert len(templates) >= 40
    assert len(set(templates)) == len(templates)


def test_frontend_paths_equal_the_backend_adopted_paths() -> None:
    frontend = {_shape(t) for t in _frontend_templates()}
    backend = _backend_shapes()
    assert frontend - backend == set(), "client sends the header on routes the server never adopted"
    assert backend - frontend == set(), "adopted routes the client would send without the header"


def test_no_wired_route_matches_a_frontend_pattern_unless_it_is_adopted() -> None:
    patterns = _frontend_patterns()
    offenders: list[tuple[str, str]] = []
    for method, path in _wired():
        if not path.startswith("/api/") or (method, path) in ADOPTED:
            continue
        concrete = re.sub(r"\{[^}]+\}", "abc123", path.removeprefix("/api"))
        if any(p.match(concrete) for p in patterns):
            offenders.append((method, path))
    assert offenders == [], "routes the client would send the header to, that are not adopted"
