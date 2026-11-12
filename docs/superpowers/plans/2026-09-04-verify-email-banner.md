# Verify-email banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell a signed-in reader with an unverified email address that it is unverified, everywhere in the app, and stop the marking screen offering a button that cannot work.

**Architecture:** One boolean is added to `GET /api/me/profile`. One banner component is mounted once in each of the four portal layouts, beside the existing `OfflineBanner`. All of its logic lives in two pure modules (a dismissal store with injectable storage, and a decision function) because the web test runner has no DOM and cannot render components. The disabled marking button goes through `canStartRun`, the pure gate `CorrectPaper` already uses for both of its start buttons.

**Tech Stack:** FastAPI + pydantic + SQLAlchemy (backend), pytest; React 19 + TypeScript + Tailwind + react-router-dom + @tanstack/react-query (frontend), vitest.

Spec: `docs/superpowers/specs/2026-09-04-verify-email-banner-design.md`

## Global Constraints

- Branch is `feature/verify-email-banner`, already cut from `develop`. Do not create another branch and do not merge or push.
- Every commit is signed: `git commit -S`. Conventional messages with scopes (`feat(web):`, `feat(api):`, `test(web):`).
- Run `pre-commit run --all-files` and fix all failures before each commit. Activate the venv first: `source .venv/bin/activate`.
- Frontend unit tests run under `environment: "node"` with **no jsdom**, and vitest only collects `tests/unit/**/*.test.ts` (not `.tsx`). React components therefore cannot be rendered in a test. Every rule worth pinning must live in a `.ts` module outside the component.
- UI copy must contain no em-dash (`—`) and no `–`. `npm run check:copy` enforces this on string literals in `web/src` (comments are stripped before the check).
- `web/src/lib/grades.ts:71` already fails `npm run check:copy` on `develop`. It is not this plan's work. Expect that one pre-existing finding and do not "fix" it here.
- Frontend commands run from `web/`: `npx vitest run`, `npm run typecheck`, `npm run lint`, `npm run check:copy`. Backend commands run from the repo root.
- If `npx vitest` reports `Cannot find package 'vitest'`, run `PUPPETEER_SKIP_DOWNLOAD=1 npm install --no-audit --no-fund` from `web/` first. A plain `npm install` fails on a corrupt `chrome-headless-shell` archive in the puppeteer cache.

---

### Task 1: Publish `emailVerified` on the profile

`users.email_verified_at` already exists and is what `require_verified_email` reads. Nothing publishes it. This adds the one boolean the client needs. No migration.

