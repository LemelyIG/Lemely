# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 5            # Phases 0-4 complete, merged and reported; Phase 5 in progress
last_updated: 2026-08-10T12:49:38Z   # (Measured with `date -u`, not carried forward.) **Seventy-ninth session: the same P5.11 gate run is STILL ALIVE at 14m53s on entry (4/13 — `ruff-check`/`ruff-format`/`mypy`/`import-linter` PASS, still inside `pytest`) — attached, Monitor re-armed persistently on `EXIT=`/FAIL/Traceback/Error/Killed/OOM/`PASS `, NOT relaunched.** Same wrapper PID `1457845` and same `check.sh` PID `1457847` sessions 76–78 recorded: one continuous run, now ~15 minutes in. INBOX had no unhandled items; B1/B2/B3 all resolved, no open blockers. Working tree on entry: **189 paths, 188 of them under `reports/phase-5/` and exactly one outside — session 78's own uncommitted `BUILD/STATE.md` note**, which is committed here (this line). **The 188 report paths get NO wip commit**, same call sessions 74–78 made: the dirt is the live run's output, and freezing a mid-run snapshot is what produced session 73's misleading partial corpus. `git status reports/phase-5` shows **zero `D` entries** at 14m53s — mid-run, so it proves nothing; the load-bearing check is the one at completion. **No source file touched.** The post-`EXIT=` procedure is unchanged and recorded below; do not re-derive it.
#                                    Prior (session 78): **Seventy-eighth session: the same P5.11 gate run is STILL ALIVE at 12m37s on entry (4/13 — `ruff-check`/`ruff-format`/`mypy`/`import-linter` PASS, inside `pytest`) — attached, Monitor re-armed on `EXIT=`/FAIL/Traceback/Error/Killed/OOM/`PASS `, NOT relaunched.** Same wrapper PID `1457845` and same `check.sh` PID `1457847` sessions 76/77 recorded, so this is one continuous run now ~13 minutes in. INBOX had no unhandled items; B1/B2/B3 all resolved, no open blockers. Working tree dirty with **188 paths, every one under `reports/phase-5/`** (0 outside) — **no wip commit**, same call sessions 74–77 made: the dirt is the live run's output, and freezing a mid-run snapshot is what produced session 73's misleading partial corpus. `git status reports/phase-5` shows **zero `D` entries** at 12m37s, but that is the mid-run reading and proves nothing — the load-bearing check is the one at completion. **No source file touched.** The post-`EXIT=` procedure is unchanged and recorded below; do not re-derive it.
#                                    Prior (session 77): ( Session 76's `12:52:00Z` is ~9 min in the FUTURE relative to this real clock reading — a hand-typed stamp, same class of drift as the `gemini_spend_usd` field. Stamp from the clock.) **Seventy-seventh session: the P5.11 gate run session 76 launched was ALIVE at 7m29s on entry (4/13 — `ruff-check`/`ruff-format`/`mypy`/`import-linter` PASS, inside `pytest`) — attached, Monitor armed on `EXIT=`/FAIL/Traceback/OOM/Killed, NOT relaunched.** Same wrapper PID `1457845` and same `check.sh` PID `1457847` session 76 recorded, so this is one continuous run. INBOX had no unhandled items; B1/B2/B3 are all resolved, so no open blockers. **No source file touched — the run is verifying this exact tree, and editing one now re-creates the six-minutes-in staleness that cost session 72 its run.**
#                                    Working tree on entry was dirty with **188 paths, every single one under `reports/phase-5/`** (0 outside) — again **NO wip commit**, for the reason sessions 74/75 recorded: the dirt is the live run's output being written this second, not leftover work, and freezing a mid-run snapshot is exactly what produced the misleading 75-file partial corpus session 73 had to reason around. The resume protocol's "clean up a dirty tree with a wip commit" is the wrong instrument while a run holds the lane. **`git status reports/phase-5` shows ZERO `D` entries at 7m29s** — but that is the *mid-run* reading and proves nothing yet; the load-bearing check is the one at completion, because a tracked file still showing `D` when the run lands is precisely the signal that the fresh run did not regenerate it.
#                                    **Unchanged and still the procedure when the `EXIT=` line arrives:** on `EXIT=0` only — `npm run compare-screens -- --baseline reports/phase-4/screens --candidate reports/phase-5/screens` (the default baseline is Phase **2.5** and is wrong here), re-check for `D` entries, then commit `reports/phase-5/` as the new baseline; P5.11 is then DONE and only P5.12 remains. **On anything but `EXIT=0`, do not commit the corpus** — a crashed run leaves a partial one, and never committing on red is what neutralizes session 73's trap.
#                                    Prior: **Seventy-sixth session: CHUNK E'S AUDIT RUN LANDED — `EXIT=0`, 73 axe route-states (exactly the ~73 chunk E predicted), 0 critical / 0 serious, Lighthouse a11y floor 96, 0 console errors. It found TWO REAL DEFECTS, both now fixed and committed (`a4b73e9`), and one of them would have turned the gate run red.** The corpus check session 75 asked for was re-run at completion and holds: `git status reports/phase-5` shows **zero `D` entries** — every previously-tracked file was regenerated, so no stale artifact rode into the baseline.
#                                    **Defect 1 — `heading-order` (moderate) on `student-notifications-populated`, the ONE non-zero cell in the whole severity table.** G-13's `NotificationRow` titled each row `<h3>` directly under the page `<h1>` with no `<h2>` between. **This is chunk E's own populated-state entry earning itself on its first run** — the empty state it previously probed has no rows and therefore no headings to order, so the defect was unreachable by the old registry. Fixed to `<h2>`. **S-28 keeps its `<h3>` cards deliberately:** it really does have `Notices`/`Calendar` `<h2>`s above them (`Announcements.tsx:418/425`), so the two screens describe different outlines. Do not normalize them to one level — the level has to describe the actual heading tree, not match a sibling screen.
#                                    **Defect 2 — horizontal scroll at 380px on G-01, and this one was a LATENT RED GATE, not a nice-to-have.** The landing hero's secondary CTA ran to x=409 in a 380px viewport because `Button` carries `whitespace-nowrap` and could not shrink. **`scripts/check_ui_gates.py:92-96` fails on ANY horizontal-scroll violation (zero tolerated)** — so `ui-thresholds` was guaranteed to go red ~28 minutes into the gate run. Caught by *reading the finished audit log before launching the gate*, which is the cheap order; discovering it inside the gate costs the whole run. The CTA row now wraps rather than truncating a label that says who the link is for.
#                                    **A procedural improvement worth keeping, and the reason this session runs ONE 28-minute job instead of two ~30-minute ones: the gate run was launched with `LEMELY_REPORT_DIR=reports/phase-5` exported.** `check.sh` passes that env through to **both** `playwright-e2e` and `puppeteer-audit` (its own header comment, `:22-23`), and `check_ui_gates.py` reads the same variable (`:40`). So one run regenerates the phase-5 corpus against the exact committed tree AND enforces the thresholds on the corpus it just produced — strictly better provenance than gating a scratch copy while committing a corpus built from an earlier tree. **This also closes a coverage hole nobody had noticed:** the finished audit left `reports/phase-5/screens/` at 43 ids while `reports/phase-4/` has 39 including **S-06, S-10, S-14, S-15, S-17 and the two `p2.10-*` pngs that phase-5 was MISSING** — those come from `screenshots.spec.ts` (Playwright), not from the audit registry, so an audit-only re-run could never have produced them and the phase-5 baseline would have shipped with five screen ids fewer than its predecessor. **The discipline that makes this safe is: commit the corpus only after `EXIT=0`.** A crashed audit leaves a partial corpus, which is session 73's trap; never committing on red neutralizes it.
#                                    **In flight now: the full `./scripts/check.sh` under `setsid`, wrapper PID `1457845`, `check.sh` PID `1457847`, log `/tmp/p511-gate.log`, ends in an `EXIT=` line. Do NOT relaunch it.** When it lands: `npm run compare-screens -- --baseline reports/phase-4/screens --candidate reports/phase-5/screens` (the default baseline is Phase **2.5** and is wrong here — always pass `--baseline`), then commit `reports/phase-5/` as the new baseline, then P5.11 is DONE and only P5.12 (the phase report) remains.
#                                    **One environment fact this session paid for: `pre-commit` is NOT on PATH — it is `.venv/bin/pre-commit`** — and its `import-linter` hook then fails with `Executable lint-imports not found` for the same reason. `.venv/bin/lint-imports` run directly reports `Contracts: 2 kept, 0 broken`. The hook failure is a PATH artifact, not a contract break, and it is doubly irrelevant when the staged files are TSX.
#                                    Prior: **Seventy-fifth session: chunk E's relaunched audit run was still ALIVE at 9m14s on entry (route 40, inside the S-22 flashcards batch, past the S-21 practice states) — attached, Monitor re-armed on `EXIT=`/FAIL/Traceback/OOM, NOT relaunched.** Same wrapper PID `1409573`, same node child `1409596` as sessions 73/74 recorded, so this is one continuous run and not a restart. Working tree on entry was dirty with **160 paths, every single one under `reports/phase-5/`** (107 untracked + 53 modified, 0 outside) — again NO wip commit, for session 74's reason: the dirt is the live run's output, not leftover work, and freezing a mid-run snapshot is exactly what produced the misleading 75-file partial corpus session 73 had to reason around. INBOX had no unhandled items. **No source file touched.**
#                                    **One new measured signal, and it is the good one: `git status reports/phase-5` shows ZERO `D` entries.** Session 73 `rm -rf`'d the directory before relaunching and recorded that any tracked file still showing `D` when the run lands is precisely the signal that the fresh run did not regenerate it — a stale artifact riding into a "fresh" baseline. All 75 previously-tracked files are back. Re-check this at completion, not only now.
#                                    **Verified read-only ahead of the post-run steps, so the procedure is not re-derived under time pressure:** the npm script is `compare-screens` → `scripts/compare_screens.mjs` (underscore file, hyphen script name — a bare `ls compare-screens.mjs` misses it), its `parseArgs` default baseline really is `reports/phase-2.5/screens` (`:76`), which is why chunk E's `--baseline reports/phase-4/screens` is load-bearing rather than decorative; `--candidate` defaults to `$LEMELY_REPORT_DIR/screens` so it can be omitted, but pass it explicitly. It hard-refuses on an empty baseline or candidate dir rather than reporting "everything added" (`:194-206`).
#                                    Prior: **Seventy-fourth session: chunk E's relaunched audit run was ALIVE at 6m48s on entry (route 24 of ~40, inside the parent/S-01 batch) — attached, Monitor armed on the `EXIT=` line, NOT relaunched.** Working tree on entry was dirty with **110 paths, every one of them under `reports/phase-5/`** — 51 modified tracked files plus 59 untracked, i.e. the artifacts the live run is writing this second. **No wip commit was made, deliberately:** the resume protocol's "clean up a dirty tree with a wip commit" is exactly session 72's trap in a new costume — it would freeze a mid-run snapshot as if it were a curated baseline. The dirt is the run's output, not leftover work, and it resolves itself when the run exits. INBOX had no unhandled items. **No source file touched — the run is verifying this exact tree, and editing one now would re-create the six-minutes-in staleness that cost session 72 its run.**
#                                    Prior: **Seventy-third session: P5.11 chunk E's audit run was KILLED AND RELAUNCHED, on purpose, against the tree that actually matches it.** Session 72 launched the run at 15:03:54 local and then edited `audit.mjs` at 15:09:58 — six minutes in — so the in-flight run could never have contained the G-13-populated check that edit adds. The edit is now committed (`401f8e1`) and verified in code before relaunch, not after. New durable wrapper PID **`1409573`** (node child `1409596`), log `/tmp/p511-audit.log`, relaunched 12:16Z; healthy at 3m26s. **Do NOT relaunch it.** Full rationale, plus the two environment traps it cost (partial audit artifacts already tracked from a mid-run `git add -A`; `pre-commit --all-files` reporting phantom failures while a run writes into `reports/`) are on the P5.11 chunk-E line. Working tree on entry was dirty with exactly that one uncommitted `audit.mjs` edit; INBOX had no unhandled items.
#                                    Prior: **Seventy-second session: THE SECOND GATE RUN FINISHED — ALL 13 GATES PASS, 0 skipped, EXIT=0. P5.9 AND P5.10 ARE BOTH DONE — 11/12 Phase-5 tasks complete. The only remaining task before the phase report is P5.11, which is now `doing`.** No gate run is in flight; the test lane is FREE for the first time in twelve sessions. Coverage **90.91%** off that run's own `.coverage` (develop 90.18% — no drop; byte-identical to P5.8 because P5.9/P5.10 touched zero backend files). Working tree clean on entry; INBOX had no unhandled items.
#                                    **What that changes about how to work: sessions 62–71 all ran read-only because a gate held the lane, and they spent that time turning P5.11's one-line brief into SIXTEEN measured points. Do not add a seventeenth. The brief is done; P5.11 is now a BUILD task, and the lane is free to build in.** Points 6+16 (S-29 `BoardRow` element prop), 7(d) (S-31 aria-labels), 15 (the XP seed), 5+3 (G-10's dedicated 3-device account and its three-edit contract tax) and 12 (the stale audit exclusion list) are the five concrete edits; points 7/11/13/14/9 are the four E2E specs; point 12(a)/(c) is the re-baseline + compare procedure.
#                                    **Sixty-ninth session: the second gate run was ALIVE at 11m18s (4/13, inside `pytest`) on entry — attached, Monitor armed, NOT relaunched.** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file touched — the run is verifying this exact tree.
#                                    **Seventieth session: the second gate run was ALIVE at 19m00s (10/13) on entry — attached, Monitor armed, NOT relaunched; `playwright-e2e` PASSED during the session, so it stands at 11/13 with only `puppeteer-audit` and `ui-thresholds` left.** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file touched — the run is verifying this exact tree.
#                                    **Seventy-first session: the second gate run was ALIVE at 24m02s (11/13, inside `puppeteer-audit`) on entry — attached, Monitor armed, NOT relaunched; only `puppeteer-audit` and `ui-thresholds` remain.** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file touched — the run is verifying this exact tree.
#                                    **The waiting time went into the axe half of P5.11 point 6, which fifteen points of brief had never checked: the markup change the ordering assertion requires is one wrong keystroke away from a SERIOUS axe violation on a route already in the registry (new point 16).** Point 6 called list semantics "an a11y gain" — true only if the two `BoardRow` call sites are made to differ. `list` and `listitem` are both `impact: "serious"`/wcag2a in `axe-core`, and `audit.mjs:432` runs `window.axe.run()` with **no** ruleset restriction, so both are live on `/student/board`. **Point 6's trap costs a wrong-but-green assertion; its natural correction costs a RED GATE** — making `BoardRow`'s root `<li>` unconditionally turns the *pinned viewer row* (`:217`, rendered inside a plain `<div>` outside the container) into an `<li>` with no list parent. The fix is an element prop on `BoardRow`, not a wrapper. **And no cheap gate catches it:** there is no `Standings` component test at all and **zero** vitest tests import axe, so all four web gates go green and it surfaces ~28 minutes in.
#                                    Prior: **The waiting time went into the one thing P5.11's acceptance criterion actually stands on and no session had measured: what the seed must WRITE for the leaderboard to be populated and deterministically ordered (new point 15). Three traps, all silent.** Points 2/3 measured what a seed group *costs* and point 6 what the assertion can *grab*; nobody had measured the data. `seed_e2e.py` has **zero** XP/streak occurrences and builds through `deps` services. (1) **`awarded_on` is a civil date and the board is a Monday..Sunday Cairo window around *today*, so any hardcoded date renders an empty-and-successful board** — the honest-empty state, not an error. (2) **Spreading events across days to look realistic re-introduces it on exactly one day**: `today - N` crosses the Monday boundary early in the week and silently zeroes that student, so the spec passes Tue–Sun and "flakes" on Monday. Put every event on today's Cairo date. (3) **The re-run trap is P4.9 chunk C's purge lesson in Phase-5 form, with a worse ending**: a capped award is a *successful* call that writes no row (`xp_repo.py:24-25`), so re-seeding drifts totals up and then freezes them all at the 250/day cap — and ties read as **equal rank** by design, so the ordering assertion collapses into an all-tied board that looks like a product decision. Purge `xp_events` before seeding.
#                                    Prior: **Sixty-ninth session: the waiting time went into the last unmeasured mechanic in P5.11: the announcement flow needs TWO ROLES in one spec, and no session had checked whether the suite has a role-switching idiom or whether the teacher's POST even has a screen (new point 13). Both answers are good.** (1) **It has a screen** — `/teacher/announcements` renders a real compose `<form>`, so the flow satisfies MISSION §5's "through the real UI" with no API-only setup step, and every locator it needs is already accessible-name-addressable (zero markup change, like G-13, unlike S-29/S-31). (2) **Two roles cost nothing** — `injectSession` (`seed.ts:184-207`) writes the session into `localStorage` pre-scripts and every seeded account carries an `accessToken`. (3) **The checkbox's visible text is EXACTLY `seed.class.name`** — `routers/classes.py:211` is `label=row.name`, verbatim. **The one trap: `audience` defaults to `"classes"` so the radio needs no click, which makes title+message+submit look like the whole driver — but `selectedClassIds` starts `[]` and gates `disabled`, so skipping the class tick clicks a disabled button and dies as a 30s "element is not enabled" timeout that reads as a hung app.**
#                                    Prior: **Sixty-eighth session: the second gate run was ALIVE at 5m36s (4/13, inside `pytest`) on entry — attached, Monitor armed, NOT relaunched.** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file touched — the run is verifying this exact tree.
#                                    **The waiting time went into the half of P5.11 no session had ever looked at: the UI-gate leg (new point 12). It found the audit registry's exclusion list stale in ALL FOUR entries.** Two things change the task. (1) **The screenshot corpus is produced by `audit.mjs`, not by `screenshots.spec.ts`** — that spec captures only five Phase-2.5 ids; the other 34 in `reports/phase-4/screens/` come from registry entries. So P5.11's screenshot leg needs **no new Playwright spec**, just `LEMELY_REPORT_DIR=reports/phase-5 npm run audit` (`reports/phase-5/` does not exist yet). (2) **`audit.mjs:83-85` and its operator-facing `log()` at `:2451` both still declare `/student/board` unaudited — it has been audited since P5.8 (`:1960`) — and excuse three other real routes as "still on mock data" when `/student/subject/:code` runs on the real `useSubject` hook.** Third instance of this shape in Phase 5, and it happened *to the sentence documenting the previous two*. The G-13 miss inverted: present-and-falsely-declared-absent, alongside three genuinely unaudited live routes.
#                                    Prior: **Sixty-seventh session: THE P5.9 GATE RUN FINISHED — ALL 13 GATES PASS, 0 skipped, EXIT=0 — AND THEN THE GREEN RESULT TURNED OUT TO BE INCOMPLETE.** Session 61's `setsid` run (PID 1077823) exited clean at ~31 minutes, seven agent sessions after it started; the numbers are on the P5.9 UI-gate checklist line and were read off that run, never re-run. Working tree clean on entry, no wip commit needed; INBOX had no unhandled items.
#                                    **The finding: `audit.mjs` had NO entry for G-13, the notification inbox — chunk B's own screen — so the gate went green *because it did not know the screen existed*.** The one new student screen in P5.9 was never axe-audited, never Lighthouse-scored, never screenshotted, and MISSION §6.8 requires all three. The registry is a hand-maintained list, which makes a missing entry silent: third instance of that shape in this build (`EXPECTED_TABLES` P5.4, the `SeedContract` mirror P4.11) and **the first where the green result was actively misleading rather than merely incomplete.** Entry added and being verified by a standalone `npm run audit` under `setsid` (`/tmp/g13-audit.log`); a full `check.sh` on the tree carrying it is still owed. **P5.9 is NOT done — do not mark it done on the strength of the EXIT=0 above.**
#                                    **Also measured off the finished run and worth carrying: `ui-thresholds` passed with NINE routes below Lighthouse performance 80** (seven at P5.8), one of them P5.9's own `settings-notifications` at 73. D4.25 restated by a second phase — `check_ui_gates.py` has no performance check at all. **Never cite this run as a performance pass.**
#                                    Prior: **Sixty-sixth session: the waiting time went into the one part of the P5.11 brief that had gone STALE, and it was pessimistic: the push/notification flow is now the CHEAPEST of the four, not the blocked one (new point 9).** Point 4 was written in session 59 *before* P5.9 existed. Three things now hold. (1) **G-13 needs ZERO markup change** — `NotificationRow` renders the title as a real `<h3>` with real `Mark as read`/`Open` buttons, so it is already in the suite's accessible-name idiom; it is the exact opposite of points 6 and 7(d), which do need an a11y fix. (2) **It costs no new seed group and no new driver** — the teacher's own announcement POST fans out at `announcements.py:202`, so the announcement flow and "push delivery" are *one driver, two assertions*; and `grade_ready` fires on the same `POST /student/correct` that point 7's XP assertion rides. (3) **Its preference gate is already satisfied** — an absent prefs row reads `DEFAULTS` = "every type enabled", so no prefs seeding. Assert `grade_ready` renders with **no** `Open` button (session 60's dead-link finding honoured in `destinationFor`), and assert the inbox row, never a delivered push.
#                                    Prior: **Sixty-fifth session: the P5.9 UI gate is STILL RUNNING under `setsid` (PID 1077823, log `/tmp/p59-gate.log`) — attached at 24m30s, now 11/13 gates PASS: `playwright-e2e` cleared, so only `puppeteer-audit` (in progress) and `ui-thresholds` remain. Do NOT relaunch it.** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file touched — the run is verifying this exact tree.
#                                    **The waiting time went into VERIFYING, not re-sharpening, P5.11's riskiest precondition — and it downgrades point 7's worry.** Point 7 warned that `xp_events.subject_code` is a live FK to `subjects.code` whose row exists "only as a side effect" of the placement seed, so a missing row would make the fail-open `award_xp_safely` swallow a real FK error and the XP assertion vanish silently. Read rather than assumed: `xp_repo.py`'s own contract (§4) confirms only the *dedupe* constraint is swallowed and "a genuine foreign-key violation (e.g. an unknown `subject_code`) still raises" — but **`scripts/seed_e2e.py:1316` raises `RuntimeError` if `link_past_paper_rows()` links fewer rows than it was given**, so a seed that produced no `subjects` row cannot complete. The precondition is *guarded by the seed itself*, not incidental. **The residual risk is only "the seed was never run against this DB", which every E2E run already precludes.** Build the XP-accrual assertion without adding a subject-row guard to it.
#                                    Prior: **Sixty-fourth session: the gate was at 16m19s, 4/13 (inside `pytest`).** Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. No source file was touched — the run is verifying this exact tree — so the waiting time went into the next unmeasured P5.11 flow: **XP accrual (point 7 on the P5.11 line).**
#                                    **The finding inverts point 2's framing for this one flow: XP accrual needs NO new seed data, because its cause already exists.** `correct-paper.spec.ts` signs up a *fresh* account and drives a real upload→mark, which is the `paper_corrected` seam (`routers/student.py:851`); a brand-new account has zero prior XP, and `GET /api/student/xp` is gated on the student role **only**, so the never-onboarded account can read S-31. The expected value is exact — **50** — not a range. Build this flow first, not last.
#                                    **The precondition that can make it vanish silently:** `xp_events.subject_code` is a live FK to `subjects.code`, the golden fixture is `0625`, and `xp_repo.py:37` says an unknown code **raises** — which `award_xp_safely` then swallows by design. The `subjects` row exists today only as a side effect of the placement seed's `link_past_paper_rows`. **An XP assertion after the correction would be the first test in this build ever to catch a fail-open seam failing.**
#                                    **And the read has nothing to grab — session 63's point-6 problem again, at S-31.** `Total XP`, `Level` and the streak `current` are all `<Eyebrow>` labels with the value in a **sibling bare `<div>`** (`Profile.tsx:133-140/167-170`): no accessible name, no association — a screen-reader defect, not just a test inconvenience. The only locatable values are indirect (the `Meter` label, `"{remaining} XP to level N"`), and reading the total through `nextLevelXp` is derived precision. **The fix is this repo's own C-2 `MarkDisplay` pattern** — value in its own `aria-label` — which `correct-paper.spec.ts:57-61` already asserts against. Not `data-testid`; point 6(a) measured the suite has none.
#                                    Prior: **Sixty-third session: P5.11's ordering assertion has nothing to grab.**
#                                    **P5.11 point 6 is new and it changes the task's shape: the leaderboard-ordering assertion — the single acceptance criterion MISSION §4 names for this phase — has nothing to grab.** `data-testid` appears **zero** times in `web/src/` and `getByTestId` zero times in `web/e2e/`, so there is no test-hook convention to fall back on (the suite locates purely by accessible name); and `BoardRow` is a bare `<div>` inside a bare `divide-y` `<div>`, so there is no row-shaped locator either. The fix is **list semantics on the ranked container only** — honest markup, an a11y gain, and the suite's existing idiom. **The trap: the viewer's pinned row is the same `BoardRow` rendered OUTSIDE that container**, so wrapping all of `BoardBody` puts an out-of-sequence rank in the list and the ordering assertion can pass on a board where the viewer ranks last. Full detail on the P5.11 line.
#                                    Prior: **Sixty-second session: P5.11's G-10 seed precondition measured.**
#                                    **P5.11's G-10 seed precondition is now measured (point 5 on the P5.11 line).** Every prior session left it as a pointer ("a seed account already holding three live devices"). It is three plain `devices` inserts — but the load-bearing part is that the account must be **dedicated**: any other E2E logging in as it mints a fresh `deviceId` and can silently consume a slot, after which G-10 stops reproducing and the audit entry goes green by rendering the ordinary logged-in screen. Silent and order-dependent. The 409 itself is non-destructive (`allow_eviction=False` writes nothing), so the entry is safely re-runnable.
#                                    **One near-miss worth keeping: I almost recorded that the SPA sends no `deviceId`, making the 3-device limit really a 3-*login* limit.** That was false — `getDeviceId()` (`web/src/lib/auth/storage.ts:16`) mints once into `localStorage` and `AuthContext.tsx:79` sends it; a `grep | head -10` had truncated before line 79. The client half is fully built and correct — **do not re-derive it as a defect**. This phase keeps recording "the code beats the note"; this time the wrong note would have been mine, from a truncated search. **Never conclude an absence from a `head`-truncated grep.**
#                                    Prior: **Sixty-first session: P5.9 CHUNKS C AND D ARE BUILT AND COMMITTED; the P5.9 UI gate was launched under `setsid`.**
#                                    Working tree clean on entry, no wip commit needed; INBOX had no unhandled items. Chunk C (`7a8f93a`) is **G-12**, chunk D (`666d6a7`) closes the teacher/parent nav gaps and puts G-12 in the audit registry. **All four web gates green after each chunk** (456 tests over 15 files, up from 430/14). Two guards verified by inversion in chunk C.
#                                    **Three findings a resuming session must not undo.** (1) **The route is `PUT`, not `PATCH`** — the brief said PATCH; `routers/me.py:176` declares `@router.put`. Still a genuine partial update via `model_fields_set`, and the screen sends **one key per toggle flip**, which is not bandwidth: a whole-object body carries `atRiskAlert`, a **422 for any role but teacher/parent**, and clobbers a change made on another device since load. Seventh Phase-5 instance of the code beating the note. (2) **`atRiskAlert: null` is information, not absence** — "no such preference for your role" — so the toggle is *filtered out*, never rendered unchecked. (3) **`urlBase64ToUint8Array` must return `Uint8Array<ArrayBuffer>`**: since TS 5.7 the bare `Uint8Array` defaults to `ArrayBufferLike`, which admits a `SharedArrayBuffer` that `applicationServerKey` does not, and the bare form fails `web-typecheck` at the `pushManager.subscribe` call rather than at the helper.
#                                    **The push state that ships is `unavailable`, and no gate exercises the other two.** This build has no VAPID keys, so `available: false` is the designed answer (D5.9 §4) — the G-12 audit entry therefore never presses the enable or test-notification buttons, and a student-session audit sees four toggles rather than five. Both written into the registry entry; both carried to P5.12's limitations. Also carried: UI spec §G-12's `weekly_summary` ships **absent**, and the toggle key list is asserted *exactly* so it cannot be added without the backend growing the enum value.
#                                    **G-10 still has no audit-registry entry** — it needs a seed account already holding three live devices, which is `scripts/seed_e2e.py` work that P5.11 owns. Not closed here, and not to be mistaken for covered.
#                                    Prior: **Sixtieth session: THE P5.8 GATE RUN FINISHED — ALL 13 GATES PASS, 0 skipped, EXIT=0. P5.8 is COMPLETE; 9/12 Phase-5 tasks done. Resume at P5.9.**
#                                    Session 51's `setsid` run (PID 927164) exited clean at ~11:59, **31 minutes** after launch and **ten agent sessions** after it started (51 launched, 52–59 attached, 60 caught the exit on an armed Monitor). Measured off that run and never re-run: **2927 tests**, **coverage 90.91%** (develop 90.18%, P5.6 90.78% — no drop), **66 axe route-states with zero violations at any severity**, **0 console errors**, **0 horizontal-scroll violations**, **Lighthouse a11y floor 96**. All four new screens are in the audit registry and score a11y 100. Working tree clean on entry, no wip commit needed.
#                                    **The one honest finding the run produced: `ui-thresholds` passed with SEVEN routes below Lighthouse performance 80, two of them new P5.8 student routes** (`student-standings` 69, `student-announcements` 77). D4.25 said the performance floor is not enforced; this run is the Phase-5 proof — `check_ui_gates.py` has no performance check, so a green `ui-thresholds` says nothing about performance. **Never cite this run as a performance pass.** Carried to P5.12 §4.
#                                    **Then started P5.9 and landed chunks A and B.** D5.15 was recorded **before any code** (MISSION §4's ordering for this phase) and made two calls: `injectManifest` over `workbox.importScripts`, because a `public/` file is invisible to `tsc`/oxlint/vitest and this phase's only new client logic must not live where no gate can see it; and — correcting D5.10 — **a service worker cannot authenticate**, since the session token is in `localStorage` which no `ServiceWorkerGlobalScope` can read. Mirroring the token into IndexedDB was rejected as a second longer-lived copy of a credential that every logout and eviction would then have to clear. The worker asks an open page instead. Chunk A is the worker + a pure decision module + 21 tests; chunk B is G-13's inbox screen + the page half of the handshake + 22 tests. **All four web gates green after each chunk** (430 tests over 14 files). **The full suite / `check.sh` has NOT been run since P5.8** — chunks C and D remain before the P5.9 UI gate.
#                                    **Two findings from those chunks that a resuming session must not undo.** (1) **`grade_ready` has no resolvable link and deliberately gets none** — its payload carries the upload UUID, but `/student/result/:paperId` addresses papers by *history index* and `int(paper_id)` 404s on a UUID, so an Open button would be a guaranteed dead link. There is no route mapping an upload id to its result. (2) **`tsconfig.sw.json`'s narrow include is load-bearing, not tidiness** — widening it to the whole `src/lib/push` directory fails with `TS2304: Cannot find name 'localStorage'`, which is the compiler stating the exact constraint D5.15 §2 rests on. That boundary is now enforced by `web-typecheck` rather than discovered on a reader's device.
#                                    **P5.12 was the last bare one-liner and is now briefed** (56/58/59 did P5.9/P5.10/P5.11). Its expensive part is §7, the honest-limitations list: every Phase-5 item that was tagged "carry to the Phase-5 limitations" as it was found is now collected in one place on the P5.12 line — nine Phase-5 items plus six carried ones — so the report writer copies instead of re-grepping 700 lines.
#                                    Prior: **Fifty-ninth session: the run is alive at 27m01s, still inside `puppeteer-audit`; the waiting time went into sharpening P5.11.**
#                                    Session 51's `setsid` run (PID 927164) is alive at **27:01**, log still 276 bytes (11/13 PASS). Health checked the fifty-fifth session's way: the `npm run audit` child (973395) is **the same one session 57 saw** — 5m59s elapsed against 27m01s total puts its start at ~21 min, exactly where session 57 reported `puppeteer-audit` beginning — under a **fresh** Chrome tree (990891 + crashpad/zygotes), which is progress rather than a restart because `audit.mjs` cycles a browser per route batch. Twelfth run not started; Monitor re-armed on 927164 (it now also fires on `EXIT=`/FAIL, so a red gate is not silent). Working tree clean on entry, no wip commit needed.
#                                    **P5.11's brief was a bare one-liner and is now measured** (P5.9 and P5.10 were sharpened by sessions 56 and 58, so P5.11 was the next unbriefed task). Three findings: **zero** E2E coverage of any Phase-5 surface, `seed_e2e.py` seeds **no** Phase-5 data at all (so leaderboard *ordering* — the one acceptance criterion MISSION §4 names — has never been asserted against a populated board, and G-10 still lacks the 3-device account it needs), and the seed contract is **P5.4's `EXPECTED_TABLES` trap in frontend form**: `seed-contract.spec.ts` asserts exact key equality plus an exhaustive SHAPE map, so one seed group costs three edits and fails ~22 min into a run instead of ~10. Full brief on the P5.11 line.
#                                    Prior: **Fifty-eighth session: the run was alive at 23m41s inside `puppeteer-audit`; the waiting time went into sharpening P5.10.**
#                                    Session 51's `setsid` run (PID 927164) is alive at **23:41**, log still 276 bytes (11/13 PASS). Health checked the fifty-fifth session's way and it holds: a live `npm run audit` child (973395) and a **fresh** Chrome tree (980241 + gpu/network/zygote workers) — note that is NOT session 57's Chrome 974729, because `audit.mjs` cycles a browser per route batch, so a *changed* Chrome PID is a sign of progress, not of a crash-restart. Eleventh run not started; Monitor re-armed on 927164. Working tree clean on entry, no wip commit needed.
#                                    **P5.10's brief was a bare one-liner and is now measured** (P5.9 was already sharpened by session 56, so P5.10 was the next unbriefed task). Two findings that change it: the global `prefers-reduced-motion` rule **already exists** at `src/index.css:742` covering `*`/`::before`/`::after`, and it genuinely reaches **all** motion here — the app is CSS-only, with exactly three `@keyframes` and **zero** animation libraries, `requestAnimationFrame` calls, or smooth-scroll. So P5.10 is not a CSS task. **The gap is that no test anywhere has ever asserted it** — the deliverable is the proof test, verified by inversion. Full brief on the P5.10 line.
#                                    Prior: **Fifty-seventh session: the P5.8 gate run has cleared 11/13 gates — `playwright-e2e` PASSED.**
#                                    Session 51's `setsid` run (PID 927164) was alive at **21m52s** and the log had grown 254 → **276 bytes**: `playwright-e2e` **PASS**. It is now inside `puppeteer-audit` (child `npm run audit` → `node scripts/audit.mjs`, 47 s elapsed, Chrome actively driving routes). Only `puppeteer-audit` and `ui-thresholds` remain. No tenth run started; attached + Monitor re-armed on 927164. Working tree clean on entry.
#                                    **The most expensive gate in this build has now passed on the P5.8 tree.** `playwright-e2e` is the live-stack leg that needs Supabase up, and it cleared without a session touching it — the whole value of `setsid` is that the run outlives the agent session that launched it.
#                                    Prior: **Fifty-sixth session: the P5.8 gate run cleared 10/13 gates including `pytest`.**
#                                    Session 51's `setsid` run (PID 927164) was still alive at 18 minutes — `ruff`/`format`/`mypy`/`import-linter`/**pytest**/`web-typecheck`/`web-lint`/`web-build`/`web-test`/`impeccable-detect` all PASS. No new run started; attached + Monitor armed. See the P5.8 checklist entry.
#                                    Prior: **Forty-sixth session: P5.6 AND P5.7 are COMPLETE — 8/12 Phase-5 tasks done. Resume at P5.8 (screens S-28..S-31).**
#                                    **P5.7 in one line:** the 3-device policy (D1.11) was already correct and atomic; what was missing was any way for a user to *see* it. Backend `allow_eviction` + a 409 challenge on login + `GET`/`DELETE /api/me/devices`, then G-10 on the login screen and G-11 at `/settings/devices`. All 13 gates green at **90.83%** with the new screen at **axe 0 / Lighthouse a11y 100**. D5.12 recorded before the code.
#                                    **Two P5.7 gaps left deliberately for P5.11/P5.9, do not mistake them for covered:** G-10 has **no audit-registry entry** (it needs an account already holding three live devices — a seed precondition, not a navigation), and **no nav entry anywhere reaches `/settings/devices`** (the teacher sidebar needs an icon-map addition, the parent portal has no sidebar).
#                                    **New environment fact, cost real work: `npx prettier --write` is NOT this repo's formatter.** `web/` has no prettier config and does not depend on it, so a bare run silently reformatted 8 files with **semicolons** against the house semicolon-free style. The web gates are typecheck + oxlint + build + vitest + impeccable detect — **none of them formats**. Never run a formatter the gate chain does not run.
#                                    Prior: **P5.6 is COMPLETE.**
#                                    No code was written this session and nothing was re-implemented: every P5.6 chunk was already committed, and the single outstanding item was the first full gate run since chunk A. It came back **all 13 gates PASS, 0 skipped, exit 0, 2767 tests, coverage 90.78%** (develop 90.18%, P5.5 90.57% — no drop), `alembic check` clean. **Nothing was red.** Five chunks of notification work — a migration, a transport, seven routes and three award seams — landed green on first full contact, which is the return on the per-chunk targeted test runs that preceded it. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **P5.7 is next and it is the first Phase-5 task with a frontend leg** (G-10 device-limit UI + G-11 device management), so MISSION §6.8 applies to it and not to anything P5.6 did: axe, Lighthouse ≥95, screenshots, `/impeccable audit`, visual compare. The 3-device session registry itself is Phase-1 work (D1.11) and already exists — read it before assuming a backend gap.
#                                    Prior context: **Forty-fourth session — P5.5 (announcements + exam calendar) is COMPLETE.** All three chunks were committed by prior sessions; this session re-implemented nothing and only ran the outstanding gates. Full `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, exit 0, 2623 tests, coverage 90.57%** (develop 90.18% — no drop); `alembic check` clean. 6/12 Phase-5 tasks done. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **P5.4's `EXPECTED_TABLES` trap did not fire** — both new tables went into the set in the same commit as their `create_table`, which is what P5.4 told the next session to do. A written-down trap that costs nothing on its next encounter is the point of writing it down.
#                                    **Forty-fifth session: P5.6 chunks B and C1 built and committed** (C2a/b/c followed in the same session).
#                                    **D5.10 recorded before chunk B's code: a push carries NO payload** — an empty RFC 8030 body plus a VAPID auth header, with the service worker fetching the inbox over the authenticated API. That is D5.9 §1 stated on the wire rather than contradicted by it, and it keeps student notification content off Google/Mozilla/Apple push infrastructure. Zero new dependencies; `pywebpush` was measured (11 packages, incl. aiohttp) and hand-rolled RFC 8291 was rejected because **it could not be honestly verified here** — no test vector, no live push service, and a self-generated vector proves only self-agreement.
#                                    **Two traps this session paid for, both cheap next time.** (1) `Settings`/`NotificationTransport` in a router's `Annotated[...]` must be **runtime** imports, not `TYPE_CHECKING` — otherwise FastAPI hands pydantic an unresolvable ForwardRef and the route raises `PydanticUserError` on its *first request*, not at import. (2) A new `lemely/web/schemas_*.py` must be added to the `disallow_any_explicit` override list in `pyproject.toml`; every existing schemas module is already there.
#                                    **Previous (forty-third) session:** **Forty-third session — P5.4 (friends backend) is COMPLETE.** Its three code chunks were already committed by the two prior sessions; the only outstanding work was the gate run, and nothing was re-implemented. Full `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, 2532 tests / 6 live-only skips / 0 failures, coverage 90.48%** (develop 90.18% — no drop); `alembic check` clean. 5/12 Phase-5 tasks done. Branch `feature/phase-5-engagement`, not yet merged to develop.
#                                    **The gate run found one real defect** (`72330b8`): `tests/test_db_schema.py` asserts exact set equality against a hand-maintained `EXPECTED_TABLES`, and migration 0015's `friendships` was never added to it. Fixed by extending the set — exact equality is what forces a new table to be acknowledged deliberately. **The generalisable form: a new table costs two edits, the migration and that set.** 0013 and 0014 added only columns, so P5.4 was the first chance in this phase for the trap to fire, and it fires ~10 minutes into the run. Make the `EXPECTED_TABLES` edit in the same chunk as the `create_table`.
#                                    **Method note worth keeping:** `check.sh` suppresses output for gates that pass, so a green log contains no pytest counts at all — read coverage with `.venv/bin/coverage report --precision=2` off the run it just did, and get the test count from `pytest --collect-only -q --no-cov`. Never re-run the suite for a number; a second run costs ~10 minutes and risks the concurrent-`.coverage` corruption noted below.
#                                    **Then continued into P5.5 (announcements), chunk A of three committed as `446e7fa`.** Two things a resuming session must not redo. **(1) P5.0's recon was wrong: the school-admin whole-school audience is NOT missing** — it has been fully built since P3.8/D3.14 (`school_wide`/`school_id`, `school_admin`-only, exposed on the teacher POST). Verified by reading `announcement_repo.py` and `routers/announcements.py`, so P5.5 is three parts, not four. That is the **fifth** Phase-5 instance of a note paraphrasing the codebase from memory and being wrong — D5.2, D5.3, D5.4, D5.5 are the others, and the standing rule holds: *read the model; where a note restates the code, the code wins.* **(2) There is no CAIE timetable data anywhere on this machine** (checked `Sources/` and the PaperScraper corpus), so the exam calendar ships as table + ingestion path + honest empty state, never invented dates.
#                                    **Resume at P5.5 chunk B** — the student announcement endpoints. The service layer is built and tested; chunk B is router/DTO/deps wiring. Read the P5.5 checklist lines, which carry the full brief. `./scripts/check.sh` has NOT been run since chunk A — run it before P5.5 is marked done.
gemini_spend_usd: 0.18429   # MEASURED from the real ledger `outputs/gemini_spend.json`
# (cumulative_usd 0.18428610, updated 2026-08-09T12:01:17Z), not carried forward. This field
# had drifted: it read **0.1612** at the start of the thirty-ninth session while the ledger —
# the Phase-0 persistent tracker that actually enforces the $8 cap — read 0.18429. The field
# is a hand-copied mirror of the ledger and nothing generates one from the other, so it is the
# field that was wrong, never the ledger. Phase 3 closed at $0.1586, so **Phase 4 spent
# $0.0257** across the whole phase (every automated test mocks Gemini; D4.3 made that
# structural). Re-read the ledger rather than this line before quoting a spend figure.

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.
- Prune a phase's detail to a single summary line once its `reports/phase-N/REPORT.md`
  is committed and merged to develop (MISSION §8b) — full rationale lives in
  `BUILD/DECISIONS.md` and the phase report, not here.

