# Cost ladder

Baseline in-run cache hits: 10 (calls replayed within rung 0 itself; their cost is not in its total). Cache entries written: 83; cacheable live records: 83.

| lever | stacked on | overrides | expected saving | measured saving (2027) | extra mismarks / allowed | id-match | p95 latency | validity | proof | verdict | reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 second-read thinking medium->low | baseline | gemini.thinking_level_for={'binding_second_read': 'low', 'correction': 'low', 'correction_borderline': 'high', 'escalation': 'high', 'extraction': 'minimal', 'generation': 'low'} | 0.40 | 36.4% | 0 / 2 | 1.000 | 409009 ms | 0.989 | /home/sico/Code/Lemely/BUILD/accuracy-runs/cost-ladder-2026-10-19/b1-second-read-low | ACCEPT | - |
| B12 binder output cap 16384 | b1-second-read-low | gemini.max_output_tokens_for={'binding_second_read': 16384, 'extraction': 16384}; gemini.thinking_level_for={'binding_second_read': 'low', 'correction': 'low', 'correction_borderline': 'high', 'escalation': 'high', 'extraction': 'minimal', 'generation': 'low'} | 0.05 | 39.4% | 0 / 2 | 1.000 | 57260 ms | 1.000 | /home/sico/Code/Lemely/BUILD/accuracy-runs/cost-ladder-2026-10-19/b12-binder-output-cap | ACCEPT | - |
| A1 correction model gemini-3.1-flash-lite | b12-binder-output-cap | gemini.correction_model=gemini-3.1-flash-lite; gemini.max_output_tokens_for={'binding_second_read': 16384, 'extraction': 16384}; gemini.thinking_level_for={'binding_second_read': 'low', 'correction': 'low', 'correction_borderline': 'high', 'escalation': 'high', 'extraction': 'minimal', 'generation': 'low'} | 0.40 | 50.5% | 0 / 2 | 1.000 | 58463 ms | 1.000 | /home/sico/Code/Lemely/BUILD/accuracy-runs/cost-ladder-2026-10-19/a1-flash-lite | ACCEPT | - |
| A1 correction model claude-haiku-5-5 | b12-binder-output-cap | gemini.correction_model=claude-haiku-5-5; gemini.max_output_tokens_for={'binding_second_read': 16384, 'extraction': 16384}; gemini.thinking_level_for={'binding_second_read': 'low', 'correction': 'low', 'correction_borderline': 'high', 'escalation': 'high', 'extraction': 'minimal', 'generation': 'low'} | 0.40 | 54.1% | 0 / 2 | 1.000 | 67568 ms | 1.000 | /home/sico/Code/Lemely/BUILD/accuracy-runs/cost-ladder-2026-10-19/a1-haiku | ACCEPT | - |

Final against baseline at 2026 rates: $0.0155 vs $0.0792 per script (80.4% saved)

Final against baseline at 2027 rates: $0.0280 vs $0.1582 per script (82.3% saved)

Stop reason: Phase A gate met: shipped B1 + B12 + A1 (claude-haiku-5-5) cut $/script by >=50% from the rung-0 baseline, so Phase B is skipped. B2 built but shelved by user (unmeasurable swapped-label risk, <=12% saving after B1). A1 alternative gemini-3.1-flash-lite also passed; user chose Haiku.
