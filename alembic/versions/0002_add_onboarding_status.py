"""Add email and onboarding_status to users; make api_key_hash nullable.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make api_key_hash nullable — pending users don't have a key yet.
    # Existing rows keep their existing hash values; only new pending rows
    # will have NULL.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("api_key_hash", nullable=True)

    # Add email column (nullable; required once Auth0 is integrated in Phase 1).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(254), nullable=True))
    op.create_index("ix_users_email", "users", ["email"])

    # Add onboarding_status. Existing rows already have valid API keys so
    # they are backfilled as 'active' via server_default.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "onboarding_status",
                sa.String(40),
                nullable=False,
                server_default="active",
            )
        )

    # Drop the server_default so future inserts cannot silently receive 'active'.
    # Existing rows are already backfilled; new inserts must supply the value
    # explicitly (the ORM model's Python-side default is 'pending_email_verification').
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("onboarding_status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("onboarding_status")

    op.drop_index("ix_users_email", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email")

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("api_key_hash", nullable=False)
