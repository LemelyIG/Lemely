# Claude E2E cost run: CAIE 0625 Oct/Nov 2024 Paper 41 (one handwritten script)

Single script, two runs (image enhancement on and off), n=1 each. Every figure is one observation, not a distribution. Per-leaf marks are in `MARKS.md` (uncommitted); this file carries counts only.

## Manifest
- Code: branch `feat/cost-ladder`, SHA `84f78506`. Shipped defaults except the `lemely.toml` here (all model slots `claude-haiku-5-5`, `claude_files_api = true`, `correction_citations = true`, `correction_terse_rationale = true`, `binding.claude_chunked_read = true`, per-task cache plan and effort map as in the file). The only difference between the two runs is `claude_image_enhance` (true: dir `claude-e2e-0625-w24-41-2026-10-23`; false: dir `...-2026-10-23-plain`). cache_dir was fresh in both.
- Inputs: the same 19-page scan and the same mark scheme `0625_w24_ms_41.pdf` (80 marks, 43 marked leaves, no MCQ leaves).
- Doctor (enhanced run, `doctor.txt`): all Claude checks ok (`anthropic_api_key`, `claude_files_workspace`, `claude_price_rows`); `all_passed=false` only from `sources_dir_readable` and `push_transport`, both irrelevant here.
- Ledger: enhanced run delta $0.03227181 (anthropic 0.03550176 -> 0.06777357); plain run delta $0.03804705 (0.06777357 -> 0.10582062). Both equal the sum of that run's CallRecords exactly (checked). The Gemini ledger did not move. Prices recovered from the records by regression: input $0.10/M, cache read $0.01/M, 5 min cache write $0.125/M, output $0.50/M (repo table, not checked against an invoice).
- Driver `driver.py` in each dir (det-first mark scheme, extraction, correction in one process, as in the Gemini run).

## $ per paper against the $0.10 target
| Variant | Script (incl. scan metadata) | Excl. scan metadata | vs $0.10 | Gemini run |
|---|---|---|---|---|
| Enhanced | **$0.03227** | $0.03118 | 32% of target | $0.15801 (4.9x) |
| Plain | **$0.03805** | $0.03692 | 38% of target | $0.15801 (4.2x) |

Mark-scheme parse amortised over 30 scripts:
- Actual path: the deterministic parser accepted the scheme ($0, `ms_path` det, 1.6 s), so $0/30 = **$0.00000** per script. Per-paper figure is unchanged.
- Claude parse path: **could not be priced.** The Claude mark-scheme parse parity stage failed on the request: 400 `invalid_request_error` "output_config.format.schema: Invalid schema: Circular reference detected in schema definitions: Question -> Question". No model output, 0 records (`records_markscheme_claude.jsonl` is empty), $0 billed. So the amortised Claude parse cost is unknown, and Claude currently cannot parse a mark scheme through structured outputs at all (parity bug: the recursive `Question` schema is rejected). Any paper whose scheme the det parser rejects would have no Claude fallback today.

### By task tag (all `claude-haiku-5-5`)
| Task tag | Attempt | Effort | Calls (enh / plain) | Input (enh) | Cached (enh) | Cache write 5m (enh) | Output (enh) | $ enh | $ plain | Share enh | Share plain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| scan_metadata | none | low | 1 / 1 | 10,498 | 0 | 0 | 81 | 0.00109 | 0.00113 | 3.4% | 3.0% |
| extraction (first read) | none | low | 1 / 1 | 89,454 | 0 | 88,534 | 5,943 | 0.01413 | 0.01376 | 43.8% | 36.2% |
| binding_second_read | none | low | 1 / 1 | 89,454 | 88,534 | 0 | 185 | 0.00107 | 0.00440 | 3.3% | 11.6% |
| correction | first | low (medium for extended) | 34 / 37 | 514,101 | 486,816 | 14,752 | 11,229 | 0.01358 | 0.01393 | 42.1% | 36.6% |
| correction_borderline | borderline | high | 3 / 6 | 45,790 | 44,256 | 0 | 3,611 | 0.00240 | 0.00482 | 7.4% | 12.7% |
| **Total** | | | **40 / 46** | 749,293 | 619,606 | 103,286 | 21,049 | **0.03227** | **0.03805** | 100% | 100% |

