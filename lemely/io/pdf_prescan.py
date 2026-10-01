"""The raw-bytes pre-scan of a PDF, run before any reader opens the file.

#262: moved out of :mod:`lemely.io.scan_limits`, which re-exports its public
names. Owns the PDF tokenizer, the object-stream bound
(:func:`check_object_stream_bytes`), the encryption sniff, and
:class:`PrescannedPdf` / :func:`prescan_pdf`, the proof that the scan has
run. Imports only :mod:`lemely.io._scan_common`.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from lemely.io._scan_common import (
    _INFLATE_CHUNK,
    _OBJECT_STREAM_ENCODING_MESSAGE,
    _OBJECT_STREAM_SEPARATOR_MESSAGE,
    _OBJECT_STREAM_UNREADABLE_MESSAGE,
    _OBJECT_STREAMS_MESSAGE,
    _STRUCTURE_TOO_COMPLEX_MESSAGE,
    MAX_OBJECT_STREAM_BYTES,
    MAX_PRESCAN_TOKENS,
    ScanRejectedError,
    ScanTooLargeError,
)

#: PDF whitespace (ISO 32000-1 Table 1) and the delimiters that end a token.
_WS = rb"\x00\t\n\x0c\r "
_REGULAR = rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]"
#: An indirect-object header: ``12 0 obj``, "obj" a whole keyword.
_OBJ_HEADER_RE = re.compile(
    rb"(?<![0-9])[0-9]+[" + _WS + rb"]+[0-9]+[" + _WS + rb"]+obj(?!" + _REGULAR + rb")"
)
#: One PDF token; a literal string's ``(`` is followed by hand (nesting, escapes).
_TOKEN_RE = re.compile(
    rb"(?P<skip>(?:[" + _WS + rb"]+|%[^\r\n]*)+)"
    rb"|(?P<open><<)|(?P<close>>>)"
    rb"|(?P<hex><[0-9A-Fa-f" + _WS + rb"]*>)"
    rb"|(?P<string>\()"
    rb"|(?P<name>/" + _REGULAR + rb"*)"
    rb"|(?P<bracket>[\[\]])"
    rb"|(?P<word>" + _REGULAR + rb"+)"
    rb"|(?P<other>.)",
    re.DOTALL,
)
_STRING_SPECIAL_RE = re.compile(rb"[()\\]")
_NAME_ESCAPE_RE = re.compile(rb"#([0-9A-Fa-f]{2})")
_ENDSTREAM_AT_RE = re.compile(rb"[" + _WS + rb"]*endstream")
_EOL_RE = re.compile(rb"[\r\n]")
#: The name ``/Encrypt``, whole, spelled plainly -- and any name holding a
#: ``#xx`` escape, which is decoded and compared (encrypt parity).
_ENCRYPT_NAME_RE = re.compile(rb"/Encrypt(?!" + _REGULAR + rb")")
_ESCAPED_NAME_RE = re.compile(rb"/" + _REGULAR + rb"*?#[0-9A-Fa-f]{2}" + _REGULAR + rb"*")


def _declares_encryption(data: bytes, budget: _ScanBudget) -> bool:
    """Whether ``/Encrypt`` appears anywhere in ``data`` as a name, escapes decoded.

    Encrypt parity: MuPDF takes ``/Encrypt`` from a ``trailer`` dictionary,
    an xref stream's dictionary, and -- when it repairs a broken xref -- any
    top-level dictionary at all, keyword or none. None of those is ever
    compressed, so the name is always in the raw bytes. Looking for it
    anywhere over-detects (a string or comment that spells it counts), which
    is safe: an encrypted file's object streams only count at their Flate
    ceiling. The plain spelling is found by one C-speed search; each name
    holding an escape is decoded and costs a token of ``budget``.
    """
    if _ENCRYPT_NAME_RE.search(data):
        return True
    for escaped in _ESCAPED_NAME_RE.finditer(data):
        budget.spend()
        if _pdf_name(escaped.group()) == b"Encrypt":
            return True
    return False


#: The most a Flate stream can expand: deflate's longest match (258 bytes)
#: costs at least two bits, so 1032 decoded bytes per compressed byte, and
#: ``1032 x length`` bounds any Flate object stream without decoding it.
_FLATE_MAX_RATIO = 1032


def _stream_data_starts(data: bytes, pos: int) -> list[int]:
    """Every offset a reader may take a stream's data to start at; ``pos`` follows ``stream``.

    Scanner review: the spec's end-of-line after ``stream`` is not what
    readers do. MuPDF (``pdf_parse_ind_obj``) skips any run of spaces, then
    takes a carriage return and an optional line feed -- or else consumes
    exactly one byte, whatever it is. pdfium skips to the end of the line.
    The strict reading takes one CR LF, LF or CR. For every standard
    separator the three agree; where they do not, each is measured and the
    largest counts.
    """
    starts = set()
    strict = pos
    if data[pos : pos + 2] == b"\r\n":
        strict += 2
    elif data[pos : pos + 1] in (b"\n", b"\r"):
        strict += 1
    starts.add(strict)
    mupdf = pos
    while data[mupdf : mupdf + 1] == b" ":
        mupdf += 1
    if data[mupdf : mupdf + 1] == b"\r":
        mupdf += 2 if data[mupdf + 1 : mupdf + 2] == b"\n" else 1
    elif mupdf < len(data):
        mupdf += 1
    starts.add(mupdf)
    eol = _EOL_RE.search(data, pos)
    if eol is not None:
        line = eol.end()
        if eol.group() == b"\r" and data[line : line + 1] == b"\n":
            line += 1
        starts.add(line)
    return sorted(starts)


#: Tab, NUL and form feed: whitespace to a PDF lexer, which MuPDF and pdfium
#: take as the separator after ``stream`` in ways the starts above do not
#: all cover (#273 item 2).
_SEPARATOR_BYTES = frozenset({0x09, 0x00, 0x0C})
_SPACES_RE = re.compile(rb" *")
_WHITESPACE_RUN_RE = re.compile(rb"[" + _WS + rb"]*")


def _separator_after_stream(data: bytes, pos: int, starts: list[int]) -> bool:
    """Whether the data after ``stream`` sits behind a separator no start covers.

    ``pos`` follows the keyword. True when the first non-space byte is a tab,
    NUL or form feed AND the run of whitespace it opens ends at an offset that
    is none of ``starts`` (what :func:`_stream_data_starts` returned): the
    readers open such a file but no start the checker tries reaches the data.
    A lone tab, NUL or form feed is the byte MuPDF consumes, and a tab then an
    end-of-line ends at the end-of-line start, so neither counts. Both scans
    are regex runs, C-speed however long the run of spaces or whitespace.
    """
    first = _SPACES_RE.match(data, pos).end()  # type: ignore[union-attr]
    if first >= len(data) or data[first] not in _SEPARATOR_BYTES:
        return False
    return _WHITESPACE_RUN_RE.match(data, first).end() not in starts  # type: ignore[union-attr]


def _stream_data_end(data: bytes, start: int, length: tuple[str, object] | None) -> int:
    """Where stream data from ``start`` ends, never short of what a reader inflates.

    By ``/Length`` if ``endstream`` follows it, and at least up to the next
    ``endstream`` -- whichever is later.
    """
    found = data.find(b"endstream", start)
    end = found if found >= 0 else len(data)
    if length and length[0] == "number":
        candidate = start + int(length[1])  # type: ignore[call-overload]
        if candidate <= len(data) and _ENDSTREAM_AT_RE.match(data, candidate):
            end = max(end, candidate)
    return end


def _strict_inflate_size(raw: bytes, *, budget: int) -> int | None:
    """:func:`_bounded_inflate_size` for the raw object-stream scan, failing closed.

    ``None`` when the data yields nothing -- a ``zlib.error`` before any
    output, or a stream that decodes to 0 bytes -- where the lenient helper
    would count 0 and pass. A stream that decodes some bytes and then fails
    counts what it yielded, as a reader inflates it.
    """
    decompressor = zlib.decompressobj()
    size = 0
    pending = raw
    try:
        while pending:
            size += len(decompressor.decompress(pending, _INFLATE_CHUNK))
            if size > budget:
                raise ScanTooLargeError(_OBJECT_STREAMS_MESSAGE, reason="objstm_bomb")
            pending = decompressor.unconsumed_tail
            if decompressor.eof:
                break
    except zlib.error:
        return size or None
    return size or None


@dataclass
class _ScanBudget:
    """Tokens the raw object-stream scan may still read (:data:`MAX_PRESCAN_TOKENS`)."""

    left: int = MAX_PRESCAN_TOKENS

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise ScanTooLargeError(_STRUCTURE_TOO_COMPLEX_MESSAGE, reason="prescan_tokens")


def _pdf_name(token: bytes) -> bytes:
    """A name token's value, ``#xx`` escapes decoded as MuPDF's lexer does."""
    return _NAME_ESCAPE_RE.sub(lambda m: bytes([int(m.group(1), 16)]), token[1:])


def _next_token(data: bytes, pos: int, budget: _ScanBudget) -> tuple[str, bytes, int]:
    """The token at ``pos`` after whitespace and comments: ``(kind, text, end)``.

    ``kind`` is ``"open"``, ``"close"``, ``"hex"``, ``"string"``, ``"name"``,
    ``"bracket"``, ``"word"`` (numbers, ``R``, keywords), ``"other"`` or
    ``"eof"``. A literal string is skipped whole, nested parentheses and
    backslash escapes included, jumping between its special characters.
    """
    while True:
        match = _TOKEN_RE.match(data, pos)
        if match is None:
            return "eof", b"", len(data)
        kind = match.lastgroup or "other"
        if kind == "skip":
            pos = match.end()
            continue
        budget.spend()
        if kind != "string":
            return kind, match.group(), match.end()
        depth, cursor = 1, match.end()
        while depth:
            special = _STRING_SPECIAL_RE.search(data, cursor)
            if special is None:
                return "string", b"", len(data)
            budget.spend()  # each parenthesis or escape in a string counts
            char = data[special.start()]
            cursor = special.end() + (1 if char == 0x5C else 0)  # a backslash escapes one byte
            depth += 1 if char == 0x28 else -1 if char == 0x29 else 0
        return "string", b"", cursor


def _stream_dict(
    data: bytes, pos: int, budget: _ScanBudget
) -> tuple[dict[bytes, tuple[str, object]], int] | None:
    """Parse the dictionary at ``pos``; its top-level entries and where it ends.

    Only what the object-stream scan needs is kept, per top-level key: a
    name value, a number, a reference (``N G R``), or a list of names for an
    array. ``None`` when ``pos`` does not start a dictionary.
    """
    kind, _, pos = _next_token(data, pos, budget)
    if kind != "open":
        return None
    entries: dict[bytes, tuple[str, object]] = {}
    depth, key = 1, None
    while depth:
        kind, text, pos = _next_token(data, pos, budget)
        if kind == "eof":
            return entries, pos
        if kind == "open":
            if depth == 1 and key is not None:
                entries[key] = ("dict", None)  # a top-level key whose value is a dictionary
            depth += 1
            key = None
        elif kind == "close":
            depth -= 1
        elif depth == 1 and key is None:
            key = _pdf_name(text) if kind == "name" else None
        elif depth == 1 and key is not None:
            if kind == "name":
                entries[key] = ("name", _pdf_name(text))
            elif kind == "word" and text.isdigit():
                after_kind, after, after_end = _next_token(data, pos, budget)
                last_kind, last, last_end = _next_token(data, after_end, budget)
                if after_kind == "word" and after.isdigit() and (last_kind, last) == ("word", b"R"):
                    entries[key] = ("ref", None)
                    pos = last_end
                else:
                    entries[key] = ("number", int(text))
            elif kind == "bracket" and text == b"[":
                names: list[bytes] = []
                simple = True
                while True:
                    kind, text, pos = _next_token(data, pos, budget)
                    if kind in ("eof", "close") or (kind, text) == ("bracket", b"]"):
                        break
                    if kind == "name":
                        names.append(_pdf_name(text))
                    else:
                        simple = False
                entries[key] = ("array", names if simple else None)
            else:
                entries[key] = ("other", None)
            key = None
    return entries, pos


def check_object_stream_bytes(data: bytes) -> None:
    """Bound a PDF's object streams from its raw bytes, before any reader opens it.

    Task 9c review round 2. With a damaged xref, MuPDF repairs it while the
    file is being OPENED, and repair loads every object stream it finds --
    parsing each whole, container-mates and all -- so a 20 KB file took a
    bare ``pymupdf.open`` to 459 MB, before :func:`_check_object_streams`
    (which reads the opened xref) can run. So the streams are found here, in
    the raw bytes, the way repair finds them: an indirect object whose
    dictionary names ``/Type /ObjStm`` directly (the name may be spelled
    ``/Type/ObjStm``, split by whitespace or a comment, or ``#xx``-escaped;
    this parses it as MuPDF's lexer does). Each one's data is taken by a
    direct ``/Length`` when ``endstream`` follows it, else up to the next
    ``endstream``, and measured with the bounded inflate: unfiltered it is
    its length, a single ``/FlateDecode`` or ``/Fl`` (bare or in a
    one-element array) is inflated in bounded chunks, anything else
    (another filter, a chain, a ``/Filter`` given by reference) cannot be
    measured and is refused (:data:`_OBJECT_STREAM_ENCODING_MESSAGE`). Past
    :data:`MAX_OBJECT_STREAM_BYTES` in total the file is refused
    (:data:`_OBJECT_STREAMS_MESSAGE`).

    A container no span of which inflates is refused as unreadable
    (:data:`_OBJECT_STREAM_UNREADABLE_MESSAGE`, reason ``objstm_unreadable``),
    or, when the first non-space byte after its ``stream`` is a tab, NUL or
    form feed (:func:`_separator_after_stream`), with
    :data:`_OBJECT_STREAM_SEPARATOR_MESSAGE` (``objstm_separator``): MuPDF and
    pdfium open such a file, so the message names the cause. Accepting it is
    deferred until the ``objstm_separator`` log shows real uploads; a container
    that inflates from some start still passes, so this adds no refusal.

    Past :data:`MAX_PRESCAN_TOKENS` tokens the file is refused as too
    complex to check (:data:`_STRUCTURE_TOO_COMPLEX_MESSAGE`).

    O(file bytes): each byte is tokenized at most once -- a header found
    inside a span already parsed (a dictionary, or a stream's data) is
    skipped, since its dictionary is part of that span -- and a stream's
    data is inflated in bounded chunks, never held decoded. Anything that
    only looks like a header inside a string or a comment can only add to
    the total, never hide a container from it.

    Nothing opens user PDF bytes with MuPDF except through
    :func:`open_checked_pdf`, which runs this first (final review, item 4;
    ``tests/test_scan_limits.py`` fails on any other ``pymupdf.open`` of
    bytes in ``lemely/``).
    """
    budget = _ScanBudget()
    containers: list[tuple[tuple[str, object] | None, list[tuple[int, int]], int]] = []
    scanned_to = 0
    for header in _OBJ_HEADER_RE.finditer(data):
        budget.spend()
        if header.start() < scanned_to:
            continue
        parsed = _stream_dict(data, header.end(), budget)
        if parsed is None:
            scanned_to = header.end()
            continue
        entries, dict_end = parsed
        scanned_to = dict_end
        kind, keyword, start = _next_token(data, dict_end, budget)
        if (kind, keyword) != ("word", b"stream"):
            continue
        starts = _stream_data_starts(data, start)
        spans = [(begin, _stream_data_end(data, begin, entries.get(b"Length"))) for begin in starts]
        scanned_to = max(scanned_to, *(end for _, end in spans))
        if entries.get(b"Type") == ("name", b"ObjStm"):
            containers.append((entries.get(b"Filter"), spans, start))
    encrypted = _declares_encryption(data, budget)
    total = 0
    # What the same containers count without Flate's worst case: an encrypted
    # file's Flate container at its raw length. An overrun this total shares
    # is not the worst-case rule's doing (``objstm_bomb``, not ``encrypted_objstm``).
    plain_total = 0
    for filters, spans, stream_pos in containers:
        longest = max(end - begin for begin, end in spans)
        worst_case = False
        if filters is None or filters == ("array", []):
            size = longest
        elif filters in (("name", b"FlateDecode"), ("name", b"Fl")) or filters in (
            ("array", [b"FlateDecode"]),
            ("array", [b"Fl"]),
        ):
            if encrypted:
                # Ciphertext: inflating it proves nothing, and with an empty user
                # password its plaintext is the attacker's to choose. Count the
                # most Flate can expand this many bytes to.
                size = longest * _FLATE_MAX_RATIO
                worst_case = True
            else:
                sizes = [
                    _strict_inflate_size(data[begin:end], budget=MAX_OBJECT_STREAM_BYTES - total)
                    for begin, end in spans
                ]
                decoded = [found for found in sizes if found]
                if not decoded and longest > 0:
                    if _separator_after_stream(data, stream_pos, [begin for begin, _ in spans]):
                        raise ScanRejectedError(
                            _OBJECT_STREAM_SEPARATOR_MESSAGE, reason="objstm_separator"
                        )
                    raise ScanRejectedError(
                        _OBJECT_STREAM_UNREADABLE_MESSAGE, reason="objstm_unreadable"
                    )
                size = max(decoded, default=0)
        else:
            raise ScanRejectedError(_OBJECT_STREAM_ENCODING_MESSAGE, reason="objstm_encoding")
        total += size
        plain_total += longest if worst_case else size
        if total > MAX_OBJECT_STREAM_BYTES:
            raise ScanTooLargeError(
                _OBJECT_STREAMS_MESSAGE,
                reason="objstm_bomb"
                if plain_total > MAX_OBJECT_STREAM_BYTES
                else "encrypted_objstm",
            )


@dataclass(frozen=True, eq=False)
class PrescannedPdf:
    """PDF bytes :func:`check_object_stream_bytes` has passed. Made only by :func:`prescan_pdf`.

    Final review, item 5: the upload check must pre-scan before pdfium plans
    the bytes, and used to pre-scan them a second time when it went on to
    open them with MuPDF. Holding this instead of the bytes is how a caller
    says the scan has run: :func:`open_checked_pdf` and
    :func:`check_pdf_content_bytes` take it without scanning again.
    """

    data: bytes


def prescan_pdf(data: bytes) -> PrescannedPdf:
    """``data`` once :func:`check_object_stream_bytes` has passed it (which raises otherwise)."""
    check_object_stream_bytes(data)
    return PrescannedPdf(data)
