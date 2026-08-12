# P6.7 — full-product visual QA sweep

Run 2026-08-12 (session 104). Tree: `46bd5f7` plus the tooling added by this
task. All numbers below come from artifacts committed alongside this file —
`lighthouse/`, `axe/`, `screens/`, `compare-vs-phase-*.json` — not from a log
line or a carried figure.

MISSION §4 (Phase 6) asks for five things. Each is answered below with the
command that re-derives it.

---

## 1. The entire screenshot corpus, regenerated

**48 screens · 246 screenshots**, at 380 / 768 / 1440 across every captured
state.

The corpus has **two producers**, and this is the fact worth carrying: running
one of them regenerates most of it and silently drops the rest.

| Producer | Command | Contributes |
|---|---|---|
| Puppeteer audit runner | `LEMELY_REPORT_DIR=reports/phase-6 npm run audit` | 43 screen ids (the route registry) |
| Playwright `screenshots.spec.ts` | `… npx playwright test screenshots.spec.ts` | S-06, S-10, S-14, S-15, S-17 |
| Playwright `correct-paper.spec.ts` | `… npx playwright test correct-paper.spec.ts` | the two `p2.10-*` journey captures |

The first pass of this task ran only the audit runner, and the compare
immediately reported those seven screens as **removed** — which is exactly the
regression signal a blocker is defined by. They had not regressed; they had
never been asked for. `TOKENSAVE_DISABLE_GREP_HOOK=1 grep -ln "SCREENS_DIR"
web/e2e/*.ts` names all producers in one line and is the check to run before
believing any `removed` count.

## 2. Per-role contact sheets — new in this phase

`web/scripts/audit.mjs` writes one flat `contact-sheet.html`. MISSION §4 asks
for a **per-role** sheet, which did not exist, so `web/scripts/contact_sheets.mjs`
was added (`npm run contact-sheets`). It reads only what is on disk, so the
sheets regenerate from a committed corpus without an 11-minute audit.

| Sheet | Screens | File |
|---|---|---|
| Index | — | `contact-sheet-index.html` |
| Student | 22 | `contact-sheet-student.html` |
| Teacher | 14 | `contact-sheet-teacher.html` |
| Parent | 4 | `contact-sheet-parent.html` |
| Shared (all roles) | 7 | `contact-sheet-shared.html` |
| Unclassified | 1 | `contact-sheet-unclassified.html` |
| Flat, all screens | 48 | `contact-sheet.html` (from the audit runner) |

`G-` screens get their own sheet rather than being copied into all three role
sheets — login, settings and device management are genuinely shared, and
duplicating them would overstate the corpus in three places at once. An id
matching no `S-`/`T-`/`P-`/`G-` prefix lands on **Unclassified** rather than
being dropped, and the script says so on stdout; it caught `DEV-01` on the
first run, which is the design working.

## 3. `/impeccable audit` across the frontend source

Full report: [`impeccable-audit.md`](impeccable-audit.md). Score **15/20
(Good)**. Headlines:

- **`npx impeccable detect` is vacuous on this machine.** impeccable 3.5.0
  returns `[]` for `web/src/` *and* for files written deliberately to trip it.
  MISSION §6 gate 8's "`npx impeccable detect` clean" therefore measures
  nothing, and is reported as such rather than counted as a pass.
- **[P1]** ~600 arbitrary Tailwind literals across 41 files bypass tokens that
  already exist for them. Not fixed at ship time — see the report for why.
- **[P2]** 54 `size="sm"` controls sit near 31px: WCAG 2.2 AA (24px) met, AAA
  (44px) not.
- Zero hardcoded colours anywhere in `web/src`.

## 4. axe + Lighthouse over every route

`LEMELY_REPORT_DIR=reports/phase-6 python scripts/check_ui_gates.py` → **exit 0**:

> UI gates clean: 73 route(s) zero serious/critical axe, Lighthouse
> accessibility >= 95 on all (44 route report(s)), performance >= 80 on 22
> student route(s), zero console errors, zero horizontal-scroll violations.

