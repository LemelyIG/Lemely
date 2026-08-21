"""RunManifest and label-manifest field-set/type tests (spec §3.3, §6)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from lemely.eval.manifest import LabelManifest, RunManifest

# Spec §3.3 "The record model" — RunManifest field list, exactly, in order.
_SPEC_3_3_RUN_MANIFEST_FIELDS = {
    "run_id",
    "git_sha",
    "timestamp",
    "prompt_versions",
    "params_fingerprint",
    "models_by_task",
    "cache_mode",
    "split",
    "corpus_digest",
}


def _make_run_manifest(split: str) -> RunManifest:
    return RunManifest(
        run_id="run-2026-08-21-a",
        git_sha="49bc6cd0000000000000000000000000000000",
        timestamp=datetime.now(UTC),
        prompt_versions={"extraction": "v3", "correction": "v2", "mark_scheme": "v1"},
        params_fingerprint="deadbeefcafe",
        models_by_task={"extraction": "gemini-2.5-flash"},
        cache_mode="read_write",
        split=split,
        corpus_digest="sha256:abc123",
    )


class TestRunManifestFieldSet:
    def test_exposes_exactly_the_spec_3_3_fields(self) -> None:
        field_names = (
            {f.name for f in dataclasses.fields(RunManifest)}
            if dataclasses.is_dataclass(RunManifest)
            else set(RunManifest.model_fields)
        )
        assert field_names == _SPEC_3_3_RUN_MANIFEST_FIELDS

    @pytest.mark.parametrize("split", ["train", "dev", "test"])
    def test_accepts_each_valid_split_value(self, split: str) -> None:
        manifest = _make_run_manifest(split)
        assert manifest.split == split

    def test_rejects_a_fourth_split_value(self) -> None:
        with pytest.raises(ValidationError):
            _make_run_manifest("holdout")


class TestLabelManifestSplitField:
    @pytest.mark.parametrize("split", ["train", "dev", "test"])
    def test_accepts_each_valid_split_value(self, split: str) -> None:
        record = LabelManifest(paper_id="0580_s23_qp_22", split=split, labeller_id="labeller-1")
        assert record.split == split

    def test_rejects_a_fourth_split_value(self) -> None:
        with pytest.raises(ValidationError):
            LabelManifest(paper_id="0580_s23_qp_22", split="holdout", labeller_id="labeller-1")
