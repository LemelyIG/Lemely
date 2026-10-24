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


def test_leaves_from_marks_keeps_marks_in_range_and_refuses_unknown_leaf() -> None:
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


def _write_inputs(d: Path, scan: Path) -> None:
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))


def _row(qid: str, mark: int, **extra: Any) -> dict[str, Any]:
    return {
        "question_id": qid,
        "mark": mark,
        "confidence": 0.95,
        "evidence": "e",
        "page": 1,
        "ambiguous": False,
        **extra,
    }


def _write_marks(d: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (d / f"marks_{name}.json").write_text(json.dumps({"leaves": rows}))


def test_review_list_flags_a_leaf_the_model_skipped(tmp_path: Path) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "s.pdf"), "scheme_source": "x"})
    )
    _write_marks(d, "opus", [_row("1a", 2)])
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 0
    assert br.main(["--root", str(root), "review-list", "k"]) == 0
    review = (d / ref.REVIEW_FILE).read_text()
    assert "| 1b |" in review and "not returned by the model" in review
    assert "| 1a |" not in review


def test_clamped_mark_is_flagged_with_the_given_and_max(tmp_path: Path) -> None:
    (leaf,) = [
        x
        for x in br.leaves_from_marks([_row("1a", 5), _row("1b", 1)], _scheme(), "opus")
        if x.question_id == "1a"
    ]
    assert leaf.mark == 2 and "model gave 5 above max 2" in leaf.note
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "s.pdf"), "scheme_source": "x"})
    )
    _write_marks(d, "opus", [_row("1a", 5), _row("1b", 1)])
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 0
    assert br.main(["--root", str(root), "review-list", "k"]) == 0
    assert "model gave 5 above max 2" in (d / ref.REVIEW_FILE).read_text()


def test_override_clears_the_skipped_flag(tmp_path: Path) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "s.pdf"), "scheme_source": "x"})
    )
    _write_marks(d, "opus", [_row("1a", 2)])
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 0
    assert br.main(["--root", str(root), "override", "k", "--leaf", "1b", "--mark", "1"]) == 0
    assert br.main(["--root", str(root), "review-list", "k"]) == 0
    assert "| 1b |" not in (d / ref.REVIEW_FILE).read_text()


def test_duplicate_question_ids_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ref.ReferenceStateError, match="1a"):
        br.leaves_from_marks([_row("1a", 1), _row("1a", 2)], _scheme(), "opus")
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    _write_marks(d, "opus", [_row("1a", 1), _row("1a", 2), _row("1b", 1)])
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 2
    assert "1a" in capsys.readouterr().err
    prior = tmp_path / "c.json"
    prior.write_text(
        json.dumps(
            {
                "questions": [
                    {"question_id": "1a", "awarded_marks": 1},
                    {"question_id": "1a", "awarded_marks": 2},
                ]
            }
        )
    )
    with pytest.raises(ref.ReferenceStateError, match="1a"):
        br.marks_from_correction(prior)


def test_malformed_marks_file_is_an_error_line_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "marks_opus.json").write_text(json.dumps({"rows": []}))
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 2
    assert capsys.readouterr().err.startswith("error:")
    (d / "marks_opus.json").write_text(json.dumps({"leaves": [{"question_id": "1a"}]}))
    assert br.main(["--root", str(root), "adopt", "k", "--from", "opus"]) == 2


def _mark_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: Any) -> tuple[Path, Path]:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF scan")
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))
    monkeypatch.setattr(br, "_pages", lambda path: [b"png"])
    monkeypatch.setattr(br, "_client", lambda settings: fake)
    monkeypatch.setattr(br, "_load_keys", lambda: None)
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps({"anthropic": 1.0}))
    return root, spend


def test_mark_books_the_spend_even_when_the_call_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lemely.io.gemini as gem

    class _Boom:
        def generate_structured(self, **kwargs: Any) -> Any:
            raise RuntimeError("overloaded")

    root, spend = _mark_setup(tmp_path, monkeypatch, _Boom())
    monkeypatch.setattr(gem, "process_call_records", lambda: [object()])
    monkeypatch.setattr(br, "cost_by_provider", lambda recs: {"anthropic": 0.25})
    assert (
        br.main(["--root", str(root), "--spend-file", str(spend), "mark", "k", "--mode", "opus"])
        == 2
    )
    assert json.loads(spend.read_text())["anthropic"] == pytest.approx(1.25)


