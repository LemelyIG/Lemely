"""Resolve the local Supabase stack's per-stack secrets from a bare shell.

``LEMELY_SUPABASE__SERVICE_ROLE_KEY``/``__ANON_KEY`` live only in the running
stack, never in ``lemely.toml`` — they are minted fresh by ``supabase start``
and are not something a fresh clone's config can name in advance. Without
this helper, the first call that needs GoTrue (a signup, a login, an admin
create) dies on a bare ``AuthError: Supabase service-role key is not
configured`` — which reads like a broken script rather than "you forgot to
export two variables".

Originally written once, for ``scripts/seed_e2e.py`` (P3.10 chunk a) —
``web/scripts/audit.mjs::resolveSupabaseEnv`` and ``web/playwright.config.ts``
independently resolve the same pair the same way. It now lives here, in
``lemely.runtime`` (the layer nothing in ``lemely.core``/``lemely.io``/
``lemely.app`` may depend on — see the import-linter "layers" contract, which
this module trivially satisfies since it imports nothing from any of them),
so a *third* seeding entry point (``lemely.db.seed``) can call the same
function instead of growing its own copy of a fact nothing regenerates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

#: The two settings every seeding path needs that live only in the running
#: stack. Same pair ``web/scripts/audit.mjs::resolveSupabaseEnv`` resolves.
_STACK_ENV_KEYS = ("LEMELY_SUPABASE__SERVICE_ROLE_KEY", "LEMELY_SUPABASE__ANON_KEY")


def ensure_supabase_env() -> None:
    """Fill the stack's service-role/anon keys from ``supabase status`` if unset.

    An already-exported value always wins, so a caller can point the seed at
    a different stack. ``supabase`` lives at ``~/.local/bin`` and is absent
    from a non-interactive shell's default ``PATH`` (P3.7), hence the
    explicit prefix. **Must be called BEFORE the first ``deps.get_*`` call**
    (or, in ``lemely.db.seed``, before the first real ``AuthService`` is
    built) — that is what reads settings into the process-wide singletons,
    and it happens once.

    Raises:
        SystemExit: ``supabase`` is not on ``PATH`` or ``supabase status``
            failed. Deliberately ``SystemExit``, not a
            :class:`~lemely.runtime.errors.LemelyError`: this is only ever
            called from a CLI ``main()`` (never from library code an
            importer might want to catch and recover from), so an uncaught
            ``SystemExit`` with a clear, actionable message *is* the correct
            behaviour — the same convention ``argparse`` itself already uses
            everywhere else in this codebase — and remapping it through a
            custom exception would only add a catch-and-reraise at every call
            site for no behavioural gain.
    """
    if all(os.environ.get(key) for key in _STACK_ENV_KEYS):
        return
    search_path = f"{os.path.expanduser('~/.local/bin')}:{os.environ['PATH']}"
    binary = shutil.which("supabase", path=search_path)
    if binary is None:
        raise SystemExit(
            "`supabase` is not on PATH (checked ~/.local/bin too), so the stack keys "
            f"cannot be resolved. Export {' and '.join(_STACK_ENV_KEYS)} yourself, "
            "or install the Supabase CLI."
        )
    try:
        # S603 is suppressed deliberately: no untrusted input reaches this
        # call — `binary` is a `shutil.which` result and every argument below
        # is a literal. (Do not open this comment with the four letters ruff
        # reads as a blanket directive, or it becomes one.)
        raw = subprocess.run(  # noqa: S603
            [binary, "status", "-o", "json"],
            capture_output=True,
            check=True,
            text=True,
            env={**os.environ, "PATH": search_path},
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - env-dependent
        raise SystemExit(
            "Could not read `supabase status -o json` to resolve the stack keys. "
            "Start the local stack (`supabase start`), or export "
            f"{' and '.join(_STACK_ENV_KEYS)} yourself."
        ) from exc
    status = json.loads(raw)
    for key, field in zip(_STACK_ENV_KEYS, ("SERVICE_ROLE_KEY", "ANON_KEY"), strict=True):
        if not os.environ.get(key):
            os.environ[key] = status[field]


__all__ = ["ensure_supabase_env"]
