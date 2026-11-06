"""Deploy-config guards for tutor-page indexing (T08; SPEC §b.5, decision row 17, SC-18).

Row 17 makes a listed tutor's public card indexable by default, with a per-tutor
opt-out the Cloudflare worker honours by asking P2 about each card. Three
static files can silently defeat that, each in a different direction:

- ``web/nginx.conf`` (Docker/self-host) has no per-tutor lookup, so every
  ``/tutors`` page must leave it ``noindex, nofollow``. The header has to sit in
  ``location = /index.html``, which the SPA fallback reaches by internal
  redirect, and a location with its own ``add_header`` stops inheriting the
  server's security headers, so that block must repeat them.
- ``web/public/robots.txt`` must never disallow ``/tutors``: a crawler never
  fetches a disallowed page, so it never reads the page's ``X-Robots-Tag``.
- ``web/public/_headers`` must carry no ``/tutors`` rule: if the platform
  applied one to ``ASSETS.fetch`` responses it would mark every card
  ``noindex``.
- ``web/wrangler.jsonc`` must send ``/tutors`` and ``/tutors/*`` through the
  worker, or the lookup never runs.

Expected values are parsed out of SPEC §b.5's text rather than restated here,
so a test cannot agree with a file merely because one hand wrote both.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
TUTOR_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"


# ── SPEC §b.5 ────────────────────────────────────────────────────────────────


def _spec_b5() -> str:
    spec = (REPO / "docs" / "tutoring" / "SPEC.md").read_text(encoding="utf-8")
    start = spec.find("### b.5 ")
    end = spec.find("\n## ", start)
    if start < 0 or end < 0:
        pytest.fail("SPEC §b.5 not found in docs/tutoring/SPEC.md")
    return spec[start:end]


def _from_spec(pattern: str, what: str) -> re.Match[str]:
    match = re.search(pattern, _spec_b5())
    if match is None:
        pytest.fail(f"SPEC §b.5 no longer states {what}; move this parser with the text")
    return match


# ── nginx.conf parsing ───────────────────────────────────────────────────────


def _strip_nginx_comments(conf: str) -> str:
    """Drop ``#`` comments that are not inside a quoted string."""
    out: list[str] = []
    for line in conf.splitlines():
        quote: str | None = None
        kept = []
        for ch in line:
            if quote is None and ch == "#":
                break
            if ch in "\"'":
                quote = None if quote == ch else (ch if quote is None else quote)
            kept.append(ch)
        out.append("".join(kept))
    return "\n".join(out)


@dataclass(frozen=True)
class _Block:
    header: str
    depth: int
    body: str


def _blocks(conf: str) -> list[_Block]:
    """Every ``<header> { <body> }`` block with the brace depth it opens at."""
    text = _strip_nginx_comments(conf)
    found: list[_Block] = []
    stack: list[tuple[int, int]] = []
    statement_start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append((statement_start, i))
            statement_start = i + 1
        elif ch == "}":
            head_start, open_at = stack.pop()
            found.append(
                _Block(
                    header=" ".join(text[head_start:open_at].split()),
                    depth=len(stack),
                    body=text[open_at + 1 : i],
                )
            )
            statement_start = i + 1
        elif ch == ";":
            statement_start = i + 1
    if stack:
        pytest.fail("unbalanced braces in web/nginx.conf")
    return found


def _own_directives(block_body: str) -> list[str]:
    """The block's own ``;``-terminated directives, nested blocks removed.

    Splits on ``;`` outside quotes only: header values such as the HSTS and CSP
    strings carry ``;`` inside their quotes.
    """
    flat = block_body
    while True:
        reduced = re.sub(r"[^;{}]*\{[^{}]*\}", "", flat)
        if reduced == flat:
            break
        flat = reduced
    directives: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in flat:
        if ch == '"':
            in_quote = not in_quote
        if ch == ";" and not in_quote:
            directives.append("".join(current))
            current = []
        else:
            current.append(ch)
    directives.append("".join(current))
    return [" ".join(d.split()) for d in directives if d.strip()]


_ADD_HEADER = re.compile(r'^add_header (\S+) ("(?:[^"\\]|\\.)*"|\S+)( always)?$')


def _add_headers(block_body: str) -> dict[str, tuple[str, bool]]:
    """``name -> (value, always)`` for the block's own ``add_header`` directives."""
    headers: dict[str, tuple[str, bool]] = {}
    for directive in _own_directives(block_body):
        match = _ADD_HEADER.match(directive)
        if match:
            headers[match.group(1)] = (match.group(2).strip('"'), bool(match.group(3)))
    return headers


def _nginx() -> str:
    return (WEB / "nginx.conf").read_text(encoding="utf-8")


def _one_block(blocks: list[_Block], header: str) -> _Block:
    matching = [b for b in blocks if b.header == header]
    assert len(matching) == 1, f"expected one `{header} {{...}}` block in web/nginx.conf"
    return matching[0]


