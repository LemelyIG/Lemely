# Lemely

Accuracy-first educational assessment tool for CAIE marking workflows.

Lemely parses mark-scheme PDFs into structured JSON, corrects student answers
against them, surfaces topic-level weaknesses, predicts a grade band, and
generates remedial quizzes — all behind a CLI that is safe to script and an
optional Gradio UI for teachers.

## Status

Phase 1 (Foundations) — production-structured package with strict typing,
layered architecture, pre-commit + CI gates, and a stable CLI contract.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"   # ui extra adds Gradio
pre-commit install
```

Supported Python: 3.12, 3.13, 3.14.

## Configuration

Lemely loads settings with precedence: env > `.env` > `lemely.toml` > defaults.
Every section uses `extra='forbid'`; typos are rejected at startup.

See `lemely.toml.example` for the full surface (kept in sync with the schema
by a drift test). Common knobs:

```toml
[gradio]
host = "127.0.0.1"
port = 7860

[paths]
sources_dir = "Sources"
output_dir  = "outputs"
cache_dir   = ".lemely-cache"

[gemini]
model       = "gemini-2.5-flash"
max_retries = 3
```

Set `GEMINI_API_KEY` (or `LEMELY_GEMINI_API_KEY`) in the environment — never in
the TOML.

## CLI quickstart

```bash
lemely doctor                                 # check config, paths, API key
lemely version                                # versions of lemely + deps
lemely estimate-cost Sources/
lemely parse-mark-schemes Sources/ --use-gemini
lemely correct-paper --mark-scheme scheme.json --answers answers.txt
lemely predict-grade correction.json
lemely detect-weaknesses correction.json
lemely generate-quiz weakness.json --count 5
```

Global options: `--json`, `--config PATH`, `--log-format {auto,json,console}`,
`--log-level`, `-v/-q`. JSON mode is the contract for scripts; human mode uses
Rich tables.

## Exit codes

See [`docs/exit-codes.md`](docs/exit-codes.md). Highlights: `0` success,
`2` usage, `3` config, `6` parse, `7` Gemini failure, `1` partial batch.

## Development

```bash
make dev          # editable install + pre-commit
make test         # pytest with coverage gate
make lint         # ruff check
make fmt          # ruff --fix + ruff format
make typecheck    # mypy strict
make imports      # import-linter contracts
make pre-commit   # run all hooks
```

CI runs the same checks across Python 3.12 / 3.13 / 3.14.

### Architecture

```
lemely/
├── core/     # pure domain logic — no I/O, no Gemini, no Rich
├── io/       # disk + Gemini adapters; depends on core only
├── app/      # CLI + Gradio; depends on io and core
└── runtime/  # config, logging, errors — leaf module (no domain imports)
```

Enforced by import-linter contracts in `pyproject.toml`.