## Phase 0 — Foundation repair — DONE (2026-07-30)
All 8 tasks complete: CI green (ruff/web), `lemely/io/det/` wired + monolith deleted (D0.5),
persistent Gemini cost ledger ($8 cap, D0.6), HistoryStore corruption surfaced, single lockfile,
`lemely doctor` real reachability. 395 passed / 84.56% cov. Merged to develop.
Report: `reports/phase-0/REPORT.md`. PR #3 (rolling develop→main, NOT merged).

## Phase 1 — Database + Auth + Tenancy — DONE (2026-08-01)
Local Supabase stack, 22-table schema (additive-only, D1.2/D1.3), GoTrue auth + backend-issued
HS256 JWTs (D1.4/D1.5), RBAC on every route + both IDORs killed (D1.6), HistoryStore→Postgres
for the web surface (D1.8/D1.9 — CLI/Gradio kept on JSON store), seat model (D1.10), 3-device
session registry (D1.11). Adversarial review: no Critical/High bypass (D1.12). 548 passed /
85.44% cov. Merged to develop. Report: `reports/phase-1/REPORT.md`.

### Carried backlog from Phase 1 (non-blocking, do opportunistically)
- [ ] todo — (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), then delete
      `lemely/io/history_store.py` + `tests/test_history_store.py`. Parity already proven.
- [x] done — (D1.6) Teacher per-tenant ownership (own-classes-only). Closed across P3.1
      (`ClassService` replaced the implicit "all students are one cohort" endpoints) and
      P3.3 (`/api/teacher/overview` stopped enumerating every student in the store; pinned
      by a two-teacher disjoint-class regression test). Row-level ownership is now real.

## Phase 2 — The core loop, real and end-to-end — DONE (2026-08-05)
Real SSE correction pipeline (P2.1), grade-boundary ingestion from cambridgeinternational.org
(P2.2, D2.1), accuracy harness + 10 golden fixtures across 0580/0606/0625 (P2.3), plagiarism/
AI-detection advisory flags (P2.4), Supabase Storage upload path (P2.5, D2.6), frontend
resurrected from dead code + auth/session foundation (P2.6), student + teacher surfaces wired
to real data (P2.7/P2.8), PWA foundation + camera capture (P2.9), Playwright E2E acceptance
verified against the live Supabase stack with an independent Postgres persistence check
(P2.10). 609 passed / 3 skipped (live-only) / 86.38% cov. Merged to develop (6254879), pushed.
PR #3 updated (title "Phases 0–2", body extended), NOT merged. ntfy sent.
Report: `reports/phase-2/REPORT.md`. Gemini cumulative spend $0.058/$8.00.

### Honest limitations carried forward from Phase 2 (must appear in DELIVERY.md, not silently resolved)
- **Accuracy gate NOT met (D2.5):** mark-level agreement 83.8% vs ≥95% target; flag_recall
  27.3% vs the 100%-disagreements-flagged target. Threshold tuning (D2.2/D2.3) and
  deterministic calculated-answer verification (D2.4) are both exhausted; the remaining gap
  is free-form algebraic method-verification — materially harder, out of scope so far.
- **PWA Lighthouse + camera-capture** not live-tested (no Chromium/camera in this sandbox,
  P2.9) — verified by inspection/manual trace only; see `reports/phase-2/pwa-limitations.md`.
  Needs a real-device/browser pass before claiming a hard pass.

## Phase 2.5 — Design system + frontend quality foundation — DONE (2026-08-05)
Token layer sourced from DESIGN.md (P2.5.1), C-1..C-13 component library + catalogue
(P2.5.2), Phase-2 screen retrofit onto tokens/components (P2.5.3), Impeccable audit+polish
(P2.5.4, D2.11), Playwright screenshot corpus (P2.5.5, D2.12), Puppeteer axe/Lighthouse
audit runner (P2.5.6), `scripts/check.sh` created from scratch — a Phase-0 mandate that had
never actually existed — plus a real CI-breaking `ruff`/`.claude` exclusion bug fixed along
the way (P2.5.7, D2.13), full QUALITY-BAR.md pass to zero serious/critical axe violations +
Lighthouse a11y 100 across all 4 in-scope routes (P2.5.8, D2.14). 609 passed / 85.54% cov
(zero backend files touched this phase; coverage delta from Phase 2 is environmental
live-test-skip variance, not a regression — see report §4). Merged to develop (fcc3e07),
pushed. PR #3 updated (title "Phases 0–2.5"), NOT merged. ntfy sent.
Report: `reports/phase-2.5/REPORT.md`. Gemini cumulative spend $0.058/$8.00 (unchanged —
pure frontend/tooling phase, zero LLM calls).
Decisions: D2.10–D2.14. Deferred/flagged component-library gaps for a future pass: see
report §8 (sub-44px touch target, non-heading empty/error tags, no mobile BottomNav, raw
`max-[1180px]:` literals outside the retrofitted screens, momentum-chart/TrendSparkline
duplication blocked on a DTO change).

## Phase 3 — Teacher + Parent surfaces — DONE (2026-08-07)
Real class model + teacher tenancy closing the last cross-tenant leak (P3.1, D3.1), the
at-risk flagging engine (P3.2, D3.3), teacher analytics T-04/T-05/T-06 (P3.3, D3.4), review
queue override-and-annotate + evidence-scoped acknowledgement (P3.4/P3.4b, D3.5), the quiz
builder end to end — bank, builder, assignment, student take/submit, auto-marking through the
*existing* engine, class results (P3.5, D3.6–D3.10, design fixed in `docs/quiz-model.md`),
parent portal backend + notification preferences (P3.6, D3.11), sixteen frontend screens
across three portals all on real data (P3.7 T-01..T-06, P3.8 T-07..T-10 + T-12 + the
announcements backend, P3.9 G-05 + P-01..P-04), and the acceptance/UI-gate pass that turned
`audit.mjs` from a 4-route single-journey script into a 24-route/34-state registry
(P3.10, D3.17/D3.18/D3.20). Plus the INBOX real-past-paper accuracy directive (D3.21) and the
MCQ integrity guard (D3.19). Blockers B1/B2/B3 all raised and resolved.
**1939 tests (1933 passed / 6 skipped / 0 failed) / 89.42% cov** (from develop's 609 /
85.54%); **all 13 gates green, 0 skipped**; 5 additive migrations, `alembic check` clean both
directions; 24 routes / 34 states audited with zero axe violations at any severity, zero
console errors, zero horizontal-scroll violations, Lighthouse a11y floor 96. Merged to develop
(49d9750), pushed. PR #3 updated (title "Phases 0–3"; its body had never actually carried a
Phase-2.5 section despite that phase's STATE line claiming so — added in the same edit), NOT
merged. Report: `reports/phase-3/REPORT.md`. Gemini cumulative spend **$0.1586 / $8.00**.

### Honest limitations carried forward from Phase 3 (must appear in DELIVERY.md, not silently resolved)
Full text in `reports/phase-3/REPORT.md` §7. The ones that change what a later phase may
assume:
- **The question bank is empty and corpus growth cannot change that (D3.7).** A mark scheme
  holds marking points; the question *stem* lives in the question paper and no stem extractor
  exists. This is a **P4 prerequisite**, not an assumption — do not re-run the measurement.
- ~~**At-risk rule 2 cannot fire until P4 supplies target grades (D3.3)**~~ — **CLOSED by P4.3**
  (D4.5). Targets are real and per-subject, the rule fires, and `below_target` is now in the T-06
  reason filter. The *not evaluable* state survives and got stricter, not weaker.
- **Teacher-route Lighthouse performance floors at 67** (`teacher-quiz-detail`). MISSION §11's
  ≥80 floor covers the student routes (met, floor 82) and never covered these.
- **Lighthouse runs on `default` states only**; axe runs on all 34 (deliberate, D3.17).
- **`web/e2e/` + `playwright.config.ts` are in no tsconfig `include`** — the most expensive
  gate has never been typechecked (D3.20).
- **Students cannot see announcements**; `notification_preferences` is written and read by
  nothing. Both are **P5's**, and P5 must not assume Phase 3 left it a helper.
- **Paper 22 was confidently wrong (D3.21):** all 40 marks at confidence 1.0, zero review
  flags, 3 marks of pure vision/transcription error. Propagating extraction confidence into
  per-question confidence on the deterministic MCQ path changes the marking contract and was
  deliberately not patched at phase end.
- **Phase 2's synthetic-golden-set accuracy gate is unchanged** (83.8% vs ≥95%). The
  real-paper measurement is on top of it, not a replacement.

### Task checklist
- [x] done — P3.1 / P3.1b / P3.2 / P3.3 / P3.4 / P3.4b / P3.5 (chunks C,A,G,B,D,E,F1,F2) /
      P3.6 (a,b) / P3.7 (a–d) / P3.8 (a–d) / P3.9 (a–d) / P3.10 (a–e) / P3.10-B3 /
      INBOX-2026-08-07-ACC. Per-task rationale is pruned per MISSION §8b now that the report
      is committed and merged — see `reports/phase-3/REPORT.md`, `BUILD/DECISIONS.md`
      (D3.1–D3.21), `BUILD/BLOCKERS.md` (B1–B3), or this file's git history.
