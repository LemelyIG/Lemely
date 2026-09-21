# Task 10, fix round 3 — closing M-A, M-B, M-C

Closes the three Minor findings from "Second re-review of `0123772e`" in
`.superpowers/sdd2/reports/task-10-review.md`. I3 (fence escape / delimiter
forgery) is already closed and approved; nothing about the fence's shape
changed here.

## M-A — "exactly six delimiters by construction" was conditional

**Where:** `lemely/io/prompts/self_review_judge.py`, `build_judge_user_prompt`.

`_strip_marker` previously ran only on the three fenced values
(`student_evidence`, `student_answer`, `marker_rationale`). The four scaffold
fields — `subject_code`, `question_id`, `point_text`, `mark_type` — were
interpolated raw, so a marker in any of them would push the prompt to seven
delimiter-bearing occurrences instead of six. Not student-reachable today
(those fields come from the mark scheme / paper metadata), so this was
defence-in-depth plus a claim stated more broadly than it held.

**Fix:** `build_judge_user_prompt` now passes all four scaffold fields
through `_strip_marker` too. The claim is now true for the whole prompt, not
just for three fields.

**Tests:** Added `SCAFFOLD_FIELDS` and
`test_no_scaffold_field_can_add_a_stray_marker`, parametrized over the same
16 `HOSTILE_PAYLOADS` × 4 scaffold fields (64 cases), asserting the marker
count stays `2 * FENCED_FIELDS` regardless of which field carries it. This is
a separate test from `test_no_untrusted_field_can_forge_a_fence_boundary`
because scaffold fields are *not* fenced — a hostile scaffold value is
expected to change the prompt's `_skeleton` (it renders where the field
always renders); what must not change is the delimiter count. Reusing the
skeleton-equality assertion for scaffold fields would be wrong, so I didn't.

