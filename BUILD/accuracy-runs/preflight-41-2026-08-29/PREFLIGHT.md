# #41 — costed preflight for the gate-9 before/after sweep. NOT RUN, NOT AUTHORISED.

**Zero spent so far.** The code half of #41 is complete and zero-spend; this
prices the sweep its acceptance requires. Posted **before** any spend, per #28
and MISSION §10a.

## The unit, stated first

**One Gemini `correction` call marks one non-MCQ leaf question.** Not per paper,
not per fixture. Every figure below multiplies that unit.

## The population, named

| | fixtures | non-MCQ leaves |
|---|---|---|
| principles **present** (6 parsed) | 6 | 39 |
| **principles ABSENT — the population A13 requires the sweep to cover** | **6** | **31** |
| **total per arm** | **12** | **70** |

**A13's condition is satisfiable.** It requires the sweep to cover "the
unparseable-principles papers specifically", and 6 fixtures / 31 non-MCQ leaves
have no principles: `0580_s23_qp_22_theory_{correct,partial,whitespace,wrong}`,
`0625_m20_qp_12_mcq`, `0625_w21_qp_32_theory_nested`.

**Two arms → 140 marker calls.**

## Cost

Basis: the A/A floor run (`aa-floor-2026-08-23-a`) spent **$0.958711** over
**740** calls — **$0.001296 per call, measured, not modelled**.

| | |
|---|---|
| 140 calls × $0.001296 | **≈ $0.181** |
| with 50% headroom for the injected principles enlarging every input | **≈ $0.27** |

**Where this estimate is weak, stated rather than buried:**

- The $0.001296 average is over a **task mix** that included `mark_scheme`
  parsing calls, which are far more expensive than `correction` calls. So the
  average **overstates** a correction-only run — the estimate is conservative in
  the safe direction.
- But the principles injection **enlarges every correction input**, by up to ~6
  bullet points of prose per call, which pushes the other way.
- Per DA26: this is a **measurement reused across a different call mix**, not a
  validated model of correction calls specifically. **An n=1 first-call check
  must precede the full run**, and the run must be ledger-bounded, exactly as
  C20's sweep was.

**Against a headroom of $1.629549, ~$0.27 fits with room. It is not authorised.**

## A consequence that outlives the sweep

**`VERSION` moves 4 → 5, which invalidates the entire cached golden corpus.**
That is required — the prompt changed, and a cached mark from the old prompt
would be attributed to the new one — but it means **every subsequent marking
run also pays full price** until the cache refills, not just this sweep. That
cost is not in the figure above and should not be discovered later.

## The batching constraint, checked rather than assumed

#41's own note requires every M1 marker-prompt change to land in **one** commit
with **one** `VERSION` bump, or the delta cannot be attributed. Re-checked on
2026-08-29:

- **#38** (M1.3) is defaulted-mark provenance and `escalate_on_defaulted_marks` —
  **not** a marker-prompt change; the provenance half already landed.
- **#39** (M1.4) was ruled **parser-side** by A9, and DA43's work on it touched
  `reconcile.py` and `config.py` — **no prompt file**.
- No other open M1 item proposes a marker-prompt change.

**So bullets 1 and 2 in this one commit, with this one `VERSION` bump, satisfy
the constraint.** Residual risk unchanged from the issue's own statement: if #38
or #39 later needs a marker-prompt change, it must be batched *with a re-run of
this sweep* or its delta is unattributable.

## What is being asked for

Authorisation to spend **up to $0.30**, ledger-bounded, with an n=1 first-call
check before the remaining 139. **Not** a request to raise the ceiling.
