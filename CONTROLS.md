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
