"""Sub-project C P0: the reference builder CLI. Fake client only: no model call, no spend."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy import reference as ref
from lemely.core.loose_schemas import MarkScheme

_SPEC = importlib.util.spec_from_file_location(
    "build_reference", Path(__file__).resolve().parents[1] / "scripts" / "build_reference.py"
)
assert _SPEC is not None and _SPEC.loader is not None
br = importlib.util.module_from_spec(_SPEC)
sys.modules["build_reference"] = br
_SPEC.loader.exec_module(br)

_SCHEME = {
    "metadata": {
        "subject": "Physics",
        "subject_code": "0625",
        "paper_number": 4,
        "paper_variant": 1,
        "session_month": "Oct/Nov",
        "session_year": 2024,
        "paper_type": "theory_extended",
        "maximum_mark": 3,
        "scheme_format": "point_based",
    },
    "questions": [
        {
            "id": "1",
            "marks": 3,
            "type": "recall",
            "parts": [
                {
                    "id": "1a",
                    "parent_id": "1",
                    "marks": 2,
                    "type": "calculation",
                    "answer_points": [
                        {"id": "M1", "point": "uses F = ma", "marks": 1},
                        {"id": "A1", "point": "6 N", "marks": 1},
                    ],
                },
                {
                    "id": "1b",
                    "parent_id": "1",
                    "marks": 1,
                    "type": "recall",
                    "answer_points": [{"id": "B1", "point": "upwards", "marks": 1}],
                },
            ],
        },
    ],
}


def _scheme() -> MarkScheme:
    return MarkScheme.model_validate(_SCHEME)


def test_scheme_leaves_lists_marked_leaves() -> None:
    assert br.scheme_leaves(_scheme()) == {"1a": 2, "1b": 1}


def test_leaves_from_marks_clamps_nothing_and_refuses_unknown_leaf() -> None:
    marks = [
        {
            "question_id": "1a",
            "mark": 2,
            "confidence": 0.9,
            "evidence": "6 N",
            "page": 1,
            "ambiguous": False,
        },
        {
            "question_id": "1b",
            "mark": 0,
            "confidence": 0.7,
            "evidence": "-",
            "page": 1,
            "ambiguous": True,
        },
    ]
    leaves = br.leaves_from_marks(marks, _scheme(), "teacher_tick")
    assert [(x.question_id, x.mark, x.source) for x in leaves] == [
        ("1a", 2, "teacher_tick"),
        ("1b", 0, "teacher_tick"),
    ]
    with pytest.raises(ref.ReferenceStateError, match="9z"):
        br.leaves_from_marks([{**marks[0], "question_id": "9z"}], _scheme(), "opus")


def test_leaves_from_marks_fills_a_missing_leaf_with_zero_and_a_note() -> None:
    leaves = br.leaves_from_marks(
        [
            {
                "question_id": "1a",
                "mark": 1,
                "confidence": 0.9,
                "evidence": "e",
                "page": None,
                "ambiguous": False,
            }
        ],
        _scheme(),
        "opus",
    )
    (missing,) = [x for x in leaves if x.question_id == "1b"]
    assert missing.mark == 0 and "not returned" in missing.note


def test_marks_from_correction_reads_awarded_marks(tmp_path: Path) -> None:
    path = tmp_path / "correction.json"
    path.write_text(
        json.dumps(
            {
                "questions": [
                    {"question_id": "1a", "awarded_marks": 1},
                    {"question_id": "1b", "awarded_marks": 0},
                ]
            }
        )
    )
    assert br.marks_from_correction(path) == {"1a": 1, "1b": 0}


class _FakeClient:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.reply


def test_mark_writes_marks_file_and_books_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF")
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))
    reply = br.ReferenceReply(
        leaves=[
            br.ReferenceLeafReply(question_id="1a", mark=2, confidence=0.9, evidence="6 N"),
            br.ReferenceLeafReply(question_id="1b", mark=1, confidence=0.95, evidence="up"),
        ]
    )
    fake = _FakeClient(reply)
    monkeypatch.setattr(br, "_pages", lambda path: [b"png1", b"png2"])
    monkeypatch.setattr(br, "_client", lambda settings: fake)
    monkeypatch.setattr(br, "_load_keys", lambda: None)
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps({"anthropic": 1.0}))
    assert (
        br.main(
            [
                "--root",
                str(root),
                "--spend-file",
                str(spend),
                "mark",
                "k",
                "--mode",
                "opus",
                "--max-usd",
                "2.0",
            ]
        )
        == 0
    )
    (call,) = fake.calls
    assert call["model"] == br.OPUS and call["task_tag"] == br.TASK_TAG
    assert call["image_parts"] == [b"png1", b"png2"]
    assert call["cache_mode"] == "read_write"
    data = json.loads((d / "marks_opus.json").read_text())
    assert [x["question_id"] for x in data["leaves"]] == ["1a", "1b"]


def test_mark_refuses_before_spend_when_the_cap_would_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ref"
    (root / "k").mkdir(parents=True)
    (root / "k" / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (root / "k" / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path), "scheme_source": "x"})
    )
    monkeypatch.setattr(br, "_load_keys", lambda: None)

    def boom(settings: object) -> object:
        raise AssertionError("must not build a client")

    monkeypatch.setattr(br, "_client", boom)
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps({"anthropic": 39.5}))
    assert (
        br.main(
            [
                "--root",
                str(root),
                "--spend-file",
                str(spend),
                "mark",
                "k",
                "--mode",
                "opus",
                "--max-usd",
                "1.0",
            ]
        )
        == 2
    )


def test_teacher_mode_needs_truth_and_sends_its_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "scan.pdf"), "scheme_source": "x"})
    )
    monkeypatch.setattr(br, "_load_keys", lambda: None)
    assert br.main(["--root", str(root), "mark", "k", "--mode", "teacher"]) == 2
    truth = tmp_path / "ticks.pdf"
    truth.write_bytes(b"%PDF")
    seen: list[Path] = []
    monkeypatch.setattr(br, "_pages", lambda path: seen.append(path) or [b"t"])
    fake = _FakeClient(br.ReferenceReply(leaves=[]))
    monkeypatch.setattr(br, "_client", lambda settings: fake)
    spend = tmp_path / "spend.json"
    assert (
        br.main(
            [
                "--root",
                str(root),
                "--spend-file",
                str(spend),
                "mark",
                "k",
                "--mode",
                "teacher",
                "--truth",
                str(truth),
                "--max-usd",
                "1",
            ]
        )
        == 0
    )
    assert seen == [truth]
    assert "tick" in fake.calls[0]["system_prompt"].lower()


def test_adopt_review_override_freeze_round(tmp_path: Path) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF")
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))
    (d / "marks_teacher.json").write_text(
        json.dumps(
            {
                "leaves": [
                    {
                        "question_id": "1a",
                        "mark": 2,
                        "confidence": 0.9,
                        "evidence": "tick tick",
                        "page": 1,
                        "ambiguous": False,
                    },
                    {
                        "question_id": "1b",
                        "mark": 0,
                        "confidence": 0.6,
                        "evidence": "-",
                        "page": 1,
                        "ambiguous": True,
                    },
                ]
            }
        )
    )
    prior = tmp_path / "gemini.json"
    prior.write_text(
        json.dumps(
            {
                "questions": [
                    {"question_id": "1a", "awarded_marks": 1},
                    {"question_id": "1b", "awarded_marks": 0},
                ]
            }
        )
    )
    assert br.main(["--root", str(root), "adopt", "k", "--from", "teacher"]) == 0
    assert (
        br.main(
            [
                "--root",
                str(root),
                "review-list",
                "k",
                "--prior",
                f"gemini={prior}",
                "--expected-total",
                "3",
            ]
        )
        == 0
    )
    review = (d / ref.REVIEW_FILE).read_text()
    assert "| 1a |" in review and "| 1b |" in review
    assert (
        br.main(
            [
                "--root",
                str(root),
                "override",
                "k",
                "--leaf",
                "1b",
                "--mark",
                "1",
                "--note",
                "tick under the line",
            ]
        )
        == 0
    )
    assert br.main(["--root", str(root), "freeze", "k", "--expected-total", "3"]) == 0
    (entry,) = ref.read_manifest(root / ref.MANIFEST_FILE)
    assert entry.key == "k"
    assert br.main(["--root", str(root), "override", "k", "--leaf", "1b", "--mark", "0"]) == 2


def _adopted(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "s.pdf"), "scheme_source": "x"})
    )
    (d / "marks_opus.json").write_text(
        json.dumps(
            {
                "leaves": [
                    {
                        "question_id": "1a",
                        "mark": 2,
                        "confidence": 0.9,
                        "evidence": "e",
                        "page": 1,
                        "ambiguous": False,
                    },
                    {
                        "question_id": "1b",
                        "mark": 1,
                        "confidence": 0.9,
                        "evidence": "e",
                        "page": 1,
                        "ambiguous": False,
                    },
                ]
            }
        )
    )
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 0
    return root, d


def test_review_list_fails_clearly_on_prior_ids_that_are_not_leaves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, d = _adopted(tmp_path)
    prior = tmp_path / "gemini.json"
    prior.write_text(
        json.dumps(
            {
                "questions": [
                    {"question_id": "1a", "awarded_marks": 2},
                    {"question_id": "1(b)", "awarded_marks": 1},
                    {"question_id": "7z", "awarded_marks": 0},
                ]
            }
        )
    )
    assert br.main(["--root", str(root), "review-list", "k", "--prior", f"gemini={prior}"]) == 2
    err = capsys.readouterr().err
    assert "gemini" in err and "1(b)" in err and "7z" in err
    assert not (d / ref.REVIEW_FILE).exists()


def test_review_list_fails_clearly_on_a_malformed_prior_argument(tmp_path: Path) -> None:
    root, _ = _adopted(tmp_path)
    assert br.main(["--root", str(root), "review-list", "k", "--prior", "no-equals-sign"]) == 2
