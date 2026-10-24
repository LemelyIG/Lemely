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


def leaves_from_marks(
    marks: list[dict[str, Any]], scheme: MarkScheme, source: ref.Source
) -> list[ref.ReferenceLeaf]:
    """Reference leaves from a marks file; a leaf the model left out is 0 with a note."""
    maxima = scheme_leaves(scheme)
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
            leaves.append(
                ref.ReferenceLeaf(qid, 0, max_marks, source, "-", "not returned by the model")
            )
            continue
        note = "ambiguous" if row.get("ambiguous") else ""
        mark = min(int(row["mark"]), max_marks)
        if mark != int(row["mark"]):
            note = (note + "; " if note else "") + f"model gave {row['mark']}, above the maximum"
        leaves.append(ref.ReferenceLeaf(qid, mark, max_marks, source, str(row["evidence"]), note))
    return leaves


def marks_from_correction(path: Path) -> dict[str, int]:
    """Awarded marks per leaf from a stored ``correction.json`` (CorrectionResult)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(q["question_id"]): int(q["awarded_marks"]) for q in data["questions"]}


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


def _mark(args: argparse.Namespace) -> int:
    from lemely.io.gemini import process_call_records, record_calls, set_call_context

    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    if args.mode in ("teacher", "mcq") and args.truth is None:
        raise ref.ReferenceStateError(f"--mode {args.mode} reads the marked copy: pass --truth")
    scheme = _scheme(script_dir)
    pages_from = (
        args.truth if args.mode in ("teacher", "mcq") else Path(_inputs(script_dir)["scan"])
    )
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
        finally:
            set_call_context(case_key=None)
            spent = cost_by_provider(process_call_records())
            ledger.add(spent)
            print(f"spend this call: {spent}")
    out = script_dir / f"marks_{args.mode}.json"
    out.write_text(
        json.dumps({"leaves": [leaf.model_dump() for leaf in reply.leaves]}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(reply.leaves)} leaves)")
    return 0


def _adopt(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    marks = json.loads((script_dir / f"marks_{args.source}.json").read_text(encoding="utf-8"))
    source: ref.Source = "opus" if args.source == "opus" else "teacher_tick"
    leaves = leaves_from_marks(marks["leaves"], _scheme(script_dir), source)
    ref.write_reference(script_dir / ref.REFERENCE_FILE, leaves)
    print(f"reference {args.key}: {sum(x.mark for x in leaves)} marks from marks_{args.source}")
    return 0


def _review_list(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    reference = ref.read_reference(script_dir / ref.REFERENCE_FILE)
    others: list[ref.OtherMarks] = []
    confidence: dict[str, float] = {}
    ambiguous: list[str] = []
    for marks_file in sorted(script_dir.glob("marks_*.json")):
        rows = json.loads(marks_file.read_text(encoding="utf-8"))["leaves"]
        name = marks_file.stem.removeprefix("marks_")
        others.append(ref.OtherMarks(name, {str(r["question_id"]): int(r["mark"]) for r in rows}))
        source_name = "opus" if name == "opus" else "teacher_tick"
        for r in rows:
            qid = str(r["question_id"])
            if qid in reference and reference[qid].source == source_name:
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
    page = pages[page_index]
    data = crop_and_upscale(page, box, upscale=1) if box is not None else page.png_bytes
    args.out.write_bytes(data)
    print(f"wrote {args.out} (page {page_index + 1}{', cropped' if box else ''})")
    return 0


def _override(args: argparse.Namespace) -> int:
    leaf = ref.apply_override(args.root / args.key, args.leaf, args.mark, args.note)
    print(f"{args.key} {leaf.question_id}: {leaf.mark} / {leaf.max_marks} (user_override)")
    return 0


def _freeze(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    sources = {name: Path(p) for name, _, p in (s.partition("=") for s in args.source)}
    entry = ref.freeze(
        script_dir,
        key=args.key,
        scan_path=Path(_inputs(script_dir)["scan"]),
        sources=sources,
        expected_total=args.expected_total,
        manifest_path=args.root / ref.MANIFEST_FILE,
    )
    print(f"froze {entry.key}: reference sha256 {entry.reference_sha256[:12]}")
    return 0


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
    p.add_argument("--mode", choices=sorted(_SYSTEM_FOR), required=True)
    p.add_argument("--truth", type=Path)
    p.add_argument("--max-usd", type=float, default=1.50, help="projected Anthropic cost")
    p.set_defaults(fn=_mark)

    p = sub.add_parser("adopt")
    p.add_argument("key")
    p.add_argument("--from", dest="source", choices=sorted(_SYSTEM_FOR), required=True)
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
