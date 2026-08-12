# Steering the build

Publish a message to the control topic `lemely-ctl-9QmZR4vXpL2wDA7t` from the
ntfy app on your phone, tap an action button on any notification, or run
`./nudge <thing>` on the laptop.

## Keywords

| Send | What happens |
|---|---|
| `SYNC` | Pushes every local branch that's ahead of its remote (or has no remote yet) to GitHub, then reports what went up, what was already current, what failed, how many files are still uncommitted, and how many PRs are open. Never force-pushes, never commits for you. |
| `SYNC <branch>` | Same, limited to one branch. |
| `STATUS` | Phase, progress bar, current task, blockers, Gemini spend, recent commits. |
| `PAUSE` | Syncs, then holds after the current run finishes. Nothing is lost. |
| `STOP` | Kills the current run immediately, then holds. Work is committed to its last checkpoint. |
| `RESUME` | Continues. |
| `SKIP` | Tells the agent to mark its current task blocked and move to the next independent one. |
| `DIGEST` | Forces the daily digest immediately. |
| *anything else* | Filed in `BUILD/INBOX.md` as a directive. The agent reads it at its next checkpoint and it outranks its current plan. |

## When SYNC is useful

The agent pushes on its own after each merge to `develop`, but a run that dies
mid-task can leave local commits on a feature branch. `SYNC` gets everything
onto GitHub so you can read the diff from the GitHub mobile app, or hand the
branch to someone else. It also runs automatically whenever you `PAUSE`, so
what you're about to review is always what's on the server.

If a push comes back rejected, it's almost always because the remote branch
moved (you or another clone pushed there). Nothing is forced and nothing is
lost — check `BUILD/logs/sync.log` and resolve it by hand.

## Taking the wheel

`PAUSE`, then open a second tmux window and run `claude` interactively in the
same repo. All state is on disk, so you can talk to it normally, make changes,
commit — then `RESUME`.

## What each notification opens

Tapping the notification body opens the most useful page for that event; the
buttons underneath are the actions worth taking from a phone. ntfy allows three
buttons per message, so each set is the three that matter for that moment.

| Notification | Tapping it opens | Buttons |
|---|---|---|
| Supervisor started | STATE.md checklist | Status · Sync · Commits |
| Heartbeat (every 10m) | Latest commit | Latest commit · Sync · Pause |
| Possibly stalled | repo | Skip task · Pause · Status |
| Run checkpointed | Latest commit | Latest commit · Sync · Pause |
| Phase complete | Pull requests | Review PRs · Phase report · Sync |
| New screenshots | reports/ tree | All screenshots · Commits · Status |
| New blocker | BLOCKERS.md | Blockers · Skip task · Pause |
| Run crashed | repo | Skip task · Pause · Open repo |
| Usage limit — waiting | Commit history | Sync · Pause · Commits |
| Limit reset — resuming | STATE.md checklist | Status · Pause |
| Long limit window — stopping | Commit history | Commits · PRs · Checklist |
| Paused | Pull requests | Resume · PRs · Branches |
| Build complete | DELIVERY.md | DELIVERY.md · PRs · Reports |
| Build halted | BLOCKERS.md | Blockers · Checklist · Resume |
| Watchdog (machine died) | Commit history | Commits · Checklist · Status |
| Daily digest | Commit history | Commits · Reports · Sync |

And for the keyword replies:

| Keyword reply | Tapping it opens | Buttons |
|---|---|---|
| `SYNC` result | Branches | Branches · Pull requests |
| `STATUS` | STATE.md checklist | Sync · Pause · Commits |
| `PAUSE` queued | Pull requests | Resume · Status · PRs |
| `STOP` | Latest commit | Resume · Sync · Commits |
| `RESUME` | STATE.md checklist | Status · Pause · Checklist |
| `SKIP` filed | INBOX.md | Inbox · Blockers · Status |
| `DIGEST` queued | reports/ tree | Journal · Reports · Status |
| Directive filed | INBOX.md | Inbox · Status · Pause |

All GitHub links point at the `develop` branch, which is where merged work
lands; `main` only moves when you merge a phase PR yourself.
