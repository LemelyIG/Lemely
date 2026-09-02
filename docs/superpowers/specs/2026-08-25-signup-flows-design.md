# Sign-Up Flows for Students & Teachers — Design

**Issue:** [#10](https://github.com/LemelyIG/Lemely/issues/10) (sub-issues
[#11](https://github.com/LemelyIG/Lemely/issues/11) student,
[#12](https://github.com/LemelyIG/Lemely/issues/12) teacher)
**Plan:** `docs/superpowers/plans/2026-08-25-signup-flows.md`
**Date:** 2026-08-25

All three issues were filed title-only — no bodies, no acceptance criteria. This
document is the specification they lack, derived from the codebase, from
`docs/LEMELY_UI_SPEC.md` §4.1, and from an interview recorded in §3.

---

## 1. Problem

**Lemely has no sign-up.** Not a partial one, not a rough one — no route, no
screen, no link. `POST /api/auth/signup` works and is reachable by `curl`;
`AuthContext.signup` is a fully-wired react-query mutation with **zero call
sites**; and every call-to-action on the marketing page navigates to `/login`.
The only accounts that can exist are the ones `lemely/db/seed.py` creates.

That is the headline, but it is not the whole gap. Tracing the account graph
turned up three structural findings that shape everything below.

### 1.1 Teacher accounts are unreachable in production

D1.7 restricts self-service signup to `student` and reserves elevated roles for
"an authenticated admin via the seat/invite flow (later task)". That flow exists:
`POST /api/school/teachers/invite`, gated to `school_admin`, scoped to a school
they hold a membership for. But:

- **No production code path creates a `School` row.** `grep` for `School(` finds
  the model definition, eighteen test files, and nothing else.
- **No production code path creates a `school_admin`.** Only `seed.py`, calling
  `AuthService.signup` directly and bypassing the router's role guard.

So the chain `platform_admin → School → school_admin → teacher` has no first
link. Issue #12 is not a missing form; it is a hole in the account graph.

### 1.2 Two working endpoints have no user interface

- `POST /api/student/classes/join` (join a class by code) is implemented,
  ownership-safe and tested. `ClassRoster.tsx` tells teachers "They enter it from
  the student portal to join" and `Standings.tsx` tells students "Ask your
  teacher for a join code" — and **the student portal has no screen that accepts
  one**.
- `POST /api/school/seats/invite` creates the account outright and returns a
  temporary password once, for the admin to convey out of band. The student
  logs in cold, having never seen which school they joined.

### 1.3 There is no email provider, and three specified screens depend on one

`HttpGoTrueBackend.admin_create_user` sends `email_confirm: True`, so every
account is born verified and G-07 has no backend. There is no password-reset
route, service, table or screen anywhere in the repository — a forgotten
password is a permanently dead account. Both gaps have the same cause: the
invite endpoints hand out temporary passwords *because* nothing can send mail.

### 1.4 Smaller findings

- `users.is_active` defaults to `false`, is **written nowhere and read nowhere**.
  A dead column. Activation in this product is a *subscription* concept
  (`/api/admin/activations/*`), not a user one.
- `docs/LEMELY_UI_SPEC.md` specifies G-02, G-03, G-06, G-07 and G-08. None exist.
- The student onboarding wizard (S-01/S-02) is **fully built and polished** at
  `/student/onboard`, and nothing routes a new account to it. The only path in is
  an action button on the Announcements screen.

---

## 2. Goal

Give students and teachers a real way to create an account, land somewhere
useful, recover from a lost password, and redeem an invite — and close the
account-graph hole that makes teacher accounts unreachable.

Concretely, this delivers the five specified public screens (G-02, G-03, G-06,
G-07, G-08), a platform-admin surface for schools and school admins, a first-run
gate for each of the two roles, and an email seam that mirrors the existing SMS
seam exactly.

---

## 3. Decisions

Twelve decisions were taken by interview before this document was written. They
are recorded here in full; the plan appends them to `BUILD/DECISIONS.md` under a
fresh **D7.x** namespace (the implementer should confirm D7 is still free at the
time of writing and shift the block if not).

| # | Decision | Rationale |
|---|---|---|
| **D7.1** | **Self-service signup is extended to `teacher`, and the admin chain is built.** `_SELF_SERVICE_SIGNUP_ROLES` becomes `{student, teacher}`. | Revises D1.7 item 1 in scope, not in spirit. D1.7's stated risk is that "anyone could POST `role=platform_admin` and mint an admin token" — an *escalation* risk. A self-registered teacher escalates nothing: every teacher service in `lemely/db` is ownership-scoped by construction with no super-role bypass (D1.6/D1.10), so they can only ever see classes they created and students who chose to type their join code. `school_admin` and `platform_admin` remain unobtainable by any anonymous caller. |
| **D7.2** | **A self-registered teacher is always independent.** No school field on the signup form, no `School` row, no membership. | `SchoolClass.school_id` is already nullable precisely for this case (D3.1, MISSION §1: "a teacher can be independent, belong to a school, or both"). A school is a commercial artifact — it carries `seat_quota`, seats and memberships — and self-serve creation would let any visitor mint one with a quota of 0, i.e. unusable until a platform admin intervened anyway. Membership arrives later, by invite. This drops G-03's optional "school or centre name" field; no `teacher_profiles` table is needed. |
| **D7.3** | **Both invite models coexist.** The existing direct-create endpoints stay; redeemable invite *codes* are added alongside them. | Direct-create is genuinely useful for bulk provisioning by an admin who already holds a roster. Redeemable codes are what the UI spec's G-08 describes and what makes a seat feel like joining a school rather than receiving a password over WhatsApp. Neither subsumes the other. |
| **D7.4** | **Email verification state lives in `public.users`, not in GoTrue.** New nullable `users.email_verified_at`; `admin_create_user` keeps `email_confirm: True`. | GoTrue-native confirmation *is* a hard wall — it refuses the password grant until confirmed — and G-07 explicitly calls for "a way to continue into a limited preview of the app rather than a hard wall". Owning the flag is the only way to have login always work while verification still means something. Additive per D1.2. |
| **D7.5** | **Verification soft-gates marking only.** An unverified account can sign in, onboard, browse and read. It cannot `POST /api/student/correct`. | That route is the Gemini spend. Gating it protects the one costly operation without walling off the product, which is exactly the balance G-07 asks for. Uploads are deliberately *not* gated: a student who has photographed a paper should not lose the capture. |
| **D7.6** | **An `EmailProvider` seam mirroring `SmsProvider`, with an offline mock.** Same `delivers_out_of_band` flag, same dev-affordance rule. | `lemely/auth/sms.py` already solved this problem well, and D3.16 already reasoned through when it is safe to return a live credential through the API. Copying that shape means the reasoning carries over unchanged, a real provider drops in with no screen changes, and both new flows are testable end to end offline. |
| **D7.7** | **Verification and reset tokens live in one `auth_tokens` table, not in memory.** | `OtpStore` is a plain in-memory dict; challenges die on restart and break under more than one worker. That is tolerable for a 60-second OTP and not for a reset link someone opens from their email an hour later. One table with a `purpose` enum rather than two near-identical tables: the lifecycle (mint, single-use, expire, revoke-on-password-change) is identical, so one repository serves both. Tokens are stored **hashed** — a database read must not yield a usable credential. |
| **D7.8** | **Platform admins get real screens for schools and school admins.** | D4.10 answered exactly this question for the admin surfaces with "fully build the required screens and completely wire them". Shipping routes alone would recreate the unreachable-endpoint pattern this issue exists to fix (§1.2). |
| **D7.9** | **A student with no `onboardingCompletedAt` is redirected to `/student/onboard` from anywhere in the portal.** | The wizard is built, polished, and near-unreachable. Every downstream surface — study plan, placement invites, subject pages, exam calendar — reads enrolment data that only onboarding writes, so a student who skips it meets correctly-empty screens everywhere and concludes the product is broken. Onboarding already carries its own "Skip for now" affordance for the impatient, so the gate is not a trap. |
| **D7.10** | **A teacher with zero classes is routed to a create-first-class step.** | The role symmetry of D7.9. A class is the teacher's enrolment data: the review queue, at-risk list and class analytics have nothing to scope to without one, and the join code a teacher needs to hand out does not exist until a class does. |
| **D7.11** | **Consent is to `/data`, and it is recorded.** A required checkbox on G-03 linking to the existing data-handling page, plus a nullable `users.terms_accepted_at`. | No terms-of-service document exists in this repository, and PRODUCT.md is explicit that absent things must not be fabricated — so the consent is to the page that genuinely exists and says what happens to a scan. Recording the timestamp makes the acceptance a fact rather than a client-side formality, and the column survives a real ToS later. |
| **D7.12** | **Public auth routes reuse the OTP cooldown pattern.** Per-email cooldown on signup, resend-verification and request-reset, mapped to **429**. | D1.7 item 2 already established both the mechanism and the status code for exactly this abuse shape. Reusing it adds no dependency and closes the cheapest path — an unthrottled endpoint that mints accounts and triggers sends. Per-IP throttling is deliberately out of scope: in-process IP limiting is unreliable behind a proxy and needs real infrastructure to mean anything. |

### 3.1 Explicitly not in scope

- **A real email provider.** The seam and the mock ship; credentials do not.
- **Per-IP rate limiting** (D7.12).
- **Parent sign-up.** Parents authenticate by phone OTP and are linked by their
  child (D3.11). Nothing changes for them beyond G-02 routing them to `/login/parent`.
- **Retiring `users.is_active`.** It stays dead and documented. Dropping a column
  violates D1.2's additive-only guarantee, and repurposing it for verification
  would overload a name that already means something else in `question_bank`.
- **A terms-of-service document** (D7.11).

---

## 4. Architecture

### 4.1 Schema (three additive migrations, `0021`–`0023`)

```
0021_account_lifecycle.py
  users.email_verified_at   timestamptz NULL   -- D7.4
  users.terms_accepted_at   timestamptz NULL   -- D7.11

0022_auth_tokens.py
  authtokenpurpose ENUM ('email_verification', 'password_reset')
  auth_tokens
    id          uuid PK
    user_id     uuid FK users(id) ON DELETE CASCADE
    purpose     authtokenpurpose NOT NULL
    token_hash  text NOT NULL          -- sha256 of the emitted token; never the token
    expires_at  timestamptz NOT NULL
    used_at     timestamptz NULL
    created_at  timestamptz NOT NULL
    INDEX ix_auth_tokens_token_hash (token_hash)          -- the redemption lookup
    INDEX ix_auth_tokens_user_id_purpose (user_id, purpose)  -- revoke-all-for-user

0023_invites.py
  inviterole ENUM ('student', 'teacher')
  invites
    id            uuid PK
    code          text NOT NULL UNIQUE
    role          inviterole NOT NULL
    school_id     uuid NULL FK schools(id) ON DELETE CASCADE
    class_id      uuid NULL FK classes(id) ON DELETE CASCADE
    seat_id       uuid NULL FK seats(id) ON DELETE SET NULL
    created_by    uuid NOT NULL FK users(id)
    expires_at    timestamptz NULL
    redeemed_by   uuid NULL FK users(id) ON DELETE SET NULL
    redeemed_at   timestamptz NULL
    CHECK (school_id IS NOT NULL OR class_id IS NOT NULL)  -- an invite to nothing is not an invite
    INDEX ix_invites_code (code)
```

Every column is nullable or defaulted, every table is new: additive-only per D1.2.
Enum `server_default`s carry an explicit `::type` cast per D1.3.

### 4.2 The email seam

`lemely/auth/email.py`, modelled line-for-line on `lemely/auth/sms.py`:

```python
class EmailProvider(Protocol):
    delivers_out_of_band: bool
    def send_verification(self, email: str, link: str) -> None: ...
    def send_password_reset(self, email: str, link: str) -> None: ...

class MockEmailProvider:
    delivers_out_of_band = False   # logs the link; the API may surface it
```

`delivers_out_of_band` gates whether the API may return `devLink` in a response,
under exactly D3.16's reasoning for `devCode`. Any real provider **must** set it
`True`. `deps.py` wires `MockEmailProvider()` unconditionally, matching how
`MockSmsProvider` is wired today; the note in `routes.tsx` about the SMS mock's
honesty problem applies here too, and the screens must not claim a mail was sent
when the configured provider does not deliver.

### 4.3 API surface

| Method | Route | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/auth/signup` | public | **Modified.** Accepts `student` and `teacher` (D7.1); takes `acceptedTerms: bool` (D7.11); per-email cooldown (D7.12); mints and sends a verification token |
| `POST` | `/api/auth/verify-email` | public | Redeem a verification token → sets `users.email_verified_at` |
| `POST` | `/api/auth/verify-email/resend` | authed | Re-mint and re-send; cooldown → 429 |
| `POST` | `/api/auth/password-reset/request` | public | Always 200 (never reveals whether the address exists); cooldown → 429 |
| `POST` | `/api/auth/password-reset/confirm` | public | Redeem token + set password; revokes all outstanding tokens **and all device sessions** |
| `GET` | `/api/invites/{code}` | public | G-08 preview: what am I joining? Resolves an `invites.code` **or** a `classes.join_code` |
| `POST` | `/api/invites/{code}/redeem` | authed | Assign the seat / enrol in the class; idempotent |
| `POST` | `/api/school/seats/invite-code` | school_admin | Mint a redeemable seat invite (reserves a seat) |
| `POST` | `/api/school/classes/{id}/invite-code` | teacher, school_admin | Mint a redeemable class invite |
| `GET` | `/api/admin/schools` | platform_admin | List schools with quota and usage |
| `POST` | `/api/admin/schools` | platform_admin | Create a school with a seat quota |
| `PATCH` | `/api/admin/schools/{id}` | platform_admin | Update name / quota |
| `POST` | `/api/admin/schools/{id}/admins` | platform_admin | Create a `school_admin` account + membership |

`POST /api/student/correct` gains a **403** when `email_verified_at IS NULL` (D7.5).

Two anti-enumeration rules carry over from the existing surface and are binding:
`password-reset/request` answers 200 whether or not the address exists, and the
signup conflict for an already-registered address is worded to offer a route to
sign in without confirming the address is held (mirroring `signInFailureMessage`'s
deliberate vagueness in `lib/authOutcome.ts`).

### 4.4 Frontend routes

```
/signup                 G-02  role selection (student · teacher · parent → /login/parent)
/signup/student         G-03  details, student variant
/signup/teacher         G-03  details, teacher variant
/verify-email           G-07  pending; resend; dev-affordance link when mocked
/verify-email/:token    G-07  confirm → role home
/reset                  G-06  request by email
/reset/:token           G-06  set a new password
/join                   G-08  enter a code
/join/:code             G-08  deep-linked preview → redeem, or → /signup with the code retained
```

All nine are public and wrapped in `LoginRoute` where a signed-in visitor should
be bounced to their portal, exactly as `/login` is today. Each carries a
`PageMeta` with a description, since these join `/`, `/landing`, `/data`,
`/login` and `/login/parent` as the only routes a signed-out reader can reach —
and each description must claim only what the product does (§3.2 item 10).

### 4.5 First-run gates

Both gates live in the portal layout, not in the router, because both depend on
data fetched after the session resolves:

- **Student** (`portals/student/index.tsx`): `useStudentProfile()` →
  `onboardingCompletedAt == null` and not already on `/student/onboard` →
  `<Navigate to="/student/onboard" replace />`. Renders the existing route
  fallback while the query is pending — never a redirect on `undefined`, which
  would bounce a returning student on every cold load.
- **Teacher** (`portals/teacher/index.tsx`): `useClasses()` → `classes.length === 0`
  and not already on the first-class route → redirect. Same pending rule.

### 4.6 Copy ownership

Every failure string on the new screens goes through a module in the
`lib/*Outcome.ts` family, never `error.message`. This is not a stylistic
preference: the redesign found seven separate screens rendering raw server
detail, including a parent shown `OTP verification failed: wrong_code` and a
student shown a camelCase JSON key. `lib/authOutcome.ts` exists and is extended
here rather than duplicated.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| **D7.1 widens who can hold `teacher`.** A bad actor self-registers, creates a class, and shares its code publicly. | They receive only students who chose to type that code, and the code reveals nothing about anyone until it is used. Every teacher service is ownership-scoped (D1.6/D1.10). The blast radius is a class the actor created; it does not touch another teacher's students, another school's data, or any admin surface. Recorded as the accepted cost of D7.1. |
| **The mock email provider means no verification mail is actually sent.** | Same posture as the SMS mock, and the same honesty rule: `delivers_out_of_band` gates the dev affordance, and no screen or page description may claim a mail was sent. The G-07 screen must read from that flag rather than hardcoding either claim. |
| **The student onboarding gate could trap an account.** A profile fetch that errors would redirect forever. | The gate redirects only on a *resolved* profile with a null completion timestamp; a pending or errored query renders the portal. Pinned by a unit test in both directions. |
| **`0023`'s partial FKs** (`school_id`/`class_id` both nullable) admit an invite to nothing. | The `CHECK` constraint makes that a rejected insert rather than a row the redemption path has to defend against — the "idempotency is enforced by the database, not by care" rule the `friendships` table already follows. |
| **Reset revokes every device session.** A user who resets a password is signed out on all three devices. | Deliberate, and the correct behaviour when the reason for the reset may be a compromise. The G-06 success screen says so plainly rather than letting it be discovered. |

---

## 6. Acceptance

- A visitor can reach `/signup` from the marketing page, create a student
  account, and land in onboarding.
- A visitor can create a teacher account and land in the create-first-class step,
  ending with a join code they can hand out.
- An unverified student is refused at `POST /api/student/correct` with a message
  that routes them to resend verification, and is refused nowhere else.
- A student who has forgotten their password can request a reset, follow the
  link (or the dev affordance), set a new password, and sign in — with all prior
  sessions revoked.
- A platform admin can create a school, set its quota, and create a school_admin
  for it, entirely from the web surface.
- A school admin can mint a seat invite code; a visitor holding it sees the
  school's name before committing, and signs up straight into the seat.
- A student holding a class join code can redeem it from `/join` — closing §1.2.
- `POST /api/auth/signup` with `role` of `school_admin` or `platform_admin` is
  still a **403**, and a test asserts it.
