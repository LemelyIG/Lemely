# Cost ladder

Baseline real split: abs error 49.0 marks over 5 scripts, review 39.6%, escalation 0.0%, worst script 0625_w24_41 $0.0466.

Baseline escalation rate 0.0% (max script 0.0%)

Baseline 0625_s23_22 escalation $0.0000 (0.0% of script)

Baseline 0625_s25_42 escalation $0.0000 (0.0% of script)

Baseline 0625_w24_41 escalation $0.0000 (0.0% of script)

Baseline 0625_w24_42 escalation $0.0000 (0.0% of script)

Baseline 0625_w25_42 escalation $0.0000 (0.0% of script)

Real A/A floors: full pipeline 8.00 marks; marking only (upstream pinned) 4.00 marks.

Baseline in-run cache hits: 11 (calls replayed within rung 0 itself; their cost is not in its total). Cache entries written: 84; cacheable live records: 84.

| lever | stacked on | overrides | expected saving | measured saving (2027) | extra mismarks / allowed | id-match | p95 latency | validity | review rate | proof | verdict | reasons | real abs err | exact | within 1 | real review | binding pass | max $/script | esc rate | esc $ share | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| final Claude config, fully live | baseline | gemini.adjudication_confidence_threshold=0.86; gemini.adjudication_drawing_leaves=True; gemini.adjudication_drawing_max_leaves=6; gemini.adjudication_max_leaves=6; gemini.adjudication_model=claude-haiku-5-5; gemini.adjudication_reread_disagreed=True; gemini.correction_retry_median=True; gemini.review_confidence_threshold_for={'claude-haiku-5-5': 0.72} | 0% | -30.5% | 0 / 1 | 1.000 | 64846 ms | 1.000 | 3.8% | BUILD/accuracy-runs/claude-c-2026-10-26-live3/F | ACCEPT | - | 32.0 | 87.5% | 98.6% | 17.0% | 5.0/5 | 0625_s25_42 $0.0655 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from baseline (0 stage tags not live, replayed where the rung called them); judged on the full-pipeline A/A floor 8.00; real latency excludes the replayed upstream |

Final against baseline at 2026 rates: $0.0046 vs $0.0034 per script (-32.2% saved)

Final against baseline at 2027 rates: $0.0046 vs $0.0034 per script (-32.2% saved)

Stop reason: Flip judgement PASS (see FLIP.md)
