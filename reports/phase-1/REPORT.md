# Phase 1 — Database + Auth + Tenancy — Milestone Report

**Status:** ✅ Complete — all acceptance criteria and applicable quality gates pass.
**Branch:** `feature/phase-1-db-auth-tenancy` → merged to `develop`; `develop → main` PR opened (not merged).
**Date:** 2026-08-01.
**Baseline (`develop` @ Phase 0):** 395 passed, 84.56% coverage, no DB/auth.
**After Phase 1:** **548 passed / 2 skipped (live-only) / 12 subtests**, **85.44% coverage** (hermetic), all applicable gates green. Gemini live spend **$0.00**.

---

## 1. What was built (task → outcome)

| # | Task | Outcome |
|---|------|---------|
| P1.1 | Local Supabase stack | `supabase/config.toml` + `seed.sql`; Makefile `db-up/db-down/db-reset/seed`; `docs/database.md`. `DatabaseSettings`/`SupabaseSettings` added. |
| P1.2 | SQLAlchemy 2 + Alembic | `lemely/db/{base,session,seed}.py` + `migrations/env.py`; baseline migration; verified live against local Postgres. |
| P1.3 | Full relational schema | **22 tables** across 8 model modules + `enums.py`; migration `0002_core_schema`. Additive-only guarantee for Phases 2–5 (D1.2); enum `server_default` cast (D1.3) → `alembic check` drift-free. |
| P1.4 | Supabase GoTrue auth + parent OTP | `lemely/auth/` — GoTrue REST client, `SmsProvider` protocol + `MockSmsProvider`, in-memory OTP store, `AuthService` mirroring GoTrue → `public.users`, `/api/auth` router. Backend is sole HS256 token issuer (D1.5). |
| P1.5 | JWT validation middleware | `get_auth_context` = real dependency: `HTTPBearer` + HS256 decode → `AuthContext`; every failure → 401 + `WWW-Authenticate: Bearer`. Anonymous stub removed. |
| P1.6 | RBAC on every route + kill IDORs | `require_role(*roles)` factory (401 then 403). Both IDOR endpoints killed (`studentId` removed from the two DTOs; identity = `auth.user_id`). No super-role (D1.6). |
| P1.8/9 | HistoryStore → Postgres (web) | `DbHistoryStore` (interface-preserving) + `migrate_json_history()` + parity tests; web surface reads/writes Postgres; CLI/Gradio keep JSON store (D1.9, recorded deviation). |
| P1.10 | Seat model | `SeatService`: on-demand seat allocation with `FOR UPDATE` quota lock (TOCTOU-safe), membership-based ownership, revoke frees a slot. `/api/school/seats` gated `school_admin`-only. Personal subscription coexists. |
| P1.11 | Device/session registry | `DeviceRegistry`: max **3** concurrent devices; 4th login evicts oldest by `last_seen_at`. `session_id` claim + sid-gated DB liveness check → evicted session → 401 (D1.11). Migration `0003_device_client_id`. |
| P1.acc | **Acceptance (this report)** | 5-role E2E auth matrix + live seat-invite→login; adversarial security sweep; every route has an authz test; gates green. |

## 2. Acceptance criteria (MISSION §4 / §6)

- ✅ **E2E auth tests for all 5 roles** (`student`, `parent`, `teacher`, `school_admin`, `platform_admin`) — `tests/test_auth_e2e_roles.py`: each role's one allowed route → 200 and every denied route → 403; the no-super-role invariant asserted (platform_admin → 403 on `/api/school/seats`). Parent **OTP E2E**: request → recover code → verify → parent token → `/api/student/overview` → 403 (proves the OTP-minted token flows through RBAC).
- ✅ **Live seat-invite → login** — `tests/test_seat_invite_live.py` (**PASSES against the real local Supabase + GoTrue + Postgres**): a seeded `school_admin` invites a student via `SeatService` → GoTrue account created + mirrored + seat allocated → student logs in → decoded token carries `app_role == "student"`. Cleans up all seeded rows + the GoTrue account.
- ✅ **Adversarial security review finds no unauthenticated / cross-tenant access** — a `reviewer` subagent swept the whole auth surface (`lemely/auth/**`, `web/deps.py`, all four routers, `seat_repo`/`device_repo`/`history_repo`). **No Critical/High auth bypass.** Verified-clean: alg-confusion (HS256 whitelist rejects `alg=none`), session-liveness (evicted `session_id` → 401), signup privilege-escalation (student-only), IDOR on seat-revoke / history keying, token `aud`/`exp` enforcement, role-claim forgery (HS256-signed). Two lower findings fixed (see §3).
- ✅ **Every route has an authz test** — `tests/test_authz_matrix.py`: no-token → 401, wrong-role → 403, IDOR-kill, real-token e2e across student/teacher/school routers (teacher + school routers are router-level gated, so their POSTs are covered by the guard proof).

