# Claude E2E cost and accuracy after the binding fixes: CAIE 0625 Oct/Nov 2024 Paper 41 (one handwritten script)

One script, four live runs (enhanced images x2, plain x2). n=2 per variant, n=1 script: every figure is an observation, not a distribution. Per-leaf marks are in `MARKS.md` beside this file (uncommitted); this file carries counts only. No ground truth exists for this script, so "agrees with Gemini" never means "correct".

## Manifest
- Code: branch `feat/cost-ladder`, SHA `84c78c51` (binding fixes F1 page labels, F2 one-based re-index, F3 stub -> retry -> hold `stub_read`, F4 Claude binder output cap 32,768, F5 no token count when images are file ids; plus the mark-scheme prompt-JSON route, so the Claude mark-scheme parse now runs). The first Claude runs were at `84f78506`; the Gemini baseline at `01f371c3`.
- Config (`lemely.toml` in each dir): all model slots `claude-haiku-5-5`, `claude_files_api = true`, `correction_citations = true`, `correction_terse_rationale = true`, `binding.claude_chunked_read = true`, per-task cache plan and effort map as in the first Claude runs. The only difference between enh and plain is `claude_image_enhance`. User chose enhanced as the default.
- Dirs: `claude-e2e2-0625-w24-41-enh1` (this one), `-enh2`, `-plain1`, `-plain2`. Run order enh1, plain1, enh2, plain2, one after another, same day, fresh `cache_dir` each, but all share one Anthropic prompt cache (see "Cache warmth" below).
- Inputs: the same 19-page scan and mark scheme `0625_w24_ms_41.pdf` (80 marks, 43 marked leaves, no MCQ leaves). The deterministic parser accepted the scheme in every run (`ms_path` det, $0); the Claude parse ran as a parity stage and is priced separately below.
- Ledger: per-run anthropic delta = script cost + Claude mark-scheme parse, equal to the sum of that run's CallRecords (checked): enh1 $0.068122, enh2 $0.052882, plain1 $0.060871, plain2 $0.057398. The Gemini ledger did not move.
- Prices (repo table, not checked against an invoice; haiku-5-5): input $0.10/M, cache read $0.01/M, 5 min cache write $0.125/M, output $0.50/M. Input tokens as logged include cached and cache-written tokens. Output tokens include thinking tokens (recomputed: enh1 extraction 920 uncached input + 88,667 written + 11,333 output = $0.016842, matches the record).
- Binder reads and Files API: events show no `claude_files_api_fallback`, `claude_upload_retry` or `claude_file_delete_failed`; page images of a real student scan went through the Files API in all four runs (same data-exposure note as the first runs; workspace not verified).

## $ per paper against the $0.10 target
Script = scan metadata + extraction + second read + correction (+ borderline), the figure in `script_costs.json`.

| Run | Script $ | Excl. scan metadata | % of $0.10 | Claude mark-scheme parse (not in script) | Gemini run |
|---|---|---|---|---|---|
| enh1 | **0.04900** | 0.04791 | 49.0% | 0.01912 (2 calls, first `parse_ok=False`) | 0.15801 (3.2x) |
| enh2 | **0.04006** | 0.03897 | 40.1% | 0.01282 (1 call) | 0.15801 (3.9x) |
| **Enhanced mean** | **0.04453** | 0.04344 | **44.5%** | 0.01597 | 3.5x cheaper |
| plain1 | 0.04848 | 0.04739 | 48.5% | 0.01239 | |
| plain2 | 0.04546 | 0.04436 | 45.5% | 0.01194 | |
| Plain mean | 0.04697 | 0.04588 | 47.0% | 0.01217 | |
| First Claude run, enhanced (before fixes) | 0.03227 | 0.03118 | 32.3% | failed (400, circular schema) | |

Amortised Claude mark-scheme parse over 30 scripts: enhanced mean $0.01597 / 30 = **$0.00053** per script; across all four runs $0.01107 to $0.01912 per parse = $0.00040 to $0.00064 per script. So enhanced mean with the Claude parse amortised is **$0.04506** per paper (45.1% of target). The actual path stays $0 because the deterministic parser accepts the scheme; the Claude figure matters only for schemes it rejects. Whether the Claude parse is accurate was not assessed here (the downstream run used the det parse). enh1's first parse returned `parse_ok=False` (8,217 output tokens, 0 thinking) and was retried; cause not diagnosed, the failed call cost $0.00986 of that run's parse.

