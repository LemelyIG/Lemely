# Parent Invites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementers run on `model=sonnet`, reviewers on `model=opus`; the orchestrating session writes no code (project rule, `~/.claude/projects/-home-sico-Code-Lemely/memory/delegate-by-model.md`). Each task below names files, interfaces, behaviours and test names; the implementer authors the code under TDD.

**Goal:** Retire every SMS/phone-dependent flow and replace parent onboarding with child-issued invites, an emailed six-digit code, and an email + password account.

**Architecture:** The existing `invites` table grows a `parent` role, a `child_id` target and a `reusable` flag, so a parent invite resolves through the same `/join/:code` preview and redeem path as class and seat invites. Three new public auth routes carry a pre-account email proof (OTP-store `email` channel → short-lived HS256 proof token → signup + link in one call). The SMS seams (`SmsProvider`, `OtpChannel.phone`, `AuthService.request_otp/verify_otp`, `users.phone`) stay in place, unused.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (Postgres), GoTrue via `lemely.auth.gotrue`, PyJWT, React 19 + react-router + TanStack Query + Vite, Playwright.

Spec: `docs/superpowers/specs/2026-09-08-parent-invites-design.md`.

## Global Constraints

- Signed commits only: `git commit -S`. Conventional scopes as listed per task. Run `pre-commit run --all-files` before each commit.
- `source .venv/bin/activate` first. Postgres-backed tests need the local stack (`supabase start`); hermetic tests do not.
- Never touch: `lemely/auth/sms.py`, `OtpChannel.phone`, `AuthService.request_otp`/`verify_otp`, `users.phone`, the JWT `phone` claim, `UserMirror.get_by_phone`, `_phone_placeholder_email`, `AuthSettings.otp_*`, `supabase/config.toml`, `SignupRequestDTO.phone`, and the tests that cover them (`tests/test_auth_service.py` OTP tests, `tests/test_otp*.py`).
- UI copy rules (REDESIGN-MISSION §3.2): no em dashes in real UI copy; sentences for humans, never enum members.
- No new DTO field that always answers the same absent value (codebase rule quoted in `schemas_invites.py`).
- Docstrings in this codebase explain *why*; match that register.
- Keep the D3.16 rule everywhere a code is returned: `devCode` is non-null only when the configured provider does not deliver out of band.

---

### Task 1: Schema — `parent` invite role, `child_id`, `reusable`

**Files:**
- Create: `lemely/db/migrations/versions/0034_parent_invites.py`
- Modify: `lemely/db/models/enums.py:333-346` (`InviteRole`), `lemely/db/models/invites.py`
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `InviteRole.parent`; `Invite.child_id: uuid.UUID | None`; `Invite.reusable: bool` (server default false); constraint `ck_invites_target` now allows `child_id`.

- [ ] Write failing schema assertions in `tests/test_db_schema.py` next to the existing invites block (line ~808): `invites` has columns `child_id` (nullable UUID, FK `users.id`, ondelete CASCADE) and `reusable` (boolean, not null, server default false); index `ix_invites_child_id` exists; enum `inviterole` contains `parent`; an insert with only `child_id` set passes `ck_invites_target`.
- [ ] Run `pytest tests/test_db_schema.py -k invites -v` → FAIL.
- [ ] Migration: revision `0034_parent_invites`, `down_revision = "0033_announcement_notified_at"`. `upgrade`: `ALTER TYPE inviterole ADD VALUE IF NOT EXISTS 'parent'`; add `child_id` + `reusable`; create index; `op.drop_constraint("ck_invites_target", "invites", type_="check")` then `op.create_check_constraint("ck_invites_target", "invites", "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL")`. `downgrade` reverses columns/index/constraint; module docstring states the enum value stays (cite `0019`).
- [ ] Model: add both columns and the widened `CheckConstraint`; `InviteRole.parent = "parent"` and rewrite the enum docstring (it currently claims only student/teacher; keep the "not `Role`" reasoning).
- [ ] Run `alembic upgrade head` against the local stack, then `pytest tests/test_db_schema.py -v` → PASS. Also `alembic downgrade -1 && alembic upgrade head` once.
- [ ] Commit: `feat(db): parent invites — inviterole.parent, invites.child_id, invites.reusable (0034)`.

---

