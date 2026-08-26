# corpus/ — parsed CAIE mark schemes

Committed under ask **B8** (human authorisation, 2026-08-26), which weighed the
exposure explicitly: this repo is **public**, the files carry verbatim CAIE
mark-scheme text, the question is copyright/licensing rather than privacy, and
git history makes it effectively permanent.

**That authorisation covers these parsed schemes and nothing else.** It is not
blanket permission to commit real-paper content; anything further needs its own
MISSION §12.7 decision.

## What is here

| path | what |
|---|---|
| `mark-schemes/` | 289 parsed `MarkScheme` JSONs |
| `manifest.json` | provenance, totals, and a SHA256 per file |
| `parse.log` | the parser's own structured log for this run |

## Why it lives here and not in `outputs/`

`outputs/` is **gitignored** (`.gitignore:46`) and nothing under it has ever
been tracked — `git ls-files outputs/` returns zero. B8 asked for the corpus to
be committed, so it needed a tracked home rather than a `git add -f` fighting an
ignore that exists to keep run artifacts out of the repo.

Recording a correction while here: an earlier run's note described
`outputs/schemes/0625_s23_ms_22.json` as *"the committed corpus"*. It was never
committed — it is local, gitignored state. Any reasoning that treated it as a
committed artifact rested on a false premise.

## Provenance

`manifest.json` carries `parser_sha`, which is the point of B8's requirement:
the corpus is attributable to a known parser state, so a future reader can tell
which parser produced it rather than guessing.

**289 parsed of 479 source PDFs, at $0.00** — det-only, no `--use-gemini`, no
Gemini call. That is up from the 250 of `census-2026-08-24-a`, because #93
(cover text outranks the paper-number map, plus B7's 0625 paper-3 constant)
unblocked 39 0625 paper-2 schemes that previously raised `ParseError`.

**The remaining 190 failures are not hidden or explained away.** They are the
det failure set that #45's census classified and that #88 items 1–2 target.
Anyone computing a denominator from this directory is computing over the
*parseable* subset, not the corpus — which is the narrowed-denominator trap this
programme keeps rediscovering.
