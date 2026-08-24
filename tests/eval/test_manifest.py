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
    "arm",
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


class TestRunManifestArmField:
    """#28's SHOULD-FIX: the run-level ``arm`` override is invisible in run
    provenance unless it's on the manifest. ``None`` means "no override --
    arm derived per case from ``scan_path``", i.e. what every run before
    this field existed actually did.
    """

    def test_arm_defaults_to_none(self) -> None:
        manifest = _make_run_manifest("dev")
        assert manifest.arm is None

    @pytest.mark.parametrize("arm", ["extract+mark", "oracle+mark"])
    def test_accepts_each_valid_arm_override(self, arm: str) -> None:
        manifest = RunManifest(
            run_id="run-2026-08-21-a",
            git_sha="49bc6cd0000000000000000000000000000000",
            timestamp=datetime.now(UTC),
            prompt_versions={"extraction": "v3", "correction": "v2", "mark_scheme": "v1"},
            params_fingerprint="deadbeefcafe",
            models_by_task={"extraction": "gemini-2.5-flash"},
            cache_mode="read_write",
            split="dev",
            corpus_digest="sha256:abc123",
            arm=arm,
        )
        assert manifest.arm == arm

    def test_rejects_an_invalid_arm_value(self) -> None:
        with pytest.raises(ValidationError):
            RunManifest(
                run_id="run-2026-08-21-a",
                git_sha="49bc6cd0000000000000000000000000000000",
                timestamp=datetime.now(UTC),
                prompt_versions={"extraction": "v3", "correction": "v2", "mark_scheme": "v1"},
                params_fingerprint="deadbeefcafe",
                models_by_task={"extraction": "gemini-2.5-flash"},
                cache_mode="read_write",
                split="dev",
                corpus_digest="sha256:abc123",
                arm="hybrid+mark",
            )

    def test_archived_manifest_missing_arm_key_still_validates(self) -> None:
        """A manifest JSON written before this field existed (no ``arm`` key
        at all) must still parse under ``extra='forbid'`` -- a missing key
        with a default is accepted, only unknown keys are rejected. This is
        what keeps the already-archived manifests under
        ``BUILD/accuracy-runs/`` parseable.
        """
        archived_json = {
            "run_id": "aa-floor-2026-08-23-a-aa-repeats-repeat-01-20260823T113918-a1",
            "git_sha": "b364bf7",
            "timestamp": "2026-08-23T11:41:39.924109Z",
            "prompt_versions": {"extraction": "5", "correction": "4", "mark_scheme": "3"},
            "params_fingerprint": "8a08cb821f60",
            "models_by_task": {
                "mark_scheme": "gemini-2.5-flash",
                "extraction": "gemini-2.5-flash",
                "correction": "gemini-2.5-flash",
            },
            "cache_mode": "bypass",
            "split": "dev",
            "corpus_digest": "e982c884f7f30cd7",
        }
        manifest = RunManifest.model_validate(archived_json)
        assert manifest.arm is None


class TestLabelManifestSplitField:
    @pytest.mark.parametrize("split", ["train", "dev", "test"])
    def test_accepts_each_valid_split_value(self, split: str) -> None:
        record = LabelManifest(paper_id="0580_s23_qp_22", split=split, labeller_id="labeller-1")
        assert record.split == split

    def test_rejects_a_fourth_split_value(self) -> None:
        with pytest.raises(ValidationError):
            LabelManifest(paper_id="0580_s23_qp_22", split="holdout", labeller_id="labeller-1")
