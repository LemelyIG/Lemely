"""flashcards: decks, cards with SM-2 state, review audit log (P4.6 chunk A).

Revision ID: 0011_flashcards
Revises: 0010_placement_quiz_ownership
Create Date: 2026-08-08 00:00:00.000000

Three additive tables, no existing column touched (D1.2/D1.3):

* ``flashcard_decks`` — one deck per student (``user_id``, ``ON DELETE
  CASCADE`` — a deck is owned by exactly one student, no shared-deck case in
  this phase). ``topic``, when set, is in the P4.2 ``"<code> <name>"``
  vocabulary. ``origin`` records whether the deck was hand-built, generated
  from a weakness, or generated from a topic (chunk B).
* ``flashcards`` — one row per card, ``deck_id`` CASCADE, plus the full SM-2
  scheduling state. The server defaults on ``repetitions``/``ease_factor``/
  ``interval_days``/``lapses``/``due_at`` reproduce exactly what
  ``lemely.core.spaced_repetition.initial_schedule`` computes for a brand-new
  card (0 / 2.5 / 0 / 0 / now()) — ``tests/test_flashcard_schema.py`` pins
  that the two never drift apart. ``due_at`` defaults to ``now()`` so a new
  card is due immediately, matching the SM-2 module's own choice.
* ``flashcard_reviews`` — the append-only audit log a self-graded scheduler
  needs to be checkable (and P5's XP seam, ``XpSource.flashcard_reviewed``):
  ``card_id``/``user_id`` CASCADE, the grade given, and the before/after
  interval + resulting ease factor.

**Enum type creation** follows ``0009``/``0010``'s pattern exactly: each new
type (``deckorigin``, ``cardsource``, ``reviewgrade``) is created explicitly
with ``checkfirst=True`` before any column references it, and every column
uses ``postgresql.ENUM(..., create_type=False)`` so SQLAlchemy never
re-issues ``CREATE TYPE``.

``reviewgrade`` mirrors (does not import) ``lemely.core.spaced_repetition.
ReviewGrade`` — ``core`` may not import ``db``, so the four-member grade
vocabulary (again/hard/good/easy) is declared on both sides; see the
docstrings in ``lemely/core/spaced_repetition.py`` and
``lemely/db/models/flashcards.py`` for why that duplication is intentional.

Downgrade drops tables in reverse dependency order (reviews before cards,
cards before decks), then drops the three enum types.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011_flashcards"
down_revision: str | Sequence[str] | None = "0010_placement_quiz_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    postgresql.ENUM("manual", "weakness", "topic", name="deckorigin").create(bind, checkfirst=True)
    postgresql.ENUM("manual", "ai", name="cardsource").create(bind, checkfirst=True)
    postgresql.ENUM("again", "hard", "good", "easy", name="reviewgrade").create(
        bind, checkfirst=True
    )

    deck_origin = postgresql.ENUM(
        "manual", "weakness", "topic", name="deckorigin", create_type=False
    )
    card_source = postgresql.ENUM("manual", "ai", name="cardsource", create_type=False)
    review_grade = postgresql.ENUM(
        "again", "hard", "good", "easy", name="reviewgrade", create_type=False
    )

    # --- flashcard_decks -----------------------------------------------
    op.create_table(
        "flashcard_decks",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origin", deck_origin, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_flashcard_decks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcard_decks")),
    )
    op.create_index(
        "ix_flashcard_decks_user_id_subject_code",
        "flashcard_decks",
        ["user_id", "subject_code"],
    )

    # --- flashcards ------------------------------------------------------
    op.create_table(
        "flashcards",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("deck_id", sa.UUID(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", card_source, nullable=False),
        sa.Column("source_question_id", sa.String(), nullable=True),
        sa.Column("repetitions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ease_factor", sa.Float(), server_default=sa.text("2.5"), nullable=False),
        sa.Column("interval_days", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lapses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deck_id"],
            ["flashcard_decks.id"],
            name=op.f("fk_flashcards_deck_id_flashcard_decks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcards")),
    )
    op.create_index("ix_flashcards_deck_id_due_at", "flashcards", ["deck_id", "due_at"])

    # --- flashcard_reviews -------------------------------------------------
    op.create_table(
        "flashcard_reviews",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("grade", review_grade, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_before_days", sa.Integer(), nullable=False),
        sa.Column("interval_after_days", sa.Integer(), nullable=False),
        sa.Column("ease_after", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["flashcards.id"],
            name=op.f("fk_flashcard_reviews_card_id_flashcards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_flashcard_reviews_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcard_reviews")),
    )
    op.create_index(
        "ix_flashcard_reviews_user_id_reviewed_at",
        "flashcard_reviews",
        ["user_id", "reviewed_at"],
    )


def downgrade() -> None:
    """Reverse 0011: drop tables in reverse dependency order, then the enum types."""
    op.drop_index("ix_flashcard_reviews_user_id_reviewed_at", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")

    op.drop_index("ix_flashcards_deck_id_due_at", table_name="flashcards")
    op.drop_table("flashcards")

    op.drop_index("ix_flashcard_decks_user_id_subject_code", table_name="flashcard_decks")
    op.drop_table("flashcard_decks")

    bind = op.get_bind()
    postgresql.ENUM(name="reviewgrade").drop(bind, checkfirst=True)
    postgresql.ENUM(name="cardsource").drop(bind, checkfirst=True)
    postgresql.ENUM(name="deckorigin").drop(bind, checkfirst=True)
