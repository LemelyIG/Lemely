# Subject Name as Primary Identifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a subject's human name (e.g. "Physics") the primary identifier everywhere it's displayed, with its CAIE code as secondary metadata, and add a genuine per-subject-enrolment qualification level (IGCSE/O-Level/AS-Level/A-Level) so the identifier can read "Physics IGCSE" where that level is known.

**Architecture:** A new nullable `qualification_level` column on `student_subject_enrolments` (backfilled from the existing per-student `StudentProfile.qualification_level` default). Backend DTOs that already carry `code`/`name` for a subject gain the level and, where they didn't already, a real name resolved via `lemely.io.det.profiles.get_profile`. The frontend gets one shared `subjectIdentifier()` helper that composes a primary (name [+ level]) and secondary (code) string; every screen that shows a subject switches to it.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + Vite (frontend), pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-subject-name-primary-identifier-design.md`

## Global Constraints

- Every new/changed backend field is the **raw enum value** (`"o_level"`), never a pre-formatted label — labels are resolved once, client-side.
- Never invent a subject name or level: fall back to the raw code (`get_profile(code).name or code`) or `None`, exactly like `lemely/web/routers/parent.py::_subject_name` already does.
- Signed commits: `git commit -S`. Conventional commit messages with scopes (`feat(db):`, `feat(web):`, etc.).
- Run `pre-commit run --all-files` and fix all failures before every commit.
- Backend tests requiring Postgres skip cleanly (`pytest.skip("local Postgres not reachable")`) — follow the existing `pg_sessionmaker`/`pg_engine` fixture pattern, never invent a new one.
- Teacher/admin `SchoolClass.subject_code` is free-typed (no FK to `subjects`), so its name resolution must fall back to the raw code exactly like every other `get_profile` call site — never raise on an unrecognised code.

---

## Task 1: Migration — `qualification_level` on `student_subject_enrolments`

**Files:**
- Create: `lemely/db/migrations/versions/0020_enrolment_qual_level.py`
- Modify: `lemely/db/models/profiles.py:93-142` (add column to `StudentSubjectEnrolment`)
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `StudentSubjectEnrolment.qualification_level: QualificationLevel | None` (ORM attribute), reused by Task 2's repo layer.

- [ ] **Step 1: Write the failing schema test**

Add to `tests/test_db_schema.py` (near `test_student_subject_enrolment_unique_per_user_and_subject`):

```python
def test_student_subject_enrolment_qualification_level_is_nullable(
    pg_engine: sa.Engine,
) -> None:
    from lemely.db.models import StudentSubjectEnrolment, Subject, User
    from lemely.db.models.enums import QualificationLevel, Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="qual-level@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-qle", name="Physics")
        session.add(subject)
        session.flush()

        no_level = StudentSubjectEnrolment(user_id=student.id, subject_code=subject.code)
        session.add(no_level)
        session.commit()
        session.refresh(no_level)
        assert no_level.qualification_level is None

        no_level.qualification_level = QualificationLevel.igcse
        session.commit()
        session.refresh(no_level)
        assert no_level.qualification_level is QualificationLevel.igcse
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_schema.py::test_student_subject_enrolment_qualification_level_is_nullable -v`
Expected: FAIL — `pg_engine` builds tables straight from `Base.metadata` (`Base.metadata.create_all(engine)`), so this fails with `AttributeError: 'StudentSubjectEnrolment' object has no attribute 'qualification_level'` until the model changes, or SKIP if no local Postgres — if it skips, proceed anyway and rely on Step 4 to confirm the model change, then come back and run for real once Postgres is available.

- [ ] **Step 3: Add the column to the ORM model**

In `lemely/db/models/profiles.py`, inside `StudentSubjectEnrolment` (after `session_year`, before the `papers` relationship):

```python
    qualification_level: Mapped[QualificationLevel | None] = mapped_column(
        sa.Enum(QualificationLevel, name="qualificationlevel"),
        nullable=True,
    )
    """Per-*subject* qualification level (IGCSE/O-Level/AS/A-Level).

    Distinct from :attr:`StudentProfile.qualification_level`, which is the
    onboarding-time default a new enrolment is seeded from
    (:meth:`~lemely.db.student_profile_repo.StudentProfileService.upsert_enrolment`)
    — a student can mix levels across subjects (IGCSE Physics alongside
    O-Level Math), which a single profile-wide value cannot represent."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_schema.py::test_student_subject_enrolment_qualification_level_is_nullable -v`
Expected: PASS (or SKIP if no local Postgres — acceptable, CI has Postgres)

- [ ] **Step 5: Write the migration**

Create `lemely/db/migrations/versions/0020_enrolment_qual_level.py`:

```python
"""per-subject qualification level on student_subject_enrolments (P5.x)

Revision ID: 0020_enrolment_qual_level
Revises: 0019_activation_review
Create Date: 2026-08-17 00:00:00.000000

Additive: one nullable column on ``student_subject_enrolments``, reusing the
``qualificationlevel`` enum type ``0009_student_profiles`` already created
(``create_type=False`` — this migration does not own that type and must not
re-issue ``CREATE TYPE``). Backfills every existing enrolment row from that
student's ``student_profiles.qualification_level`` (NULL where the student
never set one) — see the design spec's "Backfill" decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0020_enrolment_qual_level"
down_revision: str | Sequence[str] | None = "0019_activation_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "student_subject_enrolments",
        sa.Column(
            "qualification_level",
            postgresql.ENUM(
                "igcse",
                "o_level",
                "as_level",
                "a_level",
                name="qualificationlevel",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE student_subject_enrolments AS e
        SET qualification_level = p.qualification_level
        FROM student_profiles AS p
        WHERE p.user_id = e.user_id
          AND p.qualification_level IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("student_subject_enrolments", "qualification_level")
```

- [ ] **Step 6: Verify against a real Postgres**

Run: `alembic upgrade head` then `alembic check` then `alembic downgrade -1 && alembic upgrade head`
Expected: all three succeed with no output/errors — this is the same upgrade/downgrade/upgrade + `alembic check` cycle `0009_student_profiles`'s own docstring describes.

- [ ] **Step 7: Run pre-commit and the full schema test file**

Run: `pre-commit run --all-files` then `pytest tests/test_db_schema.py -v`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add lemely/db/migrations/versions/0020_enrolment_qual_level.py lemely/db/models/profiles.py tests/test_db_schema.py
git commit -S -m "feat(db): add per-subject qualification level to student_subject_enrolments"
```

---

## Task 2: Repo layer — `SubjectEnrolmentRow` + `upsert_enrolment` default-from-profile

**Files:**
- Modify: `lemely/db/student_profile_repo.py:79-90` (`SubjectEnrolmentRow`), `:258-303` (`upsert_enrolment`), `:489-505` (`_enrolment_row`)
- Test: `tests/test_student_profile_repo.py`

**Interfaces:**
- Consumes: `StudentSubjectEnrolment.qualification_level` (Task 1), `QualificationLevel` enum (`lemely.db.models.enums`).
- Produces: `SubjectEnrolmentRow.qualification_level: QualificationLevel | None`; `StudentProfileService.upsert_enrolment(..., qualification_level: QualificationLevel | str | _UnsetType | None = UNSET)` — new keyword, same `UNSET`/`None`/value semantics as `target_grade`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_student_profile_repo.py` (find the existing `upsert_enrolment`/`list_enrolments` test block and place these alongside it — follow that file's existing `_seed_subject`/`service` fixture pattern, matching `tests/test_web_parent.py`'s `_seed_subject` shown in Task 6):

```python
def test_new_enrolment_defaults_qualification_level_from_profile(
    service: StudentProfileService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A brand-new enrolment with no explicit level inherits the student's profile-level default."""
    student = _seed_student(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    service.update_profile(student, qualification_level=QualificationLevel.igcse)

    row = service.upsert_enrolment(student, "0625")

    assert row.qualification_level is QualificationLevel.igcse


def test_new_enrolment_explicit_level_overrides_profile_default(
    service: StudentProfileService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """An explicit qualification_level on upsert wins over the profile default."""
    student = _seed_student(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    service.update_profile(student, qualification_level=QualificationLevel.igcse)

    row = service.upsert_enrolment(student, "0625", qualification_level=QualificationLevel.o_level)

    assert row.qualification_level is QualificationLevel.o_level


def test_updating_existing_enrolment_with_unset_level_leaves_it_untouched(
    service: StudentProfileService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """UNSET on an update (not a create) is a no-op, matching every other field on this method."""
    student = _seed_student(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    service.upsert_enrolment(student, "0625", qualification_level=QualificationLevel.a_level)

    row = service.upsert_enrolment(student, "0625", target_grade="A")

    assert row.qualification_level is QualificationLevel.a_level


def test_explicit_none_clears_enrolment_qualification_level(
    service: StudentProfileService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """An explicit None on upsert clears a previously-set level, same as target_grade's None."""
    student = _seed_student(pg_sessionmaker)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    service.upsert_enrolment(student, "0625", qualification_level=QualificationLevel.a_level)

    row = service.upsert_enrolment(student, "0625", qualification_level=None)

    assert row.qualification_level is None
```

