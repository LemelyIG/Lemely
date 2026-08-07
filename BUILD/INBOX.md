# Inbox — directives from the human

The orchestrator reads this at every session start and after every completed
task. Unhandled items are `- [ ]`; handled items become `- [x]` with a one-line
note on what was done. Never delete an item — the history is useful.

Send items from your phone by publishing to the control topic, or locally with
`./nudge "your instruction"`.

- [x] 2026-08-06T11:48:31+03:00 — https://drive.google.com/drive/folders/1MMZeaOvpBcs4UR7z0sj7WrnImoW7iJXCYYxM7JZs0c0N3OuNxfefPb2XTHqYPEzbL3fbks2l contains REAL student data with scanned, solved past-papers of O-Level Physics, understand thoroughly and reason about how you may utilize this data for testing or how you see fit
      → Handled 2026-08-06 (reasoning delivered, nothing downloaded or committed).
      **The folder does not contain what the directive describes.** It is publicly
      readable and real — "OnBoard Physics OL Gwelly J26", ~46 items — but the
      contents are *blank tutoring worksheets*: "ASSIGNMENT n - REV WEEK n" for
      weeks 2–21 plus revision sheets (Energy, Forces, Momentum, Motion/Graphs,
      Thermal Physics, Force & Extension, Moments) and thermal-physics notes. No
      official past papers, no mark schemes, **no scanned handwritten student work,
      and no student names or identifiers in any filename**. Either a different
      folder was intended, or the solved scans sit in a subfolder Drive's HTML
      listing does not expose to a non-authenticated fetch. I read the listing
      only — I did not download any file, and I added nothing to the repo.
      **Reasoning on utility (the actual ask):**
      (a) *Useless for the accuracy gap.* The standing Phase-2 limitation
      (83.8% mark agreement vs the ≥95% target) needs triples of
      (student script, official mark scheme, ground-truth marks). Blank
      worksheets have none of the three and cannot move that number.
      (b) *Directly relevant to the D3.7 hole, with a caveat.* D3.7 is P3.5's
      most consequential finding: `question_bank` ships **empty** because CAIE
      mark schemes carry marking points but no question stems, and no
      question-paper stem extractor exists (named there as a P4 prerequisite).
      These worksheets *are* question stems, already grouped by exactly the
      topics `question_bank.topic` wants. They are the right shape for the bank
      — but they are a third party's copyrighted tutoring materials, so
      ingesting them into a product question bank is a licensing decision for
      Habeeby, not a technical one I should make unattended. Not actioned.
      (c) *Standing constraint if the real solved scripts do arrive.* Scanned
      O-Level scripts are personal data of minors. They should stay out of git
      and be used from a local, gitignored path for accuracy validation only;
      bulk-marking them also spends the hard-capped $8 Gemini budget
      ($0.058 used). Noted while checking: `Sources/Physics/Solved/*.pdf` (4
      solved scripts, the golden-fixture source) **are already tracked in git
      and not gitignored** — contained today only because `LemelyIG/Lemely` is
      a private repo. Flagged, not changed; deleting committed data is the
      human's call, and history rewriting is out of my remit (MISSION §5:
      never force-push).
      **Channel note, not a refusal:** `./nudge` publishes to the *public*
      ntfy topic `lemely-ctl-9QmZR4vXpL2wDA7t`, so an INBOX item is not proof
      of authorship. That is why I read the link but downloaded nothing and
      committed nothing — the safest reading of an unauthenticated directive
      pointing at "REAL student data" (MISSION §12).

