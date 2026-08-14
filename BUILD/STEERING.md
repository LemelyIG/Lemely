# STEERING.md — two-way steering log (append-only)

Mirror of the Steering Channel (REDESIGN-MISSION §10). Every outbound DECISION and every
inbound answer or free-text directive is logged here, newest at the bottom. Never edit or
delete an entry; correct by appending.

- **Outbound topic:** `lemely-ErBPK7TIRGD1sQP5` (I publish here)
- **Inbound topic:** `lemely-ErBPK7TIRGD1sQP5-in` (you publish here, from the ntfy app)
- **Server:** `http://home-server:7532`
- **You may also answer by editing this file directly.** File answers and ntfy answers are
  treated identically; the latest timestamp wins.
- Answer format: `D<n>: <letter>` for a DECISION, or free text to steer anything at any time.
  Free text is a directive: it is acknowledged, logged, and applied from the next work unit.

---

## 2026-08-13 — Phase 0, channel established

**OUT** `2026-08-13T14:35:53Z` · title `Steering Channel test` · msg id `EICfuD5oqEGI`
> Redesign Phase 0 is live. Reply on topic lemely-ErBPK7TIRGD1sQP5-in to steer at any time
> (e.g. 'D3: B', or free text). Answers are mirrored to BUILD/STEERING.md.

Delivered, HTTP 200.

**SELFTEST** `2026-08-13T14:36:03Z` · msg id `IOd08AgAn9Hf` · published by me to the *inbound*
topic and polled straight back, to prove the return path works before relying on it for a
timed DECISION. Not a message from the human. Ignore it when reading this log.

Round trip confirmed both ways. `LAST STEERING TS` is set past this selftest so it is never
replayed as a directive.

**No inbound messages from the human yet.** The inbound topic's full history polls empty
apart from the selftest above.

---

## 2026-08-13 — DECISION D1 (audit summary + IA changes)

**OUT** `2026-08-13T15:05Z` · title `DECISION D1 - audit summary + IA changes` · priority high

Phase 1 audit summary sent (3 legs, 48 routes, nothing modified). Full dossier:
`BUILD/DESIGN-AUDIT.md`.

Six IA proposals. **Items 1–5 are cost-free corrections and carry the default
"proceed as proposed" on a 60-minute timeout.** Item 6 (build real school-admin and
platform-admin screens, ~7 new screens plus un-bundling the `TEACHER_ROLES` guard that
`rbac.spec.ts` asserts against) **carries no default** — it is a scope decision about how
much new surface this redesign builds rather than restyles, and §10 says a question with no
sane default must not be a timeout question. Options offered: A build them now / B leave
admins on `/teacher` and defer / C scaffold routes and shells only.

On timeout I proceed with 1–5, continue to Phase 2 (brand and design system, which does not
depend on item 6), and re-ask before Phase 4 reaches admin views.

**IN** — awaiting.

---

## 2026-08-13 — DECISION D2 (logo direction)

**OUT** `2026-08-13T17:32Z` (local +03) · title `DECISION D2 - logo direction` · priority high

Sent **text-only**: this ntfy server returns `40014 attachments not allowed`
(`attachment-cache-dir` is not configured on home-server), so the contact sheet
could not be attached as REDESIGN-MISSION §5.2 assumed. It is committed to the
repo instead, at `BUILD/brand/D2-candidates.jpg`, and the message points there.
Worth fixing on the server if later phases want screenshot attachments — §9's
screenshot cadence assumes attachments work.

Four Gemini candidates plus one refine pass, then a hand-authored SVG. Options
A (ship the hand-authored SVG, **default**) / B (a2) / C (d1) / D (regenerate).
30-minute timeout.

**IN** — awaiting.

---

## 2026-08-13 — D1 and D2 both timed out, defaults applied

**IN** — nothing. The inbound topic has still never carried a message from the
human; the only entry remains my Phase-0 selftest.

