"""Scheme corpus persistence (spec 2026-09-03 §4.3). First production writer of ``mark_schemes``.

:class:`SchemeCorpusRepository` replaces the directory scan
``resolve_mark_scheme`` used to perform against parsed mark-scheme JSON files
on disk: the teacher's ``POST /schemes`` now writes one row per paper to the
existing ``mark_schemes`` table (joined to ``papers``, the same tables
:mod:`lemely.db.question_bank_repo` already writes for past-paper questions),
and :meth:`find_for` replaces the scan for the read side. No migration —
``mark_schemes.paper_id`` is already unique, so "insert or replace" is exactly
"the one row for this paper's identity".

Two things matter about how ``papers``/``subjects`` rows come to exist here:

1. **A paper's identity is six columns** (board, subject code, session month,
   session year, paper number, variant — ``uq_papers_identity``), exactly the
   detected metadata a parsed mark scheme carries. :func:`_identity_from`
   builds that identity from a :class:`~lemely.core.loose_schemas.
   MarkSchemeMetadata`, and :func:`~lemely.db.question_bank_repo.resolve_paper`
   (get-or-create) is the very same helper
   :meth:`~lemely.db.question_bank_repo.QuestionBankService.
   link_past_paper_rows` uses — one get-or-create path for ``papers``, not two
   that could drift.
2. **A subject with no bundled syllabus taxonomy cannot be stored.**
   ``subjects.name`` is ``NOT NULL`` and the only honest source for it is the
   transcribed name in the bundled taxonomy (see
   :func:`~lemely.db.question_bank_repo.resolve_paper`'s docstring); a scheme
   for a subject the taxonomy does not know is a real, silent
   :meth:`SchemeCorpusRepository.store` outcome — ``None`` — not an
   exception. There is no partial write on that path: nothing is added to the
   session before the taxonomy check fails.

**Matching (``find_for``) is keyed on the caller's detected metadata, not on
free text.** A near-miss on subject, paper number, variant, or session month
must never resolve to a different paper's scheme — that would silently grade
a student's work against the wrong mark scheme. The one deliberate exception
is the session year: when the caller has not detected one (``session_year is
None``), the newest matching paper wins rather than the query matching
nothing, because a still-legible scan with an undetectable year is exactly
the case this corpus most needs to serve.

The corpus is global, not tenant-scoped (spec §4.3): these are public CAIE
exam documents, so unlike :mod:`~lemely.db.teacher_paper_repo` there is no
visibility filter anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from lemely.core.loose_schemas import MarkScheme, MarkSchemeMetadata
from lemely.db.models.academic import MarkScheme as MarkSchemeRecord
from lemely.db.models.academic import Paper
from lemely.db.models.enums import SESSION_MONTH_LABELS, ExamBoard, SessionMonth
from lemely.db.question_bank_repo import PaperIdentity, resolve_paper

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.schemas import ExamMetadata


_SESSION_MONTH_BY_LABEL: Final[dict[str, SessionMonth]] = {
    label: member for member, label in SESSION_MONTH_LABELS.items()
}
"""Inverse of the display map, derived the same way
:mod:`lemely.db.question_bank_repo` derives its own copy — from
``SESSION_MONTH_LABELS``, so the two cannot drift apart. Not imported from
that module: its copy is a module-private implementation detail, not part of
that module's public surface."""


@dataclass(frozen=True, slots=True)
class SchemeCorpusRow:
    """One ``mark_schemes``/``papers`` join, read-shaped for the teacher console."""

    id: uuid.UUID
    doc: str
    paper_number: int
    paper_variant: int
    session_month: SessionMonth
    session_year: int | None
    maximum_mark: int
    question_count: int
    created_at: datetime


def _identity_from(meta: MarkSchemeMetadata) -> PaperIdentity | None:
    """Build the ``papers`` identity a parsed scheme's header metadata carries.

    ``None`` only if ``meta.session_month`` fails to map through
    :data:`_SESSION_MONTH_BY_LABEL` — in practice this cannot happen, since
    every member of :class:`~lemely.core.loose_schemas.SessionMonth` has an
    entry in ``SESSION_MONTH_LABELS``, but the check keeps this function total
    rather than assuming a schema invariant it does not itself enforce.
    """
    month = _SESSION_MONTH_BY_LABEL.get(meta.session_month)
    if month is None:
        return None
    return PaperIdentity(
        board=ExamBoard.caie,
        subject_code=meta.subject_code,
        session_month=month,
        session_year=meta.session_year,
        paper_number=meta.paper_number,
        paper_variant=meta.paper_variant,
    )


