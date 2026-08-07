"""Loader for the bundled CAIE syllabus topic taxonomies (P4.2).

Mirrors ``lemely.io.grade_boundaries``: bundled static JSON, no network calls.
The data file records, per subject, the syllabus PDF URL and version it was
transcribed from — provenance matters because CAIE renumbers topics between
syllabus cycles, and a label like ``"4.3 Electric circuits"`` is only
meaningful against a stated version.

Board-agnostic by construction: the file is keyed on ``(board, subject_code)``,
so Edexcel and Oxford AQA arrive as extra entries, not as a schema change.
"""

from __future__ import annotations

import json
from functools import lru_cache

from lemely.core.topics import SyllabusTaxonomy, TopicNode
from lemely.data import DATA_DIR

_TAXONOMY_PATH = DATA_DIR / "syllabus_topics.json"


def _node(raw: dict) -> TopicNode:  # type: ignore[type-arg]
    return TopicNode(
        code=str(raw["code"]),
        name=raw["name"],
        strong=list(raw.get("strong", [])),
        keywords=list(raw.get("keywords", [])),
        subtopics=[_node(sub) for sub in raw.get("subtopics", [])],
    )


@lru_cache(maxsize=1)
def load_taxonomies() -> dict[tuple[str, str], SyllabusTaxonomy]:
    """Return every bundled taxonomy, keyed by ``(board, subject_code)``.

    Cached: the file is static and parsing it per classified question would
    dominate the cost of a 273-row backfill.
    """
    payload = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], SyllabusTaxonomy] = {}
    for subject in payload["subjects"]:
        taxonomy = SyllabusTaxonomy(
            board=subject["board"],
            subject_code=subject["subject_code"],
            subject_name=subject["subject_name"],
            syllabus_version=subject["syllabus_version"],
            source_url=subject["source"]["url"],
            topics=[_node(topic) for topic in subject["topics"]],
        )
        out[(taxonomy.board, taxonomy.subject_code)] = taxonomy
    return out


def get_taxonomy(subject_code: str, *, board: str = "caie") -> SyllabusTaxonomy | None:
    """Return the taxonomy for a subject, or ``None`` if none is bundled.

    ``None`` is a normal outcome, not an error: the corpus can contain a
    subject we have not transcribed a syllabus for yet, and the honest result
    for its questions is an unclassified topic rather than a forced match
    against some other subject's tree.
    """
    return load_taxonomies().get((board, subject_code))