If this test file has no `_seed_student` helper already, add one near its other seed helpers, mirroring `tests/test_web_parent.py::_seed_user`:

```python
def _seed_student(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    return uid
```

Add the matching imports (`QualificationLevel` from `lemely.db.models.enums`, `User`/`Role` if not already imported) at the top of the file if missing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_student_profile_repo.py -k qualification_level -v`
Expected: FAIL — `upsert_enrolment()` has no `qualification_level` keyword yet (`TypeError: upsert_enrolment() got an unexpected keyword argument`), or SKIP if no local Postgres.

- [ ] **Step 3: Implement**

In `lemely/db/student_profile_repo.py`, update `SubjectEnrolmentRow` (around line 79-90):

```python
@dataclass(frozen=True, slots=True)
class SubjectEnrolmentRow:
    """One (student, subject) enrolment, with its paper numbers (S-01)."""

    enrolment_id: uuid.UUID
    user_id: uuid.UUID
    subject_code: str
    target_grade: str | None
    session_month: SessionMonth | None
    session_year: int | None
    papers: tuple[int, ...]
    qualification_level: QualificationLevel | None
```

Update `_enrolment_row` (around line 489-505) to pass it through:

```python
        return SubjectEnrolmentRow(
            enrolment_id=enrolment.id,
            user_id=enrolment.user_id,
            subject_code=enrolment.subject_code,
            target_grade=enrolment.target_grade,
            session_month=enrolment.session_month,
            session_year=enrolment.session_year,
            papers=tuple(papers),
            qualification_level=enrolment.qualification_level,
        )
```

Update `upsert_enrolment` (around line 258-303) — new keyword, and the create-vs-update branch that defaults it from the profile:

```python
    def upsert_enrolment(
        self,
        user_id: uuid.UUID | str,
        subject_code: str,
        *,
        target_grade: str | _UnsetType | None = UNSET,
        session_month: SessionMonth | _UnsetType | None = UNSET,
        session_year: int | _UnsetType | None = UNSET,
        qualification_level: QualificationLevel | str | _UnsetType | None = UNSET,
    ) -> SubjectEnrolmentRow:
        """Create or partially update the ``(user_id, subject_code)`` enrolment.

        ``qualification_level`` follows the same UNSET/None/value semantics as
        every other keyword here, with one addition: when **creating** a new
        enrolment (no existing row) and the caller leaves it at
        :data:`UNSET`, it defaults to that student's current
        :attr:`~lemely.db.models.profiles.StudentProfile.qualification_level`
        rather than staying ``NULL`` — the onboarding-time default a fresh
        subject inherits until the student overrides it per subject. Updating
        an *existing* enrolment with :data:`UNSET` leaves its level
        untouched, exactly like ``target_grade``.

        Raises:
            StudentProfileValidationError: ``subject_code`` does not exist in
                ``subjects``, or ``target_grade`` is supplied and not a
                member of :data:`~lemely.core.history.GRADE_ORDER`, or
                ``qualification_level`` is supplied as a string that is not a
                member of :class:`QualificationLevel`.
        """
        uid = _as_uuid(user_id)
        if (
            not isinstance(target_grade, _UnsetType)
            and target_grade is not None
            and target_grade not in GRADE_ORDER
        ):
            raise StudentProfileValidationError(f"Unknown target grade: {target_grade!r}")
        resolved_level: QualificationLevel | _UnsetType | None = qualification_level
        if isinstance(qualification_level, str):
            try:
                resolved_level = QualificationLevel(qualification_level)
            except ValueError as exc:
                raise StudentProfileValidationError(
                    f"Unknown qualification level: {qualification_level!r}"
                ) from exc
        with self._sessionmaker() as session, session.begin():
            subject_exists = session.scalars(
                select(Subject.code).where(Subject.code == subject_code)
            ).first()
            if subject_exists is None:
                raise StudentProfileValidationError(f"Unknown subject code: {subject_code!r}")
            row = session.scalars(
                select(StudentSubjectEnrolment).where(
                    StudentSubjectEnrolment.user_id == uid,
                    StudentSubjectEnrolment.subject_code == subject_code,
                )
            ).first()
            is_new = row is None
            if row is None:
                row = StudentSubjectEnrolment(user_id=uid, subject_code=subject_code)
                session.add(row)
            if not isinstance(target_grade, _UnsetType):
                row.target_grade = target_grade
            if not isinstance(session_month, _UnsetType):
                row.session_month = session_month
            if not isinstance(session_year, _UnsetType):
                row.session_year = session_year
            if not isinstance(resolved_level, _UnsetType):
                row.qualification_level = resolved_level
            elif is_new:
                profile = session.get(StudentProfile, uid)
                row.qualification_level = profile.qualification_level if profile else None
            session.flush()
            return self._enrolment_row(session, row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_student_profile_repo.py -k qualification_level -v`
Expected: PASS (or SKIP if no local Postgres)

- [ ] **Step 5: Run the whole repo test file**

Run: `pytest tests/test_student_profile_repo.py -v`
Expected: PASS — confirms nothing else in this module (e.g. every other `upsert_enrolment` caller/test) broke from the new keyword.

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lemely/db/student_profile_repo.py tests/test_student_profile_repo.py
git commit -S -m "feat(db): default a new enrolment's qualification level from the student's profile"
```

---

## Task 3: Student Overview — real subject names + level

**Files:**
- Modify: `lemely/web/routers/student.py:213-303` (`_subjects`, `student_overview`)
- Modify: `lemely/web/schemas_student.py:36-48` (`SubjectRowDTO`)
- Test: `tests/test_web_student.py`

**Interfaces:**
- Consumes: `StudentProfileService.list_enrolments(user_id) -> list[SubjectEnrolmentRow]` (Task 2), `get_profile(code) -> SubjectProfile` (`lemely.io.det.profiles`, already exists).
- Produces: `SubjectRowDTO.qualificationLevel: str | None`; `SubjectRowDTO.name` is now a real human name, not the code.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_student.py`, near `test_overview_subjects_are_aggregated_from_history`:

```python
def test_overview_subject_name_is_real_and_qualification_level_is_included(
    client: TestClient, profile_service: MagicMock
) -> None:
    """SubjectRowDTO.name is a real human name (not the code), and qualificationLevel
    is sourced from the student's enrolment when one exists."""
    profile_service.list_enrolments.return_value = [
        SimpleNamespace(subject_code="0625", qualification_level=QualificationLevel.igcse),
    ]

    body = client.get("/api/student/overview").json()

    by_code = {row["code"]: row for row in body["subjects"]}
    assert by_code["0625"]["name"] == "Physics"
    assert by_code["0625"]["qualificationLevel"] == "igcse"
    # "0620" has no matching enrolment in the fixture — no level, and the
    # unsupported code falls back to itself rather than an invented name.
    assert by_code["0620"]["name"] == "0620"
    assert by_code["0620"]["qualificationLevel"] is None
```

Add the needed imports at the top of `tests/test_web_student.py`:

```python
from types import SimpleNamespace

from lemely.db.models.enums import QualificationLevel
```

- [ ] **Step 2: Wire the `client` fixture to mock `StudentProfileService`**

This router doesn't take `StudentProfileService` yet, and this test file has no Postgres fixture — mock it, following the file's existing `MagicMock()` convention (`upload_repo = MagicMock()` at line 507). Update the `client` fixture (around line 145-153):

```python
@pytest.fixture
def profile_service() -> MagicMock:
    mock = MagicMock()
    mock.list_enrolments.return_value = []
    return mock


@pytest.fixture
def client(seeded_store: HistoryStore, profile_service: MagicMock) -> TestClient:
    """A TestClient whose store + auth resolve to the seeded student."""
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: seeded_store
    app.dependency_overrides[get_student_profile_service] = lambda: profile_service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=STUDENT_ID, role="student"
    )
    return TestClient(app)
```

Add `get_student_profile_service` to the `from lemely.web.deps import (...)` block at the top of the file.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_web_student.py::test_overview_subject_name_is_real_and_qualification_level_is_included -v`
Expected: FAIL — `SubjectRowDTO` has no `qualificationLevel` field yet (pydantic `ValidationError`/`KeyError` on the response), and `name` still echoes the code.

- [ ] **Step 4: Implement**

In `lemely/web/schemas_student.py`, update `SubjectRowDTO` (line 36-48):

```python
class SubjectRowDTO(ApiModel):
    """One subject card on the Overview grid (mirrors ``SubjectRow``)."""

    code: str
    name: str
    qualificationLevel: str | None = None
    detail: str
    pct: int
    papers: int
    trend: str
    grade: str
    barColor: VizColor
    trendUp: bool
```

In `lemely/web/routers/student.py`, add the import:

```python
from lemely.io.det.profiles import get_profile
```

Update `_subjects` (line 213-260ish) to take the enrolment map and resolve real names/levels:

