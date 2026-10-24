#!/usr/bin/env python3
r"""Sub-project C P0: build, review and freeze the per-leaf reference for a real script.

Every model call goes through ``GeminiClient`` on ``claude-opus-5-5`` (synchronous
Messages API, never the batches API), inside ``record_calls``, with the combined
cost-ladder spend ledger checked before and booked after. Keys are read inside this
process from ``~/.config/lemely/{anthropic,gemini}_key`` and never printed. Every file
written holds student marks and stays under the gitignored BUILD tree.

    build_reference.py prepare KEY --scan PDF (--scheme-json JSON | --scheme-pdf PDF)
    build_reference.py mark KEY --mode {opus,teacher,mcq} [--truth PDF] --max-usd 1.5
    build_reference.py adopt KEY --from {opus,teacher,mcq}
    build_reference.py review-list KEY [--prior gemini=correction.json ...] [--expected-total N]
    build_reference.py crop KEY --leaf QID --out crop.png [--extracted extracted.json] [--page N]
    build_reference.py override KEY --leaf QID --mark N [--note TEXT]
    build_reference.py freeze KEY [--expected-total N] [--source corrected_copy=PDF ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder.spend import (
    DEFAULT_SPEND_FILE,
    SpendCapError,
    SpendCaps,
    SpendLedger,
    check_can_start,
    cost_by_provider,
)
from lemely.core.loose_schemas import MarkScheme

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import Settings

OPUS = "claude-opus-5-5"
TASK_TAG = "reference"
PROMPT_VERSION = "c-reference-v1"
_KEY_FILES = (
    ("ANTHROPIC_API_KEY", "~/.config/lemely/anthropic_key"),
    ("GEMINI_API_KEY", "~/.config/lemely/gemini_key"),
)

_OPUS_SYSTEM = (
    "You are a senior Cambridge IGCSE examiner building a reference marking of one "
    "handwritten script. Mark every leaf listed against its mark scheme points only. "
    "For each leaf give the mark, your confidence from 0 to 1, the student's words or "
    "working that earn each mark quoted exactly (or '-' when nothing earns a mark), and "
    "the 1-based page the answer is on. Set ambiguous when you cannot read the answer "
    "well enough to be sure."
)
_TEACHER_SYSTEM = (
    "You are transcribing a teacher's marking of a handwritten script. The pages carry the "
    "teacher's red ticks and crosses. For each leaf listed, count the ticks the teacher "
    "gave that leaf: that count is its mark. Quote what the tick sits next to as the "
    "evidence and give the 1-based page. Do not mark the answer yourself. Set ambiguous "
    "when a tick could belong to more than one leaf, or is hard to count; confidence is "
    "how sure you are of the count."
)
_MCQ_SYSTEM = (
    "You are reading a multiple-choice script that a teacher has marked. For each leaf "
    "listed, if the teacher's tick or cross is legible, the mark is 1 for a tick and 0 for "
    "a cross. If not, read the letter the student chose, quote it as the evidence, and "
    "give the mark the key in the mark scheme gives that letter. Give the 1-based page. "
    "Set ambiguous when the chosen letter or the tick is unclear."
)
_SYSTEM_FOR = {"opus": _OPUS_SYSTEM, "teacher": _TEACHER_SYSTEM, "mcq": _MCQ_SYSTEM}


class ReferenceLeafReply(BaseModel):
    question_id: str
    mark: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    page: int | None = None
    ambiguous: bool = False


class ReferenceReply(BaseModel):
    leaves: list[ReferenceLeafReply]


def scheme_leaves(scheme: MarkScheme) -> dict[str, int]:
    """Leaf id to maximum marks, for every marked leaf of *scheme*."""
    return {q.id: q.marks for q in scheme.all_questions_flat() if q.marks > 0 and not q.parts}


MARKED_INPUT_REASON = (
    "the only copy of this MCQ script carries the teacher's ticks, so the marked copy is the "
    "pipeline input (user decision)"
)
MISSING_NOTE = "not returned by the model"
_CLAMP_PREFIX = "model gave "


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({qid for qid in ids if ids.count(qid) > 1})


def leaves_from_marks(
    marks: list[dict[str, Any]], scheme: MarkScheme, source: ref.Source
) -> list[ref.ReferenceLeaf]:
    """Reference leaves from a marks file.

    A leaf the model left out is 0 with `MISSING_NOTE`; a mark above the leaf maximum is
    clamped with a ``model gave N above max M`` note. ``flags_from_notes`` lists both
    for review. A duplicate or unknown question id raises.
    """
    maxima = scheme_leaves(scheme)
    ids = [str(row["question_id"]) for row in marks]
    duplicated = _duplicates(ids)
    if duplicated:
        raise ref.ReferenceStateError(f"marks repeat a question id: {', '.join(duplicated)}")
    by_id: dict[str, dict[str, Any]] = {}
    for row in marks:
        qid = str(row["question_id"])
        if qid not in maxima:
            raise ref.ReferenceStateError(f"marks name a leaf the scheme does not have: {qid}")
        by_id[qid] = row
    leaves: list[ref.ReferenceLeaf] = []
    for qid, max_marks in maxima.items():
        row = by_id.get(qid)
        if row is None:
            leaves.append(ref.ReferenceLeaf(qid, 0, max_marks, source, "-", MISSING_NOTE))
            continue
        note = "ambiguous" if row.get("ambiguous") else ""
        given = int(row["mark"])
        mark = min(given, max_marks)
        if mark != given:
            note = (note + "; " if note else "") + f"{_CLAMP_PREFIX}{given} above max {max_marks}"
        leaves.append(ref.ReferenceLeaf(qid, mark, max_marks, source, str(row["evidence"]), note))
    return leaves


def flags_from_notes(reference: Mapping[str, ref.ReferenceLeaf]) -> dict[str, str]:
    """Leaves whose note says the model skipped or over-marked them, with the reason."""
    flags: dict[str, str] = {}
    for qid, leaf in reference.items():
        if leaf.source == "user_override":
            continue
        reasons = [
            p
            for p in (x.strip() for x in leaf.note.split(";"))
            if p == MISSING_NOTE or p.startswith(_CLAMP_PREFIX)
        ]
        if reasons:
            flags[qid] = "; ".join(reasons)
    return flags


def _read_marks(path: Path) -> list[dict[str, Any]]:
    """The rows of a ``marks_<mode>.json``, checked for shape; malformed input raises."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["leaves"]
        for row in rows:
            str(row["question_id"])
            int(row["mark"])
            float(row["confidence"])
            row["evidence"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ref.ReferenceStateError(f"{path} is malformed ({type(exc).__name__}: {exc})") from exc
    if not isinstance(rows, list):
        raise ref.ReferenceStateError(f"{path} is malformed: 'leaves' is not a list")
    duplicated = _duplicates([str(r["question_id"]) for r in rows])
    if duplicated:
        raise ref.ReferenceStateError(f"{path} repeats a question id: {', '.join(duplicated)}")
    return list(rows)


def marks_from_correction(path: Path) -> dict[str, int]:
    """Awarded marks per leaf from a stored ``correction.json`` (CorrectionResult)."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["questions"]
        pairs = [(str(q["question_id"]), int(q["awarded_marks"])) for q in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ref.ReferenceStateError(f"{path} is malformed ({type(exc).__name__}: {exc})") from exc
    duplicated = _duplicates([qid for qid, _ in pairs])
    if duplicated:
        raise ref.ReferenceStateError(f"{path} repeats a question id: {', '.join(duplicated)}")
    return dict(pairs)


def _load_keys() -> None:
    for var, key_path in _KEY_FILES:
        path = Path(key_path).expanduser()
        if path.is_file():
            os.environ.setdefault(var, path.read_text(encoding="utf-8").strip())


def _pages(path: Path) -> list[bytes]:
    from lemely.io.rasterise import rasterise_scan_to_pages

    return [page.png_bytes for page in rasterise_scan_to_pages(path)]


def _client(settings: Settings) -> GeminiClient:
    from lemely.io.gemini import GeminiClient

    # read_write on the script's own cache dir: a rerun of `mark` replays the reply ($0).
    return GeminiClient(settings, default_cache_mode="read_write")


def _settings(script_dir: Path) -> Settings:
    from lemely.runtime.config import load_settings

    s = load_settings()
    paths = s.paths.model_copy(update={"cache_dir": script_dir / "cache"})
    return s.model_copy(update={"paths": paths})


def _scheme(script_dir: Path) -> MarkScheme:
    return MarkScheme.model_validate_json((script_dir / ref.SCHEME_FILE).read_text("utf-8"))


def _inputs(script_dir: Path) -> dict[str, str]:
    path = script_dir / "inputs.json"
    if not path.is_file():
        raise ref.ReferenceStateError(f"{path} missing: run `prepare` first")
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _prepare(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    script_dir.mkdir(parents=True, exist_ok=True)
    if args.scheme_json is not None:
        scheme = MarkScheme.model_validate_json(args.scheme_json.read_text(encoding="utf-8"))
        source = str(args.scheme_json)
    else:
        from lemely.io.det import DeterministicMarkSchemeParser
        from lemely.runtime.config import load_settings

        try:
            scheme = DeterministicMarkSchemeParser(cfg=load_settings().det_parser)(args.scheme_pdf)
            source = f"det:{args.scheme_pdf}"
        except Exception as exc:
            raise ref.ReferenceStateError(
                f"the deterministic parser failed on {args.scheme_pdf} ({exc}); parse it with "
                "`lemely parse-mark-schemes` and pass --scheme-json"
            ) from exc
    (script_dir / ref.SCHEME_FILE).write_text(scheme.model_dump_json(indent=1), encoding="utf-8")
    (script_dir / "inputs.json").write_text(
        json.dumps({"scan": str(args.scan.resolve()), "scheme_source": source}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"prepared {args.key}: {len(scheme_leaves(scheme))} leaves, scheme from {source}")
    return 0


def _leaf_list(scheme: MarkScheme) -> str:
    from lemely.io.prompts.correction_ai import render_paper_mark_scheme

    leaves = ", ".join(f"{qid} (max {m})" for qid, m in scheme_leaves(scheme).items())
    return f"Leaves to mark: {leaves}\n\nMark scheme:\n{render_paper_mark_scheme(scheme)}"


def _mark_full(args: argparse.Namespace, script_dir: Path) -> int:
    """$0, no client and no ledger: every scheme leaf at its maximum, on a stated basis."""
    basis = (args.basis or "").strip()
    if not basis:
        raise ref.ReferenceStateError("--mode full needs --basis: why every answer is correct")
    rows = [
        {
            "question_id": qid,
            "mark": max_marks,
            "confidence": 1.0,
            "evidence": basis,
            "page": None,
            "ambiguous": False,
        }
        for qid, max_marks in scheme_leaves(_scheme(script_dir)).items()
    ]
    out = script_dir / "marks_full.json"
    out.write_text(json.dumps({"leaves": rows, "basis": basis}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} leaves at full marks, no model call)")
    return 0


def _mark(args: argparse.Namespace) -> int:
    from lemely.io.gemini import process_call_records, record_calls, set_call_context

    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    if args.mode == "full":
        return _mark_full(args, script_dir)
    if args.mode in ("teacher", "mcq") and args.truth is None:
        raise ref.ReferenceStateError(f"--mode {args.mode} reads the marked copy: pass --truth")
    scheme = _scheme(script_dir)
    scan = Path(_inputs(script_dir)["scan"])
    if args.allow_marked_input and args.mode != "mcq":
        raise ref.ReferenceStateError("--allow-marked-input is only valid with --mode mcq")
    truth_sha: str | None = None
    marked_input = False
    if args.mode in ("teacher", "mcq"):
        truth_sha = ref.sha256_file(args.truth)
        if scan.is_file() and truth_sha == ref.sha256_file(scan):
            if not args.allow_marked_input:
                raise ref.ReferenceStateError(
                    f"--truth {args.truth} is the prepared scan itself: the marked copy must not "
                    "be the pipeline input (mcq only: --allow-marked-input)"
                )
            marked_input = True
    pages_from = args.truth if truth_sha is not None else scan
    ledger = SpendLedger(args.spend_file)
    check_can_start(ledger.spent(), {"anthropic": args.max_usd}, SpendCaps())
    _load_keys()
    settings = _settings(script_dir)
    client = _client(settings)
    with record_calls():
        set_call_context(case_key=f"reference:{args.key}")
        try:
            reply = client.generate_structured(
                system_prompt=_SYSTEM_FOR[args.mode],
                user_prompt=_leaf_list(scheme),
                image_parts=_pages(pages_from),
                response_schema=ReferenceReply,
                prompt_version=PROMPT_VERSION,
                model=OPUS,
                task_tag=TASK_TAG,
                cache_mode="read_write",
                extra_cache_key=f"{args.key}:{args.mode}",
            )
        except Exception as exc:
            raise ref.ReferenceStateError(
                f"model call failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            set_call_context(case_key=None)
            spent = cost_by_provider(process_call_records())
            ledger.add(spent)
            print(f"spend this call: {spent}")
    if spent.get("anthropic", 0.0) > args.max_usd:
        print(
            f"warning: anthropic spend {spent['anthropic']:.4f} exceeded --max-usd {args.max_usd}",
            file=sys.stderr,
        )
    out = script_dir / f"marks_{args.mode}.json"
    payload: dict[str, Any] = {"leaves": [leaf.model_dump() for leaf in reply.leaves]}
    if truth_sha is not None:
        payload["truth"] = {"path": str(args.truth), "sha256": truth_sha}
    if marked_input:
        payload["marked_input"] = True
        payload["marked_input_reason"] = MARKED_INPUT_REASON
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(reply.leaves)} leaves)")
    return 0


def _adopt(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    rows = _read_marks(script_dir / f"marks_{args.source}.json")
    sources: dict[str, ref.Source] = {"opus": "opus", "full": "fixture_full"}
    source: ref.Source = sources.get(args.source, "teacher_tick")
    leaves = leaves_from_marks(rows, _scheme(script_dir), source)
    if args.source == "full":
        basis = json.loads((script_dir / "marks_full.json").read_text("utf-8"))["basis"]
        leaves = [replace(leaf, note=str(basis)) for leaf in leaves]
    marked = bool(
        json.loads((script_dir / f"marks_{args.source}.json").read_text("utf-8")).get(
            "marked_input"
        )
    )
    (script_dir / "adopted.json").write_text(
        json.dumps({"from": args.source, "marked_input": marked}) + "\n", encoding="utf-8"
    )
    ref.write_reference(script_dir / ref.REFERENCE_FILE, leaves)
    print(f"reference {args.key}: {sum(x.mark for x in leaves)} marks from marks_{args.source}")
    return 0


def _review_list(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    reference = ref.read_reference(script_dir / ref.REFERENCE_FILE)
    others: list[ref.OtherMarks] = []
    confidence: dict[str, float] = {}
    ambiguous: list[str] = []
    adopted_path = script_dir / "adopted.json"
    adopted = (
        json.loads(adopted_path.read_text("utf-8"))["from"] if adopted_path.is_file() else None
    )
    for marks_file in sorted(script_dir.glob("marks_*.json")):
        rows = _read_marks(marks_file)
        name = marks_file.stem.removeprefix("marks_")
        others.append(ref.OtherMarks(name, {str(r["question_id"]): int(r["mark"]) for r in rows}))
        if name != adopted:
            continue
        for r in rows:
            qid = str(r["question_id"])
            if qid in reference and reference[qid].source != "user_override":
                confidence[qid] = float(r["confidence"])
                if r.get("ambiguous"):
                    ambiguous.append(qid)
    for pair in args.prior:
        name, sep, path = pair.partition("=")
        if not sep or not name or not path:
            raise ref.ReferenceStateError(f"--prior {pair!r} is not NAME=correction.json")
        prior = marks_from_correction(Path(path))
        unmatched = sorted(qid for qid in prior if qid not in reference)
        if unmatched:
            raise ref.ReferenceStateError(
                f"prior {name} ({path}) has ids that are not reference leaves: "
                f"{', '.join(unmatched)}"
            )
        others.append(ref.OtherMarks(name, prior))
    flagged = ref.check_first(
        reference,
        others=others,
        confidence=confidence,
        ambiguous=ambiguous,
        flags=flags_from_notes(reference),
        expected_total=args.expected_total,
    )
    out = script_dir / ref.REVIEW_FILE
    out.write_text(ref.render_review(args.key, reference, flagged), encoding="utf-8")
    print(f"{len(flagged)} of {len(reference)} leaves to check first: {out}")
    return 0


def _crop(args: argparse.Namespace) -> int:
    from lemely.io.rasterise import rasterise_scan_to_pages
    from lemely.io.reread import crop_and_upscale

    script_dir: Path = args.root / args.key
    pages = rasterise_scan_to_pages(Path(_inputs(script_dir)["scan"]))
    box: list[int] | None = None
    page_index = None if args.page is None else args.page - 1
    if args.extracted is not None:
        answers = json.loads(args.extracted.read_text(encoding="utf-8"))["answers"]
        for answer in answers:
            if answer["question_id"] == args.leaf and answer.get("source_box"):
                box = answer["source_box"]["box"]
                page_index = answer["source_box"]["page"]
    if page_index is None:
        raise ref.ReferenceStateError(f"no page for {args.leaf}: pass --page or --extracted")
    if not 0 <= page_index < len(pages):
        raise ref.ReferenceStateError(
            f"page {page_index + 1} is outside 1..{len(pages)} for {args.leaf}"
        )
    page = pages[page_index]
    data = crop_and_upscale(page, box, upscale=1) if box is not None else page.png_bytes
    args.out.write_bytes(data)
    print(f"wrote {args.out} (page {page_index + 1}{', cropped' if box else ''})")
    return 0


def _override(args: argparse.Namespace) -> int:
    leaf = ref.apply_override(args.root / args.key, args.leaf, args.mark, args.note)
    print(f"{args.key} {leaf.question_id}: {leaf.mark} / {leaf.max_marks} (user_override)")
    return 0


def _marked_input_recorded(script_dir: Path) -> bool:
    """True when adopted.json or marks_mcq.json records the user-approved marked-copy input."""
    for name in ("adopted.json", "marks_mcq.json"):
        path = script_dir / name
        if path.is_file() and json.loads(path.read_text("utf-8")).get("marked_input") is True:
            return True
    return False


def _freeze(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    sources: dict[str, Path] = {}
    for pair in args.source:
        name, sep, path = pair.partition("=")
        if not sep or not name or not path:
            raise ref.ReferenceStateError(f"--source {pair!r} is not NAME=PATH")
        sources[name] = Path(path)
    scan = Path(_inputs(script_dir)["scan"])
    if scan.is_file():
        scan_sha = ref.sha256_file(scan)
        for name, path in list(sources.items()):
            if path.is_file() and ref.sha256_file(path) == scan_sha:
                if not _marked_input_recorded(script_dir):
                    raise ref.ReferenceStateError(
                        f"--source {name} is the scan itself: the marked copy must not be the input"
                    )
                del sources[name]
                sources[f"marked_copy_is_input={name}"] = path
    entry = ref.freeze(
        script_dir,
        key=args.key,
        scan_path=scan,
        sources=sources,
        expected_total=args.expected_total,
        manifest_path=args.root / ref.MANIFEST_FILE,
    )
    print(f"froze {entry.key}: reference sha256 {entry.reference_sha256[:12]}")
    return 0


def _positive_usd(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError(f"{text} is not above 0")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--root", type=Path, default=ref.REFERENCE_ROOT)
    parser.add_argument("--spend-file", type=Path, default=DEFAULT_SPEND_FILE)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("key")
    p.add_argument("--scan", type=Path, required=True)
    scheme = p.add_mutually_exclusive_group(required=True)
    scheme.add_argument("--scheme-json", type=Path)
    scheme.add_argument("--scheme-pdf", type=Path)
    p.set_defaults(fn=_prepare)

    p = sub.add_parser("mark")
    p.add_argument("key")
    p.add_argument("--mode", choices=[*sorted(_SYSTEM_FOR), "full"], required=True)
    p.add_argument("--basis", help="--mode full: why every answer is correct")
    p.add_argument("--truth", type=Path)
    p.add_argument(
        "--allow-marked-input",
        action="store_true",
        help="mcq only: the ticked copy is the script's only copy and may be the input",
    )
    p.add_argument(
        "--max-usd", type=_positive_usd, default=1.50, help="projected Anthropic cost, above 0"
    )
    p.set_defaults(fn=_mark)

    p = sub.add_parser("adopt")
    p.add_argument("key")
    p.add_argument("--from", dest="source", choices=[*sorted(_SYSTEM_FOR), "full"], required=True)
    p.set_defaults(fn=_adopt)

    p = sub.add_parser("review-list")
    p.add_argument("key")
    p.add_argument("--prior", action="append", default=[], metavar="NAME=correction.json")
    p.add_argument("--expected-total", type=int)
    p.set_defaults(fn=_review_list)

    p = sub.add_parser("crop")
    p.add_argument("key")
    p.add_argument("--leaf", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--extracted", type=Path)
    p.add_argument("--page", type=int, help="1-based page when no extracted box is given")
    p.set_defaults(fn=_crop)

    p = sub.add_parser("override")
    p.add_argument("key")
    p.add_argument("--leaf", required=True)
    p.add_argument("--mark", type=int, required=True)
    p.add_argument("--note", default="")
    p.set_defaults(fn=_override)

    p = sub.add_parser("freeze")
    p.add_argument("key")
    p.add_argument("--expected-total", type=int)
    p.add_argument("--source", action="append", default=[], metavar="NAME=PATH")
    p.set_defaults(fn=_freeze)

    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except (ref.ReferenceStateError, SpendCapError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
