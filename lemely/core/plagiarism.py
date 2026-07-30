"""Pure plagiarism checker — stdlib difflib only, no Gemini calls."""

from __future__ import annotations

import re
import string
from difflib import SequenceMatcher

from lemely.core.integrity_schemas import IntegrityFinding


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return text


class PlagiarismChecker:
    """Detect near-verbatim copying using difflib SequenceMatcher.

    Uses difflib.SequenceMatcher.ratio() on normalised text.
    Threshold is configurable via IntegritySettings.plagiarism_threshold (default 0.85).
    No network calls, no new package dependencies.
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self._threshold = threshold

    def check(
        self,
        question_id: str,
        student_answer: str,
        expected_answer: str,
    ) -> IntegrityFinding:
        """Check one student answer against the expected answer.

        Args:
            question_id: Identifier for the question (used in IntegrityFinding).
            student_answer: The student's written answer.
            expected_answer: The mark-scheme model answer to compare against.

        Returns:
            IntegrityFinding with kind='plagiarism', flagged=True when ratio >= threshold.
        """
        norm_student = _normalize(student_answer)
        norm_expected = _normalize(expected_answer)
        score = SequenceMatcher(None, norm_student, norm_expected).ratio()
        flagged = score >= self._threshold
        rationale = (
            f"Similarity ratio {score:.3f} {'≥' if flagged else '<'} "
            f"threshold {self._threshold:.3f}."
        )
        return IntegrityFinding(
            question_id=question_id,
            kind="plagiarism",
            flagged=flagged,
            score=score,
            rationale=rationale,
        )
