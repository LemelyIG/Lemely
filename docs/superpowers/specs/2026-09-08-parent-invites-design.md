# Parent invites: retire SMS/phone auth, replace with child-issued invites + email code + password

**Status:** approved 2026-09-08 (brainstorm with the product owner).
**Supersedes:** the phone-OTP direction of D3.11, and the SMS-delivery parts of D1.4 and D3.16 in `BUILD/DECISIONS.md`.

## 1. Why

Every SMS API is metered and expensive. Lemely's only phone-dependent surfaces are the parent login (UI spec §G-05, phone + OTP) and the student's "add a parent by phone number" link. No real SMS gateway was ever wired: `lemely/web/deps.py` injects `MockSmsProvider` unconditionally, and the comment on `/login/parent` in `web/src/routes.tsx` records that no deployment of this code can send a text. Retiring SMS therefore costs nothing in infrastructure. The work is replacing how a parent gets an identity and how a child grants access.

## 2. Decisions

1. **Parent identity is email + password.** A parent is an ordinary GoTrue email/password user with `role=parent`. Returning parents sign in at `/login` (G-04). `/login/parent` is retired.
2. **Onboarding is child-issued.** The student generates an invite. The parent opens it, enters an email address, verifies a six-digit code sent to that address, sets a password, and in one server call the account is created (email already verified), linked to the child, and signed in.
3. **Two invite kinds, one table, one box.** The student can mint a single-use link (7-day expiry, revocable) and also holds a reusable short code (rotatable). Both live in the existing `invites` table and both resolve at the existing `/join/:code` screen (G-08).
4. **A parent who already has an account** accepts a second child's invite at `/join/:code` while signed in, or from the signed-out invite page via "Already have an account? Sign in", which returns them to the invite after login.
5. **Retire flows only, keep seams.** Deleted: the two `/api/auth/otp/*` routes and their DTOs, `ParentLogin.tsx` and its route, `POST /api/student/parent-links` (link by phone) with `LinkParentRequestDTO` and `ParentLinkService.link`, the phone-based seed and e2e helpers, and every line of "a phone number is the whole login" copy. Kept untouched for a possible future paid SMS channel: `SmsProvider`, `MockSmsProvider`, `OtpChannel.phone`, `AuthService.request_otp`/`verify_otp` and their unit tests, `users.phone`, the JWT `phone` claim, `UserMirror.get_by_phone`, `_phone_placeholder_email`, `AuthSettings.otp_*`, the disabled `[auth.sms.twilio]` block in `supabase/config.toml`, and `SignupRequestDTO.phone`.

## 3. Data model

Migration `0034_parent_invites` (down_revision `0033_announcement_notified_at`):

- `ALTER TYPE inviterole ADD VALUE IF NOT EXISTS 'parent'` (the enum-extension pattern of migration `0019`; the value cannot be dropped on downgrade and the docstring says so). `InviteRole` gains `parent`; its docstring no longer claims "only a student or a teacher".
- `invites.child_id UUID NULL REFERENCES users(id) ON DELETE CASCADE`, indexed as `ix_invites_child_id`.
- `invites.reusable BOOLEAN NOT NULL DEFAULT false`.
- `ck_invites_target` recreated as `school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL`.

Semantics:

| Kind | `reusable` | `expires_at` | Consumed? | Ends when |
|---|---|---|---|---|
| Single-use link | false | mint + 7 days | yes, `redeemed_by`/`redeemed_at` | redeemed, expired, or revoked (row deleted) |
| Reusable code | true | NULL | never marked; each redemption only inserts a `parent_child_links` row | rotated (row deleted, new one minted) |

A student has at most one reusable row at a time. `created_by` is the student for both kinds.

## 4. Backend

### `lemely/db/parent_repo.py`
- Remove `link(student_id, phone)` and `ParentUserNotFoundError`.
- Add `link_in_session(session, parent_id, child_id) -> None`, a public wrapper over the existing `_link_if_absent`, so the invite service links through this module and the "single `parent_child_links` writer" rule holds.
- `ParentRow` gains `email: str`. Rewrite the module docstring's "linking direction" paragraph: the student issues an invite; the parent proves an email address.

### `lemely/db/invite_repo.py`
`InviteService(sessionmaker, class_service, parent_link_service)`; `lemely/web/deps.py::get_invite_service` passes the `ParentLinkService` singleton.

