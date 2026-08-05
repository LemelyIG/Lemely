# Manual setup before resuming the build (Phase 2.5)

You said you'd do this by hand. Do all of it before restarting `supervisor.sh` —
the orchestrator will treat a missing piece as a blocker and skip design work.

## 1. Prerequisites (check first — both are real blockers)
```bash
node -v      # must be >= 24  — `npx impeccable detect` requires it
python3 -V   # must be 3.x    — UI/UX Pro Max's search scripts require it
```
If Node is below 24, upgrade before continuing (`nvm install 24 && nvm use 24`).

## 2. Install the design skills
From `/home/sico/Lemely`:

```bash
# Impeccable — primary design workflow
npx impeccable install
#   (or, inside Claude Code:  /plugin marketplace add pbakaus/impeccable )

# UI/UX Pro Max — design reference database
npx skills add nextlevelbuilder/ui-ux-pro-max-skill --skill ui-ux-pro-max --agent claude-code
#   if the install fails with a symlink error, use the CLI installer instead:
#   npx ui-ux-pro-max-cli init --ai claude

# Taste-Skill — anti-generic pressure (v2 is the default)
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
```
Verify: `ls .claude/skills/` should show `impeccable`, `ui-ux-pro-max`, and
`design-taste-frontend`. Approve any hooks the installers request.

## 3. Define the brand — this is the step that matters
Inside an interactive Claude Code session:
```
/impeccable init
```
It interviews you and writes `PRODUCT.md`, then offers `DESIGN.md`. Answer it
properly; everything downstream reads these files, and unfilled placeholders
will halt design work.

**Have answers ready for:**
- Product type → **product mode** (design serves the product), not brand mode.
  Lemely is an app, not a marketing site — except the landing page (G-01), which
  is the one Persuade surface.
- Audience → Egyptian IGCSE/A-Level students aged 14–18 on phones, plus teachers
  on laptops and parents who are not confident users.
- Voice → plain, direct, unpatronising; never cheerful about bad news.
- Anti-references → generic ed-tech (pastel rounded cards, mascots, confetti),
  and the current AI-design tells (cream + serif + terracotta; near-black with
  one acid accent; Inter-on-dark; purple-blue gradients).
- Colours and type → **your call, and it's a real decision.** `docs/LEMELY_UI_SPEC.md`
  §1.6 argues for grounding the identity in the visual language of exam papers
  (the mark in a box, the question number in the margin, the examiner's
  annotation, the threshold table). Feed that section to the interview.

**One thing to decide before you run it:** the plan you were given mentions
accent `#0057D9` and IBM Plex Sans. Those were generic examples in that
document, not Lemely brand decisions. If you want them, put them in DESIGN.md
deliberately. If not, ignore them — nothing in the kit hardcodes them.

## 4. Install the test toolchain
```bash
cd web
npm i -D @playwright/test puppeteer @axe-core/playwright axe-core lighthouse
npx playwright install --with-deps chromium webkit
```
(The orchestrator will wire the harness itself in Phase 2.5; this just gets the
binaries on disk so it isn't downloading browsers mid-run.)

## 5. Copy the updated kit in
```bash
cd /home/sico/Lemely
cp -r <kit>/BUILD .            # MISSION.md, STATE.md, QUALITY-BAR.md
cp -r <kit>/.claude .          # updated settings + designer & visual-qa agents
cp -r <kit>/docs .             # LEMELY_UI_SPEC.md
cp <kit>/supervisor.sh .
chmod +x supervisor.sh
git add -A && git commit -m "chore: design stack + phase 2.5 build kit" && git push
```

## 6. Sanity check, then launch
```bash
ls .claude/skills/ && ls docs/LEMELY_UI_SPEC.md DESIGN.md PRODUCT.md
tmux new -s lemely './supervisor.sh'
```

## What you'll get back
Phase 2.5 produces a token file, a component library with every state, the
screenshot harness, and a retro-fit of the Phase-2 screens — plus a contact
sheet of every screen at every breakpoint, attached to the phase-complete
notification on your phone. Phases 3–6 then can't merge UI without clearing
`BUILD/QUALITY-BAR.md`, axe, Lighthouse, and a visual-regression check.
