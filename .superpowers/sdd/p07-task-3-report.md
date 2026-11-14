# Phase 07 Task 3 Part B report: persist per-model LLM cost at settle

## What changed
- `lemely/db/usage_model_costs_repo.py` (new): `record_job_model_costs(session, *, job_id, totals) -> int`.
  Looks up `UsageJob.id` by `UsageJob.job_id`, merges names truncated to 128 chars, upserts on
  `(usage_job_id, model)` adding cost. Raises `LookupError` for an unknown job; empty totals write nothing.
- `lemely/web/usage.py`: `MeteredJob.run` enters `cost_scope()` and `model_cost_scope()` through one
  `ExitStack`; the totals are read at exit and passed `_exit -> _end -> _finish` as `model_totals`.
  `_finish` calls the new `_record_model_costs` only when `ledger.settle` returned `settled`, inside
  the settle transaction, in `session.begin_nested()`, with `self.job_id` read at settle time. Any exception logs
  `usage_model_cost_unrecorded` (`alert=True`, `job_id`, `error_type`) and the settle commits.
  Releases, closed-job refusals and unreserved runs never reach it. `record_llm_cost` untouched; no hook added.
- `tests/test_usage_model_costs.py`: 8 DB tests added (26 in the file).

## Tests (PYTHONPATH pinned to the worktree)
- `pytest --no-cov -o addopts="" tests/test_usage_model_costs.py tests/test_gemini_cost_record.py tests/test_web_usage_meter.py tests/test_web_usage_hold_lease.py tests/test_usage_route_coverage.py tests/test_metered_actions.py tests/architecture`: 183 passed in 244.87s.
- `tests/test_usage_model_costs.py` alone: 26 passed.

## Red proofs (each mutation reverted afterwards)
1. Feed moved outside the `try` in `GeminiClient._record_spend` (Part A guard): `test_a_refused_price_skips_both_feeds_without_failing_the_call[nan]` and `[negative]` failed (UnboundLocalError at gemini.py:2228).
2. Persist with the reserve-time id: `test_a_job_reserved_again_under_a_new_id_writes_rows_on_the_final_id` failed.
3. `begin_nested()` removed: `test_a_failure_persisting_the_split_leaves_the_job_settled_and_alerts` failed. That test drives a real check-constraint violation (negative cost) because a plain Python raise would not abort the transaction and would not prove the savepoint.

## Pre-commit
ruff, ruff format, whitespace, import-linter passed. pyright: 0 errors in my three files (repo-wide count 94 vs the known 93; none in my files). mypy hook fails on `lemely/web/routers/paymob_webhooks.py:173` (another lane's uncommitted file); `mypy` on my three files is clean.

## Deviations
- Guard 1 belongs to Part A; proved here because the brief lists it.
- The post-settle hook runs first, then the split is stored; both in the settle transaction.
