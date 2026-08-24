"""Run and label manifest record types (spec §3.3, §6).

``RunManifest`` carries exactly the fields spec §3.3 lists for it — kept
minimal and spec-exact so M0.1/#25's full ``lemely/eval/`` build can adopt
this without a rewrite. ``LabelManifest`` is the equivalent minimal carrier
for the label-manifest ``split`` field that #46/#47's labeller will write
(spec §6's "manifest recording split assignment and labeller identity").

Both share the same three-value split enum: ``"train" | "dev" | "test"``.
Reading the ``"test"`` split for an evaluation join must go through
:mod:`lemely.eval.test_touch`, never a direct comparison here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Split = Literal["train", "dev", "test"]

# Defined here (not in :mod:`lemely.eval.records`, its more natural home)
# because ``records.py`` already imports ``StrictModel`` from this module --
# a reverse import would be circular. ``lemely.eval.records`` re-imports
# ``Arm`` from here so ``from lemely.eval.records import Arm`` keeps working
# for existing callers; this module is the single source of truth for it.
Arm = Literal["extract+mark", "oracle+mark"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunManifest(StrictModel):
    """One evaluation run's identity and configuration (spec §3.3)."""

    run_id: str
    git_sha: str
    timestamp: datetime
    prompt_versions: dict[str, str]
    params_fingerprint: str
    models_by_task: dict[str, str]
    cache_mode: Literal["read_write", "bypass", "refresh"]
    split: Split
    corpus_digest: str
    arm: Arm | None = None
    """The run-level arm override passed to ``measure_accuracy(arm=...)``
    (#28/M0.4), if any. ``None`` means no override was requested -- the arm
    each case ran was derived per case from whether it had a ``scan_path``,
    which is what every run before this field existed actually did. Folded
    into ``params_fingerprint`` (see ``_build_run_manifest`` in
    ``lemely.accuracy.harness``) so the two arms of an ablation sweep archive
    distinguishable manifests. Defaults to ``None`` -- load-bearing: a
    missing key with a default is accepted by this ``StrictModel``'s
    ``extra="forbid"`` even though an unknown key is rejected, so manifests
    archived before this field existed keep parsing."""


class LabelManifest(StrictModel):
    """Split assignment and labeller identity for one paper's labels (spec §6).

    Minimal by design (DA1): membership assignment itself is M0.7b/#57, out
    of scope here. This exists only so #46/#47's labeller has a stable
    ``split`` type to write against.
    """

    paper_id: str
    split: Split
    labeller_id: str
