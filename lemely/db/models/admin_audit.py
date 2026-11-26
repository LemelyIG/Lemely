"""The admin audit log (spec §4.7): one append-only row per admin money or catalogue action.

``lemely.db.admin_billing_repo.audited`` is the only writer. A trigger rejects UPDATE
and DELETE (the function names the table, so ``plan_tier_terms`` reuses it). Migration
``0057_admin_audit_log`` installs it on real databases; the ``after_create`` listeners below
install the same SQL on ``create_all`` databases (the test harness), so both paths enforce
one rule.

``admin_user_id`` is ``ON DELETE RESTRICT``: ``SET NULL`` would be an UPDATE the
trigger refuses, and ``CASCADE`` would erase history. ``target_id`` has no foreign
key, so deleting a customer leaves the record of what was done to them.
TRUNCATE is not blocked (statement-level, used by test cleanup only).

``ix_admin_audit_log_idempotency`` serves ``admin_billing_repo.already_applied``: an admin
request that carries an idempotency key stores it in ``after`` and is looked up by
``(action, after ->> 'idempotency_key')``. The index is UNIQUE and partial on rows that carry a
key: ``lock_idempotency_key`` serialises two identical requests so the second sees the first's
row, and the unique index makes a duplicate impossible even for a caller that forgot the lock
(the insert fails instead of recording a second grant). Both the query and the migration spell
the expression exactly as below (``IDEMPOTENCY_KEY_SQL`` and ``HAS_IDEMPOTENCY_KEY_SQL``), or
Postgres would not use it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base

APPEND_ONLY_FUNCTION_SQL: Final = """
CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$
"""

APPEND_ONLY_TRIGGER_SQL: Final = """
CREATE TRIGGER trg_admin_audit_log_append_only
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""

#: The key an idempotent admin request stores in ``after``, as the index expression.
IDEMPOTENCY_KEY_SQL: Final = "(after ->> 'idempotency_key')"
#: The partial-index predicate: rows that carry a key. A query must repeat it to use the index.
HAS_IDEMPOTENCY_KEY_SQL: Final = "after ? 'idempotency_key'"


class AdminAuditLog(Base):
    """One admin action: who, what, on which record, why, and the state before and after."""

    __tablename__ = "admin_audit_log"
    __table_args__ = (
        # ``btrim(reason)`` strips spaces only, so a tab or newline reason would pass it.
        sa.CheckConstraint(r"reason ~ '\S'", name="reason_required"),
        sa.Index("ix_admin_audit_log_target", "target_kind", "target_id", "created_at"),
        sa.Index("ix_admin_audit_log_created_at", "created_at"),
        sa.Index(
            "ix_admin_audit_log_idempotency",
            "action",
            sa.text(IDEMPOTENCY_KEY_SQL),
            unique=True,
            postgresql_where=sa.text(HAS_IDEMPOTENCY_KEY_SQL),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    before: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _install_append_only_trigger(
    target: sa.Table, connection: sa.Connection, **_kw: object
) -> None:
    """Install the append-only trigger right after ``create_all`` creates the table."""
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(APPEND_ONLY_FUNCTION_SQL))
        connection.execute(sa.text(APPEND_ONLY_TRIGGER_SQL))


event.listen(AdminAuditLog.__table__, "after_create", _install_append_only_trigger)

__all__ = [
    "APPEND_ONLY_FUNCTION_SQL",
    "APPEND_ONLY_TRIGGER_SQL",
    "HAS_IDEMPOTENCY_KEY_SQL",
    "IDEMPOTENCY_KEY_SQL",
    "AdminAuditLog",
]
