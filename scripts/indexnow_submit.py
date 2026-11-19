#!/usr/bin/env python
"""Tell IndexNow about the public URLs after a production frontend deploy (run by deploy.yml).

IndexNow (https://www.indexnow.org) lets a site push "these URLs changed" to participating search
engines instead of waiting for a crawl. The key is public by design: the file
``web/public/<key>.txt`` holds the key as its only content and is served at the site root, which is
how an engine proves the submitter controls the host.

**Best effort.** Nothing here may fail a deploy. Every outcome, including a network error, ends in
exit code 0 with a ``::warning::`` where it matters. The workflow also marks the job
``continue-on-error`` as a second belt.

**When it runs.** Only when the deploy changed what users get. The workflow finds the commit of the
last production frontend deploy that finished a submission (a ``frontend-submitted-<sha>`` artifact,
see :func:`latest_marker_sha`), and :func:`frontend_changed` decides from ``git diff --name-only``
between that commit and HEAD. If the previous commit is unknown, or git cannot diff it, the answer
is "changed": submitting twice is harmless, missing a change is not.

**What counts as the frontend.** :data:`FRONTEND_INCLUDE` minus :data:`FRONTEND_EXCLUDE`, the
one place that list lives. The payload is built by :func:`build_payload` from
``web/public/sitemap.xml``.
"""

from __future__ import annotations

import argparse
import fnmatch
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

ENDPOINT: Final = "https://api.indexnow.org/indexnow"
HOST: Final = "lemelyig.com"
ROOT: Final = Path(__file__).resolve().parents[1]
SITEMAP: Final = ROOT / "web" / "public" / "sitemap.xml"
PUBLIC_DIR: Final = ROOT / "web" / "public"
SITEMAP_NS: Final = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
KEY_FILE_RE: Final = re.compile(r"^[0-9a-f]{32}\.txt$")
MARKER_PREFIX: Final = "frontend-submitted-"
MARKER_BRANCH: Final = "main"
MAX_ARTIFACT_PAGES: Final = 5
TIMEOUT_SECONDS: Final = 20
USER_AGENT: Final = "lemely-indexnow/1"

# Files under web/ that change what users get. Globs match the repo-relative path with fnmatch
# (so "*" crosses "/"). A path is frontend when it matches an include and no exclude.
FRONTEND_INCLUDE: Final[tuple[str, ...]] = (
    "web/src/*",
    "web/public/*",
    "web/worker/*",
    "web/vite/*",
    "web/index.html",
    "web/vite.config.ts",
    "web/wrangler.jsonc",
    "web/package.json",
    "web/package-lock.json",
    "web/tsconfig.json",
    "web/tsconfig.app.json",
    "web/tsconfig.sw.json",
)
FRONTEND_EXCLUDE: Final[tuple[str, ...]] = (
    "web/tests/*",
    "web/e2e/*",
    "web/dev-previews/*",
    "web/src/*.test.*",
    "web/src/*.spec.*",
    "web/worker/node_modules/*",
)

# IndexNow response meanings (https://www.indexnow.org/documentation).
SUCCESS_STATUSES: Final = frozenset({200, 202})
STATUS_REASONS: Final[Mapping[int, str]] = {
    400: "bad request (invalid format)",
    403: "key not valid (key file missing or the key does not match)",
    422: "unprocessable (URLs do not belong to the host, or the key does not match the schema)",
    429: "too many requests (rate limited)",
}


def is_frontend_path(path: str) -> bool:
    """True when a changed repo-relative path affects what users receive."""
    included = any(fnmatch.fnmatchcase(path, pattern) for pattern in FRONTEND_INCLUDE)
    excluded = any(fnmatch.fnmatchcase(path, pattern) for pattern in FRONTEND_EXCLUDE)
    return included and not excluded


def frontend_changed(changed_paths: Iterable[str] | None) -> bool:
    """Decide from a diff's file list. ``None`` means the diff is unknown: treat as changed."""
    if changed_paths is None:
        return True
    return any(is_frontend_path(path) for path in changed_paths)


def parse_sitemap(xml_text: str) -> list[str]:
    """The ``<loc>`` URLs of a sitemap, in order, without duplicates."""
    root = ET.fromstring(xml_text)  # noqa: S314 - our own committed file, not remote input
    seen: dict[str, None] = {}
    for loc in root.iter(f"{SITEMAP_NS}loc"):
        url = (loc.text or "").strip()
        if url:
            seen.setdefault(url, None)
    return list(seen)


def build_payload(host: str, key: str, urls: Sequence[str]) -> dict[str, object]:
    """The JSON body IndexNow expects; URLs off ``host`` are dropped (IndexNow rejects a mix)."""
    prefix = f"https://{host}/"
    own = [url for url in urls if url == f"https://{host}" or url.startswith(prefix)]
    return {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": own,
    }


def describe_status(status: int) -> tuple[bool, str]:
    """``(ok, message)`` for an IndexNow HTTP status; only 200 and 202 are success."""
    if status in SUCCESS_STATUSES:
        return True, f"IndexNow accepted the submission (HTTP {status})."
    reason = STATUS_REASONS.get(status, "unexpected response")
    return False, f"IndexNow returned HTTP {status}: {reason}."


def find_key(public_dir: Path) -> str | None:
    """The IndexNow key: the stem of the single ``<32 hex>.txt`` whose content is that stem."""
    for path in sorted(public_dir.glob("*.txt")):
        if KEY_FILE_RE.match(path.name) and path.read_text(encoding="utf-8").strip() == path.stem:
            return path.stem
    return None


