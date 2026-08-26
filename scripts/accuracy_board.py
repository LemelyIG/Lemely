#!/usr/bin/env python3
"""Board CLI for the Extraction & Marking Accuracy Programme tracker.

The GitHub org project "Lemely Progress" (#1, node id in ``PROJECT_NODE_ID``)
is the single source of truth for programme progress; this script is the
orchestrator's only interface to it. It reads and mutates the board through the
``gh`` CLI (GraphQL for project items and field values, the issue commands for
comments and closing) and encodes the spec's §7 ordering constraints in
``DEPENDENCIES`` so that ``next`` never proposes an issue whose prerequisites
are still open.

H-issue guard: an issue whose title starts with an H-number (H1, H2, H4, H5,
H7, H8, H9, H10) is a HUMAN task. An agent must never close one, never mark it
done, and must block rather than work around it. ``done`` refuses such issues
with exit code 2, and so do ``start`` and ``review`` (an agent has no business
progressing a human task either). ``block`` and ``comment`` stay available so
the orchestrator can surface information on them.

``done`` also acts on issues with **no board item** (ask B17): board membership
is a fact about project hygiene, not about whether an issue is a human task, and
using it as a proxy left every run-generated issue impossible to close by any
sanctioned route. Off-board, no Status is set — there is no item to set one on —
and the human-task guard is enforced directly on the issue's own title *and* its
``owner:human`` label, since off-board that guard stands alone.

Known gap, recorded rather than implied: ``comment`` still requires a board item,
so a finish comment on an off-board issue remains impossible here. B17's ruling
covered ``done`` only.

Alongside the board, ``state get``/``state set``/``state show`` are the only
sanctioned interface to BUILD/ACCURACY-STATE.md's machine-readable header (the
resume-pointer keys the supervisor reads that GitHub cannot hold). The file is
resolved from ``git rev-parse --show-toplevel``, never a hardcoded path, so
this also works run from inside the accuracy worktree.

Exit codes: 0 success · 1 usage/gh failure or nothing ready · 2 H-issue guard.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

OWNER_REPO = "LemelyIG/Lemely"
#: Org project "Lemely Progress" #1 — the only hardcoded GraphQL id. Field ids
#: and single-select option ids are looked up at runtime.
PROJECT_NODE_ID = "PVT_kwDOEQF-VM4BgoX2"
ROOT_EPIC = 23
MILESTONE_EPICS: dict[int, str] = {24: "M0", 35: "M1", 43: "M2", 53: "M3", 54: "M4"}
BLOCKERS_FILE = Path(__file__).resolve().parent.parent / "BUILD" / "BLOCKERS.md"
STATE_FILE_RELATIVE = Path("BUILD") / "ACCURACY-STATE.md"

#: The nine keys BUILD/ACCURACY-STATE.md's header may hold, in the stable order
#: the file documents them in. `state set`/`state get` refuse any other key.
STATE_KEYS: tuple[str, ...] = (
    "run_pointer",
    "worktree",
    "branch",
    "last_run_label",
    "last_run_headline",
    "review_rate",
    "ratchet",
    "spend_usd",
    "in_the_middle_of",
)

#: Spec §7 ordering constraints: issue -> issues that must be CLOSED first.
#: #57 additionally requires human approval via #49 (H4), which an agent can
#: never grant; #59 has no explicit §7 edge but its deliverable needs #44's
#: restored corpus to exist.
DEPENDENCIES: dict[int, tuple[int, ...]] = {
    27: (56, 32, 26),  # M0.3 A/A floor <- fixture repair, fixtures final, cache-bypass seam
    28: (56, 32, 26),  # M0.4 ablation <- fixture repair, fixtures final, pricing/ceiling fix
    36: (33,),  # M1.1 confidence unit <- M0.9 ratchet gate
    46: (31,),  # M2.3 labeller <- M0.7a split mechanism
    47: (31,),  # M2.4 labelling <- M0.7a split mechanism
    57: (44, 49),  # M0.7b split freeze <- M2.1 corpus restore + H4 human approval
    59: (44,),  # M2.5 transfer gap <- M2.1 restored corpus (implicit, not a §7 edge)
}

#: Advisory notes printed alongside `next`; they do not block selection.
CAVEATS: dict[int, str] = {
    25: (
        "Spec §4 sketches a tighter M0 order than §7's edge table "
        "(M0.0 -> M0.1/M0.2 -> M0.8 -> baseline run -> M0.3/M0.4/M0.5); "
        "prefer finishing #56 (M0.0) first."
    ),
    26: (
        "Spec §4 sketches a tighter M0 order than §7's edge table "
        "(M0.0 -> M0.1/M0.2 -> M0.8 -> baseline run -> M0.3/M0.4/M0.5); "
        "prefer finishing #56 (M0.0) first."
    ),
    29: "Spec §4's tighter M0 order places M0.5 after a baseline run exists (after M0.0-M0.8).",
    32: "Spec §4's tighter M0 order places M0.8 after M0.1/M0.2, before any baseline run.",
    39: (
        "Do not start the paper-level-aggregate component until #32 (M0.8) lands: "
        "spec §4 says it requires the is_excerpt marker, though §7 omits that edge."
    ),
}

STATUS_ORDER = ("Backlog", "Ready", "In progress", "In review", "Done")

_H_TITLE = re.compile(r"^H\d+\b")

#: Label marking an issue as human-only. A second, independent marker of the
#: same invariant as the H-number: MISSION 3.5 tasks an agent must never close.
_HUMAN_LABEL = "owner:human"
_M_LEAF = re.compile(r"^M(\d+)\.(\d+)([ab]?)")

ITEMS_QUERY = """
query($cursor: String, $project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content {
            ... on Issue {
              number
              title
              state
              parent { number }
              repository { nameWithOwner }
            }
          }
        }
      }
    }
  }
}
"""

FIELDS_QUERY = """
query($project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      fields(first: 30) {
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""

STATUS_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: { singleSelectOptionId: $option }
    }
  ) { projectV2Item { id } }
}
"""


class BoardError(Exception):
    """A readable failure (gh error, bad response shape, missing issue)."""


@dataclass
class Issue:
    number: int
    title: str
    state: str  # OPEN | CLOSED
    parent: int | None
    status: str | None
    size: str | None
    item_id: str


def _run_gh(args: list[str], stdin_text: str | None = None) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["gh", *args],  # noqa: S607
            capture_output=True,
            text=True,
            input=stdin_text,
            check=False,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise BoardError("the `gh` CLI is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise BoardError(f"gh {args[0]} timed out after 60s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        tail = detail[-400:] if detail else "(no output)"
        raise BoardError(f"gh {' '.join(args[:2])} failed (exit {proc.returncode}): {tail}")
    return proc.stdout


def _fetch_issues() -> dict[int, Issue]:
    """Page through all project items and index the issues by number."""
    issues: dict[int, Issue] = {}
    cursor: str | None = None
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={ITEMS_QUERY}",
            "-f",
            f"project={PROJECT_NODE_ID}",
        ]
        if cursor is not None:
            args += ["-f", f"cursor={cursor}"]
        raw = _run_gh(args)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BoardError(f"gh returned non-JSON: {raw[:200]!r}") from exc
        node = (payload.get("data") or {}).get("node")
        if not node:
            raise BoardError("unexpected GraphQL response shape: no data.node")
        page = node["items"]
        for item in page["nodes"]:
            content = item.get("content") or {}
            if content.get("number") is None:
                continue  # draft item or PR, not an issue
            repo = (content.get("repository") or {}).get("nameWithOwner")
            if repo != OWNER_REPO:
                continue
            fields: dict[str, str] = {}
            for fv in item["fieldValues"]["nodes"]:
                if fv and fv.get("field"):
                    fields[str(fv["field"]["name"])] = str(fv["name"])
            parent = content.get("parent") or {}
            number = int(content["number"])
            issues[number] = Issue(
                number=number,
                title=str(content["title"]),
                state=str(content["state"]),
                parent=int(parent["number"]) if parent.get("number") is not None else None,
                status=fields.get("Status"),
                size=fields.get("Size"),
                item_id=str(item["id"]),
            )
        info = page["pageInfo"]
        if not info["hasNextPage"]:
            return issues
        cursor = str(info["endCursor"])


def _fetch_status_field() -> tuple[str, dict[str, str]]:
    """Return (Status field id, option-name -> option-id), looked up at runtime."""
    raw = _run_gh(
        ["api", "graphql", "-f", f"query={FIELDS_QUERY}", "-f", f"project={PROJECT_NODE_ID}"]
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BoardError(f"gh returned non-JSON: {raw[:200]!r}") from exc
    node = (payload.get("data") or {}).get("node")
    if not node:
        raise BoardError("unexpected GraphQL response shape: no data.node")
    for fld in node["fields"]["nodes"]:
        if fld and fld.get("name") == "Status" and fld.get("options") is not None:
            options = {str(o["name"]): str(o["id"]) for o in fld["options"]}
            return str(fld["id"]), options
    raise BoardError("the project has no single-select Status field")


def _set_status(item_id: str, status_name: str) -> None:
    field_id, options = _fetch_status_field()
    option_id = options.get(status_name)
    if option_id is None:
        raise BoardError(f"Status option {status_name!r} not found; board has {sorted(options)}")
    _run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={STATUS_MUTATION}",
            "-f",
            f"project={PROJECT_NODE_ID}",
            "-f",
            f"item={item_id}",
            "-f",
            f"field={field_id}",
            "-f",
            f"option={option_id}",
        ]
    )


def _post_comment(number: int, body: str) -> None:
    _run_gh(
        ["issue", "comment", str(number), "--repo", OWNER_REPO, "--body-file", "-"],
        stdin_text=body,
    )


def _under_epic(number: int, issues: dict[int, Issue]) -> bool:
    """True when the issue's parent chain reaches the root epic #23."""
    seen: set[int] = set()
    current = issues.get(number)
    while current is not None and current.number not in seen:
        if current.number == ROOT_EPIC:
            return True
        seen.add(current.number)
        current = issues.get(current.parent) if current.parent is not None else None
    return False


