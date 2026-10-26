# Cost ladder

Baseline real split: abs error 36.0 marks over 5 scripts, review 38.2%, escalation 10.1%, worst script 0625_s25_42 $0.1519.

Baseline escalation rate 10.1% (max script 16.3%)

Baseline 0625_s23_22 escalation $0.0000 (0.0% of script)

Baseline 0625_s25_42 escalation $0.0971 (68.5% of script)

Baseline 0625_w24_41 escalation $0.0748 (62.9% of script)

Baseline 0625_w24_42 escalation $0.0854 (64.9% of script)

Baseline 0625_w25_42 escalation $0.0648 (62.6% of script)

Baseline triggers confidence=43

Baseline in-run cache hits: 11 (calls replayed within rung 0 itself; their cost is not in its total). Cache entries written: 84; cacheable live records: 84.

| lever | stacked on | overrides | expected saving | measured saving (2027) | extra mismarks / allowed | id-match | p95 latency | validity | review rate | proof | verdict | reasons | real abs err | exact | within 1 | real review | binding pass | max $/script | esc rate | esc $ share | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| second binder read effort none | baseline | gemini.claude_effort_for={'binding_second_read': 'none', 'correction:extended': 'medium', 'correction:mcq': 'low', 'correction:numeric': 'low', 'correction:short': 'low'} | 13% | -29.2% | 1 / 1 | 1.000 | 56862 ms | 1.000 | 25.6% | BUILD/accuracy-runs/claude-c-2026-10-24/a1 | REJECT | real abs error rose by 12.00 marks, above the A/A floor 6.00; real cost rose from $0.1019 to $0.1142 per script; 0625_s25_42 $0.1489 exceeds $0.10 per script; 0625_w24_41 $0.1222 exceeds $0.10 per script; 0625_w24_42 $0.1675 exceeds $0.10 per script; 0625_w25_42 $0.1355 exceeds $0.10 per script | 48.0 | 82.1% | 96.5% | 42.9% | 4.5/5 | 0625_w24_42 $0.1675 | 11.8% | 60.6% | real saving -12.1%; escalation rate 11.8% (max script 20.9%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0873 (61.7% of script); 0625_w24_41 escalation $0.0653 (54.9% of script); 0625_w24_42 escalation $0.1102 (67.2% of script); 0625_w25_42 escalation $0.0834 (61.7% of script); triggers confidence=50 |
| escalation cap 1 per script | baseline | gemini.escalation_cap_per_script=1 | 40% | -23.8% | 1 / 1 | 1.000 | 44311 ms | 1.000 | 25.6% | BUILD/accuracy-runs/claude-c-2026-10-24/cap1 | REJECT | real abs error rose by 17.50 marks, above the A/A floor 6.00 | 53.5 | 81.1% | 95.3% | 40.3% | 4.5/5 | 0625_s25_42 $0.0950 | 1.9% | 45.0% | real saving 34.4%; escalation rate 1.9% (max script 2.6%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0465 (51.7% of script); 0625_w24_41 escalation $0.0399 (46.4% of script); 0625_w24_42 escalation $0.0342 (44.1% of script); 0625_w25_42 escalation $0.0298 (43.3% of script); triggers confidence=8 |
| escalation cap 2 per script | baseline | gemini.escalation_cap_per_script=2 | 30% | -11.9% | 2 / 1 | 1.000 | 51873 ms | 1.000 | 26.9% | BUILD/accuracy-runs/claude-c-2026-10-24/cap2 | REJECT | 2 newly mismarked parts exceed the allowed 1 (small tier); 0625_s25_42 $0.1142 exceeds $0.10 per script; 0625_w24_41 $0.1103 exceeds $0.10 per script | 41.0 | 83.7% | 97.4% | 39.4% | 5.0/5 | 0625_s25_42 $0.1142 | 3.8% | 50.5% | real saving 21.7%; escalation rate 3.8% (max script 5.1%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0572 (54.7% of script); 0625_w24_41 escalation $0.0571 (53.7% of script); 0625_w24_42 escalation $0.0442 (50.3% of script); 0625_w25_42 escalation $0.0432 (49.5% of script); triggers confidence=16 |
| leaf-scoped Sonnet adjudication replaces prefix escalation | baseline | gemini.adjudication_max_leaves=8; gemini.adjudication_model=claude-sonnet-5-5; gemini.escalation_model=claude-haiku-5-5 | 30% | 25.1% | 0 / 1 | 1.000 | 38504 ms | 1.000 | 26.9% | BUILD/accuracy-runs/claude-c-2026-10-24/c2x | REJECT | real abs error rose by 15.50 marks, above the A/A floor 6.00; 0625_w24_42 $0.1024 exceeds $0.10 per script | 51.5 | 81.8% | 94.8% | 41.7% | 4.5/5 | 0625_w24_42 $0.1024 | 0.0% | 0.0% | real saving 38.4%; escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script) |
| escalation effort low | baseline | gemini.claude_effort_for={'correction:extended': 'medium', 'correction:mcq': 'low', 'correction:numeric': 'low', 'correction:short': 'low', 'escalation': 'low'} | 15% | -1.9% | 0 / 1 | 1.000 | 38557 ms | 1.000 | 25.6% | BUILD/accuracy-runs/claude-c-2026-10-24/e1 | REJECT | real abs error rose by 21.50 marks, above the A/A floor 6.00; 0625_s25_42 $0.1256 exceeds $0.10 per script; 0625_w24_42 $0.1089 exceeds $0.10 per script | 57.5 | 80.7% | 94.6% | 39.4% | 4.0/5 | 0625_s25_42 $0.1256 | 7.8% | 54.6% | real saving 22.6%; escalation rate 7.8% (max script 16.3%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0673 (62.2% of script); 0625_w24_41 escalation $0.0428 (49.4% of script); 0625_w24_42 escalation $0.0596 (60.4% of script); 0625_w25_42 escalation $0.0452 (51.0% of script); triggers confidence=33 |

Final against baseline at 2026 rates: $0.0044 vs $0.0044 per script (0.0% saved)

Final against baseline at 2027 rates: $0.0044 vs $0.0044 per script (0.0% saved)

Stop reason: Superseded: full-pipeline screens were confounded by binding noise; continued with pinned upstream in claude-c-2026-10-25
