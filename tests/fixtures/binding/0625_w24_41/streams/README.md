# 0625/41 Oct/Nov 2024: recorded reading-order streams

Five replies from one reader, on the same student scan as the fixtures one directory
up. Each reply is a single list, in reading order, of the question labels the model saw
and the blocks of student writing. The model was not asked for question ids and gave
none: `lemely.core.label_sequence.bind_stream` decides which question each label is.

- Variant A of the measurement in `.superpowers/sdd/task-2b-report.md` (one interleaved
  list, bound by list order).
- Model `gemini-3.8-flash`, 19 pages rendered at 72 dpi, recorded 2026-10-10.
- Prompt version `il1`.

Each file is `{"model", "prompt_version", "page_count", "items"}`. `items` is exactly
what the model returned: nothing was edited, reordered or removed. An item is either
`{"type": "label", "page", "box", "text", "kind"}` or
`{"type": "answer", "page", "box", "answer", "working_out", "confidence", "placed_by"}`.
Some items lack a field or carry the other type's fields as well (every item of run 3
does); the loader in `tests/test_label_stream_fixtures.py` reads an item by its `type`.

| File | Items | What it shows |
|---|---|---|
| `A_run1.json` | 110 | All 63 labels in order. The arrow-tied sentence of 4(b)(i) is listed after `(b)`, one label early. |
| `A_run2.json` | 116 | All 63 labels in order. Five blocks flagged `uncertain`; the arrow-tied sentence of 4(b)(i) is listed straight after the `(c)` label of question 2, with page 7. |
| `A_run3.json` | 112 | All 63 labels in order. Notes at the top of pages 13, 15 and 18 are listed before the first label of their page, unflagged. |
| `A_run4.json` | 107 | The label `4` is absent (the student ringed the printed number). Its parts `(a)`, `(b)`, `(i)`, `(ii)`, `(iii)` are all there. |
| `A_run5.json` | 112 | The label `4` is absent; the ring is reported as a block of writing, "circle around 4", flagged `uncertain`. |

The files hold the student's answer text only. The scan is not here and must never be
committed: its cover page carries the candidate's name. The sources are
`.omc/research/p4n24-shift/runs/tsA_gemini-3.8-flash_{1..5}.json` (untracked), from
which only the four keys above were kept.
