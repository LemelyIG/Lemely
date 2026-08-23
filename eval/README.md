# eval/

Runtime data written by the accuracy-programme labelling and rulings
tooling. This directory is deliberately **outside** `lemely/eval/` (which
holds pure Python analysis code, spec §3) — everything under here is
generated filesystem state, not importable analysis logic (spec §3.1, §6).

- `labels/<paper_id>/<labeller_id>/` — the two-pass blind labeller's
  (#46/#47) hash-chained JSONL output: `transcription.jsonl` (pass 1),
  `marking.jsonl` (pass 2), and `manifest.json` (split + labeller identity,
  via `lemely.eval.manifest.LabelManifest`).
- `rulings.jsonl` (DA3/#52, not yet built) will live at this same root
  alongside `labels/`.

Nothing under `eval/` is committed except this README and `.gitkeep`
placeholders — the JSONL/manifest output is per-run, per-labeller data.
