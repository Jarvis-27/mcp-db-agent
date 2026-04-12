"""Phase 3: persist plan and quota context in query_history.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("query_history", sa.Column("plan_code", sa.String(40), nullable=True))
    op.add_column("query_history", sa.Column("daily_count", sa.Integer(), nullable=True))
    op.add_column("query_history", sa.Column("daily_limit", sa.Integer(), nullable=True))
    op.add_column("query_history", sa.Column("warning_level", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("query_history", "warning_level")
    op.drop_column("query_history", "daily_limit")
    op.drop_column("query_history", "daily_count")
    op.drop_column("query_history", "plan_code")
