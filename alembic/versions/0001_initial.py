"""Initial migration — create users and query_history tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("api_key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("database_url_enc", sa.Text, nullable=False),
        sa.Column("llm_provider", sa.String(20), nullable=False),
        sa.Column("anthropic_api_key_enc", sa.Text, nullable=True),
        sa.Column("groq_api_key_enc", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("daily_query_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("daily_quota_reset_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_api_key_hash", "users", ["api_key_hash"], unique=True)

    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql", sa.Text, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_query_history_user_id_desc",
        "query_history",
        ["user_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_history_user_id_desc", table_name="query_history")
    op.drop_table("query_history")
    op.drop_index("ix_users_api_key_hash", table_name="users")
    op.drop_table("users")
