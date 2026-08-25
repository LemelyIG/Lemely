"""Subject profiles: code → name and paper-number → PaperType mappings.

Profiles replace the hard-coded heuristics in the old ``_detect_paper_type``
and ``_extract_subject_name`` methods, making the parser configurable on a
per-subject basis without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lemely.core.loose_schemas import PaperType


def _paper_type_from_cover(cover_text: str) -> PaperType | None:
    """Read a PaperType off the cover page, or ``None`` if it says nothing.

    ``None`` is the point of this helper: "the cover carries no paper-type
    keyword" has to be distinguishable from "the cover says THEORY_EXTENDED",
    or an unmodelled cover page would outrank the number map and silently
    demote every such paper to the default.

    Order matters. "Multiple Choice (Extended)" contains *both* "multiple
    choice" and "extended", and "Alternative to Practical" contains
    "practical", so the more specific phrase is tested first in each pair.
    """
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
    return None


@dataclass
class SubjectProfile:
    """Per-subject metadata for the deterministic parser."""

    code: str
    name: str
    paper_type_by_number: dict[int, PaperType] = field(default_factory=dict)

    def paper_type(self, paper_number: int, cover_text: str = "") -> PaperType:
        """Resolve PaperType from the cover text, falling back to paper number.

        **The cover text wins.** It is evidence read off the document being
        parsed; ``paper_type_by_number`` is a hard-coded table maintained by
        hand, and a syllabus can change a component's type without anyone
        editing it here.

        This order is deliberate and was a bug fix. The table used to be
        consulted first and returned immediately, so a wrong constant silently
        overrode a cover page that plainly contradicted it: ``0625`` mapped
        paper 2 to ``THEORY_CORE`` while every 0625 Paper 2 cover reads
        "Paper 2 Multiple Choice (Extended)". The wrong entry was not just
        wrong, it was *unfalsifiable by the document*, and the next wrong
        constant would have behaved the same way.

        The table is still the fallback, and it still matters: most callers
        pass no ``cover_text`` at all, and a cover page carrying no paper-type
        keyword must not demote a known paper to the default.
        """
        from_cover = _paper_type_from_cover(cover_text)
        if from_cover is not None:
            return from_cover
        if paper_number in self.paper_type_by_number:
            return self.paper_type_by_number[paper_number]
        return PaperType.THEORY_EXTENDED


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

_PHYSICS_PROFILE = SubjectProfile(
    code="0625",
    name="Physics",
    paper_type_by_number={
        1: PaperType.MCQ,
        # 0625 Paper 2 is "Multiple Choice (Extended)". This read THEORY_CORE
        # from the file's creation (810ac08) until 2026-08-25; confirmed wrong
        # against the real 0625_s23_ms_22.pdf cover page.
        2: PaperType.MCQ,
        # FLAGGED, NOT CHANGED: CAIE 0625 Paper 3 is Theory (Core), so this
        # entry looks wrong too — but it has not been confirmed against a real
        # cover page the way paper 2 was, and this fix is already mark-changing
        # enough to need its own measurement. Cover text now outranks the table
        # either way, so a Paper 3 scheme parsed from a real PDF resolves
        # correctly regardless of this line.
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
