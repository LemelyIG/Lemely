# Verify-email banner

## Purpose

An account whose email is unverified cannot mark a paper. `POST
/api/student/correct` is guarded by `require_verified_email`
(`lemely/web/deps.py:826`), D7.5's soft gate over Gemini spend, and it answers
`403 {"code": "email_unverified"}`. Nothing in the product says so before the
run is attempted, and nothing says so anywhere else at all.

This design adds one banner, mounted in all four portal layouts, that tells a
signed-in reader their address is unverified and links them to the screen that
fixes it. It is dismissible everywhere except the correction screen, where it
stays put and the marking button is disabled beside it.

## Current state

### The gate is real and reachable today

Reproduced against staging on 2026-09-04 with a signed-in student and a 4.4MB
paper: `POST /api/student/uploads` returned 200, `POST /api/student/correct`
returned `403 {"detail":{"code":"email_unverified"}}` on two consecutive
attempts. The upload transport was sound (three further direct uploads of the
same file, all 200). Marking was blocked purely by the verification gate.

A companion fix on this branch teaches `correctionFailureMessage`
(`web/src/lib/correctionOutcome.ts`) to recognise the marker and say "Verify
your email before you can do that", instead of the generic "turned this run
down and didn't say why" it produced before. That fix answers the failure
*after* a run is refused. This design answers the same fact *before* one is
started, and in the rest of the app.

### No API exposes verification state

`ProfileDTO` (`lemely/web/schemas_me.py:35`, served by `GET /api/me/profile` at
`routers/me.py:211`) carries `displayName`, `email` and `role`. It does not
carry verification state, and no other route does either. The Supabase access
token carries none: its claims are `sub`, `aud`, `role`, `iat`, `exp`,
`app_metadata` (`role`, `provider`), `email` and `session_id`.

`users.email_verified_at` exists on the model (`lemely/db/models/users.py:43`)
and is what the gate itself reads. It is simply never published.

### There is an established banner pattern to follow

`OfflineBanner` (`web/src/components/ui/offline-banner.tsx`) is a slim strip
mounted at the top of `<main>` in all four portal layouts — student
(`portals/student/index.tsx:719`), teacher (`:474`), parent (`:303`) and admin
(`:367`). It sets the conventions this design adopts:

- Split in two, so the markup can be looked at without faking global state:
  `OfflineBannerView` is hookless and is what the dev-preview kit renders;
  `OfflineBanner` is the gated wrapper the layouts mount.
- Amber/neutral, never red, per PRODUCT.md's accessibility section.
- `role="status"`, not `role="alert"` — it must not interrupt a screen reader
  mid-sentence.
- Its own `mb-6`, so a caller adds no margined wrapper that would occupy
  layout on every render where there is no banner.

### The correction screen already has one gate

`canStartRun` (`web/src/lib/uploadRun.ts`) is the single pure function deciding
whether a marking run may begin. `CorrectPaper.tsx` calls it once (`:566`) and
feeds both start buttons from the result (`:611`, `:804`). It lives outside the
component for the reason every `*Outcome.ts` module does: the web test runner is
`environment: "node"` with no jsdom, so a rule inside a component can only be
checked by reading its source.

## Decisions

### D1 — Publish a boolean, not the timestamp

`ProfileDTO` gains `emailVerified: bool`, set as `user.email_verified_at is not
None`. The client only ever asks the yes/no question. Shipping the date would
invite a screen to render "verified on 3 March", which nobody asked for and
which would then have to be maintained as a user-facing fact.

No migration: the column already exists.

### D2 — Ride the profile query already in flight

The banner reads `useProfile()` (`lib/hooks/useMeApi.ts`). Student and teacher
shells already call it for their sidebar identity block, and react-query dedupes
the rest, so the parent and admin shells gain one cached request rather than a
new endpoint. A dedicated `/api/me/verification` route was rejected: it would be
a second round trip for one boolean that belongs on the profile the app already
loads.

### D3 — Silence while the answer is unknown

The banner renders only when `useProfile()` has resolved **and**
`emailVerified === false`. A pending or errored profile renders nothing. A nag
that flashes at someone whose profile has not loaded yet, or whose profile
request failed, is worse than no nag: it accuses the reader of something the app
does not actually know.

### D4 — All four portals

The banner mounts in the student, teacher, parent and admin layouts.
`require_verified_email` guards exactly one route today, which only students
call, so for the other three roles this is a reminder about account hygiene
rather than about a wall they will hit. That is the product owner's decision:
one rule, no surprises, and verification matters for account recovery
independently of the marking gate.

It does **not** mount in the auth or marketing shells. Telling someone to verify
their email on the verify-email screen is noise.

### D5 — Dismissal lasts until the tab closes

`sessionStorage`, one key, read and written through a try/catch wrapper in the
spirit of `staleChunk.ts` (`:139` — private browsing and a full quota both make
storage throw). A storage failure degrades to "not dismissed": the banner shows.
It never crashes the shell it is mounted in.

