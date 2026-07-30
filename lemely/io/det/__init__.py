"""Deterministic CAIE mark-scheme parser (modular).

Public entry point for the deterministic (non-Gemini) mark-scheme parser.
Callers should import :class:`DeterministicMarkSchemeParser` from this package::

    from lemely.io.det import DeterministicMarkSchemeParser

The parser honours :class:`~lemely.runtime.config.DetParserSettings` and runs a
Stage-4 reconciler that raises :class:`~lemely.runtime.errors.ParseError` on a
mark-total mismatch so ``ChainedMarkSchemeParser`` can escalate to Gemini.
"""

from __future__ import annotations

from lemely.io.det.parser import DeterministicMarkSchemeParser

__all__ = ["DeterministicMarkSchemeParser"]
