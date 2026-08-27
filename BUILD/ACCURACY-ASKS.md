# ACCURACY-ASKS.md — the open human decisions, in one place

**Status 2026-08-27 (run 55): the previous B1–B18 list is DISCHARGED and has
been replaced.** Every B row was either answered in the 2026-08-26 interview and
acted on, or is carried forward below under its own C number. Seven new
decisions (**C1–C7**) were taken in an interactive interview on 2026-08-27 and
are recorded here as the standing rulings, not as open questions.

**What is actually open is short: C8, plus the four H issues.** Everything else
in the programme is sequenced behind C8.

Nothing here is a request for more investigation — each row is a decision only
you can make. Where I have a recommendation I give it, and where a
recommendation of mine would be self-serving (cheaper, or avoids a
measurement) I say so.

**How to answer.** Reply on the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or append to
`BUILD/ACCURACY-INBOX.md`, naming the ask number and your choice — e.g.
`C8: (b)`. Partial answers are useful.

**If you answer only one: C8.** It is the only thing gating the queue, and every
other agent-ownable item is behind it.

---

# OPEN

## C8 — #151: C6 retires 100% of the det marking path. Which fork?

**This is the whole queue.** #112, #110, #136, #39, #38, #95, #127 and #41 are
all held behind it.

Ruling **C6** (below) was *"deterministic parsing for MCQ ONLY"*, confirmed on a
second ask. It was taken before the blast radius was measured. Measured
afterwards, and reconciling exactly with #41's own independent 10,314-point
census:

**MCQ schemes carry zero `answer_points`** — MCQ answers live in the separate
`mcq_answer` field. So C6 does not retire *most* of the det marking path:

- **210 of 289** committed schemes (72.7%) move to paid Gemini
- **10,314 of 10,314** answer points (100%) move with them
- the paid set goes **190 → 400** of 479 source mark schemes

| | one-off | recurring, every full rebuild |
|---|---|---|
| **cost (MEASURED, per-page → per-scheme)** | **$11.92 – $14.71** | **$25.23 – $28.02** |
| *first published on #151, understated 1.83×–2.7×* | *$5.41 – $6.52* | *$10.33 – $13.79* |

**Corrected 2026-08-27 (DA26).** The figures #151 opened with reused the token
model from `preflight-88-2026-08-26`, and presented reproducing it "to the cent"
as validation. #88's item-2 sweep had **already falsified that model at 1.83×**
the same day, on this exact task — measured at n=1, confirmed at n=6, aborted at
6 of 190. The corrected figures scale the **measured** $0.07005/scheme.

**And it fits no ceiling the programme records.** Ledger **$3.146479**; the
**committed** hard ceiling is **$8.00** (`config.py:111`). The $25.00 in
`lemely.toml` is **gitignored and worktree-local** — DA13's hazard class,
invisible to CI.

| | one-off | recurring |
|---|---|---|
| ledger after | $15.07 – $17.86 | $28.38 – $31.17 |
| vs committed **$8.00** | **BREACH** | **BREACH** |
| vs local $25.00 | fits | **BREACH** |
| tokens vs 5M `per_run_token_ceiling` | **6.49M — TRIPS** | **13.74M — TRIPS** |

MISSION §12.4 makes that a stop-and-ask. Two of those are qualitative changes
from what #151 first told you: the recurring rebuild now breaches even the local
$25.00, and both plans trip the token ceiling #88 already flagged as undersized.

Beyond money: #112/#110/#136/#39 become dead work; **#53 (M3, parse-path parity)
is voided**; MISSION §2 and §14 both rest on the det path being measurable, and
this removes it rather than fixing it; #38's escalation gate loses its subject.

1. **Proceed as ruled** — det → MCQ only. Needs a ceiling decision first, then
   close #112, #110, #136, #39 as retired-by-C6.
2. **Narrow C6 to the question #41 asked** — A-mark dependency left undetermined
   on det, per B1's own *"may leave cases unresolved — accepted"*. det path and
   all four fixes stay live. **No new spend.**
3. **The middle reading** — det parses everything (so the four fixes stay
   valuable), but det-parsed marks are trusted end-to-end for MCQ only, with
   non-MCQ marking escalated. Still needs its own routing issue and preflight.

**No recommendation between 1 and 2** — that is an architecture and product
call, not a measurement one, and I would be choosing the shape of the programme
rather than reporting on it. What the measurement establishes is only that the
choice is not the marginal one it looked like when taken.

