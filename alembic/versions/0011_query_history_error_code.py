"""Add error_code column to query_history (G10).

Generic string column for categorical error tagging. First value is
``shutdown_interrupted`` (logged when an in-flight query is cancelled during
graceful shutdown); G6's retry classifier is the obvious next user.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("query_history", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("error_code", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("query_history", recreate="auto") as batch_op:
        batch_op.drop_column("error_code")
