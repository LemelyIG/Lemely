"""class model: nullable school_id + join_code

Revision ID: 0004_class_model
Revises: 0003_device_client_id
Create Date: 2026-08-05 00:00:00.000000

D3.1: two changes to ``classes``, landing the real class model + row-level
teacher tenancy.

* ``school_id`` becomes NULLABLE. This is the one recorded relaxation of
  D1.2's additive-only guarantee (see BUILD/DECISIONS.md D3.1): the MISSION
  requires that a teacher can be independent of any school, which P1.3's
  ``NOT NULL`` made unrepresentable. Dropping the constraint invalidates no
  existing row and needs no backfill.
* ``join_code`` is added (unique, indexed) — server-generated per class by
  ``ClassService.create_class`` so a student can self-enrol without a school
  seat. Nullable at the column level for any pre-existing row (none in
  practice, since no class rows exist without this column), always populated
  going forward.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_class_model"
down_revision: Union[str, Sequence[str], None] = "0003_device_client_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("classes", "school_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("classes", sa.Column("join_code", sa.String(), nullable=True))
    op.create_unique_constraint(op.f("uq_classes_join_code"), "classes", ["join_code"])
    op.create_index("ix_classes_join_code", "classes", ["join_code"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_classes_join_code", table_name="classes")
    op.drop_constraint(op.f("uq_classes_join_code"), "classes", type_="unique")
    op.drop_column("classes", "join_code")
    op.alter_column("classes", "school_id", existing_type=sa.UUID(), nullable=False)
