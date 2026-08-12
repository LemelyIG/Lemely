# API load sanity — Phase 6 (P6.2)

Run: 2026-08-11T20:58:55.403828+00:00 → 2026-08-11T20:59:35.841852+00:00
Base URL: `http://127.0.0.1:8000`  |  Concurrency: 10  |  Duration/endpoint: 5.0s

## What this is (and isn't)

Basic sanity, not a benchmark — MISSION.md §4 Phase 6 asks only for "basic load sanity on the API". No pass/fail verdict is printed below because MISSION states no latency threshold to grade against; these are measured numbers, read them as such.

- Single machine, dev-grade uvicorn server (scripts/e2e_server.py), not production infra.
- Data is scripts/seed_e2e.py's synthetic seed corpus, not production-scale data.
- Gemini is mocked for this server (fixture-backed, per MISSION's mocking requirement) — these numbers say nothing about live-model latency.
- This is a sanity check, not a benchmark: no throughput/latency threshold is asserted or graded against, because MISSION.md states none for the API.

## Results

| Endpoint | Path | n | errors | error rate | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| health | `/api/health` | 5534 | 0 | 0.0 | 8.37 | 14.46 | 48.5 |
| me_profile | `/api/me/profile` | 982 | 0 | 0.0 | 48.19 | 77.86 | 111.94 |
| student_overview | `/api/student/overview` | 481 | 0 | 0.0 | 102.51 | 144.79 | 208.61 |
| student_xp | `/api/student/xp` | 438 | 0 | 0.0 | 113.51 | 145.43 | 171.51 |
| student_leaderboard | `/api/student/leaderboard` | 329 | 0 | 0.0 | 150.13 | 200.34 | 275.12 |
| student_friends | `/api/student/friends` | 441 | 0 | 0.0 | 111.78 | 149.14 | 196.15 |
| teacher_overview | `/api/teacher/overview` | 130 | 0 | 0.0 | 395.73 | 458.1 | 517.88 |
| teacher_papers | `/api/papers` | 1916 | 0 | 0.0 | 26.42 | 34.86 | 48.4 |