- [x] done — **P3.11** Phase-3 report, merge to develop, push, update PR #3, ntfy.

## Phase 4 — Content generation + study plans — DONE (2026-08-09)
Question-stem extractor closing D3.7 (P4.1, D4.1/D4.2 — 72 papers → 273 banked 0625 stems),
syllabus taxonomy transcribed from the three official CAIE PDFs + classification (P4.2, D4.4),
student profile/onboarding data model that finally activates at-risk rule 2 (P4.3, D4.5,
migration 0009), placement backend reusing the *existing* quiz engine behind an XOR-checked
student-owned-quiz shape (P4.4, D4.6–D4.9, migration 0010), practice generator with tri-state
availability (P4.5, D4.10), flashcards + clock-injected SM-2 (P4.6, D4.11, migration 0011),
the adaptive study plan — pure scheduler, persisted, superseding weekly regeneration (P4.7,
D4.12/D4.13, migration 0012), and the ten screens S-01..S-05 / S-20..S-25 (P4.8/P4.9/P4.10,
D4.14–D4.22), closed by the acceptance + UI-gate pass (P4.11, D4.23–D4.25) that took `web/e2e/`
from 8 files/14 tests to 11/25.
**2350 tests (2344 passed / 6 skipped / 0 failed) / 90.18% cov** (from develop's 1939 /
89.42%); **all 13 gates green, 0 skipped**; 4 additive migrations, both directions clean;
122 axe route-states with zero violations at any severity, zero console errors, zero
horizontal-scroll violations, Lighthouse a11y floor 96; cross-phase compare 81 added /
**0 removed** / 78 changed. Merged to develop (321fdfc), pushed. PR #3 updated (title
"Phases 0–4"), NOT merged. Report: `reports/phase-4/REPORT.md`. Gemini cumulative
**$0.18429 / $8.00** (Phase 4 itself $0.0257 — everything built with Gemini mocked).

### Honest limitations carried forward from Phase 4 (must appear in DELIVERY.md, not silently resolved)
Full text in `reports/phase-4/REPORT.md` §7. The ones that change what a later phase may assume:
- **The Lighthouse performance floor MISSION §11 claims is gated is NOT enforced (D4.25).**
  `scripts/check_ui_gates.py` has no performance check at all; a student route sits at **79**
  and `ui-thresholds` passes. Do not cite MISSION §11's "performance ≥ 80" as a met gate.
  The specific failing route is not stable between runs; the gap is.
- **0580 and 0606 have zero ingested questions**, so placement and practice honestly refuse for
  two of three subjects. The ceiling is **mark-scheme parse coverage (32/72 for 0625)**, not
  stem extraction — that is the highest-leverage thing to improve, and it is not a P5 blocker.
- **A practice set is marked but its result cannot be read** — marking runs, marks are in the DB,
  no route exposes them for `kind=practice`. Only the *read* is missing.
- **`web/e2e/` + `playwright.config.ts` are still in no tsconfig `include` (D3.20)** — now
  covering 25 test blocks, none of them ever typechecked.
- **XP is entirely P5's and the seam is `completed_at`** (D4.17/D4.19). S-23 and S-25 deliberately
  ship with no XP number. ~~No points or streak column exists~~ — **CORRECTED 2026-08-09 at P5.0
  by reading the migrations rather than trusting this line: the schema DOES exist.** `xp_events`
  (user_id, source, amount, awarded_on, metadata, indexed on user_id+awarded_on) and `streaks`
  (current_length, longest_length, last_active_on, freezes_available, unique per user) were both
  created in **migration 0002**, Phase 1's core schema, with an `xpsource` enum whose four values
  — `paper_corrected`, `quiz_completed`, `flashcard_reviewed`, `study_session_completed` — are
  exactly MISSION §4 Phase-5's four XP sources. `lemely/db/models/engagement.py` maps both and
  `models/__init__.py` exports them. **What is genuinely absent is every line of behaviour**: no
  repo, no service, no route, no award call site, nothing reads or writes either table. So P5 needs
  no migration for core XP/streak, and the accurate form of this limitation is *"XP has schema and
  zero behaviour."* Same failure mode as the `gemini_spend_usd` and `SeedContract` drifts — a
  hand-written mirror of a fact that nothing regenerates. Verify against the migrations.
- **Phase 2's synthetic accuracy gate is unchanged** (83.8% vs ≥95%) and **D3.21's paper 22 is
  still confidently wrong** (40/40 marks at confidence 1.0, zero flags, 3 marks of pure
  vision/transcription error).
- **The visual compare can never be pixel-clean:** the seed's `run_tag` is random per run, so
  every screen rendering a class name changes on every re-baseline. `0 removed` is the number
  that carries the gate; a nonzero `changed` count is not by itself a regression signal.

### Task checklist
- [x] done — P4.1 / P4.2 / P4.3 / P4.4 (chunks A, B-1..B-4) / P4.5 / P4.6 (A,B,C) / P4.7 (A,B,C) /
      P4.8 (0,A,B,C) / P4.9 (0,A,B,C) / P4.10 (A,B,C,D) / P4.11 (A,B,C,D,E). Per-task rationale is
      pruned per MISSION §8b now that the report is committed and merged — see
      `reports/phase-4/REPORT.md`, `BUILD/DECISIONS.md` (D4.1–D4.25), or this file's git history.
- [x] done — **P4.12** Phase-4 report, merge to develop, push, update PR #3, ntfy.

## Phase 5 — Engagement layer — IN PROGRESS (started 2026-08-09, fortieth session)
See MISSION §4 (Phase 5) + UI spec §4.6 (S-28..S-31), §4.5 (G-10..G-13), T-12.

### What P5.0 reconnaissance established (measured, not assumed — do not re-derive)
- **XP/streak schema already exists** (migration 0002) — see the corrected Phase-4 limitation
  above. Tables `xp_events` + `streaks`, enum `xpsource` with exactly the four MISSION sources.
  Zero behaviour attached. **No migration needed for core XP or streaks.**
- **Tables that exist and P5 can build on:** `announcements`, `notifications`, `devices`,
  `xp_events`, `streaks`, plus the `notification_preferences` work from migration 0008.
- **Tables that genuinely do NOT exist and P5 must add:** friendships, push subscriptions,
  leaderboard opt-out flag, announcement read-receipts. (`grep create_table` over
  `lemely/db/migrations/versions/` is the cheap way to re-check this.)
- **Announcements are teacher-write-only today.** `lemely/web/routers/announcements.py` mounts
  at prefix `/api/teacher/announcements` and exposes exactly POST / GET / DELETE. There is **no
  student-facing read route at all** — that is what "students cannot see announcements" means.
  School-admin → whole-school audience is also absent.
- **`notification_preferences` is wired to a service and a DTO but gates nothing.**
  `NotificationPreferencesService` exists (`lemely/db/notification_prefs_repo.py`), `deps.py`
  provides it, `routers/me.py` reads/writes it. What is missing is any *consumer* — no send path
  consults it, because no send path exists.
- **The student leaderboard screen already exists and is honestly empty.**
  `web/src/portals/student/screens/Standings.tsx` (route `student/board`) is wired to
  `GET /student/standings`; its header comment records that the friends/school/global boards and
  the 28-cell streak heatmap were *deliberately removed* rather than mocked, because
  `StandingsDTO` has no `boards` field and no backend existed. **P5 fills that gap; it does not
  start from a mock.** Subject standings there is already real.

### Task checklist
- [x] done — **P5.0** Reconnaissance + phase plan (this section); Phase-4 XP limitation corrected.
- [x] done — **P5.1** XP + streak + leaderboard **spec** recorded in `BUILD/DECISIONS.md` (D5.1)
      **before any implementation** — MISSION §4 Phase 5 mandates this ordering explicitly. Must
      fix: per-source award amounts, anti-farming caps, the streak day boundary + timezone,
      streak-freeze grant/consume rules, the weekly leaderboard window + reset, and opt-out
      semantics. Constrained by UI spec §1.4 (XP public / grades private) and MISSION §3
      ("leaderboards show XP, never grades").