- Cache-write detail, plain run: extraction wrote 84,114 and read 4,420 (a partial hit on an entry the enhanced run left); correction read 545,824 with no write. My inference, not verified: the correction prefix text is identical across the two runs and the plain correction started within the 5 min cache window of the enhanced one, so it read the enhanced run's entry. That would flatter the plain figure by one 14,752-token write, about $0.0018.
- Container seconds: 0 in every record (no code-execution container used). `thinking_tokens` 0 everywhere (haiku-5-5 at low effort reports none; borderline at high effort reports output only).
- Cost structure of the enhanced run: the 88,534-token image cache write is $0.01107, which is **78% of extraction and 34% of the whole script**; correction output tokens (11,229 at $0.50/M) are $0.0056, **41% of the correction first-attempt line**; cache reads of the 14.7k-token correction prefix are $0.0049 (36%). Extraction (first read) is 43.8% of the script; with the second read, image handling is 47.1%.
- Gemini beside it: correction $0.05981 (41 calls) vs Claude $0.01598 (34 + 3 borderline) = 3.7x cheaper; extraction + second read $0.09819 vs $0.01520 = 6.5x cheaper.

### Latency (wall clock)
| Phase | Enhanced | Plain | Gemini |
|---|---|---|---|
| Mark scheme (det) | 1.6 s | 1.5 s | 3.9 s |
| Scan metadata | 15.2 s | 10.4 s | not run |
| Extraction + binder | 106.8 s | 158.1 s | 241.3 s |
| Correction (sequential) | 109.2 s | 134.8 s | 84.5 s |
| Total | ~233 s | ~305 s | 329.7 s |

Claude correction is slower per call than Gemini flash-lite (median 2.5 s vs 1.9 s) and sequential; no retries in either run.

## Binding
Both runs: verdict **hold** (binder label, gate enforce, `claude-haiku-5-5`, second read consulted, `retried=true`, no extra call). `first_read_failed_checks` was empty in both: the first read alone passed; the hold comes from the second read plus unaligned labels. Gemini was also hold (G5, G9; 2 unbound).
| Run | Failed checks | Unbound leaves (marks available) | Unaligned | Reasons |
|---|---|---|---|---|
| Gemini | G5 (2 leaves, neighbour_left_blank), G9 (5 leaves, answered in one read, blank in the other) | 2 (6) | not logged | neighbour_left_blank |
| Claude enhanced | G5 (7 of 43 leaves), G9 (2 leaves) | 9 (16) | 9 | writing_uncertain 7, unaligned_in_other_read 2 |
| Claude plain | G5 (6 of 43 leaves), G9 (1 leaf) | 7 (8) incl. 1 placed-by-position | 6 | writing_uncertain 6 |
- Six leaves (Q9: 9a to 9c_iv, all on page 18) are `writing_uncertain` in **both** Claude runs, while Gemini bound all six on page 18. In both runs the extractor did read writing on page 18 (6 unbound answers placed "uncertain", confidences 0.6 to 0.85), so for Q9 the problem is label alignment, not reading.
- Gemini's hold shows the same class of problem (7b_ii, 7c unbound), so binding on this scan is hard for every model tried; Claude's is worse on this page (see MARKS.md).
- **Chunked read did not fire** (`binding_chunked_read` 0): 19 pages fit in one request at 2200 px (est. 86,621 tokens at preflight).
- **Files API**: configured on (`claude_files_api=true`), no `claude_files_api_fallback`, no `claude_upload_retry`, no `claude_file_delete_failed` event. Upload and delete success are silent in the logs, so there is no positive log line; the only positive evidence is indirect (88,534-token image cache write served by file ids, doctor reporting the config). I could not confirm file ids from the logs alone and did not list the workspace.

