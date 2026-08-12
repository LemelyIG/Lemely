"""Student-portal API DTOs (camelCase) mirroring ``web/src/portals/student``.

These models mirror the interface shapes ported into
``web/src/portals/student/data.ts`` (``SubjectRow``, ``WeakThread``, ``ResultData``,
``TheoryQuestion``, ``PlanCell`` …) so screens can swap their stub constants for
live fetches without changing their render code. As with :mod:`lemely.web.schemas`
the wire format is camelCase and deliberately decoupled from the snake_case core
domain models.

**Provenance policy.** Every field below is either *data-backed* — computed from
:class:`~lemely.io.history_store.HistoryStore` records and the pure-core analytics
in :mod:`lemely.core.analytics` / :mod:`lemely.io.grade_boundaries` — or
*structurally-empty*: a typed-neutral default (``""``, ``0``, ``[]``) returned
when no data source exists for that field (leaderboard peers, streak history,
marketing copy, momentum-of-a-single-scalar). Converters in
:mod:`lemely.web.routers.student` document, per field, which is which. Nothing
here hard-codes the mock's demo numbers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from lemely.web.schemas import ApiModel

VizColor = Literal["accent", "ok", "warn", "t1", "t2", "t3"]
IntegrityMark = Literal["check", "dash", "bang"]
PointMark = Literal["check", "dot"]

# ── Overview ────────────────────────────────────────────────────────────────


class SubjectRowDTO(ApiModel):
    """One subject card on the Overview grid (mirrors ``SubjectRow``)."""

    code: str
    name: str
    detail: str
    pct: int
    papers: int
    trend: str
    grade: str
    barColor: VizColor
    trendUp: bool


class WeakThreadDTO(ApiModel):
    """A weak-topic accuracy bar (mirrors ``WeakThread`` / ``TheoryWeakRow``)."""

    topic: str
    acc: str
    width: int
    color: VizColor


class MomentumDTO(ApiModel):
    """SVG sparkline path data for the momentum widget (mirrors ``momentum``).

    ``path``/``area`` are empty strings when fewer than two papers exist (a line
    needs at least two points); ``labels`` are the ordered session tick labels.
    """

    path: str
    area: str
    lastX: str
    lastY: str
    labels: list[str]


class OverviewDTO(ApiModel):
    """Payload for ``GET /api/student/overview``."""

    studentName: str
    forecast: str
    subjects: list[SubjectRowDTO]
    weakGlobal: list[WeakThreadDTO]
    momentum: MomentumDTO


# ── Subject ─────────────────────────────────────────────────────────────────


class PaperBarDTO(ApiModel):
    """A single bar in a paper-breakdown sparkbar (mirrors ``PaperBar``)."""

    value: int
    label: str
    highlight: bool


class PaperBreakdownDTO(ApiModel):
    """Per-paper breakdown card (mirrors ``PaperBreakdown``)."""

    title: str
    sub: str
    mean: str
    boundary: str
    position: str
    positionOk: bool
    bars: list[PaperBarDTO]


class PaperHistoryRowDTO(ApiModel):
    """A row in the subject's paper history table (mirrors ``PaperHistoryRow``).

    ``id`` is the forward-position index into the student's full (unfiltered)
    :class:`~lemely.core.history.StudentHistory.records` — the same addressing
    scheme ``GET /api/student/result/{paper_id}`` uses — so a row can be passed
    straight through as ``paper_id`` to look up its full result.
    """

    id: str
    paper: str
    note: str
    marks: str
    pct: str
    grade: str
    gradeColor: VizColor
    tab: str


class TopicTileDTO(ApiModel):
    """A tile in the topic map (mirrors ``TopicTile``)."""

    name: str
    acc: str
    color: VizColor
    weak: bool


class SubjectHeaderDTO(ApiModel):
    """Subject-page header block (mirrors ``subjectHeader``)."""

    meta: str
    title: str
    intro: str
    forecast: str
    weightedMean: str
    weightedMeanDelta: str


class SubjectDTO(ApiModel):
    """Payload for ``GET /api/student/subject/{code}``."""

    header: SubjectHeaderDTO
    papersBreakdown: list[PaperBreakdownDTO]
    topicMap: list[TopicTileDTO]
    paperHistory: list[PaperHistoryRowDTO]


# ── Paper result (flagship) ───────────────────────────────────────────────────


class IntegrityRowDTO(ApiModel):
    """One integrity-check row on the result page (mirrors ``IntegrityRow``)."""

    mark: IntegrityMark
    color: VizColor
    label: str
    detail: str


class MarkPointDTO(ApiModel):
    """A mark-scheme point within a theory question (mirrors ``MarkPoint``)."""

    mark: PointMark
    id: str
    text: str
    got: bool


class TheoryQuestionDTO(ApiModel):
    """A theory question with its marking points (mirrors ``TheoryQuestion``)."""

    id: str
    topic: str
    marker: str
    conf: str
    confColor: VizColor
    marks: str
    markOk: bool
    cardWeak: bool
    points: list[MarkPointDTO]
    feedback: str
    feedbackTone: Literal["ok", "accent", "warn"]


class ResultDTO(ApiModel):
    """Payload for ``GET /api/student/result/{paper_id}`` (mirrors ``ResultData``).

    ``theory`` and ``integrity`` are populated only when a full per-question
    correction is available for the paper. History records persist totals +
    weak-areas + metadata only, so for history-sourced papers these lists are
    structurally empty and ``markerLabel``/``headline``/``summary`` fall back to
    neutral, computed strings.
    """

    code: str
    paper: str
    session: str
    markerLabel: str
    headline: str
    summary: str
    awarded: int
    max: int
    pct: int
    grade: str
    boundaryYear: str
    railLeft: int
    railFoot: str
    railNote: str
    theory: list[TheoryQuestionDTO]
    integrity: list[IntegrityRowDTO]
    provenance: str


# ── Upload + correct (self-mark) ──────────────────────────────────────────────


class StudentUploadResponse(ApiModel):
    """Payload returned by ``POST /api/student/uploads``.

    ``paperId`` is the id of the created :class:`Upload` row (== the on-disk
    directory name); the caller passes it back to ``POST /api/student/correct``.
    """

    paperId: str


class CorrectRequest(ApiModel):
    """Request body for ``POST /api/student/correct``.

    Names the paper to self-mark; the owning student is the authenticated caller
    (``auth.user_id``), never a request field — so a student can only ever mark
    their own upload.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    paperId: str


# ── Standings ─────────────────────────────────────────────────────────────────


class SubjectRankDTO(ApiModel):
    """A subject's rank line (mirrors ``SubjectRank``).

    ``rank`` is structurally empty (``""``) — ranking requires a cohort the
    single-student HistoryStore cannot supply. ``papers`` is data-backed.
    """

    code: str
    name: str
    rank: str
    color: VizColor
    papers: int


class StandingsDTO(ApiModel):
    """Payload for ``GET /api/student/standings``.

    ``subjectRanks`` and ``paperCount`` are data-backed. ``streakDays`` counts
    distinct recorded-paper days from history; ``boards`` (leaderboard peers) is
    structurally empty — no peer cohort data source exists.
    """

    subjectRanks: list[SubjectRankDTO]
    paperCount: int
    streakDays: int
