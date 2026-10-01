"""Every scan refusal carries a reason code that survives pickling (#276, #273)."""

from __future__ import annotations

import ast
import pickle
import unittest
from pathlib import Path

from lemely.io import scan_limits
from lemely.io._scan_common import (
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
        documented = scan_limits.REFUSAL_REASONS
        self.assertIsInstance(documented, frozenset)
        self.assertNotIn("unspecified", documented)
        undocumented = [
            f"{path.name}:{call.lineno} {kw.value.value!r}"
            for path, call in _refusal_raises()
            for kw in call.keywords
            if kw.arg == "reason"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value not in documented
        ]
        self.assertEqual(undocumented, [])

    def test_the_encrypted_worst_case_refusal_is_logged_as_encrypted_objstm(self) -> None:
        # The raw container only has to exceed MAX_OBJECT_STREAM_BYTES / Flate's
        # ceiling (~15.5 KB); a zero-filled array of this size compresses to about that.
        data = shared_container_broken_xref_pdf(
            scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000,
            encrypt_entry=b"/Encrypt 99 0 R",
            corrupt_header=True,
        )
        with self.assertRaises(ScanTooLargeError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(caught.exception.reason, "encrypted_objstm")
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)


if __name__ == "__main__":
    unittest.main()