def _accuracy_leaves(issues: dict[int, Issue]) -> list[Issue]:
    return [
        issue
        for issue in issues.values()
        if issue.number != ROOT_EPIC
        and issue.number not in MILESTONE_EPICS
        and _under_epic(issue.number, issues)
    ]


def _milestone(issue: Issue) -> str:
    if issue.number == ROOT_EPIC:
        return "epic"
    if issue.number in MILESTONE_EPICS:
        return MILESTONE_EPICS[issue.number]
    match = _M_LEAF.match(issue.title)
    if match:
        return f"M{match.group(1)}"
    if _H_TITLE.match(issue.title):
        return "H"
    return "?"


def _leaf_key(issue: Issue) -> tuple[int, int, str, int]:
    """Sort key: milestone major, then minor, then a/b suffix, then number."""
    match = _M_LEAF.match(issue.title)
    if match:
        return (int(match.group(1)), int(match.group(2)), match.group(3), issue.number)
    if _H_TITLE.match(issue.title):
        return (98, 0, "", issue.number)
    return (99, 0, "", issue.number)


def _unmet_deps(number: int, issues: dict[int, Issue]) -> list[int]:
    unmet: list[int] = []
    for dep in DEPENDENCIES.get(number, ()):
        dep_issue = issues.get(dep)
        if dep_issue is None or dep_issue.state != "CLOSED":
            unmet.append(dep)
    return unmet


