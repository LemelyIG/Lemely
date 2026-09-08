"""``DbCooldownStore`` — Postgres-backed cooldown store (spec §4.4, D7.7).

Implements :class:`~lemely.auth.cooldown.CooldownStoreProtocol`. Read
``lemely/db/models/auth_cooldowns.py`` first — it states the storage
contract this class implements against (composite ``(purpose, key_hash)``
key, ``key_hash`` a ``String(64)`` SHA-256 digest, no plaintext column). This
module is the *how*: the concrete store a Cloud Run deployment with more
than one instance wires in place of
:class:`~lemely.auth.cooldown.CooldownStore`'s process-local dict, so a
resend one instance receives is throttled by the stamp another instance
made a moment earlier.

Two rules carry over from :class:`~lemely.auth.cooldown.CooldownStore`
unchanged — same minimum interval per key, same "check and stamp are one
call" contract, same "a rejected call does not itself extend the window" —
and one is new because more than one process can now reach the same row at
once:

1. **Never a raw contact in a column, a log, or an exception message
   (D7.7).** :func:`_hash` — plain
   ``hashlib.sha256(value.encode()).hexdigest()`` — is applied to the key
   before it reaches a query; :class:`~lemely.auth.cooldown.CooldownError`'s
   message (unchanged, shared with :class:`~lemely.auth.cooldown.CooldownStore`)
   names the raw key it was constructed with, exactly as it already does for
   the in-memory store — this module never constructs one with anything
   else. A database read — a backup, a support query, a leak — yields
   nothing that identifies which key a cooldown was stamped for.

2. **The check and the stamp are one statement the database arbitrates,
   never a Python read-then-write, because a lock can only serialise callers
   over a row that already exists.** A never-before-seen ``(purpose,
   key_hash)`` has no row for ``SELECT ... FOR UPDATE`` to lock — two
   concurrent first-time :meth:`check_and_stamp` calls for the same brand-new
   key would both see "no row" and both attempt to insert, and the loser
   would raise an unhandled ``IntegrityError`` on the composite primary key
   rather than the domain's own
   :class:`~lemely.auth.cooldown.CooldownError`. This is exactly the bug
   ``DbOtpStore.issue`` shipped with before its fix (``lemely/db/otp_repo.py``'s
   module docstring, point 2) — the realistic trigger here is two rapid
   clicks on "resend" before either has reached the database. So
   :meth:`check_and_stamp` never branches on a prior ``SELECT`` at all: it
   always runs a single ``INSERT ... ON CONFLICT (purpose, key_hash) DO
   UPDATE ... WHERE`` statement, whose ``WHERE`` clause *is* the cooldown
   check itself. A genuinely new key always inserts cleanly (nothing to
   conflict with); a concurrent second attempt against that same new key
   conflicts on the row the first just created and is evaluated by the exact
   same cooldown guard a normal repeat call would be, so it is correctly
   throttled rather than crashing. Postgres's own conflict resolution for
   ``INSERT ... ON CONFLICT`` — not a lock this process holds — is what
   makes two concurrent inserts of the same key resolve to one winner. This
   is the same database-arbitrates-the-race idiom
   ``DbOtpStore.issue`` uses, spec §4.4 documents in
   ``DbCooldownStore.check_and_stamp``'s own pseudocode, and
   :meth:`~lemely.db.teacher_paper_repo.TeacherPaperRepository.claim_run` /
   :meth:`~lemely.db.auth_token_repo.AuthTokenService.redeem` use for the
   row-already-exists shape of the same principle.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.auth.cooldown import CooldownError
from lemely.db.models.auth_cooldowns import AuthCooldown

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


def _hash(value: str) -> str:
    """SHA-256 hex digest of ``value`` (D7.7) — the only form a key takes here."""
    return hashlib.sha256(value.encode()).hexdigest()


class DbCooldownStore:
    """Postgres-backed :class:`~lemely.auth.cooldown.CooldownStoreProtocol` (spec §4.4, D7.7).

    See the module docstring for the concurrency and hashing guarantees. This
    class is otherwise a drop-in replacement for
    :class:`~lemely.auth.cooldown.CooldownStore`: same ``check_and_stamp(key)``
    call shape, same :class:`~lemely.auth.cooldown.CooldownError` outcome
    with the same ``retry_after`` contract —
    ``tests/test_cooldown_store_parity.py`` proves the two agree on every
    case that matters across processes.

    Unlike :class:`~lemely.auth.cooldown.CooldownStore` — one instance per
    purpose, the purpose implicit in which instance a caller holds — every
    row here also carries an explicit ``purpose`` column, because a single
    table now serves every caller: ``lemely.web.deps`` builds one
    ``DbCooldownStore`` per purpose exactly as it built one ``CooldownStore``
    per purpose, and two different purposes stamping the same underlying key
    (e.g. the same email address, once for signup and once for a
    verification resend) never contend with each other
    (``test_purposes_do_not_interfere``).
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime],
        purpose: str,
        min_seconds: int,
    ) -> None:
        """Wire the store to a session factory, scoped to one ``purpose``.

        Args:
            session_factory: Session factory every call opens its own session
                and transaction from — no session is held across calls.
            clock: Zero-arg callable returning the current aware datetime.
                Injected (matching :class:`~lemely.auth.cooldown.CooldownStore`)
                so the cooldown window is testable without sleeping.
            purpose: This store's slot in the ``(purpose, key_hash)`` primary
                key — ``signup_and_reset`` or ``resend_verification`` today
                (``lemely.web.deps``). Never derived from caller input.
            min_seconds: Minimum interval between successive successful
                stamps of the same key.
        """
        self._sm = session_factory
        self._clock = clock
        self._purpose = purpose
        self._min_interval = timedelta(seconds=min_seconds)

    def check_and_stamp(self, key: str) -> None:
        """Raise if ``key`` was stamped within the cooldown window, else stamp it now.

        Check and stamp are one call, not two — matching
        :meth:`~lemely.auth.cooldown.CooldownStore.check_and_stamp` — and, as
        the module docstring explains, one *statement*: an ``INSERT ...
        ON CONFLICT (purpose, key_hash) DO UPDATE ... WHERE <stale>
        RETURNING`` the database evaluates atomically, never a ``SELECT``
        this process branches on.

        Raises:
            CooldownError: ``key`` was last stamped less than ``min_seconds``
                ago for this store's ``purpose`` — whether that stamp already
                existed or was written by a concurrent caller a moment before
                this one reached the database. The key is left untouched by
                a raise — a rejected call does not itself extend the window.
        """
        now = self._clock()
        cutoff = now - self._min_interval
        key_hash = _hash(key)
        stmt = (
            pg_insert(AuthCooldown)
            .values(purpose=self._purpose, key_hash=key_hash, stamped_at=now)
            .on_conflict_do_update(
                index_elements=[AuthCooldown.purpose, AuthCooldown.key_hash],
                set_={"stamped_at": now},
                # ``<=``, not the strict ``<`` spec §4.4's SQL sketch shows:
                # ``CooldownStore.check_and_stamp`` raises only when
                # ``elapsed < min_interval`` (strict), so a call landing at
                # *exactly* ``min_seconds`` since the last stamp passes there.
                # ``stamped_at <= cutoff`` is that same "elapsed >=
                # min_interval" condition restated in terms of the stored
                # timestamp (``cutoff = now - min_interval``); the strict
                # ``<`` the sketch uses instead rejects that exact-boundary
                # call, which ``tests/test_cooldown_store_parity.py::
                # test_call_after_window_passes[postgres]`` catches directly.
                where=AuthCooldown.stamped_at <= cutoff,
            )
            .returning(AuthCooldown.stamped_at)
        )
        with self._sm.begin() as session:
            stamped = session.execute(stmt).scalar_one_or_none()
            if stamped is not None:
                return
            # The WHERE guard rejected the write: a stamp for this
            # (purpose, key) — ours or a concurrent caller's — is still
            # inside its cooldown. Nothing was changed by our own statement,
            # so a plain follow-up read (no lock needed) gets the timestamp
            # for the message, matching ``DbOtpStore.issue``'s documented
            # shape for the identical "zero rows returned" outcome.
            last = session.execute(
                select(AuthCooldown.stamped_at).where(
                    AuthCooldown.purpose == self._purpose, AuthCooldown.key_hash == key_hash
                )
            ).scalar_one()
        raise CooldownError(key, (self._min_interval - (now - last)).total_seconds())


__all__ = ["DbCooldownStore"]
