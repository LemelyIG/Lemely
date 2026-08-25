"""Hash-chained ruling log machinery (#98, DA3/#52).

This module ships the WRITER and its tests only — no ruling content, no
sample membership, no real corpus reads. See ``lemely/labelling/rulings.py``
for the module docstring on scope, supersede records and pending parking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.labelling.paths import rulings_path
from lemely.labelling.records import read_records, record_hash
from lemely.labelling.rulings import (
    LeafFields,
    RulingScope,
    append_pending_ruling,
    append_ruling,
    append_supersede_ruling,
    applies_to,
    count_pending,
    list_pending,
    resolve_pending_ruling,
)
from lemely.labelling.verify import verify_chain, verify_rulings_chain


def _leaf(**overrides: object) -> LeafFields:
    base: LeafFields = {
        "syllabus_code": "0580",
        "tariff_band": "2",
        "parse_path": "det",
        "question_type_judgement": "calculation",
        "mark_scheme_tokens": ["oe", "cao"],
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


class TestRulingsUsesSharedHashChain:
    def test_module_does_not_redefine_record_hash_or_append_record(self) -> None:
        import lemely.labelling.rulings as rulings_module

        source = Path(rulings_module.__file__).read_text(encoding="utf-8")
        assert "def record_hash" not in source
        assert "def append_record" not in source

    def test_append_ruling_writes_a_valid_hash_chain(self, tmp_path: Path) -> None:
        record = append_ruling(
            scope=RulingScope(syllabus_code="0580"),
            decision="Award the mark under ECF.",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        path = rulings_path(tmp_path)
        records = read_records(path)
        assert len(records) == 1
        assert records[0] == record
        assert verify_chain(path).ok

    def test_record_hash_matches_shared_implementation(self, tmp_path: Path) -> None:
        record = append_ruling(
            scope=RulingScope(),
            decision="d",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        assert record["hash"] == record_hash(record["prev_hash"], record["payload"])


class TestScopePredicate:
    def test_matches_on_syllabus_code(self) -> None:
        scope = RulingScope(syllabus_code="0580")
        assert applies_to(scope, _leaf(syllabus_code="0580"))
        assert not applies_to(scope, _leaf(syllabus_code="0606"))

    def test_matches_on_tariff_band(self) -> None:
        scope = RulingScope(tariff_band="3+")
        assert applies_to(scope, _leaf(tariff_band="3+"))
        assert not applies_to(scope, _leaf(tariff_band="1"))

    def test_matches_on_parse_path(self) -> None:
        scope = RulingScope(parse_path="gemini")
        assert applies_to(scope, _leaf(parse_path="gemini"))
        assert not applies_to(scope, _leaf(parse_path="det"))

    def test_matches_on_question_type_judgement(self) -> None:
        scope = RulingScope(question_type_judgement="list")
        assert applies_to(scope, _leaf(question_type_judgement="list"))
        assert not applies_to(scope, _leaf(question_type_judgement="calculation"))

    def test_matches_on_mark_scheme_token_presence(self) -> None:
        scope = RulingScope(mark_scheme_tokens=["ecf"])
        assert applies_to(scope, _leaf(mark_scheme_tokens=["ecf", "oe"]))
        assert not applies_to(scope, _leaf(mark_scheme_tokens=["oe", "cao"]))

    def test_unset_scope_fields_are_wildcards(self) -> None:
        scope = RulingScope(syllabus_code="0580")
        # tariff_band, parse_path etc are unset -> match regardless of leaf value
        assert applies_to(scope, _leaf(syllabus_code="0580", tariff_band="1"))
        assert applies_to(scope, _leaf(syllabus_code="0580", tariff_band="3+"))

    def test_empty_scope_matches_everything(self) -> None:
        scope = RulingScope()
        assert applies_to(scope, _leaf())
        assert applies_to(scope, _leaf(syllabus_code="9709", tariff_band="3+"))


class TestSupersedeRecords:
    def test_supersede_preserves_both_records_and_a_valid_chain(self, tmp_path: Path) -> None:
        original = append_ruling(
            scope=RulingScope(syllabus_code="0580"),
            decision="Original decision.",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        original_id = original["payload"]["ruling_id"]  # type: ignore[index]

        superseding = append_supersede_ruling(
            supersedes_ruling_id=original_id,  # type: ignore[arg-type]
            scope=RulingScope(syllabus_code="0580"),
            decision="Corrected decision.",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )

        path = rulings_path(tmp_path)
        records = read_records(path)
        assert len(records) == 2
        assert records[0]["payload"]["decision"] == "Original decision."
        assert records[1]["payload"]["decision"] == "Corrected decision."
        assert records[1]["payload"]["supersedes"] == original_id
        assert superseding["payload"]["supersedes"] == original_id

        assert verify_chain(path).ok
        assert verify_rulings_chain(tmp_path).ok


class TestPendingRulingParking:
    def test_pending_ruling_is_countable_until_resolved(self, tmp_path: Path) -> None:
        assert count_pending(tmp_path) == 0

        pending = append_pending_ruling(
            paper_id="0580_s23_qp_22",
            question_id="3",
            question="Does ECF apply here?",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        pending_id = pending["payload"]["pending_id"]  # type: ignore[index]

        assert count_pending(tmp_path) == 1
        pending_list = list_pending(tmp_path)
        assert len(pending_list) == 1
        assert pending_list[0]["payload"]["pending_id"] == pending_id

        resolve_pending_ruling(
            pending_id=pending_id,  # type: ignore[arg-type]
            resolving_ruling_id="ruling-xyz",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )

        assert count_pending(tmp_path) == 0
        assert list_pending(tmp_path) == []

    def test_multiple_pending_rulings_count_independently(self, tmp_path: Path) -> None:
        append_pending_ruling(
            paper_id="p1",
            question_id="1",
            question="q1?",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        second = append_pending_ruling(
            paper_id="p2",
            question_id="2",
            question="q2?",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        assert count_pending(tmp_path) == 2

        resolve_pending_ruling(
            pending_id=second["payload"]["pending_id"],  # type: ignore[arg-type,index]
            resolving_ruling_id="ruling-abc",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        assert count_pending(tmp_path) == 1


class TestChainVerification:
    def test_verify_rulings_chain_reports_ok_on_clean_log(self, tmp_path: Path) -> None:
        append_ruling(
            scope=RulingScope(),
            decision="d1",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        append_ruling(
            scope=RulingScope(),
            decision="d2",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        result = verify_rulings_chain(tmp_path)
        assert result.ok
        assert result.broken_index is None

    def test_verify_rulings_chain_reports_first_break(self, tmp_path: Path) -> None:
        import json

        append_ruling(
            scope=RulingScope(),
            decision="d1",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        append_ruling(
            scope=RulingScope(),
            decision="d2",
            labeller_id="labeller-A",
            eval_root=tmp_path,
        )
        path = rulings_path(tmp_path)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        records = [json.loads(line) for line in lines]
        records[0]["payload"]["decision"] = "TAMPERED"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

        result = verify_rulings_chain(tmp_path)
        assert not result.ok
        assert result.broken_index == 0


class TestRulingsNeverReadPipelineOutput:
    def test_rulings_module_does_not_import_the_correction_pipeline(self) -> None:
        """DA3 (H8): a ruling is never resolved by looking at pipeline output.

        Enforced structurally by the import-linter contract
        (tests/architecture/test_rulings_import_contract.py); this test is a
        cheap in-process smoke check that the module's own import list stays
        clean, so a regression is caught even before lint-imports runs.
        """
        import lemely.labelling.rulings as rulings_module

        source = Path(rulings_module.__file__).read_text(encoding="utf-8")
        assert "lemely.core.correction" not in source
        assert "lemely.io.correction_ai" not in source
        assert "lemely.core.schemas" not in source


def test_applies_to_rejects_unknown_leaf_field_keys_gracefully() -> None:
    # applies_to only reads the fixed set of fields it knows about; an
    # over-supplied leaf dict (extra keys) must not raise.
    scope = RulingScope(syllabus_code="0580")
    leaf = _leaf()
    leaf_with_extra = dict(leaf)
    leaf_with_extra["unrelated_extra_field"] = "whatever"
    assert applies_to(scope, leaf_with_extra) == applies_to(scope, leaf)  # type: ignore[arg-type]


if __name__ == "__main__":
    pytest.main([__file__])


class TestPendingTailCannotBeFaked:
    """DA3 requires the pending tail at ZERO before the irreversible split freeze.

    A resolution record that answers nothing must not drive that gate green.
    """

    def test_a_resolution_naming_an_unparked_id_does_not_clear_anything(
        self, tmp_path: Path
    ) -> None:
        from lemely.labelling.rulings import (
            append_pending_ruling,
            count_pending,
            list_orphan_resolutions,
            resolve_pending_ruling,
        )

        append_pending_ruling(
            paper_id="0625_s24_ms_21",
            question_id="1a",
            question="Does ECF apply across parts here?",
            labeller_id="labeller-a",
            eval_root=tmp_path,
            pending_id="real-question",
        )
        # Resolves an id that was never parked -- a typo, or a fabricated record.
        resolve_pending_ruling(
            pending_id="never-parked",
            resolving_ruling_id="ruling-1",
            labeller_id="labeller-a",
            eval_root=tmp_path,
        )

        assert count_pending(eval_root=tmp_path) == 1, (
            "an unmatched resolution must not answer a real open question"
        )
        orphans = list_orphan_resolutions(eval_root=tmp_path)
        assert len(orphans) == 1, "and it must be surfaced, not silently dropped"

    def test_a_resolution_appended_before_its_question_does_not_retroactively_answer_it(
        self, tmp_path: Path
    ) -> None:
        from lemely.labelling.rulings import (
            append_pending_ruling,
            count_pending,
            resolve_pending_ruling,
        )

        # Resolution first, question second -- impossible in a real session,
        # but nothing in an append-only file prevents writing it.
        resolve_pending_ruling(
            pending_id="q-1",
            resolving_ruling_id="ruling-1",
            labeller_id="labeller-a",
            eval_root=tmp_path,
        )
        append_pending_ruling(
            paper_id="0625_s24_ms_21",
            question_id="1a",
            question="Does the list rule over-tariff this?",
            labeller_id="labeller-a",
            eval_root=tmp_path,
            pending_id="q-1",
        )

        assert count_pending(eval_root=tmp_path) == 1, (
            "a question cannot be answered before it was asked"
        )

    def test_the_ordinary_parked_then_resolved_sequence_still_clears(self, tmp_path: Path) -> None:
        """The guard must not break the case it exists to protect."""
        from lemely.labelling.rulings import (
            append_pending_ruling,
            count_pending,
            list_orphan_resolutions,
            resolve_pending_ruling,
        )

        append_pending_ruling(
            paper_id="0625_s24_ms_21",
            question_id="1a",
            question="Does ECF apply across parts here?",
            labeller_id="labeller-a",
            eval_root=tmp_path,
            pending_id="q-1",
        )
        resolve_pending_ruling(
            pending_id="q-1",
            resolving_ruling_id="ruling-1",
            labeller_id="labeller-a",
            eval_root=tmp_path,
        )

        assert count_pending(eval_root=tmp_path) == 0
        assert list_orphan_resolutions(eval_root=tmp_path) == []
