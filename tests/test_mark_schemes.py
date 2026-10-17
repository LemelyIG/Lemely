import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from lemely.core.loose_schemas import MarkSchemeMetadata
from lemely.core.schemas import BatchParseResult
from lemely.io.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely.io.metadata import parse_caie_filename_metadata

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
                parser=lambda path: calls.append(path) or real_mcq_mark_scheme(),
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

    def test_batch_transient_failure_is_recorded_and_does_not_abort(self):
        """A transient Gemini failure (503) on one paper must be recorded as
        status='transient_failed' and must not abort the whole batch."""
        from lemely.runtime.errors import ExternalServiceError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")

            def parser(_path):
                raise ExternalServiceError("503 UNAVAILABLE high demand")

            result = process_mark_scheme_batch(
                root,
                output,
                force=True,
                parser=parser,
            )

        self.assertEqual(result.items[0].status, "transient_failed")
        self.assertEqual(result.transient_failed, 1)
        self.assertEqual(result.parsed, 0)

    def test_batch_cost_ceiling_breach_aborts_the_whole_batch(self):
        """US-030: a per-run spend ceiling breach is a stop signal, not a
        per-paper transient failure.

        ``CostCeilingError`` subclasses ``ExternalServiceError``, so the
        ``except ExternalServiceError`` above used to record it as
        ``status='transient_failed'`` and keep parsing — issuing further paid
        calls into a ceiling the run had already blown, and finishing with a
        ``BatchParseResult`` that reads like an ordinary partially-transient
        batch. It must propagate instead.
        """
        from lemely.runtime.errors import CostCeilingError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_s20_ms_12.pdf").write_bytes(b"%PDF-1.4")

            attempted = []

            def parser(path):
                attempted.append(path)
                raise CostCeilingError(
                    "USD ceiling ($14.0000) exceeded; persistent cumulative spend "
                    "is $14.0100 (across all runs)."
                )

            with self.assertRaises(CostCeilingError) as ctx:
                process_mark_scheme_batch(root, output, force=True, parser=parser)

            # Read while the tmpdir still exists: nothing was written for the
            # aborted batch.
            written = sorted(p.name for p in output.iterdir())

        self.assertIn("USD ceiling", str(ctx.exception))
        # Stopped at the first paper: the second was never attempted, so the
        # batch did not keep spending past the ceiling.
        self.assertEqual(len(attempted), 1)
        self.assertEqual(written, [])

    def test_batch_summary_is_strict(self):
        with self.assertRaises(ValidationError):
            BatchParseResult(items=[], extra_field=True)


def _mark_scheme_metadata_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "subject": "Physics",
        "subject_code": "0625",
        "paper_number": 4,
        "paper_variant": 2,
        "session_month": "May/June",
        "session_year": 2020,
        "paper_type": "theory_extended",
        "maximum_mark": 80,
        "scheme_format": "point_based",
    }
    kwargs.update(overrides)
    return kwargs


class MarkSchemeMetadataSubjectCodeTests(unittest.TestCase):
    """F1 acceptance (3): subject_code moved off `Field(pattern=...)` to a
    Pydantic validator (3.x models reject the `pattern` JSON-Schema keyword) —
    the shape check itself must still hold."""

    def test_valid_subject_code_is_accepted(self):
        metadata = MarkSchemeMetadata.model_validate(_mark_scheme_metadata_kwargs())
        self.assertEqual(metadata.subject_code, "0625")

    def test_invalid_subject_code_still_raises(self):
        with self.assertRaises(ValidationError):
            MarkSchemeMetadata.model_validate(_mark_scheme_metadata_kwargs(subject_code="12a"))

    def test_rejects_trailing_newline(self):
        """F1 review FIX 6: `.match(r"^\\d{4}$")` lets "1234\\n" through — `$`
        matches just before a trailing newline too. `.fullmatch()` does not."""
        with self.assertRaises(ValidationError):
            MarkSchemeMetadata.model_validate(_mark_scheme_metadata_kwargs(subject_code="1234\n"))

    def test_schema_sent_to_gemini_has_no_pattern_keyword(self):
        """The whole point of the move: `pattern` must not appear in the
        JSON schema Gemini's structured-output call would send."""
        import json as _json

        schema_json = _json.dumps(MarkSchemeMetadata.model_json_schema())
        self.assertNotIn("pattern", schema_json)


if __name__ == "__main__":
    unittest.main()