- **D1.1–5 DEFAULTED** at 18:10 (+03), 60-minute timeout elapsed: proceed as
  proposed with the five cost-free IA corrections. They are implemented in
  Phase 3.1, not earlier, because they are IA changes and Phase 3 is where IA
  lands.
- **D1.6 REMAINS OPEN** and is deliberately not defaulted (§10: a question with
  no sane default must not be a timeout question). It does not block Phase 2 or
  3. Re-ask before Phase 4 reaches admin views; if it is still unanswered at
  that point, that is where I block rather than guess.
- **D2 DEFAULTED** at 18:10 (+03), 30-minute timeout elapsed: option A, ship the
  hand-authored SVG mark.

Reversing either default is cheap and I will do it on request: D2 is three SVG
files not yet referenced anywhere in the app, and D1.1–5 has not been written
yet at all.

---

## 2026-08-13 — Phase 3 complete

**IN** — nothing, again. The inbound topic has still never carried a message
from the human; the only entry remains my Phase-0 selftest. Polled at every
sub-phase boundary (3.1, 3.2, 3.3, 3.4) and before this gate.

**OUT** — phase start, plus a milestone notice after 3.1 and 3.2.

No new DECISION was raised this phase. Everything Phase 3 found beyond D1.1–5
fell inside its own written mandate ("no dead ends", "per-role navigation that
makes each role's top tasks one obvious step away") or was a straightforward
correction of something untrue, so none of it needed a question:

- Mobile navigation for the student and teacher portals. The audit's D1 list
  could not contain it because the audit read source, not viewports.
- Two cross-portal links that `RequireAuth` bounces for every role.
- A fabricated school name, a hardcoded date, two hardcoded greetings, and two
  "Coming soon" buttons for features that shipped.

**D1.6 remains open and undefaulted**, as agreed. It is re-asked before Phase 4
reaches admin views, and that is where I block rather than guess.

**B4 raised** (`BUILD/BLOCKERS.md`): the e2e suite adopts whatever is already on
port 8000, so `scripts/e2e_server.py`'s mocked vision seam never loads and
`correct-paper.spec.ts` fails. Environmental, verified pre-existing at the Phase
3 starting commit, and needs one command from you. The occupying process belongs
to another local user, so it was not killed unattended.

---

## 2026-08-13 — Phase 4, surface 2 (past-paper correction flow)

**IN** — nothing. Polled at the surface boundary
(`?poll=1&since=1786629365`); the response was empty. The inbound topic has
still never carried a message from the human.

**OUT** — surface milestone notice with the batched capture pair.

**No new DECISION was raised.** Everything this surface found fell inside its
own written mandate or was a correction of something untrue:

- The silent-failure defect in `streamActivity`, the 0.85-vs-0.90 confidence
  disagreement, and the mark/grade typeface: all three are the code disagreeing
  with a written spec (DESIGN.md §4, `lemely.core.schemas`), not judgement calls.
- Retry in place is audit M5, already approved as part of the mission's Phase 4.
- Audit M4 (progress lost on refresh) was deliberately *not* pulled forward and
  is recorded as Phase 6.2's, with the reason: the teacher console fixed the
  same defect architecturally (D6.13) and the student side needs the same
  backend change, not a styling one.

**D1.6 remains open and undefaulted.** Two surfaces away from admin views.

**B4 still blocks the e2e gate.** Port 8000 was re-checked this session and is
still held by the foreign `python -m lemely.web` process. Unchanged, still one
command from you, still not killed unattended.

---

## 2026-08-14T02:45+03:00 — DECISION D1.6, re-asked (outbound)

Phase 4 reached admin views (surface 7 of 10). D1.6 was first sent
2026-08-13T15:05Z and carries **no default on purpose** (§10: a question with
no sane default must not be a timeout question), so it is re-asked rather than
guessed.

**Question.** No school-admin or platform-admin screens exist. Both roles are
routed into `/teacher` today.

- **A** — build them now (~7 screens, new route subtree, un-bundles the
  `TEACHER_ROLES` guard `rbac.spec.ts` asserts against).
- **B** — defer; both admin roles keep landing on `/teacher`.
- **C** — scaffold routes and shells only, in the Study Notebook language,
  with no functionality behind them.

**Status: OPEN, no default, not blocking the build.** Per §10's "keep working
on independent tasks while it waits", Phase 4 proceeds to **surface 8 (Auth)**,
which does not depend on this answer. Admin views are taken up the moment an
answer arrives; if none has arrived when Auth, Marketing and 404/misc are all
done, that is the point at which Phase 4 genuinely blocks.

Inbound topic polled immediately before sending: still no message from the
human, ever.

---

## 2026-08-14 — Phase 4, surface 9 (marketing / landing)

**IN** — nothing. Polled at the surface boundary
(`?poll=1&since=1786629365`); the response was empty. The inbound topic has
still never carried a message from the human.

**OUT** — DECISION **D4.8** (30-minute timeout, default A), plus the surface
milestone notice.

**D4.8.** Should the internal design-directions gallery ship in the product?
`/student/directions` is an A/B/C gallery of result-header treatments, showing
mock data, reachable by any signed-in student, with no nav entry. It is the
same shape as the kit preview, which Phase 2 moved to `web/dev-previews/`
behind its own Vite entry so the product could never ship it.

- **A** — move it to `web/dev-previews/`, out of the product route table.
- **B** — leave it mounted at `/student/directions`.
- **C** — delete it.

**Default A, 30 minutes.** It carries a default because there is a sane one:
the project has already made this exact call once, for the kit preview, and A
is what it decided. Migrated to the Study Notebook in place either way, so
neither answer leaves a half-done surface.

**No other DECISION was raised.** Everything else this surface found was the
code disagreeing with something already written down, not a judgement call:

- The landing page being unreachable is an IA defect, and §1 permits IA changes
  outright. `portals/student/data.ts` had already named it ("orphaned inside
  the authenticated app") without fixing it.
- The six fabrications are PRODUCT.md's must-not-fabricate list being broken.
  Removing them needs nobody's permission; **inventing replacements would
  have**, which is why every replacement bullet cites the router that
  implements it.
- The dark proof band using `bg-ink` rather than `--paper-inverse`, the missing
  scroll-entry motion, and `font-serif` are all DESIGN.md sections the code
  disagreed with.

**D1.6 remains open and undefaulted.** One surface from the end of Phase 4.
After 404/misc, admin views are the only thing left, and that is the point at
which Phase 4 genuinely blocks rather than proceeds — as flagged when it was
re-asked on 2026-08-14T02:45.

**B4 still blocks the e2e gate.** Port 8000 was re-checked this session and is
still held. Unchanged, still one command from you, still not killed unattended.

---

## 2026-08-14 — Phase 4, surface 10 (404 / misc), and the first inbound messages

**IN — the human replied, for the first time in this mission.** Three messages
on the inbound topic, polled at the surface boundary:

1. `9gd0VBc0noOC` (ts 1786672245) — *"regarding decision D1.6 (admin screens),
   fully build the required screens and completely wire them"*.
   **This resolves D1.6 as option A**, and more strongly than option A was
   worded: not scaffolds, not shells, but built and wired. Logged, acted on:
   Phase 4 unblocks and surface 7 (admin views) is the next work unit.
2. `EHeWP2LpAc1E` / `277taBNJCTEO` (ts 1786673047/52) — *"Blocker resolved,
   ran: sudo fuser -k 8000/tcp … 1 passed"*. **This resolves B4.**

`LAST STEERING TS` advanced to **1786673052**, after both were logged and acted
on.

**On B4, one correction to the report, made by verifying rather than
accepting.** The message reported `correct-paper` passing, and that is true.
Running the *whole* suite found four further failures, which had been invisible
for the entire redesign because the suite could never run correctly. All four
are assertion drift against deliberate redesign changes, not functional
regressions; all four are fixed in place with the reason recorded per §9.7.
**The suite is now 34 passed, 0 failed** and Hard Gate §9.7 is green for the
first time. Full table in `BUILD/BLOCKERS.md` B4's resolution note.

**OUT** — surface 10 milestone notice, plus an acknowledgement of both
directives.

**Surface 10 is closed**, and it was not the tidy-up the ledger scoped. The
sweep found ten more product screens still in the build-era language — the
whole of onboarding, the whole placement flow, Subject, Parents, Notifications,
Announcements — none of which any surface had claimed, though MISSION §1 names
"onboarding/placement test" in scope outright. No DECISION was raised for it
because §1 and §12 already put them in scope; it was reported on ntfy when
found rather than at the end. `npm run check:copy` reaches **0**.

**No new DECISION is open.** D1.6 and D4.8 are both resolved, B4 is closed, and
nothing in surface 10 required a judgement the mission does not already answer.

---

## D6.6 — `test_design_tokens.py` asserts contrast the browser does not render
**Sent:** 2026-08-14 (redesign Phase 6.4 part 1) · **Status:** OPEN, no default, no timeout

**The evidence:**

    oklch(0.576 0.146 33) -> our oklch_to_srgb   #c0523c
    the same token, rendered by Chromium         #c25741
    white on #c0523c (what the test computes)    4.658  passes AA
    white on #c25741 (what a user sees)          4.436  fails AA

`--accent-on` is `#ffffff`, described in the token block as "the ONE permitted
pure white" at 4.65:1 on the accent fill. On screen it is 4.436:1, below the 4.5
floor it was chosen to clear. axe independently scored that node 4.21 on
`student-flashcards-no-weaknesses`, which is what led here.

The conversion error is 2-5/255 per channel. It matters because every contrast
value in this design system was chosen to *just* clear its threshold, so an
error that small is enough to move a claim across the line.
`tests/test_design_tokens.py` has been cited as this project's contrast
authority since Phase 2.

**Options:**
- **(A)** Reconcile `oklch_to_srgb` with what browsers actually do, re-derive
  every contrast claim in the token block against corrected values, and propose
  the resulting token changes for review before applying any of them.
- **(B)** Change only `--accent` far enough that white-on-accent clears 4.5, and
  leave the rest of the block as it stands.
- **(C)** Leave the tokens alone and record it as a known, documented AA gap.

**Why there is no default and no timeout:** every option changes, or knowingly
declines to change, the brand accent — present on every surface and chosen in
Phase 2 against a brand strategy. §10 says a question with no sane default
should not be a timeout question. Work continues on everything independent of
it; the failing node stays red rather than being loosened.

Full arithmetic and reasoning: `BUILD/DECISIONS.md` D6.5 §3.

---

## 2026-08-14 — Phase 6.4 part 2: D6.6 answered, and the answer disproved the question

**IN** — `jEmAdfevMO65` (ts **1786722798**): *"D6.6 = A"*.

Option A was: reconcile `oklch_to_srgb` with what browsers actually do, re-derive
every contrast claim against corrected values, and **propose** the resulting
token changes for review before applying any of them.

**Step 1 found nothing to reconcile. `oklch_to_srgb` was already correct.**
Chromium paints `oklch(0.576 0.146 33)` as `(192,82,60)`; the Python computes
`(192,82,60)`. Measured four independent ways — `getComputedStyle`, a canvas 2d
readback, and screenshots under the default, `srgb` and `display-p3` colour
profiles — all identical, and a literal `#c0523c` painted beside it is the same
pixel. axe, run against an isolated copy of the same button, reports
`fg=#ffffff bg=#c0523c ratio=4.65` and **passes**.

The 4.21 was axe sampling a CSS transition in flight. The state is reached by
*clicking* a toggle, which flips that button from `variant="secondary"` to
`variant="accent"` under `transition-colors`. Solving each channel for its
interpolation fraction gives `t = 0.9672 / 0.9706 / 0.9737` (background) and
`0.9712 / 0.9704 / 0.9750` (foreground) — **one fraction, 0.971 ± 0.004, across
two colour pairs with different endpoints**, reconstructing axe's 4.21 to the
digit.

So **no token change is proposed and `--accent` is untouched.** `--accent-on` is
4.653:1 and clears AA. D6.5 §3's reading — that the Python was wrong about the
colour space — is withdrawn; what it compared was axe's mid-transition sample
against the correct conversion, as though the former were a rendering.

The real defect was in the harness, and it is fixed: `runAxe` now settles
animations first. Worth stating because it is the direction that did not bite
here — a transient sample can read *higher* than the steady state just as easily,
turning a real failure green, and it is not reproducible run to run.

**OUT** — the resolution above, plus **D6.7, which is a new question for the
human.** Step 2 (re-derive every claim) found the hole `test_design_tokens.py`
never covered: it has only ever measured ink on *paper*. Against the eleven
tinted fills, `--ink-faint` is below 4.5 on **eight** of them (worst `--err-wash`
4.36) and clears the other three by 0.01–0.06. `--ink-faint: 0.529 -> 0.52`
clears 4.5 on all fourteen surfaces and stays lighter than `--ink-muted`.
**Proposed, not applied** — 334 call sites, and A's own wording says propose
first. Held as eight `xfail(strict=True)` so it can be neither forgotten nor
applied without this record moving with it.

`LAST STEERING TS` advances to **1786722798**.

---

## 2026-08-14 — D6.7 answered and applied, and the token was the smaller half

**IN** — `VqpbRSelzmn9` (ts **1786723759**):
*"D6.7 = \"--ink-faint 0.529 -> 0.52 (Proposal Accepted)\""*.

Applied exactly as proposed, in the three files that have to agree:
`web/src/index.css`, `DESIGN.md` §3.2 (including the ≈hex, `#696C6F` ->
`#66696C`), and the transcription in `tests/test_design_tokens.py`. Measured
after the change: 5.13 on `--paper`, 5.38 on `--paper-raised`, 4.78 on
`--paper-sunk`, worst-of-fourteen **4.53 on `--err-wash`**. Hierarchy intact at
11.77 / 6.09 / 5.13. The eight `xfail(strict=True)` cases are gone by being
folded into the one parametrised matrix rather than deleted, so `ink-faint` is
now checked by the same rule as its three siblings; the one thing the split list
carried that the matrix cannot — *which* pairing is binding — survives as a named
test asserting `--err-wash` is still the tightest.

**The bigger finding came out of applying it, not deciding it.** `TOKENS` in
`test_design_tokens.py` is transcribed by hand from DESIGN.md, and **nothing
tied it to `index.css`**. So this project's contrast authority could measure one
palette while the browser painted another, with every assertion still green. It
bit immediately: `index.css` was edited first, and eight tests went red
reporting the *old* value. That direction is loud; the reverse is silent, and
only the edit order made it the loud one. Closed by a gate that **parses**
`:root` rather than transcribing a third time, guarded so a regex that stops
matching cannot pass everything beneath it, and verified by inversion.

**OUT** — nothing, and that is itself worth recording. `/tmp` filled to 100%
mid-session (2.4G of stale scratch from 2026-08-12 that outlived the sessions
that made it), and **no Bash command can run**, so publishing to ntfy — which is
`curl` to a plain-HTTP LAN host — is impossible. **The channel that reports a
blocker shares a single point of failure with the work it reports on.** This
file and `BUILD/BLOCKERS.md` B5 are the only channels that survived, which is
what §10's file fallback exists for, except §10 assumes the file mirrors an ntfy
message and here it *is* the message. B5 has the one command that unblocks it.

`LAST STEERING TS` advances to **1786723759**.
