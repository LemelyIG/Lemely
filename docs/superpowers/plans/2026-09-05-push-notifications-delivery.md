# Push notifications: finishing delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the already-built web-push stack actually deliver: defer notification of scheduled announcements to their publish moment, send the two engagement notifications daily in each recipient's own time zone, run those three jobs from a background sweeper inside the API process, make VAPID keys configurable and documented, give teachers and parents an inbox, and remove the copy that says none of this exists.

**Architecture:** Per-user zones land first (`users.timezone`, `resolve_zone`, `UserZoneReader`) because the two daily jobs and quiet hours depend on them. Announcement deferral adds `announcements.notified_at` and moves the fan-out into a new `lemely/web/scheduled_notifications.py` module that both the router and the sweeper call. A `[notifications]` settings section and per-zone helpers are shared infrastructure for the two daily jobs; the sweeper (`lifespan` on `create_app`) is wired last, once all three jobs exist. VAPID keys, the two inbox screens and the copy cleanup are independent of the above and of each other. Idempotency everywhere is migration 0018's partial unique index on `(user_id, type, dedupe_key)`; nothing here adds a bookkeeping table.

**Tech Stack:** FastAPI + pydantic-settings + SQLAlchemy 2 + Alembic + structlog + click (backend), pytest against a throwaway Postgres; React 19 + TypeScript + Tailwind + react-router-dom + @tanstack/react-query (frontend), vitest (node environment, no DOM) and Playwright.

Spec: `docs/superpowers/specs/2026-09-05-push-notifications-delivery-design.md`

## Global Constraints

