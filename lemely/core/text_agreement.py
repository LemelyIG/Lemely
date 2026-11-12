"""The one text-agreement function shared by the re-read and second-read paths.

``lemely.io.reread`` (``reread_agreement``) and ``lemely.io.second_read``
(``extraction_agreement``) both score how closely two answer strings agree.
They used to carry a copy each; this is the single implementation.

It is a ``difflib.SequenceMatcher`` stand-in for the plan's ``rapidfuzz``
normalised-Levenshtein metric: ``rapidfuzz`` is not a project dependency.
Strings are compared after ``.strip().casefold()`` only. That is NOT the I2
normaliser (whitespace collapse, NFKC, "x" vs. the multiplication sign,
superscript unfold), which has not landed; it is a much weaker placeholder.
When I2 lands it plugs in here, once, for both callers.
"""

from __future__ import annotations

import difflib


def text_agreement(a: str, b: str) -> float:
    """Similarity in [0, 1] between two answer strings, after normalisation.

    Compared case- and whitespace-folded (``.strip().casefold()``), so an MCQ
    "a" against "A", or either with incidental surrounding whitespace, scores
    1.0 rather than being flagged as a disagreement.
    """
    return difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()
