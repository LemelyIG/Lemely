"""The colour ceiling charged by decoded bytes per pixel (owner decision, Task 11 review).

``MAX_DECODE_PX`` (40 Mpx) is set for 8-bit RGB: three bytes per pixel as
MuPDF decodes it. A colour image that decodes to more bytes per pixel gets
proportionally fewer pixels, ``MAX_DECODE_PX * 3 // bytes_per_pixel``:

* RGBA, CMYK, and 32-bit ``I``/``F``: 4 bytes, 30 Mpx;
* 16-bit RGB: 6 bytes, 20 Mpx;
* 16-bit RGBA or CMYK: 8 bytes, 15 Mpx.

Grey keeps its own ceilings and WebP its own. Pillow reports a 16-bit RGB
PNG or TIFF as mode ``"RGB"`` (it narrows the samples while decoding), so the
depth is read from the file's raw mode, at :func:`open_scan_image`, which
every image path opens through. The files below are headers only: every
check reads the declared size, and nothing is decoded.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from lemely.io import _scan_common
from lemely.io.pdf_canonical import open_scan_image_document
from lemely.io.scan_limits import (
    MAX_DECODE_PX,
    MAX_DECODE_PX_GREY,
    MAX_DECODE_PX_WEBP,
    ScanTooLargeError,
    check_scan_bytes,
    decode_pixel_cap,
    open_scan_image,
    plan_image,
)

_TOO_LARGE = "This scan is too large to process (limit {mpx} megapixels"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _png_header(width: int, height: int, *, colour_type: int, depth: int) -> bytes:
    """A PNG declaring ``width`` x ``height``, with one empty IDAT: opens, never decodes."""
    header = struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b""))
        + _chunk(b"IEND", b"")
    )


def _tiff_header(
    width: int, height: int, *, bits: int, samples: int, photometric: int, sample_format: int = 1
) -> bytes:
    """A little-endian TIFF declaring ``width`` x ``height`` with an empty strip."""
    short, long_ = 3, 4
    entries = [
        (256, long_, [width]),
        (257, long_, [height]),
        (258, short, [bits] * samples),
        (259, short, [1]),
        (262, short, [photometric]),
        (273, long_, [0]),
        (277, short, [samples]),
        (278, long_, [height]),
        (279, long_, [0]),
        (339, short, [sample_format] * samples),
    ]
    if photometric == 2 and samples == 4:
        entries.append((338, short, [2]))  # unassociated alpha
    entries.sort()
    data_offset = 8 + 2 + 12 * len(entries) + 4
    ifd = struct.pack("<H", len(entries))
    extra = b""
    for tag, kind, values in entries:
        packed = b"".join(struct.pack("<H" if kind == short else "<I", v) for v in values)
        if len(packed) <= 4:
            ifd += struct.pack("<HHI", tag, kind, len(values)) + packed.ljust(4, b"\x00")
        else:
            ifd += struct.pack("<HHII", tag, kind, len(values), data_offset + len(extra))
            extra += packed
    ifd += struct.pack("<I", 0)
    return b"II*\x00" + struct.pack("<I", 8) + ifd + extra


def _cmyk_jpeg_header(width: int, height: int) -> bytes:
    """A real 8x8 CMYK JPEG with its frame header rewritten to declare ``width`` x ``height``."""
    buf = io.BytesIO()
    Image.new("CMYK", (8, 8)).save(buf, "JPEG")
    data = bytearray(buf.getvalue())
    sof = data.index(b"\xff\xc0")
    data[sof + 5 : sof + 9] = struct.pack(">HH", height, width)
    return bytes(data)


#: (case, Pillow mode, cap, builder of a file declaring (width, height)).
_CASES = [
    ("RGB 8-bit PNG", "RGB", 40_000_000, lambda w, h: _png_header(w, h, colour_type=2, depth=8)),
    (
        "RGBA 8-bit PNG",
        "RGBA",
        30_000_000,
        lambda w, h: _png_header(w, h, colour_type=6, depth=8),
    ),
    ("RGB 16-bit PNG", "RGB", 20_000_000, lambda w, h: _png_header(w, h, colour_type=2, depth=16)),
    (
        "RGBA 16-bit PNG",
        "RGBA",
        15_000_000,
        lambda w, h: _png_header(w, h, colour_type=6, depth=16),
    ),
    (
        "RGB 16-bit TIFF",
        "RGB",
        20_000_000,
        lambda w, h: _tiff_header(w, h, bits=16, samples=3, photometric=2),
    ),
    (
        "RGBA 16-bit TIFF",
        "RGBA",
        15_000_000,
        lambda w, h: _tiff_header(w, h, bits=16, samples=4, photometric=2),
    ),
    (
        "CMYK 8-bit TIFF",
        "CMYK",
        30_000_000,
        lambda w, h: _tiff_header(w, h, bits=8, samples=4, photometric=5),
    ),
    ("CMYK JPEG", "CMYK", 30_000_000, _cmyk_jpeg_header),
    (
        "I 32-bit TIFF",
        "I",
        30_000_000,
        lambda w, h: _tiff_header(w, h, bits=32, samples=1, photometric=1, sample_format=2),
    ),
    (
        "F 32-bit TIFF",
        "F",
        30_000_000,
        lambda w, h: _tiff_header(w, h, bits=32, samples=1, photometric=1, sample_format=3),
    ),
]

#: Every cap above divides by this height, so ``cap // _HEIGHT`` columns is
#: exactly the cap and one more column is over it.
_HEIGHT = 1000


def test_decode_pixel_cap_charges_colour_by_decoded_bytes_per_pixel() -> None:
    for mode in ("RGB", "YCbCr", "LAB", "HSV", "P", "PA", "LA"):
        assert decode_pixel_cap(mode) == MAX_DECODE_PX, mode
    for mode in ("RGBA", "RGBX", "RGBa", "CMYK", "I", "F"):
        assert decode_pixel_cap(mode) == MAX_DECODE_PX * 3 // 4 == 30_000_000, mode
    assert decode_pixel_cap("RGB", "PNG", sample_bits=16) == 20_000_000
    assert decode_pixel_cap("RGBA", "TIFF", sample_bits=16) == 15_000_000
    assert decode_pixel_cap("CMYK", "TIFF", sample_bits=16) == 15_000_000
    # Already 4 bytes a sample: the 32-bit depth is in the mode, not charged twice.
    assert decode_pixel_cap("I", "TIFF", sample_bits=32) == 30_000_000
    assert decode_pixel_cap("F", "TIFF", sample_bits=32) == 30_000_000
    # Grey and WebP keep their own ceilings, whatever the depth argument says.
    assert decode_pixel_cap("L") == decode_pixel_cap("1") == MAX_DECODE_PX_GREY
    assert decode_pixel_cap("I;16", sample_bits=16) == MAX_DECODE_PX_GREY // 2
    assert decode_pixel_cap("RGBA", "WEBP", sample_bits=16) == MAX_DECODE_PX_WEBP


@pytest.mark.parametrize(("case", "mode", "cap", "build"), _CASES, ids=[c[0] for c in _CASES])
def test_each_colour_mode_is_admitted_at_its_cap_and_refused_one_column_over(
    case: str, mode: str, cap: int, build: object
) -> None:
    assert cap % _HEIGHT == 0
    width = cap // _HEIGHT
    at_cap = build(width, _HEIGHT)  # type: ignore[operator]
    over = build(width + 1, _HEIGHT)  # type: ignore[operator]

    with open_scan_image(io.BytesIO(at_cap)) as opened:
        assert opened.mode == mode, (case, opened.mode)
    check_scan_bytes(at_cap)

    with pytest.raises(ScanTooLargeError) as caught:
        check_scan_bytes(over)
    assert caught.value.reason == "image_px"
    assert str(caught.value).startswith(_TOO_LARGE.format(mpx=cap // 1_000_000)), str(caught.value)


@pytest.mark.parametrize("bits_case", ["RGB 16-bit PNG", "RGBA 16-bit TIFF"])
def test_a_sixteen_bit_colour_image_over_its_cap_is_refused_on_every_path(bits_case: str) -> None:
    """Pillow calls a 16-bit RGB image "RGB", so a caller judging it by mode
    alone would allow 40 Mpx. The opener every path uses -- upload, extraction,
    the crop and (through ``open_scan_image_document``) the preview -- refuses
    it from the raw mode, before anything is decoded."""
    _case, _mode, cap, build = next(c for c in _CASES if c[0] == bits_case)
    over = build(cap // _HEIGHT + 1, _HEIGHT)  # type: ignore[operator]
    assert plan_image(cap // _HEIGHT + 1, _HEIGHT, _mode) >= 1  # by mode alone: admitted

    with pytest.raises(ScanTooLargeError) as caught:
        open_scan_image(io.BytesIO(over))
    assert caught.value.reason == "image_px"
    with pytest.raises(ScanTooLargeError):
        open_scan_image_document(over)


def test_an_eight_bit_colour_image_is_read_as_eight_bits() -> None:
    with open_scan_image(io.BytesIO(_png_header(10, 10, colour_type=2, depth=8))) as opened:
        assert _scan_common._image_sample_bits(opened) == 8
    with open_scan_image(io.BytesIO(_png_header(10, 10, colour_type=2, depth=16))) as opened:
        assert _scan_common._image_sample_bits(opened) == 16