## Marks (counts only; per-leaf table in MARKS.md)
| | Gemini | Claude enhanced | Claude plain |
|---|---|---|---|
| Awarded / 80 | 58 | 46 | 48 |
| Unbound / dropped leaves | 2 | 9 | 6 |
| Flagged `needs_teacher_review` (of 43) | 9 | 24 | 24 |
| Flagged `uncited_mark` | 0 | 1 | 2 |
| Blank leaves (marker_source=blank) | 0 | 0 | 0 |
| Mean extraction confidence | 0.96 | 0.80 | 0.79 |

- Leaves differing from Gemini: enhanced 13, plain 13; enhanced vs plain 3.
- Decomposition of the gap: enhanced -12 = **-11** from 7 leaves Claude dropped as unbound but Gemini marked, **+2** from one leaf (7b_ii) Gemini dropped and Claude marked, **-3** from 5 leaves both read and marked differently (2a_iii +1; 2c, 4a, 5d, 7b_i -1 each). Plain -10 = -7 (5 dropped leaves) +2 (7b_ii) -5 (7 leaves marked differently).
- So the gap is mainly a binding/reading failure, not a marking one: dropped leaves cost 11 marks (offset by +2 for 7b_ii), while marking differences on leaves both models read cost only 3. On the 33 leaves both models bound, Claude enhanced awarded 44 against Gemini's 47 (28 of 33 identical); plain 46 against 51 on 35 leaves (28 of 35 identical). Claude marks slightly lower on bound leaves. No ground truth exists for this script, so neither side is known to be right.
- Review rate: 24 of 43 flagged (9 under Gemini). 13 of the 24 are only "confidence below 0.90"; Claude's confidences cluster at 0.6 to 0.85. A threshold calibrated on Gemini flags over half the paper for a Claude run.
- Neither paper is publishable (both hold).

## Events
| Event | Enhanced | Plain |
|---|---|---|
| claude_over_tier | 0 | 0 |
| script_over_cost_target | 0 | 0 |
| claude_token_preflight | 2 | 2 |
| claude_files_api_fallback | 0 | 0 |
| binding_chunked_read | 0 | 0 |
| retries / 429 / 5xx / parse failures | 0 | 0 |
Other: `held_paper_reads_forgotten` forgotten=0, `marking_flags` all false. `counted_tokens` was null in the preflight events (estimate 86,621 used, actual 89,454 input incl. cache write: the estimate under-counts by 3%).

## Findings requested by the plan
- **T9 (blank-leaf skip)**: already present (US-039, `marker_source="blank"`); nothing to add. This script exercised 0 blank leaves in all three runs, so the path was not run here.
- **Step 2 (effort and cache)** (`effort_cache_probe.json`): a different effort between two reads still read the cache. Extraction at low wrote 11,692 tokens; the second read at medium read 11,692 and wrote 0 ($0.000265 vs $0.000130 at equal effort; the gap is output, not cache). This contradicts the docs reading used in Task 6, so the effort-equality requirement in `_reads_share_a_claude_cache` is stricter than needed. The real runs also show it: borderline calls at high effort read the correction prefix cache (44,256 cached over 3 calls = 14,752 each) with 0 writes.
- **Data exposure (Task 2c)**: with `claude_files_api` on, page images of the scan are uploaded to the Anthropic Files API (1 h expiry, deleted at job end, not ZDR-eligible). A standard key cannot report its workspace; doctor can only ask the operator to confirm the key belongs to the dedicated Lemely workspace. This run used the existing key; I did not verify which workspace it belongs to. The scan is a real student script, so this is a real exposure for these two runs.

