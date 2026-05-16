import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from lemely_mvp.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely_mvp.metadata import parse_caie_filename_metadata
from lemely_mvp.schemas import BatchParseResult


REAL_MARK_SCHEME = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


def real_mcq_mark_scheme():
    payload = json.loads(REAL_MARK_SCHEME.read_text(encoding="utf-8"))
    payload["metadata"]["source_document"] = "0625_m20_ms_12.pdf"
    return payload


class MarkSchemeLibraryTests(unittest.TestCase):
    def test_caie_filename_metadata_extraction(self):
        metadata = parse_caie_filename_metadata("0625_m20_ms_12.pdf")

        self.assertEqual(metadata.subject_code, "0625")
        self.assertEqual(metadata.session_month, "Feb/Mar")
        self.assertEqual(metadata.session_year, 2020)
        self.assertEqual(metadata.paper_number, 1)
        self.assertEqual(metadata.paper_variant, 2)

    def test_source_library_indexes_pdfs_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            entries = index_source_library(root)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata.subject_code, "0625")
        self.assertEqual(entries[0].source_path.name, "0625_m20_ms_12.pdf")

    def test_batch_processing_skips_valid_existing_json_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            pdf = root / "0625_m20_ms_12.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            output.mkdir()
            (output / "0625_m20_ms_12.json").write_text(
                json.dumps(real_mcq_mark_scheme()),
                encoding="utf-8",
            )

            calls = []
            result = process_mark_scheme_batch(
                root,
                output,
                parser=lambda path: calls.append(path) or minimal_mcq_mark_scheme(),
            )

        self.assertIsInstance(result, BatchParseResult)
        self.assertEqual(calls, [])
        self.assertEqual(result.items[0].status, "skipped_existing")

    def test_batch_processing_force_invokes_parser_and_validates_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            pdf = root / "0625_m20_ms_12.pdf"
            pdf.write_bytes(b"%PDF-1.4")

            result = process_mark_scheme_batch(
                root,
                output,
                force=True,
                parser=lambda path: real_mcq_mark_scheme(),
            )

            saved = json.loads((output / "0625_m20_ms_12.json").read_text("utf-8"))

        self.assertEqual(result.items[0].status, "parsed")
        self.assertEqual(saved["metadata"]["source_document"], "0625_m20_ms_12.pdf")

    def test_batch_summary_is_strict(self):
        with self.assertRaises(ValidationError):
            BatchParseResult(items=[], extra_field=True)


if __name__ == "__main__":
    unittest.main()
