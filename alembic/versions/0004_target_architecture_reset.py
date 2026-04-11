"""Reset hosted auth schema to the tenant-backed target architecture.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("verification_tokens")
    op.drop_index("ix_query_history_user_id_desc", table_name="query_history")
    op.drop_table("query_history")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_api_key_hash", table_name="users")
    op.drop_table("users")

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("trust_level", sa.String(40), nullable=False),
        sa.Column("billing_status", sa.String(40), nullable=False),
        sa.Column("plan_code", sa.String(40), nullable=False),
        sa.Column("daily_query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_quota_reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_tenant_memberships_email", "tenant_memberships", ["email"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column(
            "created_by_membership_id",
            sa.String(36),
            sa.ForeignKey("tenant_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "tenant_databases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("database_url_enc", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False),
        sa.Column("last_validation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validation_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenant_databases_tenant_id", "tenant_databases", ["tenant_id"])

    op.create_table(
        "owner_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_membership_id",
            sa.String(36),
            sa.ForeignKey("tenant_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_owner_sessions_tenant_membership_id", "owner_sessions", ["tenant_membership_id"])
    op.create_index("ix_owner_sessions_session_hash", "owner_sessions", ["session_hash"], unique=True)

    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "membership_id",
            sa.String(36),
            sa.ForeignKey("tenant_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_verification_tokens_membership_id", "verification_tokens", ["membership_id"])
    op.create_index("ix_verification_tokens_token_hash", "verification_tokens", ["token_hash"], unique=True)

    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("api_key_id", sa.String(36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_query_history_tenant_id_desc", "query_history", ["tenant_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_query_history_tenant_id_desc", table_name="query_history")
    op.drop_table("query_history")
    op.drop_index("ix_verification_tokens_token_hash", table_name="verification_tokens")
    op.drop_index("ix_verification_tokens_membership_id", table_name="verification_tokens")
    op.drop_table("verification_tokens")
    op.drop_index("ix_owner_sessions_session_hash", table_name="owner_sessions")
    op.drop_index("ix_owner_sessions_tenant_membership_id", table_name="owner_sessions")
    op.drop_table("owner_sessions")
    op.drop_index("ix_tenant_databases_tenant_id", table_name="tenant_databases")
    op.drop_table("tenant_databases")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_tenant_memberships_email", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_table("tenants")

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("api_key_hash", sa.String(64), unique=True, nullable=True),
        sa.Column("database_url_enc", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(20), nullable=False),
        sa.Column("anthropic_api_key_enc", sa.Text(), nullable=True),
        sa.Column("groq_api_key_enc", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("daily_query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_quota_reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("onboarding_status", sa.String(40), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_api_key_hash", "users", ["api_key_hash"], unique=True)
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_verification_tokens_user_id", "verification_tokens", ["user_id"])
    op.create_index("ix_verification_tokens_token_hash", "verification_tokens", ["token_hash"], unique=True)

    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_query_history_user_id_desc", "query_history", ["user_id", "id"])
