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
