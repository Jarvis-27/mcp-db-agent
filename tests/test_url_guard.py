"""Tests for src/auth/url_guard.py — SSRF, path traversal, scheme validation."""

import socket
from unittest.mock import patch

import pytest
import src.auth.url_guard as ug_module

from src.auth.url_guard import InvalidDatabaseURL, validate_database_url, assert_url_still_safe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _dev_environment():
    """Run all url_guard tests in development mode so the SSL-mode check does not
    interfere with SSRF / IP / hostname tests that intentionally use plain URLs.
    The SSL-mode validation itself is tested explicitly in test_ssl_required_in_nondev.
    """
    with patch.object(ug_module.settings, "environment", "development"):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PUBLIC_IP = "8.8.8.8"  # Google DNS — clearly public, never in any blocked range


def _pg(host: str = "db.example.com", sslmode: str = "") -> str:
    ssl_part = f"?sslmode={sslmode}" if sslmode else ""
    return f"postgresql://user:pass@{host}/mydb{ssl_part}"


def _mock_resolve(ip: str = _PUBLIC_IP):
    """Return a mock for socket.getaddrinfo that always resolves to ip."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 5432))]


# ---------------------------------------------------------------------------
# Scheme allow-list
# ---------------------------------------------------------------------------


def test_postgresql_allowed():
    with patch("socket.getaddrinfo", return_value=_mock_resolve()):
        url = validate_database_url(_pg("db.example.com"), allow_sqlite=False)
    assert url.drivername == "postgresql"


def test_mysql_allowed():
    with patch("socket.getaddrinfo", return_value=_mock_resolve()):
        url = validate_database_url("mysql+pymysql://user:pass@db.example.com/mydb")
    assert url.drivername == "mysql+pymysql"


def test_sqlite_rejected_when_not_allowed():
    with pytest.raises(InvalidDatabaseURL, match="not allowed in this deployment"):
        validate_database_url("sqlite:///./demo.db", allow_sqlite=False)


def test_unknown_scheme_rejected():
    with pytest.raises(InvalidDatabaseURL, match="Unsupported database scheme"):
        validate_database_url("mongodb://host/db", allow_sqlite=False)


def test_file_scheme_rejected():
    with pytest.raises(InvalidDatabaseURL, match="Unsupported database scheme"):
        validate_database_url("file:///etc/passwd", allow_sqlite=False)


# ---------------------------------------------------------------------------
# Input sanity
# ---------------------------------------------------------------------------


def test_url_too_long():
    long_url = "postgresql://user:pass@" + "a" * 2040 + "/db"
    with pytest.raises(InvalidDatabaseURL, match="exceeds maximum length"):
        validate_database_url(long_url)


def test_url_with_newline():
    with pytest.raises(InvalidDatabaseURL, match="newline"):
        validate_database_url("postgresql://host/db\nEVIL")


def test_url_with_null_byte():
    with pytest.raises(InvalidDatabaseURL, match="null byte"):
        validate_database_url("postgresql://host/db\x00")


def test_url_with_semicolon():
    with pytest.raises(InvalidDatabaseURL, match="semicolon"):
        validate_database_url("postgresql://host/db;DROP TABLE users")


def test_invalid_url_format():
    with pytest.raises(InvalidDatabaseURL, match="Invalid database URL"):
        validate_database_url("not-a-url-at-all://:::broken")


# ---------------------------------------------------------------------------
# Blocked IP ranges (T1 — SSRF)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "127.0.0.2",
        "10.0.0.1",  # RFC1918
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.255.255",
        "169.254.169.254",  # AWS/GCP metadata
        "169.254.0.1",
        "0.0.0.1",
    ],
)
def test_blocked_ipv4(ip):
    with patch("socket.getaddrinfo", return_value=_mock_resolve(ip)):
        with pytest.raises(InvalidDatabaseURL, match="blocked IP"):
            validate_database_url(_pg("db.example.com"), allow_sqlite=False)


def test_public_ip_allowed():
    with patch("socket.getaddrinfo", return_value=_mock_resolve()):
        url = validate_database_url(_pg("db.example.com"))
    assert url is not None


# ---------------------------------------------------------------------------
# DNS resolution failure
# ---------------------------------------------------------------------------


def test_unresolvable_hostname():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
        with pytest.raises(InvalidDatabaseURL, match="Cannot resolve hostname"):
            validate_database_url(_pg("nonexistent.invalid"), allow_sqlite=False)


# ---------------------------------------------------------------------------
# SSL mode enforcement in non-development environments
# ---------------------------------------------------------------------------


def test_ssl_required_in_nondev():
    """PostgreSQL URLs without sslmode must be rejected outside development."""
    with patch.object(ug_module.settings, "environment", "production"):
        with patch("socket.getaddrinfo", return_value=_mock_resolve()):
            with pytest.raises(InvalidDatabaseURL, match="sslmode"):
                validate_database_url(_pg("db.example.com"), allow_sqlite=False)


def test_ssl_require_accepted_in_nondev():
    """sslmode=require satisfies the non-development SSL check."""
    with patch.object(ug_module.settings, "environment", "production"):
        with patch("socket.getaddrinfo", return_value=_mock_resolve()):
            url = validate_database_url(_pg("db.example.com", sslmode="require"))
    assert url is not None


# ---------------------------------------------------------------------------
# DNS rebinding (T9) — public at register time, private at engine-build time
# ---------------------------------------------------------------------------


def test_dns_rebinding_assert_url_still_safe():
    """assert_url_still_safe re-resolves and catches rebinding."""
    from sqlalchemy.engine import make_url

    url = make_url("postgresql://user:pass@db.example.com/mydb")
    with patch("socket.getaddrinfo", return_value=_mock_resolve("169.254.169.254")):
        with pytest.raises(InvalidDatabaseURL, match="blocked IP"):
            assert_url_still_safe(url)


# ---------------------------------------------------------------------------
# Query param stripping
# ---------------------------------------------------------------------------


def test_dangerous_params_stripped():
    raw = "postgresql://user:pass@db.example.com/mydb?sslmode=require&passfile=/etc/passwd&options=-c%20search_path%3Dattacker"
    with patch("socket.getaddrinfo", return_value=_mock_resolve()):
        url = validate_database_url(raw)
    params = dict(url.query) if url.query else {}
    assert "passfile" not in params
    assert "options" not in params
    assert "sslmode" in params  # sslmode is NOT stripped


def test_sslkey_sslcert_stripped():
    raw = "postgresql://user:pass@db.example.com/mydb?sslkey=/etc/ssl/key.pem&sslcert=/etc/ssl/cert.pem&sslmode=require"
    with patch("socket.getaddrinfo", return_value=_mock_resolve()):
        url = validate_database_url(raw)
    params = dict(url.query) if url.query else {}
    assert "sslkey" not in params
    assert "sslcert" not in params


# ---------------------------------------------------------------------------
# SQLite path validation (when allow_sqlite=True)
# ---------------------------------------------------------------------------


def test_sqlite_allowed_inside_dir(tmp_path):
    import src.auth.url_guard as ug_module

    with patch.object(ug_module.settings, "sqlite_user_db_dir", str(tmp_path)):
        with patch.object(ug_module.settings, "auth_database_url", "sqlite:///./auth.db"):
            url = validate_database_url(f"sqlite:///{tmp_path}/user_db.sqlite", allow_sqlite=True)
    assert url is not None


def test_sqlite_path_traversal_rejected(tmp_path):
    import src.auth.url_guard as ug_module

    with patch.object(ug_module.settings, "sqlite_user_db_dir", str(tmp_path)):
        with patch.object(ug_module.settings, "auth_database_url", "sqlite:///./auth.db"):
            with pytest.raises(InvalidDatabaseURL, match="Path traversal"):
                validate_database_url("sqlite:///../../etc/passwd", allow_sqlite=True)


def test_sqlite_outside_allowed_dir_rejected(tmp_path):
    import src.auth.url_guard as ug_module

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    with patch.object(ug_module.settings, "sqlite_user_db_dir", str(allowed)):
        with patch.object(ug_module.settings, "auth_database_url", "sqlite:///./auth.db"):
            with pytest.raises(InvalidDatabaseURL, match="must be inside"):
                validate_database_url(f"sqlite:///{other}/evil.db", allow_sqlite=True)


def test_sqlite_memory_rejected():

    with pytest.raises(InvalidDatabaseURL):
        validate_database_url("sqlite:///:memory:", allow_sqlite=True)


def test_sqlite_auth_db_rejected(tmp_path):
    import src.auth.url_guard as ug_module

    auth_db = tmp_path / "auth.db"
    with patch.object(ug_module.settings, "sqlite_user_db_dir", str(tmp_path)):
        with patch.object(ug_module.settings, "auth_database_url", f"sqlite:///{auth_db}"):
            with pytest.raises(InvalidDatabaseURL, match="auth database"):
                validate_database_url(f"sqlite:///{auth_db}", allow_sqlite=True)
