"""Merge the billing chain (``0059_payment_applied_marker``) and the waitlist chain.

``feat/paymob-integration`` and ``develop`` both forked from
``0051_tutor_evidence_uploads``. The branch went on to ``0052_usage_ledger`` ...
``0059_payment_applied_marker``; develop went to ``0052_waitlist_applicants``,
``0053_waitlist_applicant_name`` and ``0054_waitlist_email_confirmation`` (``main`` carries the
same three). Both lines were individually linear, so the merge of the two is what leaves Alembic
with two heads, and ``alembic upgrade head`` refuses to run while "head" is ambiguous
(``.github/workflows/deploy.yml`` ``migrate`` job, ``.github/workflows/ci.yml``,
``docker-entrypoint.sh``).

This revision does nothing to the schema. It is the join point only, exactly like
``0035_merge_parent_invites_review`` and ``0043_merge_heads``. The order Alembic picks between the
two parents does not matter, because the chains touch disjoint schema:

* the waitlist chain creates ``waitlist_applicants`` and ``waitlist_digest_log``, the enums
  ``waitliststatus`` and ``waitlistrole``, and adds columns and one index to
  ``waitlist_applicants``; it touches no other object;
* the billing chain never mentions ``waitlist`` and alters only ``subscriptions``, ``plan_tiers``,
  ``invites``, ``credit_packs``, ``notification_preferences``, ``payments``, the enums
  ``subscriptionstatus``, ``inviterole`` and ``notificationtype``, and tables it creates itself.

The merge preserves the existing revision IDs on both sides.

Revision ID: 0060_merge_heads
Revises: 0059_payment_applied_marker, 0054_waitlist_email_confirmation
Create Date: 2026-11-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
# "0060_merge_heads" is 16.
revision: str = "0060_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0059_payment_applied_marker",
    "0054_waitlist_email_confirmation",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change: this revision only merges the billing and waitlist heads."""


def downgrade() -> None:
    """No schema change: this revision only merges the billing and waitlist heads."""