## 3. Adversarial review — findings addressed (D1.12)

The acceptance sweep produced **no Critical/High auth bypass**. The prior in-progress fix and two review findings were completed this session:

| ID | Sev | Finding | Fix |
|----|-----|---------|-----|
| H2 | High | `POST /api/papers/upload` trusted a caller-supplied `student_id` → cross-tenant write into any student's bucket | **Removed the `student_id` form field**; bucket keyed on server-generated `paper_id` only. Real-student association deferred to the Phase 2/3 class model, gated on verified ownership (D1.12). |
| M1 | Med | Non-UUID `schoolId` / `seat_id` from an authed admin → unhandled `ValueError` → **500** | Typed `InviteStudentRequestDTO.schoolId` and the `{seat_id}` path param as `uuid.UUID` → FastAPI/Pydantic return a clean **422** before the service. Regression tests added. |
| M2 | Med | `GET /api/schemes` emitted hardcoded `"0"` "Pending" / "Your own" stat cards presented as live data (honesty) | Removed both fabricated cards; only computed "Parsed"/"Failed" remain, with a comment explaining they return when the backing data exists (Phase 2/3). |

Findings were verified against the actual code before acting; the review's self-reclassified H1 (teacher router-level guard "phantom") was confirmed a **real, enforced** FastAPI router dependency — not a bypass.

## 4. Test & coverage summary

- **548 passed, 0 failed, 2 skipped, 12 subtests** (baseline 395). The 2 skips are the live-only integration tests (`test_auth_live.py`, `test_seat_invite_live.py`) which **skip cleanly without keys and PASS with the local stack** (both verified green this session against real GoTrue+Postgres).
- **Total coverage 85.44%** hermetic (gate ≥70%; > 84.56% baseline). New auth/DB modules well covered (`schemas_school.py`, `schemas_auth.py` 100%).
- Suite stays hermetic for unattended CI runs; real-DB integration tests run in CI via a `postgres:16` service + `alembic upgrade head` (added commit `35aec2a`).

## 5. Gate evidence (final run)

```
ruff check lemely tests   → All checks passed!
ruff format --check        → 164 files already formatted
mypy lemely                → Success: no issues found in 111 source files
lint-imports               → Contracts: 2 kept, 0 broken.
pytest (hermetic)          → 548 passed, 2 skipped, 12 subtests; Total coverage: 85.44%
pytest (live, keys set)    → test_seat_invite_live + test_auth_live PASS vs real Supabase+GoTrue
web (unchanged since develop) → gates inherited-green from Phase 0 (no frontend touched)
```

## 6. Key decisions (BUILD/DECISIONS.md)

D1.1 (auth id mirror, no cross-schema FK) · D1.2 (additive-only schema conventions) · D1.3 (enum server-default cast) · D1.4 (GoTrue + mock-OTP split) · D1.5 (**backend is sole HS256 token issuer**) · D1.6 (RBAC least-privilege, teacher tenancy deferred) · D1.7 (signup RBAC / OTP cooldown / history-key guard) · D1.8/D1.9 (HistoryStore → Postgres, web only) · D1.10 (seat allocation, locked quota) · D1.11 (device registry, sid-gated liveness) · **D1.12 (teacher-upload cross-tenant-write kill + M1/M2 acceptance fixes)**.

## 7. Screenshots

N/A — Phase 1 is backend/auth/DB only; no UI was changed. Screens begin in Phase 2 (SPA wiring).

## 8. Known limitations / carried forward

- **Teacher per-tenant ownership (own-classes-only) is DEFERRED** to Phase 2/3 (D1.6): teacher routes still read the shared interim `HistoryStore`, so the *role* boundary is enforced (students/parents locked out) but row-level teacher→class ownership lands when routes move to the DB class model. Recorded, not silently incomplete.
- **CLI + Gradio history still use the JSON store** (D1.9); full deletion of `lemely/io/history_store.py` is a tracked non-blocking follow-up (parity already proven).
- **OTP challenge store is in-memory** (single-process dev, D1.4); a multi-worker deploy moves it to Redis/DB.
- **Live auth/seat E2E** require the local Supabase stack + keys; they skip (never fail) in keyless CI — hermetic tests cover the same logic. GoTrue is not yet run in CI.
- Gemini live spend this phase: **$0.00** (all mocked; no live calls).