def _map_entries(body: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for directive in _own_directives(body):
        key, _, value = directive.partition(" ")
        entries.append((key, value.strip().strip('"')))
    return entries


def _evaluate_map(entries: list[tuple[str, str]], value: str) -> str:
    """nginx ``map`` semantics: exact keys first, then regexes in order, then default."""
    for key, result in entries:
        if not key.startswith("~") and key != "default" and key == value:
            return result
    for key, result in entries:
        if key.startswith("~*") and re.search(key[2:], value, re.IGNORECASE):
            return result
        if key.startswith("~") and not key.startswith("~*") and re.search(key[1:], value):
            return result
    return dict(entries).get("default", "")


def test_nginx_index_html_sets_x_robots_tag_for_tutors() -> None:
    """Every /tutors page leaves the self-host deploy noindex, nofollow; nothing else does."""
    spec_map = _from_spec(
        r"`map \$request_uri \$robots_tag \{ (.+?) \}`", "the nginx robots map"
    ).group(1)
    spec_entries = _map_entries(spec_map)
    spec_value = _evaluate_map(spec_entries, "/tutors")
    spec_default = dict(spec_entries)["default"]
    spec_directive = _from_spec(
        r"`(add_header X-Robots-Tag \$robots_tag always);`"
        r" \*\*inside `location = /index\.html`\*\*",
        "where the robots header goes",
    ).group(1)
    # The rule the map serves, stated in the same SPEC bullet.
    _from_spec(r"Every `/tutors\*` page stays `noindex, nofollow`", "the self-host rule")
    assert spec_value == "noindex, nofollow"

    blocks = _blocks(_nginx())
    robots_maps = [b for b in blocks if b.header == "map $request_uri $robots_tag"]
    assert len(robots_maps) == 1, "web/nginx.conf needs one `map $request_uri $robots_tag` block"
    assert robots_maps[0].depth == 0, "`map` belongs to the http context, outside `server`"
    entries = _map_entries(robots_maps[0].body)
    assert dict(entries).get("default") == spec_default

    sample_tutor_uris = [
        "/tutors",
        "/tutors/",
        f"/tutors/{TUTOR_ID}",
        f"/tutors/{TUTOR_ID}/reviews",
        "/tutors/not-a-uuid",
    ]
    # The SPEC's own regex covers these, so the conf must too.
    for uri in sample_tutor_uris:
        assert _evaluate_map(spec_entries, uri) == spec_value
        assert _evaluate_map(entries, uri) == spec_value, uri
    # "Every /tutors page": the request line keeps its query string, and the
    # SPA's router matches paths case-insensitively, so these are tutor pages too.
    for uri in [
        "/tutors?subject=physics",
        f"/tutors/{TUTOR_ID}?ref=search",
        "/TUTORS",
        f"/Tutors/{TUTOR_ID.upper()}",
    ]:
        assert _evaluate_map(entries, uri) == spec_value, uri
    for uri in [
        "/",
        "/index.html",
        "/tutorsx",
        "/tutoring",
        "/student/tutors",
        "/api/public/tutors",
        f"/api/tutors/{TUTOR_ID}",
    ]:
        assert _evaluate_map(entries, uri) == spec_default, uri

    index_html = _one_block(blocks, "location = /index.html")
    assert spec_directive in _own_directives(index_html.body)
    # No other place sets the header: the map's empty default must stay the
    # only answer for every other page.
    for block in blocks:
        if block is not index_html:
            assert "X-Robots-Tag" not in _add_headers(block.body), block.header


def test_nginx_index_html_repeats_security_headers() -> None:
    """A location with its own add_header stops inheriting, so /index.html restates them."""
    blocks = _blocks(_nginx())
    server = _one_block(blocks, "server")
    server_headers = _add_headers(server.body)
    # SPEC §b.5 calls them "the five security headers".
    _from_spec(r"the five security headers", "the five security headers")
    assert len(server_headers) == 5, server_headers

    index_html = _one_block(blocks, "location = /index.html")
    block_headers = _add_headers(index_html.body)
    for name, (value, always) in server_headers.items():
        assert block_headers.get(name) == (value, always), f"location = /index.html lacks {name}"
    # Its own reason for existing is unchanged.
    assert block_headers.get("Cache-Control") == ("no-cache", False)


# ── robots.txt ───────────────────────────────────────────────────────────────


def _robots_rule_matches(rule: str, path: str) -> bool:
    """RFC 9309 path matching: prefix match, ``*`` any run, a trailing ``$`` anchors."""
    anchored = rule.endswith("$")
    body = rule[:-1] if anchored else rule
    pattern = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.match(pattern + ("$" if anchored else ""), path) is not None


def _disallow_rules(robots: str) -> list[str]:
    rules = []
    for line in robots.splitlines():
        field, _, value = line.split("#", 1)[0].partition(":")
        if field.strip().lower() == "disallow" and value.strip():
            rules.append(value.strip())
    return rules


_TUTOR_PATHS = ["/tutors", f"/tutors/{TUTOR_ID}", "/tutors?subject=physics"]


def test_robots_txt_does_not_disallow_tutors() -> None:
    """A disallowed page's X-Robots-Tag is never read, so /tutors stays crawlable."""
    _from_spec(r"`robots\.txt`\*\* never disallows `/tutors`", "the robots.txt rule")
    robots = (WEB / "public" / "robots.txt").read_text(encoding="utf-8")
    rules = _disallow_rules(robots)
    raw_count = sum(
        1 for line in robots.splitlines() if line.strip().lower().startswith("disallow:")
    )
    # Non-vacuity: the parser saw every Disallow line, and there are some.
    assert rules and len(rules) == raw_count
    assert "/api/" in rules

    for rule in rules:
        for path in _TUTOR_PATHS:
            assert not _robots_rule_matches(rule, path), f"`Disallow: {rule}` blocks {path}"

    # Canary: the matcher flags the shapes that would block a tutor page.
    for blocking in ["/tutors", "/", "/*tutors", "/tut", f"/tutors/{TUTOR_ID}$"]:
        assert any(_robots_rule_matches(blocking, path) for path in _TUTOR_PATHS), blocking


# ── public/_headers ──────────────────────────────────────────────────────────


def _headers_rules(source: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """``_headers`` format: an unindented URL pattern, then indented ``Name: value`` lines."""
    rules: list[tuple[str, list[tuple[str, str]]]] = []
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if not rules:
                pytest.fail(f"header line before any URL pattern in _headers: {line!r}")
            name, _, value = line.strip().partition(":")
            rules[-1][1].append((name.strip(), value.strip()))
        else:
            rules.append((line.strip(), []))
    return rules


def _headers_pattern_matches(pattern: str, path: str) -> bool:
    """Cloudflare ``_headers`` matching: ``*`` is a splat, ``:name`` one segment."""
    parts = []
    for token in re.split(r"(\*|:[A-Za-z]\w*)", pattern):
        if token == "*":
            parts.append(".*")
        elif token.startswith(":"):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(token))
    return re.fullmatch("".join(parts), path) is not None


def _tutor_robots_rules(source: str) -> list[str]:
    """Patterns that name /tutors, or set X-Robots-Tag on a tutor page."""
    offending = []
    for pattern, headers in _headers_rules(source):
        names = {name.lower() for name, _ in headers}
        hits_tutors = any(
            _headers_pattern_matches(pattern, p) for p in ["/tutors", f"/tutors/{TUTOR_ID}"]
        )
        if "tutors" in pattern or (hits_tutors and "x-robots-tag" in names):
            offending.append(pattern)
    return offending


def test_headers_file_has_no_tutors_rule() -> None:
    """A platform-applied /tutors rule would mark every card noindex and defeat row 17."""
    _from_spec(r"`web/public/_headers`\*\* gets \*\*no\*\* `/tutors` rule", "the _headers rule")
    source = (WEB / "public" / "_headers").read_text(encoding="utf-8")
    rules = _headers_rules(source)
    # Non-vacuity: the parser found the catch-all block and its five headers.
    catch_all = [headers for pattern, headers in rules if pattern == "/*"]
    assert len(catch_all) == 1
    assert len(catch_all[0]) == 5

    assert _tutor_robots_rules(source) == []

    # Canary: both shapes that would defeat row 17 are caught.
    assert _tutor_robots_rules(source + "/tutors/*\n  X-Robots-Tag: noindex, nofollow\n") == [
        "/tutors/*"
    ]
    assert _tutor_robots_rules("/*\n  X-Robots-Tag: noindex\n") == ["/*"]


# ── wrangler.jsonc ───────────────────────────────────────────────────────────


def _strip_jsonc_comments(source: str) -> str:
    """Drop ``//`` and ``/* */`` comments outside string literals."""
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(source):
        ch = source[i]
        if in_string:
            out.append(ch)
            if ch == "\\":
                out.append(source[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif source.startswith("//", i):
            i = source.find("\n", i)
            if i < 0:
                break
            continue
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                pytest.fail("unterminated block comment in web/wrangler.jsonc")
            i = end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def test_wrangler_run_worker_first_lists_tutors_paths() -> None:
    """The worker only runs for run_worker_first paths, so /tutors* must be on the list."""
    expected = json.loads(
        _from_spec(r"`run_worker_first` becomes `(\[[^`]+\])`", "the run_worker_first list").group(
            1
        )
    )
    binding = _from_spec(r"binding `(\w+)`", "the assets binding").group(1)
    config = json.loads(_strip_jsonc_comments((WEB / "wrangler.jsonc").read_text(encoding="utf-8")))

    assets = config["assets"]
    assert assets["run_worker_first"] == expected
    assert assets["binding"] == binding
    assert assets["not_found_handling"] == "single-page-application"
    # No deploy target replaces the top-level assets block.
    assert sorted(config["env"]) == ["production", "staging"]
    for name, target in config["env"].items():
        assert "assets" not in target, f"env.{name} overrides assets"
