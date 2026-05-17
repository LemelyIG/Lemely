"""Lemely — accuracy-first educational assessment tool."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lemely")
except PackageNotFoundError:  # pragma: no cover - editable install before metadata
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
