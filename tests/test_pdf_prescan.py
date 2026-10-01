"""Unit tests for lemely.io.pdf_prescan: the raw-bytes object-stream scan.

Split from ``test_scan_limits.py`` (#262). The scan runs before any reader
opens a user PDF, so every test here traps both readers.
"""

from __future__ import annotations

import contextlib
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

import lemely.io.pdf_prescan as pdf_prescan
from lemely.io import scan_limits
from lemely.io._scan_common import ScanRejectedError, ScanTooLargeError
from lemely.io.pdf_canonical import canonical_pdf_bytes, check_pdf_content_bytes, open_checked_pdf
from lemely.io.pdf_prescan import check_object_stream_bytes
from lemely.io.scan_limits import MAX_SCAN_PAGES, check_scan_bytes
from tests.pdf_fakes import (
    bare_encrypt_dict_pdf,
    born_digital_text_pdf,
    shared_container_broken_xref_pdf,
)
from tests.test_scan_limits import _pdf_bytes, _readers_trapped, _require_committed_fixture


class RawObjectStreamTests(unittest.TestCase):
    """A container found by xref repair: with a broken xref, MuPDF's repair
    loads every
    object stream it finds while the file is being OPENED, container-mates
    and all -- before any check can run. So object streams are found and
    bounded in the raw bytes, before any reader opens the file."""

    _BOMB = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 + 1_000

    def _trapped(self) -> contextlib.ExitStack:
        """Fail the test if any reader opens the file."""
        return _readers_trapped()

    def test_a_container_bomb_is_refused_before_any_reader_opens_the_file(self) -> None:
        """A 16 KB file whose page dict shares a Flate object stream with an
        array that inflates past the bound; startxref is off, so MuPDF's
        repair would parse the whole container at open (459 MB for the
        reviewer's 10M-element case). Refused from the raw bytes, however
        the container's dictionary is spelled."""
        variants = {
            "plain": {},
            "no space": {"type_entry": b"/Type/ObjStm"},
            "whitespace and a comment": {"type_entry": b"/Type \r\n  % note\n  /ObjStm"},
            "escaped name": {"type_entry": b"/Type /Obj#53tm"},
            "keywords inside a string first": {
                "type_entry": b"/Note (stream endobj 1 0 obj \\) x) /Type /ObjStm"
            },
            "filter array": {"filter_entry": b"/Filter [ /FlateDecode ]"},
            "abbreviated filter in an array": {"filter_entry": b"/Filter[/Fl]"},
            "length too long": {"length_delta": 40},
            "length too short": {"length_delta": -40},
        }
        for label, kwargs in variants.items():
            data = shared_container_broken_xref_pdf(self._BOMB, **kwargs)  # type: ignore[arg-type]
            self.assertLess(len(data), 100_000)
            for check in (
                check_scan_bytes,
                check_pdf_content_bytes,
                canonical_pdf_bytes,
                check_object_stream_bytes,
            ):
                with self.subTest(label, check=check.__name__), self._trapped():
                    with self.assertRaises(ScanTooLargeError) as caught:
                        check(data)
                    self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_the_upload_check_prescans_a_pdf_exactly_once(self) -> None:
        """Final review, item 5: ``check_scan_bytes`` ran the raw pre-scan
        itself and then again inside ``check_pdf_content_bytes`` -- the same
        bytes, twice (up to ~1.5 s each on a crafted 25 MB file). Once, and
        still before either reader opens the file (the bomb test above).

        How many times the scan runs is invisible to every entry point, so
        this spies on ``check_object_stream_bytes`` in ``pdf_prescan``, where
        ``prescan_pdf`` looks it up."""
        real = check_object_stream_bytes
        with patch.object(pdf_prescan, "check_object_stream_bytes", wraps=real) as prescan:
            check_scan_bytes(_pdf_bytes((595.0, 842.0), (595.0, 842.0)))
        self.assertEqual(prescan.call_count, 1)

    def test_every_pdf_entry_point_still_prescans(self) -> None:
        """Item 5 must not drop the pre-scan from any path: each entry point
        that opens user PDF bytes runs it at least once, on a clean file too,
        which no refusal would show; the same spy as above counts it."""
        data = _pdf_bytes((595.0, 842.0))
        for entry in (check_scan_bytes, check_pdf_content_bytes, canonical_pdf_bytes):
            real = check_object_stream_bytes
            with (
                self.subTest(entry=entry.__name__),
                patch.object(pdf_prescan, "check_object_stream_bytes", wraps=real) as prescan,
            ):
                entry(data)
                self.assertGreaterEqual(prescan.call_count, 1)
        with patch.object(pdf_prescan, "check_object_stream_bytes", wraps=real) as prescan:
            open_checked_pdf(data).close()
        self.assertEqual(prescan.call_count, 1)

    def test_a_scan_past_the_token_budget_is_refused_as_too_complex(self) -> None:
        """The raw scan reads every dictionary token by token; one crafted
        dictionary of 600,000 names (1.2M tokens) is refused once past
        ``MAX_PRESCAN_TOKENS``, rather than costing seconds per upload."""
        data = b"%PDF-1.7\n1 0 obj\n<<" + b"/K 0 " * 600_000 + b">>\nendobj\n"
        self.assertGreater(1_200_000, scan_limits.MAX_PRESCAN_TOKENS)
        with self._trapped(), self.assertRaises(ScanTooLargeError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._STRUCTURE_TOO_COMPLEX_MESSAGE)

    def test_spaces_after_the_stream_keyword_do_not_hide_a_container(self) -> None:
        """Scanner review: MuPDF skips any run of spaces after ``stream``
        before the data, and pdfium skips to the end of the line, so a
        container whose data follows ``stream \\n`` inflates in full at open
        (a 16 KB file to 388 MB). The scan measures from where each reader
        starts, so these are refused, not scored as 0 bytes."""
        for separator in (b" \n", b"   \n", b" \t\n", b" \r\n", b"  \r"):
            data = shared_container_broken_xref_pdf(self._BOMB, stream_separator=separator)
            with self.subTest(separator=separator), self._trapped():
                with self.assertRaises(ScanTooLargeError) as caught:
                    check_object_stream_bytes(data)
                self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_every_standard_separator_is_measured_in_full(self) -> None:
        """``\\r\\n``, ``\\n`` and ``\\r``: a container just under the bound
        passes, one just over it is refused -- so each is measured in full."""
        under = scan_limits.MAX_OBJECT_STREAM_BYTES // 2 - 10_000
        for separator in (b"\r\n", b"\n", b"\r"):
            with self.subTest(separator=separator), self._trapped():
                check_object_stream_bytes(
                    shared_container_broken_xref_pdf(under, stream_separator=separator)
                )
                with self.assertRaises(ScanTooLargeError):
                    check_object_stream_bytes(
                        shared_container_broken_xref_pdf(self._BOMB, stream_separator=separator)
                    )

    def test_a_container_no_reader_can_inflate_is_refused(self) -> None:
        """Fail closed: a Flate container that yields nothing from any start a
        reader could use is refused as unreadable, never scored as 0 bytes."""
        data = shared_container_broken_xref_pdf(1_000, corrupt_header=True)
        with self._trapped(), self.assertRaises(ScanRejectedError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_UNREADABLE_MESSAGE)

    def test_an_encrypted_files_object_streams_count_at_their_flate_ceiling(self) -> None:
        """Scanner review: an encrypted file's object streams are ciphertext --
        nothing inflates, and with an empty user password an attacker can make
        the ciphertext inflate to a harmless few bytes while the plaintext MuPDF
        decrypts is a bomb. So each counts at the most Flate can expand its
        length to (``_FLATE_MAX_RATIO``). The committed RC4 fixture's 2.7 KB of
        object streams passes; a 16 KB one is refused, however /Encrypt is
        spelled, and even when its bytes do not inflate at all."""
        small = shared_container_broken_xref_pdf(
            1_000, encrypt_entry=b"/Encrypt 99 0 R", corrupt_header=True
        )
        check_object_stream_bytes(small)
        for entry in (b"/Encrypt 99 0 R", b"/Encr#79pt 99 0 R", b"/Encrypt<</Filter/Standard>>"):
            data = shared_container_broken_xref_pdf(
                self._BOMB, encrypt_entry=entry, corrupt_header=True
            )
            with self.subTest(entry=entry), self._trapped():
                with self.assertRaises(ScanTooLargeError) as caught:
                    check_object_stream_bytes(data)
                self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_encrypt_in_a_bare_dictionary_counts_as_encrypted(self) -> None:
        """Encrypt parity: MuPDF's xref repair reads /Encrypt from any top-level
        dictionary -- with the ``trailer`` keyword, with another word before it,
        or with nothing at all -- so the scan treats any /Encrypt name in the
        file (escapes decoded) as declaring encryption. Each case's ~20 KB
        object stream then counts at Flate's ceiling and is refused; the same
        file with no /Encrypt passes."""
        check_object_stream_bytes(bare_encrypt_dict_pdf(encrypt_key=b""))
        for label, kwargs in (
            ("trailer keyword", {"prefix": b"trailer\n"}),
            ("no keyword", {}),
            ("another keyword", {"prefix": b"foobar\n"}),
            ("escaped name, no keyword", {"encrypt_key": b"/Encr#79pt"}),
            ("fully escaped name", {"encrypt_key": b"/#45#6e#63#72#79#70#74"}),
        ):
            with self.subTest(label), self._trapped():
                with self.assertRaises(ScanTooLargeError) as caught:
                    check_object_stream_bytes(bare_encrypt_dict_pdf(**kwargs))  # type: ignore[arg-type]
                self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAMS_MESSAGE)

    def test_the_committed_encrypted_fixture_passes(self) -> None:
        """``0580_s11_gt.pdf`` is RC4-encrypted (empty user password) and keeps
        its objects in object streams: it passes the raw scan and upload."""
        fixture = Path(__file__).parent / "fixtures" / "0580_s11_gt.pdf"
        _require_committed_fixture(fixture)
        data = fixture.read_bytes()
        check_object_stream_bytes(data)
        check_scan_bytes(data)

    def test_a_container_the_bounded_inflate_cannot_measure_is_refused(self) -> None:
        data = shared_container_broken_xref_pdf(1_000, filter_entry=b"/Filter /LZWDecode")
        with self._trapped(), self.assertRaises(ScanRejectedError) as caught:
            check_object_stream_bytes(data)
        self.assertEqual(str(caught.exception), scan_limits._OBJECT_STREAM_ENCODING_MESSAGE)

    def test_ordinary_object_streams_pass(self) -> None:
        """Object streams as producers write them -- pymupdf's use_objstms
        save of a 40-page born-digital file, a merge of image scans with an
        xref stream and object streams, and the same small shared container
        under a broken xref -- pass the raw scan and upload."""
        with pymupdf.open(
            stream=born_digital_text_pdf(pages=MAX_SCAN_PAGES), filetype="pdf"
        ) as doc:  # type: ignore[no-untyped-call]
            born_digital: bytes = doc.tobytes(garbage=1, use_objstms=1)  # type: ignore[no-untyped-call]
        merged = pymupdf.open()  # type: ignore[no-untyped-call]
        for _ in range(12):
            scan = pymupdf.open()  # type: ignore[no-untyped-call]
            page = scan.new_page(width=595, height=842)
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 280), 0)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            merged.insert_pdf(scan)
            scan.close()
        merged_objstm: bytes = merged.tobytes(garbage=1, deflate=True, use_objstms=1)
        merged.close()
        for label, data in (
            ("born-digital", born_digital),
            ("merged scans", merged_objstm),
            ("small shared container, broken xref", shared_container_broken_xref_pdf(1_000)),
        ):
            with self.subTest(label):
                self.assertIn(b"/ObjStm", data)
                check_object_stream_bytes(data)
                check_scan_bytes(data)


if __name__ == "__main__":
    unittest.main()
