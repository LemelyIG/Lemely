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
