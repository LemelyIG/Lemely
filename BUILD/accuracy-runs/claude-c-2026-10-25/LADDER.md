# Cost ladder

Baseline real split: abs error 37.5 marks over 5 scripts, review 35.1%, escalation 11.1%, worst script 0625_s25_42 $0.1707.

Baseline escalation rate 11.1% (max script 17.0%)

Baseline 0625_s23_22 escalation $0.0000 (0.0% of script)

Baseline 0625_s25_42 escalation $0.1089 (69.2% of script)

Baseline 0625_w24_41 escalation $0.0804 (64.7% of script)

Baseline 0625_w24_42 escalation $0.0901 (67.1% of script)

Baseline 0625_w25_42 escalation $0.0698 (62.6% of script)

Baseline triggers confidence=47

Real A/A floors: full pipeline 9.00 marks; marking only (upstream pinned) 2.50 marks.

| lever | stacked on | overrides | expected saving | measured saving (2027) | extra mismarks / allowed | id-match | p95 latency | validity | review rate | proof | verdict | reasons | real abs err | exact | within 1 | real review | binding pass | max $/script | esc rate | esc $ share | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| effort numeric high, short/recall medium | baseline | gemini.claude_effort_for={'correction:extended': 'medium', 'correction:mcq': 'low', 'correction:numeric': 'high', 'correction:recall': 'medium', 'correction:short': 'medium'} | 0% | -3.2% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-25/e5 | REJECT | real abs error did not fall (changed by +2.00 marks); a lever must reduce it; 0625_s25_42 $0.1729 exceeds $0.10 per script; 0625_w24_41 $0.1442 exceeds $0.10 per script; 0625_w24_42 $0.1488 exceeds $0.10 per script; 0625_w25_42 $0.1170 exceeds $0.10 per script | 39.5 | 84.2% | 97.4% | 35.8% | 5.0/5 | 0625_s25_42 $0.1729 | 12.0% | 63.8% | escalation rate 12.0% (max script 18.6%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.1138 (69.9% of script); 0625_w24_41 escalation $0.0823 (63.2% of script); 0625_w24_42 escalation $0.0930 (65.8% of script); 0625_w25_42 escalation $0.0656 (59.4% of script); triggers confidence=51; real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 2.50; real latency excludes the replayed upstream |
| keep higher of two Haiku marks + reason before mark | baseline | gemini.correction_reason_first=True; gemini.correction_retry_keep_higher=True | 0% | -9.6% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-25/h2ab | REJECT | real abs error did not fall (changed by +0.50 marks); a lever must reduce it; 0625_s25_42 $0.1887 exceeds $0.10 per script; 0625_w24_41 $0.1341 exceeds $0.10 per script; 0625_w24_42 $0.1824 exceeds $0.10 per script; 0625_w25_42 $0.1263 exceeds $0.10 per script | 38.0 | 85.4% | 97.2% | 36.3% | 5.0/5 | 0625_s25_42 $0.1887 | 12.3% | 58.8% | escalation rate 12.3% (max script 23.3%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.1118 (64.5% of script); 0625_w24_41 escalation $0.0710 (54.8% of script); 0625_w24_42 escalation $0.0963 (61.7% of script); 0625_w25_42 escalation $0.0683 (56.7% of script); triggers confidence=52; real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 2.50; real latency excludes the replayed upstream |
| printed 0625 P4 marking conventions | baseline | gemini.correction_syllabus_conventions=True | 0% | 2.3% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-25/h2c | REJECT | real abs error did not fall (changed by +1.00 marks); a lever must reduce it; 0625_s25_42 $0.1756 exceeds $0.10 per script; 0625_w24_41 $0.1094 exceeds $0.10 per script; 0625_w24_42 $0.1348 exceeds $0.10 per script; 0625_w25_42 $0.1185 exceeds $0.10 per script | 38.5 | 84.7% | 97.6% | 34.4% | 5.0/5 | 0625_s25_42 $0.1756 | 10.4% | 63.4% | escalation rate 10.4% (max script 17.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.1194 (70.9% of script); 0625_w24_41 escalation $0.0630 (58.3% of script); 0625_w24_42 escalation $0.0802 (64.2% of script); 0625_w25_42 escalation $0.0713 (62.7% of script); triggers confidence=44; real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 2.50; real latency excludes the replayed upstream |
| escalation effort low | baseline | gemini.claude_effort_for={'correction:extended': 'medium', 'correction:mcq': 'low', 'correction:numeric': 'low', 'correction:short': 'low', 'escalation': 'low'} | 15% | 0.0% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-25/e1b | REJECT | 0625_s25_42 $0.1275 exceeds $0.10 per script; 0625_w24_41 $0.1022 exceeds $0.10 per script; 0625_w24_42 $0.1346 exceeds $0.10 per script | 35.5 | 85.1% | 98.6% | 36.3% | 5.0/5 | 0625_w24_42 $0.1346 | 10.6% | 56.4% | real saving 18.6%; escalation rate 10.6% (max script 23.3%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0708 (59.9% of script); 0625_w24_41 escalation $0.0503 (53.6% of script); 0625_w24_42 escalation $0.0804 (63.2% of script); 0625_w25_42 escalation $0.0461 (52.5% of script); triggers confidence=45; real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 2.50; real latency excludes the replayed upstream |
| no Sonnet escalation | baseline | gemini.escalation_cap_per_script=0 | 55% | 0.0% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-25/noesc | ACCEPT | - | 38.0 | 84.9% | 97.6% | 35.4% | 5.0/5 | 0625_w24_42 $0.0496 | 0.0% | 0.0% | real saving 64.6%; escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 2.50; real latency excludes the replayed upstream |

Final against baseline at 2026 rates: $0.0000 vs $0.0000 per script

Final against baseline at 2027 rates: $0.0000 vs $0.0000 per script

Stop reason: Superseded by the H3 box fix (binder prompt changed); dropped Sonnet escalation (noesc); continued in claude-c-2026-10-26
