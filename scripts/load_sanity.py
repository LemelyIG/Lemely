#!/usr/bin/env python3
"""Basic load sanity for the API (Phase 6, P6.2 — MISSION.md §4).

MISSION §4 Phase 6 asks for "basic load sanity on the API" — not a benchmark
harness, not a capacity plan. This fires N concurrent requests at a handful
of real, already-authenticated GET endpoints against a **running** backend
and reports per-endpoint p50/p95/max latency, request count, and error rate.
It prints numbers; it does not print a verdict, because MISSION does not
state a latency threshold to grade against (see ``check_ui_gates.py`` for
what an actual honest gate looks like when a floor *is* stated).

Requires a live server (``scripts/e2e_server.py``, real Postgres/Supabase
behind it, Gemini mocked) — this is deliberately **not** a pytest test; it
would need a live process and would corrupt a coverage run if collected
alongside the suite. Auth tokens come from ``scripts/seed_e2e.py``'s JSON
output (the one seeding path every E2E/audit harness already uses — see
``web/e2e/seed.ts``'s ``SeedContract``), via ``--seed-json``.

Usage::

    source .venv/bin/activate
    python scripts/seed_e2e.py --json-out /tmp/seed.json
    python scripts/e2e_server.py &            # PORT defaults to 8000
    python scripts/load_sanity.py --seed-json /tmp/seed.json

Writes ``reports/phase-6/load-sanity.json`` (machine-readable) and
``reports/phase-6/load-sanity.md`` (human-readable) by default.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_OUT = REPO_ROOT / "reports" / "phase-6" / "load-sanity.json"
DEFAULT_MD_OUT = REPO_ROOT / "reports" / "phase-6" / "load-sanity.md"

#: Recursive JSON type, used instead of `Any` (this project's mypy config sets
#: `disallow_any_explicit`) for the loosely-shaped seed payload this script
#: only ever does dotted lookups into (``_lookup_token``). The report *this*
#: script produces has a fixed shape, so it gets real ``TypedDict``s below
#: instead — precise types beat a generic JSON blob wherever the shape is
#: actually known upfront.
JSONValue = str | int | float | bool | None | dict[str, "JSONValue"] | list["JSONValue"]
JSONDict = dict[str, JSONValue]


class EndpointSummary(TypedDict):
    """One endpoint's measured results — :meth:`EndpointResult.summary`'s return shape."""

    label: str
    path: str
    request_count: int
    error_count: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    status_counts: dict[str, int]
    sample_errors: list[str]


class ReportPayload(TypedDict):
    """The full report this script writes to ``--json-out``/``--md-out``."""

    startedAt: str
    finishedAt: str
    baseUrl: str
    concurrency: int
    durationSecondsPerEndpoint: float
    caveats: list[str]
    endpoints: list[EndpointSummary]


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One GET route to hit, and which seeded account's token authorizes it."""

    label: str
    path: str
    token_path: tuple[str, ...]
    """Dotted lookup into the seed JSON for the bearer token, e.g.
    ``("students", "control", "accessToken")``. Empty tuple means no auth
    header (the health check)."""


#: A representative spread of real read endpoints across roles — not
#: exhaustive (that's the authz matrix's job), just enough surface for a
#: "does the API fall over under light concurrent load" sanity check.
ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("health", "/api/health", ()),
    Endpoint("me_profile", "/api/me/profile", ("students", "control", "accessToken")),
    Endpoint("student_overview", "/api/student/overview", ("students", "control", "accessToken")),
    Endpoint("student_xp", "/api/student/xp", ("students", "control", "accessToken")),
    Endpoint(
        "student_leaderboard",
        "/api/student/leaderboard",
        ("students", "control", "accessToken"),
    ),
    Endpoint("student_friends", "/api/student/friends", ("students", "control", "accessToken")),
    Endpoint("teacher_overview", "/api/teacher/overview", ("teacher", "accessToken")),
    Endpoint("teacher_papers", "/api/papers", ("teacher", "accessToken")),
)


@dataclass(slots=True)
class EndpointResult:
    label: str
    path: str
    request_count: int = 0
    error_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record_success(self, status: int, elapsed_ms: float) -> None:
        self.request_count += 1
        self.latencies_ms.append(elapsed_ms)
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        if status >= 400:
            self.error_count += 1

    def record_exception(self, exc: Exception) -> None:
        self.request_count += 1
        self.error_count += 1
        self.errors.append(f"{type(exc).__name__}: {exc}")

    def summary(self) -> EndpointSummary:
        latencies = sorted(self.latencies_ms)
        return {
            "label": self.label,
            "path": self.path,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(self.error_count / self.request_count, 4)
            if self.request_count
            else None,
            "p50_ms": round(_percentile(latencies, 0.50), 2) if latencies else None,
            "p95_ms": round(_percentile(latencies, 0.95), 2) if latencies else None,
            "max_ms": round(max(latencies), 2) if latencies else None,
            "mean_ms": round(statistics.fmean(latencies), 2) if latencies else None,
            "status_counts": {str(k): v for k, v in sorted(self.status_counts.items())},
            "sample_errors": self.errors[:5],
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile over an already-sorted list (no numpy dependency)."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return sorted_values[index]


def _lookup_token(seed: JSONDict, token_path: tuple[str, ...]) -> str | None:
    node: JSONValue = seed
    for key in token_path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, str) else None


