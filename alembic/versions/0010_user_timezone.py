"""Add per-user IANA timezone column to users.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column(
                "timezone",
                sa.String(64),
                nullable=False,
                server_default="UTC",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.drop_column("timezone")