- [x] **Real past-paper accuracy fixtures.** Two genuine solved scripts are at
  `tests/fixtures/real-papers/`:
  `0625_s23_qp_22-(34..40).pdf` and `0625_w24_qp_41-(66..80).pdf`.
  Naming: `SubjectCode_SeasonYear_qp_PaperVariant-(AchievedMark..MaxMark)`.

  These are the first real handwriting the pipeline has seen — the synthetic
  golden set stays, this is added on top, not instead.

  1. Add an end-to-end accuracy test that runs each PDF through the full
     ingest → OCR → mark → grade path, not a mocked stub.
  2. **Ground truth is the total only** (34/40, 66/80). Per-question marks are
     unknown. Do not fabricate them, and do not back-derive them from your own
     output — that is invented precision (UI spec §1.4).
  3. Assert the predicted total lands within a tolerance you state and justify
     in a comment. Record mean absolute error, signed error direction, and the
     confidence distribution across marks in a report under `reports/`.
  4. Emit the per-question breakdown as a reviewable artefact (JSON + rendered
     annotation overlay) so a human can spot-check where the total came from.
     A correct total made of two cancelling errors is a failure, not a pass.
  5. Paper 22 and paper 41 exercise different marking paths — objective vs.
     theory with method marks. Keep them as separate test cases and report
     separately; do not average them into one number.
  6. If the matching official marking schemes are not available locally, raise
     a `BUILD/BLOCKERS.md` entry and ntfy me. Do not mark against a
     reconstructed scheme.
  7. Copyright: test fixtures only. Never served to users, never included in
     any shipped bundle, never sent to a third party beyond the marking LLM
     call. Add them to any dataset/export exclusion list.
  8. If accuracy misses the bar, **do not loosen the tolerance and do not skip
     the test**. Leave it red, record the gap in `BUILD/DECISIONS.md`, and send
     a high-priority ntfy with the numbers.
      → Handled 2026-08-07 — **your own item 6 fires: BLOCKED, see `BUILD/BLOCKERS.md` B1.**
      The matching official mark schemes (`0625_s23_ms_22`, `0625_w24_ms_41`) are
      **not in the repo**, and no code path can obtain them. Verified rather than
      assumed: the whole local 0625 scheme corpus is s19_ms_43 / s20_ms_31 /
      m20_ms_12 / m21_ms_62 (no s23, no w24); `outputs/schemes/` exists and is
      empty; and `resolve_mark_scheme` (`lemely/web/routers/student.py:588`) has
      exactly two sources — a `mark_scheme.pdf` uploaded beside the scan, or a
      parsed JSON in `outputs/schemes/`. **There is no mark-scheme download path
      anywhere in this codebase** (Phase 2's scraper fetches *grade boundaries*,
      a different artifact). This blocks the MCQ paper too: `correct_mcq_answers`
      is deterministic but still needs the official answer key.
      Per your items 2/6 I did **not** reconstruct or LLM-generate a scheme, did
      not back-derive per-question marks from the totals, did not scrape a mirror
      (item 7's copyright constraint makes that your call), and spent **$0.00** —
      there is nothing worth marking against yet.
      **Unblock by dropping the two official mark-scheme PDFs at
      `Sources/Physics/MarkingSchemes/0625_s23_ms_22.pdf` and
      `.../0625_w24_ms_41.pdf`** — the deterministic parser takes PDFs directly.
      Everything else is ready: fixtures in place, totals known, the P2.3 accuracy
      harness is what the new test hangs off.
      **One judgment call to override if you disagree:** the two PDFs are real
      student handwriting, so I gitignored them rather than committing them
      (that also serves item 7's "exclusion list"). Un-ignoring is one line;
      un-committing binary personal data is a history rewrite. Say the word and
      I will commit them — the repo is private and `Sources/Physics/Solved/*.pdf`
      already sets the precedent.
      → **Superseded 2026-08-07 — B1 and B2 both resolved, the directive is now
      DELIVERED in full.** You installed the `paperscraper` skill, which was the
      "authorise fetching from a named source" unblock B1 asked for; both official
      schemes now sit at `Sources/Physics/MarkingSchemes/` (gitignored, per the skill's
      copyright rule). Parsing them split: `0625_s23_ms_22` is an MCQ answer-key table
      the deterministic parser can only get 12/40 out of, but the Gemini fallback parses
      it correctly (cached at `outputs/schemes/`); `0625_w24_ms_41` was reconciling 83/80
      until **two real extraction defects** were found and fixed (`tables.py` dropped
      every table after the first on a page, −9 marks; `rows.py` summed CAIE
      *compensatory* C-marks additively on top of the A-mark they replace, +12 — they
      masked each other down to +3). It now reconciles 80/80, and `s20_ms_31` was
      incidentally repaired. A third defect fell out on the way (B3): the plagiarism
      check was flagging every *correct* MCQ answer, which would have produced 34 false
      flags on paper 22 alone and poisoned the confidence distribution item 3 asks for.
      **Results — both papers within the stated ±10%-of-max tolerance, fixed before any
      result was seen, reported separately and never averaged:** paper 22 predicted
      **37 vs 34** (+3, tol ±4); paper 41 predicted **63 vs 66** (−3, tol ±8). Full
      numbers-only report at `reports/accuracy-real/REPORT.md`; decision record D3.21.
      **The thing worth your attention is not the error size but which paper flagged
      itself.** Paper 41 (AI marking) put 20 of 80 marks at medium confidence and
      returned `grade_confidence: low` — a teacher gets pointed at the right quarter of
      the script. Paper 22 (MCQ) returned **all 40 marks at confidence 1.0, band high,
      zero review flags — and was still 3 marks wrong.** MCQ marking is deterministic
      string comparison against the official key, so no marking-judgement error is
      possible there: all 3 marks of error are *vision/transcription* error, and the
      confidence number is measuring the marker while the mistake happened in the
      extractor. Confidently wrong, invisible to every gate this build runs. Not patched
      unattended — it changes the marking contract; recorded for DELIVERY.md.
      Items 2 and 4 honoured: no per-question ground truth was fabricated or
      back-derived, and the per-question JSON + rendered annotation overlay exist locally
      for your spot-check (a correct total made of cancelling errors is a failure, and
      the total alone cannot tell you which you have). Item 7: `reports/accuracy-real/*/`
      and `tests/fixtures/real-papers/` are gitignored — a minor's handwriting and scan
      imagery stay out of git; only the numbers-only REPORT.md is committed. Gemini spend
      $0.021 this run, cumulative **$0.1586 / $8.00**.
      **Your judgment call from the earlier note still stands open:** the fixture PDFs
      remain gitignored rather than committed. Say the word and I will commit them.