def test_mark_books_the_spend_and_warns_when_over_max_usd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import lemely.io.gemini as gem

    fake = _FakeClient(br.ReferenceReply(leaves=[]))
    root, spend = _mark_setup(tmp_path, monkeypatch, fake)
    monkeypatch.setattr(gem, "process_call_records", lambda: [object()])
    monkeypatch.setattr(br, "cost_by_provider", lambda recs: {"anthropic": 0.75})
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
                "0.5",
            ]
        )
        == 0
    )
    assert json.loads(spend.read_text())["anthropic"] == pytest.approx(1.75)
    assert "exceeded --max-usd" in capsys.readouterr().err


def test_max_usd_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        br.main(["--root", str(tmp_path), "mark", "k", "--mode", "opus", "--max-usd", "0"])


def test_truth_identical_to_the_scan_is_refused_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spend = _mark_setup(tmp_path, monkeypatch, _FakeClient(br.ReferenceReply(leaves=[])))
    same = tmp_path / "copy.pdf"
    same.write_bytes(b"%PDF scan")
    monkeypatch.setattr(br, "_client", lambda s: (_ for _ in ()).throw(AssertionError("no call")))
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
                str(same),
            ]
        )
        == 2
    )


def test_teacher_marks_file_records_the_truth_path_and_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient(br.ReferenceReply(leaves=[]))
    root, spend = _mark_setup(tmp_path, monkeypatch, fake)
    truth = tmp_path / "ticks.pdf"
    truth.write_bytes(b"%PDF ticks")
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
            ]
        )
        == 0
    )
    data = json.loads((root / "k" / "marks_teacher.json").read_text())
    assert data["truth"] == {"path": str(truth), "sha256": ref.sha256_file(truth)}


def test_freeze_refuses_a_source_that_is_the_scan_and_a_malformed_source(tmp_path: Path) -> None:
    root, d = _adopted(tmp_path)
    scan = tmp_path / "s.pdf"
    scan.write_bytes(b"%PDF scan")
    twin = tmp_path / "twin.pdf"
    twin.write_bytes(b"%PDF scan")
    assert br.main(["--root", str(root), "freeze", "k", "--source", f"copy={twin}"]) == 2
    assert br.main(["--root", str(root), "freeze", "k", "--source", "no-equals"]) == 2
    assert not ref.is_frozen(d)
    assert br.main(["--root", str(root), "freeze", "k"]) == 0


def test_review_list_uses_the_adopted_files_confidence_only(tmp_path: Path) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(
        json.dumps({"scan": str(tmp_path / "s.pdf"), "scheme_source": "x"})
    )
    _write_marks(d, "teacher", [_row("1a", 2, confidence=0.3), _row("1b", 1)])
    _write_marks(d, "mcq", [_row("1a", 2, confidence=0.99), _row("1b", 1)])
    assert br.main(["--root", str(root), "adopt", "k", "--from", "teacher"]) == 0
    assert br.main(["--root", str(root), "review-list", "k"]) == 0
    review = (d / ref.REVIEW_FILE).read_text()
    assert review.count("| 1a |") == 1 and "confidence 0.30" in review
    assert br.main(["--root", str(root), "adopt", "k", "--from", "mcq"]) == 0
    assert br.main(["--root", str(root), "review-list", "k"]) == 0
    assert "| 1a |" not in (d / ref.REVIEW_FILE).read_text()


def test_crop_page_out_of_range_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _adopted(tmp_path)
    import lemely.io.rasterise as ras

    monkeypatch.setattr(ras, "rasterise_scan_to_pages", lambda p: [object(), object()])
    out = tmp_path / "o.png"
    for page in ("0", "3"):
        assert (
            br.main(
                [
                    "--root",
                    str(root),
                    "crop",
                    "k",
                    "--leaf",
                    "1a",
                    "--out",
                    str(out),
                    "--page",
                    page,
                ]
            )
            == 2
        )
