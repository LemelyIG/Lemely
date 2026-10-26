# Tutoring marketplace — STATE (survives /compact)

Updated 2026-10-25. Worktree `/home/sico/Code/Lemely/.claude/worktrees/tutoring-marketplace`, branch `feat/tutoring-marketplace` (off develop; origin/develop merged at `8d847b6b`).

## Authority
User pre-authorised: signed commits and pushes to own branches, no GO gate, bypass permissions. Still ask for: non-additive migration, changing an existing route's permissions, marking pipeline, locked rows 1-19 (`decision-log.md`), spec ambiguity.
Memory: `tutoring-autonomy-commit-push`.

## Phase
Phases 0-2 DONE (recon, brainstorm LOCKED, ADRs, SPEC rev 3, threat model, plan rev 2). Phase 3 executing from `PLAN.md`.

## Wave status
| Row | Status |
|---|---|
| I0 | DONE (merge, provision, probes, config hot patch `858e05c0`) |
| T00 | DONE `ab28fce0` (+ export fix `7c5fd10e`, live_e2e fix `864bf9c9`) |
| T16 | DONE `dc4dea03` |
| I0b | DONE: live mode `dedicated`; baseline in `handoffs/I0-baseline.md` |
| W1 (T01, T02, T03, T04) | DONE; I1 hot patches `553da773`; gate G1 green at `2d216d32` (see `handoffs/W1.md`); draft PR opened |
| W2 (T05, T06, T07, T08) | DONE; I2 hot patches `c83f8f38`; gate G2 green (see `handoffs/W2.md`) |
| W3 (T09, T10, T11, T12) | DONE incl. review fixes; I3 hot patches `43a349b6`; gate G3 running (see `handoffs/W3.md`) |
| W4 (T13, T14, T15) | DONE incl. review fixes; I4 hot patches `4ef4e0a8`; gate G4 green (see `handoffs/W4.md`) |
| W5 (T17, T18, T19, T20) | DONE incl. review fixes and block-masking lanes F5-A/F5-A2; I5a hot patches `7c5e596a`; gate G5 green (STATIC all PASS; Python 1,980; SCAN-PY 472; web 3,847; RACE 5/5); see `handoffs/W5.md` |
| W6 (T21, T22, T23, T24) | DONE incl. review fixes (F6-21..24); I6a hot patches `743d5ff0`; gate G6 green (STATIC all PASS; Python 2,134; SCAN-PY 472; web 4,193; RACE 5/5); see `handoffs/W6.md`; pushed |
| W7 (T25, T26, T27, T28) | next (tell user: disk 99% full) |
| W8, W9, IF | not started |

Rules: every new task and review = fresh agent with a minimal brief (memory `lean-context-fresh-agents`); fix rounds = fresh agent with findings + SHA; resume only after a rate-limit stop.

CI: PR #324. Wave 1 CI green (run 40253907923). Runs take ~60 min; do not push while one is in progress.

Live mode: dedicated. Playwright chromium-1234 installed. `npm ci` needs `PUPPETEER_SKIP_DOWNLOAD=1`.

## Standing facts
- Evidence runs: named-file pytest only; never the whole suite locally. Full suite = CI on the draft PR head (opened at I1).
- Guard-safe commands only: literal `env VAR=... cmd`, `bash scripts/tutoring/*.sh`, `npm --prefix web ...`.
- Hot files are lead-owned (PLAN §3).
- Open user notes: Q2 shared-DB residual state (PLAN `.omc/plans/open-questions.md`).
