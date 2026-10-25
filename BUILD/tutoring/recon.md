# Tutoring marketplace — Phase 0 recon

Base: `develop` @ 314ef8ec, worktree `.claude/worktrees/tutoring-marketplace`, branch `feat/tutoring-marketplace`.
Method: graphify + tokensave + direct reads. The four Explore agents were blocked by the tokensave hook; episodic-memory search was unavailable (no MCP tool in the subagent), so no prior tutor/consent decisions were found. `LEMELY_AUDIT.md` is dated 2026-07-30 and describes a pre-auth, pre-DB repo. Treat it as stale and not a source of open issues.

## Reuse
- **Per-student view:** `teacher_student_detail` (`lemely/web/routers/teacher.py:2381`) builds the T-05 DTO through `_student_detail_dto` (`:2323`). It covers subjects/predictions, attempts, weaknesses, trend, at-risk flags and engagement from `history_store.load(student_id)`. A tutor view swaps only the gate.
- **The gate:** `_visible_students` (`teacher.py:1891`) is the single teacher↔student authorization check (class roster). A tutor gate is a sibling that reads a consent grant.
- **Pure analytics:** `lemely/core/class_analytics.py` has `grade_distribution:199`, `cohort_trend:224`, `rank_topic_weaknesses:130`, `engagement_stats:320`. Also `core/at_risk.py` and `core/history.py`.
- **Notifications:** `NotificationService.create` (`lemely/db/notification_repo.py:292`), enum `NotificationType` (`enums.py:245`), quiet hours in the user's zone.
- **Zone:** `users.timezone` (IANA) and `DEFAULT_ZONE = Africa/Cairo` (`lemely/db/xp_repo.py:78`).
- **Charts:** `docs/COMPONENT_CATALOGUE.md` has C-3 boundary bar, C-8 trend sparkline. No ordinal-distribution chart is catalogued (to confirm).

## Missing
- Tutor profile, subjects taught, availability, booking, review, consent-grant, report/block tables.
- A consent-grant access gate and an access audit log.
- Generic email: `EmailProvider` (`lemely/auth/email.py:57`) only sends verification and password-reset links.
- A scheduler: none, so expiry must be evaluated at read time.
- Cohort-level outcome stats with a minimum cohort size.

## Conflicts and corrections to the brief
1. **Roles:** one role per user. `users.role` is a single `Role` enum column (`lemely/db/models/users.py:36`, `enums.py:22`). "Teacher and tutor" in one account needs a profile/capability, not a second role. `MembershipRole` (teacher, school_admin) is separate and school-scoped.
2. **Tenancy is not purely school-scoped.** `SchoolClass.school_id` is nullable (D3.1, `orgs.py`): independent teachers already run school-less classes. The teacher↔student link is class enrolment, so a tutor link is a new cross-class grant, not a new tenant concept.
3. **Parent link:** `ParentChildLink` is a child-issued invite (D-2026-09-08). Parents are read-only, confirmed by routes.
4. **Payments:** MISSION says "Deferred (documented, not built)", not rejected. We still build none.
5. **Single replica is stale:** DELIVERY §5.6 says the constraint was lifted (D7.13), and the OTP and cooldown stores are in Postgres. Only the Gemini response cache is per-instance. Booking conflicts still belong in the DB.
6. **D-numbers:** `BUILD/DECISIONS.md` mixes `D<phase>.<n>`, `DA<n>` and dated `D-YYYY-MM-DD`. The latest entries are dated (`D-2026-09-21`). No "next free number" exists. Proposal: `D-2026-10-25-tutoring-*`.
7. **Alembic head:** `0043_merge_heads.py` by file listing. Confirm with `alembic heads` before the migration task.
8. **Teacher router:** `teacher.py` is 2,400+ lines. Tutor routes go in a new router. No refactor of the teacher module.
9. **Index:** tokensave serves `develop`, 2 days stale. Verify any symbol before editing it.

## Not verified yet
`check.sh` gate count (13?), audit-runner and screenshot route lists (`web/scripts/audit.mjs`, `capture_surface.mjs`), the arbitrary-literal lint, `EXPECTED` table shape in `tests/test_authz_matrix_complete.py`, the notification type list, and `docs/database.md` tenancy wording.
