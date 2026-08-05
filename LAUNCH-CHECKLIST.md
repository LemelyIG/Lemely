> **Resuming mid-build?** Phases 0–2 are complete. Do the design-stack
> setup in `SETUP-DESIGN-STACK.md` first, then come back to step 8 here.

# Lemely Unattended Build — Launch Checklist

Do these in order. The run starts at step 9. Total setup: ~20 minutes.

## 1. Install the kit into the repo
```bash
cd /home/sico/Lemely
# copy from wherever you downloaded the kit:
cp -r <kit>/BUILD .
cp -r <kit>/.claude .            # merges settings.json + agents/ into the repo
cp <kit>/supervisor.sh .
chmod +x supervisor.sh
# make sure the audit is present at the repo root:
ls LEMELY_AUDIT.md
git add BUILD .claude supervisor.sh LEMELY_AUDIT.md
git commit -m "chore: add unattended build kit"
git push
```

## 2. Environment files
```bash
cat > .env << 'EOF'
GEMINI_API_KEY=<your key>
LEMELY_GEMINI_API_KEY=<same key>
EOF
```
(.env is gitignored and deny-listed from agent reads; both names set because of
the env-mapping trap the audit found — Phase 0 fixes it properly.)

## 3. Tooling present
```bash
claude --version        # need >= 2.1.154 for dynamic workflows; update: claude update
docker info             # must succeed without sudo
gh auth status          # already verified: Xart3mis, ssh, repo scope — OK
node --version && python --version
npm i -g supabase 2>/dev/null || true   # optional; agents can install it, this saves a step
```

## 4. Claude Code config (one-time, interactive)
```bash
cd /home/sico/Lemely && claude
```
Inside the session:
- `/config` → turn **Dynamic workflows** ON (required on Pro)
- `/config` → set **Dynamic workflow size** to `medium`
- `/model` → confirm Opus is selectable on your plan
- `/usage` → note your current weekly headroom before committing to the run
- exit

## 5. Phone monitoring
- ntfy app → subscribe to topic: `lemely-ErBPK7TIRGD1sQP5`
- Optional: Claude iOS app can attach to Claude Code sessions remotely; the
  supervisor's headless runs may not all be visible there — ntfy + the GitHub
  app (watch PRs and `reports/`) are the reliable channels.

## 6. Machine prep
- Suspend/sleep disabled (done, per you). Also mask lid-switch if it's a laptop
  you'll close: check `HandleLidSwitch=ignore` in /etc/systemd/logind.conf.
- Ensure ~30 GB free disk (Supabase images, node_modules, corpus downloads).
- Plug into AC power.

## 7. Sanity-check the kit
```bash
grep -n "lemely-ErBPK7TIRGD1sQP5" supervisor.sh BUILD/MISSION.md   # your ntfy topic
grep -n "8.00" BUILD/MISSION.md                                    # budget ceiling
```

## 8. Know your controls (while it runs)
- Watch live: `tmux attach -t lemely` (detach: Ctrl-b d)
- Logs: `tail -f BUILD/logs/run-*.log`
- Pause everything: `tmux send-keys -t lemely C-c` then kill the tmux session
- Resume later: just rerun step 9 — state is on disk, nothing is lost
- Emergency stop for the orchestrator itself: create a file `BUILD/STATE.md`
  edit setting `status: HALTED`
- Your review job afterwards: the `develop → main` PRs, one per phase, plus
  `reports/phase-N/REPORT.md` and finally `DELIVERY.md`

## 9. LAUNCH
```bash
cd /home/sico/Lemely
tmux new -s lemely './supervisor.sh'
```
You'll get an ntfy "Supervisor started" within seconds and a Phase-0 start
notification once the first session boots.

## What to expect
- **Notifications you'll get:** a 20-minute in-place progress heartbeat (phase,
  tasks done, last commit, elapsed), a ping on each phase transition with the
  milestone report attached, task-level progress from the orchestrator every
  30–60 min, crash alerts with the log attached (deduplicated — identical
  failures within 30 min notify once), limit-wait notices showing the exact
  resume time, and a dead-man's-switch alert if the machine dies.
- **Models:** the orchestrator runs on Sonnet and escalates itself to Opus for
  roughly 5–8 runs across the whole build (schema, auth, parser decision,
  confidence design, stubborn bugs). You'll get a "Escalating to Opus" ping
  each time, so you can see if it's over-using it.
- On Pro, expect substantial idle time waiting for session/weekly limits. The
  supervisor parses the reset time out of the limit message and sleeps until
  exactly then; if the reset is more than 14 hours out (i.e. the weekly cap),
  it stops cleanly and pings you — rerun `./supervisor.sh` after the reset and
  it picks up where it left off.
- Rough shape: Phase 0 fast; Phases 1–2 are the bulk (DB/auth + the real core
  loop + accuracy work); 3–6 follow. Wall-clock time is dominated by your plan's
  limits, not the work.
- Budget pings at $4 and $6 of Gemini spend; hard stop of live calls at $8.
- If you get a high-priority "blocker" ping and want to intervene: attach to
  tmux, read BUILD/BLOCKERS.md, and either fix the environment issue or leave it
  — the orchestrator skips blocked tasks and revisits them each session.