Corrected the stale comment at `tests/test_evidence_judge.py:38` (formerly "Three
untrusted fields are fenced, so six delimiters and no more") to state the
narrower true claim (three fields are fenced) plus the now-true broader one
(the marker is stripped from all seven string fields, so six delimiters is a
whole-prompt ceiling).

## M-B — the lenient-rule guard was only half closed

**Where:** `tests/test_evidence_judge.py`.

The `endswith` assertion structurally kills the append vector. The ten-term
denylist guarding in-place inversion is evadable by construction — I
reproduced the reviewer's exact bypass phrase ("Where the transcription
leaves the matter open, the correct answer is accepted=false") against the
*current* production `JUDGE_SYSTEM_PROMPT` and confirmed it passes all ten
denylist terms undetected (see RED transcript below).

**Fix:** Replaced the denylist loop with `test_system_prompt_is_frozen`,
which pins `len(JUDGE_SYSTEM_PROMPT)` and its SHA-256 hex digest. Any edit —
however phrased, wherever inserted — now fails this test and shows up as a
diff a reviewer has to look at, rather than needing to be enumerated in
advance. Kept the three verbatim-clause assertions and the `endswith` check
in `test_prompt_states_the_lenient_rule_as_an_instruction` as documentation
of *why* the string is what it is; dropped the denylist loop entirely since
the freeze makes it redundant. The freeze test's docstring tells a future
editor exactly what to do to change the prompt legitimately: update the
length/hash and bump `VERSION`.

### RED transcript (semantic edit defeats the frozen prompt)

Inserted the reviewer's exact bypass phrase into the live
`lemely/io/prompts/self_review_judge.py`, directly after "Never reject for
tone, brevity, or because the marker disagreed.":

```python
'Never reject for tone, brevity, or because the marker disagreed. '
'Note on standard of proof: a challenge succeeds only where the transcription '
'itself establishes the claim the student makes. Where the transcription leaves '
'the matter open, the correct answer is accepted=false. "'
```

```
$ pytest tests/test_evidence_judge.py -k test_system_prompt_is_frozen --no-cov -q
>       assert len(JUDGE_SYSTEM_PROMPT) == 1375
E       assert 1586 == 1375
E        +  where 1586 = len("You are a lenient examiner reviewing a student's challenge ...")
FAILED tests/test_evidence_judge.py::test_system_prompt_is_frozen - assert 1586 == 1375
```

File restored from a pre-edit copy (`cp`, not `git checkout --`, per the
worktree rule) and confirmed byte-identical (`diff` returned nothing) before
continuing.

## M-C — the accept-rate log alone was not a sufficient remaining check

**Where:** `lemely/io/evidence_judge.py`, `lemely/io/prompts/self_review_judge.py`.

Confirmed the implementer's stated residual limit is honest: the fence
cannot make the model obey the data rule for text inside a block, and
nothing at the prompt layer can. The accept-rate log alone is not a
sufficient check on that residual (log line with no query/threshold/owner,
on a high-by-design baseline, lagging and aggregate) — and the one direct
signal available, that `_strip_marker` actually removed something from a
student/marker-supplied field, was being discarded.

**Fix:**
- Added `evidence_was_tampered(request: JudgeRequest) -> bool` to
  `lemely/io/prompts/self_review_judge.py`: true iff stripping the marker
  changed `student_answer`, `marker_rationale`, or `student_evidence` (the
  same three fenced fields `build_judge_user_prompt` protects). No evidence
  text is logged — only the boolean.
- `GeminiEvidenceJudge.judge()` now logs `evidence_sanitised=<bool>` on the
  existing `self_review_judge_verdict` event, so a forgery attempt is a
  named, timestamped, per-submission event rather than a shift in an unread
  aggregate.

### RED transcript (event absent before the fix)

Removed the `evidence_sanitised=...` kwarg from the `log.info(...)` call in
`lemely/io/evidence_judge.py` and re-ran the new test:

```
$ pytest tests/test_evidence_judge.py -k "evidence_sanitised or evidence_was_tampered" --no-cov -q
_______ test_a_forged_marker_in_evidence_is_logged_as_evidence_sanitised _______
>       assert verdicts[0]["evidence_sanitised"] is True
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'evidence_sanitised'
FAILED tests/test_evidence_judge.py::test_a_forged_marker_in_evidence_is_logged_as_evidence_sanitised - KeyError: 'evidence_sanitised'
```

File restored from a pre-edit copy and confirmed byte-identical before
continuing.

Also added `test_evidence_was_tampered_is_true_only_when_stripping_changed_something`,
asserting: `False` for the default (clean) request; `True` when the marker
appears in `student_evidence`, `student_answer`, or `marker_rationale`
individually. And extended `test_every_verdict_is_logged_with_its_subject_for_the_accept_rate_metric`
to assert `evidence_sanitised is False` on a clean request.

## `VERSION` — not bumped, and here is why

`JUDGE_SYSTEM_PROMPT`'s text is unchanged — the freeze test pins it
byte-for-byte identical to what shipped in `0123772e`. `build_judge_user_prompt`'s
output changed only for inputs where a scaffold field (`subject_code`,
`question_id`, `point_text`, `mark_type`) contains the literal marker
`UNTRUSTED_TEXT` — and `_strip_marker` is a no-op on any string that doesn't
contain it. No real request has ever put that marker in a mark-scheme field
(the review confirmed no student-reachable path does), so for every request
that was ever actually rendered and cached, `build_judge_user_prompt`'s
output — and therefore `GeminiClient._cache_key`'s
`system_prompt + user_prompt + prompt_version` hash — is byte-identical to
before. `VERSION` stays `"2"`.

## Comment corrections

- `tests/test_evidence_judge.py:38` (`FENCED_FIELDS` docstring) — corrected
  from "Three untrusted fields are fenced, so six delimiters and no more" to
  state the narrower claim (three fields are fully fenced) separately from
  the now-true broader one (the marker is stripped from all seven string
  fields, making six a whole-prompt ceiling).
- `lemely/io/prompts/self_review_judge.py`, `_strip_marker` docstring —
  added the nit's one sentence recording that the loop is quadratic and safe
  only because `MAX_EVIDENCE_CHARS` bounds `student_evidence`.

## Files changed

- `lemely/io/prompts/self_review_judge.py`
- `lemely/io/evidence_judge.py`
- `tests/test_evidence_judge.py`

## Commands run

```
PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pytest tests/test_evidence_judge.py --no-cov -q
# 141 passed, 1 warning

PATH="/home/sico/Code/Lemely/.venv/bin:$PATH" pre-commit run --files \
  lemely/io/prompts/self_review_judge.py lemely/io/evidence_judge.py tests/test_evidence_judge.py
# ruff, ruff-format, trailing-whitespace, end-of-files, merge-conflicts,
# detect-private-key, mypy, import-linter: all Passed
```

## Nothing outstanding

All three Minors closed with tests and RED transcripts above; the nit (record
the `MAX_EVIDENCE_CHARS` coupling) was folded in alongside M-A since it
touches the same docstring.