```python
def _subjects(
    history: StudentHistory, enrolments: dict[str, SubjectEnrolmentRow]
) -> list[SubjectRowDTO]:
    """Aggregate history into per-subject Overview rows (data-backed).

    ``pct`` is the mark-weighted mean across the subject's papers; ``trend`` is
    the percentage delta between the first and last recorded paper; ``grade``
    resolves against real boundaries. ``name`` is a real human name resolved
    via :func:`get_profile`, falling back to the raw code for a subject
    outside the three the build supports (never invented — mirrors
    ``lemely.web.routers.parent._subject_name``). ``qualificationLevel``
    comes from the student's enrolment for this subject, when one exists;
    ``None`` for a subject with recorded papers but no formal enrolment.
    ``detail`` reports the paper count only.

    Grade-bearing records only (``docs/quiz-model.md`` §5): every number on
    this row — the mark-weighted mean, the first-to-last delta, and a grade
    resolved against real CAIE boundaries — is a paper claim. A quiz total
    folded into that weighted mean would move a student's forecast grade with
    marks the boundaries were never drawn for. A subject the student has only
    quizzed produces no row, which is honest: they have no standing in it yet.
    """
    boundary_store = GradeBoundaryStore()
    by_code: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
        by_code.setdefault(record.metadata.subject_code, []).append(record)

    rows: list[SubjectRowDTO] = []
    for code, records in sorted(by_code.items()):
        awarded = sum(r.awarded_marks for r in records)
        maximum = sum(r.maximum_marks for r in records)
        pct = round((awarded / maximum) * 100.0) if maximum else 0
        boundaries, _ = boundary_store.resolve(records[-1].metadata)
        delta = round(records[-1].percentage - records[0].percentage)
        enrolment = enrolments.get(code)
        rows.append(
            SubjectRowDTO(
                code=code,
                name=get_profile(code).name or code,
                qualificationLevel=(
                    enrolment.qualification_level.value
                    if enrolment and enrolment.qualification_level
                    else None
                ),
                detail=f"{len(records)} papers corrected",
                pct=pct,
                papers=len(records),
                trend=f"{'+' if delta >= 0 else ''}{delta}",
                grade=_grade_for(float(pct), boundaries),
```

(Leave the rest of the existing `SubjectRowDTO(...)` construction — `barColor`, `trendUp` — untouched below this point.)

Update `student_overview` (line 260-298ish) to fetch enrolments and pass them through:

```python
@router.get("/student/overview", response_model=OverviewDTO)
def student_overview(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> OverviewDTO:
    """Return the student Overview: subject rows, global weak threads, momentum.
    ...(docstring unchanged)...
    """
    history = history_store.load(auth.user_id)
    enrolments = {e.subject_code: e for e in profile_service.list_enrolments(auth.user_id)}
    subjects = _subjects(history, enrolments)
```

`get_student_profile_service` and `StudentProfileService` are already imported at the top of `student.py` (lines 56 and 76) — no new import needed for those two.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_web_student.py::test_overview_subject_name_is_real_and_qualification_level_is_included -v`
Expected: PASS

- [ ] **Step 6: Run the full student router test file**

Run: `pytest tests/test_web_student.py -v`
Expected: PASS (this also exercises `test_overview_subjects_are_aggregated_from_history`, which asserts on `code`/`pct`/`trend` but not `name`, so it is unaffected).

- [ ] **Step 7: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add lemely/web/routers/student.py lemely/web/schemas_student.py tests/test_web_student.py
git commit -S -m "feat(web): resolve real subject names and qualification level on the student Overview"
```

---

## Task 4: Student Subject page — restructure header to name/code/level

**Files:**
- Modify: `lemely/web/routers/student.py:307-416` (`student_subject`)
- Modify: `lemely/web/schemas_student.py:162-171` (`SubjectHeaderDTO`)
- Test: `tests/test_web_student.py`

**Interfaces:**
- Consumes: same `get_profile`/enrolment-map pattern as Task 3.
- Produces: `SubjectHeaderDTO.name: str`, `.code: str`, `.qualificationLevel: str | None`, replacing `.title`/`.meta`.

- [ ] **Step 1: Update the existing test to the new field names**

In `tests/test_web_student.py`, update `test_subject_breakdown_and_history` (around line 308-323):

```python
def test_subject_breakdown_and_history(client: TestClient, profile_service: MagicMock) -> None:
    """Subject endpoint returns per-paper bars, topic map, and paper history."""
    profile_service.list_enrolments.return_value = [
        SimpleNamespace(subject_code="0625", qualification_level=QualificationLevel.o_level),
    ]

    body = client.get("/api/student/subject/0625").json()

    assert body["header"]["name"] == "Physics"
    assert body["header"]["code"] == "0625"
    assert body["header"]["qualificationLevel"] == "o_level"
    assert body["header"]["weightedMean"] == "89"

    breakdown = body["papersBreakdown"]
    assert len(breakdown) == 1  # both papers share paper_number 1
    bars = breakdown[0]["bars"]
    assert [b["value"] for b in bars] == [82, 95]  # rounded percentages, in order
    assert bars[-1]["highlight"] is True

    topics = {t["name"] for t in body["topicMap"]}
    assert "Thermal physics" in topics
    assert "Waves" in topics
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_student.py::test_subject_breakdown_and_history -v`
Expected: FAIL — `header["name"]`/`header["code"]`/`header["qualificationLevel"]` don't exist yet (`KeyError`).

- [ ] **Step 3: Implement**

In `lemely/web/schemas_student.py`, replace `SubjectHeaderDTO` (line 162-171):

```python
class SubjectHeaderDTO(ApiModel):
    """Subject-page header block (mirrors ``subjectHeader``).

    ``name`` is the primary identifier (resolved via ``get_profile``,
    falling back to the raw code); ``code`` and ``qualificationLevel`` are
    secondary metadata the frontend composes alongside it — see
    ``lemely.web.routers.student.student_subject``.
    """

    name: str
    code: str
    qualificationLevel: str | None = None
    intro: str
    forecast: str
    weightedMean: str
    weightedMeanDelta: str
```

In `lemely/web/routers/student.py`, add `StudentProfileService`/`get_student_profile_service` to `student_subject`'s parameters and resolve the level, then rebuild the header:

```python
@router.get("/student/subject/{code}", response_model=SubjectDTO)
def student_subject(
    code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
) -> SubjectDTO:
```

(docstring unchanged). Then, near the end of the function where `header = SubjectHeaderDTO(...)` is built (line 401-408):

```python
    enrolment = next(
        (e for e in profile_service.list_enrolments(auth.user_id) if e.subject_code == code),
        None,
    )
    header = SubjectHeaderDTO(
        name=get_profile(code).name or code,
        code=code,
        qualificationLevel=(
            enrolment.qualification_level.value
            if enrolment and enrolment.qualification_level
            else None
        ),
        intro=f"{len(records)} papers corrected.",
        forecast=_grade_for(float(pct), boundaries),
        weightedMean=str(pct),
        weightedMeanDelta=f"{'+' if delta >= 0 else ''}{delta} since first paper",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_student.py::test_subject_breakdown_and_history -v`
Expected: PASS

- [ ] **Step 5: Run the full student router test file**