def _slug(title: str) -> str:
    stripped = re.sub(r"^[MH]\d+(\.\d+[ab]?)?\s*[—-]\s*", "", title)
    slug = re.sub(r"[^a-z0-9]+", "-", stripped.lower()).strip("-")
    if len(slug) > 40:
        slug = slug[:40].rsplit("-", 1)[0]
    return slug


def _branch(issue: Issue) -> str:
    return f"feature/accuracy-{issue.number}-{_slug(issue.title)}"


def _issue_dict(issue: Issue, extra: dict[str, object] | None = None) -> dict[str, object]:
    base: dict[str, object] = {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "status": issue.status,
        "size": issue.size,
        "milestone": _milestone(issue),
        "parent": issue.parent,
    }
    if extra:
        base.update(extra)
    return base


def cmd_next(as_json: bool) -> int:
    issues = _fetch_issues()
    leaves = _accuracy_leaves(issues)
    ready = [
        leaf
        for leaf in leaves
        if leaf.state == "OPEN" and leaf.status == "Ready" and not _H_TITLE.match(leaf.title)
    ]
    unblocked: list[Issue] = []
    blocked: list[tuple[Issue, list[int]]] = []
    for leaf in sorted(ready, key=_leaf_key):
        unmet = _unmet_deps(leaf.number, issues)
        if unmet:
            blocked.append((leaf, unmet))
        else:
            unblocked.append(leaf)

    blocked_json = [_issue_dict(leaf, {"blocked_by": unmet}) for leaf, unmet in blocked]
    if not unblocked:
        if as_json:
            print(json.dumps({"next": None, "queue": [], "blocked_ready": blocked_json}, indent=2))
        if blocked:
            detail = "; ".join(
                f"#{leaf.number} waits on {', '.join(f'#{d}' for d in unmet)}"
                for leaf, unmet in blocked
            )
            print(f"nothing ready: every Ready item is blocked by §7 — {detail}", file=sys.stderr)
        else:
            print(
                "nothing ready: no open board item under epic #23 has Status=Ready. "
                "Run `status` for the full picture; a human may need to move items to Ready.",
                file=sys.stderr,
            )
        return 1

    pick = unblocked[0]
    deps = DEPENDENCIES.get(pick.number)
    if deps:
        dep_note = "all §7 prerequisites closed (" + ", ".join(f"#{d}" for d in deps) + ")"
    else:
        dep_note = "no §7 prerequisite"
    why = (
        f"Status=Ready under epic #23; {dep_note}; first in milestone order "
        f"among {len(unblocked)} unblocked Ready item(s)."
    )
    caveat = CAVEATS.get(pick.number)
    branch = _branch(pick)

    if as_json:
        print(
            json.dumps(
                {
                    "next": _issue_dict(pick, {"branch": branch, "why": why, "caveat": caveat}),
                    "queue": [
                        _issue_dict(leaf, {"caveat": CAVEATS.get(leaf.number)})
                        for leaf in unblocked[1:]
                    ],
                    "blocked_ready": blocked_json,
                },
                indent=2,
            )
        )
        return 0

    print(f"#{pick.number} — {pick.title}")
    print(f"  milestone: {_milestone(pick)}    size: {pick.size or '?'}")
    print(f"  branch:    {branch}")
    print(f"  why:       {why}")
    if caveat:
        print(f"  caveat:    {caveat}")
    if unblocked[1:]:
        queue = ", ".join(f"#{leaf.number}" for leaf in unblocked[1:])
        print(f"  then:      {queue}")
    for leaf, unmet in blocked:
        waits = ", ".join(f"#{d}" for d in unmet)
        print(f"  held back: #{leaf.number} (Ready, but §7 waits on {waits})")
    return 0