Per-device-forever and a 7-day return were both rejected. The correction screen
enforces the point where it actually matters, so the reminder elsewhere can be
gentle; and a dismissal that self-renews on the next visit needs no stored
timestamp, no clock, and no boundary test.

### D6 — The banner links, it does not resend

The banner states the situation and links to `/verify-email`. `VerifyEmail.tsx`
already owns the resend, its 429 cooldown wording (`AUTH_COOLDOWN_ACTIVE`), and
the sent and failed states. Putting a resend button in a strip that renders on
every page would duplicate all of that into a second place that can disagree
with the first about what a 429 means.

### D7 — The banner owns its own sentence

It does not reuse `AUTH_EMAIL_UNVERIFIED`. That constant answers "why did that
fail" at the moment of a refusal. This banner answers "here is a standing fact
about your account", which is a different sentence to a reader even though it is
the same underlying condition.

Copy must clear `npm run check:copy` (MISSION §3.2 item 10: no em-dashes in UI
copy).

### D8 — One mount, route-aware

The banner is mounted once per portal layout, never twice, and never separately
by `CorrectPaper`. On `/student/correct` it renders without a dismiss control
and ignores any dismissal stored earlier in the session. Placement and wording
are identical to every other page; the only difference is that the dismiss
control is absent.

Rejected: a second instance mounted inside the marking panel, which would state
the same fact twice on one screen, and a panel-only variant, which would make
that one screen structurally unlike every other for no reason.

### D9 — The disabled button goes through `canStartRun`

`canStartRun` gains an `emailVerified: boolean` input and returns `false` when
it is `false`. The rule does not go into JSX. `CorrectPaper` calls the function
once and both start buttons already read its result, so both are covered by one
change, and the rule stays pinnable in a node test.

The disabled button needs no tooltip of its own: the non-dismissible banner
directly above it is the explanation, which is the reason D8 keeps the banner on
that screen rather than moving it into the panel.

## Components

| Unit | Responsibility | Depends on |
| --- | --- | --- |
| `ProfileDTO.emailVerified` | Publishes the one fact | `users.email_verified_at` |
| `verifyEmailBannerDismissal.ts` | Session-scoped dismissal, storage failures absorbed | `sessionStorage` |
| `VerifyEmailBannerView` | Markup only, hookless, preview-kit renderable | none |
| `VerifyEmailBanner` | Gates the view on profile state, route and dismissal | `useProfile`, `useLocation`, dismissal module |
| `canStartRun` | Whether marking may begin | pure |

## Data flow

1. A portal layout renders `<VerifyEmailBanner />` at the top of `<main>`.
2. It reads `useProfile()`. Pending or errored renders nothing (D3).
3. `emailVerified === true` renders nothing.
4. Otherwise it asks whether the current route is the correction screen. If so,
   it renders the view with no dismiss control. If not, it renders the view with
   one, unless this session has already dismissed it.
5. `CorrectPaper` separately passes `emailVerified` into `canStartRun`, which
   disables both start buttons while it is `false`.

## Error handling

- Profile request fails: no banner, no error surfaced. The banner is not
  important enough to report its own failure to a reader who came to do
  something else.
- `sessionStorage` throws on read or write: treated as "not dismissed" and, for
  a write, the dismissal simply does not persist. The click still hides the
  banner for that render.
- The backend field is missing (an old server against a new client): the client
  type makes `emailVerified` required, so this is a deploy-order concern, not a
  runtime branch. The pipeline already guarantees the safe order —
  `deploy-frontend` declares `needs: [resolve-env, deploy-backend]`
  (`.github/workflows/deploy.yml:315`), so the new field is being served before
  any client that reads it is published.

## Testing

Backend (pytest):

- `GET /api/me/profile` returns `emailVerified: true` for a stamped user and
  `false` for an unstamped one.

Frontend (vitest, `environment: "node"`):

- `canStartRun`: `emailVerified: false` blocks a start that every other input
  would allow; `true` changes none of the existing outcomes.
- Dismissal module: stores and reads back; a throwing storage reads as
  "not dismissed" and a throwing write does not propagate.
- Banner gating, as a pure decision function so it is testable without jsdom:
  hidden when verified, hidden while pending, hidden when errored, shown when
  unverified, dismissible off the correction route, non-dismissible on it, and
  a stored dismissal ignored on it.

Copy gate: `npm run check:copy` must pass for the new strings.

Note: `web/src/lib/grades.ts:71` already fails `check:copy` on `develop` (an
em-dash in a `mergeLadders` error string). It is unrelated to this work and is
not fixed here.

## Branch

`feature/verify-email-banner`, cut from `develop`, merged back into `develop`.
It also carries the `correctionOutcome.ts` fix described under "Current state",
which is the same subject seen from the other side.
