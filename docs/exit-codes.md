# CLI exit codes

`lemely` follows a stable, documented exit-code contract so it composes
reliably with shells, Makefiles, and CI runners.

| Code | Name                   | When it fires                                                              |
| ---- | ---------------------- | -------------------------------------------------------------------------- |
| 0    | Success                | Command completed and produced its result.                                 |
| 1    | Generic failure        | Unexpected error, or partial-failure batch (one or more items failed).     |
| 2    | UsageError             | Bad CLI arguments, missing required flags, mutually-exclusive options.     |
| 3    | ConfigError            | Invalid `lemely.toml`, missing required setting, unreadable paths.         |
| 4    | InputError             | Malformed user-supplied file (answers, weakness JSON, etc.).               |
| 5    | NotFoundError          | Required file, mark scheme, or topic not found on disk.                    |
| 6    | ParseError             | PDF or JSON parse failure (also `--on-error fail` first failure).          |
| 7    | ExternalServiceError   | Gemini API failure that did not recover after retry.                       |
| 130  | KeyboardInterrupt      | User pressed Ctrl-C.                                                       |

## Notes

- `parse-mark-schemes` defaults to `--on-error continue`: per-item failures are
  reported in the JSON payload and the process exits **1** (PartialFailureError).
  Pass `--on-error fail` to exit with the first item's underlying code instead
  (typically **6** for ParseError).
- `doctor` exits **3** when any non-optional check fails. The `gradio_extra_installed`
  check is informational and never blocks success.
- Any uncaught exception that is **not** a `LemelyError` exits **1** after
  being logged through `structlog`.
