"""Tests for ``scripts/check_ui_gates.py``'s route-gating helpers.

C4 (Task 11) extends the Lighthouse performance floor (MISSION.md §11,
previously student routes only) to two teacher routes. These tests pin
``is_perf_gated_route`` — the single predicate ``main()`` calls for that
decision — and then drive ``main()`` itself end to end against a fixture
report directory, so the actual pass/fail behaviour at the floor is proven,
not just the predicate in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import pytest

from scripts import check_ui_gates
from scripts.check_ui_gates import (
    PERF_GATED_TEACHER_SLUGS,
    PERF_GATED_TUTORING_SLUGS,
    is_perf_gated_route,
    is_student_route,
)

REGISTRY_MODULE = (
    Path(__file__).resolve().parent.parent / "web" / "scripts" / "audit_tutoring_registry.mjs"
)

RouteRow = dict[str, object]


class WriteReport(Protocol):
    def __call__(
        self, *, lighthouse_rows: list[RouteRow], axe_rows: list[RouteRow] | None = None
    ) -> None: ...


def _route(*, path: str | None = None, slug: str = "some-slug") -> RouteRow:
    row: RouteRow = {"slug": slug}
    if path is not None:
        row["path"] = path
    return row


class TestIsPerfGatedRoute:
    def test_student_route_by_path_is_gated(self) -> None:
        assert is_perf_gated_route(_route(path="/student/result/abc123", slug="student-result"))

    def test_student_root_path_is_gated(self) -> None:
        assert is_perf_gated_route(_route(path="/student", slug="student-overview"))

    def test_gated_teacher_slug_is_gated_even_without_a_student_path(self) -> None:
        route = _route(path="/teacher/classes/1/analytics", slug="teacher-class-analytics")
        assert is_perf_gated_route(route)

    def test_second_gated_teacher_slug_is_gated(self) -> None:
        route = _route(path="/teacher/review", slug="teacher-review")
        assert is_perf_gated_route(route)

    def test_ungated_teacher_slug_is_not_gated(self) -> None:
        route = _route(path="/teacher/quizzes/1", slug="teacher-grading")
        assert not is_perf_gated_route(route)

    def test_parent_route_is_not_gated(self) -> None:
        route = _route(path="/parent", slug="parent-overview")
        assert not is_perf_gated_route(route)

    def test_gated_teacher_slugs_constant_names_both_routes(self) -> None:
        # A floor-raising change, not a full teacher-route audit (per the
        # plan): exactly the two slugs it asked for, nothing more.
        assert set(PERF_GATED_TEACHER_SLUGS) == {"teacher-class-analytics", "teacher-review"}


class TestIsStudentRouteUnchanged:
    """``is_student_route`` keeps its own, narrower meaning — C4 does not
    fold the teacher slugs into it; ``is_perf_gated_route`` composes both."""

    def test_student_path_true(self) -> None:
        assert is_student_route(_route(path="/student/correct", slug="student-correct"))

    def test_teacher_gated_slug_is_not_a_student_route(self) -> None:
        route = _route(path="/teacher/review", slug="teacher-review")
        assert not is_student_route(route)


def _clean_axe_row(slug: object) -> RouteRow:
    return {"slug": str(slug), "counts": {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}}


@pytest.fixture
def report_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WriteReport:
    """Points every path ``main()`` reads at a fresh, empty fixture directory,
    and returns a helper that writes the four summary files ``main()``
    requires plus the two optional ones, defaulting each to "nothing wrong"."""
    axe_dir = tmp_path / "axe"
    lighthouse_dir = tmp_path / "lighthouse"
    axe_dir.mkdir()
    lighthouse_dir.mkdir()
    monkeypatch.setattr(check_ui_gates, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(check_ui_gates, "AXE_SUMMARY", axe_dir / "_summary.json")
    monkeypatch.setattr(check_ui_gates, "LH_SUMMARY", lighthouse_dir / "_summary.json")
    monkeypatch.setattr(check_ui_gates, "CONSOLE_ERRORS", tmp_path / "console-errors.json")
    monkeypatch.setattr(check_ui_gates, "RESPONSIVE_SUMMARY", tmp_path / "responsive-summary.json")
    monkeypatch.setattr(check_ui_gates, "ROUTE_FAILURES", tmp_path / "route-failures.json")

    def write(*, lighthouse_rows: list[RouteRow], axe_rows: list[RouteRow] | None = None) -> None:
        check_ui_gates.AXE_SUMMARY.write_text(
            json.dumps(
                axe_rows
                if axe_rows is not None
                else [_clean_axe_row(r["slug"]) for r in lighthouse_rows]
            )
        )
        check_ui_gates.LH_SUMMARY.write_text(json.dumps(lighthouse_rows))
        check_ui_gates.CONSOLE_ERRORS.write_text("[]")
        check_ui_gates.RESPONSIVE_SUMMARY.write_text("[]")
        check_ui_gates.ROUTE_FAILURES.write_text("[]")

    return write


def _lh_row(*, slug: str, path: str, performance: int, accessibility: int = 100) -> RouteRow:
    return {
        "slug": slug,
        "path": path,
        "scores": {"accessibility": accessibility, "performance": performance},
    }


class TestPerformanceFloorEndToEnd:
    """Drives ``main()`` itself against a fixture report directory — the
    plan's own scenario: "a teacher-review route at 79 fails, at 80 passes;
    a teacher-grading route at 50 is not gated"."""

    def test_teacher_review_below_floor_fails(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[_lh_row(slug="teacher-review", path="/teacher/review", performance=79)]
        )
        assert check_ui_gates.main() == 1

    def test_teacher_review_at_floor_passes(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[_lh_row(slug="teacher-review", path="/teacher/review", performance=80)]
        )
        assert check_ui_gates.main() == 0

    def test_teacher_class_analytics_below_floor_fails(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[
                _lh_row(
                    slug="teacher-class-analytics",
                    path="/teacher/classes/1/analytics",
                    performance=79,
                )
            ]
        )
        assert check_ui_gates.main() == 1

    def test_teacher_grading_at_50_is_not_gated(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[
                _lh_row(slug="teacher-grading", path="/teacher/quizzes/1/grade", performance=50)
            ]
        )
        assert check_ui_gates.main() == 0

    def test_student_route_below_floor_still_fails(self, report_dir: WriteReport) -> None:
        # Unchanged behaviour: the pre-existing student gate still gates.
        report_dir(
            lighthouse_rows=[
                _lh_row(slug="student-correct", path="/student/correct", performance=79)
            ]
        )
        assert check_ui_gates.main() == 1


