"""Self-tests for :mod:`tests.mupdf_sweep`: every way to open (or graft) a PDF
that the sweep claims to see goes red here, fed as a source string.

The repo-level assertions (``sweep(root, ...) == ALLOWED_...``) stay in
``SanctionedOpenerSweepTests`` in ``tests/test_scan_limits.py``. A sweep that
passes on the tree proves nothing unless it also fails on the evasions, so
each form below is a case the sweep must report, and the negatives are the
forms it must not.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.mupdf_sweep import (
    ALLOWED_OPENS,
    ALLOWED_PRESCANNED,
    find_mupdf_opens,
    find_prescanned_constructions,
    sweep,
)

_F = "lemely/x.py"
_MODULE = {(_F, "<module>")}


def _opens(source: str) -> set[tuple[str, str]]:
    return find_mupdf_opens(textwrap.dedent(source), _F)


class MupdfOpenEvasionTests(unittest.TestCase):
    """Each form the brief names, at module scope."""

    def test_import_pymupdf_as_alias(self) -> None:
        self.assertEqual(_opens("import pymupdf as m\nm.open(stream=b)\n"), _MODULE)

    def test_import_fitz_as_alias_document(self) -> None:
        self.assertEqual(_opens("import fitz as f\nf.Document(b)\n"), _MODULE)

    def test_plain_import_open_and_document(self) -> None:
        self.assertEqual(_opens("import pymupdf\npymupdf.open(b)\n"), _MODULE)
        self.assertEqual(_opens("import fitz\nfitz.open(b)\n"), _MODULE)
        self.assertEqual(_opens("import pymupdf\npymupdf.Document(b)\n"), _MODULE)

    def test_from_import_open_as_alias(self) -> None:
        self.assertEqual(_opens("from pymupdf import open as o\no(b)\n"), _MODULE)

    def test_from_import_document(self) -> None:
        self.assertEqual(_opens("from pymupdf import Document\nDocument(b)\n"), _MODULE)

    def test_from_fitz_import(self) -> None:
        self.assertEqual(_opens("from fitz import open\nopen(b)\n"), _MODULE)
        self.assertEqual(_opens("from fitz import Document as D\nD(b)\n"), _MODULE)

    def test_star_import_binds_open_and_document(self) -> None:
        self.assertEqual(_opens("from pymupdf import *\nopen(b)\n"), _MODULE)
        self.assertEqual(_opens("from pymupdf import *\nDocument(stream=b)\n"), _MODULE)

    def test_assigned_module_alias(self) -> None:
        self.assertEqual(_opens("import pymupdf\nz = pymupdf\nz.open(b)\n"), _MODULE)
        self.assertEqual(_opens("import fitz\nz = fitz\nz.Document(b)\n"), _MODULE)

    def test_assigned_opener_alias(self) -> None:
        self.assertEqual(_opens("import pymupdf\nz = pymupdf.open\nz(b)\n"), _MODULE)
        self.assertEqual(_opens("import pymupdf\nz = pymupdf.Document\nz(b)\n"), _MODULE)

    def test_annotated_assignment_alias(self) -> None:
        self.assertEqual(
            _opens("import pymupdf\nz: object = pymupdf.open\nz(b)\n"),
            _MODULE,
        )

    def test_chained_assignment_alias(self) -> None:
        self.assertEqual(_opens("import pymupdf\na = b = pymupdf.open\nb(x)\n"), _MODULE)

    def test_alias_of_a_from_import(self) -> None:
        self.assertEqual(_opens("from pymupdf import open as o\nz = o\nz(b)\n"), _MODULE)

    def test_insert_pdf_anywhere(self) -> None:
        self.assertEqual(_opens("doc.insert_pdf(other)\n"), _MODULE)
        self.assertEqual(
            _opens("def f(out, doc):\n    out.insert_pdf(doc, links=False)\n"),
            {(_F, "f")},
        )

    def test_insert_file_anywhere(self) -> None:
        self.assertEqual(_opens("doc.insert_file(b)\n"), _MODULE)

    def test_insert_called_through_a_reference(self) -> None:
        # ``fn = out.insert_pdf; fn(doc)`` has no ``.insert_pdf(`` call.
        self.assertEqual(_opens("fn = out.insert_pdf\nfn(doc)\n"), _MODULE)

    def test_keyword_only_open(self) -> None:
        self.assertEqual(
            _opens("import pymupdf\npymupdf.open(stream=b, filetype='pdf')\n"), _MODULE
        )


class MupdfOpenScopeTests(unittest.TestCase):
    """Bindings are resolved per scope and the enclosing function is reported."""

    def test_open_is_attributed_to_its_enclosing_function(self) -> None:
        source = """
            import pymupdf

            def outer():
                def inner():
                    return pymupdf.open(b)
                return inner
        """
        self.assertEqual(_opens(source), {(_F, "inner")})

    def test_async_function_and_method(self) -> None:
        source = """
            import pymupdf

            async def go():
                pymupdf.open(b)

            class C:
                def method(self):
                    pymupdf.open(b)
        """
        self.assertEqual(_opens(source), {(_F, "go"), (_F, "method")})

    def test_function_scope_import(self) -> None:
        source = """
            def f():
                import pymupdf
                return pymupdf.open(b)
        """
        self.assertEqual(_opens(source), {(_F, "f")})

    def test_function_scope_from_import_and_alias(self) -> None:
        source = """
            def f():
                from pymupdf import open as o
                return o(b)

            def g():
                import pymupdf
                z = pymupdf.open
                return z(b)
        """
        self.assertEqual(_opens(source), {(_F, "f"), (_F, "g")})

    def test_module_binding_is_seen_inside_a_function(self) -> None:
        source = """
            import pymupdf as m
            z = m.open

            def f():
                return z(b)
        """
        self.assertEqual(_opens(source), {(_F, "f")})

    def test_binding_in_one_function_does_not_leak_to_another(self) -> None:
        source = """
            def f():
                import pymupdf
                return pymupdf

            def g():
                return pymupdf.open(b)
        """
        self.assertEqual(_opens(source), set())

    def test_class_scope_alias_is_not_visible_to_its_methods(self) -> None:
        source = """
            import pymupdf

            class C:
                z = pymupdf.open

                def method(self):
                    return z(b)
        """
        self.assertEqual(_opens(source), set())

    def test_binding_under_if_and_try(self) -> None:
        source = """
            try:
                import pymupdf as m
            except ImportError:
                m = None
            if True:
                m.open(b)
        """
        self.assertEqual(_opens(source), _MODULE)

    def test_two_files_are_told_apart_by_filename(self) -> None:
        self.assertEqual(
            find_mupdf_opens("import pymupdf\npymupdf.open(b)\n", "lemely/other.py"),
            {("lemely/other.py", "<module>")},
        )


class MupdfOpenNegativeTests(unittest.TestCase):
    """What the sweep must not report."""

    def test_bare_open_makes_an_empty_document(self) -> None:
        self.assertEqual(_opens("import pymupdf\nout = pymupdf.open()\n"), set())
        self.assertEqual(_opens("from pymupdf import open as o\no()\n"), set())

    def test_other_pymupdf_calls(self) -> None:
        self.assertEqual(_opens("import pymupdf\npymupdf.Matrix(1, 1)\n"), set())
        self.assertEqual(_opens("import pymupdf\npymupdf.Rect(0, 0, 1, 1)\n"), set())
        self.assertEqual(_opens("import fitz\nfitz.Pixmap(b)\n"), set())

    def test_local_named_open_that_is_not_from_pymupdf(self) -> None:
        self.assertEqual(_opens("def f(open):\n    return open(b)\n"), set())
        self.assertEqual(_opens("open = make_opener()\nopen(b)\n"), set())
        self.assertEqual(_opens("import io\nio.open(b)\n"), set())
        self.assertEqual(_opens("with open('f') as fh:\n    fh.read()\n"), set())

    def test_open_on_another_module_named_like_an_alias(self) -> None:
        self.assertEqual(_opens("import pathlib as m\nm.open(b)\n"), set())

    def test_submodule_alias_is_not_the_package(self) -> None:
        # ``import pymupdf.mupdf as m`` binds the low-level module, not pymupdf.
        self.assertEqual(_opens("import pymupdf.mupdf as m\nm.open(b)\n"), set())

    def test_type_uses_of_document_are_not_calls(self) -> None:
        source = """
            import pymupdf

            def f(doc: pymupdf.Document) -> pymupdf.Document:
                x: pymupdf.Document = doc
                return x
        """
        self.assertEqual(_opens(source), set())

    def test_an_alias_assignment_alone_is_not_an_open(self) -> None:
        self.assertEqual(_opens("import pymupdf\nz = pymupdf.open\n"), set())
        self.assertEqual(_opens("import pymupdf\nz = pymupdf\n"), set())

    def test_syntax_only_mentions(self) -> None:
        self.assertEqual(
            _opens('"""pymupdf.open(b) and doc.insert_pdf(x)"""\n# fitz.open(b)\n'), set()
        )


class MupdfOpenKnownBlindSpotTests(unittest.TestCase):
    """The documented limits of the sweep, pinned so the docstring in
    :mod:`tests.mupdf_sweep` and this file cannot drift apart. These are
    reviewer territory; a test here turning red means the sweep got better and
    the module docstring needs its limits list updated."""

    def test_aliasing_deeper_than_one_assignment(self) -> None:
        self.assertEqual(_opens("import pymupdf\na = pymupdf\nb = a\nb.open(x)\n"), set())
        self.assertEqual(_opens("import pymupdf\na = pymupdf.open\nb = a\nb(x)\n"), set())

    def test_getattr_and_importlib(self) -> None:
        self.assertEqual(_opens('import pymupdf\ngetattr(pymupdf, "open")(b)\n'), set())
        self.assertEqual(
            _opens('import importlib\nimportlib.import_module("pymupdf").open(b)\n'),
            set(),
        )

    def test_opener_passed_as_a_value(self) -> None:
        self.assertEqual(_opens("import pymupdf\nmap(pymupdf.open, blobs)\n"), set())

    def test_low_level_mupdf_open(self) -> None:
        self.assertEqual(
            _opens("import pymupdf.mupdf as m\nm.fz_open_document_with_buffer('pdf', buf)\n"),
            set(),
        )

    def test_walrus_alias(self) -> None:
        self.assertEqual(_opens("import pymupdf\n(z := pymupdf.open)(b)\n"), set())
        self.assertEqual(_opens("import pymupdf\nif (z := pymupdf.open):\n    z(b)\n"), set())

    def test_subclassing_document_or_open(self) -> None:
        self.assertEqual(
            _opens("import pymupdf\nclass D(pymupdf.Document):\n    pass\nD(b)\n"),
            set(),
        )
        self.assertEqual(
            _opens("from pymupdf import Document\nclass D(Document):\n    pass\nD(b)\n"),
            set(),
        )

    def test_prescanned_through_a_module_attribute_alias(self) -> None:
        source = "import m\nP = m.PrescannedPdf\nP(b)\n"
        self.assertEqual(find_prescanned_constructions(source, _F), set())

    def test_roots_other_than_lemely_are_not_swept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("scripts/run_real_paper_accuracy.py", "main.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("import fitz\ndoc = fitz.open(p)\n", encoding="utf-8")
            (root / "lemely").mkdir()
            self.assertEqual(sweep(root, find_mupdf_opens), set())


class PrescannedConstructionTests(unittest.TestCase):
    def test_direct_and_attribute_construction(self) -> None:
        self.assertEqual(
            find_prescanned_constructions("PrescannedPdf(b)\n", _F),
            _MODULE,
        )
        self.assertEqual(
            find_prescanned_constructions("m.PrescannedPdf(data=b)\n", _F),
            _MODULE,
        )

    def test_construction_through_an_import_alias(self) -> None:
        source = "from lemely.io.pdf_prescan import PrescannedPdf as P\nP(b)\n"
        self.assertEqual(find_prescanned_constructions(source, _F), _MODULE)

    def test_construction_through_an_assigned_alias(self) -> None:
        self.assertEqual(
            find_prescanned_constructions("z = PrescannedPdf\nz(b)\n", _F),
            _MODULE,
        )

    def test_enclosing_function_is_reported(self) -> None:
        self.assertEqual(
            find_prescanned_constructions("def f():\n    return PrescannedPdf(b)\n", _F),
            {(_F, "f")},
        )

    def test_type_use_and_other_names_are_not_constructions(self) -> None:
        source = (
            "def f(p: PrescannedPdf) -> None:\n    isinstance(p, PrescannedPdf)\n    Other(p)\n"
        )
        self.assertEqual(find_prescanned_constructions(source, _F), set())


class SweepTests(unittest.TestCase):
    """:func:`sweep` walks ``root/"lemely"`` and unions the finder's results."""

    def _tree(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def test_finds_across_files_and_reports_relative_posix_paths(self) -> None:
        root = self._tree(
            {
                "lemely/io/a.py": "import pymupdf\ndef f():\n    pymupdf.open(b)\n",
                "lemely/web/b.py": "import fitz as z\nz.Document(b)\n",
                "lemely/web/c.py": "import pymupdf\npymupdf.open()\n",
            }
        )
        self.assertEqual(
            sweep(root, find_mupdf_opens),
            {("lemely/io/a.py", "f"), ("lemely/web/b.py", "<module>")},
        )

    def test_ignores_files_outside_lemely(self) -> None:
        root = self._tree(
            {
                "tests/t.py": "import pymupdf\npymupdf.open(b)\n",
                "scripts/s.py": "import pymupdf\npymupdf.open(b)\n",
                "lemely/ok.py": "x = 1\n",
            }
        )
        self.assertEqual(sweep(root, find_mupdf_opens), set())

    def test_an_evasion_in_the_tree_breaks_the_allowlist_equality(self) -> None:
        """The repo-level assertion is ``sweep(...) == ALLOWED_OPENS``; prove it
        goes red when a tree adds an evasion beside the sanctioned openers."""
        sanctioned = "\n".join(
            f"def {name}(b):\n    return pymupdf.open(stream=b)\n"
            for _file, name in sorted(ALLOWED_OPENS)
            if name != "_copy_pages"
        )
        copier = "def _copy_pages(doc, out):\n    out.insert_pdf(doc)\n"
        clean = self._tree({"lemely/io/pdf_canonical.py": "import pymupdf\n" + sanctioned + copier})
        self.assertEqual(sweep(clean, find_mupdf_opens), ALLOWED_OPENS)

        evaded = self._tree(
            {
                "lemely/io/pdf_canonical.py": "import pymupdf\n" + sanctioned + copier,
                "lemely/web/evil.py": (
                    "import pymupdf as m\nz = m.open\n\ndef h(b):\n    return z(b)\n"
                ),
            }
        )
        found = sweep(evaded, find_mupdf_opens)
        self.assertNotEqual(found, ALLOWED_OPENS)
        self.assertEqual(found - ALLOWED_OPENS, {("lemely/web/evil.py", "h")})

    def test_a_prescanned_construction_in_the_tree_breaks_the_allowlist_equality(self) -> None:
        clean = self._tree(
            {"lemely/io/pdf_prescan.py": "def prescan_pdf(b):\n    return PrescannedPdf(b)\n"}
        )
        self.assertEqual(sweep(clean, find_prescanned_constructions), ALLOWED_PRESCANNED)
        evaded = self._tree(
            {
                "lemely/io/pdf_prescan.py": "def prescan_pdf(b):\n    return PrescannedPdf(b)\n",
                "lemely/web/evil.py": (
                    "from x import PrescannedPdf as P\ndef h(b):\n    return P(b)\n"
                ),
            }
        )
        self.assertNotEqual(sweep(evaded, find_prescanned_constructions), ALLOWED_PRESCANNED)


class AllowlistTests(unittest.TestCase):
    def test_allowlists_are_the_sanctioned_functions(self) -> None:
        self.assertEqual(
            ALLOWED_OPENS,
            {
                ("lemely/io/pdf_canonical.py", "open_checked_pdf"),
                ("lemely/io/pdf_canonical.py", "_copy_pages"),
            },
        )
        self.assertEqual(ALLOWED_PRESCANNED, {("lemely/io/pdf_prescan.py", "prescan_pdf")})


if __name__ == "__main__":
    unittest.main()
