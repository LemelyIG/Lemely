# ACCURACY-INBOX.md — steering inbox for the accuracy programme

The contract, in full:

- The supervisor's control listener appends directives from the human as
  `- [ ] <timestamp> — <directive>` lines at the end of this file. Nothing else
  writes unchecked items.
- The orchestrator reads this file FIRST on every run, before touching the
  board or any code. Unchecked items are standing orders and take precedence
  over the mission's own queue.
- After acting on an item, the orchestrator flips it to `- [x]` and appends an
  indented one-line note on what it did (or why it could not act, in which case
  the item still gets checked and the problem goes to `BUILD/BLOCKERS.md` and
  the notify channel).
- Never delete an item and never reorder items — the history is the audit
  trail. Directives that are questions get their answer in the note.

Send items from your phone by publishing to the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or locally by
appending a line in the format above.

---

(no items yet — seeded empty 2026-08-18)