- Branch is `feat/push-notification-delivery`, already checked out. All work lands here; one PR into `develop`. Do not create another branch, do not push, and do not create a commit without asking first — every "Commit" step below is the point at which to ask.
- Every commit is signed: `git commit -S`. Conventional messages with scopes: `feat(db):`, `feat(web):`, `feat(notifications):`, `feat(cli):`, `test(notifications):`, `docs(push):`, `fix(web):`.
- Run `source .venv/bin/activate && pre-commit run --all-files` and fix every failure before each commit.
- Backend commands run from the repo root inside the venv. Frontend commands run from `web/`: `npx vitest run`, `npm run typecheck`, `npm run lint`, `npm run check:copy`, `npx playwright test`. If `npx vitest` reports `Cannot find package 'vitest'`, run `PUPPETEER_SKIP_DOWNLOAD=1 npm install --no-audit --no-fund` from `web/` first.
- Postgres-backed tests skip themselves when the local Supabase Postgres (`127.0.0.1:54322`) is unreachable. Start it with `make db-up` before running them; a skipped test is not a passing test.
- The web unit runner is `environment: "node"` with **no jsdom** and collects only `tests/unit/**/*.test.ts`. React components cannot be rendered in a unit test. Every rule worth pinning lives in a `.ts` module outside the component; screens are exercised by Playwright.
- UI copy must contain no em-dash (`—`) and no en-dash (`–`); `npm run check:copy` enforces this on string literals under `web/src`. A middle dot (`·`) is fine and is what the existing UI uses.
- Alembic revision ids stay at or under 32 characters (`alembic_version.version_num` is `varchar(32)`). The current head is `0028_user_avatar_path` (not 0021 as the spec's cross-references might suggest); new revisions are `0029_user_timezone` and `0030_announcement_notified_at`.
- `lemely.toml.example` is generated. After any change to `lemely/runtime/example_toml.py`, run `python -m lemely.runtime.example_toml` from the repo root; `tests/test_settings_example_drift.py` fails otherwise.
- `tests/test_authz_matrix_complete.py::test_every_route_is_declared` fails for any new API route not listed in its matrix. Task 3 adds the one new route.
- Migration docstrings are history and are not rewritten. Migration 0018's docstring says `study_plan_reminder` has no natural key; the spec corrects that claim in `NotificationService.create`'s docstring (Task 8), not in the migration.
- Copy the spec's notification strings verbatim: title `Nothing logged today`; bodies `A freeze will cover today. Your {n}-day streak stays.` and `Your {n}-day streak ends if today stays empty.`; title `Today's study session`; body `{topic} · {duration} min`. No exclamation marks, no second sentence.
- Settings values copied from the spec: `sweeper_enabled = true`, `sweep_poll_seconds = 60`, `streak_warning_hour = 19`, `study_plan_reminder_hour = 8`. `timezone` is `VARCHAR(64) NULL`; `timezone_is_explicit` is `BOOLEAN NOT NULL DEFAULT false`; `notified_at` is `TIMESTAMPTZ NULL` with a partial index over `(publish_at) WHERE notified_at IS NULL`.

## Task order and why

| # | Task | Depends on |
|---|---|---|
| 1 | Zone columns, `resolve_zone`, `UserZoneReader` | nothing |
| 2 | Services read the user's zone (XP, quiet hours, at-risk); leaderboard stays global | 1 |
| 3 | `PUT /me/timezone` and the profile fields | 1 |
| 4 | Frontend: device-zone sync at boot and the picker | 3 |
| 5 | Announcement deferral: `notified_at`, shared fan-out, `publish_due_announcements` | nothing |
| 6 | `[notifications]` settings and the per-zone bucket helpers | 1 |
| 7 | `warn_streaks` | 6 |
| 8 | `remind_study_plans` | 6 |
| 9 | The sweeper and `create_app` lifespan; `docs/deployment.md` | 5, 7, 8 |
| 10 | VAPID keys: `lemely push-keygen`, doctor check, config, deploy, docs | nothing |
| 11 | Push destinations in the client bridge; the student inbox stays consistent with it | nothing |
| 12 | Teacher inbox | 11 |
| 13 | Parent inbox | 11 |
| 14 | Playwright for the two inboxes | 12, 13 |
| 15 | Copy cleanup; CHANGELOG and DELIVERY appendix | nothing |

Tasks 10, 11 to 14, and 15 can be done in any order relative to 1 to 9.

## Documented invariants and comments this plan corrects

Each of these is an edit with a stated reason, not incidental cleanup. The task that makes it is named.

| Where | What it says today | Why it changes | Task |
|---|---|---|---|
| `lemely/db/notification_repo.py:295-301` (`NotificationService.create` docstring) | `study_plan_reminder` is the example of a type with *no* natural idempotency key | Under §2 it keys on the session id and `streak_warning` keys on the recipient's civil date | 8 |
| `lemely/db/xp_repo.py:16-23` (module docstring rule 2) | "A streak-day is a civil date in `Africa/Cairo`, never UTC" and "per-user timezones are a later wiring change" | The wiring change is this one | 2 |
| `lemely/db/xp_repo.py:38-43` (rule 5) | "There is no scheduler in this build" | A sweeper exists after Task 9; streaks still resolve lazily, which is the part that stays true | 7 |
| `lemely/db/xp_repo.py:505-509` (`XpService.profile` docstring) | one `today` for every window | The week window is global and the streak/calendar are per-user (§3, "the seam this creates") | 2 |
| `lemely/db/leaderboard_repo.py` (`board`, line 366) | nothing says why the zone is the global one | §3 requires a comment so it does not look like an oversight | 2 |
| `lemely/web/routers/student.py:823-829` (`_alert_teachers_and_parents` docstring) | rule 3 "joins `streak_warning` and `study_plan_reminder` in D5.9 §5's no-scheduler limitation" | Both are now scheduled; rule 3 alone is still not | 9 |
| `lemely/web/routers/student.py:831-836` (same docstring) | "The dedupe key is `(student, reason, Cairo civil date)`" | It is now the assessed student's own civil date | 2 |
| `lemely/db/announcement_repo.py:426-433` (`student_recipients` docstring) | "with no scheduler in this build, a scheduled announcement is never notified about at all" | The sweeper notifies it at `publish_at` | 5 |
| `lemely/web/routers/announcements.py:14-21` (module docstring) | describes the create-time fan-out only | Fan-out is now shared with the sweeper and future-dated rows are deferred | 5 |
| `web/src/lib/push/pushDecision.ts:56-65` (`DEFAULT_PUSH_URL` comment) | "neither portal has an inbox screen in this build" | Both do after Tasks 12 and 13; `/` stays the fallback for the stated reason | 11 |
| `web/src/lib/push/pushClientBridge.ts:30-47` (`destinationFor` comment) | "The three time-triggered types have no screen at all" and "neither of whom has an inbox screen" | Four of the five types now route | 11 |
| `web/src/portals/student/screens/Notifications.tsx:56-75` (`destinationFor` comment) | "Kept deliberately consistent with `pushClientBridge.destinationFor`" and "the three remaining types have no screen" | That consistency is a stated invariant; the bridge gains destinations, so the student inbox gains the same two | 11 |
| `web/src/portals/teacher/screens/Announcements.tsx:49-67, 195-203` (named by the spec) and `:347-350, 375-376, 396-399` (the same claims restated further down the file) | students cannot see announcements; no notification is sent; `publishAt` never read and "nothing will fire"; "no student-facing surface exists" | All false since P5.5 and this change | 15 |
| `web/src/lib/teacherTypes.ts:37-38, 1074-1075` | announcement endpoints "remain a later chunk's to add"; `publishAt` "stored but never read ... never imply it will fire" | `publishAt` now gates visibility and schedules the notification | 15 |
| `docs/deployment.md:404-410` (§5.2 "There is no scheduler") | nothing invokes the two engagement notifications | The sweeper does; the Cloud Run min-instances caveat replaces the section | 9 |

Two adaptations the executor should know about up front, both flagged for the lead in the plan's closing notes:

- The spec's `PUT /me/timezone` body is `{ timezone: str, explicit: bool }`, and separately says a non-explicit write never overwrites an explicit choice while "follow this device" must clear that choice. Both cannot be true with the same body shape, so `timezone` is `str | null`: `{timezone: null, explicit: false}` is the clear, `{timezone: "<zone>", explicit: false}` is the auto-detect write the server ignores while the flag is set, and `{timezone: "<zone>", explicit: true}` is the picker.
- `UserZoneReader` is injected into two process-wide singleton services, so its memo cannot be "one request" without a per-request container the codebase does not have. Its memo lives as long as the process and is invalidated by `PUT /me/timezone` through `forget(user_id)`. `docs/deployment.md` §5.1 already limits the backend to one replica, which is what makes that sound.

---

### Task 1: Zone columns, `resolve_zone`, `UserZoneReader`

**Files:**
- Create: `lemely/db/migrations/versions/0029_user_timezone.py`
- Modify: `lemely/db/models/users.py:76-81` (add two columns after `avatar_path`)
- Modify: `lemely/db/xp_repo.py:112-127` (add `resolve_zone` beside `civil_date_in_zone`), `:632-640` (add `UserZoneReader` before `_as_uuid`), `:642-659` (`__all__`)
- Test: `tests/test_user_zones.py` (new)

**Interfaces:**
- Consumes: `DEFAULT_ZONE`, `civil_date_in_zone` (existing).
- Produces: `User.timezone: str | None`, `User.timezone_is_explicit: bool`; `resolve_zone(name: str | None) -> ZoneInfo`; `class UserZoneReader` with `__init__(self, sessionmaker: sessionmaker[Session])`, `zone_for(self, user_id: uuid.UUID | str) -> ZoneInfo`, `forget(self, user_id: uuid.UUID | str) -> None`, `clear(self) -> None`. Both are exported from `lemely.db.xp_repo`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_user_zones.py`:

```python
"""Per-user civil-time zones (spec §3): ``resolve_zone`` and ``UserZoneReader``.

A stored zone that tzdata later retires must never be able to fail a student's
XP award, so resolution falls back to the launch zone and never raises.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, UserZoneReader, resolve_zone
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

CAIRO = ZoneInfo("Africa/Cairo")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(
    sm: sessionmaker[Session],
    *,
    role: Role = Role.student,
    timezone: str | None = None,
    explicit: bool = False,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                timezone=timezone,
                timezone_is_explicit=explicit,
            )
        )
    return uid


# -- resolve_zone -----------------------------------------------------------


@pytest.mark.parametrize("name", [None, "", "   "])
def test_resolve_zone_falls_back_to_the_launch_zone_for_unset(name: str | None) -> None:
    assert resolve_zone(name) is DEFAULT_ZONE


@pytest.mark.parametrize("name", ["Not/AZone", "../etc/passwd", "Africa/Cairo/../Nope"])
def test_resolve_zone_never_raises_for_an_unresolvable_name(name: str) -> None:
    """A retired or corrupt stored name is wrong by an hour or two if it falls
    back; raising would be wrong by the whole feature."""
    assert resolve_zone(name) is DEFAULT_ZONE


def test_resolve_zone_resolves_a_real_name() -> None:
    assert resolve_zone("America/Los_Angeles").key == "America/Los_Angeles"


# -- UserZoneReader ---------------------------------------------------------


def test_reader_returns_the_stored_zone(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    assert UserZoneReader(pg_sessionmaker).zone_for(uid).key == "America/Los_Angeles"


def test_reader_returns_the_launch_zone_for_a_null_column(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """NULL means never set, so the migration is a no-op for every existing row."""
    uid = _seed_user(pg_sessionmaker)
    assert UserZoneReader(pg_sessionmaker).zone_for(uid) is DEFAULT_ZONE


def test_reader_returns_the_launch_zone_for_an_unknown_user(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    assert UserZoneReader(pg_sessionmaker).zone_for(uuid.uuid4()) is DEFAULT_ZONE


def test_reader_memoises_until_told_to_forget(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    reader = UserZoneReader(pg_sessionmaker)
    assert reader.zone_for(uid).key == "America/Los_Angeles"

    with pg_sessionmaker.begin() as session:
        session.execute(sa.update(User).where(User.id == uid).values(timezone="Africa/Cairo"))

    # Still the memoised answer: the reader has not been told the row changed.
    assert reader.zone_for(uid).key == "America/Los_Angeles"
    reader.forget(uid)
    assert reader.zone_for(uid).key == "Africa/Cairo"


def test_reader_accepts_a_string_id(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="Asia/Tokyo")
    assert UserZoneReader(pg_sessionmaker).zone_for(str(uid)).key == "Asia/Tokyo"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_user_zones.py -v
```

Expected: FAIL at import with `ImportError: cannot import name 'UserZoneReader'`.

- [ ] **Step 3: Write the migration**

Create `lemely/db/migrations/versions/0029_user_timezone.py`:

```python
"""Add ``users.timezone`` and ``users.timezone_is_explicit`` (per-user civil time, spec §3).

Additive. ``timezone`` is ``NULL`` for every existing row and ``NULL`` resolves
to the launch zone (``lemely.db.xp_repo.DEFAULT_ZONE``), so this migration
changes nobody's behaviour on deploy. ``timezone_is_explicit`` records that the
*user* chose the zone, which is what stops the client's auto-detect overwriting
a deliberate choice. No backfill: nothing knows where an existing user is.

Revision ID: 0029_user_timezone
Revises: 0028_user_avatar_path
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0029_user_timezone"
down_revision: str | Sequence[str] | None = "0028_user_avatar_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "timezone_is_explicit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "timezone_is_explicit")
    op.drop_column("users", "timezone")
```

- [ ] **Step 4: Add the columns to the model**

In `lemely/db/models/users.py`, immediately after the `avatar_path` block (which ends at line 81 with the closing `"""`), add:

```python
    timezone: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """Migration ``0029`` (push-delivery spec §3). An IANA zone name
    (``America/Los_Angeles``) that every *personal* civil-date and civil-time
    calculation for this user runs in: quiet hours, streak days, the XP daily
    cap, and the two daily engagement notifications. ``None`` means never set
    and resolves to :data:`~lemely.db.xp_repo.DEFAULT_ZONE` through
    :func:`~lemely.db.xp_repo.resolve_zone`. Shared facts (the leaderboard
    week, the profile week window) deliberately do not read this column."""

    timezone_is_explicit: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    """Migration ``0029``. ``True`` when the user chose ``timezone`` in
    settings. The client sends its device zone at every app boot, and the
    server stores that only while this is ``False``, so opening the app on a
    plane never silently undoes a deliberate choice."""
```

- [ ] **Step 5: Add `resolve_zone` and `UserZoneReader`**

In `lemely/db/xp_repo.py`, add to the imports (after line 57, `from zoneinfo import ZoneInfo`):

```python
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
```

(keep the existing `from zoneinfo import ZoneInfo` line replaced by the one above), and after `from lemely.db.models.users import User` (line 64) leave the `TYPE_CHECKING` block as is. Add a module logger after the `TYPE_CHECKING` block (after line 69):

```python
log = structlog.get_logger(__name__)
```

Immediately after `civil_date_in_zone` (after line 127), add:

```python
def resolve_zone(name: str | None) -> ZoneInfo:
    """Turn a stored ``users.timezone`` into a :class:`ZoneInfo`. Never raises.

    ``None`` and blank mean never set and resolve to :data:`DEFAULT_ZONE`. A
    name ``ZoneInfo`` cannot resolve — a tzdata drop that retired it, a corrupt
    value, a path-shaped string — also resolves to :data:`DEFAULT_ZONE`, with a
    warning. Falling back is wrong by an hour or two; raising here would let a
    stored zone fail a student's XP award, which is wrong by the whole feature.
    """
    if name is None or not name.strip():
        return DEFAULT_ZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        log.warning("timezone_unresolvable", timezone=name, fallback=DEFAULT_ZONE.key)
        return DEFAULT_ZONE
```

Immediately before `_as_uuid` (before line 632), add:

```python
class UserZoneReader:
    """Resolve the civil-time zone a user lives in, from ``users.timezone``.

    Injected into :class:`XpService` and
    :class:`~lemely.db.notification_repo.NotificationService`, which keep their
    ``zone`` constructor argument as the fallback this reader defers to — so
    every existing test that pins a zone keeps working with no reader at all.

    **The memo lives as long as this object, and this object lives as long as
    the process** (``lemely.web.deps`` wires one singleton into both services).
    ``PUT /api/me/timezone`` calls :meth:`forget` after every write, which is
    what keeps a changed zone from being served stale; with the backend pinned
    to one replica (``docs/deployment.md`` §5.1) that is the only writer there
    is. A second replica would serve the old zone until its next restart,
    bounded to one civil day of drift, and is recorded here rather than solved.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Bind the reader to a session factory."""
        self._sessionmaker = sessionmaker
        self._memo: dict[uuid.UUID, ZoneInfo] = {}

    def zone_for(self, user_id: uuid.UUID | str) -> ZoneInfo:
        """The zone for ``user_id``: the stored one, else :data:`DEFAULT_ZONE`.

        An unknown user id also resolves to the default rather than raising:
        the callers are award and notify paths that must never fail on a
        lookup that is only there to pick a calendar.
        """
        key = _as_uuid(user_id)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        with self._sessionmaker() as session:
            name = session.scalar(select(User.timezone).where(User.id == key))
        zone = resolve_zone(name)
        self._memo[key] = zone
        return zone

    def forget(self, user_id: uuid.UUID | str) -> None:
        """Drop the memoised zone for one user, after their row changed."""
        self._memo.pop(_as_uuid(user_id), None)

    def clear(self) -> None:
        """Drop every memoised zone. Tests, and ``deps.reset_singletons``."""
        self._memo.clear()
```

Add `"UserZoneReader"` (alphabetically, after `"StreakState"`) and `"resolve_zone"` (after `"civil_date_in_zone"`) to `__all__`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_user_zones.py tests/test_xp_repo.py tests/test_db_schema.py -v
```

Expected: PASS. `test_db_schema.py::test_every_model_has_timestamps` and the naming-convention test are unaffected because the new columns are plain columns on an existing model.

- [ ] **Step 7: Apply the migration against the local database**

```bash
make db-migrate
```

Expected: `alembic upgrade head` reports `0028_user_avatar_path -> 0029_user_timezone`. Then confirm the downgrade path works and re-apply:

```bash
alembic -c lemely/db/migrations/alembic.ini downgrade 0028_user_avatar_path && make db-migrate
```

If the `alembic.ini` lives elsewhere, use whatever `make db-downgrade` runs (`grep -n db-downgrade -A 3 Makefile`).

- [ ] **Step 8: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/migrations/versions/0029_user_timezone.py lemely/db/models/users.py lemely/db/xp_repo.py tests/test_user_zones.py
git commit -S -m "feat(db): per-user timezone columns and a zone reader that never raises

users.timezone and users.timezone_is_explicit (migration 0029), resolve_zone
beside civil_date_in_zone, and UserZoneReader. NULL resolves to the launch
zone so the deploy changes nobody's behaviour; an unresolvable stored name
also falls back, with a warning, because a retired tzdata entry must not be
able to fail an XP award."
```

---

### Task 2: Services read the user's zone; shared facts stay global

**Files:**
- Modify: `lemely/db/xp_repo.py:9-23` (rule 2 of the module docstring), `:239-258` (`XpService.__init__`), `:313-317` (`award`), `:480-482` (`streak`), `:498-537` (`profile`)
- Modify: `lemely/db/notification_repo.py:254-278` (`NotificationService.__init__`), `:306-308` and `:347-351` (`create`)
- Modify: `lemely/db/leaderboard_repo.py:299-317` (class docstring), `:365-367` (`board`)
- Modify: `lemely/web/routers/student.py:806-880` (`_alert_teachers_and_parents`), `:883-903` (`student_correct` signature and its call)
- Modify: `lemely/web/deps.py:533-547` (`get_xp_service`), `:624-639` (`get_notification_service`), `:994-1044` (`reset_singletons`); add `get_user_zone_reader`
- Modify: `tests/test_web_notify_seams.py:310-341` (`correct_client` fixture)
- Test: `tests/test_user_zones.py` (extend)

**Interfaces:**
- Consumes: `UserZoneReader`, `resolve_zone` (Task 1).
- Produces: `XpService.__init__(sessionmaker, *, now=..., zone=DEFAULT_ZONE, zones: UserZoneReader | None = None)`; `NotificationService.__init__(sessionmaker, preferences, *, now=..., zone=DEFAULT_ZONE, zones: UserZoneReader | None = None)`; `deps.get_user_zone_reader() -> UserZoneReader`; `_alert_teachers_and_parents(..., zones: UserZoneReader, student_id: str)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_zones.py`:

```python
# -- The services read the user's zone --------------------------------------

from datetime import UTC, date, datetime, time  # noqa: E402

from lemely.db.leaderboard_repo import LeaderboardScope, LeaderboardService  # noqa: E402
from lemely.db.models.enums import NotificationType, XpSource  # noqa: E402
from lemely.db.notification_prefs_repo import NotificationPreferencesService  # noqa: E402
from lemely.db.notification_repo import NotificationService  # noqa: E402
from lemely.db.xp_repo import XpService  # noqa: E402

#: 2026-09-05 22:30Z is 01:30 on the 6th in Cairo (UTC+3) and 15:30 on the 5th
#: in Los Angeles (UTC-7): one instant, two civil dates.
SPLIT_DATE_INSTANT = datetime(2026, 9, 5, 22, 30, tzinfo=UTC)


def _xp(sm: sessionmaker[Session]) -> XpService:
    return XpService(sm, now=lambda: SPLIT_DATE_INSTANT, zones=UserZoneReader(sm))


def test_awarded_on_is_the_students_own_civil_date(pg_sessionmaker: sessionmaker[Session]) -> None:
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = _xp(pg_sessionmaker)

    assert xp.award(cairo, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 6)
    assert xp.award(la, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 5)


def test_a_student_with_no_zone_keeps_the_launch_zone(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker)
    assert _xp(pg_sessionmaker).award(student, XpSource.quiz_completed, "q1").awarded_on == date(
        2026, 9, 6
    )


def test_a_pinned_zone_without_a_reader_still_wins(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Every existing test constructs the service with ``zone=`` and no reader."""
    student = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = XpService(pg_sessionmaker, now=lambda: SPLIT_DATE_INSTANT, zone=CAIRO)
    assert xp.award(student, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 6)


def test_history_is_not_rewritten_when_a_zone_changes(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A zone applies forward only (spec §3): rows already stored keep the date
    they were computed with."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    xp = _xp(pg_sessionmaker)
    xp.award(student, XpSource.quiz_completed, "q1")

    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(User).where(User.id == student).values(timezone="America/Los_Angeles")
        )

    by_day = xp.xp_by_day(student, start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert by_day == {date(2026, 9, 6): 30}


def test_quiet_hours_are_evaluated_in_the_recipients_zone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """05:30Z is 22:30 in Los Angeles (inside 22:00-07:00) and 08:30 in Cairo."""
    moment = datetime(2026, 9, 5, 5, 30, tzinfo=UTC)
    prefs = NotificationPreferencesService(pg_sessionmaker)
    service = NotificationService(
        pg_sessionmaker,
        prefs,
        now=lambda: moment,
        zone=CAIRO,
        zones=UserZoneReader(pg_sessionmaker),
    )
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    for uid in (la, cairo):
        prefs.set(uid, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0))

    asleep = service.create(la, NotificationType.announcement, "Test", dedupe_key="a")
    awake = service.create(cairo, NotificationType.announcement, "Test", dedupe_key="a")

    assert asleep.row is not None and asleep.push_allowed is False
    assert asleep.push_suppressed_reason == "quiet_hours"
    assert awake.row is not None and awake.push_allowed is True


def test_the_leaderboard_week_is_the_same_for_every_zone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The regression test for the invariant §3 refuses to break: a shared
    ranking summed over two different weeks would mean nothing. 2026-09-06
    22:30Z is Monday the 7th in Cairo and still Sunday the 6th in Los Angeles;
    both boards use the global week regardless."""
    moment = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    board = LeaderboardService(pg_sessionmaker, now=lambda: moment)

    cairo_result = board.board(cairo, LeaderboardScope.global_)
    la_result = board.board(la, LeaderboardScope.global_)

    assert cairo_result.week_start == la_result.week_start == date(2026, 9, 7)
    assert cairo_result.week_end == la_result.week_end == date(2026, 9, 13)


def test_profile_uses_the_students_day_for_the_streak_and_the_global_week(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The seam §3 states plainly: near midnight, far from Cairo, the calendar
    ends on the student's own date while the week window is the shared one."""
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = _xp(pg_sessionmaker)

    profile = xp.profile(la)

    assert profile.calendar_end == date(2026, 9, 5)
    assert profile.week_start == date(2026, 8, 31)  # Monday of the Cairo week containing the 6th
    assert profile.week_end == date(2026, 9, 6)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_user_zones.py -v
```

Expected: the seven new tests FAIL with `TypeError: XpService.__init__() got an unexpected keyword argument 'zones'` (and the same for `NotificationService`).

- [ ] **Step 3: Wire the reader into `XpService`**

In `lemely/db/xp_repo.py`:

Replace rule 2 of the module docstring (lines 16-23) with:

```
2. **A streak-day is a civil date in the student's own zone, never UTC**
   (D5.1 §4, per-user since the push-delivery spec §3). Every conversion
   from an aware ``datetime`` to a streak-day goes through
   :func:`civil_date_in_zone`; the zone comes from :class:`UserZoneReader`
   when one is injected and from the ``zone`` constructor argument otherwise
   (:data:`DEFAULT_ZONE`, the launch default). Nothing computes a streak
   date inline, and nothing ever hardcodes a ``+02:00`` offset (Egypt's DST
   history is not constant).
```

Replace `XpService.__init__` (lines 248-258) with:

```python
    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
        zone: ZoneInfo = DEFAULT_ZONE,
        zones: UserZoneReader | None = None,
    ) -> None:
        """Wire the service to a session factory, a clock, and the streak-day zone.

        ``zones`` resolves each student's own zone; ``zone`` is the fallback it
        defers to and the only zone in use when no reader is given (every
        pre-existing test). The week window is always ``zone`` — see
        :meth:`profile`.
        """
        self._sessionmaker = sessionmaker
        self._now = now
        self._zone = zone
        self._zones = zones

    def _zone_for(self, user_id: uuid.UUID) -> ZoneInfo:
        """The zone this user's personal civil dates are computed in."""
        if self._zones is None:
            return self._zone
        return self._zones.zone_for(user_id)
```

In `award`, replace line 317:

```python
        awarded_on = civil_date_in_zone(moment, zone=self._zone)
```

with:

```python
        awarded_on = civil_date_in_zone(moment, zone=self._zone_for(student_uuid))
```

In `streak`, replace line 482:

```python
        today = civil_date_in_zone(moment, zone=self._zone)
```

with:

```python
        today = civil_date_in_zone(moment, zone=self._zone_for(student_uuid))
```

Replace `profile`'s docstring first paragraph (lines 505-509) with:

```
        S-31's whole read: total, streak, this week by source, and the calendar.

        Resolves ``today`` **once per zone** and passes it to every window.
        The streak and the calendar use the student's own civil date; the week
        window uses the global one, because :func:`week_bounds` is the single
        definition of "this week" the leaderboard also reads (D5.13 §2) and a
        student must not see a different week here than on the board. For a
        student far from the launch zone, near midnight, the week window can be
        off by one day relative to their own date. That is the accepted cost of
        one shared week (push-delivery spec §3); it is bounded at a day and
        self-corrects within hours.
```

And replace the body lines 524-527:

```python
        moment = now if now is not None else self._now()
        today = civil_date_in_zone(moment, zone=self._zone)
        week_start, week_end = week_bounds(today)
        calendar_start = today - timedelta(days=calendar_days - 1)
```

with:

```python
        moment = now if now is not None else self._now()
        student_uuid = _as_uuid(user_id)
        today = civil_date_in_zone(moment, zone=self._zone_for(student_uuid))
        # Deliberately the global zone, never the student's: see the docstring.
        week_start, week_end = week_bounds(civil_date_in_zone(moment, zone=self._zone))
        calendar_start = today - timedelta(days=calendar_days - 1)
```

- [ ] **Step 4: Wire the reader into `NotificationService`**

In `lemely/db/notification_repo.py`, change the import on line 53 to:

```python
from lemely.db.xp_repo import DEFAULT_ZONE, UserZoneReader
```

Replace `__init__` (lines 266-278) with:

```python
    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        preferences: NotificationPreferencesService,
        *,
        now: Callable[[], datetime] = _utcnow,
        zone: ZoneInfo = DEFAULT_ZONE,
        zones: UserZoneReader | None = None,
    ) -> None:
        """Wire the service to a session factory, the preference gate, a clock, and a zone.

        ``zones`` resolves the recipient's own zone for quiet hours — whose
        night it is, is a personal fact (push-delivery spec §3). ``zone`` is
        the fallback it defers to, and the only zone in use when no reader is
        given.
        """
        self._sessionmaker = sessionmaker
        self._preferences = preferences
        self._now = now
        self._zone = zone
        self._zones = zones
```

In `create`, replace lines 347-351:

```python
        quiet = is_within_quiet_hours(
            civil_time_in_zone(moment, zone=self._zone),
            prefs.quiet_hours_start,
            prefs.quiet_hours_end,
        )
```

with:

```python
        zone = self._zone if self._zones is None else self._zones.zone_for(recipient)
        quiet = is_within_quiet_hours(
            civil_time_in_zone(moment, zone=zone),
            prefs.quiet_hours_start,
            prefs.quiet_hours_end,
        )
```

- [ ] **Step 5: Say why the leaderboard stays global**

In `lemely/db/leaderboard_repo.py`, replace the class docstring (lines 300-305) with:

```python
    """Rank students by weekly XP against ``xp_events`` (D5.1).

    Constructed with a ``sessionmaker``, an injectable clock, and the
    civil-date zone the weekly window is derived in — mirrors
    :class:`~lemely.db.xp_repo.XpService`'s shape, **minus** that service's
    per-user zone reader. A leaderboard is a shared artifact: summing two
    students' XP over two different weeks would make the ranking mean
    nothing, so the week here is one global week for everyone
    (push-delivery spec §3), and this class takes no ``UserZoneReader`` on
    purpose.
    """
```

And immediately above line 366 (`today = civil_date_in_zone(moment, zone=self._zone)`) add:

```python
        # The global zone, deliberately. Per-user zones (spec §3) move every
        # *personal* civil date to the student's own calendar; a shared ranking
        # has to sum every student over the same week, so this stays on
        # DEFAULT_ZONE. ``tests/test_user_zones.py`` pins it.
```

- [ ] **Step 6: The at-risk `today` is the assessed student's**

In `lemely/web/routers/student.py`:

Add `UserZoneReader` to the import from `lemely.db.xp_repo` (find the existing line with `grep -n "from lemely.db.xp_repo import" lemely/web/routers/student.py` and add the name alphabetically; keep `civil_date_in_zone`; `DEFAULT_ZONE` can be removed from that import if this was its only use — check with `grep -n DEFAULT_ZONE lemely/web/routers/student.py`). Add `get_user_zone_reader` to the `from lemely.web.deps import (...)` block.

Replace the signature of `_alert_teachers_and_parents` (lines 806-815) with:

```python
def _alert_teachers_and_parents(
    notification_service: NotificationService,
    push_transport: NotificationTransport,
    *,
    history_store: HistoryStoreProtocol,
    profile_service: StudentProfileService,
    class_service: ClassService,
    parent_service: ParentLinkService,
    zones: UserZoneReader,
    student_id: str,
) -> None:
```

Replace the dedupe-key paragraph of its docstring (lines 831-836) with:

```
    The dedupe key is ``(student, reason, the student's own civil date)``
    (D5.11 §3, per-user since the push-delivery spec §3): at-risk is a state,
    not an event, so an upload-keyed alert would send a teacher of thirty
    students one notification per upload. The day boundary is
    :func:`~lemely.db.xp_repo.civil_date_in_zone` in the *assessed student's*
    zone — it windows that student's own work — never the recipient's and
    never a hardcoded offset.
```

Replace line 860:

```python
        today = civil_date_in_zone(datetime.now(UTC), zone=DEFAULT_ZONE)
```

with:

```python
        today = civil_date_in_zone(datetime.now(UTC), zone=zones.zone_for(student_id))
```

In `student_correct`'s signature, after the `parent_service` parameter (line 903), add:

```python
    zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)],
```

and find the call to `_alert_teachers_and_parents(` inside `run()` (`grep -n "_alert_teachers_and_parents(" lemely/web/routers/student.py`) and add `zones=zones,` beside `parent_service=parent_service,`.

If ruff's TC001 complains that `UserZoneReader` is only used in annotations, add `# noqa: TC001 - FastAPI resolves this at runtime` to the import line, matching the pattern at the top of `lemely/web/routers/announcements.py:53-60`.

- [ ] **Step 7: Wire the dependency**

In `lemely/web/deps.py`, change the import on line 65 to:

```python
from lemely.db.xp_repo import UserZoneReader, XpService
```

Add, immediately before `get_xp_service` (before line 533):

```python
@lru_cache(maxsize=1)
def get_user_zone_reader() -> UserZoneReader:
    """Return the process-wide :class:`UserZoneReader` singleton (push-delivery spec §3).

    One reader, shared by :func:`get_xp_service`, :func:`get_notification_service`
    and the at-risk seam, so every personal civil-date calculation in one
    process resolves a user's zone the same way and ``PUT /api/me/timezone``
    has exactly one memo to invalidate. Tests override this with a reader
    bound to a throwaway Postgres database.
    """
    return UserZoneReader(get_sessionmaker(get_settings()))
```

Replace the body of `get_xp_service` (line 547) with:

```python
    return XpService(get_sessionmaker(get_settings()), zones=get_user_zone_reader())
```

and its docstring sentence "the clock and streak-day zone are left at their defaults (real UTC now, ``Africa/Cairo``)" with "the clock is left at its default (real UTC now) and streak days are computed in each student's own zone through :func:`get_user_zone_reader`, falling back to ``Africa/Cairo``".

Replace the body of `get_notification_service` (lines 636-639) with:

```python
    return NotificationService(
        get_sessionmaker(get_settings()),
        get_notification_prefs_service(),
        zones=get_user_zone_reader(),
    )
```

and its docstring sentence "The clock and quiet-hours zone are left at their defaults (real UTC now, ``Africa/Cairo``)" with "The clock is left at its default (real UTC now) and quiet hours are evaluated in the recipient's own zone through :func:`get_user_zone_reader`, falling back to ``Africa/Cairo``".

In `reset_singletons`, after `get_xp_service.cache_clear()` (line 1020) add:

```python
    get_user_zone_reader.cache_clear()
```

- [ ] **Step 8: Keep the correction seam tests offline**

In `tests/test_web_notify_seams.py`, add `get_user_zone_reader` to the `from lemely.web.deps import (...)` block and `UserZoneReader` to the `from lemely.db.xp_repo import ...` line (create that import if absent). In the `correct_client` fixture, after the `get_user_mirror` override (line 339), add:

```python
    app.dependency_overrides[get_user_zone_reader] = lambda: UserZoneReader(pg_sessionmaker)
```

Then check for any other direct caller:

```bash
grep -rn "_alert_teachers_and_parents(" tests/
```

For each hit, add `zones=UserZoneReader(pg_sessionmaker),` to the call.

- [ ] **Step 9: Run the tests to verify they pass**

```bash
pytest tests/test_user_zones.py tests/test_xp_repo.py tests/test_notification_repo.py tests/test_leaderboard_repo.py tests/test_web_notify_seams.py tests/test_web_xp.py tests/test_web_student.py -q
```

Expected: PASS. Every pre-existing test constructs the services with `zone=` and no reader, which is the documented fallback.

- [ ] **Step 10: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/xp_repo.py lemely/db/notification_repo.py lemely/db/leaderboard_repo.py lemely/web/routers/student.py lemely/web/deps.py tests/test_web_notify_seams.py tests/test_user_zones.py
git commit -S -m "feat(db): personal civil dates in the user's own zone, shared weeks stay global

XpService and NotificationService take a UserZoneReader: awarded_on, the
daily cap, streak days and quiet hours follow the recipient; the at-risk
day is the assessed student's. week_bounds and the leaderboard keep the
launch zone on purpose (a shared ranking summed over two weeks means
nothing), and leaderboard_repo now says so. History is not rewritten."
```

---

### Task 3: `PUT /me/timezone` and the profile fields

**Files:**
- Modify: `lemely/auth/mirror.py:89-100` (protocol), `:180-185` (`DbUserMirror`)
- Modify: `lemely/web/schemas_me.py:35-69` (`ProfileDTO`), end of file (two new DTOs and `__all__`)
- Modify: `lemely/web/routers/me.py:12-16` (imports), `:42-52` (deps import), `:58-62` (schemas import), `:270-278` (`_profile_dto`), after `delete_avatar` (line 425)
- Modify: `tests/test_authz_matrix_complete.py:165` (add the route)
- Modify: `tests/test_web_me.py:142-168` (`_SessionUserMirror` gains `set_timezone`)
- Test: `tests/test_web_me.py` (append)

**Interfaces:**
- Consumes: `UserZoneReader.forget` (Task 1), `deps.get_user_zone_reader` (Task 2).
- Produces: `UserMirror.set_timezone(user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None`; `PUT /api/me/timezone` with body `TimezoneUpdateDTO {timezone: str | None (max 64), explicit: bool}` and response `TimezoneDTO {timezone: str | None, timezoneIsExplicit: bool}`; `ProfileDTO` gains `timezone: str | None` and `timezoneIsExplicit: bool`.

Semantics, stated once here and repeated in the route docstring:

| Body | Effect |
|---|---|
| `{timezone: "Z", explicit: true}` | store `Z`, flag `true` |
| `{timezone: "Z", explicit: false}` | store `Z` and flag `false` **only if** the flag is currently `false`; otherwise no change (auto-detect never overwrites a choice) |
| `{timezone: null, explicit: false}` | clear: `NULL`, flag `false` ("follow this device"; the client then sends its device zone) |
| `{timezone: null, explicit: true}` | 422 |
| unresolvable name, or over 64 characters | 422 |

- [ ] **Step 1: Write the failing tests**

In `tests/test_web_me.py`, extend `_SessionUserMirror` (after `set_avatar_path`, line 167) with:

```python
    def set_timezone(self, user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None:
        with self._sm.begin() as session:
            user = session.get(User, user_id)
            if user is None:
                return
            if explicit:
                user.timezone = zone
                user.timezone_is_explicit = True
            elif zone is None:
                user.timezone = None
                user.timezone_is_explicit = False
            elif not user.timezone_is_explicit:
                user.timezone = zone
```

Update the class docstring's last sentence from "Only ``get_by_id`` is implemented — the only method ``get_profile`` calls." to "``get_by_id``, ``set_avatar_path`` and ``set_timezone`` are implemented — the methods the routes under test call."

Append to the end of `tests/test_web_me.py`:

```python
# ---------------------------------------------------------------------------
# PUT /api/me/timezone (push-delivery spec §3).
# ---------------------------------------------------------------------------


def _stored_zone(sm: sessionmaker[Session], user: uuid.UUID) -> tuple[str | None, bool]:
    with sm() as session:
        row = session.get(User, user)
        assert row is not None
        return row.timezone, row.timezone_is_explicit


def test_profile_reports_the_zone_and_whether_it_was_chosen(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.teacher)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.teacher)

    body = client.get("/api/me/profile").json()

    assert body["timezone"] is None
    assert body["timezoneIsExplicit"] is False


@pytest.mark.parametrize("role", [Role.student, Role.teacher, Role.parent, Role.school_admin])
def test_an_explicit_zone_is_stored_for_every_role(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    """On the ``me`` router because a zone applies to every role: a teacher and
    a parent both receive ``at_risk_alert`` and both have quiet hours."""
    user = _seed_user(pg_sessionmaker, role)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, role)

    resp = client.put(
        "/api/me/timezone", json={"timezone": "America/Los_Angeles", "explicit": True}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"timezone": "America/Los_Angeles", "timezoneIsExplicit": True}
    assert _stored_zone(pg_sessionmaker, user) == ("America/Los_Angeles", True)


def test_a_device_zone_is_stored_while_nothing_was_chosen(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.put("/api/me/timezone", json={"timezone": "Europe/Paris", "explicit": False})

    assert resp.status_code == 200
    assert resp.json() == {"timezone": "Europe/Paris", "timezoneIsExplicit": False}
    assert _stored_zone(pg_sessionmaker, user) == ("Europe/Paris", False)


def test_a_device_zone_never_overwrites_a_chosen_one(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """Opening the app on a plane must not undo a deliberate choice."""
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)
    client.put("/api/me/timezone", json={"timezone": "Africa/Cairo", "explicit": True})

    resp = client.put("/api/me/timezone", json={"timezone": "Europe/Paris", "explicit": False})

    assert resp.status_code == 200
    assert resp.json() == {"timezone": "Africa/Cairo", "timezoneIsExplicit": True}
    assert _stored_zone(pg_sessionmaker, user) == ("Africa/Cairo", True)


def test_an_explicit_write_replaces_an_earlier_choice(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)
    client.put("/api/me/timezone", json={"timezone": "Africa/Cairo", "explicit": True})

    resp = client.put("/api/me/timezone", json={"timezone": "Asia/Tokyo", "explicit": True})

    assert resp.json() == {"timezone": "Asia/Tokyo", "timezoneIsExplicit": True}


def test_following_the_device_again_clears_the_choice(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """``timezone: null, explicit: false`` is the one body that flips the flag
    back; the client follows it with its device zone, which is then accepted."""
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)
    client.put("/api/me/timezone", json={"timezone": "Africa/Cairo", "explicit": True})

    cleared = client.put("/api/me/timezone", json={"timezone": None, "explicit": False})
    assert cleared.json() == {"timezone": None, "timezoneIsExplicit": False}

    followed = client.put("/api/me/timezone", json={"timezone": "Europe/Paris", "explicit": False})
    assert followed.json() == {"timezone": "Europe/Paris", "timezoneIsExplicit": False}


@pytest.mark.parametrize(
    "body",
    [
        {"timezone": "Mars/Olympus_Mons", "explicit": True},
        {"timezone": "../etc/passwd", "explicit": False},
        {"timezone": "A" * 65, "explicit": True},
        {"timezone": None, "explicit": True},
        {"timezone": "", "explicit": True},
    ],
)
def test_a_bad_zone_is_422_and_stores_nothing(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], body: dict[str, object]
) -> None:
    """An unvalidated string would be stored once and then degrade to the
    launch zone on every read forever, which looks like the feature silently
    not working."""
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.put("/api/me/timezone", json=body)

    assert resp.status_code == 422, resp.text
    assert _stored_zone(pg_sessionmaker, user) == (None, False)


def test_timezone_requires_a_bearer_token(client: TestClient) -> None:
    assert client.put("/api/me/timezone", json={"timezone": "Africa/Cairo", "explicit": True}).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_web_me.py -k "timezone or zone" -v
```

Expected: FAIL — the profile test with `KeyError: 'timezone'`, the PUT tests with `405`/`404` (no route yet).

- [ ] **Step 3: Extend the mirror**

In `lemely/auth/mirror.py`, add to the `UserMirror` protocol after `set_avatar_path` (after line 100):

```python
    def set_timezone(self, user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None:
        """Set, follow, or clear ``users.timezone`` (push-delivery spec §3).

        ``explicit=True`` stores ``zone`` and marks it chosen. ``explicit=False``
        with a ``zone`` is the client's device auto-detect and is written only
        while nothing was chosen — a plane must never undo a deliberate choice.
        ``explicit=False`` with ``zone=None`` clears the choice so auto-detect
        resumes. Validation (a resolvable IANA name, at most 64 characters) is
        the route's job; this writes what it is given. A ``user_id`` with no
        mirrored row is a silent no-op, matching :meth:`set_avatar_path`.
        """
        ...
```

And to `DbUserMirror` after `set_avatar_path` (after line 185):

```python
    def set_timezone(self, user_id: uuid.UUID, zone: str | None, *, explicit: bool) -> None:
        """Set, follow, or clear ``users.timezone``, if the row exists."""
        with session_scope(self._settings) as session:
            user = session.get(User, user_id)
            if user is None:
                return
            if explicit:
                user.timezone = zone
                user.timezone_is_explicit = True
            elif zone is None:
                user.timezone = None
                user.timezone_is_explicit = False
            elif not user.timezone_is_explicit:
                user.timezone = zone
```

- [ ] **Step 4: Add the DTOs**

In `lemely/web/schemas_me.py`, add `from pydantic import Field` after the `datetime` import. In `ProfileDTO`, after the `avatarUrl` docstring paragraph (line 62) add:

```
    ``timezone``/``timezoneIsExplicit`` mirror ``users.timezone`` and
    ``users.timezone_is_explicit`` (push-delivery spec §3). ``timezone`` is
    ``null`` when never set; the client renders that as "follow this device"
    and never invents a name for the server-side default.
```

and after `avatarUrl: str | None = None` (line 69) add:

```python
    timezone: str | None = None
    timezoneIsExplicit: bool = False
```

Before `__all__`, add:

```python
class TimezoneUpdateDTO(ApiModel):
    """Body for ``PUT /api/me/timezone`` (push-delivery spec §3).

    ``timezone`` is an IANA name or ``null``; ``max_length=64`` matches the
    column. ``explicit`` says whether the *user* chose it: the settings picker
    sends ``true``, the app-boot auto-detect sends ``false``, and
    ``{"timezone": null, "explicit": false}`` is "follow this device" — the
    one body that clears an earlier choice. See the route for the full table.
    """

    timezone: str | None = Field(default=None, max_length=64)
    explicit: bool


class TimezoneDTO(ApiModel):
    """Response for ``PUT /api/me/timezone``: the stored state after the write.

    Echoes what is *stored*, not what was sent — a non-explicit write against
    a chosen zone changes nothing, and the response says so.
    """

    timezone: str | None
    timezoneIsExplicit: bool
```

Add `"TimezoneDTO"` and `"TimezoneUpdateDTO"` to `__all__`.

- [ ] **Step 5: Add the route**

In `lemely/web/routers/me.py`:

- Add `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` after `from typing import Annotated` (line 16).
- Add `UserZoneReader` to a new import `from lemely.db.xp_repo import UserZoneReader  # noqa: TC001 - FastAPI resolves this at runtime` after the `student_profile_repo` import block (after line 39).
- Add `get_user_zone_reader` to the `from lemely.web.deps import (...)` block.
- Add `TimezoneDTO, TimezoneUpdateDTO` to the `from lemely.web.schemas_me import (...)` block.

In `_profile_dto` (lines 270-278), add two fields:

```python
def _profile_dto(user: User, settings: Settings, storage: StorageBackend) -> ProfileDTO:
    """Build the ``ProfileDTO`` every ``/api/me/profile``-family route returns."""
    return ProfileDTO(
        displayName=user.display_name,
        email=user.email,
        role=user.role.value,
        emailVerified=user.email_verified_at is not None,
        avatarUrl=_avatar_url_for(user, settings, storage),
        timezone=user.timezone,
        timezoneIsExplicit=user.timezone_is_explicit,
    )
```

After `delete_avatar` (after line 425), before the student-onboarding banner comment, add:

```python
# ---------------------------------------------------------------------------
# Time zone: any authenticated role (push-delivery spec §3).
# ---------------------------------------------------------------------------


def _validate_zone_name(name: str) -> None:
    """422 unless ``name`` resolves through :class:`ZoneInfo`.

    An unvalidated string would be stored once and then degrade to the launch
    zone on every read forever (``resolve_zone`` never raises), which looks
    exactly like the feature silently not working. Length is the DTO's job.
    """
    if not name.strip():
        raise HTTPException(status_code=422, detail="timezone must be an IANA zone name.")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown time zone: {name!r}. Use an IANA name."
        ) from exc


@router.put("/timezone", response_model=TimezoneDTO)
def put_timezone(
    payload: TimezoneUpdateDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)],
) -> TimezoneDTO:
    """Set the caller's civil-time zone, or let the device decide it.

    On the ``me`` router rather than ``student-profile`` because a zone
    applies to every role: a teacher and a parent both receive
    ``at_risk_alert`` and both have quiet hours.

    Three bodies mean three things:

    * ``{"timezone": "Z", "explicit": true}`` — the settings picker. Stored,
      and marked as the user's choice.
    * ``{"timezone": "Z", "explicit": false}`` — the app-boot auto-detect.
      Stored **only while no choice is on record**; otherwise ignored, so
      opening the app on a plane never undoes a deliberate choice.
    * ``{"timezone": null, "explicit": false}`` — "follow this device".
      Clears the choice; the client then sends its device zone, which the
      second rule now accepts.

    ``{"timezone": null, "explicit": true}`` is a 422 (nothing to choose), as
    is any name ``ZoneInfo`` cannot resolve or one over 64 characters. The
    response is the *stored* state, which for an ignored auto-detect write is
    the earlier choice, unchanged.

    The zone reader's memo for this user is dropped after the write so the
    next award or notification reads the new zone rather than a stale one.
    """
    if payload.timezone is None and payload.explicit:
        raise HTTPException(status_code=422, detail="An explicit time zone cannot be null.")
    if payload.timezone is not None:
        _validate_zone_name(payload.timezone)

    user_id = _require_user_id(auth)
    mirror.set_timezone(user_id, payload.timezone, explicit=payload.explicit)
    zones.forget(user_id)

    user = mirror.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No profile found for this account.")
    return TimezoneDTO(timezone=user.timezone, timezoneIsExplicit=user.timezone_is_explicit)
```

- [ ] **Step 6: Declare the route in the authz matrix**

In `tests/test_authz_matrix_complete.py`, after the `("GET", "/api/me/profile"): AUTH_ANY,` line (165) add:

```python
    ("PUT", "/api/me/timezone"): AUTH_ANY,
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
pytest tests/test_web_me.py tests/test_authz_matrix_complete.py -q
```

Expected: PASS. If `test_authz_matrix_complete.py` reports the route's guard differently from `AUTH_ANY`, the route is missing `Depends(get_auth_context)` — check the signature above.

- [ ] **Step 8: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/auth/mirror.py lemely/web/schemas_me.py lemely/web/routers/me.py tests/test_authz_matrix_complete.py tests/test_web_me.py
git commit -S -m "feat(web): PUT /me/timezone, on the me router because every role has a zone

Explicit writes are the user's choice and win; a device auto-detect write
is stored only while nothing was chosen; {timezone: null, explicit: false}
is the one body that clears a choice. Unresolvable and over-length names
are 422 rather than stored and silently degraded on every read."
```

---

### Task 4: Frontend: device-zone sync at boot and the settings picker

**Files:**
- Modify: `web/src/lib/meTypes.ts:14-34` (`Profile`), after it (`TimezoneUpdate`, `TimezoneState`)
- Create: `web/src/lib/timezone.ts`
- Modify: `web/src/lib/hooks/useMeApi.ts:28-35` (add `usePutTimezone` after `useProfile`)
- Create: `web/src/components/timezone-sync.tsx`
- Modify: `web/src/main.tsx:77` (mount `TimezoneSync` beside `RecoveryEffects`)
- Modify: `web/src/portals/settings/ProfileSettings.tsx` (imports; a third section before the closing `</>` at line 219)
- Test: `web/tests/unit/timezone.test.ts` (new)

**Interfaces:**
- Consumes: `PUT /api/me/timezone` (Task 3), `Profile.timezone` / `Profile.timezoneIsExplicit` (Task 3).
- Produces: `export interface TimezoneUpdate { timezone: string | null; explicit: boolean }`; `export interface TimezoneState { timezone: string | null; timezoneIsExplicit: boolean }`; `deviceTimezone(resolve?: () => { timeZone?: string }): string | null`; `deviceTimezoneUpdate(zone: string | null): TimezoneUpdate | null`; `explicitTimezoneUpdate(zone: string): TimezoneUpdate`; `FOLLOW_DEVICE_UPDATE: TimezoneUpdate`; `timezoneOptions(supported: readonly string[], ...extra: (string | null | undefined)[]): string[]`; `pickerValue(profile: TimezoneState | undefined): string`; `usePutTimezone(): UseMutationResult<TimezoneState, Error, TimezoneUpdate>`.

- [ ] **Step 1: Add the client types**

In `web/src/lib/meTypes.ts`, inside `Profile` after `avatarUrl: string | null` (line 33) add:

```ts
  /**
   * `users.timezone` and `users.timezone_is_explicit` (push-delivery spec
   * §3). `timezone` is `null` when never set; render that as "follow this
   * device", never as an invented name for the server's default.
   */
  timezone: string | null
  timezoneIsExplicit: boolean
```

After the `Profile` interface add:

```ts
/** Body for `PUT /api/me/timezone` (mirrors `TimezoneUpdateDTO`). See
 * `lib/timezone.ts` for the three shapes and what each means. */
export interface TimezoneUpdate {
  timezone: string | null
  explicit: boolean
}

/** Response for `PUT /api/me/timezone` (mirrors `TimezoneDTO`): the stored
 * state after the write, which for an ignored auto-detect is unchanged. */
export interface TimezoneState {
  timezone: string | null
  timezoneIsExplicit: boolean
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/tests/unit/timezone.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  FOLLOW_DEVICE_UPDATE,
  deviceTimezone,
  deviceTimezoneUpdate,
  explicitTimezoneUpdate,
  pickerValue,
  timezoneOptions,
} from "@/lib/timezone"

/*
 * Per-user time zones (push-delivery spec §3), the page half. The server owns
 * the rule that a device write never overwrites a choice; what the client has
 * to get right is which of the three bodies it sends, because the wrong flag
 * either lets a plane undo a choice or stops a choice from ever being made.
 */

describe("explicitTimezoneUpdate", () => {
  it("marks a picked zone as the user's choice", () => {
    expect(explicitTimezoneUpdate("America/Los_Angeles")).toEqual({
      timezone: "America/Los_Angeles",
      explicit: true,
    })
  })
})

describe("FOLLOW_DEVICE_UPDATE", () => {
  it("clears the choice with a null zone and explicit false", () => {
    expect(FOLLOW_DEVICE_UPDATE).toEqual({ timezone: null, explicit: false })
  })
})

describe("deviceTimezoneUpdate", () => {
  it("sends the device zone as a non-explicit write", () => {
    expect(deviceTimezoneUpdate("Europe/Paris")).toEqual({ timezone: "Europe/Paris", explicit: false })
  })

  it("sends nothing when the device has no zone to report", () => {
    expect(deviceTimezoneUpdate(null)).toBeNull()
    expect(deviceTimezoneUpdate("")).toBeNull()
  })
})

describe("deviceTimezone", () => {
  it("reads Intl's resolved zone", () => {
    expect(deviceTimezone(() => ({ timeZone: "Asia/Tokyo" }))).toBe("Asia/Tokyo")
  })

  it("is null when Intl reports none, or throws", () => {
    expect(deviceTimezone(() => ({}))).toBeNull()
    expect(
      deviceTimezone(() => {
        throw new RangeError("no Intl")
      }),
    ).toBeNull()
  })
})

describe("pickerValue", () => {
  it("shows the chosen zone when one was chosen", () => {
    expect(pickerValue({ timezone: "Africa/Cairo", timezoneIsExplicit: true })).toBe("Africa/Cairo")
  })

  it("shows follow-this-device when the zone came from the device or is unset", () => {
    expect(pickerValue({ timezone: "Africa/Cairo", timezoneIsExplicit: false })).toBe("")
    expect(pickerValue({ timezone: null, timezoneIsExplicit: false })).toBe("")
    expect(pickerValue(undefined)).toBe("")
  })
})

describe("timezoneOptions", () => {
  it("includes the current and device zones even when the browser does not list them", () => {
    expect(timezoneOptions(["Africa/Cairo"], "Mars/Base", null, undefined)).toEqual([
      "Africa/Cairo",
      "Mars/Base",
    ])
  })

  it("sorts and dedupes", () => {
    expect(timezoneOptions(["Europe/Paris", "Africa/Cairo", "Europe/Paris"], "Africa/Cairo")).toEqual([
      "Africa/Cairo",
      "Europe/Paris",
    ])
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd web && npx vitest run tests/unit/timezone.test.ts
```

Expected: FAIL — cannot resolve `@/lib/timezone`.

- [ ] **Step 4: Write the pure module**

Create `web/src/lib/timezone.ts`:

```ts
/*
 * Per-user time zones (push-delivery spec §3), the page half.
 *
 * `PUT /api/me/timezone` takes one of three bodies and the server owns what
 * each means: an explicit write is the user's choice and wins; a device write
 * (`explicit: false` with a zone) is stored only while nothing was chosen; a
 * null zone with `explicit: false` clears the choice so the device is followed
 * again. This module builds those bodies and nothing else, so the one thing the
 * client can get wrong — which flag it sends — is pinned by a unit test rather
 * than discovered by a reader whose deliberate choice got undone on a plane.
 *
 * Nothing here touches `Intl` directly except `deviceTimezone`, which takes the
 * resolver as a parameter for the reason every `lib/*.ts` module does: the web
 * runner is `environment: "node"` and a global reached for inside a function
 * could only be checked by reading its source.
 */

import type { TimezoneState, TimezoneUpdate } from "@/lib/meTypes"

/** The picker's value for "follow this device", and the one value the
 * `<select>` has that is not an IANA name. */
export const FOLLOW_DEVICE_VALUE = ""

/** "Follow this device": clears an earlier choice. The caller sends the device
 * zone right after, which the server then accepts. */
export const FOLLOW_DEVICE_UPDATE: TimezoneUpdate = { timezone: null, explicit: false }

/** The device's IANA zone, or null when the browser reports none. Wrapped:
 * some embedded engines throw from `Intl.DateTimeFormat()`. */
export function deviceTimezone(
  resolve: () => { timeZone?: string } = () => Intl.DateTimeFormat().resolvedOptions(),
): string | null {
  try {
    const zone = resolve().timeZone
    return typeof zone === "string" && zone.trim() !== "" ? zone : null
  } catch {
    return null
  }
}

/** The app-boot write. Null when there is no zone to send; the server's rule
 * (stored only while nothing was chosen) is not repeated here on purpose. */
export function deviceTimezoneUpdate(zone: string | null): TimezoneUpdate | null {
  if (zone === null || zone.trim() === "") return null
  return { timezone: zone, explicit: false }
}

/** The settings picker's write: a choice, which wins over the device. */
export function explicitTimezoneUpdate(zone: string): TimezoneUpdate {
  return { timezone: zone, explicit: true }
}

/** What the picker shows: the chosen zone, or "follow this device" for both a
 * device-sourced zone and an unset one. A device-sourced name is deliberately
 * not shown as if it were chosen — that is the state the server will happily
 * overwrite on the next boot, and the control should say so. */
export function pickerValue(profile: TimezoneState | undefined): string {
  if (profile === undefined || !profile.timezoneIsExplicit || profile.timezone === null) {
    return FOLLOW_DEVICE_VALUE
  }
  return profile.timezone
}

/** The `<select>` options: the browser's list plus any zone that has to be
 * representable even if the browser does not list it (the stored one, the
 * device's). Sorted so the list is scannable; deduped so a zone in both sets
 * appears once. */
export function timezoneOptions(
  supported: readonly string[],
  ...extra: (string | null | undefined)[]
): string[] {
  const names = new Set<string>(supported)
  for (const zone of extra) {
    if (typeof zone === "string" && zone.trim() !== "") names.add(zone)
  }
  return [...names].sort((a, b) => a.localeCompare(b))
}

/** The browser's zone list, or an empty list where `Intl.supportedValuesOf`
 * is missing; `timezoneOptions` adds the zones that must be present anyway. */
export function browserTimezones(): string[] {
  try {
    return typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : []
  } catch {
    return []
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npx vitest run tests/unit/timezone.test.ts
```

Expected: PASS, 11 tests.

- [ ] **Step 6: The mutation hook**

In `web/src/lib/hooks/useMeApi.ts`, add `TimezoneState, TimezoneUpdate` to the `import type {...} from "@/lib/meTypes"` block, and after `useProfile` (after line 35) add:

```ts
/**
 * `PUT /me/timezone` (push-delivery spec §3). Same partial-echo shape as the
 * notification-preferences hook: the response is the *stored* state, which for
 * an ignored device write is the earlier choice unchanged, so it is merged into
 * the cached profile rather than assumed from the request.
 */
export function usePutTimezone(): UseMutationResult<TimezoneState, Error, TimezoneUpdate> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (update: TimezoneUpdate) =>
      request<TimezoneState>("/me/timezone", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update satisfies TimezoneUpdate),
      }),
    onSuccess: (state) => {
      queryClient.setQueryData<Profile>(PROFILE_KEY, (old) => (old ? { ...old, ...state } : old))
    },
  })
}
```

- [ ] **Step 7: The boot-time sync**

Create `web/src/components/timezone-sync.tsx`:

```tsx
import { useEffect, useRef } from "react"
import { useAuth } from "@/lib/auth/AuthContext"
import { usePutTimezone } from "@/lib/hooks/useMeApi"
import { deviceTimezone, deviceTimezoneUpdate } from "@/lib/timezone"

/*
 * Sends the device's zone once per signed-in session (push-delivery spec §3,
 * "auto-detect"). Mounted once above the router, beside `RecoveryEffects`, for
 * the same reason that one is: this has to run whichever screen the reader
 * lands on, and an effect inside a screen would only run there.
 *
 * It sends unconditionally and lets the server decide. The rule that a device
 * write never overwrites a deliberate choice lives in `routers/me.py`, where it
 * is enforced for every client; repeating it here as a client-side gate would
 * be a second copy that could disagree with the first.
 *
 * Failure is silent by design: a missed sync costs one civil day of the launch
 * zone until the next boot, and there is no screen to report it on.
 */
export function TimezoneSync() {
  const { session } = useAuth()
  const put = usePutTimezone()
  const sentFor = useRef<string | null>(null)
  const userId = session?.userId ?? null

  useEffect(() => {
    if (userId === null || sentFor.current === userId) return
    const update = deviceTimezoneUpdate(deviceTimezone())
    if (update === null) return
    sentFor.current = userId
    put.mutate(update)
    // `put` is stable for the component's lifetime; listing it would re-run
    // this on every render and the ref guard would still make that a no-op.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  return null
}
```

In `web/src/main.tsx`, add the import beside `RecoveryEffects` (line 11):

```tsx
import { TimezoneSync } from "./components/timezone-sync"
```

and mount it immediately after `<RecoveryEffects />` (line 77):

```tsx
          {/* Sends the device zone once per session, so every civil-date
              calculation for this reader runs where they actually are. See
              the component for why it lives here and not in a screen. */}
          <TimezoneSync />
```

- [ ] **Step 8: The picker**

In `web/src/portals/settings/ProfileSettings.tsx`:

Add to the imports:

```tsx
import { useProfile, usePutTimezone, useRemoveAvatar, useUploadAvatar } from "@/lib/hooks/useMeApi"
import {
  FOLLOW_DEVICE_UPDATE,
  FOLLOW_DEVICE_VALUE,
  browserTimezones,
  deviceTimezone,
  deviceTimezoneUpdate,
  explicitTimezoneUpdate,
  pickerValue,
  timezoneOptions,
} from "@/lib/timezone"
```

(replace the existing `useMeApi` import line). Inside `ProfileSettingsSection`, after `const remove = useRemoveAvatar()` add:

```tsx
  const putTimezone = usePutTimezone()
  const [timezoneError, setTimezoneError] = useState<string | null>(null)
  const device = deviceTimezone()
  const zoneOptions = timezoneOptions(browserTimezones(), profile.data?.timezone, device)

  const handleTimezoneChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setTimezoneError(null)
    const value = event.target.value
    if (value === FOLLOW_DEVICE_VALUE) {
      // Clear the choice first, then send the device zone: the server
      // accepts a device write only once nothing is chosen.
      putTimezone.mutate(FOLLOW_DEVICE_UPDATE, {
        onError: (error) => setTimezoneError(settingsSaveFailureMessage(error)),
        onSuccess: () => {
          const update = deviceTimezoneUpdate(device)
          if (update !== null) putTimezone.mutate(update)
        },
      })
      return
    }
    putTimezone.mutate(explicitTimezoneUpdate(value), {
      onError: (error) => setTimezoneError(settingsSaveFailureMessage(error)),
    })
  }
```

Before the closing `</>` (line 219), add a third section:

```tsx
      <section aria-labelledby="timezone-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="timezone-heading" className="text-display-sm text-ink">
            Time zone
          </h2>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">
            Quiet hours, streak days and daily reminders follow this. Following your device
            keeps it up to date when you travel.
          </p>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
          <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
            Your time zone
            <select
              value={pickerValue(profile.data)}
              onChange={handleTimezoneChange}
              disabled={profile.isPending || putTimezone.isPending}
              className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            >
              <option value={FOLLOW_DEVICE_VALUE}>
                {device ? `Follow this device (${device})` : "Follow this device"}
              </option>
              {zoneOptions.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </label>
          {timezoneError ? (
            <p role="status" className="text-body-sm text-err">
              {timezoneError}
            </p>
          ) : null}
        </div>
      </section>
```

- [ ] **Step 9: Typecheck, lint, copy gate, unit suite**

```bash
npm run typecheck && npm run lint && npm run check:copy && npx vitest run
```

Expected: typecheck silent (ES2023 lib includes `Intl.supportedValuesOf`); lint reports only pre-existing warnings; `check:copy` reports only pre-existing findings; all unit tests pass. If a test fixture builds a `Profile` literal and now fails on the two new fields, add `timezone: null, timezoneIsExplicit: false` to it.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/meTypes.ts web/src/lib/timezone.ts web/src/lib/hooks/useMeApi.ts web/src/components/timezone-sync.tsx web/src/main.tsx web/src/portals/settings/ProfileSettings.tsx web/tests/unit/timezone.test.ts
git commit -S -m "feat(web): send the device time zone at boot and offer a picker in profile settings

The three request shapes live in one pure module so the flag the client
sends is pinned by a unit test. The boot sync sends unconditionally and
lets the server refuse to overwrite a choice, rather than carrying a second
copy of that rule."
```

---

### Task 5: Announcement deferral: `notified_at`, the shared fan-out, `publish_due_announcements`

**Files:**
- Create: `lemely/db/migrations/versions/0030_announcement_notified_at.py`
- Modify: `lemely/db/models/ops.py:74-101` (`Announcement`)
- Modify: `lemely/db/announcement_repo.py:131-142` (`AnnouncementRow`), `:404-474` (`student_recipients`), `:603-613` (`_to_row`), add `is_due`, `claim_due`, `DueClaim`, `mark_notified`; `__all__`
- Create: `lemely/web/scheduled_notifications.py`
- Modify: `lemely/web/routers/announcements.py:1-22` (module docstring), `:51` (import), `:164` (call), `:168-218` (delete `_notify_audience`)
- Modify: `tests/test_web_notify_seams.py` (append after the announcement tests)
- Test: `tests/test_scheduled_announcements.py` (new)

**Interfaces:**
- Consumes: `AnnouncementService.student_recipients` (existing), `notify_safely` (existing).
- Produces: `AnnouncementRow.notified_at: datetime | None`; `AnnouncementService.is_due(row: AnnouncementRow) -> bool`; `AnnouncementService.mark_notified(announcement_ids: Sequence[uuid.UUID], *, now: datetime | None = None) -> int`; `AnnouncementService.claim_due(*, now: datetime | None = None, limit: int = DEFAULT_CLAIM_LIMIT) -> ContextManager[DueClaim]` where `DueClaim.rows: list[AnnouncementRow]` and `DueClaim.stamp(at: datetime) -> None`; `DEFAULT_CLAIM_LIMIT = 100`. In `lemely.web.scheduled_notifications`: `notify_announcement_audience(service, notifications, transport, rows) -> bool`, `deliver_announcements_now(service, notifications, transport, rows) -> None`, `publish_due_announcements(service, notifications, transport, *, now: datetime, limit: int = DEFAULT_CLAIM_LIMIT) -> int`.

- [ ] **Step 1: Write the failing job-level tests**

Create `tests/test_scheduled_announcements.py`:

```python
"""The announcement sweeper job (push-delivery spec §1).

``notified_at`` means "fan-out for this row completed". The job claims due rows
with ``FOR UPDATE SKIP LOCKED``, fans out through the same code the composer
uses, and stamps **after** the send: a crash between the two re-runs the row,
and migration 0018's unique index makes the re-run harmless.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import Announcement, User
from lemely.db.models.enums import NotificationType, Role
from lemely.db.models.orgs import ClassEnrollment
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import DatabaseSettings
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import publish_due_announcements

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def announcements(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AnnouncementService:
    return AnnouncementService(pg_sessionmaker, class_service, now=lambda: NOW)


@pytest.fixture
def notifications(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    return NotificationService(
        pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker), now=lambda: NOW
    )


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _subscribe(notifications: NotificationService, user: uuid.UUID) -> str:
    endpoint = f"https://push.example.test/{user}"
    notifications.subscribe(user, endpoint, "p256dh", "auth")
    return endpoint


def _class_with_students(
    sm: sessionmaker[Session], class_service: ClassService, count: int
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    teacher = _seed_user(sm, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    students = [_seed_user(sm) for _ in range(count)]
    for student in students:
        _enroll(sm, cls.class_id, student)
    return teacher, cls.class_id, students


def _scheduled(
    announcements: AnnouncementService,
    teacher: uuid.UUID,
    class_id: uuid.UUID,
    *,
    publish_at: datetime | None,
) -> uuid.UUID:
    rows = announcements.create(
        teacher, Role.teacher, title="Trip forms", body="Due Monday.",
        class_ids=[class_id], publish_at=publish_at,
    )
    return rows[0].announcement_id


def _notified_at(sm: sessionmaker[Session], announcement_id: uuid.UUID) -> datetime | None:
    with sm() as session:
        return session.scalar(
            select(Announcement.notified_at).where(Announcement.id == announcement_id)
        )


def _inbox(notifications: NotificationService, user: uuid.UUID) -> list[str]:
    return [row.payload["announcementId"] for row in notifications.list_for_user(user)]


def test_the_job_claims_a_due_row_fans_out_to_the_audience_and_stamps_it(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 3)
    for student in students:
        _subscribe(notifications, student)
    announcement_id = _scheduled(
        announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=1)
    )

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    assert claimed == 1
    for student in students:
        assert _inbox(notifications, student) == [str(announcement_id)]
    assert len(transport.endpoints) == 3
    assert _notified_at(pg_sessionmaker, announcement_id) == NOW


def test_the_job_ignores_rows_already_stamped_and_rows_not_yet_due(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    stamped = _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(hours=1))
    announcements.mark_notified([stamped], now=NOW - timedelta(hours=1))
    future = _scheduled(announcements, teacher, class_id, publish_at=NOW + timedelta(hours=1))
    immediate = _scheduled(announcements, teacher, class_id, publish_at=None)

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    # ``publish_at IS NULL`` rows are the composer's to notify at create time,
    # never the sweeper's: a NULL is "published immediately", not "due".
    assert claimed == 0
    assert _inbox(notifications, students[0]) == []
    assert _notified_at(pg_sessionmaker, future) is None
    assert _notified_at(pg_sessionmaker, immediate) is None


def test_a_run_interrupted_between_send_and_stamp_is_harmless_when_re_run(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """The direct test of stamp-after-send. The fan-out completes, the stamp
    never lands (the claim's transaction rolls back), and the next pass finds
    the row still unstamped. The unique index rejects the second inbox row,
    ``create`` answers ``duplicate`` with ``push_allowed=False``, and no
    second push is attempted."""
    from lemely.web.scheduled_notifications import notify_announcement_audience

    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 2)
    for student in students:
        _subscribe(notifications, student)
    announcement_id = _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5))

    class _Crash(RuntimeError):
        pass

    with pytest.raises(_Crash), announcements.claim_due(now=NOW) as claim:
        assert [row.announcement_id for row in claim.rows] == [announcement_id]
        assert notify_announcement_audience(announcements, notifications, transport, claim.rows)
        raise _Crash  # before claim.stamp(): the send happened, the stamp did not

    assert _notified_at(pg_sessionmaker, announcement_id) is None
    assert len(transport.endpoints) == 2
    transport.reset()

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    assert claimed == 1
    for student in students:
        assert _inbox(notifications, student) == [str(announcement_id)]
    assert transport.endpoints == []
    assert _notified_at(pg_sessionmaker, announcement_id) == NOW


def test_two_concurrent_runs_do_not_both_claim_one_row(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """``SKIP LOCKED`` is what makes two replicas safe without a lock table.
    A second session holds the row's lock; the job sees nothing to do. Once the
    lock is released the row is claimed normally."""
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    announcement_id = _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5))

    with pg_sessionmaker() as other, other.begin():
        other.execute(
            select(Announcement).where(Announcement.id == announcement_id).with_for_update()
        ).all()
        assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 0
        assert _inbox(notifications, students[0]) == []

    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 1
    assert _inbox(notifications, students[0]) == [str(announcement_id)]


def test_a_second_pass_after_a_stamp_does_nothing(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5))

    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 1
    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 0
    assert len(_inbox(notifications, students[0])) == 1
```

- [ ] **Step 2: Write the failing route-level tests**

Append to `tests/test_web_notify_seams.py`, after the last announcement test in the file:

```python
def test_a_future_dated_announcement_notifies_nobody_at_create_time(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """A push at create time would send a student to a post ``_is_visible``
    still hides. The row stays unstamped for the sweeper (spec §1)."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    student = _seed_user(pg_sessionmaker)
    _enroll(pg_sessionmaker, cls.class_id, student)
    _auth_as(compose_client, teacher, Role.teacher)

    payload = _post(
        compose_client,
        title="Next term",
        body="Timetable attached later.",
        classIds=[str(cls.class_id)],
        publishAt="2099-01-01T09:00:00+00:00",
    )
    announcement_id = uuid.UUID(payload["announcements"][0]["announcementId"])  # type: ignore[index]

    assert notifications.list_for_user(student) == []
    assert transport.endpoints == []
    with pg_sessionmaker() as session:
        assert session.get(Announcement, announcement_id).notified_at is None  # type: ignore[union-attr]


@pytest.mark.parametrize("publish_at", [None, "2020-01-01T09:00:00+00:00"])
def test_a_null_or_past_publish_at_notifies_at_create_time_and_stamps(
    compose_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    notifications: NotificationService,
    publish_at: str | None,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    student = _seed_user(pg_sessionmaker)
    _enroll(pg_sessionmaker, cls.class_id, student)
    _auth_as(compose_client, teacher, Role.teacher)

    payload = _post(
        compose_client,
        title="Today",
        body="Now.",
        classIds=[str(cls.class_id)],
        publishAt=publish_at,
    )
    announcement_id = uuid.UUID(payload["announcements"][0]["announcementId"])  # type: ignore[index]

    assert len(notifications.list_for_user(student)) == 1
    with pg_sessionmaker() as session:
        assert session.get(Announcement, announcement_id).notified_at is not None  # type: ignore[union-attr]
```

Add `Announcement` to the file's `from lemely.db.models import ...` line.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_scheduled_announcements.py tests/test_web_notify_seams.py -k "announcement" -v
```

Expected: `test_scheduled_announcements.py` FAILS at import (`No module named 'lemely.web.scheduled_notifications'`); the two route tests FAIL with `AttributeError: notified_at`.

- [ ] **Step 4: The migration and the model**

Create `lemely/db/migrations/versions/0030_announcement_notified_at.py`:

```python
"""Add ``announcements.notified_at`` and the sweeper's partial index (push-delivery spec §1).

``notified_at`` means *fan-out for this row completed*; ``NULL`` means it has
not. Deliberately a timestamp and not a boolean: it answers "when did this go
out", the question an operator investigating a missed notification asks.

The partial index over ``(publish_at) WHERE notified_at IS NULL`` is the only
shape the sweeper's claim query needs and stays tiny, because the vast majority
of rows are stamped.

No backfill. Every existing row was notified at create time by the router
(``_notify_audience``, P5.6 chunk C2b) or, for a future-dated one, never — and
the sweeper will now notify those at their ``publish_at`` if it is still ahead,
which is the correct-but-late outcome the spec accepts. Stamping them all as
notified would silently drop a scheduled post's audience.

Revision ID: 0030_announcement_notified_at
Revises: 0029_user_timezone
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0030_announcement_notified_at"
down_revision: str | Sequence[str] | None = "0029_user_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "announcements",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_announcements_due_unnotified",
        "announcements",
        ["publish_at"],
        postgresql_where=sa.text("notified_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_announcements_due_unnotified", table_name="announcements")
    op.drop_column("announcements", "notified_at")
```

In `lemely/db/models/ops.py`, replace the `Announcement` class (lines 74-101) with:

```python
class Announcement(TimestampMixin, Base):
    """An announcement published by a teacher or school admin.

    ``notified_at`` (migration ``0030``, push-delivery spec §1) is when the
    notification fan-out for this row **completed**; ``NULL`` means it has not.
    The composer stamps it right after an immediate fan-out; the sweeper in
    :mod:`lemely.web.scheduled_notifications` claims unstamped rows whose
    ``publish_at`` has passed, fans out, and stamps **after** the send — so a
    crash between the two re-runs the row, and migration ``0018``'s unique
    index on ``notifications`` makes that re-run harmless. The partial index is
    the only shape the sweeper's claim needs.
    """

    __tablename__ = "announcements"
    __table_args__ = (
        sa.Index(
            "ix_announcements_due_unnotified",
            "publish_at",
            postgresql_where=sa.text("notified_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id"),
        nullable=True,
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    publish_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
```

- [ ] **Step 5: The service: `is_due`, `claim_due`, `mark_notified`**

In `lemely/db/announcement_repo.py`:

Add to the imports: `from contextlib import contextmanager` (stdlib block) and, under `TYPE_CHECKING`, `from collections.abc import Callable, Iterator, Sequence` (replace the existing `Callable, Sequence` line).

After `DEFAULT_STUDENT_LIMIT` (line 112) add:

```python
#: How many due rows one sweeper pass claims. A pass runs every minute and a
#: school posts a handful of scheduled announcements a day; this is a ceiling
#: on one transaction's lock footprint, not a throughput target.
DEFAULT_CLAIM_LIMIT = 100
```

In `AnnouncementRow` (lines 131-142), add a last field:

```python
    publish_at: datetime | None
    created_at: datetime
    notified_at: datetime | None = None
    """When the notification fan-out completed; ``None`` until then (spec §1).
    Defaulted so the composer's row can be built before it is stamped."""
```

After `StudentAnnouncementRow` add:

```python
@dataclass(slots=True)
class DueClaim:
    """The rows one :meth:`AnnouncementService.claim_due` call locked.

    ``rows`` are detached copies for the caller to fan out over. :meth:`stamp`
    writes ``notified_at`` on the locked models and must be called **after**
    the fan-out, inside the ``with`` block — leaving the block without calling
    it commits nothing, which is the whole point: a crash between send and
    stamp leaves the row for the next pass.
    """

    rows: list[AnnouncementRow]
    _models: list[Announcement]

    def stamp(self, at: datetime) -> None:
        """Record that every claimed row's fan-out completed at ``at``."""
        for model in self._models:
            model.notified_at = at
```

In `student_recipients`, replace the docstring paragraph "**A row that is not yet published has no recipients yet.** ..." (lines 426-433) with:

```
        **A row that is not yet published has no recipients yet.** Returning
        its future audience here would notify students about something
        :meth:`list_for_student` still hides from them — a push telling you to
        go and read a post that is not there. A scheduled row is left
        unstamped at create time and claimed by
        :func:`lemely.web.scheduled_notifications.publish_due_announcements`
        once ``publish_at`` has passed (push-delivery spec §1); this module
        used to say such a row was "never notified about at all", which was
        true only while there was no sweeper.
```

and replace the body lines 439-451 with:

```python
        if not self.is_due(row):
            return []
```

Then add, immediately before `student_recipients` (before line 404):

```python
    def is_due(self, row: AnnouncementRow) -> bool:
        """Whether ``row`` is published as of this service's clock.

        ``publish_at`` reaches this method from two places: a DB read of a
        ``timestamptz`` column (always aware) and, on the create path, whatever
        the router parsed out of the request, where an ISO string with no
        offset is naive. Comparing the two shapes raises ``TypeError``, and the
        create path runs *outside* ``notify_safely`` — so an unnormalised naive
        value would 500 an announcement that was already written. Naive means
        UTC here, as everywhere else. ``publish_at`` is an absolute instant,
        never a civil time, so per-user zones (spec §3) do not touch this.
        """
        publish_at = row.publish_at
        if publish_at is None:
            return True
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=UTC)
        return publish_at <= self._now()

    def mark_notified(
        self, announcement_ids: Sequence[uuid.UUID], *, now: datetime | None = None
    ) -> int:
        """Stamp ``notified_at`` on rows whose fan-out just completed. Returns how many.

        The composer's half of spec §1: called by the router right after an
        immediate fan-out. Only unstamped rows are touched, so a repeat is a
        no-op rather than a moved timestamp.
        """
        if not announcement_ids:
            return 0
        moment = now if now is not None else self._now()
        with self._sessionmaker() as session, session.begin():
            result = session.execute(
                sa.update(Announcement)
                .where(Announcement.id.in_(list(announcement_ids)), Announcement.notified_at.is_(None))
                .values(notified_at=moment)
            )
            return int(getattr(result, "rowcount", 0) or 0)

    @contextmanager
    def claim_due(
        self, *, now: datetime | None = None, limit: int = DEFAULT_CLAIM_LIMIT
    ) -> Iterator[DueClaim]:
        """Lock up to ``limit`` due, unstamped rows for the duration of the block.

        ``WHERE notified_at IS NULL AND publish_at IS NOT NULL AND publish_at
        <= now``, ``FOR UPDATE SKIP LOCKED``. ``SKIP LOCKED`` is what makes two
        replicas safe without a lock table: a second sweeper sees the rows the
        first is holding as simply absent. ``publish_at IS NULL`` rows are the
        composer's to notify at create time and are never claimed here.

        The transaction stays open across the caller's fan-out on purpose —
        that is what keeps a concurrent pass off these rows — and commits the
        stamp :meth:`DueClaim.stamp` wrote when the block exits normally. An
        exception in the block rolls everything back, leaving the rows
        unstamped for the next pass (spec §1, "stamping after the send").
        """
        moment = now if now is not None else self._now()
        with self._sessionmaker() as session, session.begin():
            models = list(
                session.scalars(
                    select(Announcement)
                    .where(
                        Announcement.notified_at.is_(None),
                        Announcement.publish_at.is_not(None),
                        Announcement.publish_at <= moment,
                    )
                    .order_by(Announcement.publish_at, Announcement.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                ).all()
            )
            yield DueClaim(rows=[_to_row(model) for model in models], _models=models)
```

In `_to_row` (lines 603-613) add `notified_at=row.notified_at,` after `created_at=row.created_at,`. Add `"DEFAULT_CLAIM_LIMIT"` and `"DueClaim"` to `__all__`.

Note `session.begin()` on the claim: the `session.begin()` context manager rolls back when the block raises, so `_Crash` in the test leaves the row unstamped. Passing `_models` positionally into a `slots=True` dataclass with a leading-underscore field is fine; construct it with keywords as shown.

- [ ] **Step 6: The shared module**

Create `lemely/web/scheduled_notifications.py`:

```python
"""The notification jobs a sweeper runs, and the fan-out they share with the composer.

Push-delivery spec §1, §2 and §4. Three jobs live here:

* :func:`publish_due_announcements` — claim announcements whose ``publish_at``
  has passed and notify their audience (§1).
* :func:`warn_streaks` — ``streak_warning`` at 19:00 in each student's own
  zone (§2). Added by a later task.
* :func:`remind_study_plans` — ``study_plan_reminder`` at 08:00 in each
  student's own zone (§2). Added by a later task.

**Idempotency is migration 0018's unique index, not anything in this file.**
Every job passes a ``dedupe_key`` that names the thing being announced (the
announcement id, the student's civil date, the session id), so a re-run —
after a crash, on a second replica, on the next minute's pass — comes back
``outcome=duplicate, push_allowed=False`` from
:meth:`~lemely.db.notification_repo.NotificationService.create` and neither a
duplicate inbox row nor a duplicate push can occur.

:func:`notify_announcement_audience` used to be ``_notify_audience`` in
:mod:`lemely.web.routers.announcements`. It moved here so the composer and
the sweeper share one implementation of "tell the audience"; the router still
calls it for a post that is due the moment it is written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.db.announcement_repo import DEFAULT_CLAIM_LIMIT
from lemely.db.models.enums import NotificationType
from lemely.web.notify import notify_safely

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from lemely.db.announcement_repo import AnnouncementRow, AnnouncementService
    from lemely.db.notification_repo import NotificationService
    from lemely.web.push import NotificationTransport

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Announcements (§1).
# ---------------------------------------------------------------------------


def notify_announcement_audience(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    rows: Sequence[AnnouncementRow],
) -> bool:
    """Tell each row's audience. Returns ``True`` when the loop ran to the end.

    Runs after the rows are already written, exactly like ``award_xp_safely``
    and the ``grade_ready`` seam: the announcement exists and stays existing
    whatever happens here (D5.9 §1). ``notify_safely`` already swallows
    per-recipient failures, but the **audience lookup** is a query of our own
    and sits outside it, so the whole loop is wrapped — a teacher must never
    see a 500 for a post that went out fine, and a sweeper pass must never die
    on one row. ``False`` tells the caller not to stamp ``notified_at``: the
    audience was not fully told, and leaving the row unstamped is what lets
    the next pass try again.

    D5.9 §6 fixes this seam's idempotency on the pair
    ``(announcement_id, user_id)``, and the **column value is the announcement
    id alone** because migration 0018's unique index is already
    ``(user_id, type, dedupe_key)`` — the recipient half of the pair comes
    from the index, not from the string. Concatenating the user id in as well
    was the first cut here and it is *not* wrong, merely redundant; it was
    removed because the comment justifying it ("otherwise the first student
    notified suppresses everyone else") is false, and an inversion proved it
    false: with the suffix dropped, every enrolled student is still notified.
    A comment the code disproves is worse than no comment.

    Fan-out is sequential and unbatched. A class is tens of students and a
    school is hundreds, not millions; a queue is the right answer at a scale
    this build does not have, and inventing one now would add an unproven
    moving part to a path whose failure is already harmless.
    """
    try:
        for row in rows:
            for recipient in service.student_recipients(row):
                notify_safely(
                    notifications,
                    transport,
                    user_id=recipient,
                    type=NotificationType.announcement,
                    title="New announcement",
                    # The title the teacher wrote is the pointer. The body is
                    # deliberately not forwarded: it can be long, and the
                    # notification's job is to send the student to the post,
                    # not to be the post (D5.9 §2).
                    body=row.title,
                    payload={"announcementId": str(row.announcement_id)},
                    dedupe_key=str(row.announcement_id),
                    seam="announcement",
                )
    except Exception:
        log.exception("announcement_fanout_failed", announcement_count=len(rows))
        return False
    return True


def deliver_announcements_now(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    rows: Sequence[AnnouncementRow],
) -> None:
    """The composer's path: fan out the rows that are due now, then stamp them.

    A future-dated row is skipped and left unstamped for
    :func:`publish_due_announcements`; a ``NULL`` or past ``publish_at`` is
    notified immediately, as before. The stamp is wrapped for the same reason
    the fan-out is — nothing here may fail a post that was already written —
    and is skipped when the fan-out did not complete, so the row reads
    honestly as "not yet told" rather than as done.
    """
    due = [row for row in rows if service.is_due(row)]
    if not due:
        return
    if not notify_announcement_audience(service, notifications, transport, due):
        return
    try:
        service.mark_notified([row.announcement_id for row in due])
    except Exception:
        log.exception("announcement_stamp_failed", announcement_count=len(due))


def publish_due_announcements(
    service: AnnouncementService,
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    limit: int = DEFAULT_CLAIM_LIMIT,
) -> int:
    """Claim due rows, fan out, stamp **after** the send. Returns rows stamped.

    Stamping after the send is the deliberate choice (spec §1). A crash between
    the send and the stamp re-runs the row on the next pass, and that re-run
    is harmless: migration 0018's unique index rejects the second insert and
    no second push can occur. Stamping before the send would instead silently
    lose the whole audience's notification on the same crash.
    """
    with service.claim_due(now=now, limit=limit) as claim:
        if not claim.rows:
            return 0
        if not notify_announcement_audience(service, notifications, transport, claim.rows):
            # Leave every claimed row unstamped; the next pass retries them.
            return 0
        claim.stamp(now)
        log.info("announcements_published", count=len(claim.rows))
        return len(claim.rows)


__all__ = [
    "deliver_announcements_now",
    "notify_announcement_audience",
    "publish_due_announcements",
]
```

- [ ] **Step 7: The router uses the shared module**

In `lemely/web/routers/announcements.py`:

Replace the module docstring's last paragraph (lines 14-21) with:

```
**This module used to say it delivered nothing to a student. That is no
longer true and the sentence is corrected rather than left standing.** Phase 5
built both halves MISSION §4 assigned it: the student read surface lives on
:mod:`lemely.web.routers.student_announcements` (P5.5 chunk B), and P5.6 chunk
C2b added the notification seam — ``create`` fans out one ``announcement``
notification per student in each written row's audience, after the rows have
committed and wrapped so that no delivery failure can reach the composing
teacher. The push-delivery spec (§1) moved that fan-out to
:mod:`lemely.web.scheduled_notifications`, shared with the sweeper: a row
whose ``publish_at`` is still ahead is **not** notified here, and is claimed
by the sweeper at that moment instead.
```

Replace line 51 (`from lemely.web.notify import notify_safely`) with:

```python
from lemely.web.scheduled_notifications import deliver_announcements_now
```

Replace line 164 (`_notify_audience(service, notifications, push_transport, rows)`) with:

```python
    deliver_announcements_now(service, notifications, push_transport, rows)
```

Delete `_notify_audience` entirely (lines 168-218). Remove the now-unused `NotificationType` from the `lemely.db.models.enums` import if ruff reports it (keep `Role`), and the `log` / `structlog` lines if nothing else in the module uses them (check with ruff, which pre-commit runs). Remove `Sequence` from the `TYPE_CHECKING` block if it is now unused.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
pytest tests/test_scheduled_announcements.py tests/test_web_notify_seams.py tests/test_web_announcements.py tests/test_announcement_repo.py tests/test_announcement_student_read.py tests/test_web_announcements_student.py -q
```

Expected: PASS. If a test constructs `AnnouncementRow(...)` positionally, the new trailing field has a default and needs nothing.

- [ ] **Step 9: Apply the migration**

```bash
make db-migrate
```

Expected: `0029_user_timezone -> 0030_announcement_notified_at`.

- [ ] **Step 10: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/db/migrations/versions/0030_announcement_notified_at.py lemely/db/models/ops.py lemely/db/announcement_repo.py lemely/web/scheduled_notifications.py lemely/web/routers/announcements.py tests/test_scheduled_announcements.py tests/test_web_notify_seams.py
git commit -S -m "feat(notifications): defer a scheduled announcement's notification to its publish moment

announcements.notified_at (migration 0030) records that the fan-out
completed. The composer notifies and stamps only rows due now; a sweeper
job claims due rows FOR UPDATE SKIP LOCKED, fans out through the same
code, and stamps after the send, so a crash between the two re-runs a row
that migration 0018's unique index makes harmless."
```

---

### Task 6: `[notifications]` settings and the per-zone bucket helpers

**Files:**
- Modify: `lemely/runtime/config.py:540` (add `NotificationsSettings` after `PushSettings`), `:605-629` (`Settings`)
- Modify: `lemely/runtime/example_toml.py:198` (append a `[notifications]` block after `[email]`)
- Regenerate: `lemely.toml.example`
- Modify: `tests/conftest.py:33-40` (add a session fixture beside `_disable_dotenv_file`)
- Modify: `lemely/web/scheduled_notifications.py` (zone helpers section)
- Test: `tests/test_runtime_config.py` (append to `SettingsTests`), `tests/test_scheduled_notifications.py` (new)

**Interfaces:**
- Consumes: `resolve_zone`, `DEFAULT_ZONE` (Task 1).
- Produces: `NotificationsSettings` with `sweeper_enabled: bool = True`, `sweep_poll_seconds: int = 60`, `streak_warning_hour: int = 19`, `study_plan_reminder_hour: int = 8`; `Settings.notifications`. In `lemely.web.scheduled_notifications`: `zones_in_use(session: Session) -> list[str]`, `due_zones(zone_names: Iterable[str], *, now: datetime, hour: int) -> list[tuple[str, date]]`, `zone_bucket(zone_name: str) -> ColumnElement[bool]`, `class ZoneDateMemo` with `is_done(zone: str, day: date) -> bool` and `mark_done(zone: str, day: date) -> None`.

- [ ] **Step 1: Write the failing settings tests**

Append inside `SettingsTests` in `tests/test_runtime_config.py`:

```python
    def test_notifications_defaults_match_the_spec(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertTrue(s.notifications.sweeper_enabled)
        self.assertEqual(s.notifications.sweep_poll_seconds, 60)
        self.assertEqual(s.notifications.streak_warning_hour, 19)
        self.assertEqual(s.notifications.study_plan_reminder_hour, 8)

    def test_notifications_hours_must_be_hours(self) -> None:
        from pydantic import ValidationError

        from lemely.runtime.config import NotificationsSettings

        with self.assertRaises(ValidationError):
            NotificationsSettings(streak_warning_hour=24)
        with self.assertRaises(ValidationError):
            NotificationsSettings(sweep_poll_seconds=0)

    def test_sweeper_can_be_disabled_from_the_environment(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            os.environ["LEMELY_NOTIFICATIONS__SWEEPER_ENABLED"] = "0"
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertFalse(s.notifications.sweeper_enabled)
```

- [ ] **Step 2: Write the failing zone-helper tests**

Create `tests/test_scheduled_notifications.py`:

```python
"""The two daily engagement jobs and the per-zone machinery they share (spec §2, §4).

Work is proportional to the number of *zones in use*, not to the user count:
a pass lists distinct zones, keeps the ones past the trigger hour, and queries
candidates per zone keyed on that zone's civil date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE
from lemely.runtime.config import DatabaseSettings
from lemely.web.scheduled_notifications import ZoneDateMemo, due_zones, zones_in_use

if TYPE_CHECKING:
    from collections.abc import Iterator


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def _seed_user(
    sm: sessionmaker[Session], *, role: Role = Role.student, timezone: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, timezone=timezone))
    return uid


# -- Zones in use -----------------------------------------------------------


def test_zones_in_use_is_distinct_zones_plus_the_default_bucket(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _seed_user(pg_sessionmaker)
    _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_user(pg_sessionmaker, timezone="Asia/Tokyo")

    with pg_sessionmaker() as session:
        assert zones_in_use(session) == ["Africa/Cairo", "America/Los_Angeles", "Asia/Tokyo"]


def test_zones_in_use_always_includes_the_default_even_with_no_users(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pg_sessionmaker() as session:
        assert zones_in_use(session) == [DEFAULT_ZONE.key]


# -- Due zones ---------------------------------------------------------------


def test_due_zones_keeps_the_zones_at_or_past_the_hour_with_their_own_date() -> None:
    """16:30Z on 5 Sept: 19:30 in Cairo (UTC+3, due), 09:30 in Los Angeles
    (UTC-7, not due), 01:30 on the 6th in Tokyo (UTC+9, a new day, not due)."""
    now = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)

    due = due_zones(["Africa/Cairo", "America/Los_Angeles", "Asia/Tokyo"], now=now, hour=19)

    assert due == [("Africa/Cairo", date(2026, 9, 5))]


def test_due_zones_at_the_exact_hour_is_due() -> None:
    now = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)  # 19:00 in Cairo
    assert due_zones(["Africa/Cairo"], now=now, hour=19) == [("Africa/Cairo", date(2026, 9, 5))]


def test_due_zones_falls_back_for_an_unresolvable_stored_name() -> None:
    """A retired zone name is bucketed under its own name but timed on the
    launch zone, so its users are still reached — an hour or two off, never
    never."""
    now = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)
    assert due_zones(["Mars/Base"], now=now, hour=19) == [("Mars/Base", date(2026, 9, 5))]


# -- The per-zone memo -------------------------------------------------------


def test_the_memo_skips_a_zone_until_its_date_changes() -> None:
    memo = ZoneDateMemo()
    assert memo.is_done("Africa/Cairo", date(2026, 9, 5)) is False
    memo.mark_done("Africa/Cairo", date(2026, 9, 5))
    assert memo.is_done("Africa/Cairo", date(2026, 9, 5)) is True
    assert memo.is_done("Africa/Cairo", date(2026, 9, 6)) is False
    assert memo.is_done("Asia/Tokyo", date(2026, 9, 5)) is False
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_runtime_config.py -k notifications tests/test_scheduled_notifications.py -v
```

Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'notifications'` and `ImportError: cannot import name 'ZoneDateMemo'`.

- [ ] **Step 4: The settings section**

In `lemely/runtime/config.py`, after `PushSettings` (after line 539) add:

```python
class NotificationsSettings(BaseModel):
    """The in-process notification sweeper (push-delivery spec §4).

    Overrides via ``lemely.toml`` under the ``[notifications]`` section or
    ``LEMELY_NOTIFICATIONS__*`` env vars.

    ``create_app`` starts one asyncio task that, every ``sweep_poll_seconds``,
    runs the three jobs in :mod:`lemely.web.scheduled_notifications` — due
    announcements, ``streak_warning``, ``study_plan_reminder`` — each wrapped
    so a job that throws is a logged warning and the other two still run.

    **``sweeper_enabled`` is ``False`` under test** (``tests/conftest.py``
    sets the env var for the whole suite) so the suite never races a
    background task; the default is ``True`` because a deployment that forgot
    to enable it would silently deliver nothing on a timer.

    The two hours are civil hours **in each recipient's own zone**
    (``users.timezone``, spec §3), never the server's: a student in Los
    Angeles is warned at their 19:00, not Cairo's.
    """

    model_config = ConfigDict(extra="forbid")
    sweeper_enabled: bool = True
    # How often the sweep loop runs. A minute is fine-grained enough for a
    # 19:00 warning and coarse enough that an idle deployment does almost
    # nothing between ticks (the per-zone memo skips a zone once it is done).
    sweep_poll_seconds: int = Field(default=60, ge=1)
    # ``streak_warning`` fires once the recipient's local time is at or past
    # this hour (spec §2: late enough that "nothing logged today" is true of
    # most of the day, early enough to act on).
    streak_warning_hour: int = Field(default=19, ge=0, le=23)
    # ``study_plan_reminder`` fires once the recipient's local time is at or
    # past this hour, for every incomplete session dated today.
    study_plan_reminder_hour: int = Field(default=8, ge=0, le=23)
```

In `Settings`, after `push: PushSettings = PushSettings()` (line 625) add:

```python
    notifications: NotificationsSettings = NotificationsSettings()
```

- [ ] **Step 5: The example TOML**

In `lemely/runtime/example_toml.py`, after the `[email]` block's last line (`lines.append(f"timeout_seconds = {s.email.timeout_seconds}")`, line 198) add:

```python
    lines.append("")

    lines.append("[notifications]")
    lines.append("# The in-process sweeper that publishes scheduled announcements and sends the")
    lines.append("# two daily engagement notifications (streak_warning at streak_warning_hour,")
    lines.append("# study_plan_reminder at study_plan_reminder_hour) in each recipient's OWN")
    lines.append("# time zone. It runs inside the API process, started by create_app's lifespan;")
    lines.append("# there is no separate worker to deploy. On Cloud Run, timely delivery needs")
    lines.append("# --min-instances=1: at zero instances nothing is running to sweep, and a")
    lines.append("# 19:00 warning may be missed for that day entirely. See docs/deployment.md.")
    lines.append("# The test suite sets LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=0.")
    lines.append(f"sweeper_enabled = {str(s.notifications.sweeper_enabled).lower()}")
    lines.append(f"sweep_poll_seconds = {s.notifications.sweep_poll_seconds}")
    lines.append(f"streak_warning_hour = {s.notifications.streak_warning_hour}")
    lines.append(f"study_plan_reminder_hour = {s.notifications.study_plan_reminder_hour}")
```

Then regenerate:

```bash
python -m lemely.runtime.example_toml
```

Expected: `wrote lemely.toml.example`, and `git diff lemely.toml.example` shows exactly the new block.

- [ ] **Step 6: Disable the sweeper for the whole suite**

In `tests/conftest.py`, after `_disable_dotenv_file` (after line 40) add:

```python
@pytest.fixture(scope="session", autouse=True)
def _disable_notification_sweeper() -> Iterator[None]:
    """Never race a background task under test (push-delivery spec §4).

    ``create_app`` starts the notification sweeper from its lifespan when
    ``settings.notifications.sweeper_enabled`` is true, which is the shipped
    default. The env var wins over every other settings source, so setting it
    once here covers every ``TestClient`` in the suite; the one test that
    needs the sweeper on sets the var back itself and clears the settings
    singleton.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", "0")
    try:
        yield
    finally:
        patch.undo()
```

- [ ] **Step 7: The zone helpers**

In `lemely/web/scheduled_notifications.py`, extend the imports:

```python
from dataclasses import dataclass, field
from datetime import date, datetime

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.db.announcement_repo import DEFAULT_CLAIM_LIMIT
from lemely.db.models.enums import NotificationType
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, resolve_zone
from lemely.web.notify import notify_safely
```

(and remove `datetime` from the `TYPE_CHECKING` block; add `from collections.abc import Iterable, Sequence` there and `from sqlalchemy.orm import Session` and `from sqlalchemy.sql import ColumnElement`). After the logger, before the announcements section, add:

```python
# ---------------------------------------------------------------------------
# Firing a per-user hour without scanning every user (§4).
# ---------------------------------------------------------------------------


def zones_in_use(session: Session) -> list[str]:
    """Every distinct ``users.timezone``, plus the default bucket that covers ``NULL``.

    Tiny by construction — distinct zones, not users — so the two daily jobs
    do work proportional to the number of zones in use.
    """
    stored = session.scalars(
        select(User.timezone).where(User.timezone.is_not(None)).distinct()
    ).all()
    return sorted({DEFAULT_ZONE.key, *(name for name in stored if name is not None)})


def due_zones(zone_names: Iterable[str], *, now: datetime, hour: int) -> list[tuple[str, date]]:
    """The zones whose local civil time is at or past ``hour``, with their civil date.

    The date is that zone's own, which is what every notification from these
    jobs is keyed on (spec §2). A name ``resolve_zone`` cannot resolve keeps
    its own bucket name — that is what ``users.timezone`` says for those users
    — but is timed on the launch zone, so they are reached an hour or two off
    rather than never.
    """
    due: list[tuple[str, date]] = []
    for name in zone_names:
        local = now.astimezone(resolve_zone(name))
        if local.hour >= hour:
            due.append((name, local.date()))
    return due


def zone_bucket(zone_name: str) -> ColumnElement[bool]:
    """``COALESCE(users.timezone, '<default>') = :zone`` — the per-zone candidate filter."""
    return sa.func.coalesce(User.timezone, DEFAULT_ZONE.key) == zone_name


@dataclass(slots=True)
class ZoneDateMemo:
    """The last civil date each zone's job completed. An optimisation, not a guard.

    After 19:00 in a zone the candidate query would otherwise repeat every
    minute until midnight, doing real work only for the unique index to
    discard it. Correctness comes from that index (spec §2), which is also
    what keeps two replicas — each with its own memo — from double-sending.
    A job that throws mid-zone never marks it, so the next pass retries.
    """

    _done: dict[str, date] = field(default_factory=dict)

    def is_done(self, zone: str, day: date) -> bool:
        """Whether this zone's job already completed for ``day``."""
        return self._done.get(zone) == day

    def mark_done(self, zone: str, day: date) -> None:
        """Record that this zone's job completed for ``day``."""
        self._done[zone] = day
```

Add `"ZoneDateMemo"`, `"due_zones"`, `"zone_bucket"`, `"zones_in_use"` to `__all__`.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
pytest tests/test_runtime_config.py tests/test_settings_example_drift.py tests/test_scheduled_notifications.py tests/test_scheduled_announcements.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/runtime/config.py lemely/runtime/example_toml.py lemely.toml.example tests/conftest.py lemely/web/scheduled_notifications.py tests/test_runtime_config.py tests/test_scheduled_notifications.py
git commit -S -m "feat(notifications): [notifications] settings and the per-zone bucket helpers

sweeper_enabled, sweep_poll_seconds and the two trigger hours, with the
suite forcing the sweeper off. zones_in_use lists distinct zones plus the
default bucket, due_zones keeps the ones past the hour with their own civil
date, and ZoneDateMemo is labelled as the optimisation it is: correctness
stays with migration 0018's unique index."
```

---

### Task 7: `warn_streaks`

**Files:**
- Modify: `lemely/web/scheduled_notifications.py` (new section after the zone helpers)
- Modify: `lemely/db/xp_repo.py:38-43` (rule 5 of the module docstring)
- Test: `tests/test_scheduled_notifications.py` (append)

**Interfaces:**
- Consumes: `zones_in_use`, `due_zones`, `zone_bucket`, `ZoneDateMemo` (Task 6); `Streak` model; `notify_safely`.
- Produces: `STREAK_WARNING_TITLE = "Nothing logged today"`; `streak_warning_body(length: int, *, freeze_available: bool) -> str`; `streak_tonight(row: Streak, today: date) -> tuple[int, bool] | None`; `warn_streaks(sessionmaker, notifications, transport, *, now: datetime, hour: int, memo: ZoneDateMemo) -> int`.

One refinement the executor should understand before writing it. The spec's recipient set is `current_length >= 1 AND last_active_on < today`. D5.1 §5 makes streaks resolve **lazily**: a row nobody has read for four days still says `current_length = 5` even though `_resolve_gap` would zero it on the next read. Warning that student "Your 5-day streak ends if today stays empty" would name a streak that has already ended. So the candidate set is the spec's, and each candidate is then judged by the same arithmetic `_resolve_gap` uses: missed full days between `last_active_on` and yesterday, covered by held freezes or not. A streak `_resolve_gap` would reset is skipped; `freezeAvailable` is whether a freeze remains *after* covering the days already missed, which is the "a freeze will cover today" the body promises. This is the existing rule applied, not a new one, and the plan's closing notes flag it for the lead.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduled_notifications.py`:

```python
# -- streak_warning ---------------------------------------------------------

from datetime import timedelta  # noqa: E402

from lemely.db.models.engagement import Streak  # noqa: E402
from lemely.db.models.enums import NotificationType  # noqa: E402
from lemely.db.notification_prefs_repo import NotificationPreferencesService  # noqa: E402
from lemely.db.notification_repo import NotificationService  # noqa: E402
from lemely.web.push import RecordingPushTransport  # noqa: E402
from lemely.web.scheduled_notifications import (  # noqa: E402
    STREAK_WARNING_TITLE,
    streak_tonight,
    streak_warning_body,
    warn_streaks,
)

#: 16:30Z on 5 Sept 2026: 19:30 in Cairo (past 19:00), 09:30 in Los Angeles.
CAIRO_EVENING = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)
#: Ten hours later: 02:30Z on the 6th — 19:30 on the 5th in Los Angeles, and
#: 05:30 on the 6th in Cairo, which is a new date and not yet 19:00.
LA_EVENING = CAIRO_EVENING + timedelta(hours=10)


@pytest.fixture
def notifications(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    return NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


def _seed_streak(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    *,
    length: int,
    last_active_on: date | None,
    freezes: int = 0,
) -> None:
    with sm.begin() as session:
        session.add(
            Streak(
                user_id=user,
                current_length=length,
                longest_length=max(length, 1),
                last_active_on=last_active_on,
                freezes_available=freezes,
            )
        )


def _warn(
    sm: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    *,
    now: datetime,
    memo: ZoneDateMemo | None = None,
) -> int:
    return warn_streaks(
        sm, notifications, transport, now=now, hour=19, memo=memo or ZoneDateMemo()
    )


def test_an_inactive_student_with_a_live_streak_is_warned_once_at_their_19_00(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """One warning at 19:00; a second pass with the same memo skips the zone,
    and a third pass with a fresh memo is discarded by the unique index. Both
    later passes send nothing."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=12, last_active_on=date(2026, 9, 4))
    notifications.subscribe(student, "https://push.example.test/s", "p", "a")
    memo = ZoneDateMemo()

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 1
    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 0
    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0

    rows = notifications.list_for_user(student)
    assert len(rows) == 1
    assert rows[0].type is NotificationType.streak_warning
    assert rows[0].title == STREAK_WARNING_TITLE
    assert rows[0].body == "Your 12-day streak ends if today stays empty."
    assert rows[0].payload == {"streakLength": "12", "freezeAvailable": "false"}
    assert len(transport.endpoints) == 1


def test_a_student_who_earned_xp_today_is_not_warned(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=3, last_active_on=date(2026, 9, 5))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_a_student_with_no_streak_is_not_warned(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=0, last_active_on=date(2026, 9, 1))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_the_freeze_and_no_freeze_bodies_differ_and_name_the_real_length(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """Fires even when a freeze would cover the day, because a freeze is
    consumed silently by ``_resolve_gap`` and a student who is never told
    burns freezes without knowing they had them (spec §2)."""
    frozen = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, frozen, length=7, last_active_on=date(2026, 9, 4), freezes=1)
    bare = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, bare, length=21, last_active_on=date(2026, 9, 4))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 2

    assert notifications.list_for_user(frozen)[0].body == (
        "A freeze will cover today. Your 7-day streak stays."
    )
    assert notifications.list_for_user(frozen)[0].payload["freezeAvailable"] == "true"
    assert notifications.list_for_user(bare)[0].body == (
        "Your 21-day streak ends if today stays empty."
    )


def test_a_streak_resolve_gap_would_already_have_reset_is_not_warned() -> None:
    """Two days missed, no freeze held: the row still says 5, the truth is 0,
    and a warning would name a streak that has already ended."""
    row = Streak(current_length=5, longest_length=5, last_active_on=date(2026, 9, 2), freezes_available=0)
    assert streak_tonight(row, date(2026, 9, 5)) is None


def test_a_freeze_spent_on_a_missed_day_is_not_available_for_tonight() -> None:
    """One day missed, one freeze held: the freeze covers yesterday, nothing
    covers today, so the body is the no-freeze one."""
    row = Streak(current_length=5, longest_length=5, last_active_on=date(2026, 9, 3), freezes_available=1)
    assert streak_tonight(row, date(2026, 9, 5)) == (5, False)
    two = Streak(current_length=5, longest_length=5, last_active_on=date(2026, 9, 3), freezes_available=2)
    assert streak_tonight(two, date(2026, 9, 5)) == (5, True)


def test_a_streak_warning_preference_of_false_suppresses_the_row(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=4, last_active_on=date(2026, 9, 4))
    NotificationPreferencesService(pg_sessionmaker).set(student, streak_warning=False)

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_one_pass_warns_cairo_and_not_los_angeles_then_los_angeles_ten_hours_later(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """Each is keyed on their own civil date, so the second pass — which
    spans a date boundary in Cairo but not in Los Angeles — double-sends to
    neither: Cairo is on a new date before 19:00, Los Angeles gets its one."""
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    for student in (cairo, la):
        _seed_streak(pg_sessionmaker, student, length=2, last_active_on=date(2026, 9, 4))
    memo = ZoneDateMemo()

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert notifications.list_for_user(la) == []

    assert _warn(pg_sessionmaker, notifications, transport, now=LA_EVENING, memo=memo) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert len(notifications.list_for_user(la)) == 1


def test_a_student_with_no_zone_is_warned_on_the_launch_zone(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_streak(pg_sessionmaker, student, length=1, last_active_on=date(2026, 9, 4))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_scheduled_notifications.py -k "streak or warn" -v
```

Expected: FAIL at import — `cannot import name 'warn_streaks'`.

- [ ] **Step 3: Write the job**

In `lemely/web/scheduled_notifications.py`, add `from lemely.db.models.engagement import Streak` to the imports and, under `TYPE_CHECKING`, `from collections.abc import Callable` and `from sqlalchemy.orm import Session, sessionmaker`. After the announcements section add:

```python
# ---------------------------------------------------------------------------
# streak_warning (§2).
# ---------------------------------------------------------------------------

#: Spec §2's copy. ``Profile.tsx`` states the streak is "offered, never used as
#: leverage — no countdown to losing it, no red, no 'don't break it now!'". A
#: 19:00 warning is the exact shape that sentence refuses, so the constraint
#: moved into the wording: each body states the situation once, no exclamation,
#: no countdown, no second sentence stacking urgency on the first.
STREAK_WARNING_TITLE = "Nothing logged today"


def streak_warning_body(length: int, *, freeze_available: bool) -> str:
    """The one sentence a streak warning carries. See :data:`STREAK_WARNING_TITLE`."""
    if freeze_available:
        return f"A freeze will cover today. Your {length}-day streak stays."
    return f"Your {length}-day streak ends if today stays empty."


def streak_tonight(row: Streak, today: date) -> tuple[int, bool] | None:
    """``(length, freeze_available)`` for a streak still alive tonight, else ``None``.

    Streaks resolve **lazily** (D5.1 §5): a row nobody has read in days still
    carries its old ``current_length``, and
    :meth:`~lemely.db.xp_repo.XpService._resolve_gap` is what would zero it on
    the next read. This applies that method's arithmetic without persisting
    it — the days missed between ``last_active_on`` and yesterday are covered
    by held freezes or they are not. A streak the next read would reset gets
    no warning, because "your 5-day streak ends if today stays empty" would
    name a streak that has already ended. ``freeze_available`` is whether a
    freeze remains *after* covering those days: the one that would cover
    today, which is what the body promises.
    """
    if row.current_length < 1 or row.last_active_on is None:
        return None
    yesterday = today - timedelta(days=1)
    missed = max(0, (yesterday - row.last_active_on).days)
    if missed > row.freezes_available:
        return None
    return row.current_length, row.freezes_available - missed >= 1


def warn_streaks(
    sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    hour: int,
    memo: ZoneDateMemo,
) -> int:
    """Send ``streak_warning`` to every student whose day is past ``hour`` with nothing logged.

    Per due zone (§4): candidates are ``streaks`` rows in that zone's bucket
    with ``current_length >= 1`` and ``last_active_on < today``, where
    ``today`` is that zone's own civil date. Streaks belong to students by
    construction — XP is only ever awarded to one — so no role filter is
    needed. The key is that date, one per student per their own day; the
    unique index makes every later pass that day a ``duplicate``. Returns how
    many rows were created.

    Fires even when a freeze would cover the day, and says so — the kinder
    message is the one that tells a student a freeze is being spent (§2).
    """
    created = 0
    with sessionmaker() as session:
        for zone_name, today in due_zones(zones_in_use(session), now=now, hour=hour):
            if memo.is_done(zone_name, today):
                continue
            candidates = session.scalars(
                select(Streak)
                .join(User, User.id == Streak.user_id)
                .where(
                    zone_bucket(zone_name),
                    Streak.current_length >= 1,
                    Streak.last_active_on.is_not(None),
                    Streak.last_active_on < today,
                )
            ).all()
            for row in candidates:
                tonight = streak_tonight(row, today)
                if tonight is None:
                    continue
                length, freeze_available = tonight
                result = notify_safely(
                    notifications,
                    transport,
                    user_id=row.user_id,
                    type=NotificationType.streak_warning,
                    title=STREAK_WARNING_TITLE,
                    body=streak_warning_body(length, freeze_available=freeze_available),
                    payload={
                        "streakLength": str(length),
                        "freezeAvailable": "true" if freeze_available else "false",
                    },
                    dedupe_key=today.isoformat(),
                    seam="streak_warning",
                )
                created += 1 if result.created else 0
            memo.mark_done(zone_name, today)
    if created:
        log.info("streak_warnings_sent", count=created)
    return created
```

Add `from datetime import date, datetime, timedelta` (replace the earlier `date, datetime` import). Add `"STREAK_WARNING_TITLE"`, `"streak_tonight"`, `"streak_warning_body"`, `"warn_streaks"` to `__all__`.

- [ ] **Step 4: Correct rule 5 in `xp_repo`'s docstring**

In `lemely/db/xp_repo.py`, replace rule 5 (lines 38-43) with:

```
5. **Streaks resolve lazily, on both read and award** (D5.1 §5). Nothing
   resolves them on a timer — the notification sweeper
   (:mod:`lemely.web.scheduled_notifications`) reads ``streaks`` rows to
   decide who to warn but never writes them; :meth:`XpService.streak` and
   the streak resolution inside :meth:`XpService.award` both run the same
   ``_resolve_gap`` catch-up logic from whatever ``last_active_on`` was
   persisted last, however long ago that was, and persist the result so a
   later call never re-consumes the same freeze twice.
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_scheduled_notifications.py tests/test_xp_repo.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/web/scheduled_notifications.py lemely/db/xp_repo.py tests/test_scheduled_notifications.py
git commit -S -m "feat(notifications): streak_warning at 19:00 in the student's own zone

Per-zone candidate queries keyed on that zone's civil date; the unique
index discards every later pass that day. A streak _resolve_gap would
already have reset is skipped rather than warned about, and the
freeze-available body says a freeze is being spent instead of hiding it."
```

---

### Task 8: `remind_study_plans`

**Files:**
- Modify: `lemely/web/scheduled_notifications.py` (new section after `warn_streaks`)
- Modify: `lemely/db/notification_repo.py:293-301` (`NotificationService.create` docstring)
- Test: `tests/test_scheduled_notifications.py` (append)

**Interfaces:**
- Consumes: `zones_in_use`, `due_zones`, `zone_bucket`, `ZoneDateMemo` (Task 6); `StudyPlan`, `StudyPlanSession` models.
- Produces: `STUDY_PLAN_REMINDER_TITLE = "Today's study session"`; `study_plan_reminder_body(topic: str, duration_minutes: int) -> str`; `remind_study_plans(sessionmaker, notifications, transport, *, now: datetime, hour: int, memo: ZoneDateMemo) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduled_notifications.py`:

```python
# -- study_plan_reminder ----------------------------------------------------

from lemely.db.models.study_plan import (  # noqa: E402
    StudyPlan,
    StudyPlanActivityType,
    StudyPlanSession,
)
from lemely.web.scheduled_notifications import (  # noqa: E402
    STUDY_PLAN_REMINDER_TITLE,
    remind_study_plans,
)

#: 06:30Z on 5 Sept 2026: 09:30 in Cairo, past 08:00.
CAIRO_MORNING = datetime(2026, 9, 5, 6, 30, tzinfo=UTC)


def _seed_session(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    *,
    subject_code: str = "0625",
    on: date = date(2026, 9, 5),
    topic: str = "Algebraic fractions",
    duration: int = 40,
    completed: bool = False,
    superseded: bool = False,
) -> uuid.UUID:
    with sm.begin() as session:
        plan = StudyPlan(
            user_id=user,
            subject_code=subject_code,
            week_start=date(2026, 8, 31),
            weekly_hours=5.0,
            available=True,
            generated_at=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
            superseded_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC) if superseded else None,
        )
        session.add(plan)
        session.flush()
        row = StudyPlanSession(
            plan_id=plan.id,
            date=on,
            topic=topic,
            activity_type=StudyPlanActivityType.practice,
            duration_minutes=duration,
            focus="Cancel common factors first.",
            completed_at=datetime(2026, 9, 5, 5, 0, tzinfo=UTC) if completed else None,
        )
        session.add(row)
        session.flush()
        return row.id


def _remind(
    sm: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    *,
    now: datetime = CAIRO_MORNING,
    memo: ZoneDateMemo | None = None,
) -> int:
    return remind_study_plans(
        sm, notifications, transport, now=now, hour=8, memo=memo or ZoneDateMemo()
    )


def test_an_incomplete_session_dated_today_is_reminded_once(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    session_id = _seed_session(pg_sessionmaker, student)

    assert _remind(pg_sessionmaker, notifications, transport) == 1
    assert _remind(pg_sessionmaker, notifications, transport) == 0

    rows = notifications.list_for_user(student)
    assert len(rows) == 1
    assert rows[0].type is NotificationType.study_plan_reminder
    assert rows[0].title == STUDY_PLAN_REMINDER_TITLE
    assert rows[0].body == "Algebraic fractions · 40 min"
    assert rows[0].payload == {
        "sessionId": str(session_id),
        "subjectCode": "0625",
        "topic": "Algebraic fractions",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"completed": True},
        {"on": date(2026, 9, 6)},
        {"on": date(2026, 9, 4)},
        {"superseded": True},
    ],
)
def test_completed_other_day_and_superseded_sessions_are_skipped(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    kwargs: dict[str, object],
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_session(pg_sessionmaker, student, **kwargs)  # type: ignore[arg-type]

    assert _remind(pg_sessionmaker, notifications, transport) == 0
    assert notifications.list_for_user(student) == []


def test_three_subjects_with_a_session_each_today_produce_three_notifications(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """The volume is asserted, not left to be discovered in production (spec
    §2): a plan is single-subject, so three subjects are three reminders."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    for code in ("0625", "0580", "0606"):
        _seed_session(pg_sessionmaker, student, subject_code=code)

    assert _remind(pg_sessionmaker, notifications, transport) == 3
    assert sorted(row.payload["subjectCode"] for row in notifications.list_for_user(student)) == [
        "0580",
        "0606",
        "0625",
    ]


def test_a_study_plan_reminder_preference_of_false_suppresses_the_row(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_session(pg_sessionmaker, student)
    NotificationPreferencesService(pg_sessionmaker).set(student, study_plan_reminder=False)

    assert _remind(pg_sessionmaker, notifications, transport) == 0
    assert notifications.list_for_user(student) == []


def test_a_session_is_reminded_on_its_owners_civil_date(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """06:30Z is 09:30 in Cairo and 23:30 on the 4th in Los Angeles: the
    Los Angeles session dated the 5th is not today there yet."""
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_session(pg_sessionmaker, cairo)
    _seed_session(pg_sessionmaker, la)

    assert _remind(pg_sessionmaker, notifications, transport) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert notifications.list_for_user(la) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_scheduled_notifications.py -k "remind or session" -v
```

Expected: FAIL at import — `cannot import name 'remind_study_plans'`.

- [ ] **Step 3: Write the job**

In `lemely/web/scheduled_notifications.py`, add to the imports:

```python
from lemely.db.models.study_plan import StudyPlan as DbStudyPlan
from lemely.db.models.study_plan import StudyPlanSession
```

(the `DbStudyPlan` alias is the same one `lemely/db/study_plan_repo.py` uses, for the reason its module docstring gives). After the streak section add:

```python
# ---------------------------------------------------------------------------
# study_plan_reminder (§2).
# ---------------------------------------------------------------------------

STUDY_PLAN_REMINDER_TITLE = "Today's study session"


def study_plan_reminder_body(topic: str, duration_minutes: int) -> str:
    """A pointer to the session, not a summary of it: ``Algebraic fractions · 40 min``."""
    return f"{topic} · {duration_minutes} min"


def remind_study_plans(
    sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: NotificationTransport,
    *,
    now: datetime,
    hour: int,
    memo: ZoneDateMemo,
) -> int:
    """Send ``study_plan_reminder`` for every incomplete session dated today, once ever.

    Per due zone (§4): ``study_plan_sessions`` joined to their plan where the
    plan is active (``superseded_at IS NULL``), ``session.date`` is that zone's
    civil today, and ``completed_at IS NULL``. The key is the **session id**,
    so each scheduled session prompts exactly once, ever — across a day
    boundary, a restart, or a plan regenerated mid-week. Returns rows created.

    Volume, stated rather than discovered later (§2): a plan is
    single-subject, so a student studying three subjects with a session dated
    today receives three notifications at ``hour``. The collapse to one per
    day is a one-line change of shape and is deliberately not made here.
    """
    created = 0
    with sessionmaker() as session:
        for zone_name, today in due_zones(zones_in_use(session), now=now, hour=hour):
            if memo.is_done(zone_name, today):
                continue
            candidates = session.execute(
                select(StudyPlanSession, DbStudyPlan.user_id, DbStudyPlan.subject_code)
                .join(DbStudyPlan, DbStudyPlan.id == StudyPlanSession.plan_id)
                .join(User, User.id == DbStudyPlan.user_id)
                .where(
                    zone_bucket(zone_name),
                    DbStudyPlan.superseded_at.is_(None),
                    StudyPlanSession.completed_at.is_(None),
                    StudyPlanSession.date == today,
                )
                .order_by(StudyPlanSession.id)
            ).all()
            for row, user_id, subject_code in candidates:
                result = notify_safely(
                    notifications,
                    transport,
                    user_id=user_id,
                    type=NotificationType.study_plan_reminder,
                    title=STUDY_PLAN_REMINDER_TITLE,
                    body=study_plan_reminder_body(row.topic, row.duration_minutes),
                    payload={
                        "sessionId": str(row.id),
                        "subjectCode": subject_code,
                        "topic": row.topic,
                    },
                    dedupe_key=str(row.id),
                    seam="study_plan_reminder",
                )
                created += 1 if result.created else 0
            memo.mark_done(zone_name, today)
    if created:
        log.info("study_plan_reminders_sent", count=created)
    return created
```

Add `"STUDY_PLAN_REMINDER_TITLE"`, `"remind_study_plans"`, `"study_plan_reminder_body"` to `__all__`.

- [ ] **Step 4: Correct `NotificationService.create`'s docstring**

In `lemely/db/notification_repo.py`, replace the docstring of `create` (lines 293-305) with:

```python
        """Create one inbox row, gated by preferences and idempotent on ``dedupe_key``.

        ``dedupe_key`` is optional and its absence is meaningful, not lazy:
        a notification type may have no natural idempotency key, and such rows
        carry ``NULL`` and are exempt from the partial unique index migration
        0018 creates. This mirrors D5.3's split for XP, where the paper seam
        dedupes and the flashcard seam deliberately does not.

        This docstring used to offer ``study_plan_reminder`` as the example
        of a type with no natural key ("two rows a week apart are two real
        reminders"). The push-delivery spec (§2) gave it one — the session
        id, so each scheduled session prompts exactly once ever — and gave
        ``streak_warning`` one too, the recipient's own civil date. Today all
        five types pass a key; the ``NULL`` path stays for the same reason
        ``_notify_audience`` once corrected its own comment: a docstring the
        code disproves is worse than none.

        Returns:
            A :class:`CreateResult` whose ``push_allowed`` is a separate
            answer from its ``outcome`` — see that class.
        """
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_scheduled_notifications.py tests/test_notification_repo.py tests/test_study_plan_repo.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/web/scheduled_notifications.py lemely/db/notification_repo.py tests/test_scheduled_notifications.py
git commit -S -m "feat(notifications): study_plan_reminder at 08:00 in the student's own zone

Keyed on the session id so each scheduled session prompts once, ever,
across a restart or a regenerated plan. Three subjects are three reminders
and the test says so. NotificationService.create's docstring no longer
offers this type as the example of one with no natural key."
```

---

### Task 9: The sweeper and `create_app`'s lifespan

**Files:**
- Modify: `lemely/web/scheduled_notifications.py` (new section at the end: `run_jobs`, `Sweeper`, `run_sweeper`)
- Modify: `lemely/web/deps.py` (add `get_sweeper` after `get_push_transport`, line 658; `reset_singletons`)
- Modify: `lemely/web/app.py:9-17` (imports), `:49-64` (`create_app`), `:126`
- Modify: `lemely/web/routers/student.py:823-829` (`_alert_teachers_and_parents` docstring, rule 3 paragraph)
- Modify: `docs/deployment.md:404-410` (§5.2), `:132` (the push row's neighbour: add a `[notifications]` row)
- Test: `tests/test_scheduled_notifications.py` (append), `tests/test_web_app.py` (append)

**Interfaces:**
- Consumes: `publish_due_announcements` (Task 5), `warn_streaks` (Task 7), `remind_study_plans` (Task 8), `NotificationsSettings` (Task 6).
- Produces: `run_jobs(jobs: Sequence[tuple[str, Callable[[], int]]]) -> dict[str, int | None]`; `@dataclass class Sweeper` with fields `sessionmaker`, `announcements`, `notifications`, `transport`, `settings: NotificationsSettings`, `now: Callable[[], datetime]`, `streak_memo`, `plan_memo` and method `sweep_once() -> dict[str, int | None]`; `async def run_sweeper(sweeper: Sweeper, *, poll_seconds: float, stop: asyncio.Event) -> None`; `deps.get_sweeper() -> Sweeper`.

- [ ] **Step 1: Write the failing job-isolation tests**

Append to `tests/test_scheduled_notifications.py`:

```python
# -- The sweeper (§4) ---------------------------------------------------------

import asyncio  # noqa: E402

from lemely.web.scheduled_notifications import Sweeper, run_jobs, run_sweeper  # noqa: E402


def test_a_job_that_throws_is_a_logged_warning_and_the_others_still_run() -> None:
    ran: list[str] = []

    def ok_one() -> int:
        ran.append("one")
        return 1

    def boom() -> int:
        raise RuntimeError("database went away")

    def ok_two() -> int:
        ran.append("two")
        return 2

    results = run_jobs([("one", ok_one), ("boom", boom), ("two", ok_two)])

    assert ran == ["one", "two"]
    assert results == {"one": 1, "boom": None, "two": 2}


def test_the_sweeper_loop_sweeps_immediately_and_stops_when_asked() -> None:
    """The loop must not wait a full poll interval before its first pass — a
    freshly started instance on Cloud Run has to sweep now — and must exit
    promptly on ``stop`` rather than sleeping out the interval."""
    sweeps: list[int] = []

    class _Fake:
        def sweep_once(self) -> dict[str, int | None]:
            sweeps.append(len(sweeps))
            return {}

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(run_sweeper(_Fake(), poll_seconds=60, stop=stop))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        assert sweeps == [0]
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())


def test_a_sweeper_pass_runs_all_three_jobs_against_an_empty_database(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    from lemely.db.announcement_repo import AnnouncementService
    from lemely.db.class_repo import ClassService
    from lemely.runtime.config import NotificationsSettings

    sweeper = Sweeper(
        sessionmaker=pg_sessionmaker,
        announcements=AnnouncementService(pg_sessionmaker, ClassService(pg_sessionmaker)),
        notifications=notifications,
        transport=transport,
        settings=NotificationsSettings(),
        now=lambda: CAIRO_EVENING,
    )

    assert sweeper.sweep_once() == {
        "publish_due_announcements": 0,
        "warn_streaks": 0,
        "remind_study_plans": 0,
    }
```

- [ ] **Step 2: Write the failing lifespan tests**

Append to `tests/test_web_app.py`:

```python
# -- The notification sweeper's lifespan (push-delivery spec §4) ---------------


@pytest.fixture
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the settings singleton around a test that changes the env."""
    from lemely.web import deps

    deps.reset_singletons()
    try:
        yield
    finally:
        deps.reset_singletons()


def _capture_sweeper(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stand in for ``run_sweeper`` and record how the lifespan drove it."""
    from lemely.web import app as app_module

    seen: dict[str, object] = {"started": 0, "poll_seconds": None, "stopped": False}

    async def fake_run_sweeper(sweeper: object, *, poll_seconds: float, stop: asyncio.Event) -> None:
        seen["started"] = int(seen["started"]) + 1  # type: ignore[call-overload]
        seen["poll_seconds"] = poll_seconds
        await stop.wait()
        seen["stopped"] = True

    monkeypatch.setattr(app_module, "run_sweeper", fake_run_sweeper)
    return seen


@pytest.mark.usefixtures("_fresh_settings")
def test_the_sweeper_is_not_started_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite-wide default (``tests/conftest.py``): no background task races a test."""
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", "0")
    seen = _capture_sweeper(monkeypatch)

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200

    assert seen["started"] == 0


@pytest.mark.usefixtures("_fresh_settings")
def test_the_sweeper_is_started_on_startup_and_stopped_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", "1")
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEP_POLL_SECONDS", "7")
    seen = _capture_sweeper(monkeypatch)

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert seen["started"] == 1
        assert seen["poll_seconds"] == 7
        assert seen["stopped"] is False

    assert seen["stopped"] is True


def test_a_client_without_the_context_manager_never_starts_a_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every pre-existing test builds ``TestClient(create_app())`` without a
    ``with``; Starlette runs the lifespan only inside one, so those tests are
    unaffected whatever the setting says."""
    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", "1")
    seen = _capture_sweeper(monkeypatch)

    TestClient(create_app()).get("/api/health")

    assert seen["started"] == 0
```

Add `import asyncio` and `from collections.abc import Iterator` (under `TYPE_CHECKING` if the file has such a block; otherwise a plain import) to the file's imports.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_scheduled_notifications.py -k "sweep or job" tests/test_web_app.py -k sweeper -v
```

Expected: FAIL — `cannot import name 'Sweeper'` and `AttributeError: module 'lemely.web.app' has no attribute 'run_sweeper'`.

- [ ] **Step 4: The sweeper**

In `lemely/web/scheduled_notifications.py`, add `import asyncio` to the stdlib imports and, under `TYPE_CHECKING`, `from lemely.runtime.config import NotificationsSettings`. Add at the end of the module, before `__all__`:

```python
# ---------------------------------------------------------------------------
# The runner (§4).
# ---------------------------------------------------------------------------


def run_jobs(jobs: Sequence[tuple[str, Callable[[], int]]]) -> dict[str, int | None]:
    """Run each job in turn, each wrapped individually.

    A job that throws is a logged warning and the others still run (§4). The
    returned map carries each job's count, or ``None`` for one that threw, so
    a caller (and a test) can see exactly which did what.
    """
    results: dict[str, int | None] = {}
    for name, job in jobs:
        try:
            results[name] = job()
        except Exception:
            log.warning("sweep_job_failed", job=name, exc_info=True)
            results[name] = None
    return results


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Sweeper:
    """One tick's worth of the three jobs, with the state that persists between ticks.

    The two memos are the per-zone optimisation §4 describes and are the only
    state a sweeper carries; everything else is a collaborator the app already
    has. ``deps.get_sweeper`` builds one per process.
    """

    sessionmaker: sessionmaker[Session]
    announcements: AnnouncementService
    notifications: NotificationService
    transport: NotificationTransport
    settings: NotificationsSettings
    now: Callable[[], datetime] = _utcnow
    streak_memo: ZoneDateMemo = field(default_factory=ZoneDateMemo)
    plan_memo: ZoneDateMemo = field(default_factory=ZoneDateMemo)

    def sweep_once(self) -> dict[str, int | None]:
        """Run announcements, streak warnings and study-plan reminders, once each."""
        moment = self.now()
        return run_jobs(
            [
                (
                    "publish_due_announcements",
                    lambda: publish_due_announcements(
                        self.announcements, self.notifications, self.transport, now=moment
                    ),
                ),
                (
                    "warn_streaks",
                    lambda: warn_streaks(
                        self.sessionmaker,
                        self.notifications,
                        self.transport,
                        now=moment,
                        hour=self.settings.streak_warning_hour,
                        memo=self.streak_memo,
                    ),
                ),
                (
                    "remind_study_plans",
                    lambda: remind_study_plans(
                        self.sessionmaker,
                        self.notifications,
                        self.transport,
                        now=moment,
                        hour=self.settings.study_plan_reminder_hour,
                        memo=self.plan_memo,
                    ),
                ),
            ]
        )


async def run_sweeper(sweeper: Sweeper, *, poll_seconds: float, stop: asyncio.Event) -> None:
    """Sweep now, then every ``poll_seconds``, until ``stop`` is set.

    The first pass is immediate rather than after one interval: on Cloud Run
    a freshly scaled-up instance is the only chance a missed pass gets, and
    making it wait a minute first would lose the 19:00 warning for anyone
    whose zone crossed the trigger while nothing was running (§4's caveat).

    Each pass runs in a worker thread (``asyncio.to_thread``): every job is
    synchronous SQLAlchemy, and running it on the event loop would stall every
    request for the duration of a fan-out.
    """
    while not stop.is_set():
        try:
            await asyncio.to_thread(sweeper.sweep_once)
        except Exception:
            # ``run_jobs`` already wraps each job; this catches the pass
            # itself dying (the clock, a thread failure) so the loop lives.
            log.warning("sweep_pass_failed", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue
```

Add `from datetime import UTC, date, datetime, timedelta` (replace the earlier import). Add `"Sweeper"`, `"run_jobs"`, `"run_sweeper"` to `__all__`.

- [ ] **Step 5: The dependency**

In `lemely/web/deps.py`, add `from lemely.web.scheduled_notifications import Sweeper` to the imports (after the `lemely.web.push` import, line 72) and, after `get_push_transport` (after line 658):

```python
@lru_cache(maxsize=1)
def get_sweeper() -> Sweeper:
    """Return the process-wide notification :class:`Sweeper` (push-delivery spec §4).

    Composed from the same singletons the routers use — announcements,
    notifications, the push transport, the session factory — so a scheduled
    announcement is delivered through exactly the code an immediate one is.
    Built even when ``settings.notifications.sweeper_enabled`` is false;
    ``create_app``'s lifespan decides whether to *run* it. Constructing it
    opens no connection (the engine is lazy).
    """
    settings = get_settings()
    return Sweeper(
        sessionmaker=get_sessionmaker(settings),
        announcements=get_announcement_service(),
        notifications=get_notification_service(),
        transport=get_push_transport(),
        settings=settings.notifications,
    )
```

In `reset_singletons`, after `get_push_transport.cache_clear()` (line 1025) add:

```python
    get_sweeper.cache_clear()
```

- [ ] **Step 6: The lifespan**

In `lemely/web/app.py`, replace the imports block (lines 9-17) with:

```python
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lemely import __version__
from lemely.runtime.budget_notify import register_budget_ntfy
from lemely.runtime.errors import EmptyGradeBoundaryStoreError
from lemely.web.deps import get_settings, get_sweeper
from lemely.web.scheduled_notifications import run_sweeper
```

and after the routers import add:

```python
if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = logging.getLogger(__name__)
```

Insert before `def create_app()` (before line 49):

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the notification sweeper on startup and stop it on shutdown (spec §4).

    One asyncio task for the process. It is not started when
    ``settings.notifications.sweeper_enabled`` is false — the suite sets that
    so no test races a background task — and the settings are read here, at
    startup, rather than at import so a test can change the env and rebuild
    the app. Shutdown sets the stop event and waits for the loop to return:
    a pass in flight finishes (its rows are locked in its own transaction),
    the loop sees the event, and the task exits. Starlette runs this only
    inside ``with TestClient(app)`` / a real server, never for a bare
    ``TestClient(app)``, which is why every pre-existing test is unaffected.
    """
    settings = get_settings()
    stop = asyncio.Event()
    task: asyncio.Task[None] | None = None
    if settings.notifications.sweeper_enabled:
        task = asyncio.create_task(
            run_sweeper(
                get_sweeper(),
                poll_seconds=settings.notifications.sweep_poll_seconds,
                stop=stop,
            ),
            name="notification-sweeper",
        )
        log.info(
            "notification sweeper started (every %ss)", settings.notifications.sweep_poll_seconds
        )
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            await task
```

In `create_app`, add `lifespan=_lifespan,` to the `FastAPI(...)` call (after `version=__version__,`, line 63), and extend the factory's docstring with:

```
    The one piece of process state the factory owns is the notification
    sweeper task, started and stopped by :func:`_lifespan` (push-delivery
    spec §4). Everything else stays a singleton in :mod:`lemely.web.deps`.
```

- [ ] **Step 7: Correct the at-risk docstring**

In `lemely/web/routers/student.py`, replace the rule-3 paragraph of `_alert_teachers_and_parents`'s docstring (lines 823-829) with:

```
    **Rule 3 (≥14 days inactive) cannot fire at this seam and that is not an
    oversight.** A student who has just uploaded a paper is, by definition,
    active. Rule 3 is time-triggered and is the one notification the sweeper
    in :mod:`lemely.web.scheduled_notifications` does **not** run:
    ``streak_warning`` and ``study_plan_reminder`` — which this docstring
    used to list beside it under D5.9 §5's no-scheduler limitation — now do
    fire on a timer, and rule 3 alone is still carried as a limitation rather
    than delivered.
```

- [ ] **Step 8: Documentation**

In `docs/deployment.md`, replace §5.2 (lines 404-410) with:

```markdown
### 5.2 The notification sweeper runs inside the API process, and Cloud Run can scale it to nothing

`create_app` starts one asyncio task (`lemely/web/app.py`, `_lifespan`) that every
`[notifications] sweep_poll_seconds` (60) runs three jobs from
`lemely/web/scheduled_notifications.py`: it publishes announcements whose `publish_at`
has passed, sends `streak_warning` at `streak_warning_hour` (19:00) and
`study_plan_reminder` at `study_plan_reminder_hour` (08:00), each in the recipient's
**own** time zone (`users.timezone`). There is no separate worker to deploy, and no
cron to add. Two replicas are safe — the announcement claim is `FOR UPDATE SKIP LOCKED`
and every notification is deduped by the unique index on `notifications` — but §5.1
still limits you to one for other reasons.

**Timely delivery needs `--min-instances=1`, and `deploy.yml` sets `--min-instances=0`.**
At zero instances the container is not running and no sweep happens; the first request
after scale-up sweeps immediately and delivers late. For an announcement that is
correct-but-late. For a 19:00 streak warning it may mean **no warning at all that day**:
the per-zone memo and the dedupe key are both scoped to the user's civil date, so a
warning that was never sent on the 5th is not sent on the 6th under the 5th's key.
Raise `--min-instances` to 1 in `deploy.yml` when the notifications matter more than the
idle cost; until then this section is the honest statement of what the platform gives.

At-risk rule 3 (≥14 days inactive) is still **not** delivered by anything: the alert
fires on correction, and a student who just uploaded is by definition active.
```

In the variables table, after the `LEMELY_PUSH__VAPID_PUBLIC_KEY ...` row (line 132) add:

```markdown
| `LEMELY_NOTIFICATIONS__SWEEPER_ENABLED` | `true` | Set `false` to run an API instance that never sweeps (a second replica behind a load balancer, or a one-off maintenance container). The test suite sets it. See §5.2 for the Cloud Run caveat; `__SWEEP_POLL_SECONDS` (60), `__STREAK_WARNING_HOUR` (19) and `__STUDY_PLAN_REMINDER_HOUR` (8) are its companions. |
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
pytest tests/test_scheduled_notifications.py tests/test_web_app.py tests/test_web_entrypoint.py tests/test_web_student.py -q
```

Expected: PASS. Then run the whole backend suite once, because the lifespan touches every `TestClient`:

```bash
make test
```

Expected: PASS (Postgres-backed tests may skip if the database is down; start it and re-run so they do not).

- [ ] **Step 10: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/web/scheduled_notifications.py lemely/web/deps.py lemely/web/app.py lemely/web/routers/student.py docs/deployment.md tests/test_scheduled_notifications.py tests/test_web_app.py
git commit -S -m "feat(web): run the three notification jobs from an in-process sweeper

create_app gains a lifespan that starts one asyncio task, off under test,
sweeping immediately and then every sweep_poll_seconds in a worker thread.
Each job is wrapped so one that throws is a logged warning and the other
two still run. docs/deployment.md states the Cloud Run min-instances
caveat rather than implying a guarantee the platform does not give."
```

---

### Task 10: VAPID keys: `lemely push-keygen`, the doctor check, config, deploy, docs

**Files:**
- Create: `lemely/runtime/vapid.py`
- Modify: `lemely/app/cli.py:193-197` (add `push-keygen` after `estimate-cost`), `:516-548` (doctor: push check and advisory set)
- Modify: `lemely/runtime/example_toml.py` (a `[push]` block between `[storage]` and `[auth]`, after line 141)
- Regenerate: `lemely.toml.example`
- Modify: `.github/workflows/deploy.yml:304-318` (three env vars and a comment)
- Modify: `docs/deployment.md:132` (the push row: point at the new doc)
- Create: `docs/push-notifications.md`
- Test: `tests/test_vapid_keygen.py` (new), `tests/test_cli_doctor.py` (append to `DoctorTests`)

**Interfaces:**
- Consumes: `VapidPushTransport.authorization_header` (existing), `PushSettings` (existing).
- Produces: `@dataclass(frozen=True) VapidKeyPair(public_key: str, private_key: str)`; `generate_vapid_keypair() -> VapidKeyPair`; `render_push_toml(pair: VapidKeyPair, subject: str) -> str`; CLI `lemely push-keygen [--subject mailto:...]`; doctor check named `push_transport` (advisory).

`lemely.runtime` must not import `lemely.core`, `lemely.io` or `lemely.app` (import-linter). `vapid.py` imports only `cryptography` and the stdlib, so it is the right home; the CLI imports it lazily inside the command like every other command does.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vapid_keygen.py`:

```python
"""``lemely push-keygen`` (push-delivery spec §5).

The generated pair is checked by **round-tripping** it: a transport built from
the printed keys mints a VAPID header, and the assertion in it verifies against
the printed public key. A keygen test that only checked lengths would prove
the encoding, not that a push service would accept the result.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import jwt
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric import ec

from lemely.app.cli import cli
from lemely.db.notification_repo import PushSubscriptionRow
from lemely.runtime.config import PushSettings
from lemely.runtime.vapid import generate_vapid_keypair, render_push_toml
from lemely.web.push import VapidPushTransport, _b64url_decode, push_audience

ENDPOINT = "https://push.example.test/v1/abc-123"


def _subscription() -> PushSubscriptionRow:
    return PushSubscriptionRow(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        endpoint=ENDPOINT,
        p256dh="p256dh",
        auth="auth",
        user_agent=None,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )


def _verify(public_key_b64: str, header: str) -> dict[str, object]:
    assert header.startswith("vapid t=")
    token = header.removeprefix("vapid t=").split(",", 1)[0]
    raw = _b64url_decode(public_key_b64)
    assert len(raw) == 65 and raw[0] == 0x04, "uncompressed P-256 point"
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    return jwt.decode(token, public, algorithms=["ES256"], audience=push_audience(ENDPOINT))


def test_the_generated_pair_signs_a_header_the_public_key_verifies() -> None:
    pair = generate_vapid_keypair()
    settings = PushSettings(
        vapid_public_key=pair.public_key,
        vapid_private_key=pair.private_key,
        vapid_subject="mailto:ops@example.test",
    )
    transport = VapidPushTransport(settings, now=lambda: datetime(2026, 9, 5, tzinfo=UTC))

    assert transport.available is True
    claims = _verify(pair.public_key, transport.authorization_header(ENDPOINT))
    assert claims["sub"] == "mailto:ops@example.test"
    assert len(_b64url_decode(pair.private_key)) == 32
    transport.close()


def test_two_runs_generate_two_different_pairs() -> None:
    assert generate_vapid_keypair() != generate_vapid_keypair()


def test_the_toml_block_loads_as_push_settings() -> None:
    import tomllib

    pair = generate_vapid_keypair()
    block = render_push_toml(pair, "mailto:ops@example.test")
    data = tomllib.loads(block)
    assert PushSettings(**data["push"]).vapid_public_key == pair.public_key


def test_the_command_prints_a_pair_that_round_trips_and_writes_no_file(tmp_path: object) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["--json", "push-keygen", "--subject", "mailto:ops@example.test"])
        assert result.exit_code == 0, result.output
        import os

        assert os.listdir(".") == [], "push-keygen must write nothing to disk"

    payload = json.loads(result.output)
    settings = PushSettings(
        vapid_public_key=payload["vapid_public_key"],
        vapid_private_key=payload["vapid_private_key"],
        vapid_subject=payload["vapid_subject"],
    )
    transport = VapidPushTransport(settings, now=lambda: datetime(2026, 9, 5, tzinfo=UTC))
    claims = _verify(payload["vapid_public_key"], transport.authorization_header(ENDPOINT))
    assert claims["sub"] == "mailto:ops@example.test"
    assert payload["toml"].startswith("[push]\n")
    transport.close()


def test_the_human_output_carries_a_paste_ready_block() -> None:
    result = CliRunner().invoke(cli, ["push-keygen"])
    assert result.exit_code == 0, result.output
    assert "[push]" in result.output
    assert "vapid_private_key = " in result.output
    assert "Rotating" in result.output
```

Append to `DoctorTests` in `tests/test_cli_doctor.py`:

```python
    def test_doctor_reports_push_unavailable_without_keys_and_does_not_fail_for_it(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    "LEMELY_STORAGE__PROVIDER": "supabase",
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        push = next(c for c in payload["checks"] if c["name"] == "push_transport")
        self.assertFalse(push["ok"])
        self.assertIn("push-keygen", push["detail"])
        self.assertTrue(payload["all_passed"])

    def test_doctor_reports_push_available_with_a_generated_pair(self) -> None:
        from lemely.runtime.vapid import generate_vapid_keypair

        pair = generate_vapid_keypair()
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    "LEMELY_STORAGE__PROVIDER": "supabase",
                    "LEMELY_PUSH__VAPID_PUBLIC_KEY": pair.public_key,
                    "LEMELY_PUSH__VAPID_PRIVATE_KEY": pair.private_key,
                    "LEMELY_PUSH__VAPID_SUBJECT": "mailto:ops@example.test",
                },
            )
        payload = json.loads(result.output)
        push = next(c for c in payload["checks"] if c["name"] == "push_transport")
        self.assertTrue(push["ok"], msg=push)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_vapid_keygen.py tests/test_cli_doctor.py -v
```

Expected: FAIL — `No module named 'lemely.runtime.vapid'`; the doctor tests fail on `StopIteration` (no `push_transport` check).

- [ ] **Step 3: The key generator**

Create `lemely/runtime/vapid.py`:

```python
"""Generate a VAPID (RFC 8292) application-server keypair (push-delivery spec §5).

Lives in ``lemely.runtime`` rather than beside the transport so the CLI can
import it without pulling in the web layer, and so it can never depend on
``lemely.core``/``lemely.io``/``lemely.app`` (import-linter). It writes no
file: the private key never touches disk through this module, so there is no
half-written secret to forget about.

The encodings are the ones every push service and every browser expect, and
the ones :class:`~lemely.web.push.VapidPushTransport` decodes:

* the public key is the **uncompressed** P-256 point, 65 bytes, base64url
  without padding — the value a browser passes to ``pushManager.subscribe``
  as ``applicationServerKey``;
* the private key is the 32-byte scalar, base64url without padding.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@dataclass(frozen=True, slots=True)
class VapidKeyPair:
    """One freshly generated keypair, both halves base64url-encoded."""

    public_key: str
    private_key: str


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_vapid_keypair() -> VapidKeyPair:
    """Generate a P-256 keypair in the shapes RFC 8292 and the browser need."""
    private = ec.generate_private_key(ec.SECP256R1())
    private_raw = private.private_numbers().private_value.to_bytes(32, "big")
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return VapidKeyPair(public_key=_b64url(public_raw), private_key=_b64url(private_raw))


def render_push_toml(pair: VapidKeyPair, subject: str) -> str:
    """A paste-ready ``[push]`` block for ``lemely.toml``.

    ``lemely.toml`` is gitignored, but the private key still does not belong
    on disk where it can be avoided — the deploy pipeline reads it from a
    repository secret. The block is offered because a local test of real push
    needs it somewhere the settings loader reads.
    """
    return (
        "[push]\n"
        f'vapid_public_key = "{pair.public_key}"\n'
        f'vapid_private_key = "{pair.private_key}"\n'
        f'vapid_subject = "{subject}"\n'
    )


__all__ = ["VapidKeyPair", "generate_vapid_keypair", "render_push_toml"]
```

- [ ] **Step 4: The command**

In `lemely/app/cli.py`, after `estimate_cost_cmd` (after line 197) add:

```python
@cli.command("push-keygen")
@click.option(
    "--subject",
    default="mailto:support@lemelyig.com",
    show_default=True,
    help="RFC 8292 contact for whoever operates this server (mailto: or https:).",
)
@click.pass_context
def push_keygen_cmd(ctx: click.Context, subject: str) -> None:
    """Generate a VAPID keypair for web push. Prints; writes nothing.

    A flat command like ``estimate-cost``, not a subgroup. See
    docs/push-notifications.md for where the two halves go and what rotating
    them costs.
    """
    from lemely.runtime.vapid import generate_vapid_keypair, render_push_toml

    pair = generate_vapid_keypair()
    block = render_push_toml(pair, subject)
    payload = {
        "vapid_public_key": pair.public_key,
        "vapid_private_key": pair.private_key,
        "vapid_subject": subject,
        "toml": block,
    }
    if ctx.obj.get("json_output", False):
        _dump_json(payload)
        return
    click.echo("VAPID public key (65-byte uncompressed P-256 point, base64url):")
    click.echo(f"  {pair.public_key}")
    click.echo("VAPID private key (32-byte scalar, base64url) - a secret:")
    click.echo(f"  {pair.private_key}")
    click.echo("")
    click.echo("Paste into lemely.toml (gitignored), or export the three LEMELY_PUSH__* vars:")
    click.echo(block.rstrip("\n"))
    click.echo("")
    click.echo(
        "Rotating this pair invalidates every stored subscription: the public key is "
        "baked into each one, so every browser must re-subscribe. See docs/push-notifications.md."
    )
```

Confirm `_dump_json` is the module-level helper `_print_result` already uses (`grep -n "def _dump_json" lemely/app/cli.py`).

- [ ] **Step 5: The doctor check**

In `lemely/app/cli.py`, inside `doctor_cmd`, immediately before the `try: import gradio` block (before line 516) add:

```python
    # Advisory, like storage: this build ships without VAPID keys and that is
    # a supported state (D5.9 §4) — the inbox keeps working and push simply
    # stays unavailable. Asking the transport rather than counting settings
    # fields keeps this check and the runtime's own answer from disagreeing.
    from lemely.web.push import VapidPushTransport

    push_transport = VapidPushTransport(settings.push)
    try:
        push_available = push_transport.available
    finally:
        push_transport.close()
    record(
        "push_transport",
        push_available,
        (
            f"VAPID keys configured; subject {settings.push.vapid_subject}"
            if push_available
            else "no VAPID keys configured; push unavailable, inbox still works. "
            "Run `lemely push-keygen` and see docs/push-notifications.md"
        ),
    )
```

and change the advisory set (line 548) to:

```python
    advisory_checks = {"gradio_extra_installed", "storage_backend", "push_transport"}
```

Update the comment above it to name three optional subsystems: add "and web push only needs keys once a deployment wants real pushes" after "avatar/upload routes".

- [ ] **Step 6: The example TOML**

In `lemely/runtime/example_toml.py`, after the `[storage]` block's last line (`lines.append('# gcs_project = ...')`, line 140) and its blank line (141), add:

```python
    lines.append("[push]")
    lines.append("# Web push (VAPID, RFC 8292). All three absent is a SUPPORTED state (D5.9 §4):")
    lines.append("# the transport reports itself unavailable, the notification inbox keeps")
    lines.append("# working, and every developer machine and CI run is in that state.")
    lines.append("#")
    lines.append("# Generate a pair with `lemely push-keygen` (prints, writes nothing). The")
    lines.append("# public key is handed to every browser and is not a secret; the private key")
    lines.append("# is. Deployed, both arrive from GitHub Actions (a repository variable and a")
    lines.append("# repository secret) as LEMELY_PUSH__VAPID_PUBLIC_KEY / __VAPID_PRIVATE_KEY.")
    lines.append("# ROTATING THE PAIR INVALIDATES EVERY STORED SUBSCRIPTION - the public key is")
    lines.append("# baked into each one, so every browser must re-subscribe. See")
    lines.append("# docs/push-notifications.md before changing it.")
    lines.append('# vapid_public_key = "BASE64URL-65-BYTE-POINT"')
    lines.append('# vapid_private_key = "BASE64URL-32-BYTE-SCALAR"')
    lines.append('# vapid_subject = "mailto:support@lemelyig.com"')
    lines.append(f"ttl_seconds = {s.push.ttl_seconds}")
    lines.append(f"timeout_seconds = {s.push.timeout_seconds}")
    lines.append("")
```

Regenerate: `python -m lemely.runtime.example_toml`.

- [ ] **Step 7: The deploy workflow**

In `.github/workflows/deploy.yml`, inside the comment block above `env_vars:` (after the object-storage paragraph, line 303) add:

```yaml
          #
          # Web push (VAPID). The public key is handed to every browser and is
          # a repository VARIABLE; the private key is a repository SECRET; the
          # subject is a literal contact. An unset secret renders as the empty
          # string, which `_blank_to_none` maps to None, so this is safe to
          # merge before the pair is registered: the deploy succeeds and push
          # simply stays unavailable, exactly like LEMELY_EMAIL__API_KEY
          # above. Generate the pair with `lemely push-keygen`; rotating it
          # invalidates every stored subscription (docs/push-notifications.md).
```

and after `LEMELY_EMAIL__APP_BASE_URL=...` (line 318) add:

```yaml
            LEMELY_PUSH__VAPID_PUBLIC_KEY=${{ vars.VAPID_PUBLIC_KEY }}
            LEMELY_PUSH__VAPID_PRIVATE_KEY=${{ secrets.VAPID_PRIVATE_KEY }}
            LEMELY_PUSH__VAPID_SUBJECT=mailto:support@lemelyig.com
```

- [ ] **Step 8: The document**

Create `docs/push-notifications.md`:

```markdown
# Web push: keys, placement, verification, rotation

Lemely sends payload-less VAPID web push (RFC 8030/8292): the push wakes the
service worker, and the worker asks an open page for the newest unread inbox
row (`web/src/sw.ts`, `web/src/lib/push/`). The inbox row is the notification;
a push is one delivery of it. So a deployment with no keys loses only the
buzz, never a notification. That is why every field of `[push]` defaults to
unset and why no developer machine or CI run needs one.

## 1. Generate

```
lemely push-keygen
lemely --json push-keygen   # machine-readable
```

Prints a P-256 keypair and a paste-ready `[push]` block. It writes no file: the
private key never touches disk through this tool, so there is no half-written
secret to forget about. `--subject` sets the RFC 8292 contact (`mailto:` or
`https:`); default `mailto:support@lemelyig.com`. Use an address somebody
reads: it is how a push service reaches the operator about abuse.

## 2. Place

| Where | Public key | Private key | Subject |
|---|---|---|---|
| Local `lemely.toml` (gitignored) | `[push] vapid_public_key` | `[push] vapid_private_key` | `[push] vapid_subject` |
| Shell | `LEMELY_PUSH__VAPID_PUBLIC_KEY` | `LEMELY_PUSH__VAPID_PRIVATE_KEY` | `LEMELY_PUSH__VAPID_SUBJECT` |
| Deployed (`.github/workflows/deploy.yml`) | repository **variable** `VAPID_PUBLIC_KEY` | repository **secret** `VAPID_PRIVATE_KEY` | literal in the workflow |

The public key is handed to every browser that subscribes (`GET
/api/notifications/push/config`) and is not a secret; the private key is. An
unset secret renders as the empty string in Actions, which the settings loader
reads as unset, so the workflow can merge before the pair exists.

All three are required. A partial configuration is reported as unavailable,
not attempted and rejected by every push service.

## 3. Verify

```
lemely doctor --no-network
```

The `push_transport` check says whether the transport reports itself available
(all three present). It is advisory: it never fails `doctor`, because absent
keys are a supported state. Then, with the app running and signed in, open
Settings > Notifications: the enable-push control appears only when
`/api/notifications/push/config` answers `available: true`. Enable it, and
trigger a notification (post an announcement to a class you are enrolled in,
or wait for the sweeper). The backend logs `push_send_rejected` /
`push_send_failed` with the push service's status if the pair is wrong.

## 4. Rotate

**Rotating the keypair invalidates every stored subscription.** The public key
is baked into each browser subscription as `applicationServerKey`; a push
signed with a different private key is rejected (`401`/`403`) by the push
service, and the browser will not accept a re-subscribe under a new key without
the page asking again. Every user must re-enable push from Settings >
Notifications. That is the one fact that makes rotation an event rather than a
chore: plan it, tell users, and expect `push_subscriptions` to empty and refill.

Rotation steps:

1. `lemely push-keygen` for the new pair.
2. Update the variable and the secret; redeploy.
3. `DELETE FROM push_subscriptions;` on the deployed database (or let the
   404/410 cleanup in `lemely/web/notify.py` evict them one failed push at a
   time, which is slower and noisier).
4. Users re-enable push. The inbox was never affected.

## 5. What is deliberately unchanged when keys are absent

`{ kind: "unavailable" }` in `web/src/lib/push/pushEnable.ts` and the
`unavailable` state in `web/src/portals/settings/NotificationSettings.tsx` are
the correct runtime answer whenever VAPID keys are absent, which is every
developer machine and every CI run. They stop appearing the moment keys are
configured. Do not remove them.
```

In `docs/deployment.md`, in the push variables row (line 132), replace the "Set it when" cell's text with:

```
To enable web push. All three absent is a **supported** state (D5.9 §4): the transport reports itself unavailable and the notification inbox keeps working. Generate with `lemely push-keygen`; `deploy.yml` reads the public key from the `VAPID_PUBLIC_KEY` repository variable and the private key from the `VAPID_PRIVATE_KEY` secret. Rotating the pair invalidates every stored subscription — see `docs/push-notifications.md`.
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
pytest tests/test_vapid_keygen.py tests/test_cli_doctor.py tests/test_settings_example_drift.py tests/test_push_transport.py tests/test_cli.py -q
lint-imports
```

Expected: PASS, and `lint-imports` reports every contract kept (the CLI's lazy `lemely.web.push` import is not governed by the layers contract, and `lemely.runtime.vapid` imports nothing from the forbidden packages). If `lint-imports` is not on PATH, pre-commit runs it.

- [ ] **Step 10: Commit**

```bash
source .venv/bin/activate && pre-commit run --all-files
git add lemely/runtime/vapid.py lemely/app/cli.py lemely/runtime/example_toml.py lemely.toml.example .github/workflows/deploy.yml docs/push-notifications.md docs/deployment.md tests/test_vapid_keygen.py tests/test_cli_doctor.py
git commit -S -m "feat(cli): lemely push-keygen, a doctor push check, and the VAPID deploy wiring

The pair round-trips through VapidPushTransport.authorization_header and
verifies against the printed public key. The command writes nothing.
deploy.yml reads the public key from a variable and the private key from a
secret, tolerating an unset one exactly as the email key is tolerated.
docs/push-notifications.md says that rotating the pair invalidates every
stored subscription."
```

---

### Task 11: Push destinations in the client bridge; the student inbox stays consistent with it

**Files:**
- Modify: `web/src/lib/push/pushDecision.ts:56-65` (`DEFAULT_PUSH_URL` comment)
- Modify: `web/src/lib/push/pushClientBridge.ts:30-55` (`destinationFor`), `:69-79` (`buildPushReply`), `:89-100` (`answerPushContentRequest`), `:108-133` (`registerPushClientBridge`)
- Modify: `web/src/portals/student/screens/Notifications.tsx:56-83` (`destinationFor`)
- Modify: `web/tests/unit/notifications.test.ts` (the `destinationFor` block and the `buildPushReply` calls)

**Interfaces:**
- Consumes: `getSession` from `@/lib/auth/storage` (existing).
- Produces: `export function destinationFor(notification: Pick<Notification, "type" | "payload">, role: string | undefined): string` in `pushClientBridge.ts`; `buildPushReply(page, role?: string)`; `answerPushContentRequest(fetchInbox, role?: string)`. `Notifications.destinationFor` (student screen) returns `/student/profile` for `streak_warning` and the session path for `study_plan_reminder`.

- [ ] **Step 1: Write the failing tests**

In `web/tests/unit/notifications.test.ts`, replace the import of `buildPushReply` with:

```ts
import {
  answerPushContentRequest,
  buildPushReply,
  destinationFor as pushDestinationFor,
} from "@/lib/push/pushClientBridge"
```

Replace the `describe("destinationFor", ...)` block with:

```ts
describe("destinationFor (student inbox)", () => {
  it("links an announcement to the announcements screen", () => {
    expect(destinationFor(notification({ type: "announcement" }))).toBe("/student/announcements")
  })

  it("gives grade_ready NO link, because the only paper route cannot resolve an upload id", () => {
    // `/student/result/:paperId` addresses papers by history *index* and does
    // `int(paper_id)`, so a UUID 404s. A button here would be a dead link that
    // looks like a feature — the exact thing this build treats as worse than an
    // honest absence.
    expect(
      destinationFor(
        notification({ type: "grade_ready", payload: { uploadId: "0d1c8f2e-..." } }),
      ),
    ).toBeNull()
  })

  it("links a streak warning to the profile, where the streak lives", () => {
    expect(destinationFor(notification({ type: "streak_warning" }))).toBe("/student/profile")
  })

  it("links a study plan reminder to that session's page", () => {
    expect(
      destinationFor(
        notification({
          type: "study_plan_reminder",
          payload: { sessionId: "s1", subjectCode: "0625", topic: "Algebraic fractions" },
        }),
      ),
    ).toBe("/student/plan/0625/session/s1")
  })

  it("gives a study plan reminder with no ids no link rather than a broken one", () => {
    expect(destinationFor(notification({ type: "study_plan_reminder", payload: {} }))).toBeNull()
  })

  it("gives at_risk_alert no link here, because a student never receives one", () => {
    expect(destinationFor(notification({ type: "at_risk_alert" }))).toBeNull()
  })
})

describe("pushDestinationFor (the worker's click target)", () => {
  it("routes all five types, plus the fallback", () => {
    expect(pushDestinationFor({ type: "announcement", payload: {} }, "student")).toBe(
      "/student/announcements",
    )
    expect(pushDestinationFor({ type: "streak_warning", payload: {} }, "student")).toBe(
      "/student/profile",
    )
    expect(
      pushDestinationFor(
        { type: "study_plan_reminder", payload: { sessionId: "s1", subjectCode: "0625" } },
        "student",
      ),
    ).toBe("/student/plan/0625/session/s1")
    // grade_ready keeps its deliberate lack of a specific destination.
    expect(pushDestinationFor({ type: "grade_ready", payload: { uploadId: "u" } }, "student")).toBe("/")
    expect(pushDestinationFor({ type: "at_risk_alert", payload: {} }, "teacher")).toBe(
      "/teacher/notifications",
    )
    expect(pushDestinationFor({ type: "at_risk_alert", payload: {} }, "school_admin")).toBe(
      "/teacher/notifications",
    )
    expect(pushDestinationFor({ type: "at_risk_alert", payload: {} }, "parent")).toBe(
      "/parent/notifications",
    )
  })

  it("falls back to the root when the viewer's role is unknown or the payload is short", () => {
    // `/` routes by role, so it cannot 404 for whoever received the push.
    expect(pushDestinationFor({ type: "at_risk_alert", payload: {} }, undefined)).toBe("/")
    expect(pushDestinationFor({ type: "study_plan_reminder", payload: {} }, "student")).toBe("/")
    expect(pushDestinationFor({ type: "weekly_summary", payload: {} }, "student")).toBe("/")
  })

  it("encodes a subject code rather than splicing it raw into a path", () => {
    expect(
      pushDestinationFor(
        { type: "study_plan_reminder", payload: { sessionId: "s1", subjectCode: "a/b" } },
        "student",
      ),
    ).toBe("/student/plan/a%2Fb/session/s1")
  })
})
```

In the existing `buildPushReply` tests, wherever a reply's `url` is asserted for an `at_risk_alert` row, pass a role: `buildPushReply(page, "teacher")` and expect `/teacher/notifications`. Existing calls with announcement rows need no change (`role` is optional). Add one test to that block:

```ts
  it("routes an at-risk alert to the viewer's own inbox when a role is given", () => {
    const page: NotificationsPage = {
      notifications: [notification({ type: "at_risk_alert", payload: { studentId: "s" } })],
    }
    expect(buildPushReply(page, "parent")?.url).toBe("/parent/notifications")
    expect(buildPushReply(page)?.url).toBe("/")
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npx vitest run tests/unit/notifications.test.ts
```

Expected: FAIL — `pushDestinationFor` is not exported; the streak/study-plan expectations on the student `destinationFor` return `null`.

- [ ] **Step 3: The bridge**

In `web/src/lib/push/pushClientBridge.ts`, add to the imports:

```ts
import { getSession } from "@/lib/auth/storage"
import type { Notification, NotificationsPage } from "@/lib/notificationTypes"
import { DEFAULT_PUSH_URL, PUSH_CONTENT_REPLY, PUSH_CONTENT_REQUEST } from "@/lib/push/pushDecision"
```

(replacing the two existing import lines). Replace `destinationFor` and its comment (lines 30-55) with:

```ts
/**
 * Where a push of a given type sends the reader.
 *
 * Four of the five types have a specific screen. `grade_ready` deliberately
 * does not: its payload carries the upload's UUID, and the only per-paper
 * route (`/student/result/:paperId`) addresses papers by **history index**
 * and 404s on a UUID (`routers/student.py:487`). Linking it would ship a
 * guaranteed dead link, so it keeps `DEFAULT_PUSH_URL`.
 *
 * `at_risk_alert` is addressed to a **teacher and a parent**, and each has
 * their own inbox (`/teacher/notifications`, `/parent/notifications`), so the
 * viewer's role decides. `school_admin` reads the teacher portal. With no role
 * known the answer is `/`, which routes by role and cannot 404 for whoever
 * received the push. This comment used to say neither portal had an inbox
 * screen; both do now, and the fallback stays for the reason above.
 *
 * Kept consistent with the student `Notifications.destinationFor` so a push
 * and the inbox row it announces land in the same place. The two differ only
 * where they must: the inbox screen returns `null` for "no action" and this
 * returns `DEFAULT_PUSH_URL`, because a click has to go somewhere.
 */
export function destinationFor(
  notification: Pick<Notification, "type" | "payload">,
  role: string | undefined,
): string {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    case "streak_warning":
      return "/student/profile"
    case "study_plan_reminder": {
      const { subjectCode, sessionId } = notification.payload
      if (!subjectCode || !sessionId) return DEFAULT_PUSH_URL
      return `/student/plan/${encodeURIComponent(subjectCode)}/session/${encodeURIComponent(sessionId)}`
    }
    case "at_risk_alert":
      if (role === "teacher" || role === "school_admin") return "/teacher/notifications"
      if (role === "parent") return "/parent/notifications"
      return DEFAULT_PUSH_URL
    default:
      return DEFAULT_PUSH_URL
  }
}
```

Change `buildPushReply`'s signature and body:

```ts
export function buildPushReply(page: NotificationsPage | null, role?: string): PushContentReply | null {
  if (page === null) return null
  const unread = page.notifications.find((notification) => notification.readAt === null)
  if (unread === undefined) return null
  return {
    type: PUSH_CONTENT_REPLY,
    title: unread.title,
    body: unread.body,
    url: destinationFor(unread, role),
  }
}
```

Change `answerPushContentRequest` to take and forward the role:

```ts
export async function answerPushContentRequest(
  fetchInbox: () => Promise<NotificationsPage>,
  role?: string,
): Promise<PushContentReply | null> {
  try {
    return buildPushReply(await fetchInbox(), role)
  } catch {
    return null
  }
}
```

(keep the existing comment inside the `catch`). In `registerPushClientBridge`, change the call to:

```ts
    void answerPushContentRequest(
      () => request<NotificationsPage>("/notifications?unreadOnly=true&limit=1"),
      // The role is read at answer time, not at registration: a page can
      // outlive a sign-out and sign-in as someone else.
      getSession()?.role,
    ).then((reply) => {
```

- [ ] **Step 4: The `DEFAULT_PUSH_URL` comment**

In `web/src/lib/push/pushDecision.ts`, replace the comment above `DEFAULT_PUSH_URL` (lines 56-64) with:

```ts
/**
 * Where a notification with no better destination sends the reader.
 *
 * The app root, not an inbox path, and deliberately so: this value is the
 * fallback for when **no page answered the worker at all**, so the worker does
 * not know who received the push. `/` routes by role, so it is the one
 * destination that cannot 404 for the reader who tapped it. The typed
 * destinations, including the teacher and parent inboxes, live in
 * `pushClientBridge.destinationFor`, which only runs when a page did answer.
 * This comment used to say neither of those portals had an inbox screen;
 * both do now, and the fallback stays for the reason above.
 */
```

- [ ] **Step 5: The student inbox keeps the stated invariant**

In `web/src/portals/student/screens/Notifications.tsx`, replace `destinationFor` and its comment (lines 56-83) with:

```tsx
/**
 * Where a notification's "Open" action goes, or null for no action at all.
 *
 * **`grade_ready` deliberately has no destination — that is a measured
 * constraint, not an oversight.** Its payload carries `uploadId` (the upload's
 * UUID, `routers/student.py:891`), and the only per-paper screen is
 * `/student/result/:paperId`, whose `paperId` is a **history record index**,
 * not an id: `student_result` does `int(paper_id)` and 404s on anything else
 * (`routers/student.py:487`). So an "Open" button here would be a guaranteed
 * 404 dressed up as a link. There is no route that maps an upload id to its
 * result, and inventing one is not this screen's job.
 *
 * `streak_warning` opens the profile, where the streak lives (S-31), and
 * `study_plan_reminder` opens that session's page; both are pointers to a
 * screen that already shows the thing, which is what D5.9 §2 means by "a
 * notification is a pointer". A reminder whose payload lacks its ids renders
 * with no action rather than a link that cannot resolve. `at_risk_alert` is
 * addressed to teachers and parents and never reaches a student's inbox, so
 * it has no destination here.
 *
 * Kept deliberately consistent with `pushClientBridge.destinationFor` so that
 * tapping a push and tapping the same row in this inbox land in the same
 * place. The two differ only where they must: this returns `null` for "no
 * action", the bridge returns the root, because a click has to go somewhere.
 */
export function destinationFor(notification: Notification): string | null {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    case "streak_warning":
      return "/student/profile"
    case "study_plan_reminder": {
      const { subjectCode, sessionId } = notification.payload
      if (!subjectCode || !sessionId) return null
      return `/student/plan/${encodeURIComponent(subjectCode)}/session/${encodeURIComponent(sessionId)}`
    }
    default:
      return null
  }
}
```

Also update the empty-state body in the same file (line 240) so it no longer promises something the screen renders with no action; replace it with:

```tsx
            body="When a paper is marked, a teacher posts an announcement, your streak needs a day logged, or a study session is due, it will appear here."
```

- [ ] **Step 6: Run the tests, typecheck, lint, copy gate**

```bash
npx vitest run tests/unit/notifications.test.ts tests/unit/pushDecision.test.ts && npm run typecheck && npm run lint && npm run check:copy
```

Expected: PASS; typecheck silent; lint and `check:copy` unchanged from their pre-existing findings.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/push/pushDecision.ts web/src/lib/push/pushClientBridge.ts web/src/portals/student/screens/Notifications.tsx web/tests/unit/notifications.test.ts
git commit -S -m "feat(web): route every push type to its screen, by the viewer's role for at-risk alerts

grade_ready keeps its deliberate lack of a destination and / stays the
fallback for when no page answered. The student inbox gains the same two
destinations so the comment saying it is kept consistent with the bridge
stays true."
```

---

### Task 12: Teacher inbox

**Files:**
- Create: `web/src/lib/staffInbox.ts`
- Create: `web/src/portals/teacher/screens/Notifications.tsx`
- Modify: `web/src/portals/teacher/data.ts:25-38` (`NavItem`), `:58-74` (`navItems`)
- Modify: `web/src/portals/teacher/index.tsx:9-20` (icons), `:65-67` (lazy imports), `:97-110` (`NAV_ICON`), `:154-171` (`SidebarNavItem` render), `:629` (route)
- Test: `web/tests/unit/staffInbox.test.ts` (new)

**Interfaces:**
- Consumes: `useNotifications`, `useMarkAllNotificationsRead`, `useMarkNotificationRead`, `useNotificationCounts` (existing); `QueryState`, `ListSkeleton`, `EmptyState`, `Card`, `Chip`, `Button`, `Eyebrow` (existing).
- Produces: `export type StaffRole = "teacher" | "parent"`; `staffDestinationFor(role: StaffRole, n: Pick<Notification, "type" | "payload">): string | null`; `unreadCountOf(page: NotificationsPage): number`; `showMarkAllRead(page: NotificationsPage): boolean`; `isInboxEmpty(page: NotificationsPage): boolean`; `unreadBadgeLabel(counts: NotificationCounts | undefined): string | null`; `STAFF_INBOX_ERROR`, `TEACHER_INBOX_EMPTY`, `PARENT_INBOX_EMPTY`; `staffTypeLabel(type: string): string`; `NavItem.badge?: "unread-notifications"`; route `/teacher/notifications`.

Why a `lib/` module: the runner cannot render a component, so the five states the spec asks vitest to cover are pinned two ways — the pure decisions (empty predicate, unread count, mark-all visibility, destinations) as functions, and the wiring of `QueryState`'s `skeleton`/`error`/`isEmpty`/`empty` slots plus the mark-all hook as a source-text check on both screens, the same way `dataHandling.test.ts` reads a module. Playwright (Task 14) renders the real screens. The student screen is not touched.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/staffInbox.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import {
  PARENT_INBOX_EMPTY,
  STAFF_INBOX_ERROR,
  TEACHER_INBOX_EMPTY,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
  unreadBadgeLabel,
  unreadCountOf,
} from "@/lib/staffInbox"
import type { Notification, NotificationsPage } from "@/lib/notificationTypes"

/*
 * The teacher and parent inboxes (push-delivery spec §6). Only `at_risk_alert`
 * ever reaches these two roles, and the same alert reads differently to each:
 * a teacher sees a student they teach, a parent sees their own child.
 *
 * The runner has no DOM, so the screens' five states are pinned two ways: the
 * decisions as pure functions here, and the wiring of `QueryState`'s slots as
 * a source-text check below. Playwright renders the real screens.
 */

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    notificationId: "n1",
    type: "at_risk_alert",
    title: "Amira may need support",
    body: "Declining trend",
    payload: { studentId: "stu-1", reason: "declining_trend" },
    createdAt: "2026-09-05T09:00:00Z",
    readAt: null,
    ...overrides,
  }
}

const page = (rows: Notification[]): NotificationsPage => ({ notifications: rows })

describe("staffDestinationFor", () => {
  it("sends a teacher to the student's page", () => {
    expect(staffDestinationFor("teacher", notification())).toBe("/teacher/students/stu-1")
  })

  it("sends a parent to the child's page", () => {
    expect(staffDestinationFor("parent", notification())).toBe("/parent/children/stu-1")
  })

  it("has no destination without a studentId, rather than a broken link", () => {
    expect(staffDestinationFor("teacher", notification({ payload: {} }))).toBeNull()
  })

  it("has no destination for a type these roles do not receive", () => {
    expect(staffDestinationFor("parent", notification({ type: "announcement" }))).toBeNull()
  })

  it("encodes the id", () => {
    expect(staffDestinationFor("teacher", notification({ payload: { studentId: "a b" } }))).toBe(
      "/teacher/students/a%20b",
    )
  })
})

describe("the four states", () => {
  it("is empty only with no rows", () => {
    expect(isInboxEmpty(page([]))).toBe(true)
    expect(isInboxEmpty(page([notification()]))).toBe(false)
  })

  it("counts unread rows, not rows", () => {
    expect(unreadCountOf(page([notification(), notification({ readAt: "2026-09-05T10:00:00Z" })]))).toBe(1)
  })

  it("offers mark-all-read only while something is unread", () => {
    expect(showMarkAllRead(page([notification()]))).toBe(true)
    expect(showMarkAllRead(page([notification({ readAt: "2026-09-05T10:00:00Z" })]))).toBe(false)
    expect(showMarkAllRead(page([]))).toBe(false)
  })

  it("words the empty state for each role, and the error state once for both", () => {
    expect(TEACHER_INBOX_EMPTY.body).toContain("a student you teach")
    expect(PARENT_INBOX_EMPTY.body).toContain("your child")
    expect(STAFF_INBOX_ERROR.heading).toBe("Notifications could not be loaded")
  })
})

describe("unreadBadgeLabel", () => {
  it("is absent at zero, pending, or error", () => {
    expect(unreadBadgeLabel(undefined)).toBeNull()
    expect(unreadBadgeLabel({ unread: 0, total: 3, unreadByType: {} })).toBeNull()
  })

  it("shows the count, capped so the sidebar never widens", () => {
    expect(unreadBadgeLabel({ unread: 4, total: 9, unreadByType: {} })).toBe("4")
    expect(unreadBadgeLabel({ unread: 120, total: 120, unreadByType: {} })).toBe("99+")
  })
})

describe("staffTypeLabel", () => {
  it("labels the one type these inboxes receive, and never hides an unknown one", () => {
    expect(staffTypeLabel("at_risk_alert")).toBe("Needs attention")
    expect(staffTypeLabel("weekly_summary")).toBe("weekly_summary")
  })
})

describe("both screens wire the four states and mark-all-read", () => {
  const screens = {
    teacher: "../../src/portals/teacher/screens/Notifications.tsx",
    parent: "../../src/portals/parent/screens/Notifications.tsx",
  }

  it.each(Object.entries(screens))("%s", (_name, relative) => {
    const source = readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8")
    // Loading, error, empty, loaded: the four slots of QueryState.
    expect(source).toMatch(/skeleton=\{<ListSkeleton/)
    expect(source).toMatch(/error=\{STAFF_INBOX_ERROR\}/)
    expect(source).toMatch(/isEmpty=\{isInboxEmpty\}/)
    expect(source).toMatch(/empty=\{<EmptyState/)
    // Mark all as read, gated on there being something unread.
    expect(source).toContain("useMarkAllNotificationsRead()")
    expect(source).toContain("showMarkAllRead(data)")
    // Rows link through the role-aware destination, never a hardcoded path.
    expect(source).toContain("staffDestinationFor(")
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npx vitest run tests/unit/staffInbox.test.ts
```

Expected: FAIL — cannot resolve `@/lib/staffInbox`.

- [ ] **Step 3: The pure module**

Create `web/src/lib/staffInbox.ts`:

```ts
/*
 * What the teacher and parent inboxes decide (push-delivery spec §6).
 *
 * Per-portal screens, not a shared one: only `at_risk_alert` ever reaches
 * these two roles, and the same alert reads differently to each — a teacher
 * sees a student they teach, a parent sees their own child. What the two
 * screens share is this module, not chrome: the decisions the web runner can
 * pin (it has no DOM), so a screen that misroutes a row or hides mark-all
 * fails a test rather than a reader.
 *
 * The student inbox (`portals/student/screens/Notifications.tsx`) is not
 * extracted or refactored into this; it keeps its own `destinationFor`.
 */

import type { Notification, NotificationCounts, NotificationsPage } from "@/lib/notificationTypes"

export type StaffRole = "teacher" | "parent"

/**
 * Where a row's "Open" goes, or null for no action.
 *
 * `payload.studentId` is the server-side relationship the alert was raised
 * from (`_alert_teachers_and_parents`), so linking to it never trusts a
 * caller. A row without one renders with no action rather than a link that
 * cannot resolve. Any other type has no screen for these roles and, in
 * practice, never reaches them.
 */
export function staffDestinationFor(
  role: StaffRole,
  notification: Pick<Notification, "type" | "payload">,
): string | null {
  if (notification.type !== "at_risk_alert") return null
  const studentId = notification.payload.studentId
  if (!studentId) return null
  const id = encodeURIComponent(studentId)
  return role === "teacher" ? `/teacher/students/${id}` : `/parent/children/${id}`
}

export function isInboxEmpty(page: NotificationsPage): boolean {
  return page.notifications.length === 0
}

export function unreadCountOf(page: NotificationsPage): number {
  return page.notifications.filter((n) => n.readAt === null).length
}

/** Mark-all is offered only while it would change something. */
export function showMarkAllRead(page: NotificationsPage): boolean {
  return unreadCountOf(page) > 0
}

/**
 * The nav badge's text, or null for no badge. Null for pending and error too:
 * a badge that flashes "0" or guesses during a load says something the app
 * does not yet know. Capped so a long-neglected inbox cannot widen the nav.
 */
export function unreadBadgeLabel(counts: NotificationCounts | undefined): string | null {
  if (counts === undefined || counts.unread <= 0) return null
  return counts.unread > 99 ? "99+" : String(counts.unread)
}

/** Same rule as the student inbox: an unknown type renders with its raw name
 * rather than hiding the row. */
export function staffTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    at_risk_alert: "Needs attention",
    announcement: "Announcement",
    grade_ready: "Marked",
    streak_warning: "Streak",
    study_plan_reminder: "Study plan",
  }
  return labels[type] ?? type
}

/** One error wording for both: the failure is the same connection problem. */
export const STAFF_INBOX_ERROR = {
  heading: "Notifications could not be loaded",
  body: "This is a connection problem on our side. You may well have notifications waiting, and nothing has been lost.",
}

export const TEACHER_INBOX_EMPTY = {
  heading: "Nothing yet",
  body: "When a student you teach may need support, it will appear here.",
}

export const PARENT_INBOX_EMPTY = {
  heading: "Nothing yet",
  body: "When your child may need support, it will appear here.",
}
```

- [ ] **Step 4: The teacher screen**

Create `web/src/portals/teacher/screens/Notifications.tsx`:

```tsx
import { Link, useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Button } from "@/components/ui/button"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import {
  STAFF_INBOX_ERROR,
  TEACHER_INBOX_EMPTY,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
} from "@/lib/staffInbox"
import { formatAge } from "@/portals/student/screens/Notifications"
import { cn } from "@/lib/utils"

/*
 * The teacher's inbox (push-delivery spec §6). Only `at_risk_alert` reaches a
 * teacher, raised by `_alert_teachers_and_parents` for a student they teach,
 * so a row links to that student's page. The API is the same role-agnostic
 * `/api/notifications` the student inbox reads; `tests/test_web_notifications.py`
 * pins that every role can open its own.
 *
 * A per-portal screen, not a shared one: the same alert reads differently to
 * a teacher and a parent, and the student inbox is deliberately not extracted
 * to serve three audiences. What is shared is the pure module and the
 * components that already exist (`QueryState`, `ListSkeleton`, `EmptyState`).
 * `formatAge` is imported from the student screen rather than copied: it is a
 * pure export with its own tests, and two relative-age rules would drift.
 */

function NotificationRow({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = staffDestinationFor("teacher", notification)

  const open = (): void => {
    if (unread) markRead.mutate(notification.notificationId)
    if (destination !== null) void navigate(destination)
  }

  return (
    <Card className={cn("transition-colors", unread && "border-s-2 border-s-accent")}>
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {/* <h2>: these rows sit directly under the page's <h1>, the same
                outline the student inbox documents. */}
            <h2 className="text-body-lg font-medium text-ink">{notification.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-body-sm text-ink-faint">
              <Chip tone={notification.type === "at_risk_alert" ? "warn" : "neutral"}>
                {staffTypeLabel(notification.type)}
              </Chip>
              <time dateTime={notification.createdAt}>{formatAge(notification.createdAt)}</time>
            </div>
          </div>
          {unread ? (
            <Chip tone="warn" className="flex-none">
              Unread
            </Chip>
          ) : null}
        </div>

        {notification.body !== null ? (
          <p className="max-w-[65ch] text-body-md text-ink-muted">{notification.body}</p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {destination !== null ? (
            <Button size="sm" onClick={open}>
              Open student
            </Button>
          ) : null}
          {unread ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => markRead.mutate(notification.notificationId)}
              disabled={markRead.isPending}
            >
              Mark as read
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  )
}

export function TeacherNotifications() {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()

  return (
    <div className="flex flex-col gap-4">
      {/* Outside QueryState, in every state: a heading is what the page IS. */}
      <div>
        <Eyebrow>Inbox</Eyebrow>
        <h1 className="text-display-md text-ink">Notifications</h1>
      </div>
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={STAFF_INBOX_ERROR}
        isEmpty={isInboxEmpty}
        empty={<EmptyState heading={TEACHER_INBOX_EMPTY.heading} body={TEACHER_INBOX_EMPTY.body} />}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-end gap-3">
              <div className="flex items-center gap-3">
                <Link
                  to="/teacher/settings/notifications"
                  className="text-body-sm text-accent-ink hover:underline"
                >
                  Notification settings
                </Link>
                {showMarkAllRead(data) ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => markAll.mutate()}
                    disabled={markAll.isPending}
                  >
                    Mark all as read
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex flex-col gap-3">
              {data.notifications.map((notification) => (
                <NotificationRow key={notification.notificationId} notification={notification} />
              ))}
            </div>
          </div>
        )}
      </QueryState>
    </div>
  )
}
```

- [ ] **Step 5: The route, the nav entry, the badge**

In `web/src/portals/teacher/data.ts`, add `"notifications"` to the `icon` union (after `"announcements"`, line 37) and, after the `end?: boolean` field of `NavItem` (find it with `grep -n "end?:" web/src/portals/teacher/data.ts`), add:

```ts
  /** A live count rendered beside the label. Only the inbox has one. */
  badge?: "unread-notifications"
```

In `navItems`, after the announcements entry (line 68) add:

```ts
  // The inbox carries its unread count (push-delivery spec §6): at_risk_alert
  // is the one notification a teacher receives, and it is the one that asks
  // for action.
  { to: "/teacher/notifications", label: "Notifications", icon: "notifications", badge: "unread-notifications" },
```

In `web/src/portals/teacher/index.tsx`:

- Add `Bell,` to the `@phosphor-icons/react` import (after `Megaphone,`).
- Add `import { Chip } from "@/components/ui/chip"`, `import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"` and `import { unreadBadgeLabel } from "@/lib/staffInbox"` beside the other `@/lib` imports.
- After the `Announcements` lazy const (line 67) add:

```tsx
const TeacherNotifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.TeacherNotifications })),
)
```

- In `NAV_ICON`, after `announcements: Megaphone,` add `notifications: Bell,`.
- Before `SidebarNavItem` add:

```tsx
/** The inbox's unread count. Renders nothing while pending, on error, or at
 * zero, so the nav never shows a number the app has not established. */
function UnreadNotificationsBadge() {
  const { data } = useNotificationCounts()
  const label = unreadBadgeLabel(data)
  if (label === null) return null
  return (
    <Chip tone="warn" className="flex-none">
      {label}
      <span className="sr-only"> unread</span>
    </Chip>
  )
}
```

- In `SidebarNavItem`'s render, after `<span className="flex-1">{item.label}</span>` (line 169) add:

```tsx
            {item.badge === "unread-notifications" ? <UnreadNotificationsBadge /> : null}
```

- In `teacherRoute.children`, after the announcements route (line 629) add:

```tsx
    { path: "notifications", element: <TeacherNotifications />, handle: { title: "Notifications" } },
```

- [ ] **Step 6: Tests, typecheck, lint, copy gate**

The source-text test reads the parent screen too, which does not exist until Task 13; run only the pure-function blocks for now:

```bash
npx vitest run tests/unit/staffInbox.test.ts -t "staffDestinationFor|four states|unreadBadgeLabel|staffTypeLabel" && npx vitest run tests/unit/navigation.test.ts && npm run typecheck && npm run lint && npm run check:copy
```

Expected: PASS (the `navigation.test.ts` "every nav item is a mounted teacher route" check now sees `/teacher/notifications` in both lists); typecheck silent; lint and `check:copy` unchanged.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/staffInbox.ts web/src/portals/teacher/screens/Notifications.tsx web/src/portals/teacher/data.ts web/src/portals/teacher/index.tsx web/tests/unit/staffInbox.test.ts
git commit -S -m "feat(web): a teacher inbox at /teacher/notifications with an unread badge in the nav

Rows link to the student the at-risk alert names. The decisions live in
lib/staffInbox.ts so the node runner can pin them; the student inbox is
not extracted."
```

---

### Task 13: Parent inbox

**Files:**
- Create: `web/src/portals/parent/screens/Notifications.tsx`
- Modify: `web/src/portals/parent/index.tsx:23-30` (lazy imports), `:207-268` (`Header`), `:347-362` (routes)

**Interfaces:**
- Consumes: `staffInbox.ts` (Task 12), the same hooks and components.
- Produces: route `/parent/notifications`; a header link with the unread count.

- [ ] **Step 1: The parent screen**

Create `web/src/portals/parent/screens/Notifications.tsx`:

```tsx
import { Link, useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Button } from "@/components/ui/button"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import {
  PARENT_INBOX_EMPTY,
  STAFF_INBOX_ERROR,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
} from "@/lib/staffInbox"
import { formatAge } from "@/portals/student/screens/Notifications"
import { cn } from "@/lib/utils"

/*
 * The parent's inbox (push-delivery spec §6). Only `at_risk_alert` reaches a
 * parent, raised by `_alert_teachers_and_parents` for their own child, so a
 * row links to that child's overview. The API is the same role-agnostic
 * `/api/notifications` the other two inboxes read.
 *
 * A per-portal screen, not a shared one: "a student you teach" and "your
 * child" are different sentences about the same row, and P-01's parent has
 * no interest in learning an interface built for someone else. What is
 * shared is the pure module and the components that already exist.
 * `formatAge` is imported from the student screen rather than copied, for the
 * reason the teacher screen gives.
 */

function NotificationRow({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = staffDestinationFor("parent", notification)

  const open = (): void => {
    if (unread) markRead.mutate(notification.notificationId)
    if (destination !== null) void navigate(destination)
  }

  return (
    <Card className={cn("transition-colors", unread && "border-s-2 border-s-accent")}>
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-body-lg font-medium text-ink">{notification.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-body-sm text-ink-faint">
              <Chip tone={notification.type === "at_risk_alert" ? "warn" : "neutral"}>
                {staffTypeLabel(notification.type)}
              </Chip>
              <time dateTime={notification.createdAt}>{formatAge(notification.createdAt)}</time>
            </div>
          </div>
          {unread ? (
            <Chip tone="warn" className="flex-none">
              Unread
            </Chip>
          ) : null}
        </div>

        {notification.body !== null ? (
          <p className="max-w-[65ch] text-body-md text-ink-muted">{notification.body}</p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {destination !== null ? (
            <Button size="sm" onClick={open}>
              See progress
            </Button>
          ) : null}
          {unread ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => markRead.mutate(notification.notificationId)}
              disabled={markRead.isPending}
            >
              Mark as read
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  )
}

export function ParentNotifications() {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Eyebrow>Inbox</Eyebrow>
        <h1 className="text-display-md text-ink">Notifications</h1>
      </div>
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={STAFF_INBOX_ERROR}
        isEmpty={isInboxEmpty}
        empty={<EmptyState heading={PARENT_INBOX_EMPTY.heading} body={PARENT_INBOX_EMPTY.body} />}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-end gap-3">
              <div className="flex items-center gap-3">
                {/* The parent portal has no in-portal settings lane; the
                    top-level one is their only route to it. */}
                <Link to="/settings/notifications" className="text-body-sm text-accent-ink hover:underline">
                  Notification settings
                </Link>
                {showMarkAllRead(data) ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => markAll.mutate()}
                    disabled={markAll.isPending}
                  >
                    Mark all as read
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex flex-col gap-3">
              {data.notifications.map((notification) => (
                <NotificationRow key={notification.notificationId} notification={notification} />
              ))}
            </div>
          </div>
        )}
      </QueryState>
    </div>
  )
}
```

- [ ] **Step 2: The route and the header link**

In `web/src/portals/parent/index.tsx`:

- Add `Bell,` to the `@phosphor-icons/react` import (find it with `grep -n "phosphor-icons" web/src/portals/parent/index.tsx`).
- Add `import { Chip } from "@/components/ui/chip"`, `import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"` and `import { unreadBadgeLabel } from "@/lib/staffInbox"` beside the other `@/` imports.
- After the `Weaknesses` lazy const (line 30) add:

```tsx
const ParentNotifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.ParentNotifications })),
)
```

- Before `Header` (line 207) add:

```tsx
/** The inbox's unread count. Nothing while pending, on error, or at zero. */
function UnreadNotificationsBadge() {
  const { data } = useNotificationCounts()
  const label = unreadBadgeLabel(data)
  if (label === null) return null
  return (
    <Chip tone="warn" className="flex-none">
      {label}
      <span className="sr-only"> unread</span>
    </Chip>
  )
}
```

- In `Header`, immediately before the Settings `<Link to="/settings/devices" ...>` (line 239) add:

```tsx
          {/* The parent's inbox (push-delivery spec §6). at_risk_alert is
              addressed to a parent and until now had no screen to read it
              in; the same icon-at-mobile treatment as its neighbours. */}
          <Link
            to="/parent/notifications"
            aria-label="Notifications"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 pointer-coarse:min-h-11 pointer-coarse:min-w-11 pointer-coarse:justify-center text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            <Bell size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Notifications</span>
            <UnreadNotificationsBadge />
          </Link>
```

- In `parentRoute.children`, after the weaknesses route (line 358) add:

```tsx
    { path: "notifications", element: <ParentNotifications />, handle: { title: "Notifications" } },
```

- [ ] **Step 3: Tests, typecheck, lint, copy gate**

```bash
cd web && npx vitest run tests/unit/staffInbox.test.ts tests/unit/navigation.test.ts tests/unit/notFoundFallback.test.ts && npm run typecheck && npm run lint && npm run check:copy
```

Expected: PASS, including the source-text check over both screens now; typecheck silent; lint and `check:copy` unchanged.

- [ ] **Step 4: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/portals/parent/screens/Notifications.tsx web/src/portals/parent/index.tsx
git commit -S -m "feat(web): a parent inbox at /parent/notifications, linked from the header with its unread count

Rows link to the child the at-risk alert names. Same pure module as the
teacher inbox, its own copy, because the same row reads differently to a
parent."
```

---

### Task 14: Playwright for the two inboxes

**Files:**
- Create: `web/e2e/staff-inbox.spec.ts`

**Interfaces:**
- Consumes: `readSeed`, `injectSession` from `web/e2e/seed.ts` (existing; `seed.teacher` is a `SeedAccount`, `seed.parent` carries `userId` and `accessToken`); the two routes (Tasks 12, 13).
- Produces: nothing further depends on it.

What "404 for others" means here, so the test asserts real behaviour: every portal subtree is wrapped in `RequireAuth`, which sends a signed-in reader with the wrong role to **their own** portal (`web/src/routes.tsx:666-698`, `portalPathForRole`) rather than rendering a 404 page. So the negative case asserts that the other role never sees the inbox heading at that URL and lands on their own portal instead. A signed-out visitor is sent to `/login`. The plan's closing notes flag this reading for the lead.

- [ ] **Step 1: Write the spec**

Create `web/e2e/staff-inbox.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * The teacher and parent inboxes (push-delivery spec §6, §8). Each renders for
 * its own role and is unreachable for the other: `RequireAuth` sends a
 * signed-in reader with the wrong role to their own portal rather than
 * rendering a 404 page, so the negative case asserts that the heading is
 * never shown at that URL and the reader lands on their own portal.
 *
 * The seed creates no notifications, so the state these screens ship in is
 * the empty one — which is exactly the state with the least other content to
 * orient a reader, and the one the heading has to be present in.
 */

test.describe("teacher inbox", () => {
  test("renders for a teacher", async ({ page }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    await injectSession(page, { ...seed.teacher, role: "teacher" })

    await page.goto("/teacher/notifications")

    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible()
    await expect(page.getByText("When a student you teach may need support")).toBeVisible()
    await expect(page.getByRole("link", { name: "Notification settings" })).toHaveAttribute(
      "href",
      "/teacher/settings/notifications",
    )
    expect(errors).toEqual([])
  })

  test("is not rendered for a parent, who lands on their own portal", async ({ page }) => {
    const seed = readSeed()
    await injectSession(page, { ...seed.parent, role: "parent" })

    await page.goto("/teacher/notifications")

    await expect(page).toHaveURL(/\/parent(\/|$)/)
    await expect(page.getByText("When a student you teach may need support")).toHaveCount(0)
  })
})

test.describe("parent inbox", () => {
  test("renders for a parent", async ({ page }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    await injectSession(page, { ...seed.parent, role: "parent" })

    await page.goto("/parent/notifications")

    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible()
    await expect(page.getByText("When your child may need support")).toBeVisible()
    await expect(page.getByRole("link", { name: "Notification settings" })).toHaveAttribute(
      "href",
      "/settings/notifications",
    )
    expect(errors).toEqual([])
  })

  test("is not rendered for a teacher, who lands on their own portal", async ({ page }) => {
    const seed = readSeed()
    await injectSession(page, { ...seed.teacher, role: "teacher" })

    await page.goto("/parent/notifications")

    await expect(page).toHaveURL(/\/teacher(\/|$)/)
    await expect(page.getByText("When your child may need support")).toHaveCount(0)
  })

  test("sends a signed-out visitor to sign in", async ({ page }) => {
    await page.goto("/parent/notifications")
    await expect(page).toHaveURL(/\/login/)
  })
})
```

`watchConsole(page)` returns the `string[]` it keeps appending console errors to (`web/e2e/console-errors.ts:23`), so it is asserted on directly at the end of the test, as `parent-journey.spec.ts` does.

- [ ] **Step 2: Run the suite**

```bash
cd web && npx playwright test e2e/staff-inbox.spec.ts
```

Expected: 5 passed. The Playwright config boots the backend and the seed itself (`web/playwright.config.ts`, `globalSetup`); if it reports the seed JSON missing, run the full suite once (`npm run test:e2e`) so `global-setup.ts` produces it, then re-run the one file.

- [ ] **Step 3: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/e2e/staff-inbox.spec.ts
git commit -S -m "test(web): the teacher and parent inboxes render for their own role only

RequireAuth answers the wrong role with a redirect to its own portal, not a
404 page, and the spec asserts that behaviour rather than a page that does
not exist."
```

---

### Task 15: Copy cleanup; CHANGELOG and DELIVERY appendix

**Files:**
- Modify: `web/src/portals/teacher/screens/Announcements.tsx:49-67` (module doc), `:195-203` (header)
- Modify: `web/src/lib/teacherTypes.ts:37-38`, `:1074-1075`
- Modify: `CHANGELOG.md` (under `## [Unreleased]`)
- Modify: `DELIVERY.md:181-200` (§5.3, append)

**Interfaces:** none.

Explicitly kept, per spec §7: the `unavailable` state in `web/src/portals/settings/NotificationSettings.tsx` and `{ kind: "unavailable" }` in `web/src/lib/push/pushEnable.ts`. Do not touch them. `CHANGELOG.md` and `DELIVERY.md` mentions of the unavailable transport are historical record and are appended to, not rewritten.

- [ ] **Step 1: The teacher announcements screen**

In `web/src/portals/teacher/screens/Announcements.tsx`, replace the module doc comment's last three paragraphs (lines 49-67, from "Two things the spec asks for" to the closing `*/`) with:

```tsx
 * One thing the spec asks for that is honestly absent, per D3.14 §2 — do not
 * stub it:
 * - **No attachment.** There is no attachment column and no storage wiring.
 *   It is omitted entirely rather than rendered as a disabled upload control,
 *   the same treatment T-05's absent integrity signals got.
 *
 * `publishAt` both gates visibility and schedules the notification: a dated
 * announcement is hidden from students until that moment
 * (`AnnouncementService.list_for_student`), and the notification sweeper
 * fans out to the audience at that moment (`lemely/web/scheduled_notifications.py`).
 * An undated one is visible and notified as soon as it is written. This
 * header used to say students could not see announcements and no notification
 * was sent; both stopped being true in Phase 5, and the sentence is corrected
 * rather than left standing.
 *
 * The "how it appears to a student" preview is rendered as exactly what is
 * stored — title, body, audience, timestamp — and captioned as a preview of
 * the record, not of a student's inbox.
 */
```

Replace the header paragraph (lines 197-202) with:

```tsx
        <p className="text-body-md text-ink-muted m-0 mt-1 max-w-[640px] text-pretty">
          Write a note for one or more of your classes. Students see it in their announcements
          list and get a notification. A dated announcement stays hidden and unsent until the
          date you set.
        </p>
```

Three more sentences in the same file say the same false things and are corrected for the same reason (the spec names the header and the module doc; these are the same claim restated further down):

Replace the date field's helper text (lines 347-350):

```tsx
          <span className="text-body-sm text-ink-muted text-pretty">
            Recorded with the announcement. It does <strong>not</strong> schedule anything. There
            is no delivery yet, so nothing will fire at this time.
          </span>
```

with:

```tsx
          <span className="text-body-sm text-ink-muted text-pretty">
            Hidden from students and unsent until this date and time. Leave it empty to post now.
          </span>
```

Replace the preview's JSX comment (lines 375-376):

```tsx
      {/* Preview of the stored record, deliberately not of a student's inbox —
          no student-facing surface exists to preview against. */}
```

with:

```tsx
      {/* Preview of the stored record, deliberately not of the student
          announcements screen: that screen adds its own read state and
          ordering, and a second rendering of it here would drift. */}
```

Replace the preview caption (lines 396-399):

```tsx
          <p className="text-body-sm text-ink-muted mt-1.5 m-0 text-pretty">
            This shows what gets stored. It is not a preview of a student's view, and students have
            no announcements surface yet.
          </p>
```

with:

```tsx
          <p className="text-body-sm text-ink-muted mt-1.5 m-0 text-pretty">
            This shows what gets stored. Students read it in their own announcements list, which
            lays it out differently.
          </p>
```

Leave the `Dated` chip and the "dated ..." line in `AnnouncementRow` (lines 89 and 96-98): both state a fact about the record that is still true.

- [ ] **Step 2: The types comments**

In `web/src/lib/teacherTypes.ts`, replace the sentence at lines 37-38 (`Announcement endpoints remain a later P3.8 chunk's to add.`) with:

```
 * The T-12 announcement family (`AnnouncementCreateRequest`, `Announcement`,
 * `AnnouncementList`) sits at the bottom of this file.
```

Replace the `publishAt` paragraph of the `AnnouncementCreateRequest` doc comment (lines 1074-1075) with:

```
 * `publishAt` is an absolute instant that both **gates visibility** (a dated
 * announcement is hidden from students until then) and **schedules the
 * notification** (the sweeper fans out to the audience at that moment). Null
 * means visible and notified immediately. Word it as exactly that.
```

- [ ] **Step 3: Copy gate, typecheck, unit suite**

```bash
cd web && npm run check:copy && npm run typecheck && npx vitest run tests/unit/announcements.test.ts
```

Expected: `check:copy` unchanged from its pre-existing findings (the new header has no dashes); typecheck silent; the announcements unit test still passes. If `tests/unit/announcements.test.ts` asserts the old header text, update that assertion to the new sentence.

- [ ] **Step 4: CHANGELOG and DELIVERY**

In `CHANGELOG.md`, under `## [Unreleased]`, at the end of the `### Added` section (immediately before the next `###` heading), add:

```markdown
#### Push notifications delivered

- Scheduled announcements are notified at their `publishAt` rather than at
  create time: `announcements.notified_at` records the fan-out, and an
  in-process sweeper claims due rows `FOR UPDATE SKIP LOCKED` and stamps them
  after the send.
- `streak_warning` (19:00) and `study_plan_reminder` (08:00) are sent daily,
  each in the recipient's own time zone; idempotency is the existing unique
  index on `notifications`, not a new table.
- Per-user time zones: `users.timezone`, auto-detected from the device at boot
  and overridable in Profile settings (`PUT /api/me/timezone`). Quiet hours,
  streak days, the XP daily cap and the at-risk day follow it; the leaderboard
  week and the profile week window stay global on purpose.
- `[notifications]` settings (`sweeper_enabled`, `sweep_poll_seconds`, the two
  trigger hours); the sweeper is off under test.
- `lemely push-keygen` generates a VAPID keypair; `lemely doctor` reports
  whether push is available; `deploy.yml` reads the keys from a repository
  variable and secret and tolerates their absence. `docs/push-notifications.md`
  covers generating, placing, verifying and rotating (rotation invalidates
  every stored subscription).
- Teacher and parent inboxes (`/teacher/notifications`, `/parent/notifications`)
  for `at_risk_alert`, with unread counts in the nav; pushes now open the
  screen each type is about.
- The teacher announcements screen no longer says students cannot see
  announcements. *Limited, still:* at-risk rule 3 (≥14 days inactive) is not
  delivered by anything, and on Cloud Run at `--min-instances=0` a sweep only
  happens while an instance is running (`docs/deployment.md` §5.2).
```

In `DELIVERY.md` §5.3, append one bullet after the last one in the list (after "browsers require some notification per push.", line 200):

```markdown
- **Superseded in part by the push-delivery spec** (`docs/superpowers/specs/2026-09-05-push-notifications-delivery-design.md`):
  a sweeper now runs inside the API process and delivers `streak_warning`,
  `study_plan_reminder` and scheduled announcements, each in the recipient's
  own time zone; VAPID keys are generated by `lemely push-keygen` and wired
  through `deploy.yml`. The first bullet above is kept as the record of what
  shipped in Phase 5. What is still true: at-risk rule 3 fires on nothing,
  and no real push has been delivered in any harness on a build machine
  without keys.
```

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/portals/teacher/screens/Announcements.tsx web/src/lib/teacherTypes.ts CHANGELOG.md DELIVERY.md
git commit -S -m "docs(web): stop saying announcements are neither seen nor sent

The teacher composer's header and module comment, and two comments in
teacherTypes.ts, described a phase that has passed. CHANGELOG and DELIVERY
are appended to, not rewritten."
```

---

## Manual verification

After Task 15, before opening the PR. The unit runners cannot cover these; each needs the app running against the local database with `make db-up && make db-migrate`.

- [ ] Start the backend with the sweeper on (the default outside tests): `python -m lemely.web`. Confirm the startup log line `notification sweeper started (every 60s)`. Stop it with Ctrl-C and confirm it exits within a second, not after a full poll interval.
- [ ] As a teacher, post an announcement to a class dated two minutes ahead. Confirm the enrolled student's inbox stays empty, then gains the row within a minute of the date passing, and that `SELECT notified_at FROM announcements` is stamped.
- [ ] As a student, set the time zone in Profile settings to a zone where it is currently after 19:00, with a streak row whose `last_active_on` is yesterday. Within a minute, confirm one `Nothing logged today` row and no second one on the next sweep.
- [ ] Run `lemely push-keygen`, paste the block into `lemely.toml`, restart the backend, confirm `lemely doctor --no-network` reports `push_transport` ok and Settings > Notifications shows the enable-push control instead of the unavailable state. Remove the block afterwards; the unavailable state must return.
- [ ] Sign in as a teacher and as a parent; confirm the nav (teacher) and header (parent) show an unread count once an at-risk alert exists, and that "Open student" / "See progress" lands on the right page.

## Self-review notes

Checked against the spec section by section. §1 (Task 5: schema, create path, the job, stamp-after-send). §2 (Tasks 7 and 8: triggers, recipients, keys, payloads, copy verbatim, the volume statement; Task 8 also carries the `create` docstring correction). §3 (Tasks 1 to 4: what moves and what stays, the leaderboard comment, the seam in `profile`, history not rewritten, schema, `resolve_zone` never raising, the reader, auto-detect and explicit setting, the endpoint on `me`, validation). §4 (Task 6 settings and per-zone machinery incl. the memo labelled as an optimisation; Task 9 lifespan, per-job wrapping, `docs/deployment.md`'s Cloud Run caveat). §5 (Task 10: the flat command, prints and writes nothing, example TOML, the three deploy vars with a tolerated empty secret, the doc with rotation's cost, the doctor check). §6 (Tasks 12 to 14: per-portal screens on the existing hooks, existing chrome only, `destinationFor` for the four types with `grade_ready` and `DEFAULT_PUSH_URL` kept, the corrected comment). §7 (Task 15: the four removals; the two `unavailable` states explicitly kept; CHANGELOG/DELIVERY appended). §8: every pytest bullet has a named test in Tasks 1, 2, 3, 5, 7, 8, 9 or 10; every vitest bullet in Tasks 4, 11 or 12; the Playwright bullet in Task 14.

Type consistency: `UserZoneReader.zone_for/forget/clear` (Task 1) are the names Tasks 2 and 3 call; `DueClaim.rows/stamp` and `claim_due`/`mark_notified`/`is_due` (Task 5) are what Task 9's `Sweeper` reaches through `publish_due_announcements`; `warn_streaks`/`remind_study_plans` keyword signatures (Tasks 7, 8) match `Sweeper.sweep_once` (Task 9); `NotificationsSettings` field names (Task 6) match the example TOML, `deps.get_sweeper` and the lifespan; `TimezoneUpdate`/`TimezoneState` (Task 4) match `TimezoneUpdateDTO`/`TimezoneDTO` (Task 3) field-for-field; `staffDestinationFor`/`isInboxEmpty`/`showMarkAllRead`/`unreadBadgeLabel` (Task 12) are the names both screens and the source-text test use.

Three places this plan goes beyond the spec's letter, each for a stated reason and each flagged to the lead: the `timezone: null` clear body (Task 3), the process-lifetime memo with `forget` (Task 1), and `streak_tonight` skipping a streak `_resolve_gap` would already have reset (Task 7). One place it reads the spec's "404 for others" as the app's actual answer, a redirect (Task 14). One edit outside the spec's list, made to keep a comment the code would otherwise disprove: the student inbox's `destinationFor` gains the two destinations the bridge gains (Task 11).
