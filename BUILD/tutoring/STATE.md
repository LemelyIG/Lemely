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
| I0 | merge + push + provision + probes done (`handoffs/I0-probes.md`); config patch + commit pending |
| T00 | dispatched (sonnet/high) |
| config hot patch | dispatched (sonnet/medium) |
| T16, I0b | not started |
| W1..W9, IF | not started |

## Standing facts
- Evidence runs: named-file pytest only; never the whole suite locally. Full suite = CI on the draft PR head (opened at I1).
- Guard-safe commands only: literal `env VAR=... cmd`, `bash scripts/tutoring/*.sh`, `npm --prefix web ...`.
- Hot files are lead-owned (PLAN §3).
- Open user notes: Q2 shared-DB residual state (PLAN `.omc/plans/open-questions.md`).
