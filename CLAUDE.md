## Environment

- venv at `.venv/` — activate with `source .venv/bin/activate`
- Set `GEMINI_API_KEY` env var (never commit it or put it in `lemely.toml`)
- Copy `lemely.toml.example` → `lemely.toml` for local config (`lemely.toml` is gitignored)
- Run `lemely doctor` to validate config, paths, and API key

## Git

- Signed commits required: always `git commit -S`
- Conventional commit messages with scopes: `feat(det):`, `fix(parsers_det):`, `refactor(core):`, `test(accuracy):`, etc.
- Run `pre-commit run --all-files` and fix all failures before creating any commit
- Do not push unless asked
- Do not create commits unless asked