Run: `pytest tests/test_web_student.py -v`
Expected: PASS

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lemely/web/routers/student.py lemely/web/schemas_student.py tests/test_web_student.py
git commit -S -m "feat(web): restructure subject-page header into name/code/qualificationLevel"
```

---

## Task 5: Onboarding enrolment DTOs — carry `qualificationLevel`

**Files:**
- Modify: `lemely/web/schemas_student_profile.py:28-45` (`SubjectEnrolmentDTO`), `:92-109` (`EnrolmentUpsertDTO`)
- Modify: `lemely/web/routers/me.py:235-246` (`_enrolment_to_dto`), `:348-365` (`put_student_profile_enrolments`)
- Test: `tests/test_me_router.py`

**Interfaces:**
- Consumes: `SubjectEnrolmentRow.qualification_level` (Task 2).
- Produces: `SubjectEnrolmentDTO.qualificationLevel: str | None`; `EnrolmentUpsertDTO.qualificationLevel: str | None`, round-tripped through `PUT /me/student-profile/enrolments`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_me_router.py` (find its existing enrolment PUT test and place this alongside it, following that file's existing fixtures):

```python
def test_put_enrolments_round_trips_qualification_level(client: TestClient) -> None:
    """A per-subject qualificationLevel in the PUT body is stored and echoed back."""
    body = client.put(
        "/api/me/student-profile/enrolments",
        json={
            "enrolments": [
                {"subjectCode": "0625", "qualificationLevel": "igcse", "papers": []},
            ]
        },
    ).json()

    assert body[0]["qualificationLevel"] == "igcse"

    # A second PUT with the level omitted-as-None clears it (full-desired-state
    # semantics, same as targetGrade/sessionMonth on this endpoint).
    body = client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "qualificationLevel": None, "papers": []}]},
    ).json()

    assert body[0]["qualificationLevel"] is None
```

(This assumes `tests/test_me_router.py` already seeds subject `"0625"` and authenticates a student for its `client` fixture — follow whatever seed helper its other `PUT /enrolments` tests already use, e.g. `test_put_enrolments_unknown_subject_code_is_422`'s setup.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_me_router.py::test_put_enrolments_round_trips_qualification_level -v`
Expected: FAIL — pydantic rejects the unknown `qualificationLevel` key or the response omits it.

- [ ] **Step 3: Implement**

In `lemely/web/schemas_student_profile.py`, add the field to `SubjectEnrolmentDTO` (line 28-45):

```python
class SubjectEnrolmentDTO(ApiModel):
    """One subject enrolment, with its papers and confidence ratings (S-01).
    ...(docstring unchanged)...
    """

    subjectCode: str
    qualificationLevel: str | None = None
    targetGrade: str | None = None
    sessionMonth: str | None = None
    sessionYear: int | None = None
    papers: list[int]
    confidenceRatings: list[ConfidenceRatingDTO]
```

And to `EnrolmentUpsertDTO` (line 92-109):

```python
class EnrolmentUpsertDTO(ApiModel):
    """One item of a ``PUT /api/me/student-profile/enrolments`` request body.
    ...(docstring unchanged)...
    """

    subjectCode: str
    qualificationLevel: str | None = None
    targetGrade: str | None = None
    sessionMonth: str | None = None
    sessionYear: int | None = None
    papers: list[int] | None = None
    """The full desired paper-number set for this subject. ``None``/omitted means "no papers"."""
```

In `lemely/web/routers/me.py`, update `_enrolment_to_dto` (line 235-245):

```python
def _enrolment_to_dto(
    row: SubjectEnrolmentRow, ratings: list[ConfidenceRatingRow]
) -> SubjectEnrolmentDTO:
    return SubjectEnrolmentDTO(
        subjectCode=row.subject_code,
        qualificationLevel=row.qualification_level.value if row.qualification_level else None,
        targetGrade=row.target_grade,
        sessionMonth=row.session_month.value if row.session_month else None,
        sessionYear=row.session_year,
        papers=list(row.papers),
        confidenceRatings=[_rating_to_dto(r) for r in ratings],
    )
```

Update `put_student_profile_enrolments` (line 348-365) to pass the level through — every field on `EnrolmentUpsertDTO` is already full-desired-state (not a patch), so this passes the raw value straight to `upsert_enrolment`, letting its own validation (Task 2, Step 3) reject an unknown string:

```python
    results: list[SubjectEnrolmentDTO] = []
    try:
        for item in payload.enrolments:
            enrolment = service.upsert_enrolment(
                auth.user_id,
                item.subjectCode,
                target_grade=item.targetGrade,
                session_month=_session_month_from_dto(item.sessionMonth),
                session_year=item.sessionYear,
                qualification_level=item.qualificationLevel,
            )
```

(Rest of the function body is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_me_router.py::test_put_enrolments_round_trips_qualification_level -v`
Expected: PASS

- [ ] **Step 5: Run the full me-router test file**

Run: `pytest tests/test_me_router.py -v`
Expected: PASS

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lemely/web/schemas_student_profile.py lemely/web/routers/me.py tests/test_me_router.py
git commit -S -m "feat(web): round-trip per-subject qualificationLevel through the enrolments endpoint"
```

---

## Task 6: Parent portal — real names already present, add `qualificationLevel`

**Files:**
- Modify: `lemely/web/schemas_parent.py:173-192` (`SubjectOverviewDTO`), `:243-258` (`SubjectDetailDTO`)
- Modify: `lemely/web/routers/parent.py:372-436` (`parent_child_overview`), `:444+` (`parent_child_subject`)
- Test: `tests/test_web_parent.py`

**Interfaces:**
- Consumes: `StudentProfileService.list_enrolments` (already injected in both routes as `profile_service`).
- Produces: `SubjectOverviewDTO.qualificationLevel: str | None`, `SubjectDetailDTO.qualificationLevel: str | None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_parent.py`, following the exact seeding pattern of `test_child_overview_surfaces_a_real_below_target_flag_when_a_target_is_set` (line 569-599):

```python
def test_child_overview_includes_qualification_level_per_subject(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    history_store: HistoryStore,
    profile_service: StudentProfileService,
) -> None:
    """A subject's qualificationLevel comes from the child's own enrolment for it."""
    parent = _seed_user(pg_sessionmaker, Role.parent)
    student = _seed_user(pg_sessionmaker, Role.student)
    _link(pg_sessionmaker, parent_id=parent, child_id=student)
    _seed_subject(pg_sessionmaker, code="0625", name="Physics")
    profile_service.upsert_enrolment(student, "0625", qualification_level="igcse")
    history_store.append(
        str(student),
        _paper(
            student_id=student, percentage=80.0, grade="B", recorded_at="2026-08-04T10:00:00+00:00"
        ),
    )

    _auth_as(client, parent, Role.parent)
    overview = client.get(f"/api/parent/children/{student}").json()
    assert overview["subjects"][0]["qualificationLevel"] == "igcse"

    detail = client.get(f"/api/parent/children/{student}/subjects/0625").json()
    assert detail["qualificationLevel"] == "igcse"
```

(`_paper` is this file's existing paper-fixture helper, used identically by the neighboring at-risk test — reuse it, don't redefine it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_parent.py::test_child_overview_includes_qualification_level_per_subject -v`
Expected: FAIL — `KeyError: 'qualificationLevel'` on both responses.

- [ ] **Step 3: Implement**

In `lemely/web/schemas_parent.py`, add the field to `SubjectOverviewDTO` (line 173-192):

```python
class SubjectOverviewDTO(ApiModel):
    """One subject's standing on the child overview (P-02).
    ...(docstring unchanged)...
    """

    subjectCode: str
    subjectName: str
    qualificationLevel: str | None = None
    predictedGrade: str
    target: str | None = None
    latestPercentage: float
    paperCount: int
    trend: list[SubjectTrendPointDTO] = Field(default_factory=list)
```

And to `SubjectDetailDTO` (line 243-258):

```python
class SubjectDetailDTO(ApiModel):
    """Response for ``GET /api/parent/children/{child_id}/subjects/{code}`` (P-03).
    ...(docstring unchanged)...
    """

    childId: str
    subjectCode: str
    subjectName: str
    qualificationLevel: str | None = None
    predictedGrade: str
    papers: list[SubjectPaperDTO] = Field(default_factory=list)
    boundaryDistance: GradeBoundaryDistanceDTO | None = None
    weakTopics: list[WeakTopicDTO] = Field(default_factory=list)
```

In `lemely/web/routers/parent.py`, update `parent_child_overview` (line 372-436) to build an enrolment map and pass the level through:

```python
    child = _authorized_child(parent_link_service, class_service, auth, child_id)
    history = history_store.load(str(child.child_id))
    now = datetime.now(UTC)
    enrolments = {e.subject_code: e for e in profile_service.list_enrolments(child.child_id)}

    by_subject: dict[str, list[PaperRecord]] = {}
    for record in grade_bearing(history.records):
        by_subject.setdefault(record.metadata.subject_code, []).append(record)
    subjects = [
        SubjectOverviewDTO(
            subjectCode=code,
            subjectName=_subject_name(code),
            qualificationLevel=(
                enrolments[code].qualification_level.value
                if code in enrolments and enrolments[code].qualification_level
                else None
            ),
            predictedGrade=subject_records[-1].grade,
            target=None,
            latestPercentage=subject_records[-1].percentage,
            paperCount=len(subject_records),
            trend=[
                SubjectTrendPointDTO(recordedAt=r.recorded_at, percentage=r.percentage)
                for r in subject_records
            ],
        )
        for code, subject_records in sorted(by_subject.items())
    ]
```

(Rest of the function — `recent_papers`, `targets`, `assessment`, the return — is unchanged.)

Now find `parent_child_subject` (starts at line 444) and read it in full before editing (its body wasn't captured above — its signature already takes `profile_service` or needs it added, matching `parent_child_overview`'s pattern). Add a `profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)]` parameter if it doesn't already have one, then build `SubjectDetailDTO` with:

```python
    enrolment = next(
        (e for e in profile_service.list_enrolments(child.child_id) if e.subject_code == code),
        None,
    )
    return SubjectDetailDTO(
        childId=str(child.child_id),
        subjectCode=code,
        subjectName=_subject_name(code),
        qualificationLevel=(
            enrolment.qualification_level.value
            if enrolment and enrolment.qualification_level
            else None
        ),
        # ...remaining existing fields unchanged...
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_parent.py::test_child_overview_includes_qualification_level_per_subject -v`
Expected: PASS

- [ ] **Step 5: Run the full parent router test file**

Run: `pytest tests/test_web_parent.py -v`
Expected: PASS

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lemely/web/schemas_parent.py lemely/web/routers/parent.py tests/test_web_parent.py
git commit -S -m "feat(web): surface per-subject qualificationLevel on the parent portal"
```

---

## Task 7: Teacher/admin classes — real subject name (no level)

**Files:**
- Modify: `lemely/web/routers/classes.py:176-221` (`_class_row_to_summary`), `:223+` (`_class_row_to_detail`)
- Modify: `lemely/web/schemas_teacher.py:378-416` (`ClassSummaryDTO`), `:424-453` (`ClassDetailDTO`)
- Test: `tests/test_web_teacher.py` (or wherever this router's existing class-list/class-detail tests live — follow its established `_class`/`_seed_class` fixtures)

**Interfaces:**
- Consumes: `get_profile(code) -> SubjectProfile` (already used in Task 3/4/6 — same function, new call site). `SchoolClass.subject_code` is nullable and **not** FK'd to `subjects`, so this must tolerate an unrecognised or `None` code exactly like every other `get_profile` call site (falls back to the raw code, never raises).
- Produces: `ClassSummaryDTO.subjectName: str | None`, `ClassDetailDTO.subjectName: str | None` (both `None` exactly when `subjectCode` is `None`).

- [ ] **Step 1: Write the failing test**

Locate this router's existing class-list test (search `tests/test_web_teacher.py` for `def test_list_classes` or similar — reuse its exact class-seeding helper) and add:

```python
def test_class_summary_includes_a_real_subject_name(client: TestClient, ...) -> None:
    """subjectName resolves the human name for a known code; unset code -> unset name."""
    # ...seed one class with subject_code="0625" and one with subject_code=None,
    # using this file's existing class-seed helper...
    body = client.get("/api/teacher/classes").json()
    by_id = {c["id"]: c for c in body["classes"]}
    physics = next(c for c in body["classes"] if c["subjectCode"] == "0625")
    assert physics["subjectName"] == "Physics"
    no_subject = next(c for c in body["classes"] if c["subjectCode"] is None)
    assert no_subject["subjectName"] is None
```

Adapt the fixture setup lines to match whatever this file's real class-creation helper is named (found in Step 0 above) — do not invent a new seeding path.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_teacher.py -k class_summary_includes_a_real_subject_name -v`
Expected: FAIL — `KeyError: 'subjectName'`.

- [ ] **Step 3: Implement**

In `lemely/web/schemas_teacher.py`, add to `ClassSummaryDTO` (line 378-416):

```python
    id: str
    label: str
    studentCount: int
    average: float | None = None
    subjectCode: str | None = None
    subjectName: str | None = None
    schoolId: str | None = None
```

(Insert `subjectName` right after `subjectCode`; rest of the class unchanged.) Same edit to `ClassDetailDTO` (line 424-453):

```python
    id: str
    label: str
    stats: list[StatCardDTO] = Field(default_factory=list)
    mastery: list[MasteryRowDTO] = Field(default_factory=list)
    distribution: list[DistributionBarDTO] = Field(default_factory=list)
    students: list[StudentRowDTO] = Field(default_factory=list)
    subjectCode: str | None = None
    subjectName: str | None = None
    schoolId: str | None = None
```

In `lemely/web/routers/classes.py`, add the import:

```python
from lemely.io.det.profiles import get_profile
```

Add a tiny local resolver right above `_class_row_to_summary` (mirrors `parent.py::_subject_name`, but tolerates `None`):

```python
def _class_subject_name(code: str | None) -> str | None:
    """Human name for a class's subject code, or ``None`` when the class has none set.

    Mirrors ``lemely.web.routers.parent._subject_name``, with the one
    difference this call site needs: ``SchoolClass.subject_code`` is
    nullable and not FK'd to ``subjects`` (a teacher types it freely), so an
    absent code must stay absent rather than resolving to some default name.
    """
    if code is None:
        return None
    return get_profile(code).name or code
```

Then in `_class_row_to_summary`'s return (line 209-220), add one line:

```python
    return ClassSummaryDTO(
        id=str(row.class_id),
        label=row.name,
        studentCount=row.student_count,
        average=average,
        subjectCode=row.subject_code,
        subjectName=_class_subject_name(row.subject_code),
        schoolId=str(row.school_id) if row.school_id is not None else None,
        joinCode=row.join_code,
        atRiskCount=at_risk_count,
        lastActivityAt=_latest_activity(histories),
        topWeakness=ranked[0].topic if ranked else None,
    )
```

And the equivalent single line in `_class_row_to_detail`'s `ClassDetailDTO(...)` construction (around line 338, `subjectCode=row.subject_code,` — add `subjectName=_class_subject_name(row.subject_code),` directly after it).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_teacher.py -k class_summary_includes_a_real_subject_name -v`
Expected: PASS

- [ ] **Step 5: Run the full teacher/classes test files**

Run: `pytest tests/test_web_teacher.py tests/test_web_classes.py -v` (adjust to whichever file(s) actually cover `lemely/web/routers/classes.py` — confirm with `pytest --collect-only -q | grep -i class`)
Expected: PASS

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add lemely/web/routers/classes.py lemely/web/schemas_teacher.py tests/test_web_teacher.py
git commit -S -m "feat(web): resolve a real subject name for teacher/admin class summaries"
```

---

## Task 8: Shared frontend helper — `qualificationLevels` + `subjectIdentifier`

**Files:**
- Create: `web/src/lib/qualificationLevels.ts`
- Modify: `web/src/components/ui/subject-tag.tsx` (add `subjectIdentifier`)
- Modify: `web/src/portals/student/screens/onboarding/onboardingData.ts:78-84` (re-export instead of duplicate)
- Test: `web/tests/unit/subjectIdentifier.test.ts` (new)

**Interfaces:**
- Produces: `QUALIFICATION_LEVELS: { value: string; label: string }[]`, `qualificationLevelLabel(value: string | null | undefined): string | null` (in `qualificationLevels.ts`); `subjectIdentifier(name: string, code: string, level?: string | null): { primary: string; secondary: string }` (in `subject-tag.tsx`).

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/subjectIdentifier.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { subjectIdentifier } from "@/components/ui/subject-tag"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"

describe("qualificationLevelLabel", () => {
  it("resolves a known raw value to its label", () => {
    expect(qualificationLevelLabel("o_level")).toBe("O-Level")
  })

  it("returns null for null/undefined/unknown", () => {
    expect(qualificationLevelLabel(null)).toBeNull()
    expect(qualificationLevelLabel(undefined)).toBeNull()
    expect(qualificationLevelLabel("not_a_level")).toBeNull()
  })
})

describe("subjectIdentifier", () => {
  it("composes name-primary with level and code in the secondary line", () => {
    expect(subjectIdentifier("Physics", "0625", "igcse")).toEqual({
      primary: "Physics",
      secondary: "IGCSE · 0625",
    })
  })

  it("omits the level segment when level is null", () => {
    expect(subjectIdentifier("Physics", "0625", null)).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })

  it("omits the level segment when level is omitted entirely", () => {
    expect(subjectIdentifier("Physics", "0625")).toEqual({
      primary: "Physics",
      secondary: "0625",
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run web/tests/unit/subjectIdentifier.test.ts`
Expected: FAIL — neither `qualificationLevels.ts` nor `subjectIdentifier` exist yet (module resolution error).

- [ ] **Step 3: Implement**

Create `web/src/lib/qualificationLevels.ts`:

```ts
/**
 * The four CAIE qualification levels a subject enrolment can carry (mirrors
 * `lemely.db.models.enums.QualificationLevel`). Single source of truth for
 * this label table — `subjectIdentifier` (subject-tag.tsx) and onboarding's
 * `SubjectsStep` both import it rather than keeping their own copy.
 */
export const QUALIFICATION_LEVELS: { value: string; label: string }[] = [
  { value: "igcse", label: "IGCSE" },
  { value: "o_level", label: "O-Level" },
  { value: "as_level", label: "AS-Level" },
  { value: "a_level", label: "A-Level" },
]

/** The human label for a raw qualification-level value, or `null` for
 * null/undefined/unrecognised — never an invented label. */
export function qualificationLevelLabel(value: string | null | undefined): string | null {
  if (!value) return null
  return QUALIFICATION_LEVELS.find((l) => l.value === value)?.label ?? null
}
```

In `web/src/components/ui/subject-tag.tsx`, add the import and the new function (after the existing `SubjectTag` export):

```ts
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
```

```ts
/**
 * Compose a subject's primary/secondary display text: the name leads,
 * the qualification level (when known) and the code follow as secondary,
 * muted detail. Every screen that shows a subject renders through this
 * rather than inventing its own primary/secondary split — see the design
 * spec (`docs/superpowers/specs/2026-08-17-subject-name-primary-identifier-design.md`).
 */
export function subjectIdentifier(
  name: string,
  code: string,
  level?: string | null,
): { primary: string; secondary: string } {
  const levelLabel = qualificationLevelLabel(level)
  return {
    primary: name,
    secondary: levelLabel ? `${levelLabel} · ${code}` : code,
  }
}
```

In `web/src/portals/student/screens/onboarding/onboardingData.ts`, replace the local `QUALIFICATION_LEVELS` declaration (line 78-84) with a re-export, so there is exactly one table:

```ts
export { QUALIFICATION_LEVELS } from "@/lib/qualificationLevels"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run web/tests/unit/subjectIdentifier.test.ts`
Expected: PASS

- [ ] **Step 5: Run the full frontend unit suite**

Run: `npx vitest run`
Expected: PASS — confirms the `onboardingData.ts` re-export didn't break `SubjectsStep`'s existing import (`import { QUALIFICATION_LEVELS } from "./onboardingData"` still resolves).

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/qualificationLevels.ts web/src/components/ui/subject-tag.tsx web/src/portals/student/screens/onboarding/onboardingData.ts web/tests/unit/subjectIdentifier.test.ts
git commit -S -m "feat(web): add a shared subjectIdentifier helper for name-primary subject display"
```

---

## Task 9: TypeScript DTO mirrors

**Files:**
- Modify: `web/src/lib/studentTypes.ts:25-35` (`SubjectRow`), `:117-125` (`SubjectHeader`)
- Modify: `web/src/lib/meTypes.ts:42-49` (`SubjectEnrolment`), `:97-103` (`EnrolmentUpsert`)
- Modify: `web/src/lib/parentTypes.ts:98-109` (`SubjectOverview`), `:136-145` (`SubjectDetail`)
- Modify: `web/src/lib/teacherTypes.ts:281-292` (`ClassSummary`), `:370-383` (`ClassDetail`)

No test file — these are pure type declarations with no runtime behavior; TypeScript compilation itself is the check (Step 2 below).

**Interfaces:**
- Consumes: every backend DTO shape added in Tasks 3-7.
- Produces: the exact frontend mirror types every Task 10-14 screen imports.

- [ ] **Step 1: Update `web/src/lib/studentTypes.ts`**

`SubjectRow` (line 25-35):

```ts
export interface SubjectRow {
  code: string
  name: string
  qualificationLevel: string | null
  detail: string
  pct: number
  papers: number
  trend: string
  grade: string
  barColor: VizColor
  trendUp: boolean
}
```

`SubjectHeader` (line 117-125) — replace `meta`/`title` with `name`/`code`/`qualificationLevel`:

```ts
/** Subject-page header block (mirrors `SubjectHeaderDTO`). */
export interface SubjectHeader {
  name: string
  code: string
  qualificationLevel: string | null
  intro: string
  forecast: string
  weightedMean: string
  weightedMeanDelta: string
}
```

- [ ] **Step 2: Update `web/src/lib/meTypes.ts`**

`SubjectEnrolment` (line 42-49):

```ts
export interface SubjectEnrolment {
  subjectCode: string
  qualificationLevel: string | null
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
  papers: number[]
  confidenceRatings: ConfidenceRating[]
}
```

`EnrolmentUpsert` (line 97-103):

```ts
export interface EnrolmentUpsert {
  subjectCode: string
  qualificationLevel: string | null
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
  papers: number[] | null
}
```

- [ ] **Step 3: Update `web/src/lib/parentTypes.ts`**

`SubjectOverview` (line 98-109):

```ts
export interface SubjectOverview {
  subjectCode: string
  /** Translated name, falling back to the raw code when unknown — never invented. */
  subjectName: string
  qualificationLevel: string | null
  predictedGrade: string
  /** Always null until Phase 4 (see the module header). */
  target: string | null
  latestPercentage: number
  paperCount: number
  /** Oldest first. */
  trend: SubjectTrendPoint[]
}
```

`SubjectDetail` (line 136-145):

```ts
export interface SubjectDetail {
  childId: string
  subjectCode: string
  subjectName: string
  qualificationLevel: string | null
  predictedGrade: string
  papers: SubjectPaper[]
  /** null when not computable (already on A*, or no boundary row) — omit the panel. */
  boundaryDistance: GradeBoundaryDistance | null
  weakTopics: WeakTopic[]
}
```

- [ ] **Step 4: Update `web/src/lib/teacherTypes.ts`**

`ClassSummary` (line 281-292):

```ts
export interface ClassSummary {
  id: string
  label: string
  studentCount: number
  average: number | null
  subjectCode: string | null
  subjectName: string | null
  schoolId: string | null
  joinCode: string | null
  atRiskCount: number | null
  lastActivityAt: string | null
  topWeakness: string | null
}
```

`ClassDetail` (line 370-383):

```ts
export interface ClassDetail {
  id: string
  label: string
  stats: StatCard[]
  mastery: MasteryRow[]
  distribution: DistributionBar[]
  students: StudentRow[]
  subjectCode: string | null
  subjectName: string | null
  schoolId: string | null
  joinCode: string | null
  atRiskCount: number | null
  lastActivityAt: string | null
  topWeakness: string | null
}
```

- [ ] **Step 5: Run the TypeScript compiler to surface every call site these renamed/added fields break**

Run: `cd web && npm run typecheck`
Expected: a list of errors in exactly the screens Tasks 10-14 are about to fix (e.g. `Property 'title' does not exist on type 'SubjectHeader'` in `Subject.tsx`). This list is the authoritative checklist for those tasks — do not fix them here, just confirm the errors are the expected ones (name/title/meta mismatches in the screens listed in this plan) and none are unrelated collateral damage.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/studentTypes.ts web/src/lib/meTypes.ts web/src/lib/parentTypes.ts web/src/lib/teacherTypes.ts
git commit -S -m "feat(web): update TS DTO mirrors for qualificationLevel and subjectName fields"
```

---

## Task 10: Student Overview — flip the subject ledger row

**Files:**
- Modify: `web/src/portals/student/screens/Overview.tsx:119-171` (`SubjectLedgerRow`)
- Test: `web/tests/unit/` — if this component has no existing unit test, this task's verification is `tsc --noEmit` + a manual check via Step 4; do not invent a component test harness this codebase doesn't already use for this screen (check first: `ls web/tests/unit | grep -i overview`).

**Interfaces:**
- Consumes: `SubjectRow` (Task 9), `subjectIdentifier` (Task 8).

- [ ] **Step 1: Check for an existing test**

Run: `find web/tests -iname '*overview*'`
If a test file exists covering `SubjectLedgerRow`, read it and update its expectations in this same step (name-primary, code/level secondary) before touching the component, following this plan's TDD order. If none exists, proceed directly to Step 2 — this screen has no established unit-test harness to extend.

- [ ] **Step 2: Implement**

In `web/src/portals/student/screens/Overview.tsx`, add the import:

```ts
import { subjectIdentifier } from "@/components/ui/subject-tag"
```

Replace the code-chip-plus-conditional-name block (line 146-171) with:

```tsx
      <div className="flex items-center gap-3 md:contents">
        {(() => {
          const { primary, secondary } = subjectIdentifier(row.name, row.code, row.qualificationLevel)
          return (
            <>
              {/* Name leads — the pastel tone still comes from `subjectToneForCode`,
                  §3.8's single lookup table, now carrying the code chip rather
                  than doubling as the row's identity. */}
              <span
                className={cn(
                  "inline-flex shrink-0 items-center rounded-sm px-2 py-1 text-data-sm",
                  toneFill(subjectToneForCode(row.code)),
                )}
              >
                {row.code}
              </span>

              <span className="flex flex-col gap-0.5 flex-1 min-w-0 md:flex-none">
                <span className="truncate text-body-md font-medium text-ink">{primary}</span>
                <span className="truncate text-body-sm text-ink-faint">
                  {secondary} · {row.detail}
                </span>
              </span>
            </>
          )
        })()}

        <GradeBadge
          grade={row.grade}
          size="inline"
          basis="predicted"
          className="md:hidden"
        />
      </div>
```

This removes the `row.name !== row.code` guard entirely (the backend now always supplies a real name, per Task 3) and the stale comment explaining it.

- [ ] **Step 3: Type-check**

Run: `cd web && npm run typecheck`
Expected: the `Overview.tsx` errors from Task 9 Step 5 are gone.

- [ ] **Step 4: Manual verification**

Run the dev server (`cd web && npm run dev`), sign in as a seeded student with at least one recorded subject, and open `/student`. Confirm the ledger row shows the subject name in the prominent position and "`LEVEL · CODE · N papers`" (or "`CODE · N papers`" when level is unknown) as the muted line beneath it.

- [ ] **Step 5: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/portals/student/screens/Overview.tsx
git commit -S -m "feat(web): lead the student Overview ledger row with the subject name"
```

---

## Task 11: Student Subject page — header uses the new DTO shape

**Files:**
- Modify: `web/src/portals/student/screens/Subject.tsx:101-126`

**Interfaces:**
- Consumes: `SubjectHeader` (Task 9), `subjectIdentifier` (Task 8).

- [ ] **Step 1: Implement**

In `web/src/portals/student/screens/Subject.tsx`, add the import:

```ts
import { subjectIdentifier } from "@/components/ui/subject-tag"
```

Replace the destructure and the `meta`/`title` render (line 101 and 120-126):

```tsx
  const { header: subjectHeader, papersBreakdown, topicMap, paperHistory } = data
  const { primary, secondary } = subjectIdentifier(
    subjectHeader.name,
    subjectHeader.code,
    subjectHeader.qualificationLevel,
  )
```

```tsx
        <div className="min-w-0 flex-1 basis-80">
          <div className="text-data-sm text-ink-muted">{secondary}</div>
          <h1 className="mt-1 text-display-lg text-ink">{primary}</h1>
          <div className="mt-2 max-w-[62ch] text-pretty text-body-md text-ink-muted">
            {subjectHeader.intro}
          </div>
        </div>
```

- [ ] **Step 2: Type-check**

Run: `cd web && npm run typecheck`
Expected: the `Subject.tsx` errors from Task 9 Step 5 are gone.

- [ ] **Step 3: Manual verification**

Open `/student/subject/0625` (or whichever seeded subject code is available) in the running dev server. Confirm the H1 reads the subject name (e.g. "Physics") and the small line above it reads "`LEVEL · 0625`" or "`0625`".

- [ ] **Step 4: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/portals/student/screens/Subject.tsx
git commit -S -m "feat(web): render the Subject page header from name/code/qualificationLevel"
```

---

## Task 12: Student sidebar — include level in the nav tag

**Files:**
- Modify: `web/src/portals/student/index.tsx:236-262` (`SubjectNavGroup`)

**Interfaces:**
- Consumes: `subjectIdentifier` (Task 8). `SubjectRow` (used as `subject: SubjectRow` here) already carries `qualificationLevel` after Task 9.

- [ ] **Step 1: Implement**

In `web/src/portals/student/index.tsx`, add the import:

```ts
import { subjectIdentifier } from "@/components/ui/subject-tag"
```

In `SubjectNavGroup` (line 236-262), the row already renders `label={subject.name}` (name-primary, correct) — only the `tag` needs to switch from the bare code to the composed secondary text:

```tsx
function SubjectNavGroup({
  subject,
  expanded,
  onToggle,
  onNavigate,
  touch,
}: {
  subject: SubjectRow
  expanded: boolean
  onToggle: () => void
  onNavigate: () => void
  touch?: boolean
}) {
  const Glyph = subjectIcon(subject.code)
  const { secondary } = subjectIdentifier(subject.name, subject.code, subject.qualificationLevel)
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <NavRow
            to={`/student/subject/${subject.code}`}
            label={subject.name}
            icon={Glyph}
            tag={secondary}
            touch={touch}
            onClick={onNavigate}
          />
        </div>
```

(Rest of the function unchanged.)

- [ ] **Step 2: Type-check**

Run: `cd web && npm run typecheck`
Expected: no new errors from this file.

- [ ] **Step 3: Manual verification**

In the running dev server, open the student sidebar and confirm each enrolled subject's row shows the name with "`LEVEL · CODE`" (or just the code) as its trailing tag.

- [ ] **Step 4: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/portals/student/index.tsx
git commit -S -m "feat(web): show qualification level in the student sidebar's subject tag"
```

---

## Task 13: Parent portal — add level to the existing name-primary rows

**Files:**
- Modify: `web/src/portals/parent/screens/ChildOverview.tsx:44-73` (`SubjectRow`)
- Modify: `web/src/portals/parent/screens/SubjectDetail.tsx:89-99`

**Interfaces:**
- Consumes: `subjectIdentifier` (Task 8), `SubjectOverview`/`SubjectDetail` (Task 9).

- [ ] **Step 1: Implement — `ChildOverview.tsx`**

Add the import and use `subjectIdentifier` for the secondary line (line 44-57):

```ts
import { subjectIdentifier } from "@/components/ui/subject-tag"
```

```tsx
function SubjectRow({ childId, subject }: { childId: string; subject: SubjectOverview }) {
  const { primary, secondary } = subjectIdentifier(
    subject.subjectName,
    subject.subjectCode,
    subject.qualificationLevel,
  )
  return (
    <Link
      to={`/parent/children/${childId}/subjects/${subject.subjectCode}`}
      className="group flex items-center gap-4 rounded-lg border border-rule bg-paper-raised p-5 transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <GradeBadge grade={subject.predictedGrade} size="inline" basis="predicted" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="text-body-lg font-medium text-ink">{primary}</div>
        <div className="text-body-sm text-ink-muted">
          <span className="text-data-sm">{secondary}</span> ·{" "}
          {subject.paperCount === 1 ? "1 paper" : `${subject.paperCount} papers`} · latest{" "}
          <span className="text-data-sm">{Math.round(subject.latestPercentage)}%</span>
        </div>
```

(Rest of the component unchanged.)

- [ ] **Step 2: Implement — `SubjectDetail.tsx`**

Add the import and replace the header block (line 89-99):

```ts
import { subjectIdentifier } from "@/components/ui/subject-tag"
```

```tsx
export function SubjectDetail() {
  const { childId = "", code = "" } = useParams<{ childId: string; code: string }>()
  const { data, isPending, isError, error } = useChildSubject(childId, code)
```

...and, inside the success render (where `data.subjectName`/`data.subjectCode` are used):

```tsx
  const { primary, secondary } = subjectIdentifier(
    data.subjectName,
    data.subjectCode,
    data.qualificationLevel,
  )
```

```tsx
          <div className="flex flex-col gap-0.5">
            <h1 className="text-display-lg text-ink">{primary}</h1>
            {/* Level + code as secondary detail, never the headline (§4.8 design
                note), and on the data face, which is what a syllabus code is. */}
            <div className="text-data-sm text-ink-faint">{secondary}</div>
          </div>
```

(Place the `subjectIdentifier` call right after the existing `const { papers, boundaryDistance, weakTopics } = data` destructure at line 87, and remove the old `data.subjectCode` reference it replaces.)

- [ ] **Step 3: Type-check**

Run: `cd web && npm run typecheck`
Expected: no new errors in either file.

- [ ] **Step 4: Manual verification**

In the running dev server, sign in as a seeded parent, open a child's overview and one of their subjects; confirm both screens show the subject name prominently with "`LEVEL · CODE`" (or code-only) beneath it.

- [ ] **Step 5: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/portals/parent/screens/ChildOverview.tsx web/src/portals/parent/screens/SubjectDetail.tsx
git commit -S -m "feat(web): show qualification level alongside subject name on parent screens"
```

---

## Task 14: Teacher/admin classes — name-primary, code secondary (no level)

**Files:**
- Modify: `web/src/portals/teacher/screens/Classes.tsx` (subject cell in the class table)
- Modify: `web/src/portals/teacher/screens/ClassDetail.tsx:114-119` (eyebrow line)
- Modify: `web/src/portals/admin/screens/Classes.tsx:108-121` (subject cell)

**Interfaces:**
- Consumes: `ClassSummary`/`ClassDetail` (Task 9, `subjectName` field). No `subjectIdentifier` call here — teacher/admin scope is name+code, no level (per the spec's decision), and both fields are already separate strings, so this is a direct render, not the helper.

- [ ] **Step 1: Implement — `web/src/portals/teacher/screens/Classes.tsx`**

Find the subject-code table cell (search this file for `subjectCode` in its render — it's a `<TD>` rendering the raw code, analogous to the admin cell already shown in this plan's research). Replace the bare code render with name-primary, code-secondary:

```tsx
                <TD>
                  {c.subjectCode ? (
                    <div className="flex flex-col gap-0.5">
                      <span className="text-body-sm text-ink">{c.subjectName ?? c.subjectCode}</span>
                      <span className="text-data-sm text-ink-faint">{c.subjectCode}</span>
                    </div>
                  ) : (
                    <span className="text-body-sm text-ink-faint">Not set</span>
                  )}
                </TD>
```

(Match the surrounding `<TD>` structure exactly as it exists in the file — the snippet above is the content change; keep whatever `key`/`className` wrapper the existing cell already has.)

- [ ] **Step 2: Implement — `web/src/portals/teacher/screens/ClassDetail.tsx`**

Replace the eyebrow line (line 114-119):

```tsx
          <div className="min-w-0">
            <div className="text-eyebrow text-ink-faint">
              {classDetail.subjectCode
                ? `${classDetail.subjectName ?? classDetail.subjectCode} · ${classDetail.subjectCode}`
                : "No subject set"}
            </div>
            <h1 className="text-display-md mt-1.5 text-pretty">
              {classDetail.label}
            </h1>
          </div>
```

- [ ] **Step 3: Implement — `web/src/portals/admin/screens/Classes.tsx`**

Replace the subject badge cell (line 108-121):

```tsx
                <TD>
                  {schoolClass.subjectCode ? (
                    // A bare syllabus code, so the tone comes from
                    // `subjectToneForCode` rather than `SubjectTag`'s
                    // name-based lookup, which would fall back to "other" for
                    // every class in the school.
                    <div className="flex items-center gap-2">
                      <Badge tone={subjectToneForCode(schoolClass.subjectCode)}>
                        {schoolClass.subjectName ?? schoolClass.subjectCode}
                      </Badge>
                      <span className="text-data-sm text-ink-faint">{schoolClass.subjectCode}</span>
                    </div>
                  ) : (
                    <span className="text-body-sm text-ink-faint">Not set</span>
                  )}
                </TD>
```

(`schoolClass`'s type here is `ClassSummary`, same as teacher — confirm the exact local variable name matches what Task 9's research found; this plan used `schoolClass` per the original file read.)

- [ ] **Step 4: Type-check**

Run: `cd web && npm run typecheck`
Expected: no new errors in any of the three files.

- [ ] **Step 5: Manual verification**

In the running dev server, sign in as a teacher and an admin; confirm the classes list and a class-detail page both show the subject's name with its code as smaller secondary text (or "Not set"/"No subject set" when the class has no subject).

- [ ] **Step 6: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/portals/teacher/screens/Classes.tsx web/src/portals/teacher/screens/ClassDetail.tsx web/src/portals/admin/screens/Classes.tsx
git commit -S -m "feat(web): show the subject name alongside its code on teacher/admin class screens"
```

---

## Task 15: Onboarding — per-subject qualification-level override

**Files:**
- Modify: `web/src/portals/student/screens/onboarding/onboardingData.ts:129-159` (`SubjectDraft`, `buildEnrolmentPayload`)
- Modify: `web/src/portals/student/screens/Onboarding.tsx:93-171` (seeding, `toggleSubject`, `handleSubjectsContinue`)
- Modify: `web/src/portals/student/screens/onboarding/SubjectsStep.tsx:116-146` (per-subject card)
- Test: `web/tests/unit/onboarding.test.ts`

**Interfaces:**
- Consumes: `QUALIFICATION_LEVELS` (Task 8), `EnrolmentUpsert.qualificationLevel` (Task 9).
- Produces: `SubjectDraft.qualificationLevel: string | null`; `buildEnrolmentPayload` includes it in the PUT body.

- [ ] **Step 1: Write the failing test**

In `web/tests/unit/onboarding.test.ts`, find the existing `buildEnrolmentPayload` test(s) (near "builds one entry per selected subject") and add:

```ts
it("includes each subject's own qualificationLevel in the enrolment payload", () => {
  const drafts: SubjectDraft[] = [
    {
      subjectCode: "0625",
      qualificationLevel: "igcse",
      papers: new Set([1]),
      targetGrade: null,
      sessionMonth: null,
      sessionYear: null,
    },
  ]

  const payload = buildEnrolmentPayload(drafts)

  expect(payload[0].qualificationLevel).toBe("igcse")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run web/tests/unit/onboarding.test.ts -t "includes each subject's own qualificationLevel"`
Expected: FAIL — `SubjectDraft` has no `qualificationLevel` field yet (TS type error surfaces as a build/test failure), and `payload[0].qualificationLevel` is `undefined`.

- [ ] **Step 3: Implement — `onboardingData.ts`**

Update `SubjectDraft` (line 129-135):

```ts
export interface SubjectDraft {
  subjectCode: string
  qualificationLevel: string | null
  papers: ReadonlySet<number>
  targetGrade: string | null
  sessionMonth: string | null
  sessionYear: number | null
}
```

Update `buildEnrolmentPayload` (line 151-159):

```ts
export function buildEnrolmentPayload(drafts: SubjectDraft[]): EnrolmentUpsert[] {
  return drafts.map((draft) => ({
    subjectCode: draft.subjectCode,
    qualificationLevel: draft.qualificationLevel,
    targetGrade: draft.targetGrade,
    sessionMonth: draft.sessionMonth,
    sessionYear: draft.sessionYear,
    papers: [...draft.papers].sort((a, b) => a - b),
  }))
}
```

- [ ] **Step 4: Implement — `Onboarding.tsx`**

Seed each draft's level from the existing enrolment when editing, or from the current profile-level default when the student toggles a new subject on. In the seeding effect (line 96-104):

```tsx
    for (const enrolment of existing.enrolments) {
      if (!SUPPORTED_SUBJECTS.some((s) => s.code === enrolment.subjectCode)) continue
      seededDrafts[enrolment.subjectCode] = {
        subjectCode: enrolment.subjectCode,
        qualificationLevel: enrolment.qualificationLevel,
        papers: new Set(enrolment.papers),
        targetGrade: enrolment.targetGrade,
        sessionMonth: enrolment.sessionMonth,
        sessionYear: enrolment.sessionYear,
      }
```

In `toggleSubject` (line 123-139), default a newly-added subject's level to the step's current global selector value:

```tsx
  function toggleSubject(code: string) {
    setDrafts((prev) => {
      const next = { ...prev }
      if (next[code]) {
        delete next[code]
      } else {
        next[code] = {
          subjectCode: code,
          qualificationLevel: qualificationLevel,
          papers: new Set(),
          targetGrade: null,
          sessionMonth: null,
          sessionYear: null,
        }
      }
      return next
    })
  }
```

`updateDraft` (line 149-155) already accepts `Partial<SubjectDraft>` and needs no change — `SubjectsStep`'s new per-subject control (Step 5 below) calls it with `{ qualificationLevel: value }`.

- [ ] **Step 5: Implement — `SubjectsStep.tsx`**

Add a new prop for the per-subject setter, and a small `Select` inside each expanded subject card. Update the props interface (line 49-61):

```ts
export interface SubjectsStepProps {
  qualificationLevel: string | null
  onQualificationLevel: (value: string) => void
  drafts: Record<string, SubjectDraft>
  onToggleSubject: (code: string) => void
  onSubjectQualificationLevel: (code: string, value: string) => void
  onTogglePaper: (code: string, paper: number) => void
  onTargetGrade: (code: string, grade: string | null) => void
  onSessionMonth: (code: string, month: string | null) => void
  onSessionYear: (code: string, year: number | null) => void
  onContinue: () => void
  saving: boolean
  error: string | null
}
```

Add the parameter to the function signature (line 63-75) and add the control inside the expanded card's `<div className="flex flex-wrap gap-4">` block (line 164-209), as the first control:

```tsx
export function SubjectsStep({
  qualificationLevel,
  onQualificationLevel,
  drafts,
  onToggleSubject,
  onSubjectQualificationLevel,
  onTogglePaper,
  onTargetGrade,
  onSessionMonth,
  onSessionYear,
  onContinue,
  saving,
  error,
}: SubjectsStepProps) {
```

```tsx
                  <div className="flex flex-wrap gap-4">
                    <Select
                      label="Qualification level"
                      value={draft.qualificationLevel ?? ""}
                      onChange={(event) =>
                        onSubjectQualificationLevel(subject.code, event.target.value)
                      }
                      wrapperClassName="w-44"
                    >
                      {QUALIFICATION_LEVELS.map((level) => (
                        <option key={level.value} value={level.value}>
                          {level.label}
                        </option>
                      ))}
                    </Select>

                    <Select
                      label="Target grade"
                      value={draft.targetGrade ?? ""}
                      onChange={(event) => onTargetGrade(subject.code, event.target.value || null)}
                      wrapperClassName="w-44"
                    >
```

(Leave the existing "Target grade"/"Target session"/"Year" controls exactly as they are — the new Select is inserted immediately before them, and `QUALIFICATION_LEVELS` is already imported at the top of this file.)

In `Onboarding.tsx`, wire the new prop where `SubjectsStep` is rendered (near line 272-275):

```tsx
          qualificationLevel={qualificationLevel}
          onQualificationLevel={setQualificationLevel}
          drafts={drafts}
          onToggleSubject={toggleSubject}
          onSubjectQualificationLevel={(code, value) => updateDraft(code, { qualificationLevel: value })}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run web/tests/unit/onboarding.test.ts`
Expected: PASS — including every pre-existing test in this file (confirms the new required `qualificationLevel` field on `SubjectDraft` didn't silently break another test's inline draft objects; if it did, add `qualificationLevel: null` to those fixtures).

- [ ] **Step 7: Type-check**

Run: `cd web && npm run typecheck`
Expected: clean.

- [ ] **Step 8: Manual verification**

Run the dev server, start onboarding as a fresh student, pick a global qualification level, select a subject (confirm its per-subject level defaults to the global one), change it, and continue. Confirm no console errors and the subject card's level control is visible and functional.

- [ ] **Step 9: Run pre-commit**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add web/src/portals/student/screens/onboarding/onboardingData.ts web/src/portals/student/screens/Onboarding.tsx web/src/portals/student/screens/onboarding/SubjectsStep.tsx web/tests/unit/onboarding.test.ts
git commit -S -m "feat(web): let a student override qualification level per subject during onboarding"
```

---

## Task 16: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest`
Expected: PASS (Postgres-dependent tests skip cleanly if no local Postgres; run again with Postgres available before merging).

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd web && npx vitest run && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 3: Run pre-commit across the whole tree**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 4: Confirm no leftover `title`/`meta` references**

Run: `grep -rn "subjectHeader.title\|subjectHeader.meta\|header\[.title.\]\|header\[.meta.\]" web/src lemely 2>/dev/null`
Expected: no output — every consumer of the old `SubjectHeaderDTO` shape was updated in Tasks 4 and 11.

No commit for this task — it's a verification checkpoint before the branch is considered done. If anything fails, fix it within the task whose files it touches and re-run this checklist.
