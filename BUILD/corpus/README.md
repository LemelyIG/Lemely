# Corpus manifest (#44, M2.1 — corpus restoration via PaperScraper)

## What this is

`corpus-manifest-2026-08-23.json` is a **read-only snapshot summary** of the
source corpus fetched by [PaperScraper](https://github.com/) (external tool
at `/home/sico/PaperScraper`, not part of this repo) for CAIE syllabuses
`0580` (Mathematics), `0606` (Additional Mathematics), and `0625` (Physics).

It records, as data: a deterministic digest over the catalogue's `done`
rows, counts by subject/document-type, the session-vs-topical split, the
per-topic breakdown for `0625`'s topical compilations, a coverage check
(question papers with no matching mark scheme), and the one document that
failed to download.

## Where the corpus itself lives

The actual PDFs are **not committed to this repo** and never will be:

- They live at `/home/sico/PaperScraper/papers/` (out-of-tree), tracked by
  PaperScraper's own SQLite catalogue at
  `/home/sico/PaperScraper/papers/index.db`.
- CAIE past papers, mark schemes, and grade-threshold documents are exam
  board copyright material. They are used here for educational
  accuracy-measurement purposes only — never redistributed, never
  committed, never uploaded anywhere outside this local fetch.
- `Sources/` (Lemely's own per-subject fixture tree, `Sources/<Subject>/...`)
  is a **different, gitignored** location with a different shape
  (per-session directories). Mapping PaperScraper's flat catalogue-driven
  layout onto `Sources/` — especially for topical compilations, which are
  not organised by session at all — is a deliberate decision deferred to a
  human (see `BUILD/corpus/corpus-manifest-2026-08-23.json`'s `provenance`
  block and issue #44). Nothing under this directory copies or restructures
  any fetched file.

## Provenance

The fetch that produced the catalogue snapshot this manifest describes was
run under the scope approved in closed issue **#48** (H2 — dry-run scope
approval), using exactly the three commands recorded in the manifest's
`provenance.approved_fetch_commands` field. This directory's tooling never
re-runs that fetch — `scripts/build_corpus_manifest.py` only reads the
catalogue.

## Regenerating the manifest

```bash
.venv/bin/python scripts/build_corpus_manifest.py \
    --db-path /home/sico/PaperScraper/papers/index.db \
    --output BUILD/corpus/corpus-manifest-<UTC-date>.json
```

Both flags have sensible defaults (see `--help`); omitting `--output` writes
`BUILD/corpus/corpus-manifest-<today's UTC date>.json`.

The script opens the catalogue via a `file:...?mode=ro` SQLite URI — it
cannot write to the catalogue even if a bug tried to. It never invokes
`paperscraper fetch`.

## Unit tests

`tests/test_build_corpus_manifest.py` covers the digest function
(`compute_corpus_digest`) against a small temporary SQLite fixture shaped
like the PaperScraper catalogue — not the real catalogue, which lives
outside the repo and is not reproducible in CI. It proves determinism (same
input twice → same digest) and sensitivity (an added, removed, or
checksum-changed row → a different digest).
