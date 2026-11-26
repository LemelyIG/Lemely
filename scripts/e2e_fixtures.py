"""Constants shared by the Playwright database scripts and the test suite.

One definition each, so the scripts that build the disposable ``lemely_e2e``
database and the tests that pin them cannot drift apart. Import it as
``scripts.e2e_fixtures`` (``web/playwright.config.ts`` pins ``PYTHONPATH`` to the
checkout, which is what makes ``scripts`` importable from a script run by path).
"""

from __future__ import annotations

from typing import Final

#: The only database the Playwright reset may drop, exactly.
E2E_DATABASE_NAME: Final = "lemely_e2e"

#: Every account an e2e run creates in GoTrue is on this domain: the seed
#: (``scripts/seed_e2e.py`` ``EMAIL_DOMAIN``, pinned equal by a test) and the specs
#: that sign up through the app. GoTrue's ``auth`` schema lives in the shared
#: ``postgres`` database and survives the reset, so this suffix is the only thing
#: that lets ``scripts/reset_e2e_db.py`` clean those accounts up without ever
#: touching anyone else's.
E2E_EMAIL_DOMAIN: Final = "e2e.lemely.local"

#: (subject_code, session_year, paper_number, max_mark, thresholds, source_url) for
#: the synthetic ``component_thresholds`` rows both the Playwright database and
#: ``tests/conftest.py``'s ambient-database fixture install. All May/June, variant 1,
#: ``verified=True``. Clearly-fake data (``example.invalid`` sources), not exam board
#: data; see the docstring of ``_seed_ambient_grade_boundaries`` for why each row
#: exists.
BOUNDARY_FIXTURE_ROWS: Final[tuple[tuple[str, int, int, int, dict[str, int], str], ...]] = (
    (
        "0625",
        2023,
        1,
        40,
        {"C": 25, "D": 22, "E": 19, "F": 16, "G": 13},
        "https://example.invalid/test-fixture/0625_s23_p11.pdf",
    ),
    (
        "0625",
        2024,
        1,
        40,
        {"C": 26, "D": 23, "E": 20, "F": 17, "G": 14},
        "https://example.invalid/test-fixture/0625_s24_p11.pdf",
    ),
    (
        "0625",
        2019,
        2,
        50,
        {"A": 35, "B": 29, "C": 25, "D": 21, "E": 17, "F": 13, "G": 9},
        "https://example.invalid/test-fixture/0625_s19_p21.pdf",
    ),
    (
        "0000",
        2024,
        1,
        100,
        {"A": 80, "B": 70, "C": 60, "D": 50, "E": 40, "F": 30, "G": 20},
        "https://example.invalid/test-fixture/0000_s24_p11.pdf",
    ),
)