- [x] done — **P5.2** XP engine backend, both chunks. **Full suite on the committed tree:
      exit 0, 6 live-only skips, 90.30% cov** (develop 90.18% — no drop); ruff, ruff format,
      mypy (186 files), lint-imports, `alembic check` all clean. `xp_repo.py` and
      `xp_awards.py` both 100% covered.
      - [x] **chunk A** (`e786657`) — migration 0013 + `lemely/db/xp_repo.py` (`XpService`:
            award / total_xp / xp_breakdown / streak, Cairo civil-date helper, per-source +
            global daily caps, lazy streak resolution with freeze grant/consume) + 42 tests.
            D5.2 recorded: the column is **`subject_code`** (String FK to `subjects.code`), not
            D5.1 §7's `subject_id` UUID — eight other subject-scoped tables key on the code and
            every award seam already carries one. `alembic check` clean **both directions**.
            **Trap found and fixed, worth not repeating:** the dev DB had the *pre-amendment*
            0013 (`subject_id`) applied, so `alembic check` failed while `pytest` passed — the
            tests build their schema fresh, the dev DB does not. After amending an
            **uncommitted** migration, drop its artifacts, `alembic stamp` the previous
            revision, and re-upgrade; otherwise the file and the DB silently disagree.
      - [x] **chunk B** (`8fc3bc4`) — the four award seams, all wired at the **router** layer
            (not inside the repo services: `XpService` owns its own sessionmaker and would
            otherwise interleave transactions with a service that has just committed;
            `quiz.py` already composed two services per endpoint, so this follows the house
            pattern). Every seam goes through the single fail-open helper
            `lemely/web/xp_awards.py::award_xp_safely`, which logs and swallows an XP failure
            so an already-committed student action can never be turned into an error response
            (D5.1 §3, "the learning wins") — proven with an injected failing double.
            `get_xp_service()` added to `deps.py` + `reset_singletons()`. Three internal
            service dataclasses (`SubmitResultRow`, `SessionView`, `ReviewOutcome`) grew a
            `subject_code` field; **no wire DTO changed**, so the frontend is untouched.
            **D5.3 — the defect worth remembering.** The paper seam's first cut deduped on the
            *attempt* id. `persist_correction` inserts a fresh `Attempt` every call, so that key
            is re-minted on every re-correction and the unique index never fires: a student
            re-running `/student/correct` on one PDF could farm **250 XP/day** (the 5/day cap),
            which is exactly what D5.1 §8 ("a paper can be re-marked … none of those may
            re-award XP") exists to prevent. Now keyed on `owned.id`, the **upload**. Verified
            by inversion — reverting the key fails both regression tests on `2 != 1` xp_events
            rows, and those tests also assert two `Attempt` rows exist so they cannot pass by
            the pipeline having declined to re-run. **The brief, not the spec, was wrong:** the
            orchestrator's task table paraphrased §8 and lost its meaning. Where a brief
            restates a spec, the spec wins.
            `flashcard_reviewed` is deliberately NOT deduped between two reviews of one card
            (repeat review is the point of SM-2); its control is the 60/day cap. Pinned by a
            test so nobody "fixes" it into the paper seam's shape.
- [x] done — **P5.3** Leaderboards backend, both chunks. **Full `./scripts/check.sh` on the
      committed tree: all 13 gates PASS, 0 skipped; coverage 90.43%** (develop 90.18% — no
      drop). `routers/leaderboard.py` and `schemas_leaderboard.py` 100% covered,
      `leaderboard_repo.py` 98%.
      - [x] **chunk A** (`e5c945b`) — migration 0014 (`student_profiles.leaderboard_opt_out`)
            + `lemely/db/leaderboard_repo.py`: the weekly window (D5.1 §6, Monday 00:00 →
            Sunday 23:59:59 Cairo, summed from `xp_events` every time — no denormalized
            column), class/school/global scopes, per-subject basis on
            `xp_events.subject_code`, own-row pinning, opt-out in the query's WHERE clause.
            The D5.1 §0 guard test compiles the emitted SQL and asserts it joins no marking
            table. **D5.4 — the brief was wrong about the schema:** it specified the school
            scope on `school_memberships`, which is *staff only* (`MembershipRole` has exactly
            `teacher`/`school_admin`); no student ever has such a row, so the school board
            would have been permanently empty and read as a data problem, not a defect.
            Students reach a school through `Seat` (`school_id` + `assigned_user_id`, status
            not `revoked`), as `class_repo`/`seat_repo` already do. Same failure mode as D5.2.
            Two smaller catches in the same chunk: `RANK() OVER (ORDER BY xp DESC, user_id)`
            broke ties into 1 and 2 — the tiebreak moved to the outer `order_by` so equal
            effort reads as equal standing; and the opt-out join must be an **outer** join
            with `coalesce(..., false)`, since a student who never onboarded has no
            `student_profiles` row and an inner join would have erased exactly them.
      - [x] **chunk B** (`3a2c445`) — `GET /api/student/leaderboard`
            (`scope=class|school|global`, `basis=total|<subject code>`, `class_id`, `limit`),
            student-role-only, in its own thin router; `leaderboard_opt_out` threaded through
            `student_profile_repo` → `me.py` → `StudentProfileDTO`; `get_leaderboard_service()`
            in `deps.py` + `reset_singletons()`.
            **The DTOs are structurally answer-only (D5.1 §0)** — no field shaped like a mark,
            grade or percentage *exists* on them, and `tests/test_schemas_leaderboard.py`
            introspects the field sets, so a well-meaning future addition fails a test instead
            of reaching the wire. `leaderboard_opt_out` is NOT NULL on the model, so an
            explicit `null` in `PATCH /me/profile` is a 422, never a coerced `False`.
            **D5.5 — the defect worth remembering.** `display_names_for()` first copied the
            codebase-wide `display_name or email` fallback (`quiz_taking_repo` and siblings
            each re-declare it). `users.display_name` is nullable at signup, so it fires for
            real users. That fallback is safe where the audience is one class; the **global
            board's audience is every student on the platform**, so the identical line
            broadcasts a real contact address to strangers. The query no longer selects
            `users.email` at all — unnamed students rank normally as `"Student"`. Pinned by a
            test asserting over the **response body** that no `@` appears anywhere in it.
            Errors: not-enrolled-in-the-requested-class is **403 and never an existence
            oracle** (the service checks enrolment only, so "no such class" and "not your
            class" are indistinguishable); school-scope-with-no-school is a **successful
            `unavailable`** response, never a 404 and never a falsely empty board, which would
            assert the untrue "nobody scored this week".
            Judged and deliberately not fixed: `board()`'s three queries are not pinned to one
            snapshot, so a concurrent award can make the viewer's row disagree with the top-N
            by a few XP. Self-corrects next request; a leaderboard is an inherently stale read.
      - **Not done here, by design:** the **friends** scope waits on P5.4's table, and the
        consuming screen waits on P5.8. `web/src/portals/student/screens/Standings.tsx`
        (`student/board`) is still on `GET /student/standings`, whose `StandingsDTO` has no
        `boards` field — nothing frontend changed this task.
- [x] done — **P5.4** Friends backend + migration (requests in/out, accept, remove, privacy).
      **Full `./scripts/check.sh` on the committed tree: all 13 gates PASS, 0 skipped;
      2532 tests, 6 live-only skips, 0 failures; coverage 90.48%** (develop 90.18%,
      P5.3 90.43% — no drop). `alembic check` clean.
      **One defect the gate run found, fixed as `72330b8`:** `tests/test_db_schema.py`
      asserts *exact set equality* between `Base.metadata.tables` and a hand-maintained
      `EXPECTED_TABLES`; migration 0015's `friendships` was never added to it, so the
      suite failed on `Extra items in the left set: 'friendships'`. Fixed by extending the
      set, not by loosening the assertion — exact equality is the whole point of that test.
      **Worth not re-learning: a new table costs two edits, the migration and this set.**
      P5.2's and P5.3's migrations (0013, 0014) added only *columns*, so this is the first
      time in Phase 5 the trap could fire, and it fires ~10 minutes into the gate run.
      Add the table to `EXPECTED_TABLES` in the same chunk that writes the `create_table`.
      **Also lands the leaderboard's fourth scope**: add `LeaderboardScope.friends` to
      `lemely/db/leaderboard_repo.py` once the friendships table exists. Everything else it
      needs is built — follow the existing `_membership_subquery` shape, keep the opt-out in
      the WHERE clause, and extend the D5.1 §0 emitted-SQL guard test to the new scope.
      Three code chunks, all committed by earlier sessions and none re-implemented since:
      `7397df0` (chunk A), `71d1a9b` (chunk B), `63a4bbc` (the D5.7 race fix). The
      forty-third session ran the outstanding gates and closed the task.
      - [x] **D5.7 fix** (`63a4bbc`) — `FriendService.request`'s genuinely-new-pair INSERT had no
            `IntegrityError` handling, and sat bare inside `with session.begin()`, so a lost race
            on `uq_friendships_pair` surfaced at COMMIT — after `request()` returned, outside any
            frame `routers/friends.py` can catch. Two tabs POSTing the same first-ever friend code:
            one 201, one raw **500**. Now `session.begin_nested()` + catch, resolving the winner
            through the *same* `_resolve_existing_pair` helper the sequential path uses so the two
            cannot drift. Not an integrity defect — the constraint always won (D5.6 holds).
            **The prior session's inversion claim was wrong and D5.7 is corrected in place:**
            re-running it here (savepoint → `if True:`) fails both tests, but the `IntegrityError`
            never reaches COMMIT — the failing `flush()` **poisons the enclosing transaction**, so
            the recovery SELECT dies first with `InvalidRequestError`. Same 500; the lesson is
            different and worth keeping: **a savepoint is what makes the error recoverable, not
            merely catchable.** Once the outer transaction is poisoned there is nothing left to
            re-read with. *Verify an inherited "proven by inversion" note before repeating it —
            a claim about a test is not the test.*
      - [x] **chunk A** (`7397df0`) — migration 0015 (`friendships` + `users.friend_code`) +
            `lemely/db/friend_repo.py` (`FriendService`) + `LeaderboardScope.friends` + tests.
            D5.6 recorded. One friendship is one row (canonical `pair_low`/`pair_high`, unique
            index + three CHECKs), so the reciprocal row is a database error, pinned by a test
            that inserts through the session rather than the service.
      - [x] **chunk B** (`71d1a9b`) — `GET/POST/DELETE /api/student/friends` in its own thin
            router mirroring P5.3's `leaderboard.py`; `schemas_friends.py`; deps; tests.
            Identity is structurally the token's `sub` on every route — no caller-supplied user
            id exists on this router. Two defects found while wiring: `POST /requests` derived
            the other party from `addressee_id`, which is the *caller* in the crossed-requests
            case (now derived from whichever end the caller is not on, and the response reports
            `accepted` there); and `accept` matched the returned row against the raw path string,
            but `uuid.UUID` accepts uppercase/braces/`urn:uuid:` forms that normalise
            differently — those would have accepted and then fallen through to a 500.
      Design fixed before implementation (to be recorded as D5.6): **`users` has no
      `username` column**, so S-30's "add by username" is unbuildable as written; a
      nullable-unique `users.friend_code` (8 chars, ambiguity-free alphabet, minted lazily)
      serves both the typed code and the invite link, and avoids the two bad alternatives —
      searching by `display_name` (not unique, and lets a student enumerate strangers) and
      searching by email (the exact leak D5.5 killed). One row per pair, canonicalised into
      `pair_low`/`pair_high` with a unique index + three CHECK constraints, so a duplicate or
      reciprocal friendship is a database error rather than a service-layer convention
      (D5.1 §8's reasoning applied to a second table).
- [x] done — **P5.5** Announcements: student-facing read + read-receipts, school-admin audience,
      auto-populated official CAIE session dates for the exam calendar.
      Backend only — the consuming screens are P5.8/P5.9. UI spec §S-28 (line 725) is the
      product truth for what the student surface must eventually hold.
      **Closed by the forty-fourth session's gate run — nothing was re-implemented.** All three
      chunks were already committed; the only outstanding work was the gates. Full
      `./scripts/check.sh`: **all 13 gates PASS, 0 skipped, exit 0**; **2623 tests**;
      **coverage 90.57%** (develop 90.18%, P5.4 90.48% — no drop); `alembic check` clean.
      **P5.4's `EXPECTED_TABLES` trap did NOT fire this time** — chunks A and C each added
      their table (`announcement_reads`, `exam_dates`) to the set in the same commit as the
      `create_table`, which is exactly the fix P5.4 wrote down. The lesson held on first
      contact; keep doing it.
      **P5.0's reconnaissance was WRONG on one of the three bullets — corrected here by reading
      the code, and this is the fifth instance in Phase 5 of the same failure mode.** P5.0 wrote
      that the "school-admin → whole-school audience is also absent". **It is not: it has been
      fully built since P3.8/D3.14.** `AnnouncementService.create` takes `school_wide` +
      `school_id`, restricts it to `Role.school_admin`, validates the target through
      `ClassService.member_school_ids`, and writes the `school_id`-set/`class_id`-NULL row; the
      router exposes it as `schoolWide`/`schoolId` on `POST /api/teacher/announcements`. Do not
      rebuild it. Verified in `lemely/db/announcement_repo.py:141-230` and
      `lemely/web/routers/announcements.py:100-134`. **So P5.5 is a three-part task, not four.**
      What P5.0 got right, re-verified: `announcements`/`notifications` exist, the router mounts
      only at `/api/teacher/announcements` with exactly POST/GET/DELETE, and there is genuinely
      **no student-facing read route at all**.
      - [x] **chunk A** (`446e7fa`) — migration 0016 (`announcement_reads`) + the student read
            path on `AnnouncementService` (`list_for_student`, `unread_count_for_student`,
            `mark_read`, `StudentAnnouncementRow`, `DEFAULT_STUDENT_LIMIT`) + 17 tests.
            `alembic check` clean **both directions**; ruff/format/mypy(195 files) clean; the
            three related test files pass (57 tests). **Not yet run: the full suite / `check.sh`.**
            The school arm keys on **`Seat`, not `SchoolMembership`** (D5.4), and `publish_at`
            is now honoured for students but deliberately **not** for the author's own list.
            **Both guards verified by inversion, not asserted:** swapping the school arm back to
            `SchoolMembership` fails `test_school_wide_announcement_reaches_a_seated_student`
            with the student seeing an *empty list* — the exact "reads as a data problem"
            shape D5.4 warns about; replacing the `publish_at` predicate with `sa.true()` fails
            2 tests. `announcement_reads` went into `EXPECTED_TABLES` in the same commit.
            The clock is now injected (`now=`) and the docstring that asserted its absence was
            corrected rather than left contradicting the code.
      - [x] **chunk B** (`51657f8`) — the student announcement endpoints:
            `lemely/web/routers/student_announcements.py` (`GET ""`, `GET "/unread-count"`,
            `POST "/{id}/read"`), `schemas_announcements_student.py`, app wiring, 24 route
            tests + 11 schema-introspection tests. **`deps.py` needed no new entry** —
            `get_announcement_service` has existed since P3.8 and is reused, so the student
            and their teacher share one clock and cannot disagree about whether a scheduled
            announcement is published; `reset_singletons()` already covered it. The brief
            predicted a deps pair here and was wrong; the code won.
            Two guards **verified by inversion**: `publishedAt` is the *effective* time
            (`publish_at or created_at`) and the only time field on the wire — shipping
            `created_at` too would let a screen sort by typing time and disagree with the
            server's ordering; and the read receipt echoes the **canonical** id, because
            `uuid.UUID` accepts `urn:uuid:`/uppercase/braces forms and echoing the raw path
            hands back an id that never matches the list response (P5.4 chunk B's lesson,
            second sighting).
      - [x] **chunk C** (`5713238`) — the exam calendar. Migration 0017 (`exam_dates`)
            + `lemely/db/exam_calendar_repo.py` (`ExamCalendarService`: `ingest`,
            `parse_timetable_payload`, `calendar_for_student`) + `schemas_exam_calendar.py`
            + `routers/exam_calendar.py` (`GET /api/student/exam-calendar`, read-only) +
            deps/`reset_singletons`/app wiring + 41 tests. **D5.8 recorded** with the full
            rationale. `alembic check` clean both directions.
            **`exam_dates` went into `EXPECTED_TABLES` in the same edit as the
            `create_table`** — P5.4's trap, not re-sprung.
            **The table ships empty and that is the deliverable**, not a gap: no CAIE
            timetable exists on this machine, so ingestion is built and *nothing* populates
            a row. Three empty causes are kept apart (`no_enrolment` / `no_timetable` /
            per-paper `no_session`) because collapsing the first two would blame Cambridge
            for a blank the student can fill in themselves. The grain is the paper
            **variant**, with `paper_number` stored beside it (the only key the student's
            declared papers can join on) — number-grain storage would have forced the
            ingester to discard real dates. Past dates are deliberately **not** filtered and
            the service takes **no clock**: dropping them would empty a calendar mid-series
            and make `no_timetable` fire when we hold all the data.
            Two guards **verified by inversion**: collapsing `no_enrolment` into
            `no_timetable` fails 2 tests, and dropping the self-contradicting-batch rejection
            fails another. Two real traps found while building — `sa.Enum(..., create_type=
            False)` silently ignores the flag and re-`CREATE TYPE`s an existing enum (use
            `sa.dialects.postgresql.ENUM`; `pytest` passed while `alembic upgrade` failed),
            and **this FastAPI version wraps included routers in an opaque `_IncludedRouter`
            with no `.path`**, so a route-introspection test over `app.routes` finds nothing
            and passes for the wrong reason — read `app.openapi()["paths"]` instead.
            **Honest gap carried to the Phase-5 limitations:** there is no CLI wrapper around
            `ingest` yet (service + parser only), deliberately not built speculatively while
            no document exists to feed it.
- [x] done — **P5.6** Notifications inbox + web push (VAPID) with a headless-testable
      transport, and make `notification_preferences` actually gate delivery.
      **Closed by the forty-sixth session's gate run — nothing was re-implemented.** All
      five chunks (spec, A, B, C1, C2a/b/c) were already committed; the only outstanding
      work was the first full run since chunk A. Full `./scripts/check.sh`: **all 13 gates
      PASS, 0 skipped, exit 0**; **2767 tests**; **coverage 90.78%** (develop 90.18%,
      P5.5 90.57% — no drop); `alembic check` clean. **Nothing was red** — the three
      seams, the transport and the routes all landed green on first full contact, which
      is what the per-chunk targeted test runs were buying.
      Backend only — the consuming screens are P5.9 (G-12/G-13). MISSION §4 Phase-5 names the
      four triggers: grades ready, new announcement, streak about to break, study-plan reminder,
      plus at-risk alerts to the teacher and (if opted in) the parent.
      **Recon done 2026-08-10 by reading the models, not by paraphrasing a note** (this is the
      sixth Phase-5 task where that distinction mattered — D5.2/D5.4/D5.5, P5.5's own header, and
      the two deps predictions that were wrong):
      - **`notifications` exists and has ZERO writers.** `lemely/db/models/ops.py:140` —
        `id`/`user_id`/`type`/`title`/`body`/`payload` (JSONB, defaults `{}`)/`read_at`, indexed
        on `(user_id, read_at)`. `grep -rln "Notification("` over `lemely/` excluding `models/`
        returns **nothing**: no repo, no service, no route, no call site. So the inbox is a
        genuinely empty build, not a retrofit — but **no migration is needed for the inbox
        itself**, exactly like P5.2's XP tables.
      - **`NotificationType` has exactly five values** (`enums.py:164`): `grade_ready`,
        `announcement`, `streak_warning`, `study_plan_reminder`, `at_risk_alert`.
      - **`notification_preferences` already has one boolean per type, same five names**
        (`ops.py:335`), all `NOT NULL DEFAULT true`, **plus `quiet_hours_start`/`quiet_hours_end`
        (nullable `Time`)**. So "make preferences gate delivery" needs **no schema work** — the
        toggles are there and `NotificationPreferencesService.get/set`
        (`lemely/db/notification_prefs_repo.py`) already reads them. What is missing is a
        *consumer*, because no send path exists. The service's `get` returns an all-defaults row
        for a user with no row, so the gate must treat "never configured" as opted-**in**.
      - **Nothing anywhere mentions VAPID or push subscriptions** — `grep -rlin
        "vapid|push_subscription"` over `lemely/` and `web/src/` is empty. **The push
        subscription table is the one genuine migration this task needs** (P5.0 listed it, and
        that bullet is confirmed).
      **Design to fix in DECISIONS.md before implementing** (P5.1 set this precedent and MISSION
      §4 mandates it for the engagement layer): the transport seam. Web push cannot be sent from
      a headless test, so define a `NotificationTransport` protocol with a real VAPID
      implementation and a recording in-memory double, choose it in `deps.py`, and make the
      **inbox row the source of truth with push as a best-effort side effect** — a failed push
      must never lose a notification or fail the action that produced it (D5.1 §3's fail-open
      reasoning, already implemented once in `lemely/web/xp_awards.py::award_xp_safely`).
      Also decide: quiet-hours semantics (suppress the *push*, never the inbox row — the student
      must not silently lose a notification because it arrived at 2am), and whether
      `at_risk_alert` to a **parent** consults the parent's own preference row (it must — the
      opt-in in MISSION §4 is the parent's, not the student's).
      **Traps already paid for, do not re-spring:** a new table costs **two** edits, the
      migration and `EXPECTED_TABLES` in `tests/test_db_schema.py` (P5.4) — make both in the same
      chunk; use `sa.dialects.postgresql.ENUM` if a new enum is involved, because
      `sa.Enum(..., create_type=False)` silently re-`CREATE TYPE`s and passes pytest while
      `alembic upgrade` fails (P5.5 chunk C); and a route-introspection test must read
      `app.openapi()["paths"]`, not `app.routes`, which this FastAPI version wraps in an opaque
      `_IncludedRouter` with no `.path` so the test passes for the wrong reason (P5.5 chunk C).
      Check whether `get_notification_preferences_service` already exists in `deps.py` before
      adding one — the last two briefs predicted a deps entry that was already there.
      - [x] **spec** (`369ef68`) — **D5.9 recorded before any code**, per MISSION §4. Load-bearing
            calls: the inbox row is the source of truth and push is a best-effort side effect that
            can never fail the action producing it; **a type toggle off suppresses the row too**
            (content preference) while **quiet hours suppress only the push** (timing preference,
            row still written) — safe precisely because a notification is always a pointer and
            never the data; a missing prefs row means opted-**in**; parent at-risk alerts read the
            **parent's** prefs so a student cannot silence alerts about themselves; VAPID keys
            absent ⇒ transport reports itself unavailable rather than erroring (this machine has
            no keys); a 404/410 from a push service **deletes** the subscription; `grade_ready`
            dedupes on the **upload**, not the attempt (D5.3 written down before it can recur);
            and — **the honest gap** — `streak_warning`/`study_plan_reminder` are time-triggered
            with **no scheduler in this build**, so they ship as service methods nothing invokes
            on a timer. Do not build a scheduler daemon; carry it to the Phase-5 limitations.
      - [x] **chunk A** (`e9c3ca1`) — migration 0018 + `lemely/db/notification_repo.py`
            (`NotificationService`: create/mark_read/mark_all_read/list_for_user/counts,
            subscribe/unsubscribe/forget_endpoint/subscriptions_for) + 60 tests.
            ruff/format/mypy(203 files)/lint-imports clean; `alembic check` clean **both
            directions**; the three related test files pass (71 tests).
            **Not yet run: the full suite / `check.sh`.**
            **The brief was wrong that the inbox needs no migration** — it needs no *table*, but
            D5.9 §6's per-upload idempotency has nowhere to live on the existing row, so
            `notifications` gained a `dedupe_key` column mirroring 0013's `xp_events.dedupe_key`:
            nullable, **partial** unique index `WHERE dedupe_key IS NOT NULL` so the types with no
            natural key (two study-plan reminders a week apart are two real reminders) stay
            exempt. Sixth instance this phase of the code beating the note.
            **D5.9 §2's split verified by inversion, both halves:** forcing the preference gate
            to always-enabled fails 2 tests; making quiet hours drop the row as well as the push
            fails `test_quiet_hours_write_the_row_and_only_block_the_push`.
            `push_subscriptions` went into `EXPECTED_TABLES` **in the same commit** — third table
            running to avoid P5.4's trap.
            **Worth not re-deriving: Cairo is UTC+3 in August, not +2** (Egypt reinstated summer
            time in 2023), so quiet hours convert through `ZoneInfo` and the test pins an August
            *and* a January instant. A hardcoded offset is wrong by exactly one hour for half the
            year. Also: `Session.execute` is typed as returning `Result`, which has **no
            `rowcount`** — narrow through a one-attribute `Protocol`, since mypy here forbids
            explicit `Any` so `cast("CursorResult[Any]", ...)` fails the gate.
      - [x] **chunk B** (`58fa04c`) — the transport seam: `lemely/web/push.py`
            (`NotificationTransport` protocol, `VapidPushTransport`,
            `RecordingPushTransport`, `PushResult`/`PushOutcome`), `PushSettings` in
            `lemely/runtime/config.py`, `get_push_transport` + `get_notification_service`
            in `deps.py` + `reset_singletons()`, 37 tests.
            ruff/format/mypy(204 files)/lint-imports clean. **Not yet run: the full
            suite / `check.sh`.**
            **D5.10 recorded before the code, and it supersedes D5.9 §4's
            `send(subscription, payload)` sketch: a push carries NO payload.** Empty
            RFC 8030 body + RFC 8292 VAPID `Authorization` header; the service worker
            fetches the inbox over the authenticated API. That is D5.9 §1 (inbox row is
            the source of truth, push is one delivery of it) stated on the wire instead
            of contradicted by it, and it keeps student notification titles/bodies off
            Google/Mozilla/Apple push infrastructure entirely.
            **The alternative was measured:** `pywebpush` resolves cleanly here
            (`uv pip install --dry-run`) but adds **11 packages including `aiohttp`** — a
            second HTTP stack beside the existing `httpx`. Hand-rolling RFC 8291
            (ECDH/HKDF/AES128GCM) was rejected for the stronger reason that **it could
            not be honestly verified on this machine**: content encryption is only
            provable against a published test vector or a live push service, and a
            self-generated vector proves the code agrees with itself. Payload-less push
            needs neither — the ES256 assertion is verified *by decoding it with the
            public key*. **Zero new dependencies** (`pyjwt[crypto]` in the `db` extra,
            `httpx` in `web`).
            Absent VAPID keys are a supported state (D5.9 §4): `available` False, every
            send `unavailable`, one log line per process. `get_push_transport` returns the
            **real** transport even unconfigured — substituting a double there would leave
            the path this build actually runs untested.
            **Three guards verified by inversion:** attaching a payload fails
            `test_the_push_body_is_empty`; folding 5xx into `expired` fails 5 tests
            (a 503 must not evict a healthy device); signing the full endpoint instead of
            its origin fails 3 — the subscription path is the nearest thing a subscription
            has to a secret and must stay out of the assertion.
            `get_notification_service` composes the **existing**
            `get_notification_prefs_service` singleton (the brief's "check whether it
            already exists" warning was right, it did) so the delivery gate and the
            endpoint that edits it cannot disagree (D5.9 §2).
            **Carry to the Phase-5 limitations:** with no payload, a service worker must
            fetch before it can render, so a push arriving offline (or whose fetch fails)
            shows a generic "You have a new notification" — browsers require *some*
            notification per push. This is P5.9's service-worker brief.
      - [x] **chunk C1** (`dbc5d9f`) — the routes and the fail-open helper.
            `lemely/web/routers/notifications.py` (`GET ""`, `GET /counts`,
            `POST /{id}/read`, `POST /read-all`, `GET /push/config`,
            `POST /push/subscribe`, `POST /push/unsubscribe`),
            `schemas_notifications.py`, `lemely/web/notify.py` (`notify_safely`), app
            wiring, 49 tests (31 route + 18 helper). ruff/format/mypy(207)/lint-imports
            clean; the four notification test files pass together (126 tests).
            **Not yet run: the full suite / `check.sh`.**
            **The router is deliberately role-agnostic**, unlike every Phase-5 router it
            mirrors: `at_risk_alert` is addressed to a teacher and a parent, so a
            `Role.student` gate would have built an inbox two of its three intended
            readers cannot open. Pinned by a test over four roles.
            **New trap, cost real debugging, do not re-spring:** `Settings` and
            `NotificationTransport` must be imported at **runtime**, not under
            `TYPE_CHECKING`. FastAPI resolves every `Annotated[...]` parameter through
            pydantic, and with `from __future__ import annotations` a type-checking-only
            name leaves an unresolvable ForwardRef — the route then raises
            `PydanticUserError` **on its first request**, not at import, which is a much
            later and more confusing place to find out. `ruff`'s TC001 wants the
            opposite and is overridden with a reasoned `noqa`.
            Also: `lemely.web.schemas_notifications` had to join the
            `disallow_any_explicit` override list in `pyproject.toml` — pydantic's mypy
            plugin injects `Any` into generated `__init__`s, and **every** schemas module
            is already on that list. A new `schemas_*.py` costs that edit too.
            Behaviour worth keeping: subscribing is accepted with **no VAPID keys**
            (a subscription is a durable fact about a browser; refusing it would force
            every user to re-subscribe the day keys arrive); `removed: false` for someone
            else's endpoint is a **success**, not a 404 that would reveal ownership; the
            wire payload is `dict[str, str]` and **coerced, not rejected**, on read,
            because an inbox that 500s over one odd row is worse than a stringified id.
      - [x] **chunk C2a** (`78d58a0`) — the `grade_ready` seam. `notify_safely` in
            `/student/correct` immediately after `award_xp_safely`, dedupe on the
            **upload** (D5.9 §6 / D5.3). Verified by inversion: an attempt key fails
            `test_re_correcting_the_same_paper_does_not_re_notify`, which also asserts
            two `Attempt` rows so it cannot pass by the pipeline declining to re-run.
            Body says "Paper 4 Variant 1", never "Paper 4/1" — a slash between two
            small integers reads as a mark out of a total on a lock screen.
            New `tests/test_web_notify_seams.py` (6 tests here, 18 by end of C2).
            **Trap found: a substring scan over a payload containing a UUID is a test
            that fails on the seed** — "67" appears in a random UUID about a third of
            the time, which is what made the first run intermittently red. Assert the
            payload structurally; scan only the human-readable strings.
      - [x] **chunk C2b** (`965a242`) — the `announcement` seam, plus
            `AnnouncementService.student_recipients`: `list_for_student`'s predicate
            read in the other direction, so the seam and the student read path share
            one definition of "the audience". The recon was right that no such method
            existed for the school arm.
            Two guards **verified by inversion**: swapping the school arm to
            `SchoolMembership` fails the seated-student test with an empty audience
            (D5.4's "reads as a data problem" shape); dropping the future-`publish_at`
            guard fails `test_a_scheduled_announcement_notifies_nobody_yet`.
            Naive `publish_at` (the router parses an offset-less ISO string) is
            normalised to UTC — this runs **outside** `notify_safely`, so an
            unnormalised value would TypeError and 500 an announcement already written.
            **A first cut was removed for being justified by a false comment**: the key
            was `f"{announcement_id}:{recipient}"` on the reasoning that otherwise the
            first student notified suppresses the rest. Inversion disproved it —
            migration 0018's unique index is already `(user_id, type, dedupe_key)`, so
            the recipient half of D5.9 §6's pair comes from the index. Key is now the
            announcement id alone. **Generalisable: before writing the reason a guard
            exists, check whether something else already provides it.**
      - [x] **chunk C2c** (`c1792fd`) — the `at_risk_alert` seam and **D5.11**
            (recorded before the code, per MISSION §4). Seam is the post-correction
            point; dedupe on `(student, reason, Cairo civil date)` via
            `civil_date_in_zone` — at-risk is a *state*, so an upload key would send a
            teacher of thirty students one alert per upload. Two inversions, each
            landing on exactly one test: `flag.summary` as the body (it renders
            percentages and predicted grades) fails the no-evidence assertion; no
            dedupe key fails the second-paper-same-day test. D5.9 §3 pinned from both
            sides — a student turning `at_risk_alert` off does **not** silence their
            teacher or parent, and the parent's own row gates the parent's alert.
            **The recon was wrong about recipients (seventh time this phase the code
            beat a note): `ClassService.student_classes` does NOT reach the teacher
            id** — `StudentClassRow` is class_id/name/subject_code/school_name. Two
            narrow readers added instead (`teachers_for_student`, `display_name_for`)
            rather than widening a row the parent portal renders.
            **Rule 3 (≥14 days inactive) cannot fire at this seam** — a student who
            just uploaded is by definition active — so the reason most likely to
            matter for a *disengaging* student is the one this build cannot deliver.
            Joins D5.9 §5's no-scheduler limitation; **carry to the Phase-5
            limitations**.
            **Process trap that cost real work: `git checkout <file>` to revert an
            inversion also discarded ~80 lines of uncommitted real work in the same
            file.** Copy the file to /tmp before inverting, restore with `cp`, and
            invert one thing at a time — two simultaneous inversions produced a
            NameError that failed four tests and proved nothing about either.
      - [x] done — `./scripts/check.sh`, the first full run since chunk A: **13/13 PASS,
            0 skipped, exit 0, 2767 tests, 90.78% coverage**, `alembic check` clean.
            The C2 recon below is kept for reference; all of it is now spent.
            **Recon done 2026-08-10, use it rather than re-deriving:**
            - **`grade_ready`** — easiest, do it first. The seam is
              `lemely/web/routers/student.py:735`, immediately after the existing
              `award_xp_safely(..., seam="paper_corrected")` call. Recipient is
              `auth.user_id`; **dedupe on `str(owned.id)` — the upload, never the
              attempt** (D5.9 §6 / D5.3: `persist_correction` mints a fresh `Attempt`
              every run, so an attempt key re-fires on every re-correction of one PDF).
              Payload carries the upload id; **never a mark** (D5.9 §2).
            - **`announcement`** — the seam is `create_announcement` in
              `lemely/web/routers/announcements.py:100`, after `service.create` returns
              its rows. **Recipient resolution does not exist yet and is the real work
              here.** For a class row, `ClassService.roster(caller_id, caller_role,
              class_id)` works directly and the author's ownership is already proven by
              the create that just succeeded. **For a `school_wide` row there is no
              method at all** — the audience is every student holding a non-revoked
              `Seat` in that school (D5.4: students reach a school through `Seat`, never
              `SchoolMembership`), and `seat_repo.py` exposes only
              create/available/list_admin_schools/seat_usage/invite/revoke. Add one
              narrow reader (to `AnnouncementService`, beside `list_for_student`, whose
              audience logic is the same predicate in the other direction) rather than a
              second independently-derived query. Dedupe on
              `f"{announcement_id}:{user_id}"` (D5.9 §6).
            - **`at_risk_alert`** — the hardest, and **scope it honestly**. At-risk is
              computed **on read** today (`assess_at_risk` called from
              `routers/classes.py:203/306`), so there is no existing event to hang this
              on. The defensible seam is the same post-correction point as `grade_ready`:
              a new paper is exactly what can change rule 1 (declining trend) and rule 2
              (below target). **Rule 3 (≥14 days inactive) is time-triggered and cannot
              fire here** — it joins `streak_warning`/`study_plan_reminder` in D5.9 §5's
              no-scheduler limitation, and must be stated as such, not quietly omitted.
              Recipients: the student's teachers via `ClassService.student_classes(
              student_id)` (it joins `SchoolClass`, so the teacher id is reachable), and
              the parents via `ParentLinkService.list_parents(student_id)`.
              **The parent's own `notification_preferences.at_risk_alert` is what gates
              the parent's row (D5.9 §3)** — `notify_safely` already does this correctly
              because the gate reads the *recipient's* prefs, but a test must pin it, or
              a student could silence alerts about themselves.
            **If C2 turns out larger than one session, split it: C2a `grade_ready`
            (small, self-contained), C2b `announcement`, C2c `at_risk_alert`.** Committing
            `grade_ready` alone is a real increment; do not hold it hostage to the other
            two.
- [x] done — **P5.7** 3-device limit enforced in the UI (G-10) + device management (G-11).
      **Full `./scripts/check.sh` on the committed tree: all 13 gates PASS, 0 skipped,
      exit 0; 2789 tests; coverage 90.83%** (develop 90.18%, P5.6 90.78% — no drop);
      `alembic check` clean. **MISSION §6.8 satisfied for the new screen, measured not
      assumed:** `/settings/devices` audited as G-11 — **axe 0 violations at every
      severity** (critical/serious/moderate/minor all 0), **Lighthouse accessibility 100**
      (performance 87, best-practices 100), screenshots at all three breakpoints
      (380/768/1440), and the responsive summary carries **zero** horizontal-scroll
      violations. 8/12 Phase-5 tasks done.
      **Recon done 2026-08-10 by reading the code** (`lemely/db/device_repo.py`,
      `lemely/auth/service.py:123-140`, `lemely/web/routers/auth.py`): the **policy already
      exists and is correct** — D1.11's `DeviceRegistry.register_login` locks the user row
      `FOR UPDATE`, registers, and evicts the oldest beyond `MAX_DEVICES = 3` atomically;
      `deps.get_auth_context` checks liveness per request. **`MAX_DEVICES` needs no change and
      no migration is needed.** What is genuinely missing is exactly two things: **no route
      exposes a user's devices at all** (G-11's list + individual sign-out), and **eviction is
      silent** — `DeviceRegistration.evicted_session_ids` exists but `_register_device` drops it,
      so a client cannot know a device was signed out. The SPA already mints and sends
      `deviceId` (`web/src/lib/auth/storage.ts`), so the slot-reuse path is wired end to end.
      **D5.12 recorded before any code.** Load-bearing: the device list is **never** shown to an
      unauthenticated caller (that would enumerate a stranger's browsers from an email alone), so
      G-10 is a **409 challenge on the login itself** — credentials proven first, no token minted,
      nothing evicted — confirmed by re-sending the login with `confirmDeviceEviction: true`;
      "would this evict?" is answered **inside** the existing `FOR UPDATE` transaction via
      `allow_eviction: bool = True` (a preflight query would be a TOCTOU between two tabs); a
      re-login on a known `client_device_id` is never a challenge; and **rough location is
      deliberately absent** — no geo-IP source and no stored IP exist, and UI spec §1.4 forbids
      inventing the one field the user would decide on. Carry that to the Phase-5 limitations.
      - [x] **chunk A** (`5660cbf`) — `allow_eviction` + `DeviceLimitReachedError` in
            `device_repo.py`, threaded through `AuthService.login`
            (`confirm_device_eviction`), the **409** on `POST /api/auth/login`, and
            `GET`/`DELETE /api/me/devices` reusing the existing idempotent `revoke`.
            New `lemely/web/schemas_devices.py` + `lemely/web/devices.py` (one projector,
            shared by the challenge and the list, so the two surfaces cannot describe the
            same device differently). `AuthContext` grew `session_id` — it was already on
            the claims and already checked for liveness, but never carried, so nothing
            could mark "this device is the one you are using". 22 new tests (4 registry,
            18 route). ruff/format/mypy(209)/lint-imports clean; the seven related test
            files pass together (156 tests). **Not yet run: the full suite / `check.sh`.**
            **No migration and no `EXPECTED_TABLES` edit** — the `devices` table is
            Phase-1's and unchanged. `schemas_devices` **did** need the
            `disallow_any_explicit` override in `pyproject.toml` (P5.6 C1's trap, second
            sighting: every `schemas_*.py` costs that edit).
            **Two guards verified by inversion**, one file at a time with a `/tmp` copy
            (P5.6 C2c's process trap, not re-sprung): dropping the `allow_eviction` check
            fails the two registry tests; hardcoding the login's confirm flag fails three
            route tests. **The third inversion is the one worth keeping** — it exposed a
            test that passed for the wrong reason: `test_the_challenge_carries_no_location_
            field` scanned the response body for "location", and a 200 body trivially
            contains none either, so it would have stayed green with the challenge gone.
            It now asserts the 409 first. *A negative assertion needs a positive one
            beside it, or it proves only that the response was short.*
            **Scope call recorded in the code, not just here:** the OTP path keeps
            evicting silently, because the code is single-use and a challenge the caller
            re-sent confirmed would fail on a spent code and cost the parent a second SMS.
            Parents on a fourth device get D1.11's old behaviour — Phase-5 limitation.
      - [x] **chunk B** (`b4bb942`) — G-10 renders in place of the login form on the 409
            (`DeviceLimitNotice.tsx`), G-11 ships at **`/settings/devices`** guarded for all
            five roles (`portals/settings/DeviceSettings.tsx`), plus `lib/deviceTypes.ts`,
            `lib/devices.ts`, `lib/hooks/useDeviceApi.ts`, the `confirmDeviceEviction` flag
            through `AuthContext`/`authTypes`, the `App.tsx` route, and a **G-11 entry in
            `web/scripts/audit.mjs`'s registry**. 12 new vitest cases (336 total pass);
            typecheck, oxlint, build, `impeccable detect` clean.
            **Deliberately not stubbed:** G-11's profile/password/relationships/subscription
            rows have no P5.7 backend, and a settings row that does nothing is worse than an
            absent one. Stated in the screen's header comment, not just here.
            **Two things left for P5.11, recorded so they are not mistaken for covered:**
            (1) **G-10 has no audit-registry entry** — it needs an account already holding
            three live devices, which is a *seed precondition*, not a navigation; (2) **no
            nav entry anywhere reaches `/settings/devices`** — the teacher sidebar needs an
            icon-map addition and the parent portal has no sidebar at all, so wiring three
            portals' nav belongs with P5.9's screens rather than half-done here.
            **Trap that cost real work — `npx prettier --write` is NOT this repo's
            formatter.** `web/` has no prettier config and prettier is not a dependency, so
            a bare run reformatted 8 files with **semicolons**, against the house
            semicolon-free style, silently and across files I had only read. Reverted with
            `git checkout` on the three tracked files (re-applying the edits by hand) and
            `--no-semi` on the five new ones. The web gates are **typecheck + oxlint +
            build + vitest + impeccable detect** — none of them formats. Do not reach for a
            formatter that the gate chain does not run.
- [x] done — **P5.8** Screens S-28, S-29, S-30, S-31. **CLOSED 2026-08-10 (session 60): the
      gate run finished ALL 13 GATES PASS, 0 skipped, EXIT=0.** Nothing was re-implemented —
      every chunk was committed by earlier sessions and the only outstanding work was this run.
      **Measured off the run itself, never re-run** (the method note below): **2927 tests**
      (`--collect-only`), **coverage 90.91%** (develop 90.18%, P5.6 90.78% — no drop, a rise);
      **66 axe route-states with ZERO violations at any severity**, **0 console errors**,
      **0 horizontal-scroll violations**, **Lighthouse a11y floor 96** (`teacher-review`; the
      four new screens sit at 100, e.g. `student-standings`). All four Phase-5 screens appear
      in the audit registry: `student-announcements`, `student-standings`, `student-friends`,
      `student-profile`, plus `settings-devices`.
      **The run took 31 minutes and spanned TEN agent sessions (51→60).** Session 51 launched
      it with `setsid`; sessions 52–59 each attached, confirmed health and did recon instead of
      relaunching. Five pre-`setsid` runs never reached gate 5. **That is the whole return on
      `setsid` and on the "attach, never relaunch" rule — do not lose it.**
      **One honest finding this run produced, and it is now a Phase-5 instance of D4.25, not
      merely a carried one.** `ui-thresholds` PASSED with **seven routes below Lighthouse
      performance 80** — `teacher-quiz-detail` 66, **`student-standings` 69**,
      `teacher-class-analytics` 71, `student-placement-invite` 73, `teacher-class-roster` 75,
      **`student-announcements` 77**, `teacher-quizzes` 78. Two of those are **new P5.8 student
      routes**, and MISSION §11's "performance ≥ 80" is claimed to be gated for exactly the
      student routes. It is not gated: `scripts/check_ui_gates.py` has no performance check at
      all, so a green `ui-thresholds` says nothing about performance. Do **not** cite this run
      as a performance pass; it is a11y + axe + console + responsive only. Carried to the
      Phase-5 limitations for P5.12 §4.
      **Worth not re-deriving about the artefacts:** `reports/.scratch/axe/` holds 67 files —
      66 per-slug detail files plus **`_summary.json`, which is the one to read** (a per-slug
      file is not the run summary despite also containing a list). Both `console-errors.json`
      and `responsive-summary.json` are `[]` on a clean run, i.e. an empty list is the PASS
      shape, not a missing measurement.
      **CORRECTION to this brief, made 2026-08-11 by reading the code — the eighth time
      this phase a note lost to the codebase. "Every backend these screens need is already
      built" is TRUE for S-28/S-29/S-30 and FALSE for S-31.** `XpService` is wired into the
      web layer at **write seams only**: `grep total_xp\|xp_breakdown\|streak` over
      `lemely/web/` returns `deps.py`, `xp_awards.py` and the four award call sites, and
      **nothing reads**. The service methods themselves exist and are 100%-covered
      (`xp_repo.py:342 total_xp`, `:353 xp_breakdown(start, end)`, `:377 streak(now)`), so
      S-31 needs **one thin read router**, not an engine. That is chunk A and it goes first.
      **D5.1 §10 pre-authorised two S-31 decisions and they are P5.8's to make:** the
      XP→level mapping is explicitly deferred here ("P5.8 fixes it and records it, so long
      as it is a pure function of total XP"), and **achievements/milestones are out of
      scope** unless the screen is unbuildable without them, in which case they get their
      own decision record. UI spec §1.4 (never invent precision) governs S-31's "lifetime
      stats" line — ship only the stats a table actually holds.
      Chunking: **A** = the XP read route + D5.13; **B** = S-28; **C** = S-29 + S-30
      (they are one navigation pair and share the friends DTOs); **D** = S-31.
      - [x] **chunk A** (`6c74c97`) — `GET /api/student/xp` + `lemely/web/xp_levels.py`
            (the curve D5.1 §10 deferred here) + `XpService.profile`/`xp_by_day` +
            `schemas_xp.py` + app wiring + 91 tests. **D5.13 recorded before the code.**
            ruff/format/mypy(212)/lint-imports clean; 221 related tests pass.
            **Not yet run: the full suite / `check.sh`.**
            `_week_bounds` moved from `leaderboard_repo` to **`xp_repo.week_bounds`** so
            S-29 and S-31 cannot report two different weeks for one fact (D5.13 §2);
            `profile()` resolves `today` **once** for all four reads, so a request crossing
            midnight in Cairo cannot return a week and a calendar that disagree.
            `schemas_xp` needed the `disallow_any_explicit` override in `pyproject.toml`
            (**third sighting — every `schemas_*.py` costs that edit**) and the
            `# noqa: TC001` runtime import (P5.6 C1's ForwardRef trap, second sighting).
            **The inversion that FAILED is the thing to carry forward.** D5.13 §1 justified
            the integer curve by claiming `floor(sqrt(total / 100))` is wrong at the level
            boundaries. Inverting the implementation left **all 62 level tests green** — at
            a boundary `100·N²` both the division and the square root are exact in IEEE 754
            for any total this product can reach. The integer form still ships (its
            correctness does not *depend* on that floating-point argument holding forever),
            but **D5.13 §1 was corrected in place rather than left standing on a failure
            mode nobody had reproduced.** Third instance of this family — P5.6 C2b's guard
            justified by a false comment, D5.7's inherited "proven by inversion" claim, now
            this. **The rule: invert first, then write why. Writing the reason first is how
            a decision record acquires a confident sentence that is not true.**
            The absent-not-zero calendar rule was inverted too and is real (filling the
            window with zeros fails 6 tests across both layers).
            **Scope call, recorded in the DTO docstrings and not just here:** S-31's
            "papers marked / questions answered / hours studied" ships **absent**. The
            obvious source is a count of `xp_events` rows and it is wrong by construction —
            D5.1 §3's caps mean a capped award writes no row, §8's dedupe means a
            re-corrected paper writes one row for two markings. Carry to the Phase-5
            limitations. Achievements out of scope on D5.1 §10's own terms.
      - [x] **chunk B** (`64df07e`) — **S-28 is built.** `screens/Announcements.tsx`,
            `lib/announcementTypes.ts`, `lib/hooks/useAnnouncementApi.ts`, route
            `/student/announcements`, sidebar entry + breadcrumb in `data.ts`, and an
            **S-28 entry in `web/scripts/audit.mjs`**. 13 new vitest cases (349 total,
            from 336). typecheck / oxlint (0 errors) / build / vitest / `impeccable
            detect` all clean.
            D5.8's three empty causes reach the screen as three different states, per the
            brief. The calendar ships in its `no_timetable` state and **that is what the
            audit entry probes** — its `ready` waits on the announcements heading, never
            the countdown, because a probe waiting on a hero that legitimately does not
            render would hang and be misread as a route failure.
            **`StateViewAction` is `{label, onClick}` and has NO `to` field** — a nav
            action needs `useNavigate`. Caught by `npm run build`, not by
            `npx tsc --noEmit -p tsconfig.json`, which passed on the same tree: **the
            build runs `tsc -b` over a different project set, so it is the stricter gate.
            Do not treat a bare `tsc --noEmit` as having typechecked the web app.**
            `cd web` persisting into the next Bash call bit again (the environment fact
            below is real) — absolute-path everything after an `npx` run.
      - [x] **chunk C** (`d5.14` + two commits) — **S-29 and S-30 are built.**
            `screens/Standings.tsx` rewritten from its P2.7 placeholder,
            `screens/Friends.tsx`, `lib/leaderboardTypes.ts`, `lib/friendTypes.ts`,
            `lib/hooks/useLeaderboardApi.ts`, `lib/hooks/useFriendApi.ts`, route
            `/student/friends`, sidebar + breadcrumb, and **S-29 + S-30 entries in
            `web/scripts/audit.mjs`** (`/student/board` had never been in that registry,
            so this is its first coverage, not a re-audit). 17 new vitest cases
            (**366 total, from 349**); build / oxlint 0 errors / vitest / `impeccable
            detect` clean. **Not yet run: the full suite / `check.sh`.**
            **D5.14 recorded before the code**, and it corrects the brief twice.
            **(1) `scope=class` was unreachable, not merely awkward** — it needs a
            `class_id` and no student-facing route listed a student's classes (the only
            readers of `ClassService.student_classes` were the parent portal's
            P-01/P-02). So chunk C absorbed a small backend leg: **`GET
            /api/student/classes`** over that same method, never a second enrolment
            query. **(2) The opt-out endpoint is `PATCH /api/me/student-profile`, not
            the brief's `/me/profile`**, and the frontend's `meTypes.ts` mirror was
            missing `leaderboardOptOut` entirely — added to both `StudentProfile` and
            `StudentProfileUpdate`, the latter as `boolean | undefined` (not
            `| null`, which is a 422 on a NOT NULL column). Ninth and tenth instances
            this phase of the code beating a note.
            **The per-row streak indicator was built rather than dropped.** §S-29 fixes
            every row as "rank, avatar, display name, XP, streak indicator" and
            `LeaderboardRowDTO` had none. Dropping it was cheaper and lost to a stronger
            argument than spec-completeness: `FriendDTO.streak` already shows it, so the
            leaderboard's own `friends` scope would render the same people, one screen
            over, with the number missing. `LeaderboardService.streaks_for` mirrors
            `display_names_for` (one batched read, pinned by a call-counting test —
            a per-row version returns identical data and only the count catches it).
            **`streak` is `int | None` and `None` is not `0`**: a broken streak is a real
            zero, a missing `streaks` row is no fact at all. Verified by inversion —
            `.get(id, 0)` fails exactly `test_a_student_with_no_streak_row_reports_null_
            not_zero` while its paired real-zero test stays green.
            **The avatar §S-29 names has no storage anywhere**, so it is a monogram off
            the display name — a rendering of data we hold, never a generated identicon
            that would look like identity the account does not have. Uses `\p{L}`, not
            `[A-Za-z]`, so an Arabic display name does not degrade to the fallback glyph
            in this product's launch market. Carry "no avatar storage" to the Phase-5
            limitations.
            **A real pre-existing defect found and fixed: `web/tsconfig.test.json` had no
            `jsx` option**, so any test importing a `.tsx` fails TS6142 — which chunk B's
            `announcements.test.ts` does. It did not surface then because **`tsc -b` is
            incremental and a stale `node_modules/.tmp` tsbuildinfo reports success**.
            Confirmed by stashing this work and rebuilding the committed tree clean.
            **`rm -rf node_modules/.tmp` before believing a green `tsc -b`** — this is the
            second sighting of chunk B's "the build is the stricter gate" lesson, and the
            sharper form of it.
            83 related backend tests pass; ruff / format / mypy (214 files) /
            lint-imports clean. `schemas_student_classes` joined the
            `disallow_any_explicit` list (**fourth sighting** — every `schemas_*.py`
            costs that edit).
      - [x] **chunk D** — **S-31 is built.** `screens/Profile.tsx`, `lib/xpTypes.ts`,
            `lib/hooks/useXpApi.ts`, route `/student/profile`, sidebar + breadcrumb, and
            an **S-31 entry in `web/scripts/audit.mjs`**. 15 new vitest cases
            (**381 total, from 366**); build / oxlint 0 errors / `impeccable detect`
            clean.
            **No lifetime stats and no achievements shipped, per D5.13 §3** — the screen
            is deliberately thin and a future session must not "fill" it: a count of
            `xp_events` rows is wrong by construction (caps write no row, dedupe writes
            one row for two markings) and "hours studied" has no source in this schema.
            The audit entry says so too, so a probe for those states is not added later
            as if restoring something missing.
            **The level curve is not re-derived client-side** (pinned by a test reading
            50% off a band, not a formula), and **the calendar collapses absent into zero
            deliberately** — that is the correct direction: the backend omits empty days
            so "no XP" and "outside the window" stay distinct, and inside a known window
            an omitted day means exactly zero. Pinned by a test asserting an absent day
            and an explicit zero day produce identical cells.
            **Incidentally closes half of a P5.7 gap:** `/settings/devices` had no nav
            entry anywhere; the **student** portal now reaches it from S-31. Teacher and
            parent still do not — that remains P5.11's.
      - [x] **done — UI gate for P5.8: ALL 13 GATES PASS, 0 skipped, EXIT=0** (finished
            2026-08-10 ~11:59, 31 minutes after session 51 launched it; closed by session 60,
            which was attached via a Monitor when it exited). Historical detail below kept
            because the five-session detour that preceded it is the source of the `setsid`
            rule and the orphaned-pytest trap in the environment facts.
            (sessions **47, 48 and 49 each started this run and
            each died in the same place** — `/tmp/check_p58*.log` are four files of exactly
            84 bytes, all stopping after the four backend gates, i.e. mid-`pytest`. The
            forty-eighth also had to kill an **orphaned pytest** from the forty-seventh —
            see the environment facts below. The **fiftieth** session diagnosed the shared
            cause as the 600 s foreground cap and restarted it as a harness-tracked
            background task — **and that run died in the same place too**, producing a
            fifth 84-byte log. **The fifty-first session corrected the diagnosis: the
            600 s cap is NOT what is killing these runs.** The five logs are stamped
            11:15 / 11:20 / 11:23 / 11:25 / 11:27 — **2 to 5 minutes apart**, so each
            session died only ~2–4 minutes after launching the run, far short of any
            600 s cap, and session 50's *background* run died identically, which a
            foreground-only cap cannot explain. What is actually shared is that all five
            died **during `pytest`** (gate 5, `check.sh:65`) on a box already 3.7 GB into
            swap with 7.8 GB RAM — resource pressure, not a tool timeout. **The fix that
            makes this survivable is `setsid`**: session 51 launched the run in its own
            detached session/process group, so a dying agent session no longer takes the
            gate run down with it. See the corrected environment fact below.
            **CONFIRMED by the fifty-second session (this one): `setsid` is the fix, and
            the fifty-first session's run was still alive when session 52 resumed.**
            Session 51 launched it at 11:30; session 52 opened at 11:33 and found
            `check.sh` PID 927164 and its `pytest` child 927224 both **still running** at
            3 minutes elapsed — past the 2–4 minute mark where all five previous runs
            died. Session 52 did **not** start a sixth run; it attached to the surviving
            one by polling `kill -0`.
            **The "84-byte log" is not a symptom of anything.** It is what *every*
            healthy run looks like while `pytest` is in flight: `check.sh` suppresses a
            passing gate's output, so between the four backend gates finishing and pytest
            returning, the log is exactly those four PASS lines and nothing else. The
            fifty-second session's still-running log was byte-identical to the five
            "dead" ones. **A log that has stopped growing is only evidence of death if
            the process is also gone — check `pgrep`/`kill -0` before reading a byte
            count as a failure signal.** Three sessions' diagnoses were built on that
            byte count alone.)
            **Fifty-third session (this one) re-confirmed it at 8 minutes elapsed.**
            Session 51's run — `check.sh` PID **927164**, `pytest` child **927224**,
            log `/tmp/check_p58_s51.log` — was still alive at 11:38, having been
            launched 11:30. That is more than double the 2–4 minute mark that killed
            every pre-`setsid` run. Session 53 did **not** start a seventh run either;
            it attached by polling `kill -0 927164`. **The standing instruction for any
            session that resumes here: `pgrep -af check.sh` FIRST. A live PID means
            attach and wait (~25 min total: pytest ~10, audit leg ~11), never relaunch.**
            **Fifty-fourth session (this one) attached at 10:22 elapsed** — same run,
            same PID 927164, `pytest` child 927224 still owned by it (PPID 927164, so
            no orphan). Instead of hand-polling, it armed a **Monitor** that streams new
            log lines and fires once when `kill -0 927164` fails, so the wait costs no
            turns and the run's own output is the completion signal. Seventh run still
            not started. `setsid` has now carried this run past **10 minutes**, ~4x the
            mark that killed every pre-`setsid` attempt.
            **Fifty-fifth session (this one) attached at 14:13 elapsed** — same run, same
            PID 927164, `pytest` child 927224 still its own (PPID 927164, no orphan) and
            **actively working**: 7m30s of CPU at 52.7%, 696 MB RSS. That is the check
            worth copying — a live PID says "not dead", but accumulating CPU time says
            "not hung", and the four sessions that misread this run had neither number.
            Eighth run still not started; the Monitor was re-armed on the same PID.
            Working tree was clean on entry, so no wip commit was needed.
            **Fifty-sixth session (this one): the run has cleared `pytest` and TEN of the
            thirteen gates.** At 11:48, 18 minutes after session 51 launched it, PID 927164
            was still alive and `/tmp/check_p58_s51.log` had grown from 84 to **254 bytes**:
            `ruff-check`, `ruff-format`, `mypy`, `import-linter`, **`pytest`**,
            `web-typecheck`, `web-lint`, `web-build`, `web-test`, `impeccable-detect` — all
            **PASS**, with the header `== Live-stack UI gates ==` printed and
            `npm run test:e2e` (child 966482, its own `playwright test` below it) freshly
            started. **`pytest` is the gate that killed all five pre-`setsid` attempts, and
            it has now passed.** Only `playwright-e2e`, `puppeteer-audit` and `ui-thresholds`
            remain — the ~11-minute audit leg. No ninth run was started; the session attached
            and re-armed the Monitor on 927164. Working tree clean on entry.
            **The generalisable form of the five-session detour, now that the run has proved
            it: `setsid` bought ~18 minutes where the ceiling was 2–4.** The four sessions
            that read an 84-byte log as a crash were reading the *normal* mid-`pytest`
            appearance of a healthy run; the log going 84 → 254 in one step is what a
            passing `pytest` looks like from outside, because `check.sh` writes a gate's
            PASS line only when the gate *returns*.
            **Fifty-seventh session (this one): `playwright-e2e` PASSED — 11 of 13 gates
            green.** At 11:52, **21m52s** after session 51 launched it, PID 927164 was
            still alive and the log had grown 254 → **276 bytes** with `PASS
            playwright-e2e` as the new line. The run is now inside `puppeteer-audit`:
            child `npm run audit` (973395) → `sh -c node scripts/audit.mjs` (973406) →
            `node` (973407, 8.3% CPU, 266 MB) with a real Chrome tree below it
            (974729 + workers, 19 s old). Health was checked the fifty-fifth session's
            way — not just `kill -0`, but accumulating CPU and a live Chrome — so
            "alive" is backed by "working". No tenth run started; the Monitor was
            re-armed on 927164. Working tree clean on entry, so no wip commit.
            **`playwright-e2e` is the live-stack leg (needs Supabase up) and it cleared
            with no session touching it.** That is the whole return on `setsid`: five
            pre-`setsid` runs never reached gate 5, and this one has now carried through
            gate 11 across *seven* agent sessions. Only `puppeteer-audit` (the ~11-minute
            leg, in flight) and `ui-thresholds` remain.
            — MISSION §6.8 in full, run **once** after C and D land
            rather than per chunk: axe (0 serious/critical), Lighthouse a11y ≥ 95,
            screenshots at 380/768/1440 for every new screen × state, visual compare
            (read `removed` = 0, not `changed`).
      S-28 (announcements + exam calendar):
      `GET /api/student/announcements`, `/unread-count`, `POST /{id}/read` (P5.5 chunk B)
      and `GET /api/student/exam-calendar` (P5.5 chunk C) — **the calendar table ships
      empty and its three distinct empty causes (`no_enrolment`/`no_timetable`/
      `no_session`) must reach the screen as three different states, not one blank**
      (D5.8). Leaderboard: `GET /api/student/leaderboard` with all four scopes including
      `friends` (P5.3/P5.4); `web/src/portals/student/screens/Standings.tsx` is the
      existing honest-empty screen this fills — read its header comment first, it records
      what was deliberately removed rather than mocked. Friends: `GET/POST/DELETE
      /api/student/friends` (P5.4) — S-30's "add by username" is **unbuildable as
      written**, `users` has no username; the built mechanism is `friend_code` (D5.6).
      Follow P5.7's frontend conventions: no `fallback` in `request()`, one hook file per
      area under `lib/hooks/`, and **do not run `npx prettier`** (see the environment fact
      below). MISSION §6.8 applies in full again.
- [x] done — **P5.9** Screens G-10, G-11, G-12, G-13.
      **CLOSED 2026-08-10 (session 72): the second full gate run finished — ALL 13 GATES PASS,
      0 skipped, EXIT=0** (`setsid` PID 1232550, log `/tmp/p59b-gate.log`, ~31 min, carried
      across four agent sessions: 68 launched, 69–71 attached, 72 caught the exit). It verified
      the tree carrying all three of session 67's changes at once — the G-13 registry entry,
      the `page-has-heading-one` fix, and P5.10's new spec. Coverage read off that run's own
      `.coverage`: **90.91%** (develop 90.18%, P5.8 90.91% — no drop; identical because P5.9/
      P5.10 touched zero backend files, which is the same correct-not-stale equality the P5.9
      UI-gate line already explains). Commit `5df4807`; working tree clean at launch and at exit.
      **D5.15 recorded 2026-08-10 (session 60) BEFORE any code**, per the ordering MISSION §4
      mandates for this phase — it answers item 3 below and adds one finding item 3 did not
      have. Two loads worth carrying up here:
      **(a) A service worker cannot authenticate, so D5.10 is not implementable as written.**
      The session JWT is persisted to **`localStorage`** (`lib/auth/storage.ts:33/44`, consumed
      at `lib/api.ts:45`) and `localStorage` does not exist in a `ServiceWorkerGlobalScope`. A
      SW fetch would go out unauthenticated and take a 401. **Mirroring the token into
      IndexedDB was rejected** — it creates a second, longer-lived copy of a bearer credential
      that every logout, refresh and device eviction must then also clear, quietly undoing the
      session boundaries P5.7/D5.12 was built to make real. The SW instead **asks an open
      client** (`clients.matchAll` + `postMessage` with a timeout) and the page does the
      authenticated fetch, so the credential never leaves the page context. **Consequence to
      carry to the Phase-5 limitations: with no tab open every push renders the generic "You
      have a new notification"; the window where push carries real content is a backgrounded
      but open tab.**
      **(b) `injectManifest`, not `workbox.importScripts`.** A `public/` file is copied
      verbatim — not typechecked by `tsc -b`, not linted, not reachable by vitest — and putting
      this phase's only new client logic where no gate can see it is what "proven by a test"
      forbids. **Zero new downloads**: all four workbox runtime packages are already installed
      at 7.4.1 (transitive from `vite-plugin-pwa` 1.3.0); they are promoted to explicit
      `devDependencies` because `src/sw.ts` imports them directly. **Reproduce the generateSW
      behaviour deliberately or it is lost** — `precacheAndRoute(self.__WB_MANIFEST)`,
      `navigateFallback` to `/index.html` **with the `/^\/api/` denylist preserved** (the
      original comment records that `/api/*` must never be cached because marks and grades are
      live), and `skipWaiting`/`clientsClaim` so `registerType: "autoUpdate"` still means what
      it meant. Test seam: a **pure function** (content vs. fallback) that vitest drives, with
      `src/sw.ts` a thin adapter — vitest is `environment: "node"` with no jsdom
      (`vitest.config.ts:25`) and there is no `ServiceWorkerGlobalScope` to mount anyway.
      - [x] **chunk A** (`e3c2076`) — the service worker. `web/src/sw.ts` (adapter),
            `web/src/lib/push/pushDecision.ts` (the pure decision logic),
            `web/tests/unit/pushDecision.test.ts` (21 tests), `tsconfig.sw.json`,
            `vite.config.ts` → `injectManifest`, the three workbox packages promoted to
            explicit devDependencies. **web-typecheck / web-lint / web-test / web-build all
            green** (408 tests over 13 files; lint shows only the pre-existing
            `only-export-components` warnings). **Not yet run: the full suite / `check.sh`.**
            **Verified on the BUILT worker, not on the source** — a strategy switch is exactly
            where "it compiles" and "it still does what it did" come apart: `dist/sw.js` has
            **28 precache entries**, the `\/api` navigation denylist, **both `push` and
            `notificationclick` listeners**, `skipWaiting`, and `dist/registerSW.js` is still
            auto-injected into `index.html`. **Trap: the minifier rewrites `addEventListener("push"`
            to backticks**, so a grep for the double-quoted form finds nothing and reads as a
            missing handler. Grep for `showNotification`/`clients.matchAll` or for the backtick
            form.
            **`sw.ts` is typechecked, confirmed by inversion** (appending a deliberate type
            error fails `tsc -b` with TS2322 at `src/sw.ts`) — worth doing because `tsconfig.sw.json`
            is a *new* project and a reference that silently checks nothing is the exact
            "passes for the wrong reason" shape P5.5 chunk C and P5.8 both paid for.
            **One design correction made while building, recorded here because the file comments
            alone would lose it:** the first cut of the test file asserted `.toThrow()` under the
            name "never throws", which is a contradiction that would have shipped a false
            guarantee. The resolution is not defensive code in the pure function — a reply crosses
            a `postMessage` boundary and is therefore **structured-cloned**, so no getter or class
            instance can reach it and hostile property access is not a reachable input. The
            always-show-something guarantee instead lives in `sw.ts` wrapped around the decision,
            which is where the browser requirement actually applies.
      - [x] **chunk B** (`b7368bb`) — **G-13 is built**, plus the page half of chunk A's
            handshake. `portals/student/screens/Notifications.tsx` (route
            `/student/notifications`), `lib/notificationTypes.ts`,
            `lib/hooks/useNotificationApi.ts`, `lib/push/pushClientBridge.ts`,
            `main.tsx` registration, `tests/unit/notifications.test.ts` (22 tests).
            **web-typecheck / web-lint / web-test / web-build all green** (430 tests over 14
            files). **Not yet run: the full suite / `check.sh`.**
            **The finding that changed the design, and it is a live-link defect avoided:
            `grade_ready` has NO resolvable destination and deliberately gets no link.** Its
            payload carries `uploadId`, the upload's **UUID** (`routers/student.py:891`), but
            the only per-paper screen is `/student/result/:paperId` whose `paperId` is a
            **history record index** — `student_result` does `int(paper_id)` and 404s on
            anything else (`routers/student.py:487`). An "Open" button there would have been a
            guaranteed dead link that looks like a feature. **There is no route mapping an
            upload id to its result**; if a later task wants one, that is a backend addition,
            not a frontend fix. Carry to the Phase-5 limitations.
            **The default push destination is `/`, not an inbox path**, because the API is
            role-agnostic on purpose — `at_risk_alert` is addressed to a **teacher and a
            parent**, neither of whom has an inbox screen in this build, so a hardcoded student
            path would 404 for exactly the audience the notification was written for.
            **`tsconfig.sw.json` now enforces D5.15 §2 at compile time, which was discovered by
            it failing.** Including the whole `src/lib/push` directory pulls
            `pushClientBridge.ts` → `lib/api` → `auth/storage`, and the build fails with
            **`TS2304: Cannot find name 'localStorage'`** under the WebWorker lib — the type
            system stating the exact constraint the whole design rests on. The include is
            narrowed to `src/sw.ts` + `src/lib/push/pushDecision.ts`, so any future attempt to
            reach page-only APIs from the worker fails `web-typecheck` instead of failing at
            runtime on a reader's device. **Do not widen that include back to the directory.**
            The bridge replies with the **newest unread** row, never simply the newest — a push
            described by a notification the reader has already opened is actively misleading,
            and that is what a naive `notifications[0]` yields the moment a read row sits on
            top. Registered in `main.tsx` at startup, not inside a screen: a push can arrive
            whenever a tab is open, and a listener mounted with one screen would answer only
            while that screen happened to be showing.
      - [x] **chunk C** (`7a8f93a`) — **G-12 is built.**
            `portals/settings/NotificationSettings.tsx` at `/settings/notifications`
            (top-level, all roles, like G-11), `lib/notificationPrefs.ts`,
            `lib/push/pushEnable.ts`, `lib/hooks/useNotificationPrefsApi.ts`, a route in
            `App.tsx`, a link from the G-13 inbox, `tests/unit/notificationPrefs.test.ts`
            (26 tests). **web-typecheck / web-lint / web-build / web-test all green**
            (456 tests over 15 files, up from 430/14). **Not yet run: the full suite /
            `check.sh`.**
            **The brief was wrong about the verb: it is `PUT`, not `PATCH`**
            (`routers/me.py:176`). Still a genuine partial update via `model_fields_set`,
            and the screen sends **one key per toggle flip** — not bandwidth: a
            whole-object body carries `atRiskAlert`, which is a 422 for any role but
            teacher/parent, and clobbers a change made on another device since load.
            **`atRiskAlert: null` is information, not absence** — "no such preference for
            your role". The toggle is filtered out rather than rendered unchecked, which
            would have offered a student a switch the router rejects.
            **Two guards verified by inversion.** `resolvePushState` checks **server
            availability before browser support** (both mean push cannot happen, but only
            the browser one *looks* actionable, and acting on it achieves nothing while
            the server has no keys) — swapping the two lines fails a test. And `granted`
            **without** a live subscription resolves to `prompt`, not `enabled`: the
            permission is the browser's memory of an old answer, the subscription is what
            the server can push to, and cleared site data / a new profile / a 410 the
            server acted on leaves the first without the second — dropping `subscribed`
            from the check fails a test.
            **The test-notification button is a device check, not a delivery test, and
            says so in its own copy.** No route in this backend sends a test push and on a
            keyless build none could; it goes through the **SW registration**, not
            `new Notification()`, which is unsupported on Android Chrome — exactly where a
            hand-rolled test button silently does nothing on the platform these students
            use.
            **Trap worth not re-paying: `urlBase64ToUint8Array` must return
            `Uint8Array<ArrayBuffer>`.** Since TS 5.7 the bare `Uint8Array` defaults its
            parameter to `ArrayBufferLike`, which admits a `SharedArrayBuffer` that
            `applicationServerKey` does not — the bare form fails `web-typecheck` at the
            `pushManager.subscribe` call, not at the helper.
            Five toggles only; the key list is asserted **exactly**, so UI spec §G-12's
            `weekly_summary` cannot be added without the backend growing the enum value
            first. Carried to the Phase-5 limitations.
      - [ ] ~~chunk C brief~~ (superseded by the entry above; kept for the route note)
            **`GET`/`PATCH /api/me/notification-preferences`** (`routers/me.py:86`) — *not*
            `/me/profile` or `/me/student-profile`, the two neighbours P5.8 chunk C tripped over.
            **Ship exactly FIVE toggles**; UI spec §G-12's `weekly_summary` has no backend value,
            no column and no sender, and a sixth switch that gates nothing violates UI spec §1.4.
            Quiet hours are real (`quiet_hours_start`/`_end`). **Three distinct states, not one
            grey button**: transport unavailable (this machine has no VAPID keys, so
            `GET /api/notifications/push/config` returns `available: false` **by design** —
            D5.9 §4), browser permission denied, and granted.
      - [x] **chunk D** (`666d6a7`) — the nav gaps closed, and **the brief's predicted fix
            was the wrong shape.** One entry per portal, not two, because the two settings
            screens now **link to each other** — without that the teacher sidebar and the
            parent header would each have needed a pair, and a hub for two screens is a
            screen that exists to hold two links.
            **The teacher entry needed no icon-map addition at all.** It sits in the sidebar
            *footer* beside "Open the student portal", not in `navItems`: the primary nav is
            that teacher's work — every entry is a `/teacher` route with a `NavLink` active
            state — and `/settings/*` is account-level, shared with every role, and would
            never render active from a list matched against the teacher subtree.
            The parent portal genuinely has no sidebar (P-01, deliberate), so the header was
            the only surface; the link takes the same icon-at-mobile + `aria-label`
            treatment as the Sign out button beside it, for the `button-name` reason
            recorded there.
            **G-12 IS in the audit registry** (`web/scripts/audit.mjs`), with two
            non-coverages written into the entry rather than left to be discovered: a
            student session sees **four** toggles, not five (`atRiskAlert` renders only for
            teacher/parent), and the push section renders **`unavailable`** — the honest
            state for every build this repo produces — so the enable and test-notification
            buttons are **not exercised by any gate**. Auditing them needs a mocked config,
            i.e. a screen this deployment never shows. Carried to the Phase-5 limitations.
            **Still open, deliberately: G-10 has no audit-registry entry.** It needs a seed
            account already holding three live devices — a `scripts/seed_e2e.py` change, and
            P5.11 owns the seed work.
            **web-typecheck / web-lint / web-build / web-test all green** (456 tests over 15
            files).
      - [ ] ~~chunk D brief~~ (superseded above) Teacher + parent still have
            **no nav entry to `/settings/devices`** (P5.8 wired only the student one from S-31;
            the teacher sidebar needs an icon-map addition, the parent portal has no sidebar).
            G-10's **audit-registry entry** needs a seed account already holding three live
            devices — that is a `scripts/seed_e2e.py` change and P5.11 owns the seed work, so
            either coordinate it there or leave it and report it honestly.
      - [x] **UI gate for P5.9 — FINISHED 2026-08-10, ALL 13 GATES PASS, 0 skipped, EXIT=0.**
            Session 61's `setsid` run (PID 1077823) took **~31 minutes** and was carried
            across seven agent sessions (61 launched, 62–66 attached, 67 caught the exit on
            an armed Monitor). Measured off that run and **never re-run**: **2927 tests**,
            **coverage 90.91%**, **67 axe route-states with zero violations at any severity**
            (P5.8: 66 — the +1 is G-12), **40 Lighthouse routes, a11y floor 96, 39 of 40 at
            100**, **0 console errors**, **0 horizontal-scroll violations**.
            **The pytest count and coverage are byte-identical to the P5.8 run, and that is
            correct, not a stale artifact** — P5.9 is a frontend-only task that touched zero
            backend files. Verified rather than assumed: `.coverage`'s mtime falls inside this
            run's pytest leg. Do not "fix" the equality.
            **`ui-thresholds` passed with NINE routes below Lighthouse performance 80, up
            from seven at P5.8, and one of the two new ones is P5.9's own `settings-notifications`
            at 73** (the other new entrant is `student-study-plan-week` at 76; the full set is
            teacher-quiz-detail 66, student-standings 70, teacher-class-analytics 72,
            settings-notifications 73, teacher-class-roster 73, teacher-schemes 73,
            student-study-plan-week 76, student-announcements 78, student-practice-generator 79).
            This is D4.25 restated by a second phase: `check_ui_gates.py` has **no performance
            check**, so a green `ui-thresholds` says nothing about performance. **Never cite
            this run as a performance pass.** Carried to P5.12 §4.
      - [x] **G-13 registry gap — FOUND BY SESSION 67 AFTER the gate went green; CLOSED by the
            second gate run (session 72, all 13 PASS on the tree carrying the fix).** The gate passed on a registry that **did not
            contain G-13 at all**: `Notifications.tsx` (chunk B's screen, route
            `/student/notifications`) shipped with no entry in `web/scripts/audit.mjs`, so the
            one new *student* screen in this task was never axe-audited, never
            Lighthouse-scored and never screenshotted. MISSION §6.8 requires exactly that for
            every new screen.
            **The failure mode is what matters: the registry is a hand-maintained list, so a
            missing entry is SILENT — the gate goes green *because* it does not know the
            screen exists.** That is the third instance of this shape in the build
            (`EXPECTED_TABLES` at P5.4, the `SeedContract` mirror at P4.11) and the first
            where the green result was actively misleading rather than merely incomplete.
            **Write the registry entry in the same chunk as the screen.**
            Entry added (screenId `G-13`, slug `student-notifications`, `practiceActiveSession`,
            probe `"Nothing yet"`). It audits the **empty** state, which is the state the
            screen genuinely ships in: the seed writes no Phase-5 rows and notifications only
            exist via a live fan-out, so **`NotificationRow` — the unread dot, `Mark as read`,
            `Open` — is not covered by axe.** A real gap, recorded not hidden; P5.11's seed
            work should add a `populated` state *alongside* this one, not replace it.
            **VERIFIED, and the entry immediately earned itself: the standalone
            `npm run audit` came back `EXIT=0` with G-13 driving cleanly (68 route-states,
            41 Lighthouse routes, `student-notifications` a11y **100**) — and carrying
            THE FIRST NON-ZERO AXE COUNT IN THIS CORPUS.** Every prior run in the build
            reported zero violations at *any* severity across 66–67 route-states; G-13
            reported **1 moderate `page-has-heading-one`**. That is exactly what the missing
            registry entry had been hiding, and it is a real screen-reader defect, not a
            harness artefact: the `<h1>` lived **inside the populated branch only**, so the
            empty state — the state this screen actually ships in, since the seed creates no
            notifications — had no page heading at all. The page stopped identifying itself
            precisely when it had the least other content to orient by.
            **Note it would NOT have failed the gate**: `check_ui_gates.py` fails on
            serious/critical only, so `ui-thresholds` would have gone green on a moderate.
            The build's own standard has been zero-at-any-severity, and that standard is
            enforced by *reading the summary*, not by the gate.
            Fixed by hoisting the heading into an `InboxHeading` component rendered in
            **all four** states (loading / error / empty / populated); the loading and error
            states had silently lacked it too. There is no unit-level pin available —
            `vitest.config.ts` is `environment: "node"` with no jsdom and no
            @testing-library, deliberately (D3.20) — so **the axe entry itself is the
            regression pin**, which is now real rather than absent.
            Same `page-has-heading-one` shape `MarkSchemes.tsx` and `Grading.tsx` already
            carry comments about. A full `./scripts/check.sh` on the fixed tree is still owed
            before P5.9 may be marked done.
      **Brief sharpened 2026-08-10 (session 56) by reading the code while the P5.8 gate run
      held the test lane — recon only, nothing edited. Four corrections, and the first is a
      scope halving.**
      1. **G-10 and G-11 are already BUILT — P5.7 shipped both.** `DeviceLimitNotice.tsx`
         (the 409 challenge) and `portals/settings/DeviceSettings.tsx` at `/settings/devices`,
         with a G-11 audit-registry entry and axe 0 / Lighthouse a11y 100 already measured.
         **P5.9's real scope is G-12 + G-13 only**, plus the two gaps P5.7 and P5.8 recorded
         as explicitly *not* covered: G-10 has **no audit-registry entry** (it needs a seed
         account already holding three live devices — a seed precondition, not a navigation,
         so it is a `scripts/seed_e2e.py` change) and **teacher + parent still have no nav
         entry to `/settings/devices`** (P5.8 chunk D wired the student one from S-31; the
         teacher sidebar needs an icon-map addition and the parent portal has no sidebar).
      2. **There is no notification frontend of any kind.** `grep -rln "notification"
         web/src` returns exactly three teacher files, none of them related
         (`ReviewItem.tsx`, teacher `Announcements.tsx`, `teacherTypes.ts`). No hook, no
         types file, no screen. Both screens are a clean build, like S-28 was.
      3. **The real architectural item, and it needs a decision record before code:
         D5.10's payload-less push has nowhere to land.** `web/vite.config.ts:12` runs
         `VitePWA` with `registerType: "autoUpdate"` and a `workbox: {...}` block — that is
         the **generateSW** strategy, which emits a service worker with **no `push` event
         handler at all**, and there is no service-worker source file anywhere in `web/src`
         (`web/dist/sw.js` and `registerSW.js` are build artefacts, not inputs). D5.10 chose
         an empty push body precisely so the SW must *fetch the inbox over the authenticated
         API before it can render* — so a custom `push` handler is not optional decoration
         here, it is the only thing that makes P5.6's transport visible. That means moving to
         `strategies: "injectManifest"` + a `src/sw.ts`, or `workbox.importScripts`. **Decide
         and record it before writing the screen**, per the ordering MISSION §4 mandates for
         this phase. P5.6 chunk B already wrote the brief for its offline behaviour: a push
         whose fetch fails must still show a generic "You have a new notification", because
         browsers require *some* notification per push.
      4. **G-12's spec names a toggle the backend does not have.** UI spec §G-12 (line 375)
         lists "results ready, new announcement, study session reminders, streak at risk,
         weekly summary, teacher/at-risk alerts". `NotificationType` has exactly **five**
         values and **`weekly_summary` is not one of them** — there is no sender, no column,
         and no row. Ship the five real toggles; do not add a sixth switch that gates
         nothing (UI spec §1.4). Quiet hours **are** real (`quiet_hours_start`/`_end` on
         `notification_preferences`) and the route is
         **`GET`/`PATCH /api/me/notification-preferences`** (`routers/me.py:86`) — note it is
         *not* `/me/profile` or `/me/student-profile`, the two neighbours P5.8 chunk C
         already tripped over.
      5. **G-12's "test-notification button" and permission state must both handle
         `available: false` honestly.** This machine has **no VAPID keys**, so
         `GET /api/student/notifications/push/config` reports the transport unavailable by
         design (D5.9 §4) — that is a first-class state for this screen, distinct from
         "the browser denied permission", which §G-12 explicitly asks be shown "clearly with
         a route to fix it rather than toggles that silently do nothing". Three states, not
         one grey button.
- [x] done — **P5.10** Motion pass + a real `prefers-reduced-motion` proof test (MISSION §4
      Phase-5 acceptance names this explicitly).
      **CLOSED 2026-08-10 (session 72) by the same second gate run — `playwright-e2e` PASS with
      `reduced-motion.spec.ts` in the suite.** No CSS was written, as items 1–3 predicted; the
      deliverable was the proof test and it was verified by inversion before the gate ran.
      **WRITTEN 2026-08-10 (session 67): `web/e2e/reduced-motion.spec.ts`, two tests, no CSS
      touched — exactly the one-chunk shape items 2/3 predicted.** Awaiting its first run
      (the standalone G-13 audit held the browser lane while it was written); typecheck and
      oxlint on the file are already clean.
      **Target: `/teacher/schemes`, because it is the one route carrying all THREE of the
      rule's declarations at once** — `.lm-screen` (`index.css:727`) gives a real `lm-in`
      animation, and its "Upload your own" `<Button>` carries `transition-colors`
      (`button.tsx:16`). Asserting only an animation would leave `transition-duration`, a
      third of the rule, unproven. The control test (motion allowed) asserts both durations
      are **>1ms** — without it the `reduce` test could pass vacuously on a page where
      nothing animated in the first place, which looks identical to a real pass.
      **The finding worth keeping: `test.use({ reducedMotion: "reduce" })` — which item 3 of
      this brief recommended — IS A TYPE ERROR on the pinned Playwright, and NOTHING WOULD
      HAVE CAUGHT IT.** `reducedMotion` is not a declared key of `PlaywrightTestOptions` in
      1.62.1 (`colorScheme` is; verified by reading the interface in
      `node_modules/playwright/types/test.d.ts:7145`), and `web/e2e/` is in **no** tsconfig
      `include` (D3.20), so the directory is never typechecked by any gate. Used
      `page.emulateMedia({ reducedMotion: "reduce" })` instead — same real CDP signal, fully
      typed. **This is D3.20 costing something concrete for the first time**: the carried
      limitation stopped being theoretical the moment a spec needed a type it could get
      wrong. Carry to P5.12 §4 with that framing, not as a generic "e2e isn't typechecked".
      **RUN AND INVERTED, both green — the only thing still owed is the full `check.sh`.**
      First run: **2 passed (25.8s), EXIT=0**. Inversion done properly rather than claimed
      (D5.7's lesson — *a claim about a test is not the test*): the `index.css:742` block was
      deleted and the suite re-run, giving **1 failed / 1 passed** with the `reduce` test
      reporting `Expected: < 1, Received: 320` — the real 0.32s token — while the control
      test still passed. `index.css` restored and verified byte-identical (`git diff` empty).
      That is the shape item 4 demanded: the test fails for the right reason, and it cannot
      pass on a page where nothing animates.
      **Brief sharpened 2026-08-10 (session 58) by measuring the code while the P5.8 gate run
      held the test lane — recon only, nothing edited. The scope is smaller than the task
      title implies, and it has moved from CSS to testing.**
      1. **The reduced-motion rule already exists and is already global.** `src/index.css:742`
         is `@media (prefers-reduced-motion: reduce)` over `*`, `*::before`, `*::after`,
         forcing `animation-duration: 0.001ms !important`, `animation-iteration-count: 1
         !important`, `transition-duration: 0.001ms !important`. Do **not** rebuild it and do
         not add per-component `motion-reduce:` variants on the assumption it is missing —
         that is the seventh Phase-5 chance for a note to be beaten by the code.
      2. **That blanket rule genuinely reaches ALL motion in this app, and that was measured,
         not assumed.** The whole surface is CSS-only: exactly **three** `@keyframes`
         (`lm-in` screen entry :702, `lm-pulse` ambient :712, `lm-spin` spinner :721), and
         **zero** of every escape hatch a blanket CSS rule cannot cover — no animation library
         in `package.json` (no framer/motion/gsap/spring), **no `requestAnimationFrame`
         anywhere in `src/`**, and **no `scroll-behavior: smooth` / `scrollIntoView` /
         `scrollTo`**. So there is no JS-driven or scroll motion to retrofit. If P5.8's four
         new screens added none either, the CSS half of this task is **already done** and the
         honest deliverable is the proof.
         **RE-VERIFIED 2026-08-10 (session 62) on the post-P5.9 tree, which is what item 2's
         conditional was waiting on: the claim holds and the CSS half IS already done.** Still
         exactly three `@keyframes`, all in `index.css`; still **zero** `requestAnimationFrame`,
         `scrollIntoView`, `scrollTo(`, `scroll-behavior` anywhere in `src/`; still no animation
         library in `package.json`. P5.9's four chunks added **one** motion token in total —
         `transition-colors` in `Notifications.tsx` — and a transition is exactly what the
         blanket `transition-duration: 0.001ms !important` already covers; `NotificationSettings.tsx`
         and `sw.ts` added none. `grep -rln "reduced-motion|reducedMotion|prefers-reduced"` over
         `src/`, `e2e/` and `tests/` **still returns only `index.css` and `processing-state.tsx`**,
         so item 3's gap is intact and untouched. **P5.10 is a one-chunk test task — write no CSS.**
      3. **The actual gap is the test, and it does not exist at all.** `grep -rln
         "reduced-motion|reducedMotion"` over `e2e/` and `src/` returns **only `index.css` and
         `processing-state.tsx`** — no test file, in any suite, has ever asserted this.
         MISSION §4 Phase-5 says "proven by a test", so a passing screenshot is not the
         deliverable. Playwright takes `reducedMotion: "reduce"` in a context/`use:` block
         (`playwright.config.ts:72` already has a `use:` block and one `chromium` project at
         :77–80), which is the cheap seam — a second project or a per-test `test.use()`.
      4. **Assert something observable, not the media query.** A test that only checks the
         `@media` block exists re-states the CSS. Assert the *computed* style of a
         genuinely-animating element (`processing-state.tsx` is the spinner and its header
         comment at :19 already documents that it relies on this global rule, so it is the
         honest target) is ~0 duration under `reduce` and non-zero without it. **Verify by
         inversion** — deleting the `index.css:742` block must fail the test — per the standing
         Phase-5 practice; a reduced-motion test that passes with the rule removed is the exact
         "passes for the wrong reason" shape P5.5 chunk C already paid for once.
      5. One subtlety worth not re-deriving: the rule neutralises duration but never sets
         `animation: none`, so `lm-pulse` (an *infinite* ambient pulse) becomes one 0.001ms
         cycle rather than stopping mid-frame. That is correct behaviour, not a bug to fix.
- [ ] doing — **P5.11** Acceptance + UI-gate pass: E2E for XP accrual, leaderboard ordering, push
      delivery (mock), announcement flow; axe/Lighthouse/screenshots/visual compare.
      **STARTED 2026-08-10 (session 72), the first session with a free test lane since 61.**
      Chunk plan derived from the sixteen measured points below — build in this order, because
      each chunk is a precondition of the next:
      **A. a11y/markup prep (`web/`)** — points 6+16 (`BoardRow` element prop + `<ol>` on the
      ranked container only) and 7(d) (S-31 value `aria-label`s in the C-2 `MarkDisplay`
      pattern). Both are what makes the assertions in chunk C locatable at all.
      **B. seed (`scripts/seed_e2e.py`)** — point 15's XP rows (today's Cairo date, purge first)
      and point 5's dedicated G-10 three-device account. Only G-10 pays point 3's three-edit
      contract tax (point 10 proved the XP rows do not).
      **C. the four E2E specs** — point 7 (XP accrual, inside `correct-paper.spec.ts`), 11
      (leaderboard ordering, click Class scope first), 13+14 (announcement flow, both roles),
      9 (the inbox rows, riding chunk C's own drivers).
      **D. audit registry** — point 12(b): delete the false four-route claim from **both**
      `audit.mjs:83-85` and `:2451`, add the three genuinely-unaudited routes, add G-10's entry
      (now possible, chunk B seeds it). Do not re-add `/student/board`.
      **E. the UI-gate pass** — point 12(a)/(c): `LEMELY_REPORT_DIR=reports/phase-5 npm run
      audit`, `compare-screens` with an **explicit** `--baseline reports/phase-4/screens`, then
      the full `./scripts/check.sh` under `setsid`.
      ---
      **PROGRESS (session 72): chunks A, B, C and D are BUILT, COMMITTED and each verified
      against the live stack. Only chunk E remains.**
      - [x] **chunk A** (`4bbbe0c`) — S-29 `BoardRow` takes the element as a **prop**
            (`<li>` inside the new `<ol>`, `<div>` for the pinned viewer row). Point 16's trap
            avoided: making the root `<li>` unconditionally would have put a listitem outside
            any list — a *serious* axe violation no web gate catches. S-31's Level / Total XP /
            Day streak are now named `group`s. Deliberately **not** C-2 `MarkDisplay`'s exact
            shape: that names a generic `<div>` (no accessible name in ARIA) and repeats the
            value into the label where it can drift. Naming the group with the LABEL and
            leaving the value as content states the number once.
      - [x] **chunk B** (`cfccaec`) — `seed_e2e.py` grows an `engagement` group: three XP-ranked
            roster students (**declining 200 / inactive 150 / control 100**, real `XpService`
            awards, all on the run's own Cairo date) and a dedicated three-device account.
            Paid the full three-edit contract tax in one commit. **Verified by running the seed
            against the live stack** — and it purged **51** pre-existing `xp_event` rows on its
            first run, so point 15(d)'s accumulation was already real, not hypothetical.
      - [x] **chunk C** (`df57c37`) — `engagement.spec.ts` (leaderboard ordering + the
            announcement flow across two roles) plus the XP and `grade_ready` assertions
            appended to `correct-paper.spec.ts`. **7 specs pass against the live stack in 45s.**
            **Inverted, not just passed:** reversing the expected order fails with `row 1 should
            be Seed Control`, proving the assertion reads real DOM order.
            Also fixed a real S-28 defect the flow surfaced: every card's `Read it` button had
            the identical accessible name, so a screen-reader user hears it repeated with
            nothing to distinguish the notices. It now carries the title (visible text still
            leads, per WCAG 2.5.3) — which is also what lets the spec scope by title instead of
            depending on the seed happening to hold exactly one announcement.
      - [x] **chunk D** (`e288caf`) — the stale exclusion list is gone from **both** sites, all
            three genuinely-unaudited routes have entries (S-08, G-01, DEV-01), and **G-10 is
            closed** — the last screen in the build with no entry.
            **The entries earned themselves immediately, exactly as G-13's did: NONE of the
            three rendered an `<h1>`.** Three more `page-has-heading-one` defects that the
            false "still on mock data" exclusion had been hiding. Fixed in all four of
            Subject's states, not just the populated one — G-13's specific lesson.
            **One honest scope call recorded in the entry itself: G-10 declines Lighthouse.**
            `runLighthouseAudit` drives its own navigation and never replays `ready`, so it
            would score the plain login form and file the number under G-10's slug — a
            measurement of a state it never reached. `/login` is already scored on its own
            entry.
      - [ ] **chunk E — AUDIT LEG DONE (`EXIT=0`, session 76); GATE LEG IN FLIGHT.**
            **The audit landed clean and its numbers are the phase's evidence:** 58 declarative
            registry routes + 4 D2.10-era inline, **73 axe passes** (one per audited *state*) and
            **44 Lighthouse passes** (one per route's canonical state only — P3.10 chunk e2a's
            deliberate decision; **do not read this run as "every state got a full Lighthouse
            pass"**), **0 critical / 0 serious**, Lighthouse **a11y floor 96**, **0 console
            errors**. `student-notifications-populated 0/0/1/0` was the only non-zero cell in the
            entire severity table, and `Horizontal-scroll violations: 1`. Both are now fixed in
            `a4b73e9` — see the two "Defect" paragraphs in this file's header for what each was
            and why each was invisible until this run. Zero `D` entries in
            `git status reports/phase-5` at completion, so nothing stale rode in.
            **Also measured and carried to P5.12 §4: ELEVEN routes score Lighthouse performance
            below 80** (nine at P5.9, seven at P5.8), the lowest being `student-standings` at
            **63** — a P5.8 screen, and now the worst performer in the build. D4.25 is restated by
            a third phase in a row: `check_ui_gates.py` has **no performance check at all**, so a
            green `ui-thresholds` says nothing about performance. **Never cite this run as a
            performance pass.**
            **Gate leg in flight:** full `./scripts/check.sh` under `setsid` with
            `LEMELY_REPORT_DIR=reports/phase-5` exported (see the header for why that single
            variable collapses two runs into one and fixes the five missing screen ids). Wrapper
            PID **`1457845`**, `check.sh` PID `1457847`, log `/tmp/p511-gate.log`, ends in an
            `EXIT=` line. **Do NOT relaunch it.**
            ---
            **Historical, for the audit leg that produced the above:** launched
            `LEMELY_REPORT_DIR=reports/phase-5 npm run audit` under `setsid`, relaunched
            2026-08-10T12:16Z, log `/tmp/p511-audit.log`. **Durable wrapper PID `1409573`**,
            `node scripts/audit.mjs` child `1409596`; `audit.mjs` recycles Chrome per route
            batch, so a changed child PID is progress, not a crash. Do NOT relaunch it.
            **Why session 72's run (wrapper 1376670) was killed at ~11 of ~30 minutes — a
            judgment call that overrode this line's own "do NOT relaunch".** That run started
            15:03:54 local; `audit.mjs` was then edited at **15:09:58**, six minutes into it, to
            add the G-13 *populated* axe check (now committed as `401f8e1`). Node reads its
            entrypoint once at startup, so **the in-flight run could never have contained the
            edit** — it was verifying a tree that no longer existed. Letting it finish would
            have produced a baseline corpus that had to be re-run anyway (~30 min), against
            ~11 min sunk by relaunching. The decisive argument is that **`./scripts/check.sh`
            runs `puppeteer-audit` too**, so the edit executes in the 28-minute gate regardless
            — proving it in this audit is strictly cheaper than discovering it red there. The
            edit was verified before the relaunch, not after: `/student/notifications` is a real
            route (`portals/student/index.tsx:220`, nested under `path: "student"` — it is
            absent from `App.tsx`, which has only five top-level paths, so a grep of `App.tsx`
            alone falsely reads as "no such route"); the waited-for string matches
            `routers/student.py:882` verbatim; `shoot`/`runAxe`/`waitForText` signatures match;
            and the following S-06 block does its own `page.goto`, so the inserted navigation
            does not strand it. The `grade_ready` fan-out itself is already proven live by
            chunk C's `correct-paper.spec.ts`.
            **Two environment facts this cost real work to learn, both worth keeping.**
            (1) **`reports/phase-5/` was ALREADY PARTLY TRACKED — 75 files — swept into two
            BUILD-doc commits mid-run.** `96ce495` (15:05:14) and `4e7e772` (15:07:41) landed
            ~1.5 and ~4 minutes into session 72's audit and captured whatever partial artifacts
            existed at that instant. That corpus is **not a curated baseline**; it is a
            mid-run snapshot. `rm -rf reports/phase-5` before the relaunch therefore showed as
            tracked `D` deletions rather than vanishing. Deliberately **not** restored: the
            fresh run regenerates the corpus, and any tracked file still showing `D` when it
            lands is precisely the signal that the new run did not produce it — restoring first
            would let a stale artifact ride silently into a "fresh" baseline. **When committing
            a BUILD doc, path-scope the `git add`; a bare `git add -A` during an audit run
            commits partial evidence.**
            (2) **`pre-commit run --all-files` is unusable while an audit run is writing into
            `reports/`.** It reported `trim trailing whitespace` and `detect-private-key` as
            FAILED "files were modified by this hook" — neither was real; the hooks saw the
            live run rewriting JSON underneath them. Path-scoped
            `pre-commit run --files web/scripts/audit.mjs` passes clean. **Scope pre-commit to
            the files being committed whenever a background job is writing to the tree.**
            When it lands: read the axe/Lighthouse summary (expect **~73 route-states**, up
            from 68 — G-10, S-08, G-01, DEV-01, plus G-13 populated), then
            `npm run compare-screens -- --baseline reports/phase-4/screens --candidate
            reports/phase-5/screens` (the default baseline is Phase **2.5** and is wrong for
            this phase — always pass `--baseline`), then the full `./scripts/check.sh` under
            `setsid`. `reports/phase-5/` is a new committed baseline.
      **Brief sharpened 2026-08-10 (session 59) by measuring the code while the P5.8 gate run
      held the test lane — recon only, nothing edited. Three findings, and the third is a trap
      that fires 22 minutes into a gate run.**
      1. **There is ZERO E2E coverage of any Phase-5 surface.** `grep -rlnE
         "leaderboard|/student/board|/student/friends|/student/announcements|/student/profile|
         notification|streak|settings/devices"` over `web/e2e/` returns **NONE**. The suite is
         15 files / 25 test blocks and every one of them is Phase 2–4 (at-risk, correct-paper,
         parent/teacher/student journeys, phase4-journey, phase4-practice, rbac, screenshots,
         seed-contract, smoke). So all four flows are a **clean build**, not a retrofit — the
         same shape S-28 and the notification screens were. Do not go looking for a Phase-5
         helper to extend.
      2. **`scripts/seed_e2e.py` seeds NO Phase-5 data at all.** `grep -nE
         "XpEvent|Streak|Friendship|Announcement|Notification|PushSubscription|ExamDate|Device"`
         over all 1796 lines returns **nothing**. Two consequences the brief must not gloss:
         (a) the S-28/S-29/S-30/S-31 entries P5.8 added to `audit.mjs` are probing **empty
         states only** — that is honest for the axe/Lighthouse leg but means **leaderboard
         ordering has never been asserted against a populated board**, which is the single
         acceptance criterion MISSION §4 names for this phase; (b) **G-10 still has no
         audit entry** because it needs an account already holding three live devices, and
         *that* is the seed gap P5.7 recorded as "a seed precondition, not a navigation".
         Seeding XP events across two students with a known ordering is the cheapest way to
         make criterion (a) real, and it is a `seed_e2e.py` change, not a screen change.
      3. **The seed contract costs THREE edits, not one — this is P5.4's `EXPECTED_TABLES`
         trap in its frontend form, and it is more expensive because it fails inside
         `playwright-e2e` (~22 min into a run) instead of `pytest` (~10 min).**
         `web/e2e/seed-contract.spec.ts:171` asserts **exact** top-level key equality
         (`toEqual` over sorted `Object.keys`) and :180 walks an **exhaustive** dotted `SHAPE`
         map over every field. So one new seed group costs: `scripts/seed_e2e.py` (the
         `SeedContract` dataclass at :941 **and** `build_result_payload`, documented at
         spec:126 as returning exactly **14 keys**) + `web/e2e/seed.ts:34` (the TS interface)
         + `seed-contract.spec.ts` (both the key list and `SHAPE`). **Make all three edits in
         the same commit as the seed change**, exactly as P5.5 did for `EXPECTED_TABLES`.
      4. **Ordering: the push-delivery flow depends on P5.9.** G-12/G-13 do not exist yet
         (P5.9 §2 measured that there is no notification frontend of any kind), so "push
         delivery (mock)" has no screen to assert against until P5.9 lands. The other three
         flows (XP accrual, leaderboard ordering, announcement flow) are unblocked **today** —
         S-28/S-29/S-30/S-31 all shipped in P5.8. If P5.9 slips, build those three rather than
         holding the task. And scope the push flow honestly when it comes: this machine has no
         VAPID keys, so the transport reports itself unavailable by design (D5.9 §4) and **no
         real push can be delivered in any harness here** — the assertable facts are the inbox
         row (D5.9 §1's source of truth) and G-12's unavailable state, never a delivered push.
      5. **G-10's seed precondition is now MEASURED (session 61, read-only while the P5.9 gate
         held the lane). It is three `devices` rows and one dedicated account — but the
         account being dedicated is the load-bearing part, not the rows.**
         **The mechanism, verified in code rather than assumed.** The SPA *does* send a device
         identity — `getDeviceId()` (`web/src/lib/auth/storage.ts:16`) mints a
         `crypto.randomUUID()` **once** into `localStorage` and reuses it, and
         `AuthContext.tsx:79/106/127` sends it as `deviceId` on login/signup/OTP-verify.
         Backend: `_device_context` (`routers/auth.py:55`) → `DeviceRegistry.register_login`,
         which matches on `(user_id, client_device_id, revoked_at IS NULL)` and only counts a
         **new slot** when `_match_existing` returns None (`device_repo.py:198` — it returns
         None immediately for a NULL fingerprint). `MAX_DEVICES = 3` (`device_repo.py:39`).
         **I nearly recorded the opposite and it was wrong** — a `grep ... | head -10` truncated
         before line 79 and made it look like the SPA sent no `deviceId`, i.e. that the 3-device
         limit was really a 3-*login* limit. It is not; the client half is fully built and
         correct. *Do not re-derive this as a defect.* The lesson is this phase's recurring one
         pointed the other way — the note-vs-code gap was mine, caused by a truncated grep.
         **Never conclude an absence from a `head`-truncated search.**
         **Why a fresh browser triggers G-10 for free:** Playwright/Puppeteer start with an empty
         `localStorage`, so every audit run mints a *new* deviceId, never matches a seeded row,
         and needs a fourth slot. The SPA sends `confirmDeviceEviction: false` by default
         (`AuthContext.tsx:80`), which maps to `allow_eviction=False`, so the registry raises
         `DeviceLimitReachedError` and **writes nothing** — the 409 is non-destructive and
         idempotent, so the audit entry can be re-run and re-screenshotted freely. It only
         becomes destructive if something *confirms*.
         **So the actual precondition is: a dedicated account no other test ever logs in as.**
         Any other E2E logging in as the same student mints its own fresh deviceId and, on a
         path that permits eviction, silently consumes/evicts a slot — after which G-10 stops
         reproducing and the audit entry goes green by rendering the ordinary logged-in screen.
         That failure is silent and order-dependent, which is the expensive kind. Seed a
         **G-10-only** account.
         **Seeding is three plain inserts, no login flow needed:** `devices` requires only
         `user_id` + `last_seen_at` (`models/users.py:180` — `id` has a `gen_random_uuid()`
         server default; `client_device_id`/`device_label`/`user_agent`/`revoked_at` are all
         nullable, and `revoked_at IS NULL` is what "live" means). Leave `client_device_id`
         **NULL** so no browser can ever accidentally match one.
         **Give the three rows distinct labels/user-agents and staggered `last_seen_at`.**
         `_to_challenge` (`routers/auth.py:65`) names the device a confirmed retry would sign
         out as the **last** of a most-recently-active-first list, and `DeviceLimitNotice.tsx:41`
         highlights exactly that `oldestDeviceId`. With three NULL-labelled rows the screenshot
         is three indistinguishable lines and the one behaviour G-10 exists to prove — that the
         UI names the device it will sign out rather than leaving the client to re-derive it —
         is not visible in the evidence.
         Remember this seed change costs the **three** edits of point 3, not one.
      6. **The leaderboard-ordering assertion has NOTHING to grab, and the naive fix is
         wrong. Measured session 63, read-only while the P5.9 gate held the lane.**
         **(a) There is no test-hook convention to fall back on.** `data-testid` appears
         **zero** times in `web/src/` and `getByTestId` **zero** times in `web/e2e/` — the
         whole 15-file suite locates by accessible name (`getByRole`/`getByText`/`getByLabel`,
         top hits: `getByRole("link", {name: …})`, `getByText("Loading overview…")`). Do not
         introduce testids for this one flow; that imports a foreign convention into a suite
         that deliberately has none.
         **(b) But `BoardRow` (`Standings.tsx:120`) is a bare `<div>` with no role**, inside a
         bare `<div className="divide-y">` (`:199`). Rank is a plain `<span>`, name a plain
         `<span>`. So there is **no row-shaped locator at all** — no `listitem`, no `row`, no
         accessible name on the row. Ordering can only be read as raw DOM order out of the
         section (`aria-labelledby="s29-board"`, `:352`), which asserts nothing a refactor
         would not silently break.
         **The right move is list semantics on the ranked container** — a ranked board *is* an
         ordered list, so `<ol>`/`<li>` is the honest markup, it is an a11y improvement rather
         than a test-only hook, and it yields `getByRole("listitem")` in the suite's existing
         idiom. It is a `web/` change, so P5.11's own UI gate covers it.
         **(c) The trap: the viewer's pinned row is the SAME `BoardRow` component rendered
         OUTSIDE the ranked container** (`:216`, when the viewer falls outside the top N).
         Wrap the `<ol>` around the `divide-y` container **only**. Wrapping the whole
         `BoardBody` puts the pinned row in the list as a trailing `listitem` whose rank is
         out of sequence — an ordering assertion then either fails for the wrong reason or,
         worse, passes on a board where the viewer happens to rank last. Same shape as the
         `no_enrolment`/`no_timetable` collapse P5.5 chunk C refused: two different things
         that render alike.
      7. **XP accrual needs NO new seed data — its cause already exists in the suite, and the
         gap is the read side, not the write side. Measured session 64, read-only while the
         P5.9 gate held the lane.** Point 2 said Phase-5 flows are a clean build; that is true
         of leaderboard/friends/announcements but **not** of XP accrual, and building a fresh
         driver for it would duplicate a flow the suite already runs.
         **(a) `correct-paper.spec.ts` is already a live XP-award driver.** It signs up a
         **fresh** account (`e2e-${Date.now()}@example.com`, :23/:26-33) and drives a real
         upload→mark through the UI, and `POST /student/correct` awards `paper_corrected`
         at `routers/student.py:851`. A brand-new account has **zero** prior XP, so the
         before/after assertion needs no seeding, no fixture and no clock control — the
         strongest of the four flows to build first, not last.
         **(b) The read path is open to that account.** `routers/xp.py:46` gates
         `GET /api/student/xp` on `require_role(Role.student)` **only** — no student profile,
         no onboarding, no enrolment — and `XpService` resolves the streak lazily. So the
         never-onboarded correct-paper account can render S-31 `/student/profile`, which is
         driven purely by `useXpProfile()` (`Profile.tsx:283`). The expected number is exact,
         not a range: `XP_AMOUNTS[paper_corrected]` is **50** (`xp_repo.py:80`), one award,
         well under the 5/day source cap and the 250 global cap.
         **(c) The one precondition that can make the award vanish silently, and it is not
         obvious.** `xp_events.subject_code` is a **live FK to `subjects.code`**
         (`models/engagement.py:55`), the golden fixture reports `subject_code: "0625"`
         (`tests/golden/0625_m20_qp_12_mcq/mark_scheme.json:4`), and `xp_repo.py:37` states
         in its own docstring that an unknown `subject_code` **still raises**. That raise is
         caught by `award_xp_safely` (D5.1 §3 fail-open, deliberately) — so a missing
         `subjects` row costs the student 50 XP while the correction, the result screen and
         **every gate in this build stay green**. The row does exist today, but only as a
         *side effect*: the sole `Subject(` constructor in the codebase is
         `question_bank_repo.py:290`, reached from `link_past_paper_rows`, which the seed
         calls for the placement paper (`seed_e2e.py:489`). Nothing declares that dependency
         and nothing asserts it. **Asserting XP after the correction is the first test that
         would ever catch a fail-open seam failing** — which is the whole point of writing
         the flow, and worth stating in the test's own comment so a later reader does not
         "simplify" it away.
         **(d) The read has nothing to grab — point 6's finding again, at S-31.** `Total XP`
         is an `<Eyebrow>` label with the value in a **sibling bare `<div>`**
         (`Profile.tsx:137-140`), and `Level` (:133-134) and the streak `current` (:167-170)
         have the identical detached shape. `getByText("Total XP")` finds the *label*; the
         number has no accessible name and no programmatic association with it — a
         screen-reader defect, not merely a test inconvenience. Only two values on the screen
         are locatable at all, and both are indirect: the `Meter` label (:145) and
         `"{remaining} XP to level N"` (:147-149), and asserting on `remaining` reads the
         total through `nextLevelXp` — derived precision, exactly what UI spec §1.4 forbids.
         **The fix is this repo's own established pattern, not a new one:** C-2 `MarkDisplay`
         already "carries the value in its own aria-label rather than a sibling text node",
         and `correct-paper.spec.ts:57-61` asserts against precisely that. Give the label/value
         pairs the same treatment. Do **not** reach for `data-testid` — point 6(a) measured
         that the suite has none.
      8. **Point 3's three-edit seed-contract tax applies to FEWER flows than it reads.
         Measured session 64.** Point 3 is right that a *new seed group* costs three edits in
         one commit, and points 2/5 are right that G-10 needs one. But two of the four named
         flows need **no new group at all**, so scoping the whole task around that tax
         overestimates it.
         **XP accrual: none needed** — point 7(a); the driver is a fresh signup inside
         `correct-paper.spec.ts`, which touches no seed group.
         **Announcements: none needed either.** The audience precondition is already seeded:
         `seed_e2e.py:1137` creates the class and enrols the at-risk roster, and the contract
         already exposes `teacher`, `class` and `students` (`build_result_payload`, :941-980),
         which `teacher-journey.spec.ts` and `at-risk-flags.spec.ts` already log in as. Student
         audience resolution is class enrolment **or** a non-revoked school `Seat` (D5.4,
         `routers/student_announcements.py:11-12`), so an enrolled roster student qualifies on
         the first branch. Teacher writes at `POST /api/teacher/announcements`
         (`announcements.py:130`); student reads at `GET /api/student/announcements`
         (`student_announcements.py:79`) with `/unread-count` and `/{id}/read` beside it — the
         read-receipt round trip is assertable end to end.
         **Do not point the announcement flow at the `correctedPaper` student**: `seed_e2e.py:39`
         records it as a *standalone* account deliberately not enrolled in the class, so it has
         no class audience and would render an honest empty state that reads as a passing flow.
         **So the seed work is G-10's three `devices` rows and the leaderboard's XP-ordering
         rows — and only those pay the three-edit tax.**
      10. **Point 8's remaining tax shrinks again: the leaderboard-ordering seed pays it
         EITHER. Measured session 67 while the P5.9 gate finished. Only G-10 pays it — one
         account, three edits, and that is the whole seed-contract cost of P5.11.**
         Point 8 left two payers. The ordering rows are not one, because the assertion needs
         **no new contract key**: `SeedContract` already exposes `students.{declining,inactive,
         control,correctedPaper,belowTarget}` with `displayName`, `email`, `password` and
         `accessToken` (`web/e2e/seed.ts:34`), and they are already co-enrolled in `class`. So
         the spec logs in as a student it already has, reads the *expected* names from the
         contract it already reads, and asserts their relative order on the class board. The
         seed adds `xp_events` rows for existing users and exposes **nothing new** — zero edits
         to `seed.ts`, zero to `seed-contract.spec.ts`, zero to `build_result_payload`.
         **Two traps in those rows, both cheap to avoid and both silent if missed.**
         (a) **`awarded_on` must land inside the CURRENT Cairo week or the board is empty.**
         `board()` filters `XpEvent.awarded_on` between `week_bounds(civil_date_in_zone(now))`
         (`leaderboard_repo.py:367/436`), which is Monday–Sunday of the ISO week containing
         today (`xp_repo.py:130`). A hardcoded literal date passes on the day it is written and
         then silently empties the board forever after — and an empty board fails as "ordering
         assertion found no rows", which reads as a product defect. Seed relative to the seed
         run's own Cairo today.
         (b) **`xp_events.subject_code` is NULLABLE** (`models/engagement.py:55`, FK to
         `subjects.code` with `ondelete="SET NULL"`), so a `basis=total` ordering seed needs
         **no `subjects` row at all**. Session 65 verified the seed guarantees one anyway; this
         is the independent reason the ordering flow cannot trip point 7's FK worry. That worry
         still stands for the *live award* path, which is a different seam.
      11. **S-29 opens on the FRIENDS board, not the class board — so the ordering test must
         click a scope tab before it can assert anything. Measured session 67.**
         `Standings.tsx:316` is `useState<LeaderboardScope>("friends")`. A spec that just
         navigates to `/student/board` and reads rows is looking at the **friends** board,
         which is empty for every seeded student (no friendships are seeded), so the ordering
         assertion would find zero rows and fail as "the board is empty" — a failure that
         reads as a backend defect and is really a default.
         **Drive it in the suite's own idiom, no new hook needed.** The scope selector is a
         `role="group"` / `aria-label="Board scope"` (`:364`) of `TabButton`s carrying
         `aria-pressed` (`:297`), labelled exactly **Friends / Class / School / Everyone**
         (`SCOPES`, `:278`). So `getByRole("group", {name: "Board scope"}).getByRole("button",
         {name: "Class"})` locates it by accessible name, and `aria-pressed` is readable state
         — the same product-owned attribute `audit.mjs`'s `pressToggleOnce` already relies on,
         so the click can be made idempotent for free.
         **Seed the ordering into the CLASS scope specifically.** The seeded roster is
         co-enrolled in `class` (point 10), the class picker only renders when
         `classList.length > 1` (`:379`), and the roster is one class — so `effectiveClassId`
         resolves with no extra interaction. The global/school boards would drag in every
         other seeded account and make the expected order depend on unrelated seed groups.
      12. **P5.11's OTHER half — the UI-gate leg — has never been measured, and measuring it
         found the audit registry's exclusion list stale in ALL FOUR entries. Measured
         session 68, read-only while the second P5.9/P5.10 gate held the lane.**
         Points 1–11 all measure the four E2E flows. The task line's second clause —
         "axe/Lighthouse/screenshots/visual compare" — had never been looked at by any session.
         **(a) How the corpus is actually produced, which is not what its own file header says.**
         `web/e2e/screenshots.spec.ts` captures **five** screen ids only (S-06/S-10/S-14/S-15/
         S-17, the Phase-2.5 retrofit) at 380/768/1440. The other 34 ids in
         `reports/phase-4/screens/` come from **`web/scripts/audit.mjs`**, which writes the same
         `screens/<id>/<state>--<bp>.png` convention. So "capture screenshots for every new
         screen" is overwhelmingly an *audit-registry* job, not a Playwright-spec job — the
         Phase-5 screens are already captured by their registry entries, and
         `screenshots.spec.ts` needs **no** new test. **`reports/phase-5/` does not exist yet**;
         creating it is the explicit re-baseline act `report-dir.ts` documents:
         `LEMELY_REPORT_DIR=reports/phase-5 npm run audit` (and `npm run test:e2e`), never a
         default run — the default is the gitignored `reports/.scratch` precisely so a routine
         `check.sh` cannot overwrite a committed baseline.
         **(b) The registry's exclusion list is stale in all four entries — the third instance
         of this shape in Phase 5, and the file warns about itself twice in its own header.**
         `audit.mjs:83-85` still says "Deliberately still NOT in this registry (P5 screens still
         on mock data): /student/subject/:code, /student/board, /student/landing,
         /student/directions." Measured against the code:
         • **`/student/board` IS audited** — a real registry entry at `audit.mjs:1960` (P5.8's
           S-29). The claim is simply false.
         • **The false claim is ALSO in the runner's operator-facing `log()` at `audit.mjs:2451`**,
           not just the comment. That is the exact failure the header itself describes when
           `/student/plan` went stale ("fixing only the comment would have left the false
           statement in the operator-facing output, where it is actually read"). It has now
           happened a third time, to the sentence documenting the previous two.
         • **`/student/subject/:code` is NOT on mock data.** `Subject.tsx:17` is
           `useSubject(code)`, a real react-query hook. So a real, live-data student route is
           unaudited under a justification that is false — the G-13 miss in its other direction:
           G-13 was absent-and-silently-green, this is present-and-falsely-declared-absent plus
           three genuinely-absent routes excused by a stale reason.
         • `/student/landing` and `/student/directions` are static (no data hook), which is a
           *different* reason from the one written down — and by the registry's own rule three
           lines further on ("no *populated* fixture is NOT on its own a reason to leave a route
           out … an unlooked-at route is exactly how this gate became vacuous") it is not a
           sufficient one either. All four routes exist (`portals/student/index.tsx:213/218/
           235/236`).
         **What P5.11 owes here:** delete the four-route claim from **both** `:83-85` and
         `:2451`, and add registry entries for `/student/subject/:code`, `/student/landing`,
         `/student/directions` (subject needs a seeded student with a corrected paper — the
         contract's `students.correctedPaper` already is one; the other two are static and need
         no fixture). Do **not** re-add `/student/board` — it is already there, and a duplicate
         entry would double-capture S-29 and quietly disagree with itself on state slugs.
         **(c) The visual compare is a manual phase act with a DEFAULT THAT IS WRONG FOR P5.**
         `web/scripts/compare_screens.mjs` is deliberately **not** a `check.sh` gate (its header
         explains why: a per-run screenshot gate re-fails on every intended change and trains
         everyone to ignore it — D3.2's vacuous baseline gate). It is run by hand at re-baseline
         time: `npm run compare-screens -- --baseline reports/phase-4/screens --candidate
         reports/phase-5/screens`. **Its default baseline is `reports/phase-2.5/screens`**, so a
         bare `npm run compare-screens` diffs Phase 5 against a 2.5-era corpus and returns a
         meaningless flood of `added`/`changed` that buries any real regression. Always pass
         `--baseline` explicitly. Exit code is 0 without `--fail-on-change` by design — "changed"
         is a question for a human — so **the compare cannot fail the build and its output must
         be read and accounted for in the report**, which is P4.11's `0 removed` convention
         (a nonzero `changed` is not by itself a regression: the seed's random `run_tag` changes
         every screen showing a class name — the standing Phase-4 limitation).
      13. **The announcement flow can be driven ENTIRELY THROUGH THE UI — a teacher compose
         form exists — and its one trap is a disabled submit button that fails as a 30s hang.
         Measured session 69, read-only while the second P5.9/P5.10 gate held the lane.**
         Points 8 and 9(b) both describe the announcement cause as "the teacher's own POST"
         and neither says whether a *screen* issues it. It does: `/teacher/announcements`
         (`portals/teacher/index.tsx:259`) renders a real compose `<form>`
         (`teacher/screens/Announcements.tsx:198`), so this flow needs no API-only setup step
         and satisfies MISSION §5's "through the real UI" without a caveat.
         **(a) Every locator it needs already exists in the suite's accessible-name idiom —
         zero markup change, like G-13 and unlike S-29/S-31.** `Title` (:202-210) and
         `Message` (:213-223) are inputs nested *inside* their `<label>`, so implicit
         association makes `getByLabel("Title")`/`getByLabel("Message")` work; the class
         `Checkbox` (`components/ui/checkbox.tsx:29/65`) likewise wraps its input in a
         `<label>` with the visible text inside; submit is
         `getByRole("button", {name: "Save announcement"})` (:332).
         **(b) The checkbox's visible text is EXACTLY the seed contract's class name** —
         `routers/classes.py:211` builds the DTO as `label=row.name`, verbatim and undecorated,
         and `seed.ts:39` exposes `class: {classId, name, joinCode}`. So
         `getByLabel(seed.class.name)` matches exactly; no substring hedging and no
         `run_tag` prefix to work around.
         **(c) The trap: `selectedClassIds` starts EMPTY and it gates the submit button's
         `disabled` attribute.** `audience` already defaults to `"classes"` (:120) so the
         radio needs no click — which makes it *look* like title + message + submit is the
         whole driver. It is not: `canSubmit` (:146-149) additionally requires
         `selectedClassIds.length > 0`, and that array starts `[]` (:121). A spec that skips
         the checkbox clicks a **disabled** button and dies as a 30-second Playwright
         "element is not enabled" timeout — which reads as a hung app or a backend problem,
         not as a missing tick. Tick the class checkbox before submitting.
         **(d) The success signal is server-derived and already assertable, so do not assert
         on navigation — the screen does not navigate.** On success a `role="status"` region
         renders "Saved to 1 class." (:335-338) where the count is `data.announcements.length`
         (:174) — the rows **the server says it created**, not an optimistic local value. The
         form also self-clears (:175-178), an independent second proof. Both are stronger
         evidence than a URL change would have been.
         **(e) Two roles in one spec costs nothing.** `injectSession` (`seed.ts:184-207`)
         writes `lemely.session` into `localStorage` before the page's own scripts run and
         every seeded account carries an `accessToken`, so the student half of the flow needs
         no second login. Use the real UI login (`teacher-journey.spec.ts:30-31`) for the
         teacher half if the compose screen is what is under test, and `injectSession` for the
         student read — which is exactly the split `phase4-journey.spec.ts:51-53` already
         documents ("`injectSession` because the login itself is not what they are testing").
      14. **S-28's read half needs no markup change either, the read-receipt round trip is
         fully UI-assertable, and its locator is unique only by an accident of the seed.
         Measured session 69.** Point 9(a) measured G-13's inbox row and found it already
         addressable; nobody had checked S-28, the *other* screen the announcement flow
         asserts on. Same answer: `AnnouncementCard` renders the title as a real **`<h3>`**
         (`student/screens/Announcements.tsx:141`) and the unread state as a literal `Unread`
         chip (:155), so `getByRole("heading", {name: <title>})` locates the card and the chip's
         presence/absence is the readable state. **Three of the four flows now need zero a11y
         work; only S-29 (point 6) and S-31 (point 7d) do.**
         **(a) Opening IS reading, so the receipt round trip costs one click.**
         `handleOpen` (:191-205) fires `markRead.mutate(id)` on first expand, so
         `getByRole("button", {name: "Read it"})` → the `Unread` chip disappearing is the
         whole `POST /{id}/read` round trip asserted end to end through the UI. The button
         also carries `aria-expanded` (:176), so the click is idempotent-checkable in the
         same way point 11's `aria-pressed` is.
         **(b) The trap: `Read it` is NOT a unique accessible name.** Every card renders its
         own identically-named button, so `getByRole("button", {name: "Read it"})` resolves
         only because the seed seeds **zero** announcements (point 2) and the flow's own
         teacher posts exactly one. That is a real precondition, not a property of the screen:
         the day any session seeds an announcement, this locator becomes a strict-mode
         violation in a spec that never changed. Scope it through the card's `<h3>` title —
         which the flow already knows, because it typed it — rather than relying on the count.
      15. **The XP seed that the ordering assertion stands on has TWO date traps and one
         re-run trap, and all three degrade SILENTLY into a board that still renders.
         Measured session 70, read-only while the second P5.9/P5.10 gate held the lane.**
         Points 2/3 measured what a new seed group *costs* (three edits, the contract trap);
         point 6 measured what the ordering assertion can *grab*. Nobody had measured what
         the seed must actually WRITE for a board to be populated and deterministically
         ordered — which is the single acceptance criterion MISSION §4 names for this phase.
         Confirmed by reading: `scripts/seed_e2e.py` contains **zero** occurrences of
         `xp_event`/`XpService`/`streak`, and it builds through `lemely.web.deps` services,
         never raw ORM inserts (its only `session.execute` is the purge at :1298).
         **(a) `awarded_on` is a civil DATE and the board is a Monday..Sunday window around
         TODAY, so a hardcoded date seeds an empty board.** `LeaderboardService.board` filters
         via `week_bounds(civil_date_in_zone(now, zone=DEFAULT_ZONE))` — `xp_repo.py:130` and
         `:112`, `DEFAULT_ZONE = Africa/Cairo` (`:73`). Any fixed calendar date stops being
         "this week" the moment the week rolls over, and the board then renders **empty and
         successful** — not an error, exactly the honest-empty state P5.3 chunk B built.
         Seed relative to now, in Cairo, always.
         **(b) The obvious fix — spreading events across several days for a realistic
         board — reintroduces the same bug on ONE day of the week.** `awarded_on = today - N`
         crosses the Monday boundary whenever the run happens early in the week, dropping
         that student's events into *last* week and silently zeroing them. A spec built that
         way passes Tuesday through Sunday and fails only on Monday, which reads as flake.
         **Put every seeded event on today's Cairo civil date — no spread.**
         **(c) Doing that costs nothing, because 250 XP/day is ample headroom for an
         ordering.** `GLOBAL_DAILY_CAP = 250` (`:99`) with per-source event caps (`:91`):
         `paper_corrected` 50 XP x5/day, `flashcard_reviewed` 1 XP x60/day. So totals like
         200/150/100/50 are exactly 4/3/2/1 papers, and flashcards give 1-XP granularity for
         any value between — every seeded total stays inside what the real award path could
         genuinely produce in one day, so the board is fixture data without being a fictional
         state. Going through `XpService` (house style) is therefore affordable; the escape
         hatch if a wider spread is ever needed is that the dedupe index is **partial**
         (`engagement.py:30-36`, `WHERE dedupe_key IS NOT NULL`), so NULL-key rows never
         collide — but that bypasses the caps and should not be the default.
         **(d) The re-run trap, and it is P4.9 chunk C's purge lesson in Phase-5 form.**
         `seed_e2e.py:1282-1307` exists because the question bank "grows by 24 rows every
         run"; `xp_events` is the same shape with a worse failure mode. Re-seeding the same
         day pushes each student toward 250, and **a capped award is a SUCCESSFUL call that
         writes no row** (`xp_repo.py:24-25`, D5.1 §3) — no exception, nothing logged, the
         seed reports success. So the board first drifts upward, then *freezes* with every
         student tied at the cap; and P5.3 chunk A deliberately made ties read as **equal
         rank** (equal effort = equal standing), so the ordering assertion collapses into an
         all-tied board that looks like a product decision rather than a seed defect.
         **Purge this run's `xp_events` before seeding, exactly as the bank rows are purged.**
      16. **Point 6's markup fix has an AXE consequence nobody measured, and the obvious way to
         write it produces a SERIOUS violation on a route already in the registry — i.e. a hard
         MISSION §6.8 blocker, surfacing ~28 minutes into a gate run. Measured session 71,
         read-only while the second P5.9/P5.10 gate held the lane.**
         Point 6 says the ordering assertion needs list semantics on the ranked container only,
         and calls it "an a11y gain". That is true *only* if the two `BoardRow` call sites are
         made to differ. Measured rather than assumed:
         (a) **Both axe rules are live and both are `impact: "serious"`.** `list`
         (`selector: "ul, ol"`) and `listitem` (`selector: "li"`) are wcag2a/wcag131 in
         `axe-core`, and `audit.mjs:432` calls `window.axe.run()` with **no** `runOnly`/`withTags`
         restriction — so the full default ruleset applies, and `/student/board` has been in the
         registry since P5.8 (`audit.mjs:1960`). Zero serious violations is a MISSION §6.8 gate.
         (b) **The failure mode is the exact inverse of point 6's trap, and one of the two fixes
         is always wrong.** Point 6 warns against wrapping *all* of `BoardBody` (the pinned
         viewer row would join the list out of rank order). The natural correction — wrap only
         `Standings.tsx:200`'s `divide-y` container in `<ol>` and make `BoardRow`'s root `<li>`
         unconditionally — is silently worse: the pinned viewer row at `:217` renders the *same*
         `BoardRow` inside a plain `<div>` at `:215`, so it becomes an **`<li>` with no list
         parent** and trips `listitem`. Point 6's trap costs a wrong-but-green assertion; this
         one costs a red gate.
         **So `BoardRow` needs the element to be a prop** (`<li>` inside the ranked container,
         `<div>` for the pinned instance) — one parameter, not a wrapper. Nothing else in the
         subtree matters: the container's only children are `BoardRow`s, so the `list` rule's
         `only-listitems` check passes once they are `<li>`.
         (c) **No cheap gate catches this — it is `puppeteer-audit` or nothing.** There is **no**
         `Standings` component test anywhere (`find src -iname "*standings*"` returns only the
         screen itself), and **zero** vitest tests in `web/src` import axe at all. So a
         `listitem` violation is invisible to `web-typecheck`, `web-lint`, `web-build` and
         `web-test` — all four go green — and only appears in the second-to-last gate, ~28
         minutes in. Same discovery-cost shape as P5.4's `EXPECTED_TABLES`, one gate later.
      9. **Point 4 is STALE and it was pessimistic. The push/notification flow is now the
         CHEAPEST of the four, not the blocked one. Measured session 66, read-only while the
         P5.9 gate held the lane.** Point 4 was written in session 59, *before* P5.9 existed,
         and its "no screen to assert against until P5.9 lands" is now wrong twice over: the
         screen shipped (chunks B–D), **and** the flow needs no driver of its own.
         **(a) G-13 needs ZERO markup change — it is the opposite of points 6 and 7(d).**
         `NotificationRow` (`Notifications.tsx:105`) renders the title as a real
         **`<h3>`** (:127), so `getByRole("heading", {name: "New announcement"})` locates a
         row directly; the body is a `<p>` carrying the teacher's own title, the unread state
         is a literal `Unread` chip, and both actions are real buttons
         (`Mark as read`, `Open`). Every assertion this flow needs is already in the suite's
         accessible-name idiom. **Do not budget an a11y fix here** — S-29 and S-31 need one,
         G-13 does not.
         **(b) It rides on drivers that already exist, so it costs no new seed group.** The
         announcement fan-out is `announcements.py:202` — the teacher's own
         `POST /api/teacher/announcements` notifies every `student_recipients(row)` — so the
         announcement flow of point 8 and "push delivery (mock)" are **one driver, two
         assertions**: the S-28 list *and* the G-13 inbox row. Likewise `grade_ready`
         (`student.py:877`) fires on the same `POST /student/correct` that point 7 builds the
         XP assertion on, so the correct-paper spec can assert an inbox row for free.
         **(c) `grade_ready` renders with NO `Open` button and that is correct, not a bug.**
         `destinationFor` (`Notifications.tsx:73`) maps `announcement` → `/student/announcements`
         and everything else → `null`, which is session 60's finding (the upload UUID is not
         addressable by `/student/result/:paperId`) honoured in the UI. Assert the *absence*;
         a later session must not "fix" it into a dead link.
         **(d) The one precondition — and unlike point 7(c) it is already satisfied.**
         `notification_repo.create` gates every row on the recipient's preferences
         (`:308-315`, an opted-out type returns `row=None` and the flow silently produces
         nothing). But `notification_prefs_repo.py:88-98` returns `DEFAULTS` for a user with
         **no stored row**, documented as "every type enabled, no quiet hours". So a fresh
         signup and an unseeded roster student both receive. No prefs seeding required.
         **(e) Scope honestly, exactly as point 4 said:** `transport.available` is `False`
         here (no VAPID keys, D5.9 §4), so `notify_safely` returns
         `push_suppressed_reason="transport_unavailable"` **after** writing the row. The row
         is the assertable fact; a delivered push is not, in any harness on this machine.
- [ ] todo — **P5.12** Phase-5 report, merge to develop, push, update PR #3, ntfy.
      **Brief sharpened 2026-08-10 (session 60) while the P5.8 gate run held the test lane —
      recon only, nothing edited. P5.12 was the last remaining bare one-liner (56/58/59 did
      P5.9/P5.10/P5.11). Its expensive part is not the merge, it is §7.**
      1. **Follow `reports/phase-4/REPORT.md`'s section structure** — it is the most recent and
         the most complete: 1 what-was-built, 2 acceptance criteria against MISSION §4, 3 test
         & coverage, 4 quality gates, 5 visual/a11y evidence, 6 the near-vacuous criterion,
         7 known limitations, 8 defects found in existing work, 9 decisions, 10 blockers,
         appendix files-of-record. Phase 4's §6 is worth keeping as a habit, not a one-off.
      2. **§9 is D5.1–D5.14** (`BUILD/DECISIONS.md`, lines 4394–5612). Fourteen records, six of
         them written **before** their code (D5.1, D5.9, D5.10, D5.12, D5.13, D5.14) — that
         ordering is what MISSION §4 mandates for this phase and is worth stating as a result,
         not just complying with silently.
      3. **§7 is the section that must not be re-derived at report time — the Phase-5
         limitations are already scattered across this file's task entries and every one of
         them was explicitly marked "carry to the Phase-5 limitations" when it was found.**
         Collected here once so the report writer copies rather than greps:
         - **No scheduler exists in this build (D5.9 §5).** `streak_warning` and
           `study_plan_reminder` ship as service methods nothing invokes on a timer. Joined by
           **at-risk rule 3 (≥14 days inactive), which cannot fire at its seam** — the alert
           fires on correction, and a student who just uploaded is by definition active, so the
           reason most likely to matter for a *disengaging* student is the one this build
           cannot deliver.
         - **The exam-calendar table ships empty and that is the deliverable, not a gap**
           (D5.8) — no CAIE timetable exists on this machine. There is also **no CLI wrapper
           around `ExamCalendarService.ingest`**, deliberately not built speculatively while no
           document exists to feed it.
         - **No VAPID keys on this machine**, so the push transport reports itself unavailable
           by design (D5.9 §4) and **no real push can be delivered in any harness here**. The
           assertable facts are the inbox row and G-12's unavailable state, never a delivered
           push.
         - **A payload-less push (D5.10) means a service worker must fetch before it can
           render**, so a push arriving offline (or whose fetch fails) shows a generic "You
           have a new notification" — browsers require *some* notification per push.
         - **S-31's "papers marked / questions answered / hours studied" ships absent.** The
           obvious source — a count of `xp_events` rows — is wrong by construction: D5.1 §3's
           caps mean a capped award writes no row, and §8's dedupe means a re-corrected paper
           writes one row for two markings. Achievements are out of scope on D5.1 §10's own
           terms.
         - **No avatar storage exists anywhere**, so S-29's avatar is a monogram off the
           display name — a rendering of data we hold, never a generated identicon that would
           look like identity the account does not have.
         - **G-10's "rough location" is deliberately absent** (D5.12) — no geo-IP source and no
           stored IP exist, and UI spec §1.4 forbids inventing the one field the user would
           decide on.
         - **UI spec §G-12's `weekly_summary` toggle has no backend** — `NotificationType` has
           exactly five values and that is not one of them. Five real toggles shipped; a sixth
           switch gating nothing would violate UI spec §1.4.
         - **G-10 has no audit-registry entry** — it needs a seed account already holding three
           live devices, a seed precondition rather than a navigation. Closed only if P5.11
           lands the `seed_e2e.py` change; report it honestly if not.
      4. **Carried limitations that are NOT Phase-5's but must still appear** (MISSION says
         reported, never silently resolved): the Lighthouse **performance** floor MISSION §11
         claims is gated is still **not enforced** (D4.25, `check_ui_gates.py` has no
         performance check); `web/e2e/` + `playwright.config.ts` are **still in no tsconfig
         `include`** (D3.20) and P5.11 will only grow that untypechecked surface; Phase 2's
         synthetic accuracy gate is **unchanged at 83.8% vs ≥95%**; D3.21's paper 22 is **still
         confidently wrong** (40/40 marks at confidence 1.0, zero flags, 3 marks of pure
         vision/transcription error); 0580 and 0606 still have **zero ingested questions**; and
         a practice set is **marked but its result cannot be read**.
      5. **Mechanics, from P4.12 and P3.11.** Merge `feature/phase-5-engagement` → develop,
         push, update PR #3 (rolling develop→main, **never merged**) — retitle to "Phases 0–5"
         and **append** a Phase-5 section rather than replacing the body; P3.11 found the PR
         body had silently never carried its Phase-2.5 section despite STATE claiming it did,
         so **read the existing body before editing it**. Then prune this Phase-5 section to a
         single summary line per MISSION §8b once the report is committed and merged.
      6. **ntfy: attachments are DISABLED on this instance** (see the environment facts below) —
         put the substance in the message body and use `click`/`actions` to link the report on
         GitHub. Do not retry the `Filename:` PUT.
      7. **Read the real ledger for the spend figure**, `outputs/gemini_spend.json`, not this
         file's `gemini_spend_usd` field — that field is a hand-copied mirror and has drifted
         before (it was 0.1612 against a real 0.18429). Phase 5 is expected to be ~$0.00 of new
         spend; every automated test mocks Gemini (D4.3 made that structural).

### Environment facts worth not re-deriving (cost real work to find)
- **`pre-commit` needs `.venv/bin` on `PATH`, or two hooks fail for the wrong reason.**
  CLAUDE.md mandates `pre-commit run --all-files` before every commit. A bare
  `pre-commit` is **not on PATH at all** (use `.venv/bin/pre-commit`), and running it that
  way still fails `mypy` and `import-linter` with **`Executable 'mypy' not found` /
  `Executable 'lint-imports' not found`** — both are `language: system` hooks that resolve
  their binary off `PATH`, and invoking the venv's pre-commit by absolute path does not put
  the venv's `bin` there. Run it as
  `PATH="/home/sico/Lemely/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files`
  (or `source .venv/bin/activate` first) and all ten hooks pass.
  **The failure mode that matters: it is a false red, not a code failure**, and the two
  hooks it fakes are exactly two of the gates — so it invites either a bogus "the tree is
  broken" diagnosis or a `--no-verify` habit. Session 62 caught it only because the
  concurrently-running `check.sh` had already printed `PASS mypy` / `PASS import-linter`
  on the same tree. **An "executable not found" is an environment answer, never a verdict
  on the code.**
- **A gate run must be launched with `setsid`, or it dies with the session. This note has
  now been wrong twice; the third version is the one backed by timestamps.** Five sessions
  (47, 48, 49, 50) produced **five `/tmp/check_p58*.log` files of exactly 84 bytes**, each
  stopping after the same four backend gates, i.e. mid-`pytest` (gate 5, `check.sh:65`).
  - *First theory (sessions 47–49): bad luck.* Wrong — identical byte counts across
    independent sessions is a deterministic cutoff.
  - *Second theory (session 50): the 600 s foreground Bash cap.* **Also wrong, and it cost
    a sixth run.** The logs are stamped 11:15 / 11:20 / 11:23 / 11:25 / 11:27 — **2 to 5
    minutes apart** — so each session died ~2–4 minutes in, nowhere near 600 s. Decisively,
    session 50 *did* follow that advice and ran it as a harness-tracked background task,
    and it died in exactly the same place. A foreground-only cap cannot kill a background
    task. **Check the timestamps before accepting a duration-based explanation** — the gaps
    between the logs falsified the cap theory using evidence that was already on disk when
    the theory was written.
  - *Third version, what actually holds:* the agent **session** is dying (cause not fully
    pinned; this box has 7.8 GB RAM and was already 3.7 GB into swap, and `pytest` with
    coverage over 2767 tests is the heaviest thing in the run — resource pressure, not a
    tool timeout). Whatever kills the session also kills anything in its process group,
    background or not, and that is what manufactures the orphaned-pytest trap below.
  **So: launch the run in its own detached session with `setsid`**, which puts it outside
  the agent's process group and lets it survive:
  `setsid nohup bash -c './scripts/check.sh > /tmp/LOG 2>&1; echo "EXIT=$?" >> /tmp/LOG' </dev/null >/dev/null 2>&1 & disown`
  Then poll the log; a session that dies mid-run costs nothing, because the next session
  reads a log that kept growing. Append `EXIT=$?` so the status is readable afterwards.
  - *Confirmed by session 52*, which resumed 3 minutes after session 51 launched the run
    and found it **still alive** — the first run in five to get past the 2–4 minute mark.
  - **Corollary that cost four sessions: an 84-byte log is the NORMAL appearance of a
    healthy run mid-`pytest`, not a symptom.** `check.sh` prints nothing for a passing
    gate, so between the four backend gates and pytest returning there is nothing to
    write. Sessions 47–50 each read that byte count as a crash. **Before diagnosing a
    stalled run, `pgrep -af check.sh` or `kill -0 <pid>`** — a stopped log plus a live
    process means "working", and the only honest wait is to poll the PID, not the file.
  A full run is ~25 minutes (pytest ~10, the audit leg ~11). The original note's real
  content still holds and is why the script is the entry point: `check.sh` exports
  `$HOME/.local/bin` onto PATH itself, so all 13 gates run.
- `pytest -q` emits **no `N passed` line** (a reporter plugin eats it). Count the progress
  characters in the `^[.sFEx]+ +\[ NN%\]` lines, or read the `Total coverage:` line.
- **A dead session leaves an ORPHANED `pytest` behind, and the next session's `check.sh`
  then runs concurrently with it — springing the coverage trap below without anyone
  starting a second run deliberately.** Seen for real at the start of the forty-eighth
  session: the forty-seventh's `check.sh` died with the session, but its `pytest` child was
  re-parented to PID 1 and kept running (`/tmp/check_p58.log`, 11:15); the new run started
  11:20 and its pytest was contending within one second. **Before starting any gate run,
  `pgrep -af "check.sh|bin/pytest"` and kill anything with `PPID 1`.** The resume protocol's
  "verify the working tree is clean" does not cover this — an orphan leaves no trace in
  `git status`.
- **Never run `pytest` concurrently with `./scripts/check.sh`.** Both drive `pytest-cov` and
  they contend on the same `.coverage` data file, so the *coverage figure* comes back badly
  wrong while the run still exits 0 — a concurrent run reported **89.67% with
  `practice_repo.py` at 68%**, where a clean serial run of the identical tree reported
  **90.37% and 99%**. The test counts stayed correct (2331/6/0 both times), which is what
  makes it convincing: it reads as a real coverage regression to be chased. Re-measure
  serially before believing any coverage drop.
- **`pre-commit` is not on PATH, and the fix is one PATH entry — not, as this note
  previously claimed, an unfixable hook-environment defect.** The binary is
  `.venv/bin/pre-commit` (no bare `pre-commit`, and `$HOME/.local/bin` does not have it).
  Invoking it as `.venv/bin/pre-commit` is *not enough*: its `mypy` and `import-linter`
  hooks are `system`-language, so they resolve their executable off **PATH**, which still
  lacks the venv — both then fail *"Executable ... not found"*. **Run it as
  `PATH="$PWD/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files`** and all ten hooks
  pass (verified 2026-08-10, session 55, on the P5.8 tree). The old note's "verify in
  `check.sh` instead" advice still works but is the expensive path — it reaches those two
  tools by the same mechanism, having exported a bin dir onto PATH first.
- **`tsc -b` is incremental and a stale `node_modules/.tmp` hides real errors.**
  `web/tsconfig.test.json` was missing `jsx` since P5.8 chunk B — every test importing
  a `.tsx` fails TS6142 — and `npm run build` reported success anyway because the
  tsbuildinfo predated the test. **`rm -rf web/node_modules/.tmp` before believing a
  green build.** Related: a bare `npx tsc --noEmit -p tsconfig.json` is NOT the web
  typecheck; `tsc -b` covers a different (larger) project set and is the stricter gate.
- **`cd` in one Bash call persists into the next.** A `cd web` for an npx run leaves the
  following command running from `web/`, where `.venv/` and `.pre-commit-config.yaml` do not
  exist — which reads as "the venv is gone". Prefix with an absolute `cd /home/sico/Lemely`.
- `GEMINI_API_KEY` lives in `/home/sico/Lemely/.env` and is **not** exported into a
  non-interactive shell — `set -a && . ./.env && set +a`.
- The UI gates write to gitignored `reports/.scratch` (D3.2). Re-baseline explicitly with
  `LEMELY_REPORT_DIR`; never commit into a previous phase's report dir.
- The E2E backend is `scripts/e2e_server.py` on port 8000 — there is no module-level `app`
  attribute on `lemely.web.app`.
- `scripts/seed_e2e.py` is the ONE seeding path for both harnesses, all 5 roles.
- **The past-paper corpus is outside this repo**: `/home/sico/PaperScraper/papers/CAIE/igcse/
  <subject>-<code>/<year>/<session>/` (648 PDFs, 0580/0606/0625). `Sources/` holds only mark
  schemes and the 4 solved scripts — no question papers. Read-only from here.
- Re-parse mark schemes with `lemely parse-mark-schemes <corpus-dir> --output-root
  outputs/schemes --force --on-error continue` (~54s for 0625; 32/72 parse).
- **The ntfy server has attachments DISABLED — do not keep retrying them.** MISSION §7 says to
  PUT a file with a `Filename:` header; that endpoint returns **HTTP 400 `{"code":40014,
  "error":"invalid request: attachments not allowed"}`** on this instance (server-side config,
  not a request the orchestrator can fix). The JSON publish endpoint itself works fine (200).
  So: put the substance **in the message body** and use `click`/`actions` to link the artifact
  on GitHub instead of attaching it.
- **`ruff` excludes `lemely/db/migrations/versions` via `extend-exclude`** (pyproject), and
  **naming a migration file explicitly on the ruff command line overrides that exclusion** —
  so `ruff check lemely/db/migrations/versions/00NN_x.py` reports TC003 on the standard
  `from collections.abc import Sequence` header that *every* migration has and that
  `./scripts/check.sh` correctly ignores. Verified by running it against the already-merged
  `0012_study_plans` and getting the identical error. Lint migrations only through `check.sh`.
- **`pytest --collect-only` still runs the coverage plugin** and will clobber `.coverage` —
  pass `--no-cov`. Its `-q` output is one `path: N` line per file, so the total is
  `... | grep -E "^tests/.*: [0-9]+$" | awk -F': ' '{s+=$2} END {print s}'` (2350 at Phase 4).
- **The visual compare can never be pixel-clean**: `scripts/seed_e2e.py`'s `run_tag` is random
  per run, so every screen rendering a class name changes on every re-baseline. Read **`removed`**
  (must be 0), not `changed`, as the regression signal.

## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