## Red flags
1. Claude mark-scheme parse is broken (400 circular `Question -> Question` schema). Parity bug; blocks any Claude-only mark-scheme path.
2. Enhanced run's second read returned 185 output tokens in 2.9 s, against 5,943 for its first read and 6,854 for the plain run's second read. It looks near-empty rather than a real second read; its agreement or disagreement signal (G9 on 2a_i and 8a) should not be trusted. The extraction response is not in the cache dir, so I could not inspect it. Worth a targeted check before reading anything into enhanced-vs-plain.
3. Cache-write cost dominates a cold run: $0.011 for one image prefix. If the second read ever missed (TTL, order), the script cost goes up by about $0.0086.
4. Plain run correction benefited from a cross-run cache hit (see above), about $0.0018.

## Opportunities for sub-project C (numbers from this run)
1. **One correction call per question.** 34 calls re-send a ~14.7k-token prefix; cache makes that cheap (reads $0.0049 plus one $0.0018 write, together 49% of the $0.0136 correction line) but not free. Output is the bigger part ($0.0056, 41%); median 310 output tokens per call, max 1,850. Options: group the leaves of a question (or a page) into one call to cut the prefix reads, or shorten output further. Upper bound on saving from prefix reads is about $0.005 per paper (15%), at the price of losing per-leaf isolation.
2. **Sonnet adjudication on disagreements.** Headroom is $0.068 per paper at the enhanced figure. Candidate disagreement set: leaves with Haiku borderline calls (3 enhanced, 6 plain) or leaves where the two Claude runs differ (3) or where Claude differs from Gemini on bound leaves (5 to 7). Sonnet price is not in my data; as a labelled assumption of 10x the Haiku per-call cost (about $0.004 per leaf), 6 leaves cost about $0.024, inside the budget. Not measured.
3. **`uncited_mark` as an escalation trigger.** It fired on 1 (enhanced: 7b_i) and 2 (plain: 1c_ii, 8a) leaves. Two of those three leaves (7b_i, 8a) are leaves where Claude is 1 mark under Gemini; n is far too small to call it a signal, but it is cheap (3 of 43 leaves) and worth testing on a larger set.
4. **Scan metadata cost.** One call, 10,498 input tokens, $0.00109 (enhanced) to $0.00113 (plain), 3.0 to 3.4% of the script and 10 to 15 s of wall clock; it re-sends no cache. Candidates: derive from the filename or first page crop, or run once per class.
5. **Extraction is 44% of the cost (enhanced), 47% with the second read.** 88.5k image tokens at 19 pages is about 4.7k per page; the cache write alone is $0.011. Cutting resolution below 2200 px, dropping blank or cover pages, or confirming blank pages before upload would scale this directly. Not tested.
6. **Per-provider review threshold.** 24 of 43 leaves are flagged on Claude against 9 on Gemini, 13 purely from the 0.90 confidence cut; calibrate the threshold (or the confidence prompt) per provider before relying on the review queue.
7. **Binding on page 18 (Q9)** costs 7 marks in both Claude runs and is the largest single lever on the gap; candidates are a targeted page-18 re-read or letting the label binder use the position-placed answers (6 unbound answers on that page had writing read).
8. **Relax the effort-equality cache check** (Step 2 finding): lets the second read run at a different effort without losing the cache.
9. **Borderline policy.** 3 vs 6 high-effort calls cost $0.0024 vs $0.0048 (7 to 13% of the script) for a handful of changed marks; measure whether borderline changes any mark before keeping it as is.

## Files
`lemely.toml`, `driver.py`, `run.log`, `events.jsonl`, `records.jsonl` (+ `records_*.jsonl`), `script_costs.json`, `timing.json`, `extracted.json`, `correction.json`, `mark_scheme.json`, `ledger_before.json`, `ledger_after.json`, `doctor.txt`, `effort_cache_probe.json` here; the plain run's equivalents in `claude-e2e-0625-w24-41-2026-10-23-plain/`. `extracted.json`, `correction.json`, `records*.jsonl`, `events.jsonl`, `MARKS.md`, `cache/`, `outputs/` hold or can hold student data and stay uncommitted.
