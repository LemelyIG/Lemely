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

from datetime import datetime
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
    qualificationLevel: str | None = None
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


class MomentumPointDTO(ApiModel):
    """One corrected paper on the momentum line.

    ``recorded_at`` is the canonical UTC ISO-8601 timestamp; the reading of it
    belongs to the frontend, which knows the reader's locale. ``percentage`` is
    the paper's percentage as recorded, never rescaled or clipped.
    """

    recordedAt: str
    percentage: float


class MomentumDTO(ApiModel):
    """The momentum series: percentage per corrected paper, oldest first.

    ``points`` is empty when fewer than two grade-bearing papers exist — a line
    needs at least two points, and the frontend renders its empty state off
    exactly that condition rather than recounting papers for itself.

    **This carried pre-rendered SVG path data until P5.3** (``path``, ``area``,
    ``lastX``, ``lastY``, ``labels``), computed against a hardcoded 300x88
    viewbox and a 55-100% band. Two defects came with it, and both are gone
    rather than fixed, because the geometry itself has left the backend:

    - The band **clipped from below**. ``y = 88 - ((pct - 55) / 45) * 78``
      puts anything under 55% past the bottom of the viewbox (40% lands at
      y=114, 30% at y=131), and the element it drew into was
      ``overflow-visible``, so a struggling student's line escaped the panel
      and drew over the labels beneath it. The students whose momentum matters
      most were the ones whose line left the chart.
    - ``labels`` was ``recorded_at[:7]``, a year-month. Five papers sat in one
      month rendered five identical ticks.

    Shipping a series instead of a path also puts the axis where it can be
    read: the frontend plots against a real 0-100 scale, so nothing clips and
    nothing has to agree with a coordinate transform written in another
    language (``web/src/portals/student/data.ts`` used to hold a copy of it).
    """

    points: list[MomentumPointDTO]


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
    """Subject-page header block (mirrors ``subjectHeader``).

    ``name`` is the primary identifier (resolved via ``get_profile``,
    falling back to the raw code); ``code`` and ``qualificationLevel`` are
    secondary metadata the frontend composes alongside it — see
    ``lemely.web.routers.student.student_subject``.
    """

    name: str
    code: str
    qualificationLevel: str | None = None
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


class UploadRunDTO(ApiModel):
    """Run state of one uploaded paper, for a reader who is not the SSE stream.

    Exists because the marking run outlives the browser tab that started it.
    ``POST /api/student/correct`` does its work on a background thread and
    persists the attempt when it finishes, so a student who reloads mid-run has
    not lost the marking — they have lost the only thing that was *reporting* on
    it. This is what a reloaded screen reads instead.

    It deliberately carries no per-question progress. The SSE frames are
    published to a process-global bus with no replay, so once they are gone they
    are gone, and a recovered screen that redrew the three-stage panel would be
    showing ticks it invented. ``status`` is the whole of what is still known.

    ``startedAt`` is meaningful only while ``status`` is ``processing``; it is
    the moment that status was written. ``stale`` is the server's own judgement
    on that timestamp (see ``MARKING_RUN_STALE_AFTER``), computed here rather
    than in the client because the server owns the clock the timestamp came
    from.
    """

    paperId: str
    status: str
    filename: str | None
    startedAt: datetime | None
    stale: bool


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
