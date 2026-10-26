"""The tutoring area catalogue, read from ``lemely/data/tutoring_areas.json`` (SPEC §a.2, P3).

A tutor's area is one of the few fields served on the open web (decision-log
row 5b, SPEC §a.5), so it is never free text: ``tutor_profiles.area_code`` must
be a ``code`` from this file, and P3 (``GET /api/public/tutoring-areas``) serves
the file's entries in file order. Large cities where most international-school
families live are listed as cities; elsewhere the unit is a governorate, because
a smaller unit would help identify a tutor (THREAT-MODEL PP-4).

Each entry is ``{"code", "name", "country_code"}`` and nothing else. The file is
validated as a whole when it is read: a malformed file is a deploy error, so it
raises :class:`AreaCatalogueError` rather than serving a partial list.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from lemely.data import DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

AREAS_FILE: Final = DATA_DIR / "tutoring_areas.json"

#: ``tutor_profiles.area_code`` is varchar(40).
_CODE: Final = re.compile(r"[a-z][a-z0-9_]{1,39}")
_COUNTRY: Final = re.compile(r"[A-Z]{2}")
_MAX_NAME_LENGTH: Final = 60
_KEYS: Final = frozenset({"code", "name", "country_code"})


class AreaCatalogueError(ValueError):
    """The areas file is not a list of well-formed, uniquely coded entries."""


@dataclass(frozen=True, slots=True)
class TutoringArea:
    """One selectable area: a stable code, its English display name and its country."""

    code: str
    name: str
    country_code: str


@dataclass(frozen=True, slots=True)
class AreaCatalogue:
    """Every tutoring area, in file order, with lookup by code."""

    areas: tuple[TutoringArea, ...]
    _by_code: Mapping[str, TutoringArea] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the areas by code (the dataclass is frozen, hence ``object.__setattr__``)."""
        object.__setattr__(self, "_by_code", {area.code: area for area in self.areas})

    def get(self, code: str) -> TutoringArea | None:
        """The area with ``code``, or ``None`` when the code is not in the catalogue."""
        return self._by_code.get(code)

    def name_for(self, code: str) -> str:
        """The display name of ``code``; the code itself if a stored code left the file."""
        area = self._by_code.get(code)
        return area.name if area is not None else code


def _entry(raw: object, position: int) -> TutoringArea:
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise AreaCatalogueError(f"entry {position} must have exactly the keys {sorted(_KEYS)}")
    code, name, country = raw["code"], raw["name"], raw["country_code"]
    if not isinstance(code, str) or _CODE.fullmatch(code) is None:
        raise AreaCatalogueError(f"entry {position}: code must match {_CODE.pattern}")
    if (
        not isinstance(name, str)
        or name != name.strip()
        or not 1 <= len(name) <= _MAX_NAME_LENGTH
        or any(unicodedata.category(char)[0] == "C" for char in name)
    ):
        raise AreaCatalogueError(f"entry {position}: name must be 1 to 60 printable characters")
    if not isinstance(country, str) or _COUNTRY.fullmatch(country) is None:
        raise AreaCatalogueError(f"entry {position}: country_code must be two capital letters")
    return TutoringArea(code=code, name=name, country_code=country)


def parse_tutoring_areas(raw: object) -> AreaCatalogue:
    """Validate decoded JSON and return the catalogue (raises :class:`AreaCatalogueError`)."""
    if not isinstance(raw, list) or not raw:
        raise AreaCatalogueError("the areas file must be a non-empty JSON list")
    areas = tuple(_entry(item, position) for position, item in enumerate(raw))
    codes = [area.code for area in areas]
    if len(set(codes)) != len(codes):
        raise AreaCatalogueError("area codes must be unique")
    return AreaCatalogue(areas=areas)


def read_tutoring_areas(path: Path) -> AreaCatalogue:
    """Read and validate an areas file."""
    return parse_tutoring_areas(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_tutoring_areas() -> AreaCatalogue:
    """The bundled catalogue, read once per process (it ships with the code)."""
    return read_tutoring_areas(AREAS_FILE)


__all__ = [
    "AREAS_FILE",
    "AreaCatalogue",
    "AreaCatalogueError",
    "TutoringArea",
    "load_tutoring_areas",
    "parse_tutoring_areas",
    "read_tutoring_areas",
]
