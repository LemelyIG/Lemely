"""Writes the per-paper label manifest (spec §6), reusing ``LabelManifest``.

Deliberately reuses :class:`lemely.eval.manifest.LabelManifest` rather than
defining a new type — it already carries exactly ``paper_id``, ``split``,
and ``labeller_id``, the spec §6 manifest fields.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from typing import TYPE_CHECKING

from lemely.eval.manifest import LabelManifest
from lemely.labelling.paths import DEFAULT_EVAL_ROOT, manifest_path

if TYPE_CHECKING:
    from pathlib import Path

    from lemely.eval.manifest import Split


def write_label_manifest(
    paper_id: str,
    *,
    split: Split,
    labeller_id: str,
    eval_root: Path = DEFAULT_EVAL_ROOT,
) -> LabelManifest:
    """Write the manifest for ``paper_id`` and return it.

    The write is atomic (write-to-temp then :func:`os.replace`), matching
    :class:`lemely.io.history_store.HistoryStore` and
    :class:`lemely.io.cost_ledger.CostLedger`. That is not defensive
    boilerplate here — the manifest has a concurrent reader by construction.
    ``run_labeller`` writes it from the server thread while anything watching
    for the labelling session to come up polls for the file, and a plain
    ``Path.write_text`` creates the file *before* it has content. A reader that
    checks existence and then parses can therefore land in the gap and read
    zero bytes.

    That is not hypothetical: it is why
    ``tests/eval/test_labeller_cli.py::test_run_labeller_writes_the_manifest_before_serving``
    failed intermittently in CI with ``JSONDecodeError: Expecting value: line 1
    column 1 (char 0)`` — on a loaded runner, never on a fast one. Making the
    write atomic fixes the readers rather than the one test: under
    ``os.replace`` the path only ever names a complete manifest, so "the file
    exists" and "the file parses" stop being separable states.
    """
    manifest = LabelManifest(paper_id=paper_id, split=split, labeller_id=labeller_id)
    path = manifest_path(paper_id, labeller_id, eval_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    # The temp file must share a directory with the destination: os.replace is
    # only atomic within a filesystem, and eval_root may well be a mount of its
    # own. The leading dot keeps a half-written manifest from matching a
    # `manifest.*.json` glob if the process dies between mkstemp and replace.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(manifest.model_dump_json(indent=2))
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return manifest
