"""Every scan refusal carries a reason code that survives pickling (#276, #273)."""

from __future__ import annotations

import ast
import pickle
import unittest
from pathlib import Path

from lemely.io import pdf_content_walk, scan_limits
from lemely.io._scan_common import (
    _OBJECT_STREAM_SEPARATOR_MESSAGE,
    ScanRejectedError,
    ScanTooLargeError,
)
from lemely.io.pdf_prescan import check_object_stream_bytes
from tests.pdf_fakes import shared_container_broken_xref_pdf

_ROOT = Path(__file__).resolve().parent.parent
_SOURCES = {
    path: ast.parse(path.read_text(encoding="utf-8"))
    for path in sorted((_ROOT / "lemely").rglob("*.py"))
}


def _base_name(node: ast.expr) -> str:
    """The name a class base or a callee is spelled with: ``X`` or ``mod.X``."""
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def _error_class_names(trees: list[ast.Module]) -> frozenset[str]:
    """``ScanRejectedError`` and every class in ``trees`` that derives from it.

    Final review R2 M3: derived from the source to a fixpoint, not listed by
    hand, so a new subclass is swept the day it is written.
    """
    classes = [
        (node.name, {_base_name(base) for base in node.bases})
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    names = {"ScanRejectedError"}
    grew = True
    while grew:
        found = {name for name, bases in classes if bases & names}
        grew = not found <= names
        names |= found
    return frozenset(names)


_ERROR_NAMES = _error_class_names(list(_SOURCES.values()))


def _refusal_calls_in(tree: ast.Module, names: frozenset[str]) -> list[ast.Call]:
    """Every call in ``tree`` that builds one of the error classes ``names``.

    Every construction counts, not only one under ``raise``: an error built
    by a factory and raised later carries the reason it was built with. A
    class imported under another name is followed through its alias.
    """
    aliases = {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in names and alias.asname
    }
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _base_name(node.func) in names | aliases
    ]


def _refusal_calls() -> list[tuple[Path, ast.Call]]:
    """Every construction of a refusal in ``lemely/``, with the file it is in."""
    return [
        (path, call)
        for path, tree in _SOURCES.items()
        for call in _refusal_calls_in(tree, _ERROR_NAMES)
    ]


def _reason_values(call: ast.Call) -> list[ast.expr]:
    """What a construction passes as its reason: ``reason=``, the second
    positional argument, or a ``**`` mapping (which is never a literal)."""
    values = [kw.value for kw in call.keywords if kw.arg in ("reason", None)]
    return values + call.args[1:2]


def _split_reason(node: ast.expr) -> tuple[list[str], list[ast.expr]]:
    """The string literals a ``reason=`` expression can be (both arms of a
    conditional), and the sub-expressions that are not literals."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value], []
    if isinstance(node, ast.IfExp):
        body, body_rest = _split_reason(node.body)
        other, other_rest = _split_reason(node.orelse)
        return body + other, body_rest + other_rest
    return [], [node]


def _unreasoned(calls: list[ast.Call]) -> list[ast.Call]:
    """The constructions that leave the reason on its ``"unspecified"`` default."""
    return [call for call in calls if not _reason_values(call)]


def _undocumented(calls: list[ast.Call]) -> list[str]:
    """Every literal reason, both arms of a conditional, not in ``REFUSAL_REASONS``."""
    return [
        literal
        for call in calls
        for value in _reason_values(call)
        for literal in _split_reason(value)[0]
        if literal not in scan_limits.REFUSAL_REASONS
    ]


def _dynamic(calls: list[ast.Call]) -> set[str]:
    """Every reason expression that is not a literal, as source text."""
    return {
        ast.unparse(rest)
        for call in calls
        for value in _reason_values(call)
        for rest in _split_reason(value)[1]
    }


#: Final review R2 M3: the forms the sweep used to miss, each with a reason
#: it must flag -- a positional unknown code, a factory's default, a new
#: subclass, an aliased import and a ``**`` mapping.
_PLANTED = """
from lemely.io._scan_common import ScanRejectedError as Refusal

class ScanNewError(ScanTooLargeError):
    pass

class ScanNewerError(ScanNewError):
    pass

def positional():
    raise ScanRejectedError("m", "not_a_code")

def factory():
    return ScanRejectedError("m")

def via_factory():
    raise factory()

def subclassed():
    raise ScanNewerError("m")

def aliased():
    raise Refusal("m", reason="also_not_a_code")

def splatted(**options):
    raise ScanRejectedError("m", **options)
