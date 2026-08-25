"""#59: ``scripts/rasterise_handwritten_fixtures.py`` flattening and determinism.

The script's whole reason to exist is one property — **extraction must never
see a text layer** — and the manifest it commits rests on a second —
**a re-render reproduces the same bytes**. Both were asserted in prose in the
introducing commit. Prose does not fail when someone drops the metadata
pinning or swaps the renderer, and either regression is silent: the fixture
still looks like a fixture, but the measurement it feeds either reads printed
question text without using vision at all (overstating real performance) or
carries a digest that no longer means anything.

Builds its own source PDF with a real text layer via ``pymupdf`` rather than
reading the three real papers, which live outside the repo and are not
reproducible in CI (same reasoning as ``tests/test_build_corpus_manifest.py``).
The render-twice-assert-identical-bytes shape follows
``tests/test_accuracy_synth.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pymupdf
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rasterise_handwritten_fixtures.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rasterise_handwritten_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pdf_with_text_layer(path: Path, *, pages: int = 2) -> Path:
    """A PDF carrying real extractable text — the hazard being flattened away."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595.276, height=841.89)  # A4 in points
        page.insert_text((72, 144), f"Question {i + 1} State the unit of force.", fontsize=14)
    doc.save(str(path))
    doc.close()
    return path


class TestFlattening:
    def test_the_text_layer_is_actually_destroyed(self, tmp_path: Path) -> None:
        module = _load_module()
        source = _pdf_with_text_layer(tmp_path / "source.pdf")

        entry = module.rasterise(source, tmp_path / "out" / "source.pdf")

        assert entry["source_text_chars"] > 0, "the fixture must start with a real text layer"
        assert entry["output_text_chars"] == 0, (
            "a surviving text layer would let extraction read the printed question "
            "text without vision, measuring nothing"
        )

    def test_every_page_survives_the_render(self, tmp_path: Path) -> None:
        module = _load_module()
        source = _pdf_with_text_layer(tmp_path / "source.pdf", pages=3)

        entry = module.rasterise(source, tmp_path / "out" / "source.pdf")

        assert entry["pages"] == 3


class TestDeterminism:
    def test_the_timestamps_that_break_determinism_are_actually_pinned(
        self, tmp_path: Path
    ) -> None:
        """The load-bearing assertion, and it does NOT depend on render timing.

        Pillow embeds the current wall-clock time and a ``/Title`` derived from
        the output filename unless they are pinned; that is what made two
        renders of the real papers produce different digests.

        The obvious test — render twice, compare bytes — is a FALSE NEGATIVE
        here and was measured to be one: with the metadata pinning deliberately
        removed, it still passed, because a 2-page synthetic renders in
        milliseconds so both saves land in the same clock second and embed the
        same timestamp anyway. Only the real 20-page papers, ~30s apart,
        diverge. So this asserts the pinned values are present in the output,
        which holds regardless of how fast the machine is.
        """
        import pymupdf as _pymupdf

        module = _load_module()
        source = _pdf_with_text_layer(tmp_path / "source.pdf")

        module.rasterise(source, tmp_path / "a" / "source.pdf")

        with _pymupdf.open(str(tmp_path / "a" / "source.pdf")) as rendered:
            metadata = rendered.metadata or {}
        assert metadata.get("creationDate") == "D:19700101000000Z", (
            "unpinned /CreationDate — every output_sha256 in the manifest "
            "becomes a false claim of reproducibility"
        )
        assert metadata.get("modDate") == "D:19700101000000Z"
        assert metadata.get("title") == "lemely-handwritten-fixture", (
            "an unpinned /Title is derived from the output filename, so the "
            "same pages under a different name would hash differently"
        )

    def test_two_renders_of_one_input_produce_identical_bytes(self, tmp_path: Path) -> None:
        """Supporting check only — see the test above for why this one is weak.

        It cannot fail from unpinned timestamps at this fixture size. It still
        catches a renderer that is non-deterministic for some *other* reason
        (dithering, dict ordering, an embedded random id).
        """
        module = _load_module()
        source = _pdf_with_text_layer(tmp_path / "source.pdf")

        first = module.rasterise(source, tmp_path / "a" / "source.pdf")
        second = module.rasterise(source, tmp_path / "b" / "source.pdf")

        assert first["output_sha256"] == second["output_sha256"]

    def test_a_different_input_gives_a_different_digest(self, tmp_path: Path) -> None:
        """Guards the opposite failure: a digest that is stable because it is constant."""
        module = _load_module()
        one = _pdf_with_text_layer(tmp_path / "one.pdf", pages=1)
        two = _pdf_with_text_layer(tmp_path / "two.pdf", pages=2)

        assert (
            module.rasterise(one, tmp_path / "a" / "o.pdf")["output_sha256"]
            != module.rasterise(two, tmp_path / "b" / "t.pdf")["output_sha256"]
        )


class TestAcceptanceCheckFailsClosed:
    def test_a_fixture_that_kept_its_text_is_refused_not_written_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If flattening ever silently stops working, the script must STOP.

        Failing closed matters more than the check being redundant today: the
        alternative is a fixture that looks fine and quietly measures nothing.
        """
        module = _load_module()
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        for name in module.SOURCES:
            _pdf_with_text_layer(source_dir / name)

        real_rasterise = module.rasterise

        def _rasterise_leaving_text(source: Path, out_pdf: Path) -> dict[str, object]:
            entry = real_rasterise(source, out_pdf)
            entry["output_text_chars"] = 137  # pretend the text layer survived
            return entry

        monkeypatch.setattr(module, "rasterise", _rasterise_leaving_text)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "rasterise_handwritten_fixtures.py",
                "--source-dir",
                str(source_dir),
                "--out-dir",
                str(tmp_path / "out"),
                "--manifest",
                str(tmp_path / "manifest.json"),
            ],
        )

        with pytest.raises(SystemExit) as excinfo:
            module.main()

        assert "FLATTENING FAILED" in str(excinfo.value)
        assert not (tmp_path / "manifest.json").exists(), (
            "no manifest may be written for a fixture that failed its own check"
        )

    def test_a_missing_source_stops_rather_than_writing_a_partial_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        source_dir = tmp_path / "src"
        source_dir.mkdir()  # deliberately empty

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "rasterise_handwritten_fixtures.py",
                "--source-dir",
                str(source_dir),
                "--out-dir",
                str(tmp_path / "out"),
                "--manifest",
                str(tmp_path / "manifest.json"),
            ],
        )

        with pytest.raises(SystemExit) as excinfo:
            module.main()

        assert "missing source" in str(excinfo.value)
        assert not (tmp_path / "manifest.json").exists()


class TestRenderScaleMatchesTheSyntheticArm:
    def test_render_scale_is_pinned_to_the_synthetic_renderer(self) -> None:
        """A resolution difference between the arms would sit inside the measurement.

        ``lemely.accuracy.synth.render_handwritten_scan`` renders
        ``page_size=(1240, 1754)`` at ``resolution=150.0``; #59 compares that
        corpus against these fixtures, so the two must share a scale.
        """
        import inspect

        from lemely.accuracy.synth import render_handwritten_scan

        module = _load_module()
        signature = inspect.signature(render_handwritten_scan)

        assert module.TARGET_DPI == 150.0
        assert module.A4_PX == (1240, 1754)
        assert signature.parameters["page_size"].default == (1240, 1754), (
            "the synthetic renderer's page size changed — #59's two arms are no "
            "longer rendered at the same scale"
        )