Cache warmth: only enh1 wrote the correction prefix cache (14,752 tokens, $0.00184); enh2, plain1 and plain2 read an entry left by an earlier run within the 5 minute window. Extraction image writes were cold in all four (plain2 got a 4,420-token partial hit). Cold-corrected enh2 would be $0.04190, enhanced mean **$0.04545**. Either way the enhanced mean is 45% of target, about 3.5x under the Gemini run.

### By task tag, enhanced runs (all `claude-haiku-5-5`)
enh1:

| Task tag | Calls | Input | Cached read | Cache write 5m | Output (incl. thinking) | of which thinking | $ | Share |
|---|---|---|---|---|---|---|---|---|
| scan_metadata | 1 | 10,512 | 0 | 0 | 81 | 0 | 0.00109 | 2.2% |
| extraction | 1 | 89,587 | 0 | 88,667 | 11,333 | 5,069 | 0.01684 | 34.4% |
| binding_second_read | 1 | 89,587 | 88,667 | 0 | 19,365 | 12,808 | 0.01066 | 21.8% |
| correction | 42 | 635,085 | 604,832 | 14,752 | 15,254 | 2,713 | 0.01707 | 34.8% |
| correction_borderline | 3 | 45,705 | 44,256 | 0 | 5,496 | 4,536 | 0.00334 | 6.8% |
| **Total** | **48** | 870,476 | 737,755 | 103,419 | 51,529 | 25,126 | **0.04900** | 100% |

enh2:

| Task tag | Calls | Input | Cached read | Cache write 5m | Output (incl. thinking) | of which thinking | $ | Share |
|---|---|---|---|---|---|---|---|---|
| scan_metadata | 1 | 10,512 | 0 | 0 | 81 | 0 | 0.00109 | 2.7% |
| extraction | 1 | 89,587 | 0 | 88,667 | 12,397 | 5,837 | 0.01737 | 43.4% |
| binding_second_read | 1 | 89,587 | 88,667 | 0 | 6,029 | 0 | 0.00399 | 10.0% |
| correction | 42 | 634,967 | 619,584 | 0 | 14,619 | 2,098 | 0.01504 | 37.6% |
| correction_borderline | 3 | 45,667 | 44,256 | 0 | 3,952 | 2,767 | 0.00256 | 6.4% |
| **Total** | **48** | 870,320 | 752,507 | 88,667 | 37,078 | 10,702 | **0.04006** | 100% |

Dollars by tag, all runs:

| Task tag | enh1 | enh2 | plain1 | plain2 | First Claude enh |
|---|---|---|---|---|---|
| scan_metadata | 0.00109 | 0.00109 | 0.00109 | 0.00109 | 0.00109 |
| extraction | 0.01684 | 0.01737 | 0.01733 | 0.01728 | 0.01413 |
| binding_second_read | 0.01066 | 0.00399 | 0.01049 | 0.00409 | 0.00107 |
| correction | 0.01707 | 0.01504 | 0.01569 | 0.01582 | 0.01358 |
| correction_borderline | 0.00334 | 0.00256 | 0.00388 | 0.00717 | 0.00240 |
| **Script** | **0.04900** | **0.04006** | **0.04848** | **0.04546** | **0.03227** |

Cost structure (enh runs): the 88,667-token extraction image cache write is $0.01108, 22.6% (enh1) to 27.7% (enh2) of the script. Correction (42 calls) is prefix cache reads $0.0060 to $0.0062 (14,752 tokens x 42 at $0.01/M), output $0.0073 to $0.0076, uncached input $0.0015. Thinking tokens total 25,126 (enh1, $0.0126, 25.6% of the script) and 10,702 (enh2, $0.0054, 13.4%).
Container seconds 0 everywhere. No code execution.