### Task 2: `ParentLinkService` — drop phone linking, add `link_in_session`

**Files:**
- Modify: `lemely/db/parent_repo.py`
- Test: `tests/test_parent_repo.py`

**Interfaces:**
- Produces: `ParentLinkService.link_in_session(session: Session, parent_id: uuid.UUID, child_id: uuid.UUID) -> None` (idempotent; no role check, caller guarantees a `role=parent` id); `ParentRow(parent_id, display_name, email, phone)`.
- Removes: `ParentLinkService.link`, `ParentUserNotFoundError`.

- [ ] Delete the phone-link tests (`test_link_unknown_phone_never_creates_a_user`, `test_link_ignores_a_matching_phone_on_a_non_parent_role`, `test_link_picks_the_most_recently_created_parent_for_a_shared_phone`, and any other `link(` by phone test). Add `test_link_in_session_inserts_one_row_and_is_idempotent` and `test_list_parents_carries_email`. Keep `test_a_phone_only_parents_name_is_their_phone_not_the_placeholder_email` (display-name fallback still runs for legacy rows).
- [ ] Run `pytest tests/test_parent_repo.py -v` → FAIL on the new tests.
- [ ] Implement: remove `link` and `ParentUserNotFoundError`; add `link_in_session` wrapping `_link_if_absent`; add `email` to `ParentRow` and populate it in `list_parents`; rewrite the module docstring's "Linking direction is fixed" paragraph (student mints an invite, parent proves an email, the invite service is the only caller of `link_in_session`).
- [ ] `pytest tests/test_parent_repo.py -v` → PASS. `ruff check lemely/db/parent_repo.py`.
- [ ] Commit: `refactor(parent_repo): drop link-by-phone, expose link_in_session for invites`.

---

### Task 3: `InviteService` — parent invites

**Files:**
- Modify: `lemely/db/invite_repo.py`, `lemely/web/deps.py:995-1010` (`get_invite_service`)
- Test: `tests/test_invite_repo.py`

**Interfaces:**
- Consumes: Task 1 columns, Task 2 `link_in_session`.
- Produces:
  - `InviteService.__init__(sessionmaker, class_service, parent_link_service)`
  - `mint_parent_invite(student_id, *, reusable: bool) -> Invite`
  - `get_or_create_parent_code(student_id) -> Invite`
  - `rotate_parent_code(student_id) -> Invite`
  - `list_parent_invites(student_id) -> list[Invite]`
  - `revoke_parent_invite(student_id, code) -> None` (raises `InviteNotFoundError`)
  - `InvitePreview.child_name: str | None`
  - `redeem(user_id, code, *, caller_role: Role | None = None) -> RedeemResult` with `RedeemResult.child_id`
  - `InviteRoleMismatchError(InviteError)`
  - `PARENT_INVITE_TTL = timedelta(days=7)`