"""


def _container_raw_length(data: bytes) -> int:
    """The byte length of the one object stream's raw data in a fixture PDF."""
    start = data.index(b"stream\n", data.index(b"/ObjStm")) + len(b"stream\n")
    return data.index(b"\nendstream", start) - start


class ReasonCodeTests(unittest.TestCase):
    def test_a_refusal_pickles_with_its_message_and_reason(self) -> None:
        exc = ScanTooLargeError("too big", reason="page_px")
        back = pickle.loads(pickle.dumps(exc))  # noqa: S301 -- a round trip of our own object
        self.assertEqual(str(back), "too big")
        self.assertEqual(back.reason, "page_px")
        self.assertIs(type(back), ScanTooLargeError)

    def test_str_is_the_message_alone(self) -> None:
        self.assertEqual(str(ScanRejectedError("m", reason="r")), "m")

    def test_the_default_reason_is_unspecified_and_every_refusal_overrides_it(self) -> None:
        self.assertEqual(ScanRejectedError("m").reason, "unspecified")
        offenders = [
            f"{path.name}:{call.lineno}"
            for path, call in _refusal_calls()
            if not _reason_values(call)
        ]
        self.assertEqual(offenders, [])

    def test_every_literal_reason_is_documented(self) -> None:
        """Both arms of a conditional count, not just a bare literal, and a
        positional reason as well as ``reason=``."""
        documented = scan_limits.REFUSAL_REASONS
        self.assertIsInstance(documented, frozenset)
        self.assertNotIn("unspecified", documented)
        undocumented = [
            f"{path.name}:{call.lineno} {literal!r}"
            for path, call in _refusal_calls()
            for literal in _undocumented([call])
        ]
        self.assertEqual(undocumented, [])
        arms = {
            literal
            for _, call in _refusal_calls()
            for value in _reason_values(call)
            if isinstance(value, ast.IfExp)
            for literal in _split_reason(value)[0]
        }
        self.assertEqual(arms, {"encrypted_objstm", "objstm_bomb"})

    def test_every_non_literal_reason_is_a_page_bound_and_documented(self) -> None:
        """The only reason that is not a literal is a ``_PageBound``'s; every
        bound the module defines carries a documented code."""
        dynamic = _dynamic([call for _, call in _refusal_calls()])
        self.assertEqual(dynamic, {"bound.reason"})
        reasons = {
            pdf_content_walk._SCAN_PAGE_BOUND.reason,
            pdf_content_walk._CROP_PAGE_BOUND.reason,
        }
        self.assertEqual(reasons, {"page_cap", "crop_page_cap"})
        self.assertLessEqual(reasons, scan_limits.REFUSAL_REASONS)

    def test_the_sweep_covers_every_error_class_and_construction(self) -> None:
        """The swept classes are every subclass the package defines (checked
        against the live class tree), and the sweep reaches the factory in
        ``pdf_canonical`` that builds an error for a later ``raise``."""
        live: set[str] = set()
        pending: list[type[ScanRejectedError]] = [ScanRejectedError]
        while pending:
            cls = pending.pop()
            if cls.__module__.startswith("lemely."):
                live.add(cls.__name__)
            pending.extend(cls.__subclasses__())
        self.assertLessEqual(live, _ERROR_NAMES)
        self.assertLessEqual(
            {
                "ScanRejectedError",
                "ScanTooLargeError",
                "ScanUnsupportedEncodingError",
                "ScanUnsupportedFormatError",
            },
            _ERROR_NAMES,
        )
        factory_built = [
            call
            for path, call in _refusal_calls()
            if path.name == "pdf_canonical.py"
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "_STRUCTURE_TOO_COMPLEX_MESSAGE"
        ]
        self.assertEqual(len(factory_built), 1)
        self.assertEqual(_undocumented(factory_built), [])
        self.assertEqual(_unreasoned(factory_built), [])

    def test_the_sweep_flags_each_form_it_used_to_miss(self) -> None:
        """Final review R2 M3, the sweep's own red proof: planted source with
        a positional unknown code, a factory left on the default, a new
        subclass (two levels down) on the default, an aliased import with an
        unknown code, and a ``**`` mapping."""
        tree = ast.parse(_PLANTED)
        names = _error_class_names([*_SOURCES.values(), tree])
        self.assertLessEqual({"ScanNewError", "ScanNewerError"}, names)
        calls = _refusal_calls_in(tree, names)
        lines = _PLANTED.splitlines()
        self.assertEqual(
            {lines[call.lineno - 1].strip() for call in _unreasoned(calls)},
            {'return ScanRejectedError("m")', 'raise ScanNewerError("m")'},
        )
        self.assertEqual(sorted(_undocumented(calls)), ["also_not_a_code", "not_a_code"])
        self.assertEqual(_dynamic(calls), {"options"})

    def test_the_encrypted_worst_case_refusal_is_logged_as_encrypted_objstm(self) -> None:
        data = shared_container_broken_xref_pdf(
            scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000,
            encrypt_entry=b"/Encrypt 99 0 R",
            corrupt_header=True,
        )
        # The premise: only Flate's worst case (1032 x the raw length) takes this
        # container over the cap; its raw length alone is well under it.
        raw = _container_raw_length(data)
        self.assertGreater(raw * 1032, scan_limits.MAX_OBJECT_STREAM_BYTES)
        self.assertLess(raw, scan_limits.MAX_OBJECT_STREAM_BYTES)
        with self.assertRaises(ScanTooLargeError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(caught.exception.reason, "encrypted_objstm")
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_an_encrypted_overrun_from_raw_lengths_alone_is_objstm_bomb(self) -> None:
        """The label says the worst-case rule did it, so it needs that rule to
        have mattered: an unfiltered container over the cap on its raw length
        is a plain bomb, encrypted or not."""
        small = shared_container_broken_xref_pdf(
            1_000, filter_entry=b"", encrypt_entry=b"/Encrypt 99 0 R"
        )
        # Swap the container's raw data for one more byte than the cap allows. Its
        # /Length is now stale, which the scan ignores: it reads to ``endstream``.
        start = small.index(b"stream\n", small.index(b"/ObjStm")) + len(b"stream\n")
        end = start + _container_raw_length(small)
        data = small[:start] + b"\x00" * (scan_limits.MAX_OBJECT_STREAM_BYTES + 1) + small[end:]
        with self.assertRaises(ScanTooLargeError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(caught.exception.reason, "objstm_bomb")
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)


class SeparatorRefusalTests(unittest.TestCase):
    """#273 item 2: a container refused for what follows ``stream`` says so."""

    def test_a_tab_nul_or_form_feed_separator_is_refused_with_the_named_message(self) -> None:
        for sep in (b"\t\t", b"\x00\x00", b"\x0c\x0c", b"\t "):
            with self.subTest(sep=sep), self.assertRaises(ScanRejectedError) as caught:
                check_object_stream_bytes(
                    shared_container_broken_xref_pdf(10, stream_separator=sep)
                )
            self.assertEqual(str(caught.exception), _OBJECT_STREAM_SEPARATOR_MESSAGE)
            self.assertEqual(caught.exception.reason, "objstm_separator")

    def test_separators_that_a_reader_start_accepts_still_pass(self) -> None:
        for sep in (b"\t", b"\t\n", b"\x00", b"\x0c", b"\t\r\n", b" \n"):
            with self.subTest(sep=sep):
                self.assertIsNone(
                    check_object_stream_bytes(
                        shared_container_broken_xref_pdf(10, stream_separator=sep)
                    )
                )

    def test_a_lone_separator_before_corrupt_data_is_unreadable_not_a_separator_refusal(
        self,
    ) -> None:
        """A single tab, NUL or form feed is the start MuPDF takes, so it is not
        what the checker failed on: the data after it is corrupt."""
        for sep in (b"\t", b"\x00", b"\x0c"):
            plain = shared_container_broken_xref_pdf(10, stream_separator=sep, corrupt_header=True)
            # The fixture's corruption is two NULs, which would read as more separator.
            data = plain.replace(b"stream" + sep + b"\x00\x00", b"stream" + sep + b"\xff\xff", 1)
            self.assertNotEqual(data, plain)
            with self.subTest(sep=sep), self.assertRaises(ScanRejectedError) as caught:
                check_object_stream_bytes(data)
            self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_UNREADABLE_MESSAGE)
            self.assertEqual(caught.exception.reason, "objstm_unreadable")

    def test_a_corrupt_container_behind_a_plain_separator_keeps_the_unreadable_message(
        self,
    ) -> None:
        with self.assertRaises(ScanRejectedError) as caught:
            check_object_stream_bytes(shared_container_broken_xref_pdf(10, corrupt_header=True))
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_UNREADABLE_MESSAGE)
        self.assertEqual(caught.exception.reason, "objstm_unreadable")


if __name__ == "__main__":
    unittest.main()