_UNTICKED_BOX = re.compile(r"^\s*-\s*\[ \]", re.MULTILINE)

#: H issues MISSION 14 records as closed by the human or with human verification,
#: and explicitly forbids reopening. They still carry unticked boxes, so the audit
#: below reports them as a quiet note rather than an alarm — an alarm that fires on
#: known-settled issues every run is one nobody reads, which is the failure this
#: audit exists to prevent.
_HUMAN_VERIFIED_CLOSED_H = frozenset({34, 48, 50, 60})


def _closed_h_with_unmet_boxes(leaves: list[Issue]) -> list[tuple[Issue, int]]:
    """Return closed H issues that still carry unticked acceptance boxes.

    MISSION 3.5 says H-numbered issues are human tasks that are never closed. The
    ``_h_guard`` enforces that on this script's own mutation paths, but it cannot
    intercept a close performed straight through the GitHub UI or API — which is
    exactly how #49, #51, #52 and #55 were all closed in a 71-second window on
    2026-08-18 with their boxes unticked. Every run afterwards read
    ``open H (human only): none`` and took it to mean "no human work outstanding".

    So audit the closed ones too, and shout about any that were never actually
    finished. A retired bullet is recorded as ticked-and-struck, so it does not
    trip this; only a genuinely unmet box does.
    """
    flagged: list[tuple[Issue, int]] = []
    for leaf in sorted(
        (i for i in leaves if _H_TITLE.match(i.title) and i.state == "CLOSED"),
        key=_leaf_key,
    ):
        try:
            raw = _run_gh(
                ["issue", "view", str(leaf.number), "--repo", OWNER_REPO, "--json", "body"]
            )
            body = str(json.loads(raw).get("body") or "")
        except (BoardError, json.JSONDecodeError):
            continue  # never let the audit break `status`
        unmet = len(_UNTICKED_BOX.findall(body))
        if unmet:
            flagged.append((leaf, unmet))
    return flagged