def latest_marker_sha(artifacts: Mapping[str, object]) -> str | None:
    """The commit of the newest ``frontend-submitted-<sha>`` artifact in a GitHub list response."""
    raw = artifacts.get("artifacts")
    if not isinstance(raw, list):
        return None
    found: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("expired"):
            continue
        name, created = item.get("name"), item.get("created_at")
        run_info = item.get("workflow_run")
        if not (
            isinstance(name, str) and isinstance(created, str) and name.startswith(MARKER_PREFIX)
        ):
            continue
        sha = name[len(MARKER_PREFIX) :]
        # Only a marker written by a run on main, for the commit it names: a PR or staging run
        # must not be able to suppress a production submission.
        if (
            re.fullmatch(r"[0-9a-f]{40}", sha)
            and isinstance(run_info, dict)
            and run_info.get("head_branch") == MARKER_BRANCH
            and run_info.get("head_sha") == sha
        ):
            found.append((created, sha))
    return max(found)[1] if found else None


def _fetch_json(url: str, token: str) -> Mapping[str, object]:
    request = urllib.request.Request(  # noqa: S310 - fixed https GitHub API URL
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body = json.load(response)
    return body if isinstance(body, dict) else {}


def lookup_previous_sha(repo: str, token: str) -> str | None:
    """Ask GitHub for the last submitted commit; ``None`` on any problem (the caller submits)."""
    base = f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100"
    try:
        for page in range(1, MAX_ARTIFACT_PAGES + 1):
            listing = _fetch_json(f"{base}&page={page}", token)
            sha = latest_marker_sha(listing)
            if sha is not None:  # newest first: the first page with a marker holds the newest
                return sha
            raw = listing.get("artifacts")
            if not isinstance(raw, list) or len(raw) < 100:
                break
        return None
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f"::warning::Could not read the previous frontend deploy marker: {error}")
        return None


def changed_paths_since(previous_sha: str, head: str = "HEAD") -> list[str] | None:
    """Files changed between two commits, or ``None`` when git cannot say (unknown commit)."""
    result = subprocess.run(  # noqa: S603 - fixed argv, SHA validated by the caller
        ["git", "diff", "--name-only", "--no-renames", f"{previous_sha}..{head}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def _http(request: urllib.request.Request) -> tuple[int, str]:
    """Return ``(status, body)``; an HTTP error status is a result here, not an exception."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


def key_is_live(
    host: str, key: str, fetch: Callable[[urllib.request.Request], tuple[int, str]]
) -> bool:
    """Report whether ``https://<host>/<key>.txt`` serves exactly the key."""
    request = urllib.request.Request(
        f"https://{host}/{key}.txt", headers={"User-Agent": USER_AGENT}
    )
    status, body = fetch(request)
    return status == 200 and body.strip() == key


def post_payload(
    payload: Mapping[str, object], fetch: Callable[[urllib.request.Request], tuple[int, str]]
) -> int:
    request = urllib.request.Request(  # noqa: S310
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT},
        method="POST",
    )
    return fetch(request)[0]


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def run(args: argparse.Namespace) -> int:
    """Always returns 0: IndexNow must never fail a deploy, whatever goes wrong."""
    try:
        return _run(args)
    except Exception as error:
        print(f"::warning::IndexNow step failed unexpectedly ({type(error).__name__}): {error}")
        return 0


def _run(args: argparse.Namespace) -> int:
    """Decide and submit; see :func:`run` for the never-fail wrapper."""
    key = find_key(PUBLIC_DIR)
    if key is None:
        print("::warning::No IndexNow key file found in web/public; skipping the submission.")
        return 0
    payload = build_payload(args.host, key, parse_sitemap(args.sitemap.read_text(encoding="utf-8")))
    if not payload["urlList"]:
        print("::warning::The sitemap lists no URLs on the host; nothing to submit.")
        return 0

    previous = args.previous_sha
    if previous is None and not args.force:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        previous = lookup_previous_sha(repo, token) if token and repo else None
    changed: list[str] | None = None
    if previous and not args.force:
        if not re.fullmatch(r"[0-9a-f]{40}", previous):
            print(f"::warning::Ignoring a malformed previous SHA {previous!r}.")
        else:
            changed = changed_paths_since(previous)
    if not args.force and not frontend_changed(changed):
        print(f"No frontend files changed since {previous}; not submitting to IndexNow.")
        return 0
    print(
        f"Submitting {len(payload['urlList'])} URL(s) to IndexNow "  # type: ignore[arg-type]
        f"(previous deploy: {previous or 'unknown'})."
    )
    print(json.dumps(payload, indent=2))
    if args.dry_run:
        print("--dry-run: nothing sent.")
        return 0

    try:
        if not key_is_live(args.host, key, _http):
            print(f"::warning::https://{args.host}/{key}.txt is not serving the key; skipping.")
            return 0
        ok, message = describe_status(post_payload(payload, _http))
    except (OSError, ValueError, http.client.HTTPException) as error:  # network failure, timeout
        print(f"::warning::IndexNow submission failed: {error}")
        return 0
    if ok:
        print(message)
        _write_output("submitted", "true")
    else:
        print(f"::warning::{message}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--sitemap", type=Path, default=SITEMAP)
    parser.add_argument(
        "--previous-sha", help="Commit of the last submitted deploy (default: ask GitHub)."
    )
    parser.add_argument("--force", action="store_true", help="Submit regardless of what changed.")
    parser.add_argument("--dry-run", action="store_true", help="Decide and print, send nothing.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
