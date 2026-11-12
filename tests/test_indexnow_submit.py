"""``scripts/indexnow_submit.py``: sitemap parsing, payload, frontend path filter, status handling.

No network: HTTP goes through an injected fetch and git through a throwaway repository.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "indexnow_submit", ROOT / "scripts" / "indexnow_submit.py"
)
assert _spec is not None
assert _spec.loader is not None
ix = importlib.util.module_from_spec(_spec)
sys.modules["indexnow_submit"] = ix
_spec.loader.exec_module(ix)

KEY = "035fedb9f93990ebeedcbb20374e07d7"
SHA_A = "a" * 40
SHA_B = "b" * 40

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://lemelyig.com/</loc></url>
  <url><loc> https://lemelyig.com/data </loc></url>
  <url><loc>https://lemelyig.com/data</loc></url>
  <url><loc>https://staging.lemelyig.com/</loc></url>
</urlset>"""


def test_parse_sitemap_keeps_order_trims_and_dedupes() -> None:
    assert ix.parse_sitemap(SITEMAP) == [
        "https://lemelyig.com/",
        "https://lemelyig.com/data",
        "https://staging.lemelyig.com/",
    ]


def test_the_committed_sitemap_parses_to_production_urls_only() -> None:
    urls = ix.parse_sitemap(ix.SITEMAP.read_text(encoding="utf-8"))
    assert urls
    assert all(url.startswith("https://lemelyig.com") for url in urls)


def test_build_payload_shape_and_foreign_hosts_dropped() -> None:
    payload = ix.build_payload("lemelyig.com", KEY, ix.parse_sitemap(SITEMAP))
    assert payload == {
        "host": "lemelyig.com",
        "key": KEY,
        "keyLocation": f"https://lemelyig.com/{KEY}.txt",
        "urlList": ["https://lemelyig.com/", "https://lemelyig.com/data"],
    }


def test_the_repo_key_file_matches_its_name() -> None:
    assert ix.find_key(ix.PUBLIC_DIR) == KEY


@pytest.mark.parametrize(
    "path",
    [
        "web/src/App.tsx",
        "web/src/pages/landing/Hero.tsx",
        "web/public/sitemap.xml",
        "web/public/robots.txt",
        "web/index.html",
        "web/worker/index.ts",
        "web/vite/manifest.ts",
        "web/vite.config.ts",
        "web/wrangler.jsonc",
        "web/package-lock.json",
    ],
)
def test_frontend_paths_count(path: str) -> None:
    assert ix.is_frontend_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "web/tests/unit/foo.test.ts",
        "web/e2e/landing.spec.ts",
        "web/dev-previews/landing/index.html",
        "web/src/lib/format.test.ts",
        "web/README.md",
        "web/playwright.config.ts",
        "web/Dockerfile",
        "lemely/web/app.py",
        "docs/ci-cd.md",
        ".github/workflows/deploy.yml",
        "tests/test_x.py",
    ],
)
def test_non_frontend_paths_do_not_count(path: str) -> None:
    assert not ix.is_frontend_path(path)


def test_frontend_changed_rules() -> None:
    assert ix.frontend_changed(["docs/x.md", "web/src/a.tsx"])
    assert not ix.frontend_changed(["docs/x.md", "web/e2e/a.spec.ts"])
    assert not ix.frontend_changed([])
    assert ix.frontend_changed(None)  # unknown previous commit: submit


@pytest.mark.parametrize("status", [200, 202])
def test_success_statuses(status: int) -> None:
    ok, message = ix.describe_status(status)
    assert ok and str(status) in message


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500])
def test_other_statuses_are_failures_with_a_reason(status: int) -> None:
    ok, message = ix.describe_status(status)
    assert not ok
    assert str(status) in message
    if status in ix.STATUS_REASONS:
        assert ix.STATUS_REASONS[status] in message


def _artifact(
    name: str,
    created: str,
    *,
    expired: bool = False,
    branch: str = "main",
    head_sha: str | None = None,
) -> dict[str, object]:
    sha = name.removeprefix("frontend-submitted-")
    return {
        "name": name,
        "created_at": created,
        "expired": expired,
        "workflow_run": {"head_branch": branch, "head_sha": head_sha or sha},
    }


