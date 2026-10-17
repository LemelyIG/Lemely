"""Loader for CAIE syllabus topic taxonomies, backed by ``subject_topics``.

Was bundled static JSON. Keyed on ``(board, subject_code)``, so another board
arrives as extra rows rather than a schema change. Provenance still travels
with the data: ``subjects.source_url`` and ``subjects.syllabus_version`` are
what a label like ``"4.3 Electric circuits"`` is only meaningful against,
because CAIE renumbers topics between syllabus cycles.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.topics import SyllabusTaxonomy, TopicNode, topic_sort_key
from lemely.db.models.academic import Subject
from lemely.db.models.catalogue import SubjectTopic
from lemely.db.session import get_sessionmaker

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

_lock = threading.Lock()
_cache: dict[tuple[str, str], SyllabusTaxonomy] | None = None


def invalidate_reference_cache() -> None:
    """Drop the process cache. Called by the seeding and ingest paths."""
    global _cache
    with _lock:
        _cache = None


def _build_nodes(
    children: dict[uuid.UUID | None, list[SubjectTopic]], parent: uuid.UUID | None
) -> list[TopicNode]:
    """Depth-first tree build, in syllabus order.

    Ordered by :func:`~lemely.core.topics.topic_sort_key`, never by the code
    string: sorting ``"1.10"`` as text puts it before ``"1.2"``, and 0580's
    subtopics really do run past ten.
    """
    return [
        TopicNode(
            code=row.code,
            name=row.name,
            strong=list(row.strong),
            keywords=list(row.keywords),
            subtopics=_build_nodes(children, row.id),
        )
        for row in sorted(children.get(parent, []), key=lambda r: topic_sort_key(r.code))
    ]


def _load(session: Session) -> dict[tuple[str, str], SyllabusTaxonomy]:
    subjects = {s.code: s for s in session.scalars(sa.select(Subject))}
    by_subject: dict[tuple[str, str], dict[uuid.UUID | None, list[SubjectTopic]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in session.scalars(sa.select(SubjectTopic)):
        by_subject[(row.board.value, row.subject_code)][row.parent_id].append(row)

    out: dict[tuple[str, str], SyllabusTaxonomy] = {}
    for (board, code), children in by_subject.items():
        subject = subjects.get(code)
        # A taxonomy needs a source URL by construction. A subject without one
        # yields no taxonomy rather than one citing nothing.
        if subject is None or not subject.source_url or not subject.syllabus_version:
            continue
        out[(board, code)] = SyllabusTaxonomy(
            board=board,
            subject_code=code,
            subject_name=subject.name,
            syllabus_version=subject.syllabus_version,
            source_url=subject.source_url,
            topics=_build_nodes(children, None),
        )
    return out


def load_taxonomies(session: Session | None = None) -> dict[tuple[str, str], SyllabusTaxonomy]:
    """Every taxonomy, keyed ``(board, subject_code)``. Cached per process."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    loaded = _load(session) if session is not None else _load_with_own_session()
    with _lock:
        _cache = loaded
    return loaded


def _load_with_own_session() -> dict[tuple[str, str], SyllabusTaxonomy]:
    with get_sessionmaker()() as session:
        return _load(session)


def get_taxonomy(
    subject_code: str, *, board: str = "caie", session: Session | None = None
) -> SyllabusTaxonomy | None:
    """The taxonomy for a subject, or ``None`` if none is stored.

    ``None`` is a normal outcome, not an error: the corpus can contain a
    subject whose syllabus has not been transcribed, and the honest result is
    an unclassified question rather than an invented topic.
    """
    return load_taxonomies(session).get((board, subject_code))
