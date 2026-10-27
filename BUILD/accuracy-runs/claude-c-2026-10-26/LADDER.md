# Cost ladder

Baseline real split: abs error 41.5 marks over 5 scripts, review 38.7%, escalation 0.0%, worst script 0625_s25_42 $0.0507.

Baseline escalation rate 0.0% (max script 0.0%)

Baseline 0625_s23_22 escalation $0.0000 (0.0% of script)

Baseline 0625_s25_42 escalation $0.0000 (0.0% of script)

Baseline 0625_w24_41 escalation $0.0000 (0.0% of script)

Baseline 0625_w24_42 escalation $0.0000 (0.0% of script)

Baseline 0625_w25_42 escalation $0.0000 (0.0% of script)

Real A/A floors: full pipeline 5.00 marks; marking only (upstream pinned) 1.00 marks.

| lever | stacked on | overrides | expected saving | measured saving (2027) | extra mismarks / allowed | id-match | p95 latency | validity | review rate | proof | verdict | reasons | real abs err | exact | within 1 | real review | binding pass | max $/script | esc rate | esc $ share | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Haiku crop adjudication of drawings (cap 6) + re-read disagreements (H2d+H4a) | baseline | gemini.adjudication_drawing_leaves=True; gemini.adjudication_drawing_max_leaves=6; gemini.adjudication_max_leaves=0; gemini.adjudication_model=claude-haiku-5-5; gemini.adjudication_reread_disagreed=True | 0% | -4.4% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-26/crop1 | ACCEPT | - | 40.5 | 84.9% | 97.4% | 37.7% | 5.0/5 | 0625_s25_42 $0.0541 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from baseline (9 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 1.00; real latency excludes the replayed upstream |
| Haiku crop adjudication of text leaves below 0.86 (cap 6) | baseline | gemini.adjudication_confidence_threshold=0.86; gemini.adjudication_max_leaves=6; gemini.adjudication_model=claude-haiku-5-5 | 0% | -8.2% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-26/crop2 | ACCEPT | - | 39.5 | 85.4% | 97.2% | 38.4% | 5.0/5 | 0625_s25_42 $0.0556 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from baseline (9 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 1.00; real latency excludes the replayed upstream |
| median of three Haiku marks below 0.86 (H4c) | baseline | gemini.correction_retry_median=True | 0% | -17.8% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-26/med3b | ACCEPT | - | 39.5 | 85.1% | 97.4% | 35.8% | 5.0/5 | 0625_w24_41 $0.0572 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from baseline (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 1.00; real latency excludes the replayed upstream |
| crop1 levers stacked on crop2 | crop2 | gemini.adjudication_confidence_threshold=0.86; gemini.adjudication_drawing_leaves=True; gemini.adjudication_drawing_max_leaves=6; gemini.adjudication_max_leaves=6; gemini.adjudication_model=claude-haiku-5-5; gemini.adjudication_reread_disagreed=True | 0% | -1.5% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-26/cropboth | ACCEPT | - | 38.5 | 85.1% | 97.6% | 38.2% | 5.0/5 | 0625_s25_42 $0.0561 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from crop2 (9 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 1.00; real latency excludes the replayed upstream |
| median of three + review threshold 0.72 on cropboth | cropboth | gemini.adjudication_confidence_threshold=0.86; gemini.adjudication_drawing_leaves=True; gemini.adjudication_drawing_max_leaves=6; gemini.adjudication_max_leaves=6; gemini.adjudication_model=claude-haiku-5-5; gemini.adjudication_reread_disagreed=True; gemini.correction_retry_median=True; gemini.review_confidence_threshold_for={'claude-haiku-5-5': 0.72} | 0% | -15.7% | 0 / 0 | 1.000 | 0 ms | 1.000 | - | BUILD/accuracy-runs/claude-c-2026-10-26/final | ACCEPT | - | 34.0 | 87.3% | 97.6% | 19.8% | 5.0/5 | 0625_s25_42 $0.0621 | 0.0% | 0.0% | escalation rate 0.0% (max script 0.0%); 0625_s23_22 escalation $0.0000 (0.0% of script); 0625_s25_42 escalation $0.0000 (0.0% of script); 0625_w24_41 escalation $0.0000 (0.0% of script); 0625_w24_42 escalation $0.0000 (0.0% of script); 0625_w25_42 escalation $0.0000 (0.0% of script); real upstream pinned from cropboth (5 stage tags not live, replayed where the rung called them); judged on the marking-only A/A floor 1.00; real latency excludes the replayed upstream |

Final against baseline at 2026 rates: $0.0000 vs $0.0000 per script

Final against baseline at 2027 rates: $0.0000 vs $0.0000 per script

Stop reason: Pinned screens complete; final stack confirmed fully live in claude-c-2026-10-26-live3