**Files:**
- Modify: `lemely/web/schemas_me.py:35-51` (`ProfileDTO`)
- Modify: `lemely/web/routers/me.py:211` (the `return ProfileDTO(...)`)
- Modify: `tests/test_web_me.py:101-113` (`_seed_user`)
- Test: `tests/test_web_me.py` (new tests after the existing profile tests, which end at line 469)

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/me/profile` responds with `emailVerified: bool`, `true` exactly when `users.email_verified_at is not None`.

- [ ] **Step 1: Give the seed helper a way to stamp verification**

`_seed_user` currently cannot create a verified user. Extend it the same way `display_name` was added, with a default that leaves every existing caller untouched.

In `tests/test_web_me.py`, replace lines 101-113 with:

```python
def _seed_user(
    sm: sessionmaker[Session],
    role: Role,
    display_name: str | None = None,
    email_verified_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a real ``users`` row — ``notification_preferences.user_id`` FKs to it,
    so any test that actually writes a preferences row (not just reads the
    all-defaults value) needs a real user to satisfy the constraint.

    ``display_name`` defaults to ``None`` (unset by every pre-existing caller
    of this helper) so the profile tests can seed the nullable-name case
    without touching any other test in this file. ``email_verified_at``
    defaults to ``None`` for the same reason: an unverified account is what
    every pre-existing caller already meant.
    """
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                email_verified_at=email_verified_at,
            )
        )
    return uid
```

Ensure `datetime` is imported at the top of the file. If `from datetime import datetime` is not already present, add it (check with `grep -n "^from datetime\|^import datetime" tests/test_web_me.py`; if the file imports `datetime` differently, match the existing style rather than adding a second import).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_web_me.py`, after `test_profile_display_name_is_null_when_unset_not_fabricated` (which ends at line 469):

```python
def test_profile_reports_an_unverified_email_as_unverified(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """D7.5's gate reads ``email_verified_at``; nothing published it until now.

    Without this field the app cannot tell a reader their address is
    unverified before ``POST /student/correct`` refuses the run, which is the
    whole reason the verify-email banner exists.
    """
    user = _seed_user(pg_sessionmaker, Role.student)
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    assert resp.json()["emailVerified"] is False


def test_profile_reports_a_verified_email_as_verified(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A boolean, never the timestamp: the client only asks the yes/no question."""
    user = _seed_user(
        pg_sessionmaker,
        Role.student,
        email_verified_at=datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
    )
    _use_user_mirror(client, pg_sessionmaker)
    _auth_as(client, user, Role.student)

    resp = client.get("/api/me/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["emailVerified"] is True
    # The date itself is deliberately not published. Shipping it would invite a
    # screen to render "verified on 3 March", which nobody asked for and which
    # would then have to be maintained as a user-facing fact.
    assert "emailVerifiedAt" not in body
```

Ensure `timezone` is imported alongside `datetime`.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_web_me.py -k "emailVerified or verified_email or email_as_verified or email_as_unverified" -v
```

Expected: both new tests FAIL with `KeyError: 'emailVerified'`.

- [ ] **Step 4: Add the field to the DTO**

In `lemely/web/schemas_me.py`, in `ProfileDTO`, replace the field block (lines 49-51) with:

```python
    displayName: str | None = None
    email: str
    role: str
    emailVerified: bool
```

And extend the class docstring, after the sentence ending "never a fabricated name.", with:

```
    ``emailVerified`` is ``users.email_verified_at is not None`` and nothing
    more. D7.5's soft gate (``deps.require_verified_email``) reads that column
    to refuse ``POST /student/correct``, and until this field existed no route
    and no token claim published the fact, so the app could only discover it
    by being refused. A boolean rather than the timestamp on purpose: the
    client only ever asks the yes/no question, and publishing the date would
    invite a screen to render it as a user-facing fact.
```

- [ ] **Step 5: Populate it in the route**

In `lemely/web/routers/me.py`, replace line 211:

```python
    return ProfileDTO(displayName=user.display_name, email=user.email, role=user.role.value)
```

with:

```python
    return ProfileDTO(
        displayName=user.display_name,
        email=user.email,
        role=user.role.value,
        emailVerified=user.email_verified_at is not None,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_web_me.py -v
```

Expected: PASS, including the two new tests and every pre-existing profile test.

- [ ] **Step 7: Run the wider backend suite for this router**

```bash
pytest tests/test_web_me.py tests/test_authz_matrix_complete.py tests/test_auth_router.py -q
```

Expected: PASS. If another test constructs `ProfileDTO` directly it will now fail on the missing required field; fix it by passing `emailVerified=False`.

- [ ] **Step 8: Commit**

```bash
source .venv/bin/activate
pre-commit run --all-files
git add lemely/web/schemas_me.py lemely/web/routers/me.py tests/test_web_me.py
git commit -S -m "feat(api): publish emailVerified on the profile

D7.5's gate reads users.email_verified_at to refuse POST /student/correct,
and no route or token claim published it, so the app could only learn an
address was unverified by being refused. A boolean, never the timestamp: the
client only asks the yes/no question."
```

---

### Task 2: Session-scoped dismissal store

A pure module with injectable storage, so it is testable with no real `sessionStorage` under vitest's node environment. Mirrors `ChunkGuardStorage` (`lib/staleChunk.ts:83`), including its rule that a storage throw degrades to the safe behaviour rather than propagating.

**Files:**
- Create: `web/src/lib/verifyEmailDismissal.ts`
- Test: `web/tests/unit/verifyEmailDismissal.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `export type BannerStorage = Pick<Storage, "getItem" | "setItem">`, `export const VERIFY_EMAIL_DISMISS_KEY: string`, `export function readDismissed(storage: BannerStorage | undefined): boolean`, `export function writeDismissed(storage: BannerStorage | undefined): void`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/verifyEmailDismissal.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  readDismissed,
  VERIFY_EMAIL_DISMISS_KEY,
  writeDismissed,
  type BannerStorage,
} from "@/lib/verifyEmailDismissal"

/*
 * The banner's dismissal is session-scoped and must never be the reason a
 * portal shell crashes. Safari private browsing and a full quota both make
 * storage throw, so every case here is really one rule: a storage that
 * misbehaves reads as "not dismissed" and the banner shows.
 */

function fakeStorage(initial: Record<string, string> = {}): BannerStorage {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => {
      map.set(key, value)
    },
  }
}

const throwingStorage: BannerStorage = {
  getItem: () => {
    throw new Error("SecurityError: storage is disabled")
  },
  setItem: () => {
    throw new Error("QuotaExceededError")
  },
}

describe("readDismissed", () => {
  it("is false for a fresh session", () => {
    expect(readDismissed(fakeStorage())).toBe(false)
  })

  it("is true once a dismissal has been written", () => {
    const storage = fakeStorage()
    writeDismissed(storage)
    expect(readDismissed(storage)).toBe(true)
  })

  it("reads a throwing storage as not dismissed, so the banner still shows", () => {
    expect(readDismissed(throwingStorage)).toBe(false)
  })

  it("reads an absent storage as not dismissed", () => {
    // Server-side rendering, or a browser where `sessionStorage` is not
    // exposed at all. Neither is a reason to hide the banner.
    expect(readDismissed(undefined)).toBe(false)
  })

  it("ignores a value that is not the stored marker", () => {
    expect(readDismissed(fakeStorage({ [VERIFY_EMAIL_DISMISS_KEY]: "maybe" }))).toBe(false)
  })
})

describe("writeDismissed", () => {
  it("does not throw when storage refuses the write", () => {
    expect(() => writeDismissed(throwingStorage)).not.toThrow()
  })

  it("does not throw when there is no storage at all", () => {
    expect(() => writeDismissed(undefined)).not.toThrow()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npx vitest run tests/unit/verifyEmailDismissal.test.ts
```

Expected: FAIL — cannot resolve `@/lib/verifyEmailDismissal`.

- [ ] **Step 3: Write the implementation**

Create `web/src/lib/verifyEmailDismissal.ts`:

```ts
/*
 * Whether this session has dismissed the verify-email banner.
 *
 * `sessionStorage`, not `localStorage`, and that is the whole of decision D5:
 * the dismissal lasts the visit and the banner returns next time the app is
 * opened. The correction screen enforces the point where it actually matters
 * (it renders the banner un-dismissibly and disables the marking button), so
 * the reminder everywhere else can afford to be gentle, and a dismissal that
 * self-renews needs no stored timestamp, no clock, and no boundary test.
 *
 * The storage is a parameter rather than a global for the reason
 * `StaleChunkGuard` takes one (`lib/staleChunk.ts:83`): the web test runner is
 * `environment: "node"` with no `sessionStorage` at all, and a module that
 * reached for a global could only be checked by reading its source.
 *
 * Every access is wrapped. Safari private browsing and a full quota both make
 * storage throw on `setItem`, and some private-mode configurations throw on
 * `getItem` too. A throw here must never be the reason a portal shell fails to
 * render, so it degrades to "not dismissed": the banner shows. Showing a
 * banner one time too many is a strictly better failure than a blank app.
 */

/** The slice of `Storage` this module uses, so a test can pass a two-method
 * fake rather than implementing the whole interface. */
export type BannerStorage = Pick<Storage, "getItem" | "setItem">

export const VERIFY_EMAIL_DISMISS_KEY = "lemely:verify-email-banner-dismissed"

/** The only value treated as a dismissal. Anything else in the slot (a
 * half-written value, another tool's key collision) reads as not dismissed. */
const DISMISSED = "1"

/** Whether this session has dismissed the banner. False whenever the answer
 * cannot be read, including when there is no storage at all. */
export function readDismissed(storage: BannerStorage | undefined): boolean {
  if (!storage) return false
  try {
    return storage.getItem(VERIFY_EMAIL_DISMISS_KEY) === DISMISSED
  } catch {
    return false
  }
}

/** Record a dismissal for the rest of this session. Silent on failure: the
 * caller has already hidden the banner in component state, so a storage that
 * refuses the write costs only the persistence, not the interaction. */
export function writeDismissed(storage: BannerStorage | undefined): void {
  if (!storage) return
  try {
    storage.setItem(VERIFY_EMAIL_DISMISS_KEY, DISMISSED)
  } catch {
    // Deliberately empty. See the module header.
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run tests/unit/verifyEmailDismissal.test.ts
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/verifyEmailDismissal.ts web/tests/unit/verifyEmailDismissal.test.ts
git commit -S -m "feat(web): session-scoped dismissal store for the verify-email banner

Injectable storage so it is testable under the node-environment runner, and
every access wrapped: a storage that throws reads as not dismissed, because
showing the banner once too often beats a portal shell that will not render."
```

---

### Task 3: The banner's decision function and the client type

The component cannot be tested (no jsdom, and vitest collects only `.test.ts`), so every rule about *when* the banner appears lives here, as a pure function.

**Files:**
- Modify: `web/src/lib/meTypes.ts:13-17` (the `Profile` interface)
- Create: `web/src/lib/verifyEmailBanner.ts`
- Test: `web/tests/unit/verifyEmailBanner.test.ts`

**Interfaces:**
- Consumes: `readDismissed` from Task 2 is *not* used here; this function takes an already-resolved `dismissed` boolean so it stays pure.
- Produces: `export const CORRECTION_PATH = "/student/correct"`, `export type VerifyEmailBannerState = "hidden" | "dismissible" | "pinned"`, `export function verifyEmailBannerState(input: { emailVerified: boolean | undefined; pathname: string; dismissed: boolean }): VerifyEmailBannerState`.

- [ ] **Step 1: Add the field to the client type**

In `web/src/lib/meTypes.ts`, replace the `Profile` interface (lines 13-17) with:

```ts
export interface Profile {
  displayName: string | null
  email: string
  role: string
  /**
   * `users.email_verified_at is not None`, published by `ProfileDTO` for the
   * verify-email banner. Required, not optional: the pipeline deploys the
   * backend before the frontend (`deploy-frontend` declares
   * `needs: [resolve-env, deploy-backend]` in `.github/workflows/deploy.yml`),
   * so a client that reads this field is never published against a server
   * that does not serve it.
   */
  emailVerified: boolean
}
```

Also extend the interface's existing doc comment above it so it still describes the whole shape: after the sentence ending "never a fabricated name.", add `` `emailVerified` is D7.5's gate condition, read by the verify-email banner. ``

- [ ] **Step 2: Write the failing test**

Create `web/tests/unit/verifyEmailBanner.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  CORRECTION_PATH,
  verifyEmailBannerState,
  type VerifyEmailBannerState,
} from "@/lib/verifyEmailBanner"

/*
 * Every rule about when the verify-email banner appears. It lives in a pure
 * function rather than in the component because the web runner is
 * `environment: "node"` with no jsdom and collects only `.test.ts`, so a rule
 * inside a component could only be checked by reading its source.
 */

function state(
  over: Partial<Parameters<typeof verifyEmailBannerState>[0]> = {},
): VerifyEmailBannerState {
  return verifyEmailBannerState({
    emailVerified: false,
    pathname: "/student/overview",
    dismissed: false,
    ...over,
  })
}

describe("verifyEmailBannerState", () => {
  it("shows a dismissible banner to an unverified reader", () => {
    expect(state()).toBe("dismissible")
  })

  it("shows nothing to a verified reader", () => {
    expect(state({ emailVerified: true })).toBe("hidden")
  })

  it("shows nothing while the profile is still unknown", () => {
    // `useProfile()` pending, or errored. A nag that flashes at someone whose
    // profile has not loaded accuses them of something the app cannot yet
    // know, which is worse than saying nothing.
    expect(state({ emailVerified: undefined })).toBe("hidden")
  })

  it("stays hidden once dismissed this session", () => {
    expect(state({ dismissed: true })).toBe("hidden")
  })

  it("pins the banner on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH })).toBe("pinned")
  })

  it("ignores an earlier dismissal on the correction screen", () => {
    // The one screen the gate actually blocks. A dismissal made on the
    // overview must not hide the reason the marking button is disabled here.
    expect(state({ pathname: CORRECTION_PATH, dismissed: true })).toBe("pinned")
  })

  it("does not pin for a verified reader on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH, emailVerified: true })).toBe("hidden")
  })

  it("does not pin while the profile is unknown on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH, emailVerified: undefined })).toBe("hidden")
  })

  it("does not pin on a path that merely starts with the correction path", () => {
    // A future `/student/correction-history` must not inherit the pinned
    // behaviour by accident.
    expect(state({ pathname: "/student/correcting" })).toBe("dismissible")
    expect(state({ pathname: `${CORRECTION_PATH}/history` })).toBe("dismissible")
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd web && npx vitest run tests/unit/verifyEmailBanner.test.ts
```

Expected: FAIL — cannot resolve `@/lib/verifyEmailBanner`.

- [ ] **Step 4: Write the implementation**

Create `web/src/lib/verifyEmailBanner.ts`:

```ts
/*
 * When the verify-email banner appears, and in which of its two forms.
 *
 * Split out of the component for the reason every `*Outcome.ts` module in this
 * codebase exists: the web test runner is `environment: "node"` with no jsdom
 * and collects only `tests/unit/**\/*.test.ts`, so logic inside a component can
 * only be pinned by reading its source, and a source-reading gate cannot tell
 * a rule that works from a rule that merely still has the right words in it.
 *
 * Two things this deliberately does NOT do. It does not read storage (the
 * caller resolves `dismissed` and passes it, so this stays a pure function of
 * its inputs), and it does not treat "unknown" as "unverified" — see
 * `emailVerified` below.
 */

/**
 * The one route where the banner is pinned. Matched exactly, never by prefix:
 * a future `/student/correction-history` would otherwise inherit a
 * non-dismissible banner and a disabled button by accident.
 */
export const CORRECTION_PATH = "/student/correct"

/**
 * - `hidden` — render nothing at all, including no margin.
 * - `dismissible` — the ordinary strip, with a dismiss control.
 * - `pinned` — the same strip with no dismiss control, and any dismissal
 *   already stored for this session ignored.
 */
export type VerifyEmailBannerState = "hidden" | "dismissible" | "pinned"

export function verifyEmailBannerState({
  emailVerified,
  pathname,
  dismissed,
}: {
  /**
   * `undefined` while `useProfile()` is pending, and when it errored. Both
   * mean the app does not know, and not knowing is not the same as knowing
   * the address is unverified: a banner that appears during a load, or
   * because a request failed, tells the reader something the app has not
   * established. Only an explicit `false` shows the banner.
   */
  emailVerified: boolean | undefined
  pathname: string
  dismissed: boolean
}): VerifyEmailBannerState {
  if (emailVerified !== false) return "hidden"
  // Checked before `dismissed` on purpose: this is the screen the gate
  // actually blocks, and the banner is the explanation for the disabled
  // marking button sitting under it.
  if (pathname === CORRECTION_PATH) return "pinned"
  if (dismissed) return "hidden"
  return "dismissible"
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
npx vitest run tests/unit/verifyEmailBanner.test.ts
```

Expected: PASS, 9 tests.

- [ ] **Step 6: Typecheck**

```bash
npm run typecheck
```

Expected: no output (success). No `Profile` object literal exists in `web/tests` today, so this should be clean; if a future fixture does build one it will fail on the missing `emailVerified`, which is fixed by adding `emailVerified: true` unless that test is about verification.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/meTypes.ts web/src/lib/verifyEmailBanner.ts web/tests/unit/verifyEmailBanner.test.ts
git commit -S -m "feat(web): decide when the verify-email banner appears

A pure function, because the node-environment runner cannot render a
component. Unknown is not unverified: a pending or errored profile shows
nothing rather than accusing a reader of something the app has not
established."
```

---

### Task 4: The banner component

Follows `offline-banner.tsx` exactly, including its split into a hookless view for the dev-preview kit and a gated wrapper for the layouts.

**Files:**
- Create: `web/src/components/ui/verify-email-banner.tsx`
- Modify: `web/dev-previews/App.tsx` (import near line 36, and a cell in the states section near line 1383)

**Interfaces:**
- Consumes: `verifyEmailBannerState`, `CORRECTION_PATH` (Task 3); `readDismissed`, `writeDismissed` (Task 2); `Profile.emailVerified` (Task 3); `useProfile` from `@/lib/hooks/useMeApi`.
- Produces: `export function VerifyEmailBannerView({ onDismiss }: { onDismiss?: () => void }): JSX.Element` and `export function VerifyEmailBanner(): JSX.Element | null`.

- [ ] **Step 1: Write the component**

Create `web/src/components/ui/verify-email-banner.tsx`:

```tsx
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { EnvelopeSimple, X } from "@phosphor-icons/react"
import { useProfile } from "@/lib/hooks/useMeApi"
import { verifyEmailBannerState } from "@/lib/verifyEmailBanner"
import { readDismissed, writeDismissed } from "@/lib/verifyEmailDismissal"

/*
 * "Your email is not verified yet", mounted once in each of the four portal
 * layouts beside `OfflineBanner`, whose conventions this follows to the
 * letter: amber/neutral rather than red (PRODUCT.md's accessibility section),
 * `role="status"` rather than `alert` so it never interrupts a screen reader
 * mid-sentence, and its own `mb-6` so that rendering nothing costs nothing in
 * layout instead of leaving an empty margined element on every page.
 *
 * Why it exists: `POST /student/correct` is guarded by D7.5's
 * `require_verified_email`, and before this the product said nothing about
 * that until the run had already been refused. `correctionOutcome.ts` now
 * words that refusal properly; this says it first, and everywhere.
 *
 * Why it links rather than resending: `VerifyEmail.tsx` already owns the
 * resend, its 429 cooldown wording and its sent/failed states. A resend button
 * in a strip that renders on every page would be a second place that can
 * disagree with the first about what a 429 means.
 *
 * Why it does not reuse `AUTH_EMAIL_UNVERIFIED`: that sentence answers "why
 * did that just fail", at the moment of a refusal. This one answers "here is a
 * standing fact about your account", which is a different thing to read even
 * though the underlying condition is the same.
 *
 * Split in two, exactly as `offline-banner.tsx` is, so the strip can be looked
 * at in the dev-preview kit without a router, a query client or a signed-in
 * session: `VerifyEmailBannerView` is the markup with no hooks;
 * `VerifyEmailBanner` is the one the layouts mount.
 */

export function VerifyEmailBannerView({ onDismiss }: { onDismiss?: () => void }) {
  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center gap-2.5 rounded-md border border-rule bg-paper-sunk px-3.5 py-2.5"
    >
      <EnvelopeSimple size={16} className="text-ink-muted" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-body-sm text-ink">
        <span className="font-medium">Your email isn't verified yet.</span> Verify it to start
        marking papers.
      </p>
      <Link
        to="/verify-email"
        className="shrink-0 text-body-sm text-accent-ink underline decoration-1 underline-offset-2 transition-colors hover:text-accent-hover"
      >
        Verify now
      </Link>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss the email verification reminder"
          className="shrink-0 rounded-sm p-1 text-ink-muted transition-colors hover:text-ink"
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  )
}

export function VerifyEmailBanner() {
  const { data } = useProfile()
  const { pathname } = useLocation()
  /*
   * Seeded from storage once, then owned by React. Reading on every render
   * would be a `sessionStorage` hit per render of every page in the app, and
   * the value cannot change underneath us: this component is the only writer.
   */
  const [dismissed, setDismissed] = useState(() =>
    readDismissed(typeof window === "undefined" ? undefined : window.sessionStorage),
  )

  const state = verifyEmailBannerState({
    emailVerified: data?.emailVerified,
    pathname,
    dismissed,
  })

  if (state === "hidden") return null

  const dismiss = () => {
    setDismissed(true)
    writeDismissed(typeof window === "undefined" ? undefined : window.sessionStorage)
  }

  // `pinned` passes no `onDismiss`, which is what removes the control: the
  // view renders it only when a caller supplies a handler, the same rule
  // `OfflineBannerView` follows for its own "Try again".
  return <VerifyEmailBannerView onDismiss={state === "pinned" ? undefined : dismiss} />
}
```

Both icons are confirmed present: `X` is already imported by `web/src/components/ui/modal.tsx:10`, and `EnvelopeSimple` ships in `@phosphor-icons/react` (`node_modules/@phosphor-icons/react/dist/csr/EnvelopeSimple.d.ts`). No substitution is needed.

- [ ] **Step 2: Register the view in the dev-preview kit**

In `web/dev-previews/App.tsx`, add next to the existing offline-banner import (line 36):

```tsx
import { VerifyEmailBannerView } from "@/components/ui/verify-email-banner"
```

Then, immediately after the `ComponentSection` named "Offline banner" closes (near line 1388), add a sibling section. This mirrors that section's exact structure, including the `w-full` wrapper the cell needs to let the strip fill its cell:

```tsx
<ComponentSection
  name="Verify-email banner"
  summary="`VerifyEmailBanner`, mounted inside every portal layout's main below the offline strip. Shown only once the profile has resolved and says the address is unverified. Dismissible for the session everywhere except `/student/correct`, where the dismiss control is absent and the marking button is disabled beneath it."
>
  <StateCell state="error" provenance="prop" note="VerifyEmailBannerView, dismissible">
    <div className="w-full">
      <VerifyEmailBannerView onDismiss={() => undefined} />
    </div>
  </StateCell>
  <StateCell state="error" provenance="prop" note="VerifyEmailBannerView, pinned on /student/correct">
    <div className="w-full">
      <VerifyEmailBannerView />
    </div>
  </StateCell>
</ComponentSection>
```

Note: `VerifyEmailBannerView` renders a `<Link>`, so this section only mounts inside a router. If the preview kit has no router at this point in the tree, the two cells will throw on render. Check with `grep -n "RouterProvider\|BrowserRouter\|MemoryRouter" web/dev-previews/App.tsx`; if there is none, wrap just these two cells in `<MemoryRouter>` from `react-router-dom` rather than adding a router to the whole kit.

- [ ] **Step 3: Typecheck, lint and the copy gate**

```bash
npm run typecheck && npm run lint && npm run check:copy
```

Expected: typecheck silent; lint reports only the pre-existing `only-export-components` warnings; `check:copy` reports only the pre-existing `src/lib/grades.ts:71` finding. If `check:copy` names `verify-email-banner.tsx`, an em-dash reached the copy: restructure the sentence.

- [ ] **Step 4: Run the whole unit suite**

```bash
npx vitest run
```

Expected: PASS. Nothing in this task is directly covered by a test (a component cannot be rendered here); this run is guarding against an import cycle or a broken module.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/components/ui/verify-email-banner.tsx web/dev-previews/App.tsx
git commit -S -m "feat(web): the verify-email banner itself

Follows offline-banner.tsx to the letter, including the split into a hookless
view the preview kit can render and a gated wrapper the layouts mount. It
links to /verify-email rather than resending, because VerifyEmail.tsx already
owns the resend and its cooldown wording."
```

---

### Task 5: Mount it in the four portal layouts

**Files:**
- Modify: `web/src/portals/student/index.tsx` (import near line 13, mount after the `<OfflineBanner>` at line 719)
- Modify: `web/src/portals/teacher/index.tsx` (import near line 5, mount after the `<OfflineBanner>` at line 474)
- Modify: `web/src/portals/parent/index.tsx` (import near line 9, mount after the `<OfflineBanner>` at line 303)
- Modify: `web/src/portals/admin/index.tsx` (import near line 22, mount after the `<OfflineBanner>` at line 367)

**Interfaces:**
- Consumes: `VerifyEmailBanner` (Task 4).
- Produces: nothing further tasks depend on.

- [ ] **Step 1: Add the import to each of the four files**

Beside the existing `OfflineBanner` import in each file:

```tsx
import { VerifyEmailBanner } from "@/components/ui/verify-email-banner"
```

- [ ] **Step 2: Mount it in each of the four files**

In each layout, immediately **after** the closing of the existing `<OfflineBanner ... />` element inside `<main>`, add:

```tsx
{/* Below the offline strip on purpose: connectivity is the transient,
    self-healing message and belongs on top, while this is a standing fact
    about the account. Renders nothing (no margin either) unless the profile
    has resolved and says the address is unverified. */}
<VerifyEmailBanner />
```

Do not pass any props. Do not mount it anywhere else, and in particular do not mount a second copy inside `CorrectPaper` — the single mount is route-aware (decision D8).

- [ ] **Step 3: Typecheck and lint**

```bash
cd web && npm run typecheck && npm run lint
```

Expected: typecheck silent; lint unchanged from the pre-existing warning set.

- [ ] **Step 4: Confirm all four are mounted**

```bash
grep -rn "VerifyEmailBanner" web/src/portals/*/index.tsx
```

Expected: eight lines — one import and one mount in each of student, teacher, parent, admin.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/portals/student/index.tsx web/src/portals/teacher/index.tsx web/src/portals/parent/index.tsx web/src/portals/admin/index.tsx
git commit -S -m "feat(web): mount the verify-email banner in all four portals

One mount per layout, below the offline strip. The banner is route-aware, so
the correction screen does not mount its own copy."
```

---

### Task 6: Disable the marking button while unverified

The rule goes into `canStartRun`, the pure gate `CorrectPaper` already calls once and feeds both start buttons from, not into JSX.

**Files:**
- Modify: `web/src/lib/uploadRun.ts` (the `canStartRun` signature and body)
- Modify: `web/tests/unit/uploadRun.test.ts:90-118` (four existing call sites)
- Modify: `web/src/portals/student/screens/CorrectPaper.tsx` (imports, and the `canStartRun` call at line 566)

**Interfaces:**
- Consumes: `Profile.emailVerified` (Task 3).
- Produces: `canStartRun` gains a required `emailVerified: boolean` field in its argument object.

- [ ] **Step 1: Write the failing tests**

In `web/tests/unit/uploadRun.test.ts`, first add `emailVerified: true` to each of the four existing `canStartRun({...})` calls (lines 93, 105, 111, 117) so they keep asserting what they always asserted. Then append inside the `describe("canStartRun", ...)` block:

```ts
  it("refuses to start while the reader's email is unverified", () => {
    // D7.5's gate would answer 403 `{"code": "email_unverified"}`, so the
    // button would spend a click, an upload's worth of waiting and a stage
    // animation to arrive at a refusal the app already knew about. The
    // pinned banner directly above the button is the explanation.
    expect(
      canStartRun({
        phase: "none",
        hasScan: true,
        hasUploadedPaper: false,
        emailVerified: false,
      }),
    ).toBe(false)
  })

  it("refuses even when the scan is already on the server", () => {
    expect(
      canStartRun({
        phase: "stopped",
        hasScan: false,
        hasUploadedPaper: true,
        emailVerified: false,
      }),
    ).toBe(false)
  })

  it("changes nothing for a verified reader", () => {
    expect(
      canStartRun({ phase: "none", hasScan: true, hasUploadedPaper: false, emailVerified: true }),
    ).toBe(true)
    expect(
      canStartRun({ phase: "waiting", hasScan: true, hasUploadedPaper: true, emailVerified: true }),
    ).toBe(false)
  })
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npx vitest run tests/unit/uploadRun.test.ts
```

Expected: FAIL — the three new tests fail (`emailVerified: false` still returns `true`), and TypeScript reports an unknown property until Step 3 lands.

- [ ] **Step 3: Add the input to `canStartRun`**

In `web/src/lib/uploadRun.ts`, replace the `canStartRun` doc comment's final paragraph and the function with:

```ts
/**
 * Whether a *new* marking run may be started right now.
 *
 * The hard constraint is not a UI nicety. Two runs over one scan would spend a
 * hard-capped Gemini budget twice, write a second attempt row for the same
 * paper, and cross-talk on an event bus that is process-global and
 * single-stream, so both readers would see a mix of the two.
 *
 * `hasScan` is a local file; `hasUploadedPaper` is a scan the server already
 * holds. Either is enough, which is the part that makes a reloaded failure
 * recoverable at all: after a reload the `File` is gone and the scan is not.
 *
 * `emailVerified` is D7.5's soft gate, brought forward. `POST /student/correct`
 * is guarded by `require_verified_email` and answers
 * `403 {"code": "email_unverified"}`, so starting a run for an unverified
 * account spends a click, an upload's worth of waiting and a stage animation
 * to reach a refusal the app already knew was coming. It belongs here rather
 * than in the screen's JSX because the screen calls this once and feeds both
 * of its start buttons from the result, so one input covers both.
 *
 * Note the caller's contract: pass `true` when the answer is not yet known.
 * A pending profile must not disable the button, for the same reason the
 * banner stays hidden while the profile is pending — the app does not know,
 * and acting on what it does not know is how a verified student ends up
 * looking at a dead button during a page load.
 */
export function canStartRun({
  phase,
  hasScan,
  hasUploadedPaper,
  emailVerified,
}: {
  phase: RunPhase
  hasScan: boolean
  hasUploadedPaper: boolean
  emailVerified: boolean
}): boolean {
  if (!emailVerified) return false
  if (phase === "waiting") return false
  return hasScan || hasUploadedPaper
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run tests/unit/uploadRun.test.ts
```

Expected: PASS, including the four pre-existing cases.

- [ ] **Step 5: Wire the screen**

In `web/src/portals/student/screens/CorrectPaper.tsx`, add to the imports:

```tsx
import { useProfile } from "@/lib/hooks/useMeApi"
```

Inside the component, above the existing `const canStart = canStartRun({` at line 566, add:

```tsx
  /*
   * D7.5's gate, read before the run rather than after the refusal. `undefined`
   * (profile pending or errored) counts as allowed: the app does not know, and
   * a verified student must not watch a dead button during a page load. If it
   * guesses wrong the run is refused, and `correctionFailureMessage` now words
   * that refusal properly.
   */
  const profile = useProfile()
  const emailVerified = profile.data?.emailVerified !== false
```

Then replace the `canStartRun` call with:

```tsx
  const canStart = canStartRun({
    phase,
    hasScan: Boolean(scanFile),
    hasUploadedPaper: retryable,
    emailVerified,
  })
```

Both start buttons (`:611` and `:804`) already read `canStart`; they need no change.

- [ ] **Step 6: Run the full suite, typecheck, lint and the copy gate**

```bash
npx vitest run && npm run typecheck && npm run lint && npm run check:copy
```

Expected: all unit tests pass; typecheck silent; lint and `check:copy` report only their pre-existing findings.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely && source .venv/bin/activate && pre-commit run --all-files
git add web/src/lib/uploadRun.ts web/tests/unit/uploadRun.test.ts web/src/portals/student/screens/CorrectPaper.tsx
git commit -S -m "feat(web): don't offer a marking run that D7.5 will refuse

The rule goes through canStartRun, which the screen calls once and feeds both
start buttons from, so one input covers both and stays pinnable in a node
test. Unknown counts as allowed: a pending profile must not disable the
button for a verified student."
```

---

## Manual verification

After Task 6, before opening a PR. This cannot be automated here: the unit runner has no DOM, and the account state lives on staging.

- [ ] Run `cd web && npm run dev` and sign in as an account with an unverified address. Confirm the banner appears on the student overview with a dismiss control, that dismissing hides it, and that navigating around keeps it hidden.
- [ ] Navigate to `/student/correct`. Confirm the banner is present with **no** dismiss control even after the dismissal above, and that "Mark this paper" is disabled once a file is chosen.
- [ ] Reload the tab. Confirm the dismissal SURVIVES the reload: `sessionStorage` is cleared when
  the tab closes, not when the page reloads, so the banner staying hidden here is correct and the
  banner reappearing would be the bug. Open a new tab to see it return.
- [ ] Verify the address, reload, and confirm the banner is gone everywhere and the marking button works.
- [ ] Check the four portals render the banner by signing in as a teacher, parent and admin with unverified addresses, or by temporarily returning `emailVerified=False` from the route.

## Self-review notes

Checked against the spec: D1 (Task 1), D2 (Task 4 wrapper reads `useProfile`), D3 (Task 3 `emailVerified !== false`), D4 (Task 5), D5 (Task 2), D6 (Task 4 links to `/verify-email`), D7 (Task 4 owns its own copy), D8 (Task 3 `CORRECTION_PATH`, Task 5 single mount), D9 (Task 6). Every spec testing bullet has a step. No task references a symbol another task does not define.

One thing the spec left implicit and this plan makes explicit: the spec's D3 says the *banner* stays silent while the profile is unknown, but says nothing about the *button*. Task 6 resolves it the same way and says why — unknown counts as allowed, so a verified student never watches a dead button during a load, and a wrong guess costs one refusal that `correctionOutcome.ts` now words properly.