@pytest.fixture(autouse=True)
def _no_ci_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test write to CI's real ``GITHUB_OUTPUT``."""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)


def test_latest_marker_sha_picks_the_newest_live_marker() -> None:
    listing = {
        "artifacts": [
            _artifact(f"frontend-submitted-{SHA_A}", "2026-11-01T00:00:00Z"),
            _artifact(f"frontend-submitted-{SHA_B}", "2026-11-05T00:00:00Z"),
            _artifact("coverage", "2026-11-09T00:00:00Z"),
            _artifact(f"frontend-submitted-{'c' * 40}", "2026-11-08T00:00:00Z", expired=True),
            _artifact("frontend-submitted-not-a-sha", "2026-11-09T00:00:00Z"),
        ]
    }
    assert ix.latest_marker_sha(listing) == SHA_B


def test_latest_marker_sha_is_none_without_markers() -> None:
    assert ix.latest_marker_sha({"artifacts": []}) is None
    assert ix.latest_marker_sha({}) is None


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *argv],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_changed_paths_since_uses_git_and_none_for_an_unknown_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "one")
    first = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "b.txt").write_text("2")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "two")
    monkeypatch.setattr(ix, "ROOT", tmp_path)
    assert ix.changed_paths_since(first) == ["web/b.txt"]
    assert ix.changed_paths_since(SHA_A) is None


def test_key_is_live_requires_status_200_and_the_exact_key() -> None:
    def serving(body: str, status: int = 200):
        return lambda _request: (status, body)

    assert ix.key_is_live("lemelyig.com", KEY, serving(KEY + "\n"))
    assert not ix.key_is_live("lemelyig.com", KEY, serving("<html>spa fallback</html>"))
    assert not ix.key_is_live("lemelyig.com", KEY, serving(KEY, 404))


# ---- run(): decisions and best-effort guarantees ---------------------------------------------


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "host": "lemelyig.com",
        "sitemap": ix.SITEMAP,
        "previous_sha": SHA_A,
        "force": False,
        "dry_run": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _record(
    monkeypatch: pytest.MonkeyPatch, *, status: int = 200, key_ok: bool = True
) -> list[urllib.request.Request]:
    sent: list[urllib.request.Request] = []

    def fake_http(request: urllib.request.Request) -> tuple[int, str]:
        sent.append(request)
        if request.full_url.endswith(".txt"):
            return (200, KEY) if key_ok else (200, "<html>")
        return status, ""

    monkeypatch.setattr(ix, "_http", fake_http)
    return sent


def test_run_skips_when_no_frontend_file_changed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent = _record(monkeypatch)
    monkeypatch.setattr(
        ix, "changed_paths_since", lambda _sha: ["docs/ci-cd.md", "web/e2e/a.spec.ts"]
    )
    assert ix.run(_args()) == 0
    assert sent == []
    assert "not submitting" in capsys.readouterr().out


def test_run_submits_when_a_frontend_file_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    sent = _record(monkeypatch, status=202)
    monkeypatch.setattr(ix, "changed_paths_since", lambda _sha: ["web/src/App.tsx"])
    assert ix.run(_args()) == 0
    assert [r.full_url for r in sent] == [f"https://lemelyig.com/{KEY}.txt", ix.ENDPOINT]
    assert sent[1].get_method() == "POST"
    assert out.read_text() == "submitted=true\n"


def test_run_submits_when_the_previous_commit_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _record(monkeypatch)
    monkeypatch.setattr(ix, "changed_paths_since", lambda _sha: None)
    assert ix.run(_args()) == 0
    assert len(sent) == 2
    monkeypatch.setattr(ix, "lookup_previous_sha", lambda _repo, _token: None)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    sent.clear()
    assert ix.run(_args(previous_sha=None)) == 0
    assert len(sent) == 2


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500])
def test_run_never_fails_on_a_bad_status_and_does_not_record_a_marker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, status: int
) -> None:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _record(monkeypatch, status=status)
    monkeypatch.setattr(ix, "changed_paths_since", lambda _sha: None)
    assert ix.run(_args()) == 0
    assert f"::warning::IndexNow returned HTTP {status}" in capsys.readouterr().out
    assert not out.exists()