- `mint_parent_invite(student_id, *, reusable: bool) -> Invite` — `role=parent`, `child_id=student`, `created_by=student`, `expires_at = now + 7 days` when not reusable, `NULL` when reusable.
- `get_or_create_parent_code(student_id) -> Invite` — returns the reusable row for this child, minting one lazily (the same "a class always has a join code" rule as `classes.join_code`).
- `rotate_parent_code(student_id) -> Invite` — deletes the reusable row and mints a new one.
- `list_parent_invites(student_id) -> list[Invite]` — live (unexpired), unredeemed, non-reusable rows for this child, oldest first.
- `revoke_parent_invite(student_id, code) -> None` — deletes only when `child_id == student_id` and `reusable is False`; anything else raises `InviteNotFoundError` (a student learns nothing about another student's codes).
- `preview` returns `InvitePreview(role=parent, child_name=<display_name, or "your child" when blank>, school_name=None, class_name=None, teacher_name=None)`. `InvitePreview` gains `child_name: str | None`. The preview never carries the child's email or id.
- `redeem(user_id, code, *, caller_role: Role | None = None)`. Parent invites require `caller_role is Role.parent`; otherwise `InviteRoleMismatchError` (new, → 403). A student/teacher invite redeemed by a parent also raises it. The parent branch calls `parent_link_service.link_in_session(session, user_uuid, invite.child_id)` inside the same transaction that marks the invite redeemed, and marks `redeemed_by/at` only when `reusable is False`. `RedeemResult` gains `child_id: uuid.UUID | None`.
- `_insert_invite` grows `child_id`, `reusable`, `expires_at` keyword arguments.

### `lemely/auth/email.py`
`EmailProvider` Protocol gains `send_signup_code(email, code) -> None`; implemented by `MockEmailProvider` (INFO log, same style as `send_verification`), `ResendEmailProvider` (subject "Your Lemely code"), and `tests/auth_fakes.py::FakeEmailProvider` (records to `sent_signup_codes`, honours `raise_on_send`).

### `lemely/auth/tokens.py`
- `mint_email_proof_token(*, email, invite_code, settings, ttl_seconds=900, now=None) -> str` — HS256 with the shared secret, its own audience `lemely-email-proof` and `typ="email_proof"`, so it is never accepted as an access or refresh token.
- `decode_email_proof_token(token, settings) -> EmailProofClaims(email, invite_code)`; raises `TokenError` on any failure.

### `lemely/auth/service.py`
- `signup(..., email_verified: bool = False)`: when true, stamps `users.email_verified_at` via `mirror.mark_email_verified` after the upsert and skips the verification link/code send (`verification_dev_link`/`verification_dev_code` stay `None`).
- `request_parent_signup_code(email) -> str | None` — issues an `OtpChannel.email` challenge, calls `email.send_signup_code`, returns the code under the `_dev_code_for` rule (D3.16). Lets `OtpRateLimitError` propagate.
- `verify_parent_signup_code(email, code) -> None` — `otp_store.verify(email, code, channel=OtpChannel.email)`; any non-ok result raises `AuthError(f"Email verification failed: {result.value}")` (the wording `web/src/lib/authOutcome.ts` already maps to sentences).

### `lemely/web/schemas_auth.py`
Remove `OtpRequestDTO`, `OtpVerifyDTO`, `OtpRequestResponseDTO`. Add `ParentCodeRequestDTO{email, inviteCode}`, `ParentCodeRequestResponseDTO{status: "sent", devCode}`, `ParentCodeVerifyDTO{email, inviteCode, code}`, `ParentCodeVerifyResponseDTO{proofToken}`, `ParentSignupDTO{proofToken, password, displayName?, acceptedTerms, deviceId?}`.

### `lemely/web/routers/auth.py`
Delete the two OTP routes. Add three public routes:

- `POST /api/auth/parent/request-code` — the invite must resolve to a live parent invite (any other outcome is the same 404 as an unknown code); an email that already has an account is a 400 whose detail says to sign in and open the invite instead; the per-email signup cooldown (`get_signup_and_reset_cooldown_store`) and `OtpRateLimitError` both map to 429 with the existing `_cooldown_detail`/message text; returns `devCode` only when the provider does not deliver out of band.
- `POST /api/auth/parent/verify-code` — verifies the code (failure → 401 with the service's detail), re-checks the invite is live (→ 404), returns `proofToken`.
- `POST /api/auth/parent/signup` — decodes the proof token (→ 401), re-checks the invite (→ 404), calls `signup(email, password, Role.parent, display_name, device, accepted_terms, email_verified=True)` (`AuthError` → 400), then `invite_service.redeem(user_id, code, caller_role=Role.parent)`, and returns `TokenResponseDTO`. The docstring records the honest gap: the GoTrue create and the link are not one database transaction (the same shape as seat invites); a parent left unlinked by a failure between the two re-presents the same code at `/join/:code`.

`_SELF_SERVICE_SIGNUP_ROLES` is unchanged; parents still cannot use `/api/auth/signup`.

### `lemely/web/routers/invites.py` and `schemas_invites.py`
`redeem_invite` passes `caller_role=Role(auth.role)` and maps `InviteRoleMismatchError` → 403. Role literals gain `"parent"`. `InvitePreviewDTO.childName`, `RedeemInviteResponseDTO.childId`.

### `lemely/web/routers/student.py` and `schemas_parent.py`
- Remove `student_link_parent` and `LinkParentRequestDTO`.
- `LinkedParentDTO` gains `email: str`; `phone` stays nullable.
- New student-only routes: `GET /api/student/parent-invites` → `ParentInvitesDTO{code: {code, url}, links: [{code, url, expiresAt}]}`; `POST /api/student/parent-invites` → `ParentInviteLinkDTO{code, url, expiresAt}`; `DELETE /api/student/parent-invites/{code}` → 204 (unknown → 404); `POST /api/student/parent-invites/code/rotate` → `{code, url}`. `url` is `settings.email.app_base_url` (the origin `ResendEmailProvider._absolute` already joins links onto) plus `/join/<code>`.

## 5. Frontend (`web/`)

- Extract the six-box code entry from `ParentLogin.tsx` into `src/components/auth/CodeInput.tsx` (paste, auto-advance, auto-submit, the `data-lg` dev-code rung) before deleting `ParentLogin.tsx`.
- Delete `src/portals/auth/ParentLogin.tsx`, the `/login/parent` route, `requestOtp`/`verifyOtp` in `AuthContext.tsx`, and the `Otp*` types in `authTypes.ts`. Keep `otpVerifyFailureMessage`; the parent code step reuses it.
- New `src/portals/auth/SignupParent.tsx` at `/signup/parent` (wrapped in `LoginRoute`), reading `?code=`. Three steps: email + name; `CodeInput`; password (strength from `signupDetailsLogic.ts`) + the D7.11 terms checkbox. Dev code shown in the same labelled developer panel style as the reset flow. 30-second display-only resend cooldown, "Change email", and a "This invite link doesn't work" panel linking to `/join` when the code is missing or dead. Pre-account hooks live in `src/lib/hooks/useParentSignupApi.ts`; only the session-minting final call is added to `AuthContext` as `parentSignup`.
- `JoinWithCode.tsx` / `useInvitesApi.ts`: parent previews read "<childName> invited you to follow their progress on Lemely"; signed-out visitors go to `/signup/parent?code=` and see "Already have an account? Sign in" (→ `/login?next=/join/<code>`); a signed-in parent redeems and lands on `/parent/children/<childId>`; a signed-in student or teacher sees a refusal line instead of a redeem button.
- `Parents.tsx` (student): "Your parent code" card (copy, share via `navigator.share` with clipboard fallback, reset), "Send a one-time link" with a pending list showing expiry and a revoke action, and the linked-parents list showing email.
- Copy and route fixes: `Login.tsx` parent link → `/join`; `SignupRoleSelect.tsx` parent card → `/join`; `RequireAuth.tsx` parent → `/login`; parent portal sign-out → `/login`; `Children.tsx` step 2 → "In their account, they open Parent access and share their code or link with you."; the marketing parent block; the `/login/parent` comment block in `routes.tsx`.

## 6. Seed, e2e, docs

- `lemely/db/seed.py`: the demo parent becomes `parent@demo.lemely.local` / `DEMO_PASSWORD`, created through the same email path as the other demo roles and linked to the demo student. `DemoParent`, `_create_or_recover_parent`, `_apply_parent_display_name` and the SMS `SeedError` branch go.
- `scripts/seed_e2e.py`: parent and empty parent are created via `signup(..., Role.parent)`; the linked parent is linked through `ParentLinkService.link_in_session`; the declining student's reusable parent code is minted and emitted. Output contract: `parent: {userId, email, password, accessToken, linkedStudent}`, `emptyParent: {userId, email, password, accessToken}`, `students.declining.parentInviteCode`. `build_phone`/`build_empty_parent_phone` go.
- `web/e2e/seed.ts`, `seed-contract.spec.ts`, `parent-journey.spec.ts` (test (a) drives `/join/<parentInviteCode>` through the three-step parent signup using the dev code and lands on the child's overview).
- Docs: UI spec §G-05 rewritten as "Parent join and sign in" with G-02/G-04 exits updated; a new `BUILD/DECISIONS.md` entry; `PRODUCT.md` parent persona; `docs/deployment.md`; `README` demo-account table; `CHANGELOG.md`; the `lemely.toml.example` OTP comment.

## 7. Testing

- `tests/test_invite_repo.py`: parent mint (both kinds), expiry, reusable never consumed, single-use consumed, revoke ownership, rotate, role mismatch, preview never leaks email or id.
- `tests/test_auth_router.py`: the three parent routes (happy path, wrong code, expired proof token, taken email, dead invite, cooldown); the OTP route tests are deleted.
- `tests/test_auth_service.py`, `tests/test_auth_tokens.py`, `tests/test_web_invites.py`, `tests/test_web_student.py`, `tests/test_parent_repo.py`, `tests/test_authz_matrix_complete.py`, `tests/test_seed.py`, `tests/test_seed_e2e.py`, `tests/test_web_entrypoint.py`, `tests/test_db_schema.py` updated accordingly.
- `web/tests/unit`: `joinWithCode.test.ts`, `requireAuth.test.ts`, `authOutcome.test.ts`, new `signupParentLogic.test.ts`.
