"""Reusable service layer for the FastAPI backend.

Services wrap the core/io pipelines behind portal-agnostic entry points so the
teacher and student routers can share one implementation of extraction and
grading.
"""

from __future__ import annotations