- [ ] Tests (Postgres, reuse the file's existing fixtures/`_seed_*` helpers): `test_mint_parent_link_sets_child_created_by_and_seven_day_expiry`; `test_get_or_create_parent_code_is_lazy_and_stable`; `test_rotate_parent_code_replaces_the_row`; `test_list_parent_invites_excludes_expired_redeemed_and_reusable`; `test_revoke_parent_invite_refuses_another_students_code`; `test_preview_parent_invite_names_child_never_email_or_id`; `test_redeem_parent_link_links_and_consumes`; `test_redeem_parent_code_links_without_consuming_so_a_second_parent_can_use_it`; `test_redeem_parent_invite_by_student_is_role_mismatch`; `test_redeem_class_invite_by_parent_is_role_mismatch`; `test_redeem_parent_invite_twice_by_same_parent_is_idempotent`. Update the fixture that constructs `InviteService` to pass a `ParentLinkService`.
- [ ] `pytest tests/test_invite_repo.py -v` → FAIL.
- [ ] Implement per spec §4. `_insert_invite` gains `child_id`, `reusable`, `expires_at` kwargs. Parent preview: `child_name = user.display_name or "your child"`. Parent redeem branch inside the same `session.begin()` as `_find_live_invite(for_update=True)`. `redeem` docstring: reusable codes are the documented exception to "an `invites` row is single-use".
- [ ] Wire `get_invite_service` to pass `get_parent_link_service()`; update its docstring (it says "needs no account-creation seam" — still true; add the parent-link seam sentence).
- [ ] `pytest tests/test_invite_repo.py tests/test_web_invites.py -v` → PASS (web tests still construct the service; fix their constructor call).
- [ ] Commit: `feat(invites): child-issued parent invites (single-use link + reusable code)`.

---

### Task 4: Auth service — email proof and parent signup primitives

**Files:**
- Modify: `lemely/auth/email.py`, `lemely/auth/tokens.py`, `lemely/auth/service.py`, `tests/auth_fakes.py`
- Test: `tests/test_auth_service.py`, `tests/test_auth_tokens.py`

**Interfaces:**
- Produces:
  - `EmailProvider.send_signup_code(email: str, code: str) -> None` on Protocol, `MockEmailProvider`, `ResendEmailProvider`, `FakeEmailProvider` (`sent_signup_codes: list[tuple[str, str]]`).
  - `mint_email_proof_token(*, email, invite_code, settings, ttl_seconds=900, now=None) -> str`; `decode_email_proof_token(token, settings) -> EmailProofClaims` (frozen dataclass `email`, `invite_code`); audience `lemely-email-proof`, `typ="email_proof"`; raises the module's existing `TokenError`.
  - `AuthService.signup(..., email_verified: bool = False)`.
  - `AuthService.request_parent_signup_code(email) -> str | None`.
  - `AuthService.verify_parent_signup_code(email, code) -> None` (raises `AuthError`).

- [ ] Tests: `test_auth_tokens.py`: proof token round-trips, rejects tampering, rejects an access token presented as proof and vice versa, expires. `test_auth_service.py`: `test_signup_email_verified_stamps_and_sends_nothing`; `test_request_parent_signup_code_returns_code_only_when_provider_does_not_deliver`; `test_request_parent_signup_code_propagates_resend_cooldown`; `test_verify_parent_signup_code_wrong_and_ok`. Add `send_signup_code` to `FakeEmailProvider`.
- [ ] Run the four test selections → FAIL.
- [ ] Implement per spec §4. `ResendEmailProvider.send_signup_code` subject "Your Lemely code"; body states the code and that it expires in ten minutes (`email_otp_ttl_seconds` default). `signup(email_verified=True)` stamps via `self._mirror.mark_email_verified(created.id, verified_at=_utcnow())` and skips the verification send.
- [ ] `pytest tests/test_auth_service.py tests/test_auth_tokens.py -v` → PASS.
- [ ] Commit: `feat(auth): email proof token and parent signup code primitives`.

---

### Task 5: HTTP — parent auth routes, invites router, student parent-invites; delete OTP and phone-link routes

**Files:**
- Modify: `lemely/web/schemas_auth.py`, `lemely/web/routers/auth.py`, `lemely/web/schemas_invites.py`, `lemely/web/routers/invites.py`, `lemely/web/schemas_parent.py`, `lemely/web/routers/student.py:1199-1264`
- Test: `tests/test_auth_router.py`, `tests/test_web_invites.py`, `tests/test_web_student.py`, `tests/test_authz_matrix_complete.py:128-131,278-283`

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces (wire):
  - `POST /api/auth/parent/request-code {email, inviteCode}` → `{status:"sent", devCode}`; 404 dead/non-parent invite; 400 email taken; 429 cooldown.
  - `POST /api/auth/parent/verify-code {email, inviteCode, code}` → `{proofToken}`; 401 bad code; 404 dead invite.
  - `POST /api/auth/parent/signup {proofToken, password, displayName?, acceptedTerms, deviceId?}` → `TokenResponseDTO`; 401 bad proof; 404 dead invite; 400 signup error.
  - `GET /api/invites/{code}` gains `childName`; `role` may be `"parent"`. `POST /api/invites/{code}/redeem` gains `childId`; 403 on role mismatch.
  - `GET /api/student/parent-invites` → `ParentInvitesDTO{code:{code,url}, links:[{code,url,expiresAt}]}`; `POST` → `ParentInviteLinkDTO`; `DELETE /{code}` → 204/404; `POST /code/rotate` → `{code,url}`. `url = f"{settings.email.app_base_url}/join/{code}"`.
  - `LinkedParentDTO.email`.
- Removes: `/api/auth/otp/request`, `/api/auth/otp/verify`, `POST /api/student/parent-links`, `OtpRequestDTO`, `OtpVerifyDTO`, `OtpRequestResponseDTO`, `LinkParentRequestDTO`.

- [ ] Tests first. `test_auth_router.py`: delete `test_otp_*`; add `test_parent_request_code_happy_path_returns_dev_code`, `test_parent_request_code_dead_invite_is_404`, `test_parent_request_code_taken_email_is_400`, `test_parent_request_code_cooldown_is_429`, `test_parent_verify_code_wrong_is_401`, `test_parent_signup_creates_verified_parent_and_links`, `test_parent_signup_expired_proof_is_401`. The `context` fixture needs an `InviteService` override (`get_invite_service`) — use a fake with the same method names or the Postgres service via the `pg_sessionmaker` pattern used in `test_web_invites.py`; pick the Postgres route so the link is real. `test_web_invites.py`: parent preview + redeem + 403 mismatch. `test_web_student.py`: replace `test_student_links_a_parent_by_phone_then_lists_it` / `test_student_link_unknown_phone_is_a_clean_404` with `test_student_parent_invites_get_mints_code_lazily`, `test_student_mints_and_revokes_a_link`, `test_student_cannot_revoke_another_students_link`, `test_student_rotate_code_changes_it`, `test_list_parents_carries_email`. `test_authz_matrix_complete.py`: remove the OTP and phone-link rows; add `("POST","/api/auth/parent/request-code"): PUBLIC` (+ verify-code, signup) and the four `parent-invites` rows as STUDENT.
- [ ] Run those files → FAIL.
- [ ] Implement per spec §4. Router helper `_require_live_parent_invite(invite_service, code) -> None` used by all three auth routes (404 on `InviteNotFoundError` or non-parent role). Reuse `_cooldown_detail`, `_device_context`, `_to_token_dto`. In `student.py` build `url` from `get_settings().email.app_base_url`.
- [ ] `pytest tests/test_auth_router.py tests/test_web_invites.py tests/test_web_student.py tests/test_authz_matrix_complete.py -v` → PASS. `ruff check .`.
- [ ] Commit: `feat(web): parent signup routes and student parent-invites; retire OTP and phone-link routes`.

---

### Task 6: Seed and e2e seed script

**Files:**
- Modify: `lemely/db/seed.py:100-310`, `scripts/seed_e2e.py`, `web/e2e/seed.ts`, `web/e2e/seed-contract.spec.ts`
- Test: `tests/test_seed.py`, `tests/test_seed_e2e.py`, `tests/test_web_entrypoint.py:38`

**Interfaces:**
- Consumes: Task 2 `link_in_session`, Task 3 `get_or_create_parent_code`, `AuthService.signup(role=Role.parent)`.
- Produces: `DEMO_ACCOUNTS` gains `DemoAccount(email="parent@demo.lemely.local", role=Role.parent, display_name="Demo Parent")`; `DEMO_PARENT`/`DemoParent` removed; `create_demo_accounts` links the demo parent to the demo student (new `_link_demo_parent(parent_link_service, parent_id, student_id)` — `create_demo_accounts` gains a `parent_link_service` kwarg, `seed_demo_accounts` wires it). Seed-e2e output contract: `parent: {userId, email, password, accessToken, linkedStudent}`, `emptyParent: {userId, email, password, accessToken}`, `students.declining.parentInviteCode: str`. `build_phone`, `build_empty_parent_phone` removed.

- [ ] Tests: `test_seed.py` — `TestDemoAccountTable` now expects five email accounts and one per role; replace OTP-based parent tests with `test_demo_parent_is_linked_to_demo_student` and `test_second_run_creates_nothing`; delete `_OutOfBandSms`. `test_seed_e2e.py` — delete `build_phone` tests; add `test_contract_carries_parent_invite_code_and_parent_email`. `test_web_entrypoint.py` — drop `OTP_MESSAGE`; if the test asserted the mock SMS log line on startup/seed, assert the mock email signup-code line instead or remove that assertion.
- [ ] Run → FAIL.
- [ ] Implement per spec §6. In `seed_e2e.py`, `_signup_account("parent", Role.parent, run_tag)` and `("empty-parent", ...)`; link via `parent_link_service` under a session; mint the declining student's code with `deps.get_invite_service().get_or_create_parent_code(...)`. Update the module docstring's parent paragraphs and the output-contract example. Update `web/e2e/seed.ts` `SeedContract` (parent → `SeedAccount & { linkedStudent: string }`, `emptyParent: SeedAccount`, `students.declining.parentInviteCode`) and `seed-contract.spec.ts` field assertions.
- [ ] `pytest tests/test_seed.py tests/test_seed_e2e.py tests/test_web_entrypoint.py -v` → PASS. `make seed` against the local stack succeeds twice.
- [ ] Commit: `refactor(seed): demo and e2e parents are email accounts linked by invite`.

---

### Task 7: Frontend — parent signup, join screen, student Parent access, cleanup

**Files:**
- Create: `web/src/components/auth/CodeInput.tsx`, `web/src/portals/auth/SignupParent.tsx`, `web/src/portals/auth/signupParentLogic.ts`, `web/src/lib/hooks/useParentSignupApi.ts`, `web/tests/unit/signupParentLogic.test.ts`
- Delete: `web/src/portals/auth/ParentLogin.tsx`
- Modify: `web/src/routes.tsx` (remove `/login/parent` block ~lines 320-345, add `/signup/parent` beside `/signup/student`), `web/src/lib/auth/AuthContext.tsx` (remove `requestOtp`/`verifyOtp`, add `parentSignup`), `web/src/lib/authTypes.ts` (remove `Otp*`, add `ParentCodeRequestBody`, `ParentCodeRequestResponse`, `ParentCodeVerifyBody`, `ParentCodeVerifyResponse`, `ParentSignupBody`; `InvitePreview.role` union gains `"parent"`, add `childName`), `web/src/lib/parentTypes.ts` (`LinkedParent.email`; add `ParentInvites`, `ParentInviteLink`), `web/src/lib/hooks/useStudentApi.ts` (remove `useLinkParent`; add `useParentInvites`, `useMintParentLink`, `useRevokeParentLink`, `useRotateParentCode`), `web/src/lib/hooks/useInvitesApi.ts` (`describeInvitePreview` parent line; `signupPathForInvite` accepts `"parent"`; `RedeemInviteResult.childId`), `web/src/portals/auth/JoinWithCode.tsx`, `web/src/portals/student/screens/Parents.tsx`, `web/src/portals/auth/Login.tsx:197-203`, `web/src/portals/auth/SignupRoleSelect.tsx:38-47,109-116`, `web/src/lib/auth/RequireAuth.tsx:78-90`, `web/src/portals/parent/index.tsx:288`, `web/src/portals/parent/screens/Children.tsx:151`, `web/src/portals/marketing/data.ts:210-216`, `web/src/portals/marketing/index.tsx:110-124`
- Test: `web/tests/unit/joinWithCode.test.ts`, `web/tests/unit/requireAuth.test.ts:29`, `web/tests/unit/authOutcome.test.ts`

**Interfaces:**
- Consumes: Task 5 wire shapes.
- Produces: `CodeInput({ length, value, onChange, onComplete, disabled, error })`; `signupParentLogic.ts` pure helpers: `parentSignupStep(state): "email" | "code" | "password"`, `validateParentEmailStep`, `validateParentPasswordStep` (reusing `MIN_PASSWORD_LENGTH`/`passwordStrength` from `signupDetailsLogic.ts`), `parentSignupDevPanel(devCode)`, `parentInviteMissingCopy()`; `AuthContext.parentSignup: UseMutationResult<TokenResponse, Error, ParentSignupBody>`.

- [ ] Unit tests first (vitest, node env, pure logic only): `signupParentLogic.test.ts` covering step derivation, validation messages, dev panel visibility rule (mirrors `passwordResetDevPanel`), missing-code copy. `joinWithCode.test.ts`: `describeInvitePreview` for a parent preview (with and without `childName`), `signupPathForInvite("ABC","parent") === "/signup/parent?code=ABC"`. `requireAuth.test.ts:29`: rename and retarget the parent case to `/login`. `authOutcome.test.ts`: no change expected; confirm it still passes.
- [ ] `cd web && npm run test` → FAIL on the new tests.
- [ ] Implement per spec §5. Order: extract `CodeInput` from `ParentLogin.tsx` (keep the paste/auto-advance/auto-submit behaviour and the `data-lg` dev-code rung), then delete `ParentLogin.tsx`. `SignupParent.tsx` uses `AuthFrame` from `Login.tsx`, the D7.11 terms checkbox copy from `SignupDetails.tsx`, `otpVerifyFailureMessage` for step-2 errors, `safeNextPath` is not needed. `JoinWithCode.tsx`: signed-out parent invite → "Create your parent account" → `/signup/parent?code=`, plus "Already have an account? Sign in" → `/login?next=/join/<code>`; signed-in parent → redeem → `/parent/children/<childId>`; signed-in non-parent → refusal line, no button. `Parents.tsx`: code card (Copy, Share, Reset), one-time link section (mint, pending list with expiry from `expiresAt`, Revoke), linked list shows `email`. Copy fixes as listed in the spec.
- [ ] `cd web && npm run lint && npm run test && npm run build` → all green. Grep gate: `rg -n 'login/parent|requestOtp|verifyOtp|/auth/otp|useLinkParent' web/src` returns nothing.
- [ ] Commit: `feat(web-ui): parent signup by invite; student parent access codes; retire phone login`.

---

### Task 8: Playwright — parent journey

**Files:**
- Modify: `web/e2e/parent-journey.spec.ts`, and any spec reading `seed.parent.phone` (grep `web/e2e` for `phone`).

**Interfaces:**
- Consumes: Task 6 contract (`students.declining.parentInviteCode`, `parent.email/password`), Task 7 screens.

- [ ] Rewrite test (a): a fresh visitor opens `/join/<parentInviteCode>`, sees the child's name, clicks through to `/signup/parent?code=…`, enters a run-tagged email + name, reads `devCode` from the developer panel, enters it in `CodeInput`, sets a password, accepts terms, lands on `/parent/children/<declining.userId>`. Test (b) unchanged apart from field names. Add test (c): a signed-out returning parent uses `/login` with `parent.email`/`parent.password` and lands on `/parent`.
- [ ] `cd web && npx playwright test parent-journey seed-contract signup` against a freshly seeded stack (`python scripts/seed_e2e.py`) → PASS.
- [ ] Commit: `test(e2e): parent journey via invite code and email signup`.

---

### Task 9: Docs and decisions

**Files:**
- Modify: `docs/LEMELY_UI_SPEC.md:296-298,320-340`, `BUILD/DECISIONS.md` (append), `PRODUCT.md:28`, `docs/deployment.md:392,443`, `README.md` (demo-account table), `CHANGELOG.md`, `lemely.toml.example:148-155`

- [ ] UI spec: §G-05 becomes "Parent join and sign in" (code from the child at G-08 → email → code → password; returning parents use G-04); G-02 and G-04 exits updated; the "Shipped divergence" note under G-07 that cites G-05's SMS mock is reworded.
- [ ] `BUILD/DECISIONS.md`: new entry "D-2026-09-08 — Parent identity is email + password via child-issued invites; SMS retired, seams kept", stating the decision, why (metered SMS, no gateway ever wired), what it supersedes (D3.11's phone direction, the SMS parts of D1.4/D3.16), the honest gap (GoTrue create + link not one transaction), and the reusable-code exception to single-use invites.
- [ ] `PRODUCT.md:28` parent persona; `docs/deployment.md` challenge-store row and demo table; README demo table (`parent@demo.lemely.local`); CHANGELOG entry; `lemely.toml.example` OTP comment (phone challenge lifecycle retained for the seam, email channel is what ships).
- [ ] `pre-commit run --all-files` → clean.
- [ ] Commit: `docs: parent invites replace phone OTP; record decision and update spec`.

---

## Verification (after Task 9)

- `make test` and `ruff check .` clean; `cd web && npm run lint && npm run test && npm run build` clean; Playwright `parent-journey`, `seed-contract`, `signup` green.
- Manual walk per the spec: `make seed`, sign in as `student@demo.lemely.local`, open Parent access, copy the code; private window → `/join/<code>` → parent signup with the dev code → child overview; `/join/<code>` again while signed in → idempotent; sign out; `/login` with `parent@demo.lemely.local` / `Demo-Lemely-1!` → `/parent`.
- Grep gates: `rg -n 'login/parent|requestOtp|verifyOtp|/auth/otp|useLinkParent' web/src lemely tests scripts` returns nothing.
