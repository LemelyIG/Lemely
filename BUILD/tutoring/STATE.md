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
| W2 (T05, T06, T07, T08) | next |
| W3..W9, IF | not started |

Live mode: dedicated. Playwright chromium-1234 installed. `npm ci` needs `PUPPETEER_SKIP_DOWNLOAD=1`.

## Standing facts
- Evidence runs: named-file pytest only; never the whole suite locally. Full suite = CI on the draft PR head (opened at I1).
- Guard-safe commands only: literal `env VAR=... cmd`, `bash scripts/tutoring/*.sh`, `npm --prefix web ...`.
- Hot files are lead-owned (PLAN §3).
- Open user notes: Q2 shared-DB residual state (PLAN `.omc/plans/open-questions.md`).