def cmd_status(as_json: bool) -> int:
    issues = _fetch_issues()
    leaves = _accuracy_leaves(issues)

    counts: dict[str, dict[str, int]] = {}
    for leaf in leaves:
        row = counts.setdefault(_milestone(leaf), dict.fromkeys(STATUS_ORDER, 0))
        row[leaf.status or "Backlog"] = row.get(leaf.status or "Backlog", 0) + 1

    h_open = sorted(
        (leaf for leaf in leaves if _H_TITLE.match(leaf.title) and leaf.state == "OPEN"),
        key=_leaf_key,
    )
    h_unmet = _closed_h_with_unmet_boxes(leaves)
    in_progress = sorted(
        (leaf for leaf in leaves if leaf.status in ("In progress", "In review")),
        key=_leaf_key,
    )
    blocked = [
        (leaf, _unmet_deps(leaf.number, issues))
        for leaf in sorted(leaves, key=_leaf_key)
        if leaf.state == "OPEN" and _unmet_deps(leaf.number, issues)
    ]
    epics = [issues[n] for n in sorted(MILESTONE_EPICS) if n in issues]

    if as_json:
        print(
            json.dumps(
                {
                    "milestone_counts": counts,
                    "epics": [_issue_dict(e) for e in epics],
                    "h_open": [_issue_dict(h) for h in h_open],
                    "h_closed_with_unmet_boxes": [
                        _issue_dict(h, {"unmet_boxes": n}) for h, n in h_unmet
                    ],
                    "in_progress": [_issue_dict(i) for i in in_progress],
                    "blocked": [
                        _issue_dict(leaf, {"blocked_by": unmet}) for leaf, unmet in blocked
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"Accuracy programme — epic #{ROOT_EPIC} on 'Lemely Progress' #1")
    print()
    header = f"{'milestone':<10}" + "".join(f"{s:>13}" for s in STATUS_ORDER) + f"{'total':>8}"
    print(header)
    for name in ("M0", "M1", "M2", "M3", "M4", "H"):
        mrow = counts.get(name)
        if mrow is None:
            continue
        total = sum(mrow.values())
        cells = "".join(f"{mrow.get(s, 0):>13}" for s in STATUS_ORDER)
        print(f"{name:<10}" + cells + f"{total:>8}")
    print()
    epic_line = " · ".join(f"#{e.number} {_milestone(e)}={e.status or 'none'}" for e in epics)
    print(f"epics: {epic_line}")
    print()
    if in_progress:
        for leaf in in_progress:
            print(f"in flight: #{leaf.number} [{leaf.status}] {leaf.title}")
    else:
        print("in flight: nothing")
    if h_open:
        for h in h_open:
            print(f"open H (human only): #{h.number} {h.title}")
    else:
        print("open H (human only): none")
    for h, n_boxes in h_unmet:
        if h.number in _HUMAN_VERIFIED_CLOSED_H:
            print(
                f"note: closed H #{h.number} has {n_boxes} unticked box(es), but MISSION 14 "
                f"records it human-verified closed — do not reopen."
            )
            continue
        print(
            f"!! H-ISSUE CLOSED WITH {n_boxes} UNMET ACCEPTANCE BOX(ES): #{h.number} {h.title}\n"
            f"   MISSION 3.5 says H issues are never closed. Do NOT read this as settled; "
            f"treat it as OPEN and escalate to the human."
        )
    if blocked:
        for leaf, unmet in blocked:
            waits = ", ".join(f"#{d}" for d in unmet)
            print(f"blocked: #{leaf.number} [{leaf.status or 'none'}] waits on {waits}")
    else:
        print("blocked: nothing")
    return 0


def _require_issue(issues: dict[int, Issue], number: int) -> Issue:
    issue = issues.get(number)
    if issue is None:
        raise BoardError(f"issue #{number} is not on the project board (or not in {OWNER_REPO})")
    return issue


def _h_guard(issue: Issue, action: str) -> bool:
    """Return True (and print the refusal) when the issue is a human task."""
    if _H_TITLE.match(issue.title):
        print(
            f"refusing to {action} #{issue.number} ({issue.title.split('—')[0].strip()}): "
            "H-numbered issues are human tasks. An agent must never progress or close "
            "one — block and wait for the human instead.",
            file=sys.stderr,
        )
        return True
    return False


def _stdin_or_default(default: str) -> str:
    body = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    return body or default


def cmd_start(number: int) -> int:
    issues = _fetch_issues()
    issue = _require_issue(issues, number)
    if _h_guard(issue, "start"):
        return 2
    branch = _branch(issue)
    _set_status(issue.item_id, "In progress")
    body = _stdin_or_default(f"Starting work on branch `{branch}`. (accuracy_board start)")
    _post_comment(number, body)
    print(branch)
    return 0


def cmd_review(number: int, pr_url: str) -> int:
    issues = _fetch_issues()
    issue = _require_issue(issues, number)
    if _h_guard(issue, "review"):
        return 2
    _set_status(issue.item_id, "In review")
    _post_comment(
        number,
        f"In review: {pr_url}\n\nStatus set to In review by accuracy_board. The PR body "
        f"should carry `Closes #{number}` so GitHub links and auto-closes it on merge.",
    )
    print(f"#{number} set to In review, PR linked by comment: {pr_url}")
    return 0


def _fetch_issue_off_board(number: int) -> tuple[str, str, list[str]]:
    """Fetch (title, state, labels) for an issue straight from GitHub.

    Board membership used to gate ``done`` entirely (``_require_issue`` raised
    before the H-guard ever ran), which meant "not on the board" — a fact about
    project hygiene, not about whether an issue is a human task — blocked every
    off-board close. This fetches just enough that ``done`` can judge an issue
    with no project item at all: title and labels for the human-task guards,
    state for idempotency.

    **Every field is validated rather than coerced, and the failure mode is
    fail-CLOSED.** ``str(payload["title"])`` would turn a null or missing title
    into the literal ``"None"`` or ``""`` — neither of which matches
    ``_H_TITLE`` — so a degraded response would sail past the H-guard and close
    the issue. A guard whose fetch failure defaults to "not a human task" is
    worse than no guard, because it fails silently and only on the bad path.
    """
    raw = _run_gh(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            OWNER_REPO,
            "--json",
            "number,title,state,labels",
        ]
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BoardError(f"gh returned non-JSON for issue #{number}: {raw[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise BoardError(f"gh returned a non-object payload for issue #{number}: {payload!r}")

    title = payload.get("title")
    state = payload.get("state")
    if not isinstance(title, str) or not title.strip():
        raise BoardError(f"gh returned no usable title for issue #{number}: {payload!r}")
    if state not in {"OPEN", "CLOSED"}:
        raise BoardError(f"gh returned an unrecognised state for issue #{number}: {state!r}")
    # Fetched, so assert it: a mismatch means we are about to act on the wrong issue.
    if payload.get("number") != number:
        raise BoardError(f"gh returned issue #{payload.get('number')} when asked for #{number}")

    raw_labels = payload.get("labels") or []
    labels = [
        name for entry in raw_labels if isinstance(entry, dict) and (name := entry.get("name"))
    ]
    return title, state, labels


def cmd_done(number: int) -> int:
    issues = _fetch_issues()
    issue = issues.get(number)
    if issue is None:
        # Off-board: fetch title/state directly so the H-guard still runs
        # against the real title, rather than refusing outright. There is no
        # board item, so there is no Status field to set to Done.
        title, state, labels = _fetch_issue_off_board(number)
        off_board_issue = Issue(
            number=number,
            title=title,
            state=state,
            parent=None,
            status=None,
            size=None,
            item_id="",
        )
        if _h_guard(off_board_issue, "close"):
            return 2
        # The H-number is not the only marker of a human task, and off-board
        # this guard stands alone — board membership used to be an incidental
        # second net. B17's ruling named "H-number/label" for exactly this
        # reason: `owner:human` marks issues that are human-only without
        # carrying an H-numbered title, so a title-only check would close one.
        if _HUMAN_LABEL in labels:
            print(
                f"refusing to close #{number} ({title.split('—')[0].strip()}): "
                f"it carries the {_HUMAN_LABEL!r} label. That marks a human task "
                "as surely as an H-number does — block and wait for the human.",
                file=sys.stderr,
            )
            return 2
        if state == "CLOSED":
            print(f"#{number} is already closed (off-board: no project item to check)")
            return 0
        _run_gh(["issue", "close", str(number), "--repo", OWNER_REPO])
        print(f"#{number} closed (off-board: no project item, so no Status was set)")
        return 0

    if _h_guard(issue, "close"):
        return 2
    _set_status(issue.item_id, "Done")
    _run_gh(["issue", "close", str(number), "--repo", OWNER_REPO])
    print(f"#{number} closed and set to Done")
    return 0


def _append_blocker(issue: Issue, on_desc: str) -> bool:
    """Append a blocker section for *issue*, unless one is already there.

    Returns True if a section was written, False if one already existed.

    Blocking the same issue twice used to append a second, byte-identical stub —
    #40 ended up in BUILD/BLOCKERS.md twice that way. The file's contract is
    never-delete, so a duplicate cannot simply be tidied away later; it has to
    not be written. The heading is matched on the issue NUMBER alone, because
    the title can be edited on GitHub after the first block.
    """
    heading = f"## #{issue.number} — "
    if BLOCKERS_FILE.exists() and heading in BLOCKERS_FILE.read_text(encoding="utf-8"):
        return False

    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    section = (
        "\n---\n\n"
        f"## #{issue.number} — {issue.title}\n\n"
        f"**Raised:** {stamp} · **Status:** OPEN · "
        "**Source:** `scripts/accuracy_board.py block`\n\n"
        f"Blocked on {on_desc}. Board Status set back to Backlog. Resolve the blocker, "
        "append a RESOLVED line here, and move the item back to Ready.\n"
    )
    with BLOCKERS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(section)
    return True


def cmd_block(number: int, on: str) -> int:
    issues = _fetch_issues()
    issue = _require_issue(issues, number)
    on_desc = f"#{on}" if on.isdigit() else on
    _set_status(issue.item_id, "Backlog")
    _post_comment(
        number,
        f"Blocked on {on_desc}. Status set back to Backlog by accuracy_board; "
        f"logged in BUILD/BLOCKERS.md.",
    )
    written = _append_blocker(issue, on_desc)
    if written:
        print(f"#{number} set to Backlog, blocker logged: {on_desc}")
    else:
        print(
            f"#{number} set to Backlog; BUILD/BLOCKERS.md already has a section for "
            f"#{number}, so nothing was appended. Update that section by hand if the "
            "reason has changed."
        )
    return 0


def cmd_comment(number: int) -> int:
    issues = _fetch_issues()
    issue = _require_issue(issues, number)
    if sys.stdin.isatty():
        raise BoardError("comment expects the body on stdin (pipe it in)")
    body = sys.stdin.read().strip()
    if not body:
        raise BoardError("empty comment body on stdin; nothing posted")
    _post_comment(issue.number, body)
    print(f"comment posted on #{number}")
    return 0


def _repo_root() -> Path:
    """Resolve the repo root the script is running in.

    Never hardcoded: the script runs against a worktree
    (``/home/sico/Lemely-worktrees/accuracy``), not necessarily this checkout.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise BoardError("the `git` CLI is not installed or not on PATH") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise BoardError(f"not inside a git repository (git rev-parse --show-toplevel: {detail})")
    return Path(proc.stdout.strip())


def _state_path() -> Path:
    return _repo_root() / STATE_FILE_RELATIVE


def _parse_state_header(lines: list[str]) -> tuple[dict[str, int], int]:
    """Return ({key: line index}, index of the '---' boundary line).

    The header is every ``key: value`` line above the first line that is
    exactly ``---``; that boundary is what the supervisor's
    ``grep -m1 "^key:"`` relies on staying at column zero.
    """
    header: dict[str, int] = {}
    boundary: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            boundary = i
            break
        # An empty-valued key (``in_the_middle_of:`` with nothing after the
        # colon) is still a key. Matching on ``": " in line`` missed it, so
        # ``state set`` took its "key absent" branch and INSERTED a second
        # line, leaving the empty one above the real one — and the supervisor's
        # ``grep -m1`` then read the empty match, silently blinding the resume
        # pointer. The duplicate guard below could never fire for that case
        # either, because the offending line was never recognised as a key.
        key_match = re.fullmatch(r"([a-z_]+):(?: (.*))?", line)
        if key_match:
            key = key_match.group(1)
            if key in header:
                raise BoardError(
                    f"{_state_path()}: key {key!r} appears twice in the header "
                    f"(lines {header[key] + 1} and {i + 1})"
                )
            header[key] = i
    if boundary is None:
        raise BoardError(f"{_state_path()}: no '---' boundary found; header is malformed")
    return header, boundary


def _state_line_value(line: str) -> str:
    """Value of a ``key: value`` header line; ``''`` for an empty-valued ``key:``."""
    _, _, value = line.partition(": ")
    return value


def _read_state_lines() -> list[str]:
    path = _state_path()
    if not path.exists():
        raise BoardError(f"{path} does not exist")
    return path.read_text(encoding="utf-8").splitlines()


def _write_state_lines(lines: list[str]) -> None:
    """Atomically rewrite the state file: temp file in the same dir, then os.replace."""
    path = _state_path()
    text = "\n".join(lines) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".accuracy-state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _format_spend(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def cmd_state_get(key: str) -> int:
    if key not in STATE_KEYS:
        print(
            f"error: unknown state key {key!r}; allowed keys: {', '.join(STATE_KEYS)}",
            file=sys.stderr,
        )
        return 1
    lines = _read_state_lines()
    header, _boundary = _parse_state_header(lines)
    if key not in header:
        print(f"error: key {key!r} is absent from {_state_path()}", file=sys.stderr)
        return 1
    value = _state_line_value(lines[header[key]])
    print(value)
    return 0


def cmd_state_set(key: str, value: str) -> int:
    if key not in STATE_KEYS:
        raise BoardError(f"unknown state key {key!r}; allowed keys: {', '.join(STATE_KEYS)}")
    lines = _read_state_lines()
    header, boundary = _parse_state_header(lines)

    new_value = value
    if key == "spend_usd" and value.startswith("+"):
        delta = float(value[1:])
        current_text = _state_line_value(lines[header[key]]) if key in header else "0"
        try:
            current = float(current_text)
        except ValueError:
            current = 0.0
        new_value = _format_spend(current + delta)

    new_line = f"{key}: {new_value}"
    if key in header:
        lines[header[key]] = new_line
    else:
        # Key not present yet (shouldn't happen once seeded): append at the end
        # of the header block, just above the '---' boundary.
        lines.insert(boundary, new_line)

    _write_state_lines(lines)
    print(f"{key}: {new_value}")
    return 0


def cmd_state_show(as_json: bool) -> int:
    lines = _read_state_lines()
    header, _boundary = _parse_state_header(lines)
    values: dict[str, str] = {
        key: _state_line_value(lines[header[key]]) for key in STATE_KEYS if key in header
    }
    if as_json:
        print(json.dumps(values, indent=2))
        return 0
    for key in STATE_KEYS:
        if key in values:
            print(f"{key}: {values[key]}")
        else:
            print(f"{key}: <absent>", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="accuracy_board",
        description="Orchestrator interface to the accuracy programme's GitHub board.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_next = sub.add_parser("next", help="print the next unblocked Ready issue")
    p_next.add_argument("--json", action="store_true", dest="as_json")

    p_status = sub.add_parser("status", help="one-screen board summary")
    p_status.add_argument("--json", action="store_true", dest="as_json")

    p_start = sub.add_parser(
        "start",
        help=(
            "Status=In progress, comment, then print ONLY the branch name to "
            "stdout as the sole/last line (safe for $(...) capture); all "
            "human-facing text goes to stderr"
        ),
    )
    p_start.add_argument("issue", type=int)

    p_review = sub.add_parser("review", help="Status=In review, link the PR by comment")
    p_review.add_argument("issue", type=int)
    p_review.add_argument("--pr", required=True, help="PR URL to link")

    p_done = sub.add_parser("done", help="Status=Done and close (refuses H issues, exit 2)")
    p_done.add_argument("issue", type=int)

    p_block = sub.add_parser("block", help="Status=Backlog, comment, log to BUILD/BLOCKERS.md")
    p_block.add_argument("issue", type=int)
    p_block.add_argument("--on", required=True, help="blocking issue number or free-text reason")

    p_comment = sub.add_parser("comment", help="post a comment read from stdin")
    p_comment.add_argument("issue", type=int)

    p_state = sub.add_parser(
        "state",
        help=(
            "get/set/show BUILD/ACCURACY-STATE.md's machine-readable header "
            "(resolved via `git rev-parse --show-toplevel`, never hardcoded)"
        ),
    )
    state_sub = p_state.add_subparsers(dest="state_cmd", required=True)

    p_state_get = state_sub.add_parser(
        "get", help="print one key's value to stdout; exit 1 if the key is absent"
    )
    p_state_get.add_argument("key", help=f"one of: {', '.join(STATE_KEYS)}")

    p_state_set = state_sub.add_parser(
        "set",
        help=(
            "rewrite one key's value in place, preserving key order and the "
            "human-readable body below the header. For spend_usd (only), a "
            "value starting with '+' (e.g. '+0.1234') is ADDED to the current "
            "value instead of replacing it -- the chosen way for a measurement "
            "to accumulate cumulative spend without a separate read-then-write."
        ),
    )
    p_state_set.add_argument("key", help=f"one of: {', '.join(STATE_KEYS)}")
    p_state_set.add_argument(
        "value", help="new value; for spend_usd, '+<number>' adds to the current value"
    )

    p_state_show = state_sub.add_parser("show", help="print all header keys and their values")
    p_state_show.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "next":
            return cmd_next(args.as_json)
        if args.cmd == "status":
            return cmd_status(args.as_json)
        if args.cmd == "start":
            return cmd_start(args.issue)
        if args.cmd == "review":
            return cmd_review(args.issue, args.pr)
        if args.cmd == "done":
            return cmd_done(args.issue)
        if args.cmd == "block":
            return cmd_block(args.issue, args.on)
        if args.cmd == "comment":
            return cmd_comment(args.issue)
        if args.cmd == "state":
            if args.state_cmd == "get":
                return cmd_state_get(args.key)
            if args.state_cmd == "set":
                return cmd_state_set(args.key, args.value)
            if args.state_cmd == "show":
                return cmd_state_show(args.as_json)
            parser.error(f"unknown state subcommand {args.state_cmd!r}")
        parser.error(f"unknown subcommand {args.cmd!r}")
    except BoardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
