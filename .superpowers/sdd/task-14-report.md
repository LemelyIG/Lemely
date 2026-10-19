# Task 14 (B12 per-tag output-token cap) report

Commit 5dd7ac39 on feat/cost-ladder (signed, path-scoped).

Files: lemely/io/gemini.py, lemely/runtime/config.py, lemely/runtime/example_toml.py, lemely.toml.example (regenerated via `python -m lemely.runtime.example_toml`), tests/test_gemini_output_cap.py (new), tests/test_cost_ladder_settings.py (defaults + key list).

Setting: `GeminiSettings.max_output_tokens_for: dict[str, int>0] = {}`. `GeminiClient._output_cap(tag)` returns override or `_MAX_OUTPUT_TOKENS`. Used in the request config and `_params_fingerprint` (Gemini models only; claude- keeps the adapter cap, fingerprint unchanged). Empty map: identical requests and keys (test_gemini_cache_keys_unchanged, test_cascade_off_is_byte_identical green unmodified).

Thinking vs cap: thinking tokens DO count. https://ai.google.dev/gemini-api/docs/thinking : "sets the maximum number of tokens a response can generate, including thought tokens"; if the limit is hit while reasoning it stops and returns truncated or empty output. Recorded in the `_output_cap` docstring.

Truncation handling: before, finish MAX_TOKENS raised `_TransientError`, so tenacity retried up to max_retries+1 (4) full-price calls at the same cap. Now, when a per-tag cap is in force: spend is recorded (billed), `_mark_last_record_unparsed()` sets parse_ok=False, and `ExternalServiceError` ("hit the N-token output cap for <tag>") is raised, not retried, and it bypasses the schema-correction retry. With the default cap (no per-tag entry) the old retry behaviour is kept deliberately (global rule: default reproduces today); a test pins it.

What happens next: first read (tag `extraction`, "|bind1"): `_read_both` re-raises a first-read error, so the paper job fails with ExternalServiceError (fast and cheap, but no fallback; the second read does not take over). Second read (tag `binding_second_read`): error is logged, its cache entry forgotten, and it is re-run once on the calling thread under the same cap; if that truncates too the job fails.

Tests (real): 209 passed, 23 subtests passed (the 8 listed files); tests/architecture passed; pre-commit all hooks pass (ruff-format reformatted once, rerun clean).

Concerns: capping `extraction` makes a runaway first read fail the whole paper rather than degrade; pick the cap well above the legit p99 output (incl. thinking). A cap on `extraction` also changes that tag's cache keys (fresh calls, no stale hits). lemely/accuracy/harness.py has its own `_MAX_OUTPUT_TOKENS` in the manifest fingerprint, not made per-tag-aware (out of scope).

## Fix round 1 (NEEDS_CONTEXT, no code change)

The controller's premise does not hold in the code. A first read whose reply fails to parse is NOT recovered by the second read: `generate_structured` makes one schema-correction call, and if that fails raises `ParseError`; `_read_both` then does `if first_error is not None: raise first_error`, and `run_binding` forgets the cached reads and re-raises. tests/test_extraction_binding.py::test_a_failed_first_read_fails_the_paper_as_extraction_always_has pins this. The baseline "recovery" of the 65,522-token read was most likely the schema-correction retry (a second call on the same read) or a gate-level pass, not a second-read takeover. Only a failing SECOND read is retried once (`_read_both`).

So a truncation that raises ParseError (the parse-failure type) still fails the paper on a first read. Making a first-read truncation flow into the second read needs a change in lemely/io/binding/orchestrate.py `_read_both` (treat a first-read truncation error as recoverable by the second read), which is outside my files. Current committed behaviour (5dd7ac39) is unchanged.

## Fix round 2 (option c, gemini.py only)

Under a per-tag cap a MAX_TOKENS reply is billed and recorded parse_ok=False (raised as `_CapTruncatedError`, an ExternalServiceError subclass). `_call_with_retry` then runs `_check_cost_ceiling()` and makes exactly one fresh generation of the same request at the same cap (not a schema-correction call). The retry runs inside the caller's `_call_labelled` context, so its CallRecord carries the same attempt/question_id. A second truncation raises ExternalServiceError with both calls billed. Default cap (no per-tag entry) is unchanged. orchestrate.py untouched: a double truncation on a first read still fails the paper; the cap just makes a runaway cost at most 2 capped calls.
