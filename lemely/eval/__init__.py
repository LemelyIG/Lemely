"""Evaluation record model and analyses.

See spec §3 (`docs/superpowers/specs/2026-08-17-accuracy-programme-design.md`).
Label *data* does not live in this package (spec §3.1) — it lives at
repository-root ``eval/labels/…`` so labels are never importable and the
labeller process cannot reach pipeline code (spec §6).
"""

from __future__ import annotations
