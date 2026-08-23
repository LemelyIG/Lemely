"""Writes the per-paper label manifest (spec §6), reusing ``LabelManifest``.

Deliberately reuses :class:`lemely.eval.manifest.LabelManifest` rather than
defining a new type — it already carries exactly ``paper_id``, ``split``,
and ``labeller_id``, the spec §6 manifest fields.
"""

from __future__ import annotations

from pathlib import Path

from lemely.eval.manifest import LabelManifest, Split
from lemely.labelling.paths import DEFAULT_EVAL_ROOT, manifest_path


def write_label_manifest(
    paper_id: str,
    *,
    split: Split,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> LabelManifest:
    manifest = LabelManifest(paper_id=paper_id, split=split, labeller_id=labeller_id)
    path = manifest_path(paper_id, labeller_id, eval_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest
