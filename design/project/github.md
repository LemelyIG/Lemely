repo: LemelyIG/Lemely
branch: main

## Last sync

date: 2026-07-27T21:45:20Z

### Updated in this project

- Built `Lemely.dc.html` — a full desktop web UI for the Lemely platform, grounded in the repo's domain model.
- Result screens use the real `AccuracyReport` shape (marks, percentage, predicted grade, confidence band, marker_source, needs_teacher_review) and the supplied 0625/12 May/June 2020 report.
- Theory-marking screen quotes real mark points from the parsed `0625_s20_ms_31` scheme.
- Correction workspace mirrors the Gradio flow: detect metadata → fetch scheme → extract answers → grade, with the EventBus-style live log.

## Screen map

| Screen (in Lemely.dc.html) | Repo files |
| --- | --- |
| Paper result — MCQ | lemely/core/schemas.py, lemely/core/analytics.py, lemely/app/renderers.py |
| Paper result — theory | lemely/core/loose_schemas.py (MarkScheme), lemely/io/correction_ai.py |
| Correct a paper | lemely/app/gradio_app.py, lemely/app/gradio_callbacks.py, lemely/app/live_log.py |
| Subject deep-dive | lemely/io/subject.py, lemely/core/schemas.py (SubjectResult) |
| Overview / weaknesses | lemely/core/analytics.py (summarize_weaknesses, predict_grade) |
| Study plan, Standings, Teacher, Onboarding, Landing | product description (no repo counterpart yet) |
