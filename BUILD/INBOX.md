# Inbox — directives from the human

The orchestrator reads this at every session start and after every completed
task. Unhandled items are `- [ ]`; handled items become `- [x]` with a one-line
note on what was done. Never delete an item — the history is useful.

Send items from your phone by publishing to the control topic, or locally with
`./nudge "your instruction"`.