class TestTutoringPerformanceGate:
    """T33 (SPEC §d, "Accessibility and performance gate routes"): Lighthouse performance
    >= 80 on ``/tutors``, ``/tutors/:id`` and every ``/student/*`` route. The two public
    pages sit outside the ``/student`` subtree, so they are gated by slug."""

    def test_public_directory_is_gated(self) -> None:
        assert is_perf_gated_route(_route(path="/tutors", slug="tutors-directory"))

    def test_public_card_is_gated(self) -> None:
        card = _route(
            path="/tutors/6f6b9baf-5c31-41ab-ba1b-5e2bde560fbb", slug="tutors-public-card"
        )
        assert is_perf_gated_route(card)

    def test_student_tutoring_routes_are_gated_by_path(self) -> None:
        for path in (
            "/student/tutors",
            "/student/tutors/abc",
            "/student/tutors/abc/book",
            "/student/sessions",
            "/student/sessions/abc",
            "/student/tutor-access",
        ):
            assert is_perf_gated_route(_route(path=path, slug="any-slug-at-all")), path

    def test_teacher_parent_and_admin_tutoring_routes_are_not_gated(self) -> None:
        for path, slug in (
            ("/teacher/tutoring", "teacher-tutoring-home"),
            ("/parent/tutors", "parent-tutors"),
            ("/platform/tutors", "platform-tutors"),
        ):
            assert not is_perf_gated_route(_route(path=path, slug=slug)), path

    def test_gated_slugs_are_exactly_the_two_public_pages(self) -> None:
        assert set(PERF_GATED_TUTORING_SLUGS) == {"tutors-directory", "tutors-public-card"}

    def test_gated_slugs_are_the_ones_the_audit_registers(self) -> None:
        # A slug the gate names but the audit never writes would gate nothing (the gate only
        # reads rows that exist), so the names are checked against the registry's own text.
        registry = REGISTRY_MODULE.read_text(encoding="utf-8")
        for slug in PERF_GATED_TUTORING_SLUGS:
            assert f'slug: "{slug}"' in registry, slug

    def test_directory_below_floor_fails(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[_lh_row(slug="tutors-directory", path="/tutors", performance=79)]
        )
        assert check_ui_gates.main() == 1

    def test_directory_at_floor_passes(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[_lh_row(slug="tutors-directory", path="/tutors", performance=80)]
        )
        assert check_ui_gates.main() == 0

    def test_student_tutor_profile_below_floor_fails(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[
                _lh_row(slug="student-tutor-profile", path="/student/tutors/abc", performance=79)
            ]
        )
        assert check_ui_gates.main() == 1

    def test_teacher_tutoring_home_at_50_is_not_gated(self, report_dir: WriteReport) -> None:
        report_dir(
            lighthouse_rows=[
                _lh_row(slug="teacher-tutoring-home", path="/teacher/tutoring", performance=50)
            ]
        )
        assert check_ui_gates.main() == 0

    def test_a_route_that_died_mid_run_fails_the_gate(self, report_dir: WriteReport) -> None:
        # P28: an entry whose `ready` never matched (a login redirect, an error page) is a
        # route failure, and the gate reads route-failures.json.
        report_dir(
            lighthouse_rows=[_lh_row(slug="tutors-directory", path="/tutors", performance=95)]
        )
        check_ui_gates.ROUTE_FAILURES.write_text(
            json.dumps(
                [
                    {
                        "screenId": "G-16",
                        "path": "/tutors",
                        "error": "Waiting failed: 20000ms exceeded",
                    }
                ]
            )
        )
        assert check_ui_gates.main() == 1