| Measure | Phase 5 | Phase 6 |
|---|---|---|
| axe route-states | 73 | **73** |
| axe violations (critical/serious/moderate/minor) | 0/0/0/0 | **0/0/0/0** |
| Lighthouse route reports | 44 | **44** |
| Accessibility floor | 96 (`teacher-review`) | **96** (`teacher-review`) |
| Performance floor | 65 (`teacher-quiz-detail`) | **80** (`teacher-quiz-detail`) |
| Routes below 80 performance | **8** | **0** |
| Console errors | 0 | **0** |
| Horizontal-scroll violations | 0 | **0** |

**Every route in the product is now at or above 80 performance, including the
teacher and parent routes MISSION §11 never gated.** They were fixed as a side
effect of P6.1's code splitting, not by a bar being moved; `check_ui_gates.py`
still gates student routes only, because inventing a floor MISSION does not
state would be as wrong as ignoring the one it does.

### The one live defect this sweep found, and its fix

`student-standings` failed at **performance 74**, on **CLS 0.386 and nothing
else** — LCP, TBT and speed-index were all healthy.

The cause was attributed from a *committed* artifact rather than a re-run:
`reports/phase-5/lighthouse/student-standings.json` already carried the
`layout-shifts` audit, and both recorded shifts name
`<section aria-labelledby="s29-subjects">` being pushed down the page as three
blocks above it arrive after first paint. **This is not a P6.1 regression** —
CLS was already 0.220 on this route in Phase 5. It is intermittent for a
reason worth stating: the shifts only score when the skeleton paints *before*
the data lands, so the same tree scored 92 on one run and 74 on the next.

Fixed in `web/src/portals/student/screens/Standings.tsx` by reserving the
space (`46bd5f7`); the threshold was not touched. Measured after:

| | before | after |
|---|---|---|
| CLS | 0.386 | **0.000** |
| Layout shifts recorded | 2 | **0** |
| Performance | 74 | **93** |

Zero shifts recorded, not a smaller number — so this is a fixed defect, not a
luckier run.

## 5. Regression against the Phase-2.5 baselines

MISSION §4: *"Any regression against Phase-2.5 baselines is a blocker."*
`removed` is the regression signal, not `changed` — the seed's `run_tag` is
random per run, so every screen rendering a class name changes on every
re-baseline and the compare can never be pixel-clean by construction.

| Baseline | added | **removed** | changed | unchanged |
|---|---|---|---|---|
| `reports/phase-2.5/screens` (39 files) | 207 | **0** | 39 | 0 |
| `reports/phase-5/screens` (246 files) | 0 | **0** | 112 | 134 |

**No blocker.** Against Phase 5 the file counts match exactly (246 → 246) with
`added: 0` and `removed: 0`, which is the strongest form of this check the
harness can produce: every screen Phase 5 captured, Phase 6 captured too, and
Phase 6 introduced no screen Phase 5 lacked. 134 files are byte-comparable
unchanged — a larger unchanged share than Phase 5 managed against Phase 4.

JSON: [`compare-vs-phase-2.5.json`](compare-vs-phase-2.5.json),
[`compare-vs-phase-5.json`](compare-vs-phase-5.json).

---

## Commands to re-derive everything here

```bash
# 1. the corpus + axe + Lighthouse (~35 min; needs the local Supabase stack up)
cd web && LEMELY_REPORT_DIR=reports/phase-6 npm run audit
cd web && LEMELY_REPORT_DIR=reports/phase-6 npx playwright test screenshots.spec.ts
cd web && LEMELY_REPORT_DIR=reports/phase-6 npx playwright test correct-paper.spec.ts

# 2. the gates
LEMELY_REPORT_DIR=reports/phase-6 .venv/bin/python scripts/check_ui_gates.py

# 3. the sheets and the compares (seconds — read committed PNGs only)
cd web && LEMELY_REPORT_DIR=reports/phase-6 npm run contact-sheets
cd web && LEMELY_REPORT_DIR=reports/phase-6 node scripts/compare_screens.mjs \
  --baseline reports/phase-2.5/screens --json reports/phase-6/compare-vs-phase-2.5.json
```
