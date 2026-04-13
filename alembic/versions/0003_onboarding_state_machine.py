"""Add verification_tokens table; make database_url_enc nullable; add email_verified_at.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-10 00:00:00.000000

Changes:
- users.database_url_enc: NOT NULL -> nullable (DB URL is now submitted in a
  separate onboarding step, not at registration time).
- users.email_verified_at: new nullable DateTime column.
- verification_tokens: new table for single-use email verification tokens and
  short-lived setup session tokens.
- Data migration: backfill onboarding_status='active' for existing rows that
  already have an api_key_hash (they pre-date the state machine and are active).
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Make database_url_enc nullable - DB URL is submitted post-verification
    # ------------------------------------------------------------------
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("database_url_enc", nullable=True)

    # ------------------------------------------------------------------
    # 2. Add email_verified_at column
    # ------------------------------------------------------------------
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
        )

    # ------------------------------------------------------------------
    # 3. Data migration: rows that already have an api_key_hash are
    #    pre-state-machine active users - mark them as such.
    #    Build the UPDATE with SQLAlchemy so the boolean predicate is compiled
    #    correctly for both PostgreSQL and SQLite.
    # ------------------------------------------------------------------
    users = sa.sql.table(
        "users",
        sa.Column("onboarding_status", sa.String()),
        sa.Column("api_key_hash", sa.String()),
        sa.Column("is_active", sa.Boolean()),
    )
    op.execute(
        users.update()
        .where(users.c.api_key_hash.is_not(None))
        .where(users.c.is_active.is_(True))
        .values(onboarding_status="active")
    )

    # ------------------------------------------------------------------
    # 4. Create verification_tokens table
    # ------------------------------------------------------------------
    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_verification_tokens_user_id",
        "verification_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_verification_tokens_token_hash",
        "verification_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_verification_tokens_token_hash", table_name="verification_tokens")
    op.drop_index("ix_verification_tokens_user_id", table_name="verification_tokens")
    op.drop_table("verification_tokens")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email_verified_at")

    # Restore NOT NULL on database_url_enc - fill empty values with a placeholder
    # so the constraint can be applied without data loss on downgrade.
    op.execute("UPDATE users SET database_url_enc = 'placeholder' WHERE database_url_enc IS NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("database_url_enc", nullable=False)