Full preflight: `BUILD/accuracy-runs/preflight-c6-2026-08-27/`.

## C9 — B14, still owed on the H issues

Unchanged, and not decisions I can make or work around (MISSION §3.5 — never
close one, never mark one done, never work around one):

- **#49 (H4)** — split membership stays **NOT frozen** until #57 delivers and you
  sign off. #57 is blocked on it.
- **#51 (H7)** — labeller B's identity and onboarding.
- **#52 (H8)** — the three seed rulings themselves (ECF, `oe` alternatives, list
  rule over-tariff). The machinery is built and the log ships empty; the rulings
  are examiner judgment and I will not draft them.
- **#55 (H9)** — authorisation for the single run of the frozen test split.

## C10 — B17 is still unfixed, and it bit again this run

`scripts/accuracy_board.py` gates **every** subcommand — including `comment` —
on board membership, so it refuses any issue not on the project board. B17 ruled
**option 3** (a direct H-number/label check instead of board membership as a
proxy), and that is **not implemented**. This run had to post four rulings via
raw `gh issue comment` — **#112, #136, #127 and #151** — because the sanctioned
path structurally refuses them.

Recording it as an ask only because it keeps costing runs; the fix itself is
agent-ownable and needs no decision from you beyond "yes, do it".

---

# ANSWERED 2026-08-27 (run 55) — standing rulings, do not re-argue

| # | Issue | Ruling |
|---|---|---|
| **C1** | #112, #110, #136-fix | Marking sweep **WAIVED** on the instrument-blindness ground #38 got under A6(a) and #93 under B2 — `load_golden_cases` (`harness.py:130`) never invokes the det parser, so both arms are identical inputs. In its place: a **zero-spend deterministic before/after re-parse** of the 289 schemes under `corpus/` (`parser_sha 8758dba`), checked against #112's pre-stated prediction of strict deflation (77–246 marks). B15 is **not** reopened. |
| **C2** | #38 b2+3 | **Defer behind #136's fix, then re-measure.** The 44.4%-of-papers / 21.6%-of-points defaulted rate is contaminated by DA21 mechanism (B). Bullets stay **open and unticked** — nothing closed on a falsified premise. |
| **C3** | #39 | **Same waiver as C1**, with a zero-spend deterministic before/after over `corpus/` standing in — measuring how many schemes the gate **reroutes**, not what Gemini then marks. Caveat attached by the human: #39 is **cost-changing**, so the reroute count is itself the number to watch. Bullet 9's zero-false-positive requirement **holds**. |
| **C4** | #58 | **~14 calls / ~$0.01 AUTHORISED** to close bullet 3 on live evidence (the offline "7 held" must not stand in for it). **No new issue** for q11b — it stays recorded on #58 as reproduced-but-not-significant (Fisher p = 0.4737). §12.9 still forbids re-running at higher n. |
| **C5** | #127 | **Fold into #95.** One corpus-membership restatement instead of two. Chain: #151 → #136 fix → #95 → this. |
| **C6** | #41 → programme-wide | **Deterministic parsing for MCQ ONLY.** Asked twice; the broad reading was confirmed against an option stating it "largely moots #112, #110, #136 and #39". **Now costed and forked as C8 / #151** — it is not executable as ruled without a ceiling decision. |
| **C7** | #59 | **Both blockers authorised** — commit the handwritten CAIE renders (MISSION §12.7 granted, scoped to #59) and run the measurement (costed preflight first, per #28). The public-repo irreversibility point was flagged once and the ruling reaffirmed with it in view. |

**Carried forward from the B list, still binding:** B3 (0.99 is INHERITED-NOT-MEASURED, no follow-up issue), B5 (whitespace fixtures are ordinary golden cases; their consequence — restating every figure against the new membership — is **unspent, not skipped**), B12 (per-mark-point is the published H7 figure; `mark_point_verdicts` still declared and never read), B15 (fix all three sub-defects — the *what*; only its sweep clause was superseded by C1), B16 (`cumulative_usd` is a known-contaminated **upper bound**; re-sum every run, never carry the header forward).

**Sequencing as it now stands:** **#151 (C8)** → #136 fix → then #95 → #127, and #38's re-measurement; #112 + #110 jointly; #39. #58's ~$0.01 and #59 are authorised and independent, awaiting their preflights. #57 stays blocked on #49.
