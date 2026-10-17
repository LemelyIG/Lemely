from pathlib import Path

from lemely.core.schemas import ExtractedAnswers

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "binding" / "0625_w24_41"
NAMES = [
    "full_shift_lite",
    "full_shift_38_a",
    "full_shift_38_b",
    "full_shift_38_c",
    "chaotic",
    "partial_a",
    "partial_b",
    "aligned",
]


def _load(name: str) -> ExtractedAnswers:
    return ExtractedAnswers.model_validate_json((FIXTURE_DIR / f"{name}.json").read_text())


def test_fixture_set_is_complete():
    for name in NAMES:
        assert (FIXTURE_DIR / f"{name}.json").is_file(), name
        assert _load(name).answers


def test_fixtures_carry_no_local_paths():
    for name in NAMES:
        text = (FIXTURE_DIR / f"{name}.json").read_text()
        assert "/home/" not in text, name
        assert "/tmp/" not in text, name  # noqa: S108
        assert _load(name).source_scan == "0625_w24_41_student_scan.pdf"


def test_aligned_fixture_matches_the_scan():
    by_id = {a.question_id: a for a in _load("aligned").answers}
    assert "43" in by_id["1a_i"].answer
    assert "63" in by_id["1a_i"].answer
    assert "20" in by_id["1a_ii"].answer
    assert "4.5" in by_id["9c_iv"].answer
    assert "7c" not in by_id
