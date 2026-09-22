"""The lenient evidence judge for student self-review, on Gemini.

One bounded call per challenged point (:class:`JudgeRequest`), returning a
:class:`JudgeVerdict`. Implements :class:`lemely.core.self_review.EvidenceJudge`.

**Failure propagates.** ``generate_structured``'s ``ExternalServiceError`` /
``ParseError`` are not caught here; the service turns any exception into a
``student_evidence_unjudged`` review-queue row. Catching here and returning a
default verdict would be the silent decision the spec forbids.

**The metric.** Every verdict logs ``self_review_judge_verdict`` with the
subject code and the outcome. A judge that accepts everything is
indistinguishable from no guard at all; the accept rate per subject is what
tells the two apart, and it is emitted from the first call. That aggregate is
lagging and cannot say which verdict was manipulated, so the same log line
also carries ``evidence_sanitised``: whether the fence marker had to be
stripped from any of the three student/marker-supplied fields. Unlike a shift
in an accept rate nobody queries, that is a per-submission, near-zero-false-
positive signal that someone tried to forge a fence boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.core.schemas import StrictModel
from lemely.core.self_review import JudgeVerdict
from lemely.io.prompts.self_review_judge import (
    JUDGE_SYSTEM_PROMPT,
    VERSION,
    build_judge_user_prompt,
    evidence_was_tampered,
)

if TYPE_CHECKING:
    from lemely.core.self_review import JudgeRequest
    from lemely.io.gemini import GeminiClient

log = structlog.get_logger(__name__)

#: ``GeminiSettings.model_for`` tag; ``self_review_judge_model`` overrides the model.
TASK_TAG = "self_review_judge"


class JudgeOutcome(StrictModel):
    """The judge's structured answer."""

    accepted: bool
    reason: str


class GeminiEvidenceJudge:
    """Judge one challenged mark point with a single Gemini call."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        """Decide one challenged point. Raises on any Gemini failure."""
        # No extra_cache_key: GeminiClient._cache_key already hashes system_prompt +
        # user_prompt + prompt_version, and build_judge_user_prompt(request) is a
        # strict superset of every JudgeRequest field, so a per-request digest here
        # could never separate two calls the prompt hash would not already separate.
        outcome = self._client.generate_structured(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=build_judge_user_prompt(request),
            response_schema=JudgeOutcome,
            prompt_version=VERSION,
            task_tag=TASK_TAG,
        )
        log.info(
            "self_review_judge_verdict",
            subject_code=request.subject_code,
            question_id=request.question_id,
            accepted=outcome.accepted,
            claims_earned=request.student_claims_earned,
            evidence_sanitised=evidence_was_tampered(request),
        )
        return JudgeVerdict(accepted=outcome.accepted, reason=outcome.reason)


__all__ = ["TASK_TAG", "GeminiEvidenceJudge", "JudgeOutcome"]