def _row(ms: MarkSchemeRecord, paper: Paper) -> SchemeCorpusRow:
    doc = (
        Path(ms.source_document).name
        if ms.source_document
        else f"{paper.subject_code}_{paper.paper_number}{paper.paper_variant}.json"
    )
    return SchemeCorpusRow(
        id=ms.id,
        doc=doc,
        paper_number=paper.paper_number,
        paper_variant=paper.paper_variant,
        session_month=paper.session_month,
        session_year=paper.session_year,
        maximum_mark=ms.maximum_mark,
        question_count=len(ms.parsed_payload["questions"]),
        created_at=ms.created_at,
    )


class SchemeCorpusRepository:
    """The parsed mark-scheme corpus on ``papers``/``mark_schemes`` (spec §4.3, DS5)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind to a ``sessionmaker`` (mirrors every other repo in this package)."""
        self._sm = session_factory

    def store(self, scheme: MarkScheme, *, provenance: str) -> uuid.UUID | None:
        """Insert or replace the ``mark_schemes`` row for the scheme's paper.

        ``None`` when the scheme's subject has no bundled syllabus taxonomy —
        see the module docstring; a real, silent branch, not an error.
        """
        identity = _identity_from(scheme.metadata)
        if identity is None:
            return None
        with self._sm.begin() as session:
            resolved = resolve_paper(session, identity)
            if resolved is None:
                return None
            paper_id, _created = resolved
            existing = session.scalars(
                select(MarkSchemeRecord).where(MarkSchemeRecord.paper_id == paper_id)
            ).one_or_none()
            payload = scheme.model_dump(mode="json")
            maximum = scheme.metadata.maximum_mark
            if existing is None:
                existing = MarkSchemeRecord(
                    paper_id=paper_id,
                    maximum_mark=maximum,
                    parsed_payload=payload,
                    provenance=provenance,
                )
                session.add(existing)
                session.flush()
            else:
                existing.maximum_mark = maximum
                existing.parsed_payload = payload
                existing.provenance = provenance
            return existing.id

    def set_source_document(self, scheme_id: uuid.UUID, key: str) -> None:
        """Record the uploaded PDF's object key. A silent no-op for an unknown id."""
        with self._sm.begin() as session:
            row = session.get(MarkSchemeRecord, scheme_id)
            if row is not None:
                row.source_document = key

    def list_rows(self) -> list[SchemeCorpusRow]:
        """Every stored scheme, newest first, for the teacher console's ``GET /schemes``."""
        stmt = (
            select(MarkSchemeRecord, Paper)
            .join(Paper, Paper.id == MarkSchemeRecord.paper_id)
            .order_by(MarkSchemeRecord.created_at.desc())
        )
        with self._sm() as session:
            return [_row(ms, paper) for ms, paper in session.execute(stmt)]

    def find_for(self, metadata: ExamMetadata) -> MarkScheme | None:
        """The corpus scheme matching detected exam metadata, or ``None``.

        Every field on ``metadata`` narrows the match — subject, paper
        number, variant, and (when detected) session month and year — so a
        near-miss on any one of them returns ``None`` rather than a different
        paper's scheme (module docstring). Omitting the year is the sole
        exception: the newest matching paper wins instead of the query
        matching nothing.
        """
        month = _SESSION_MONTH_BY_LABEL.get(metadata.session_month)
        conditions = [
            Paper.subject_code == metadata.subject_code,
            Paper.paper_number == metadata.paper_number,
            Paper.paper_variant == metadata.paper_variant,
        ]
        if month is not None:
            conditions.append(Paper.session_month == month)
        if metadata.session_year is not None:
            conditions.append(Paper.session_year == metadata.session_year)
        stmt = (
            select(MarkSchemeRecord)
            .join(Paper, Paper.id == MarkSchemeRecord.paper_id)
            .where(*conditions)
            .order_by(Paper.session_year.desc().nulls_last(), MarkSchemeRecord.created_at.desc())
            .limit(1)
        )
        with self._sm() as session:
            row = session.scalars(stmt).one_or_none()
            return None if row is None else MarkScheme.model_validate(row.parsed_payload)


__all__ = ["SchemeCorpusRepository", "SchemeCorpusRow"]
