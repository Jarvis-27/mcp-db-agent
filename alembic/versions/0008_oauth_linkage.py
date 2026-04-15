"""Add OAuth identity linkage columns to users.

Adds five nullable columns that record the OAuth provider identity bound to
each local account via the "Connect MCP account" explicit-linking flow:

  oauth_issuer           — authorization server issuer URL
  oauth_subject          — provider-assigned subject (sub claim)
  oauth_email            — email from the OAuth identity token
  oauth_email_verified_at — when the provider last confirmed email ownership
  oauth_last_login_at    — last time a valid bearer token was used for this link

A unique index on (oauth_issuer, oauth_subject) prevents duplicate bindings.
All columns are nullable so existing rows are unaffected and no backfill is
required.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("oauth_issuer", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("oauth_subject", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("oauth_email", sa.String(254), nullable=True))
        batch_op.add_column(
            sa.Column("oauth_email_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("oauth_last_login_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_users_oauth_issuer_subject",
            ["oauth_issuer", "oauth_subject"],
            unique=True,
        )
        batch_op.create_index("ix_users_oauth_email", ["oauth_email"])


def downgrade() -> None:
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.drop_index("ix_users_oauth_issuer_subject")
        batch_op.drop_index("ix_users_oauth_email")
        batch_op.drop_column("oauth_last_login_at")
        batch_op.drop_column("oauth_email_verified_at")
        batch_op.drop_column("oauth_email")
        batch_op.drop_column("oauth_subject")
        batch_op.drop_column("oauth_issuer")
