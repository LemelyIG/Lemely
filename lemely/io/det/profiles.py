"""Subject profiles: code → name and paper-number → PaperType mappings.

Profiles replace the hard-coded heuristics in the old ``_detect_paper_type``
and ``_extract_subject_name`` methods, making the parser configurable on a
per-subject basis without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lemely.core.loose_schemas import PaperType


@dataclass
class SubjectProfile:
    """Per-subject metadata for the deterministic parser."""

    code: str
    name: str
    paper_type_by_number: dict[int, PaperType] = field(default_factory=dict)

    def paper_type(self, paper_number: int, cover_text: str = "") -> PaperType:
        """Resolve PaperType from paper number, then cover-text keywords."""
        if paper_number in self.paper_type_by_number:
            return self.paper_type_by_number[paper_number]
        lower = cover_text.lower()
        if "multiple choice" in lower:
            return PaperType.MCQ
        if "alternative to practical" in lower:
            return PaperType.ALTERNATIVE_PRACTICAL
        if "practical" in lower:
            return PaperType.PRACTICAL
        if "core" in lower:
            return PaperType.THEORY_CORE
        if "extended" in lower:
            return PaperType.THEORY_EXTENDED
        return PaperType.THEORY_EXTENDED


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

_PHYSICS_PROFILE = SubjectProfile(
    code="0625",
    name="Physics",
    paper_type_by_number={
        1: PaperType.MCQ,
        2: PaperType.THEORY_CORE,
        3: PaperType.THEORY_EXTENDED,
        4: PaperType.THEORY_EXTENDED,
        5: PaperType.PRACTICAL,
        6: PaperType.ALTERNATIVE_PRACTICAL,
        61: PaperType.ALTERNATIVE_PRACTICAL,
        62: PaperType.ALTERNATIVE_PRACTICAL,
    },
)

_MATHEMATICS_PROFILE = SubjectProfile(
    code="0580",
    name="Mathematics",
    paper_type_by_number={
        # 0580 has no MCQ component: 1/3 are non-calculator/calculator Core,
        # 2/4 are non-calculator/calculator Extended.
        1: PaperType.THEORY_CORE,
        2: PaperType.THEORY_EXTENDED,
        3: PaperType.THEORY_CORE,
        4: PaperType.THEORY_EXTENDED,
    },
)

_ADDITIONAL_MATHEMATICS_PROFILE = SubjectProfile(
    code="0606",
    name="Additional Mathematics",
    paper_type_by_number={
        # 0606 has no MCQ component either — both papers are structured/written.
        1: PaperType.THEORY_EXTENDED,
        2: PaperType.THEORY_EXTENDED,
    },
)

_DEFAULT_PROFILE = SubjectProfile(
    code="0000",
    name="",
    paper_type_by_number={
        1: PaperType.MCQ,
        6: PaperType.ALTERNATIVE_PRACTICAL,
    },
)

_REGISTRY: dict[str, SubjectProfile] = {
    "0625": _PHYSICS_PROFILE,
    "0580": _MATHEMATICS_PROFILE,
    "0606": _ADDITIONAL_MATHEMATICS_PROFILE,
}


def get_profile(subject_code: str) -> SubjectProfile:
    """Return the profile for *subject_code*, or the default profile if unknown."""
    return _REGISTRY.get(subject_code, _DEFAULT_PROFILE)


def register_profile(profile: SubjectProfile) -> None:
    """Register a custom subject profile (useful for testing / user extensions)."""
    _REGISTRY[profile.code] = profile
