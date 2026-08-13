# STATE.md — Lemely Checkpoint File

> This file is the single resume point. On every session start (fresh or after a
> usage-limit reset), read this file FIRST, then `BUILD/STEERING.md`, then continue
> from `NEXT ACTION`. Update this file after every completed work unit, every gate
> result, every DECISION sent or resolved, and every steering message processed.
> Never rewrite history sections; only update the live fields and append to logs.

---

## BUILD (MISSION.md) — COMPLETE

The MISSION.md build is finished. On first redesign session, fill this table from the
actual build outcome (read the prior STATE content / BUILD reports / merged PRs), then
treat it as frozen history.

| Phase | Status | Milestone PR |
|---|---|---|
| (fill from completed build) | DONE | |

Do not reopen build phases. Any build-era bug found during redesign: fix in place
if trivial, otherwise log under REDESIGN → Deferred Issues.

---

## REDESIGN (REDESIGN-MISSION.md) — ACTIVE

### Live status

```
MISSION:            BUILD/REDESIGN-MISSION.md
CURRENT PHASE:      0 — Setup & Verification
CURRENT SURFACE:    none
CURRENT BRANCH:     (create redesign base branch off develop in Phase 0)
NEXT ACTION:        Verify §2 prerequisites: all 9 skills loadable, Python 3,
                    Node 22.12+, Playwright+Chromium, Gemini key, ntfy topics.
                    Install anything missing, then run context.mjs, hooks on,
                    /impeccable init, and send the Steering Channel test message.
LAST UPDATED:       (set on first session)
LAST STEERING TS:   0   (poll https://ntfy.sh/lemely-ErBPK7TIRGD1sQP5-in/json?poll=1&since=<this>)
```

### Phase ledger

| Phase | Status | Completed | Notes |
|---|---|---|---|
| 0. Setup & Verification | IN PROGRESS | — | |
| 1. Audit | PENDING | — | |
| 2. Brand & Design System | PENDING | — | |
| 3. IA & UX Flows | PENDING | — | |
| 4. Surface redesign | PENDING | — | |
| 5. Motion & data-viz | PENDING | — | |
| 6. Hardening & adaptation | PENDING | — | |
| 7. Final QA & report | PENDING | — | |

### Surface ledger (Phase 4 order)

| Surface | Status | Branch | Gates | Merged |
|---|---|---|---|---|
| Student dashboard | QUEUED | — | — | — |
| Past-paper correction flow | QUEUED | — | — | — |
| Study surfaces (classifieds, flashcards, plans) | QUEUED | — | — | — |
| Gamification (XP, streaks, leaderboards) | QUEUED | — | — | — |
| Teacher dashboard + quiz builder | QUEUED | — | — | — |
| Parent views | QUEUED | — | — | — |
| Admin views | QUEUED | — | — | — |
| Auth | QUEUED | — | — | — |
| Marketing / landing | QUEUED | — | — | — |
| 404 / misc | QUEUED | — | — | — |

### Gate status (current surface only)

```
SURFACE:            none
BUILD COMPLETE:     —
INSPECTION ROUND:   —
FINDINGS TO FIX:    —
CONFIRM ROUND:      —
HALLMARK STAMP:     —
HOOK FINDINGS:      —
TESTS:              —
```

### Open DECISIONs

| ID | Question | Options | Default | Sent | Timeout | Status |
|---|---|---|---|---|---|---|
| — | | | | | | |

Resolved: none

### Steering log pointer

Full log: `BUILD/STEERING.md` (append-only; create it in Phase 0 if missing).
Last processed inbound message: none.

### Deferred issues (found during redesign, not blocking)

- none

---

## Update rules (for the agent)

1. Update `Live status` block on every work-unit boundary; `LAST UPDATED` always current.
2. Phase/surface ledgers: flip status only, append notes; never delete rows.
3. Gate status block is scratch space for the current surface; reset it when a surface
   merges (copy its outcome into the surface ledger first).
4. DECISIONs: add on send, move to Resolved with the answer on resolution or timeout
   (mark timeouts as "DEFAULTED").
5. `LAST STEERING TS` advances only after the message is logged AND acted on or queued.
6. Commit STATE.md with the work it describes, same commit.
