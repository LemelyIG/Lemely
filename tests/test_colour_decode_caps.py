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
from pathlib import Path

import pytest
from PIL import Image

from lemely.io import _scan_common
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
from lemely.io.scan_render import render_preview_png

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
    width: int,
    height: int,
    *,
    bits: int,
    samples: int,
    photometric: int,
    sample_format: int = 1,
    planar: bool = False,
) -> bytes:
    """A little-endian, uncompressed TIFF declaring ``width`` x ``height``; no pixel data.

    ``planar``: one strip per sample (PlanarConfiguration 2), each declared
    full size. Pillow's raw decoder then names each plane by its band
    (``"R"``, ``"G"``, ...), so the depth is not in the raw mode at all.
    """
    short, long_ = 3, 4
    strips = samples if planar else 1
    strip_bytes = width * height * bits // 8 * (1 if planar else samples)
    entries = [
        (256, long_, [width]),
        (257, long_, [height]),
        (258, short, [bits] * samples),
        (259, short, [1]),
        (262, short, [photometric]),
        (273, long_, [0] * strips),
        (277, short, [samples]),
        (278, long_, [height]),
        (279, long_, [strip_bytes] * strips),
        (284, short, [2 if planar else 1]),
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


def _bmp_565_header(width: int, height: int) -> bytes:
    """A 16-bit 5-6-5 BMP declaring ``width`` x ``height``; no pixel data.

    Two bytes a PIXEL (Pillow's raw mode ``"BGR;16"``), decoded to 8-bit RGB:
    not 16 bits a sample.
    """
    stride = (width * 2 + 3) // 4 * 4
    dib = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 16, 3, stride * height, 2835, 2835, 0, 0
    ) + struct.pack("<III", 0xF800, 0x07E0, 0x001F)
    offset = 14 + len(dib)
    return b"BM" + struct.pack("<IHHI", offset + stride * height, 0, 0, offset) + dib


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
        "RGBA 16-bit planar TIFF",
        "RGBA",
        15_000_000,
        lambda w, h: _tiff_header(w, h, bits=16, samples=4, photometric=2, planar=True),
    ),
    (
        "RGB 16-bit planar TIFF",
        "RGB",
        20_000_000,
        lambda w, h: _tiff_header(w, h, bits=16, samples=3, photometric=2, planar=True),
    ),
    (
        "CMYK 16-bit TIFF",
        "CMYK",
        15_000_000,
        lambda w, h: _tiff_header(w, h, bits=16, samples=4, photometric=5),
    ),
    (
        "LA 16-bit PNG (Pillow: RGBA)",
        "RGBA",
        15_000_000,
        lambda w, h: _png_header(w, h, colour_type=4, depth=16),
    ),
    ("RGB 5-6-5 BMP", "RGB", 40_000_000, _bmp_565_header),
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
    the crop and the preview -- refuses it from the raw mode, before anything
    is decoded."""
    _case, _mode, cap, build = next(c for c in _CASES if c[0] == bits_case)
    over = build(cap // _HEIGHT + 1, _HEIGHT)  # type: ignore[operator]
    assert plan_image(cap // _HEIGHT + 1, _HEIGHT, _mode) >= 1  # by mode alone: admitted

    with pytest.raises(ScanTooLargeError) as caught:
        open_scan_image(io.BytesIO(over))
    assert caught.value.reason == "image_px"
    with pytest.raises(ScanTooLargeError):
        render_preview_png(over)


@pytest.mark.parametrize(
    ("data", "bits"),
    [
        pytest.param(_png_header(10, 10, colour_type=2, depth=8), 8, id="RGB 8-bit PNG"),
        pytest.param(_png_header(10, 10, colour_type=2, depth=16), 16, id="RGB 16-bit PNG"),
        pytest.param(_png_header(10, 10, colour_type=4, depth=16), 16, id="LA 16-bit PNG"),
        pytest.param(
            _tiff_header(10, 10, bits=16, samples=4, photometric=2, planar=True),
            16,
            id="RGBA 16-bit planar TIFF",
        ),
        pytest.param(
            _tiff_header(10, 10, bits=16, samples=4, photometric=5), 16, id="CMYK 16-bit TIFF"
        ),
        pytest.param(
            _tiff_header(10, 10, bits=8, samples=3, photometric=2), 8, id="RGB 8-bit TIFF"
        ),
        pytest.param(_bmp_565_header(10, 10), 8, id="RGB 5-6-5 BMP"),
    ],
)
def test_the_sample_depth_is_read_per_sample(data: bytes, bits: int) -> None:
    """Task 11 re-review: a TIFF's depth comes from ``BitsPerSample`` (a
    planar TIFF's raw modes name bands, not depths), and a 5-6-5 BMP is two
    bytes a pixel, not 16 bits a sample."""
    with open_scan_image(io.BytesIO(data)) as opened:
        assert _scan_common._image_sample_bits(opened) == bits


@pytest.mark.parametrize("bits_case", ["RGB 16-bit PNG", "RGBA 16-bit planar TIFF"])
def test_the_crop_and_extraction_refuse_a_sixteen_bit_image_over_its_cap(
    bits_case: str, tmp_path: Path
) -> None:
    """Both open the image through ``open_scan_image``, so a 16-bit image over
    its cap is refused there, before anything is decoded."""
    from lemely.io.rasterise import iter_scan_pages
    from lemely.io.scan_render import crop_image_scan

    _case, _mode, cap, build = next(c for c in _CASES if c[0] == bits_case)
    over = build(cap // _HEIGHT + 1, _HEIGHT)  # type: ignore[operator]
    path = tmp_path / "scan.img"
    path.write_bytes(over)

    with pytest.raises(ScanTooLargeError) as crop:
        crop_image_scan(over, [100, 100, 300, 400])
    assert crop.value.reason == "image_px"
    with pytest.raises(ScanTooLargeError) as extraction:
        list(iter_scan_pages(path, 200.0))
    assert extraction.value.reason == "image_px"
