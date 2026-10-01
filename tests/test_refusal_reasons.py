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
_ERROR_NAMES = frozenset(
    {
        "ScanRejectedError",
        "ScanTooLargeError",
        "ScanUnsupportedEncodingError",
        "ScanUnsupportedFormatError",
    }
)


def _refusal_raises() -> list[tuple[Path, ast.Call]]:
    """Every ``raise Scan...Error(...)`` in ``lemely/io``, with the file it is in."""
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted((_ROOT / "lemely" / "io").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in _ERROR_NAMES:
                found.append((path, node.exc))
    return found


def _reason_values(call: ast.Call) -> list[ast.expr]:
    return [kw.value for kw in call.keywords if kw.arg == "reason"]


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

    def test_the_default_reason_is_unspecified_and_every_io_raise_overrides_it(self) -> None:
        self.assertEqual(ScanRejectedError("m").reason, "unspecified")
        offenders = [
            f"{path.name}:{call.lineno}"
            for path, call in _refusal_raises()
            if not (any(kw.arg == "reason" for kw in call.keywords) or len(call.args) >= 2)
        ]
        self.assertEqual(offenders, [])

    def test_every_literal_reason_is_documented(self) -> None:
        """Both arms of a conditional count, not just a bare literal."""
        documented = scan_limits.REFUSAL_REASONS
        self.assertIsInstance(documented, frozenset)
        self.assertNotIn("unspecified", documented)
        undocumented = [
            f"{path.name}:{call.lineno} {literal!r}"
            for path, call in _refusal_raises()
            for value in _reason_values(call)
            for literal in _split_reason(value)[0]
            if literal not in documented
        ]
        self.assertEqual(undocumented, [])
        arms = {
            literal
            for _, call in _refusal_raises()
            for value in _reason_values(call)
            if isinstance(value, ast.IfExp)
            for literal in _split_reason(value)[0]
        }
        self.assertEqual(arms, {"encrypted_objstm", "objstm_bomb"})

    def test_every_non_literal_reason_is_a_page_bound_and_documented(self) -> None:
        """The only reason that is not a literal is a ``_PageBound``'s; every
        bound the module defines carries a documented code."""
        dynamic = {
            ast.unparse(rest)
            for _, call in _refusal_raises()
            for value in _reason_values(call)
            for rest in _split_reason(value)[1]
        }
        self.assertEqual(dynamic, {"bound.reason"})
        reasons = {
            pdf_content_walk._SCAN_PAGE_BOUND.reason,
            pdf_content_walk._CROP_PAGE_BOUND.reason,
        }
        self.assertEqual(reasons, {"page_cap", "crop_page_cap"})
        self.assertLessEqual(reasons, scan_limits.REFUSAL_REASONS)

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
