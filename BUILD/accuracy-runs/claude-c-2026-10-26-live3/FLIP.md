# Flip judgement

Candidate `F` against the Gemini rung `gemini`. Real split: the frozen reference set, 2 live run(s) each; per-leaf marks stay uncommitted. Counts only.

Gemini escalation rate 0.2% (max script 2.3%)

Gemini 0625_s23_22 escalation $0.0000 (0.0% of script)

Gemini 0625_s25_42 escalation $0.0000 (0.0% of script)

Gemini 0625_w24_41 escalation $0.0000 (0.0% of script)

Gemini 0625_w24_42 escalation $0.0575 (18.2% of script)

Gemini 0625_w25_42 escalation $0.0000 (0.0% of script)

Gemini triggers confidence=1

Candidate escalation rate 0.0% (max script 0.0%)

Candidate 0625_s23_22 escalation $0.0000 (0.0% of script)

Candidate 0625_s25_42 escalation $0.0000 (0.0% of script)

Candidate 0625_w24_41 escalation $0.0000 (0.0% of script)

Candidate 0625_w24_42 escalation $0.0000 (0.0% of script)

Candidate 0625_w25_42 escalation $0.0000 (0.0% of script)

| figure | Gemini | Claude candidate |
|---|---|---|
| real abs error (marks) | 37.0 | 32.0 |
| exact leaves | 86.3% | 87.5% |
| within 1 mark | 97.4% | 98.6% |
| review rate | 9.9% | 17.0% |
| binding passes | 5.0/5 | 5.0/5 |
| mean $ per script (2027) | $0.2128 | $0.0492 |
| worst script | 0625_w24_42 $0.3713 | 0625_s25_42 $0.0655 |
| escalation rate | 0.2% | 0.0% |
| escalation $ share | 5.4% | 0.0% |
| incomplete real cases | 0 | 0 |
| synthetic mismarked parts | 6 | 4 |

| script | Gemini max $ | Claude max $ | Claude escalation $ |
|---|---|---|---|
| 0625_s23_22 | $0.0163 | $0.0130 | $0.0000 |
| 0625_s25_42 | $0.2896 | $0.0655 | $0.0000 |
| 0625_w24_41 | $0.2502 | $0.0620 | $0.0000 |
| 0625_w24_42 | $0.3713 | $0.0572 | $0.0000 |
| 0625_w25_42 | $0.2283 | $0.0545 | $0.0000 |

Verdict: PASS

Reasons:
- none

Notes:
- real abs error 32.00 vs Gemini 37.00
- review rate 17.0% vs Gemini 9.9%
- binding passes 5.0 vs Gemini 5.0
- escalation rate 0.0% (max script 0.0%)
- 0625_s23_22 escalation $0.0000 (0.0% of script)
- 0625_s25_42 escalation $0.0000 (0.0% of script)
- 0625_w24_41 escalation $0.0000 (0.0% of script)
- 0625_w24_42 escalation $0.0000 (0.0% of script)
- 0625_w25_42 escalation $0.0000 (0.0% of script)

## Caveats and decisions (added by hand, 2026-10-26)

- **The Gemini rung predates the numbered-item binding fix (H2e, commit 0186d061).** It was copied from `claude-c-2026-10-24/gemini` (real split, two runs) to stay inside the $6 Gemini cap. On 0625_s25_42, both Gemini runs leave 7(c)(ii) items 1 and 2 unbound (4 marks per run), while both Claude runs bind them. On today's code Gemini would score about 33 rather than 37, so the Claude candidate (32.0) leads by about 1 mark, inside the real marking-only A/A floor (4.0). The verdict stands; the margin is "not worse", not "better".
- **Review-rate bar (user decision, 2026-10-26):** the flip bar caps the candidate's review rate at 22% (was: at most Gemini + 10 points). Claude's review threshold is 0.72; on the pinned crop2 runs it flags about 21.7% of leaves and catches about 65% of wrong leaves, against Gemini's 28%.
- **Gemini-path binder changes (user decision, 2026-10-26):** the numbered-item binding (H2e) and the two stub re-reads under their own cache keys apply to every provider, as bug fixes, with no switch.
- **Dev split of the Gemini rung:** reused from `cost-ladder-2026-10-19/a1-flash-lite` (user decision); it differs from today's Gemini defaults only in the first-read output cap (16,384 vs 32,768), which no read in that rung approached (largest 1,626 tokens).