## Where cost went up against the first Claude run (enhanced, $0.03227)
enh1 +$0.01673, enh2 +$0.00779. By tag:
- **Second read completing: +$0.0029 (enh2) to +$0.0096 (enh1).** The first run's second read returned 185 output tokens (a near-empty read, flagged then as suspect). The fixed pipeline's second reads are real: 6,029 output tokens in enh2 and plain2, 19,365 and 19,019 in enh1 and plain1. In those two the model also spent 12,808 and 12,410 thinking tokens ($0.0064 and $0.0062, about 60% of the read's cost, 13% of the script) while the other two reported 0 thinking. The same read at the same effort setting is bimodal: 2 of 4 runs thought for about 12.5k tokens, 2 of 4 did not.
- **Extraction: +$0.0027 (enh1) to +$0.0032 (enh2).** Output rose from 5,943 to 11,333 and 12,397 tokens, of which 5,069 and 5,837 are now reported as thinking (the first run reported none). The same pass now returns 42 answers where the first run returned 34. The image cache write is unchanged (88.5k to 88.7k tokens; input rose by 133 tokens, consistent with the F1 page-index labels).
- **Correction: +$0.0015 (enh2) to +$0.0035 (enh1).** 42 first-attempt calls instead of 34, because eight leaves that were dropped as unbound are now bound and marked. enh1 also paid the one cold prefix write ($0.0018).
- **Borderline: +$0.0002 to +$0.0009**, 3 calls as before, higher thinking per call (1.5k to 1.8k).
- Scan metadata: unchanged, $0.00109.

F4 (the 32,768 cap) paid for itself: two second reads (19,365 and 19,019 output tokens) exceed the old 16,384 cap, so on the old cap they would have been truncated. No `gemini_cap_truncated_retry` fired, so none needed a retry.

## Comparison: Gemini vs Claude before fixes vs Claude after fixes
| | Gemini | Claude before (enh / plain) | Claude after enh1 | enh2 | plain1 | plain2 |
|---|---|---|---|---|---|---|
| Script $ | 0.15801 | 0.03227 / 0.03805 | 0.04900 | 0.04006 | 0.04848 | 0.04546 |
| Awarded / 80 | 58 | 46 / 48 | 60 | 60 | 58 | 61 |
| Binding verdict | hold | hold / hold | pass | pass | pass | pass |
| Failed gate checks | G5 (2 leaves), G9 (5) | G5 (7), G9 (2) / G5 (6), G9 (1) | G5 (3), G9 (1) | none | none | G9 (1) |
| Unbound leaves (marks available) | 2 (6) | 9 (16) / 6 (8) | 1 (3) | 0 | 0 | 0 |
| Leaves not marked (dropped or blank) | 2 | 9 / 6 | 1 (dropped) | 1 (blank) | 1 (blank) | 1 (blank) |
| Unbound answers (writing with no leaf) | 6 | 9 / 7 | 2 | 4 | 5 | 3 |
| Leaves flagged `needs_teacher_review` (of 43) | 9 | 24 / 24 | 18 | 13 | 18 | 19 |
| of which confidence-only | 0 | 13 / 13 | 10 | 8 | 11 | 12 |
| of which binding unverified | 9 | 9 / 8 | 5 | 4 | 4 | 4 |
| Flagged `uncited_mark` | 0 | 1 / 2 | 4 | 1 | 2 | 2 |
| Mean extraction confidence (marked leaves) | 0.96 | 0.80 / 0.79 | 0.86 | 0.84 | 0.84 | 0.84 |

- The hold verdict is gone in all four runs. enh1 still lists G5 and G9 as failed checks but the verdict is `pass` (the gate is rate-based; I did not re-derive that threshold here). Paper-level `needs_teacher_review` is true in enh1 and was not examined for the others.
- 7c (3 marks) is the one leaf not marked everywhere: dropped as `label_not_seen` in enh1, blank (both reads empty) in the other three, dropped in Gemini. 7b_ii, which Gemini dropped, is bound and marked in all four new runs.
- Total review rate fell from 24 of 43 (56%) to 13 to 19 (30% to 44%), still above Gemini's 9 (21%). Confidence-only flags are 8 to 12 of the 13 to 19.
- `uncited_mark` went from 1 to 2 leaves (first runs) to 1 to 4 per run (4 / 1 / 2 / 2). Leaf 4a carries it in 3 of 4 runs and 8a in 2 of 4; 3a, 6a, 9b and 9c_iv once each. Too few to call a signal.
- No parse failures on the script path (all `parse_ok` true); no truncation, no 429/5xx.

## Agreement with Gemini, per leaf (counts; table in `MARKS.md`)
43 leaves. "Differ by" is in marks.

| Run | Identical | Differ | by 1 | by 2 | Sum abs | Net (Claude - Gemini) |
|---|---|---|---|---|---|---|
| enh1 | 36 | 7 | 6 | 1 | 8 | +2 |
| enh2 | 35 | 8 | 6 | 2 | 10 | +2 |
| plain1 | 36 | 7 | 6 | 1 | 8 | 0 |
| plain2 | 37 | 6 | 3 | 3 | 9 | +3 |
| Claude-first enh (before fixes) | 30 | 13 | 9 | 4 | 18 | -12 |
| Claude-first plain | 30 | 13 | 10 | 3 | 16 | -10 |

- The +2 in enh1 and enh2 is one leaf: 7b_ii, which Gemini left unbound (0 awarded) and Claude marks 2 in all four runs. On the 41 leaves both models marked, enh1 and enh2 are identical on 35 and 34 (marks 58 against 58 in both); plain1 35 (56 against 58); plain2 36 (59 against 58). The old gap (Claude 12 marks low, dominated by 11 marks on dropped leaves) is closed: the remaining disagreement is spread, small, and not one-directional.
- 10 leaves differ from Gemini in at least one of the four runs. Three leaves differ from Gemini in all four runs and in the same direction in every run but one: 2a_i (Claude +1 of 2), 5d (Claude 0 against 1 of 4), 7b_i (Claude 2, 2, 2, 1 against 3 of 3). Their confidence is 0.60 to 0.93 (5d and 7b_i 0.60 to 0.80). This is a stable model difference, not run noise, and a good set to hand to a human or a stronger model.
- Seven leaves are unstable across the four Claude runs themselves: 2a_iii, 2c, 4b_i, 5c_i, 6c_ii, 7b_i, 8a.

## Run-to-run variance
| Pair | Script $ | Marks | Leaves that differ | Sum abs |
|---|---|---|---|---|
| enh1 vs enh2 | 0.04900 vs 0.04006 (-18%) | 60 vs 60 | 2 (2a_iii, 8a; 1 mark each, opposite signs) | 2 |
| plain1 vs plain2 | 0.04848 vs 0.04546 (-6%) | 58 vs 61 | 6 (2a_iii, 2c, 5c_i, 6c_ii, 7b_i, 8a) | 7 |
| enh1 vs plain1 | | 60 vs 58 | 2 (2c, 4b_i) | 2 |
| enh2 vs plain2 | | 60 vs 61 | 5 | 7 |

- Cost variance is almost all the second read's thinking (see above): the $0.0089 gap between enh1 and enh2 is $0.0067 of second-read cost, $0.0019 cold cache write, and the rest noise.
- Mark variance within a variant (2 to 6 leaves, 2 to 7 marks) is as large as the difference between variants (2 to 5 leaves). With n=2 there is no detectable effect of image enhancement on marks or on cost (enh mean $0.0445 against plain $0.0470, a gap smaller than the within-variant spread). The choice of enhanced stands on the first-run evidence, not on these four.

## Events (per run: enh1 / enh2 / plain1 / plain2)
| Event | Count |
|---|---|
| `binding_read_reindexed` (F2) | 0 / 0 / 0 / 0 |
| `binding_read_stub` and `binding_read_stub_again` (F3) | 0 / 0 / 0 / 0 |
| `gemini_cap_truncated_retry` (cap retries) | 0 / 0 / 0 / 0 |
| `claude_token_preflight` (reason `file_sources`, `counted_tokens=None`; F5) | 2 / 2 / 2 / 2 |
| `claude_over_tier` | 0 / 0 / 0 / 0 |
| over-target (`script_over_cost_target`; never emitted, max script $0.049) | 0 / 0 / 0 / 0 |
| `claude_files_api_fallback`, `claude_upload_retry`, `claude_file_delete_failed` | 0 |
| `binding_gate_result` | 1 each, `retried=False`, `second_read=True` |
| `marking_flags` | 1 each |
| `gemini_call` records | 50 / 49 / 50 / 51 (includes 1 or 2 mark-scheme parse calls) |

None of the new fix paths fired. Zero reindex events across 8 binder reads (4 first, 4 second) is consistent with F1's page labels having removed the one-based numbering (the investigation saw 3 of 22 reads numbered that way), but n=8 does not prove it. Zero stub events: no read was short. F5 behaved as specified (file ids in use, no `count_tokens` 400, estimate 86,621 against actual 89,587 input, a 3.3% under-estimate).

## Latency (wall clock per stage, seconds)
| Stage | enh1 | enh2 | plain1 | plain2 | First Claude enh | Gemini |
|---|---|---|---|---|---|---|
| Mark scheme (det) | 1.0 | 4.5 | 1.5 | 1.3 | 1.6 | 3.9 |
| Scan metadata (call 4 to 7 s) | 72.2 | 62.1 | 55.7 | 57.5 | 15.2 | not run |
| Extraction + binder (first read, second read, prep) | 224.9 (49.4 + 82.0 + 93.5) | 170.5 (54.0 + 22.2 + 94.3) | 204.3 (51.6 + 80.9 + 71.8) | 158.7 (57.6 + 23.4 + 77.7) | 106.8 | 241.3 |
| Correction (45 sequential calls, median 2.4 s) | 143.6 | 133.7 | 145.4 | 180.3 | 109.2 | 84.5 |
| **Total (excludes the Claude parity parse, 50 to 60 s)** | **441.8** | **370.8** | **406.8** | **397.8** | ~233 | 329.7 |

- The two reads run one after the other (the second must hit the first's cache), so a thinking second read adds about 60 s (82 s against 22 s).
- About 72 to 94 s of the extraction stage and 51 to 66 s of the scan-metadata stage is not model time: no call is logged. The first Claude run spent 15 s on scan metadata, so this is new; cause not diagnosed (page-index labels are text blocks and cannot cost that much; machine load or image preparation are untested guesses).
- Correction is sequential (45 calls, median 2.4 s each); plain2's 180 s includes one 23.4 s borderline call. No retries.

## Remaining gaps
1. **Review queue is 1.4x to 2.1x Gemini's** (13 to 19 against 9 of 43), 8 to 12 of them from confidence below 0.90 alone. 6 to 14 of the flagged leaves per run give marks identical to Gemini's.
2. **Three leaves are a stable Claude/Gemini disagreement** (2a_i, 5d, 7b_i) and seven are unstable within Claude; with no ground truth we do not know which side is right.
3. **Unbound writing remains**: 2 to 5 answers per run are read but placed `uncertain` or `position` with no leaf (Gemini: 6).
4. **7c** is marked in none of the five runs; whether the student wrote anything there is unknown (3 marks).
5. **Latency 371 to 442 s** against 233 s before and 330 s for Gemini; 150 s or more is unexplained preparation time.
6. Cost is not yet an issue (mean 45% of target), but second-read thinking can swing a run by 13%.
7. **Haiku price tier cliff**: the price table bills a request at 5x every rate once total input passes 100,000 tokens. The extraction and second-read requests are 89,587 tokens, 10.4% below it; a script of about 22 pages at this per-page size would cross it (`claude_over_tier` is the event that would show it). The chunked read did not fire here.

## Opportunities for sub-project C (numbers from these runs)
1. **Claude review threshold offset.** Confidence below 0.90 puts 13 to 16 leaves per run in the queue. Below 0.85 it is 6 to 9, and still catches 4 to 5 of the 5 to 7 leaves that differ from Gemini; below 0.80 it is 3 to 4, catching 3 to 4. Claude's confidences cluster at 0.80 to 0.85 and no Gemini leaf was flagged on confidence at all, so the 0.90 cut mostly flags the model's habit; it still catches most disagreeing leaves, which is why the offset should be set against human marks, not removed. Cost: $0; saves teacher review time on roughly 10 leaves per paper. Needs ground truth to pick the offset (agreement with Gemini is the only reference here).
2. **Second-read thinking.** 12.4k to 12.8k thinking tokens in 2 of 4 runs cost $0.0062 to $0.0064 (13% of the script) and 60 s; the 2 runs without it also passed the gate; in the enhanced pair the marks are equal (60 and 60), while the plain pair differs (58 and 61) for reasons this data cannot separate from run noise. Capping or disabling thinking on the second read (untested; the brief listed it as out of scope) saves up to $0.0064 per paper (13% enh1), and the 5.1k to 6.5k thinking tokens of the first read ($0.0025 to $0.0032) are the next candidate. Test needed: second read at effort `none` against the current setting on this scan and one other, checking G9 agreement and unbound counts.
3. **Sonnet adjudication on the stable-disagreement leaves** (2a_i, 5d, 7b_i, plus leaves with confidence below 0.80: 3 to 4 per run). Sonnet rows in the price table are 20x Haiku on input, cache write and output ($2/M, $2.50/M, $10/M) and 10x on cache read ($0.10/M). Estimate (not measured): reusing the 14,752-token correction prefix, one cold write is $0.037, each further call about $0.0056 (read $0.0015 + about 400 output tokens $0.004); three leaves cost about $0.052, which is more than the whole current paper and leaves $0.097 of $0.10. So it only fits with a leaf-scoped prompt (a few thousand tokens, about $0.007 per leaf) or with at most 1 to 2 leaves. Value depends on item 1 of "Remaining gaps": it settles which side is right only if the stronger model is itself checked against a human mark.
4. **Extraction image cache write**: $0.0111 per paper (22.6% to 27.7%), about 4.7k tokens per page for 19 pages. Cutting resolution, blank-page skipping, or sending the cover page only to scan-metadata would scale this directly. Not tested; it is already net positive against uncached second reads (about $0.006 saved).
5. **Correction call count**: 42 calls each re-read a 14,752-token prefix ($0.0060 to $0.0062 per paper, 35% to 40% of the correction line) and write about 350 output tokens ($0.0073 to $0.0076, 45%). Grouping leaves of a question into one call saves at most $0.005 per paper and loses per-leaf isolation.
6. **Borderline policy**: 3 to 5 high-effort calls cost $0.0026 to $0.0072 (5.6% to 15.8% of the script; plain2 used 5 calls and 10.5k thinking tokens). This data does not show whether borderline changed any mark. Measure that before keeping it.
7. **Scan metadata**: $0.00109 and 4 to 7 s of call time, but the stage takes 56 to 72 s wall clock; the preparation time is the larger prize.

## Red flags
1. enh1 returns `verdict=pass` with G5 failed on 3 leaves (7b_i, 7b_ii, 7c) and G9 on 1 (7c). Check that the gate's rate threshold, not a leak, explains it, before treating pass as publishable.
2. Latency regression: 371 to 442 s against 233 s, with 150 s or more of unlogged preparation. Undiagnosed.
3. enh1's first Claude mark-scheme parse failed `parse_ok` once (retry doubled that parse's cost); cause unknown.
4. Cross-run cache hits flatter three of the four correction lines by $0.0018 each; the mean is $0.0445 measured or $0.0455 cold-corrected.
5. Four more uploads of a real student scan to the Files API; no failed-delete event, but deletion was not verified against the workspace.
6. Two of four second reads think for 12.5k tokens and two do not, at the same setting: a cost and latency lottery until item 2 above is resolved.

## Files
Here: `lemely.toml`, `driver.py`, `run.log`, `events.jsonl`, `records.jsonl` (+ `records_correction.jsonl`, `records_extraction.jsonl`, `records_markscheme_claude.jsonl`, `records_scan_metadata.jsonl`), `script_costs.json`, `timing.json`, `extracted.json`, `correction.json`, `mark_scheme.json`, `ledger_before.json`, `ledger_after.json`, `MARKS.md`. The other three runs have the same set. `extracted.json`, `correction.json`, `records*.jsonl`, `events.jsonl`, `MARKS.md`, `cache/` and `outputs/` hold or can hold student data and stay uncommitted.
