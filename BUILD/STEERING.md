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
