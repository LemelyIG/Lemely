# 0625/41 Oct/Nov 2024 recorded extractions

Eight recorded `ExtractedAnswers` outputs from one student scan of Cambridge IGCSE
Physics 0625/41 (October/November 2024, 19 pages). All runs date from 2026-10-09
except `aligned.json`. The scan itself is deliberately absent: it carries the
candidate's name on the cover page and must never be committed. Only the extracted
text is kept, and `source_scan` is set to `0625_w24_41_student_scan.pdf` in every
file. Nothing else in a file was changed from what the model returned.

| Fixture | Model | Render dpi | Code | What it shows |
|---|---|---|---|---|
| `full_shift_lite.json` | gemini-3.5-flash-lite | 72 | 885724d0 | Every answer from `1b` to `7c` sits one question late. |
| `full_shift_38_a.json` | gemini-3.8-flash | 72 | 885724d0 | Whole paper one question late. |
| `full_shift_38_b.json` | gemini-3.8-flash | 72 | 885724d0 | Whole paper one question late (second run). |
| `full_shift_38_c.json` | gemini-3.8-flash | 72 | 885724d0 | Whole paper one question late (third run). |
| `chaotic.json` | gemini-3.5-flash-lite | 72 | not recorded | Offsets from -1 to -9, invented ids (`5b_i`, `5b_ii`, `5c`), six ids used twice. |
| `partial_a.json` | gemini-3.5-flash-lite | 72 | not recorded | `1b` to `1c_ii` one question late; `2a_i` appears twice. |
| `partial_b.json` | gemini-3.5-flash-lite | 72 | not recorded | `1b` to `1c_ii` one question late; invents `1c_iii`. |
| `aligned.json` | gemini-2.5-flash | whole PDF uploaded | 1bee5a4d | Every answer is on its own question. |

`aligned.json` came from an older checkout (1bee5a4d, prompt version 5), which
uploaded the whole PDF rather than rendering pages. It has 42 answers; `7c` is
absent because the student left it blank.

The sources live under
`.omc/research/p4n24-shift/` (untracked).
