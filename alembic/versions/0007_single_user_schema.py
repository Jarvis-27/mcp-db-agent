"""Single-user account schema — collapse tenant+membership+database into users.

Replaces:
  - tenants (multi-tenant)
  - tenant_memberships
  - tenant_databases
  - owner_sessions

With:
  - users (single-account: identity + onboarding + billing + db inlined)
  - user_sessions

Also renames FKs in:
  - verification_tokens.membership_id → user_id (FK → users.id)
  - api_keys.tenant_id → user_id (FK → users.id), drops created_by_membership_id
  - query_history.tenant_id → user_id (no FK, plain text column)

Pre-flight validation (fails loudly, do NOT proceed if any check fires):
  - Each tenant must have exactly one owner membership
  - No non-owner memberships allowed
  - Owner emails must remain globally unique after collapse

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 0. Pre-flight validation
    # ------------------------------------------------------------------
    # Check for tenants with zero owners
    zero_owner = conn.execute(
        text(
            """
            SELECT t.id FROM tenants t
            LEFT JOIN tenant_memberships m
                ON m.tenant_id = t.id AND m.role = 'owner'
            WHERE m.id IS NULL
            """
        )
    ).fetchall()
    if zero_owner:
        ids = [r[0] for r in zero_owner]
        raise RuntimeError(
            f"Migration aborted: {len(ids)} tenant(s) have no owner membership — "
            f"resolve manually before running this migration: {ids}"
        )

    # Check for tenants with more than one owner
    multi_owner = conn.execute(
        text(
            """
            SELECT tenant_id, COUNT(*) as cnt
            FROM tenant_memberships
            WHERE role = 'owner'
            GROUP BY tenant_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if multi_owner:
        ids = [r[0] for r in multi_owner]
        raise RuntimeError(
            f"Migration aborted: {len(ids)} tenant(s) have multiple owner memberships — "
            f"resolve manually before running this migration: {ids}"
        )

    # Check for non-owner memberships
    non_owner = conn.execute(
        text("SELECT id FROM tenant_memberships WHERE role != 'owner'")
    ).fetchall()
    if non_owner:
        ids = [r[0] for r in non_owner]
        raise RuntimeError(
            f"Migration aborted: {len(ids)} non-owner membership(s) found — "
            f"remove them before running this migration: {ids}"
        )

    # Check for duplicate owner emails. The single-user schema enforces a
    # globally unique users.email index, so any collision must be resolved
    # before the cutover starts rather than failing during bulk insert.
    duplicate_owner_emails = conn.execute(
        text(
            """
            SELECT m.email
            FROM tenant_memberships m
            WHERE m.role = 'owner'
            GROUP BY m.email
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_owner_emails:
        emails = [r[0] for r in duplicate_owner_emails]
        raise RuntimeError(
            "Migration aborted: owner emails must be globally unique before "
            f"cutover; duplicate email(s) found: {emails}"
        )

    # ------------------------------------------------------------------
    # 1. Create users table
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "onboarding_status",
            sa.String(40),
            nullable=False,
            server_default="pending_email_verification",
        ),
        sa.Column(
            "account_status",
            sa.String(40),
            nullable=False,
            server_default="active",
        ),
        sa.Column("billing_status", sa.String(40), nullable=False, server_default="free"),
        sa.Column("plan_code", sa.String(40), nullable=False, server_default="free"),
        sa.Column("daily_query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_quota_reset_at", sa.DateTime(timezone=True), nullable=False),
        # Inlined database
        sa.Column("db_url_enc", sa.Text(), nullable=True),
        sa.Column("db_name", sa.String(100), nullable=True),
        sa.Column("db_validation_status", sa.String(40), nullable=True),
        sa.Column("db_last_validation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("db_last_validation_error", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_onboarding_status", "users", ["onboarding_status"])
    op.create_index("ix_users_account_status", "users", ["account_status"])

    # ------------------------------------------------------------------
    # 2. Migrate data: tenants + memberships + databases → users
    # ------------------------------------------------------------------
    conn.execute(
        text(
            """
            INSERT INTO users (
                id, email, email_verified_at,
                onboarding_status, account_status,
                billing_status, plan_code,
                daily_query_count, daily_quota_reset_at,
                db_url_enc, db_name, db_validation_status,
                db_last_validation_at, db_last_validation_error,
                created_at, updated_at, suspended_at, closed_at
            )
            SELECT
                t.id,
                m.email,
                m.email_verified_at,
                t.status,
                t.account_status,
                t.billing_status,
                t.plan_code,
                t.daily_query_count,
                t.daily_quota_reset_at,
                td.database_url_enc,
                td.name,
                td.validation_status,
                td.last_validation_at,
                td.last_validation_error,
                t.created_at,
                t.updated_at,
                t.suspended_at,
                t.closed_at
            FROM tenants t
            JOIN tenant_memberships m
                ON m.tenant_id = t.id AND m.role = 'owner'
            LEFT JOIN tenant_databases td
                ON td.tenant_id = t.id AND td.is_active IS TRUE
            """
        )
    )
    # ------------------------------------------------------------------
    # 3. Create user_sessions table
    # ------------------------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_session_hash", "user_sessions", ["session_hash"], unique=True)

    # ------------------------------------------------------------------
    # 4. Migrate owner_sessions → user_sessions
    #    owner_sessions.tenant_membership_id → membership → tenant_id = user_id
    # ------------------------------------------------------------------
    conn.execute(
        text(
            """
            INSERT INTO user_sessions (
                id, user_id, session_hash,
                expires_at, last_used_at, revoked_at, created_at
            )
            SELECT
                os.id,
                m.tenant_id,
                os.session_hash,
                os.expires_at,
                os.last_used_at,
                os.revoked_at,
                os.created_at
            FROM owner_sessions os
            JOIN tenant_memberships m
                ON m.id = os.tenant_membership_id
            """
        )
    )
    # ------------------------------------------------------------------
    # 5. Rebuild verification_tokens with user_id FK
    #    SQLite does not support DROP/ADD COLUMN with FK changes,
    #    so we use batch mode (rename → recreate → copy → drop old).
    # ------------------------------------------------------------------
    with op.batch_alter_table("verification_tokens", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))

    # Populate user_id from membership → tenant_id
    conn.execute(
        text(
            """
            UPDATE verification_tokens
            SET user_id = (
                SELECT m.tenant_id
                FROM tenant_memberships m
                WHERE m.id = verification_tokens.membership_id
            )
            WHERE user_id IS NULL
            """
        )
    )
    # Drop membership_id column and make user_id NOT NULL + FK
    with op.batch_alter_table("verification_tokens", recreate="always") as batch_op:
        batch_op.drop_index("ix_verification_tokens_membership_id")
        batch_op.drop_column("membership_id")
        batch_op.alter_column("user_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_verification_tokens_user_id",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_verification_tokens_user_id", ["user_id"])

    # ------------------------------------------------------------------
    # 6. Rebuild api_keys with user_id FK, drop created_by_membership_id
    # ------------------------------------------------------------------
    with op.batch_alter_table("api_keys", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))

    conn.execute(
        text("UPDATE api_keys SET user_id = tenant_id WHERE user_id IS NULL")
    )
    with op.batch_alter_table("api_keys", recreate="always") as batch_op:
        batch_op.drop_index("ix_api_keys_tenant_id")
        batch_op.drop_column("tenant_id")
        batch_op.drop_column("created_by_membership_id")
        batch_op.alter_column("user_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_api_keys_user_id",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_api_keys_user_id", ["user_id"])

    # ------------------------------------------------------------------
    # 7. Rename query_history.tenant_id → user_id
    # The index on the renamed column is created outside the batch context
    # because alembic's batch mode cannot resolve the new column name when
    # a create_index and an alter_column rename happen in the same batch block.
    # ------------------------------------------------------------------
    with op.batch_alter_table("query_history", recreate="always") as batch_op:
        batch_op.alter_column("tenant_id", new_column_name="user_id")
        batch_op.drop_index("ix_query_history_tenant_id_desc")
    op.create_index("ix_query_history_user_id_desc", "query_history", ["user_id", "id"])

    # ------------------------------------------------------------------
    # 8. Drop old tables (order matters for FK constraints)
    # ------------------------------------------------------------------
    op.drop_table("owner_sessions")
    op.drop_table("tenant_databases")
    op.drop_table("tenant_memberships")
    op.drop_table("tenants")


def downgrade() -> None:
    # A full downgrade is complex and unlikely to be needed in practice.
    # This stub raises to prevent accidental rollback.
    raise NotImplementedError(
        "Downgrade from 0007 is not supported. "
        "Restore from a backup taken before the migration."
    )
