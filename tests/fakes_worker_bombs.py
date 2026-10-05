"""PDFs that blow up a reader before any check can measure them (#260).

Built in-test, nothing committed. Each one is small on the wire and makes a
C reader allocate far more than the web process can spare while it OPENS the
file, so no Python-level bound can refuse it first; only the extraction
worker's limits can. Owned by the scan-render lane (Task 10); the shared
builders in ``tests/pdf_fakes.py`` are frozen after lane 0. Also the two
``VmHWM`` helpers the tests use to bound what reaches the test process.
"""

from __future__ import annotations

import zlib

import pytest

from tests.pdf_fakes import assemble_pdf, pdf_stream

#: One mebibyte of path operators: the unit :func:`streamed_flate_bomb` repeats.
_OPS = b"0 0 m 1 1 l S\n"
_CHUNK = _OPS * (1_048_576 // len(_OPS))


def streamed_flate_bomb(inflated_bytes: int) -> bytes:
    """At least ``inflated_bytes`` of path operators, Flate-compressed in 1 MiB chunks.

    Never holds the inflated data: ``pdf_fakes.flate_bomb_ops`` builds it in
    memory first, which for a gigabyte would grow the test process by as much
    as the bomb it is meant to keep out of it.
    """
    compressor = zlib.compressobj(9)
    parts: list[bytes] = []
    done = 0
    while done < inflated_bytes:
        parts.append(compressor.compress(_CHUNK))
        done += len(_CHUNK)
    parts.append(compressor.flush())
    return b"".join(parts)


def catalog_metadata_bomb_pdf(inflated_bytes: int) -> bytes:
    """One empty A4 page, and a catalog ``/Metadata`` stream that inflates to ``inflated_bytes``.

    The reviewer's ``catmeta`` shape (task 13 review, ``probe.py``). No page
    reaches the metadata, so the content walk never measures it, but pdfium
    inflates it while opening the document (``FPDF_LoadMemDocument``),
    inside the upload check's ``_pdfium_plan``. At 1,000,000,000 bytes the
    file is about 1.9 MB and the check peaked at about 1.98 GB in-process.
    """
    return assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R /Metadata 5 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
            pdf_stream(b"", b"q Q"),
            pdf_stream(
                b"/Type /Metadata /Subtype /XML /Filter /FlateDecode",
                streamed_flate_bomb(inflated_bytes),
            ),
        ]
    )


def reset_peak_rss() -> int:
    """Reset this process's ``VmHWM`` to its current RSS, and return that.

    Writing ``5`` to ``/proc/self/clear_refs`` resets the peak (Linux 4.0+).
    Skips the calling test where that file cannot be written, so a bound on
    the peak is never checked against a peak that was never reset.
    """
    try:
        with open("/proc/self/clear_refs", "w", encoding="ascii") as clear:
            clear.write("5")
    except OSError as exc:
        pytest.skip(f"cannot reset VmHWM: {exc}")
    return peak_rss_bytes()


def peak_rss_bytes() -> int:
    """This process's ``VmHWM`` (peak resident set size) in bytes."""
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("no VmHWM in /proc/self/status")


__all__ = [
    "catalog_metadata_bomb_pdf",
    "peak_rss_bytes",
    "reset_peak_rss",
    "streamed_flate_bomb",
]