def _run_endpoint(
    client: httpx.Client,
    base_url: str,
    endpoint: Endpoint,
    token: str | None,
    *,
    concurrency: int,
    duration_seconds: float,
) -> EndpointResult:
    result = EndpointResult(label=endpoint.label, path=endpoint.path)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + duration_seconds

    # Each worker thread appends to its own list and returns it; results are
    # only merged back on the main thread after every worker finishes, so
    # there is no concurrent mutation of shared state to reason about.
    def _one_request() -> tuple[int, float] | Exception:
        start = time.perf_counter()
        try:
            response = client.get(f"{base_url}{endpoint.path}", headers=headers, timeout=10.0)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return response.status_code, elapsed_ms
        except httpx.HTTPError as exc:
            return exc

    def _worker() -> list[tuple[int, float] | Exception]:
        out: list[tuple[int, float] | Exception] = []
        while time.monotonic() < deadline:
            out.append(_one_request())
        return out

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_worker) for _ in range(concurrency)]
        raw_results = [item for future in as_completed(futures) for item in future.result()]

    for item in raw_results:
        if isinstance(item, Exception):
            result.record_exception(item)
        else:
            status, elapsed_ms = item
            result.record_success(status, elapsed_ms)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: %(default)s — scripts/e2e_server.py's default).",
    )
    parser.add_argument(
        "--seed-json",
        required=True,
        help="Path to the JSON payload from `python scripts/seed_e2e.py --json-out <path>`.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Concurrent workers per endpoint (default: %(default)s).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Seconds to hammer each endpoint (default: %(default)s).",
    )
    parser.add_argument(
        "--json-out",
        default=str(DEFAULT_JSON_OUT),
        help="Where to write the machine-readable report (default: %(default)s).",
    )
    parser.add_argument(
        "--md-out",
        default=str(DEFAULT_MD_OUT),
        help="Where to write the human-readable report (default: %(default)s).",
    )
    args = parser.parse_args(argv)

    seed: JSONDict = json.loads(Path(args.seed_json).read_text(encoding="utf-8"))

    try:
        health = httpx.get(f"{args.base_url}/api/health", timeout=5.0)
        health.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Backend at {args.base_url} is not reachable ({exc}). Is e2e_server.py running?")
        return 1

    started_at = datetime.now(UTC)
    results: list[EndpointResult] = []
    with httpx.Client() as client:
        for endpoint in ENDPOINTS:
            token = _lookup_token(seed, endpoint.token_path) if endpoint.token_path else None
            if endpoint.token_path and token is None:
                print(f"skip {endpoint.label}: token path {endpoint.token_path} not in seed JSON")
                continue
            print(
                f"hammering {endpoint.label} ({endpoint.path}) "
                f"— concurrency={args.concurrency}, duration={args.duration}s ..."
            )
            result = _run_endpoint(
                client,
                args.base_url,
                endpoint,
                token,
                concurrency=args.concurrency,
                duration_seconds=args.duration,
            )
            results.append(result)
            summary = result.summary()
            print(
                f"  n={summary['request_count']} errors={summary['error_count']} "
                f"p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms max={summary['max_ms']}ms"
            )
    finished_at = datetime.now(UTC)

    payload: ReportPayload = {
        "startedAt": started_at.isoformat(),
        "finishedAt": finished_at.isoformat(),
        "baseUrl": args.base_url,
        "concurrency": args.concurrency,
        "durationSecondsPerEndpoint": args.duration,
        "caveats": [
            "Single machine, dev-grade uvicorn server (scripts/e2e_server.py), "
            "not production infra.",
            "Data is scripts/seed_e2e.py's synthetic seed corpus, not production-scale data.",
            "Gemini is mocked for this server (fixture-backed, per MISSION's mocking requirement) "
            "— these numbers say nothing about live-model latency.",
            "This is a sanity check, not a benchmark: no throughput/latency threshold is asserted "
            "or graded against, because MISSION.md states none for the API.",
        ],
        "endpoints": [r.summary() for r in results],
    }

    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    md_out = Path(args.md_out)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(_render_markdown(payload), encoding="utf-8")

    print(f"\nWrote {json_out}")
    print(f"Wrote {md_out}")
    return 0


def _render_markdown(payload: ReportPayload) -> str:
    lines = [
        "# API load sanity — Phase 6 (P6.2)",
        "",
        f"Run: {payload['startedAt']} → {payload['finishedAt']}",
        f"Base URL: `{payload['baseUrl']}`  |  "
        f"Concurrency: {payload['concurrency']}  |  "
        f"Duration/endpoint: {payload['durationSecondsPerEndpoint']}s",
        "",
        "## What this is (and isn't)",
        "",
        "Basic sanity, not a benchmark — MISSION.md §4 Phase 6 asks only for "
        '"basic load sanity on the API". No pass/fail verdict is printed below '
        "because MISSION states no latency threshold to grade against; these are "
        "measured numbers, read them as such.",
        "",
    ]
    for caveat in payload["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Endpoint | Path | n | errors | error rate | p50 (ms) | p95 (ms) | max (ms) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for ep in payload["endpoints"]:
        lines.append(
            f"| {ep['label']} | `{ep['path']}` | {ep['request_count']} | {ep['error_count']} | "
            f"{ep['error_rate']} | {ep['p50_ms']} | {ep['p95_ms']} | {ep['max_ms']} |"
        )
    lines.append("")
    for ep in payload["endpoints"]:
        if ep["sample_errors"]:
            lines.append(f"### Sample errors — {ep['label']}")
            lines.extend(f"- {err}" for err in ep["sample_errors"])
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
