"""device client id

Revision ID: 0003_device_client_id
Revises: 0002_core_schema
Create Date: 2026-07-31 13:00:00.000000

Additive-only (D1.2): adds the stable client-supplied ``client_device_id`` column
to ``devices`` plus an index on ``(user_id, client_device_id)`` so a re-login on
the same device reuses its row instead of consuming a new slot (D1.11).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_device_client_id"
down_revision: Union[str, Sequence[str], None] = "0002_core_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("devices", sa.Column("client_device_id", sa.String(), nullable=True))
    op.create_index(
        "ix_devices_user_id_client_device_id",
        "devices",
        ["user_id", "client_device_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_devices_user_id_client_device_id", table_name="devices")
    op.drop_column("devices", "client_device_id")