def test_run_never_fails_on_a_network_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_request: urllib.request.Request) -> tuple[int, str]:
        raise TimeoutError("timed out")

    monkeypatch.setattr(ix, "_http", boom)
    monkeypatch.setattr(ix, "changed_paths_since", lambda _sha: None)
    assert ix.run(_args()) == 0
    assert "::warning::IndexNow submission failed" in capsys.readouterr().out


def test_run_skips_when_the_key_is_not_live(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent = _record(monkeypatch, key_ok=False)
    monkeypatch.setattr(ix, "changed_paths_since", lambda _sha: None)
    assert ix.run(_args()) == 0
    assert [r.full_url for r in sent] == [f"https://lemelyig.com/{KEY}.txt"]
    assert "::warning::" in capsys.readouterr().out


def test_dry_run_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent = _record(monkeypatch)
    assert ix.run(_args(dry_run=True, force=True)) == 0
    assert sent == []
    assert KEY in capsys.readouterr().out


def test_a_marker_from_a_pr_or_staging_branch_is_ignored() -> None:
    listing = {
        "artifacts": [
            _artifact(f"frontend-submitted-{SHA_B}", "2026-11-09T00:00:00Z", branch="feat/x"),
            _artifact(f"frontend-submitted-{SHA_A}", "2026-11-01T00:00:00Z"),
        ]
    }
    assert ix.latest_marker_sha(listing) == SHA_A
    only_pr = {"artifacts": [listing["artifacts"][0]]}
    assert ix.latest_marker_sha(only_pr) is None


def test_a_marker_whose_run_sha_differs_from_its_name_is_ignored() -> None:
    forged = _artifact(f"frontend-submitted-{SHA_B}", "2026-11-09T00:00:00Z", head_sha=SHA_A)
    assert ix.latest_marker_sha({"artifacts": [forged]}) is None
    no_run = {"name": f"frontend-submitted-{SHA_B}", "created_at": "2026-11-09T00:00:00Z"}
    assert ix.latest_marker_sha({"artifacts": [no_run]}) is None


def test_lookup_reads_later_pages_until_a_marker_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    filler = [_artifact(f"coverage-{n}", "2026-11-09T00:00:00Z") for n in range(100)]
    pages = {
        "1": {"artifacts": filler},
        "2": {"artifacts": [_artifact(f"frontend-submitted-{SHA_A}", "2026-11-01T00:00:00Z")]},
    }
    urls: list[str] = []

    def fake_fetch(url: str, _token: str) -> dict[str, object]:
        urls.append(url)
        return pages[url.rsplit("page=", 1)[1]]

    monkeypatch.setattr(ix, "_fetch_json", fake_fetch)
    assert ix.lookup_previous_sha("o/r", "t") == SHA_A
    assert len(urls) == 2


def test_lookup_stops_after_the_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    filler = {"artifacts": [_artifact(f"coverage-{n}", "2026-11-09T00:00:00Z") for n in range(100)]}
    calls: list[str] = []

    def fake_fetch(url: str, _token: str) -> dict[str, object]:
        calls.append(url)
        return filler

    monkeypatch.setattr(ix, "_fetch_json", fake_fetch)
    assert ix.lookup_previous_sha("o/r", "t") is None
    assert len(calls) == ix.MAX_ARTIFACT_PAGES


def test_run_never_fails_on_a_malformed_sitemap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad = tmp_path / "sitemap.xml"
    bad.write_text("<urlset><url>", encoding="utf-8")
    sent = _record(monkeypatch)
    assert ix.run(_args(sitemap=bad)) == 0
    assert sent == []
    assert "::warning::IndexNow step failed unexpectedly" in capsys.readouterr().out
