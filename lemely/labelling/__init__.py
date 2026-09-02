"""The two-pass blind labeller (spec §6, M2.3/#46).

This package is deliberately outside ``lemely/eval/`` — the labeller needs
filesystem and HTTP IO, which the "Evaluation analyses must stay pure"
import-linter contract forbids for ``lemely.eval`` — and outside
``lemely/web/`` — it is not a product surface and must not depend on the web
app's FastAPI/DB session stack.

Blindness is enforced structurally, not just by convention: the
"The blind labeller must not depend on the correction pipeline" contract in
``pyproject.toml`` forbids any module under here from importing
``lemely.core.correction`` or ``lemely.io.correction_ai``, directly or
transitively. Pass 1 (transcription) serves scan-region image data only;
pass 2 (marking) serves the mark scheme plus the labeller's own pass-1
transcription, read back from the just-written JSONL — never a pipeline
output object such as ``CorrectedQuestion``.

Reads are never gated on the test-split authorisation token that
``lemely.eval.test_touch`` provides — DA1/binding constraint for #46: that
gate is for evaluation-result/label *joins*, not for labelling itself. This
package never imports ``lemely.eval.test_touch``.
"""

from __future__ import annotations
