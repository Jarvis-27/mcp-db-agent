"""Integration tests for Alembic migration 0007.

These tests run the actual migration module against a real in-memory SQLite
database seeded with a hand-built pre-0007 schema.  Every data-transformation
path (tenants→users, owner_sessions→user_sessions, FK rewrites in
verification_tokens / api_keys / query_history) is genuinely exercised rather
than mocked.

Strategy
--------
1. Build the legacy four-table schema with raw DDL.
2. Seed realistic data for each foreign-key chain.
3. Swap the migration module's `op` with a real ``alembic.operations.Operations``
   object backed by the live connection (same monkeypatch hook the unit tests
   use, but with a real connection instead of MagicMock).
4. Call ``migration.upgrade()`` and commit.
5. Assert the post-migration state directly via SQL.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0007_single_user_schema.py"
)

# ---------------------------------------------------------------------------
# Fixed identifiers used across all seed helpers
# ---------------------------------------------------------------------------

NOW = "2024-01-15T10:00:00"
FUTURE = "2025-06-01T00:00:00"

TENANT_ID = "tid-aaa-001"
MEMBERSHIP_ID = "mid-aaa-001"
DB_ID = "dbid-aaa-001"
SESSION_ID = "sessid-aaa-001"
TOKEN_ID = "tokid-aaa-001"
KEY_ID = "keyid-aaa-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_migration():
    """Import the migration module into a fresh, independent module object."""
    spec = spec_from_file_location("migration_0007_int", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_legacy_schema(conn) -> None:
    """Recreate the pre-0007 four-table schema the migration expects to find."""
    conn.execute(
        text("""
        CREATE TABLE tenants (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending_email_verification',
            account_status TEXT NOT NULL DEFAULT 'active',
            billing_status TEXT NOT NULL DEFAULT 'free',
            plan_code TEXT NOT NULL DEFAULT 'free',
            daily_query_count INTEGER NOT NULL DEFAULT 0,
            daily_quota_reset_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            suspended_at TEXT,
            closed_at TEXT
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE tenant_memberships (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            email TEXT NOT NULL,
            email_verified_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE tenant_databases (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT 'primary',
            database_url_enc TEXT,
            validation_status TEXT,
            last_validation_at TEXT,
            last_validation_error TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE owner_sessions (
            id TEXT PRIMARY KEY,
            tenant_membership_id TEXT NOT NULL,
            session_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_membership_id) REFERENCES tenant_memberships(id)
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE verification_tokens (
            id TEXT PRIMARY KEY,
            membership_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            purpose TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY (membership_id) REFERENCES tenant_memberships(id)
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE api_keys (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            created_by_membership_id TEXT,
            name TEXT NOT NULL DEFAULT 'default',
            prefix TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'mcp_read',
            last_used_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    )
    conn.execute(
        text("""
        CREATE TABLE query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            question TEXT NOT NULL,
            sql TEXT NOT NULL,
            success INTEGER NOT NULL,
            row_count INTEGER,
            attempts INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            error TEXT,
            plan_code TEXT,
            daily_count INTEGER,
            daily_limit INTEGER,
            warning_level TEXT
        )
    """)
    )
    # Indices the migration drops by name — must exist for batch_alter_table.
    conn.execute(
        text(
            "CREATE INDEX ix_verification_tokens_membership_id ON verification_tokens(membership_id)"
        )
    )
    conn.execute(text("CREATE INDEX ix_api_keys_tenant_id ON api_keys(tenant_id)"))
    conn.execute(
        text("CREATE INDEX ix_query_history_tenant_id_desc ON query_history(tenant_id, id)")
    )
    conn.commit()


def _seed_full_tenant(conn) -> None:
    """Seed one complete tenant: owner membership, active DB, session, token, key, history row."""
    conn.execute(
        text(
            "INSERT INTO tenants VALUES"
            " (:id, 'setup_complete', 'active', 'free', 'free', 42, :fut, :now, :now, NULL, NULL)"
        ),
        {"id": TENANT_ID, "fut": FUTURE, "now": NOW},
    )

    conn.execute(
        text(
            "INSERT INTO tenant_memberships VALUES (:id, :tid, 'owner', 'owner@example.com', :now)"
        ),
        {"id": MEMBERSHIP_ID, "tid": TENANT_ID, "now": NOW},
    )

    conn.execute(
        text(
            "INSERT INTO tenant_databases VALUES"
            " (:id, :tid, 'primary', 'enc_url_xyz', 'validated', :now, NULL, 1)"
        ),
        {"id": DB_ID, "tid": TENANT_ID, "now": NOW},
    )

    conn.execute(
        text("INSERT INTO owner_sessions VALUES (:id, :mid, 'hash_abc', :fut, NULL, NULL, :now)"),
        {"id": SESSION_ID, "mid": MEMBERSHIP_ID, "fut": FUTURE, "now": NOW},
    )

    conn.execute(
        text(
            "INSERT INTO verification_tokens VALUES"
            " (:id, :mid, 'tok_hash_xyz', 'email_verification', :fut, NULL)"
        ),
        {"id": TOKEN_ID, "mid": MEMBERSHIP_ID, "fut": FUTURE},
    )

    conn.execute(
        text(
            "INSERT INTO api_keys VALUES"
            " (:id, :tid, :mid, 'default', 'mdbk_pre', 'key_hash_xyz', 'mcp_read', NULL, NULL, :now)"
        ),
        {"id": KEY_ID, "tid": TENANT_ID, "mid": MEMBERSHIP_ID, "now": NOW},
    )

    conn.execute(
        text(
            "INSERT INTO query_history"
            " (timestamp, tenant_id, question, sql, success, row_count, attempts, duration_ms)"
            " VALUES (:now, :tid, 'How many rows?', 'SELECT COUNT(*) FROM foo', 1, 1, 1, 42)"
        ),
        {"now": NOW, "tid": TENANT_ID},
    )

    conn.commit()


def _run_migration(conn, monkeypatch) -> None:
    """Patch the migration module's `op` with real alembic Operations and run upgrade()."""
    migration = _load_migration()
    ctx = MigrationContext.configure(conn)
    real_op = Operations(ctx)
    monkeypatch.setattr(migration, "op", real_op)
    migration.upgrade()
    conn.commit()


@pytest.fixture
def migrated(monkeypatch):
    """Yield an open connection to a fully migrated SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    conn = engine.connect()
    try:
        _build_legacy_schema(conn)
        _seed_full_tenant(conn)
        _run_migration(conn, monkeypatch)
        yield conn
    finally:
        conn.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Happy-path: all five data-migration paths
# ---------------------------------------------------------------------------


def test_tenant_collapses_into_users_row(migrated):
    """The users row must inherit identity, onboarding state, and billing from the tenant."""
    rows = migrated.execute(text("SELECT * FROM users")).mappings().all()
    assert len(rows) == 1
    u = dict(rows[0])

    assert u["id"] == TENANT_ID
    assert u["email"] == "owner@example.com"
    assert u["email_verified_at"] == NOW
    assert u["onboarding_status"] == "setup_complete"
    assert u["account_status"] == "active"
    assert u["plan_code"] == "free"
    assert int(u["daily_query_count"]) == 42


def test_active_database_inlined_into_users_row(migrated):
    """The active tenant_database row must be inlined onto the users row."""
    u = dict(migrated.execute(text("SELECT * FROM users")).mappings().one())

    assert u["db_url_enc"] == "enc_url_xyz"
    assert u["db_name"] == "primary"
    assert u["db_validation_status"] == "validated"
    assert u["db_last_validation_at"] == NOW
    assert u["db_last_validation_error"] is None


def test_owner_sessions_migrate_to_user_sessions(migrated):
    """owner_sessions rows must appear in user_sessions keyed by tenant_id → user_id."""
    rows = migrated.execute(text("SELECT * FROM user_sessions")).mappings().all()
    assert len(rows) == 1
    s = dict(rows[0])

    assert s["id"] == SESSION_ID
    assert s["user_id"] == TENANT_ID
    assert s["session_hash"] == "hash_abc"
    assert s["expires_at"] == FUTURE
    assert s["revoked_at"] is None


def test_verification_tokens_rewritten_with_user_id(migrated):
    """verification_tokens.membership_id must be replaced by user_id → tenant_id."""
    rows = migrated.execute(text("SELECT * FROM verification_tokens")).mappings().all()
    assert len(rows) == 1
    t = dict(rows[0])

    assert t["id"] == TOKEN_ID
    assert t["user_id"] == TENANT_ID
    assert "membership_id" not in t
    assert t["token_hash"] == "tok_hash_xyz"


def test_api_keys_rewritten_with_user_id(migrated):
    """api_keys.tenant_id → user_id; created_by_membership_id column removed."""
    rows = migrated.execute(text("SELECT * FROM api_keys")).mappings().all()
    assert len(rows) == 1
    k = dict(rows[0])

    assert k["id"] == KEY_ID
    assert k["user_id"] == TENANT_ID
    assert k["scope"] == "mcp_read"
    assert "tenant_id" not in k
    assert "created_by_membership_id" not in k


def test_query_history_tenant_id_renamed_to_user_id(migrated):
    """query_history.tenant_id must be renamed to user_id; data preserved."""
    rows = migrated.execute(text("SELECT * FROM query_history")).mappings().all()
    assert len(rows) == 1
    h = dict(rows[0])

    assert h["user_id"] == TENANT_ID
    assert h["question"] == "How many rows?"
    assert int(h["duration_ms"]) == 42
    assert "tenant_id" not in h


def test_legacy_tables_are_dropped(migrated):
    """All four legacy tables must be absent after the migration."""
    inspector = inspect(migrated.engine)
    remaining = set(inspector.get_table_names())
    for dropped in ("tenants", "tenant_memberships", "tenant_databases", "owner_sessions"):
        assert dropped not in remaining, f"Legacy table {dropped!r} was not dropped"


# ---------------------------------------------------------------------------
# Edge-case: tenant with no active database
# ---------------------------------------------------------------------------


def test_tenant_without_active_db_gets_null_db_fields(monkeypatch):
    """A tenant that never connected a database should produce a users row with null db cols."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        _build_legacy_schema(conn)
        # Tenant with no tenant_databases row
        conn.execute(
            text(
                "INSERT INTO tenants VALUES"
                " ('tid-no-db', 'pending_db_connection', 'active', 'free', 'free',"
                "  0, :fut, :now, :now, NULL, NULL)"
            ),
            {"fut": FUTURE, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO tenant_memberships VALUES"
                " ('mid-no-db', 'tid-no-db', 'owner', 'nodb@example.com', NULL)"
            )
        )
        conn.commit()

        _run_migration(conn, monkeypatch)

        u = dict(conn.execute(text("SELECT * FROM users WHERE id = 'tid-no-db'")).mappings().one())
        assert u["email"] == "nodb@example.com"
        assert u["db_url_enc"] is None
        assert u["db_name"] is None
        assert u["db_validation_status"] is None


# ---------------------------------------------------------------------------
# Edge-case: pre-flight guard fires on duplicate owner emails
# ---------------------------------------------------------------------------


def test_preflight_rejects_duplicate_owner_emails(monkeypatch):
    """upgrade() must abort before touching DDL when two owners share an email."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        _build_legacy_schema(conn)
        for suffix in ("A", "B"):
            tid = f"tid-dup-{suffix}"
            mid = f"mid-dup-{suffix}"
            conn.execute(
                text(
                    "INSERT INTO tenants VALUES"
                    " (:id, 'setup_complete', 'active', 'free', 'free', 0, :fut, :now, :now, NULL, NULL)"
                ),
                {"id": tid, "fut": FUTURE, "now": NOW},
            )
            conn.execute(
                text(
                    "INSERT INTO tenant_memberships VALUES (:id, :tid, 'owner', 'same@example.com', NULL)"
                ),
                {"id": mid, "tid": tid},
            )
        conn.commit()

        migration = _load_migration()
        ctx = MigrationContext.configure(conn)
        real_op = Operations(ctx)
        monkeypatch.setattr(migration, "op", real_op)

        with pytest.raises(RuntimeError, match="duplicate email"):
            migration.upgrade()

        # DDL must not have started — users table should not exist
        inspector = inspect(engine)
        assert "users" not in inspector.get_table_names()
