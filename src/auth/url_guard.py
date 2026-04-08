"""URL validation guard — prevents SSRF, path traversal, and DNS rebinding (T1, T9)."""

import ipaddress
import socket
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL

from src.config import settings


class InvalidDatabaseURL(ValueError):
    """Raised when a user-supplied database URL fails validation."""


_ALLOWED_SCHEMES = {
    "postgresql",
    "postgresql+psycopg2",
    "mysql+pymysql",
}

# Query params that can redirect the connection or read local files
_STRIP_PARAMS = {
    "options",
    "passfile",
    "service",
    "sslkey",
    "sslcert",
    "sslrootcert",
    "krbsrvname",
    "gsslib",
    "host",
}

# Private / reserved IPv4 ranges
_BLOCKED_IPV4_NETWORKS = [
    ipaddress.IPv4Network("127.0.0.0/8"),  # loopback
    ipaddress.IPv4Network("10.0.0.0/8"),  # RFC1918 private
    ipaddress.IPv4Network("172.16.0.0/12"),  # RFC1918 private
    ipaddress.IPv4Network("192.168.0.0/16"),  # RFC1918 private
    ipaddress.IPv4Network("169.254.0.0/16"),  # link-local + cloud metadata (AWS/GCP)
    ipaddress.IPv4Network("0.0.0.0/8"),  # "this" network
    ipaddress.IPv4Network("100.64.0.0/10"),  # Shared Address Space (RFC6598)
    ipaddress.IPv4Network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.IPv4Network("240.0.0.0/4"),  # reserved
    ipaddress.IPv4Network("255.255.255.255/32"),  # broadcast
]

_BLOCKED_IPV6_NETWORKS = [
    ipaddress.IPv6Network("::1/128"),  # loopback
    ipaddress.IPv6Network("fc00::/7"),  # ULA
    ipaddress.IPv6Network("fe80::/10"),  # link-local
    ipaddress.IPv6Network("::/128"),  # unspecified
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped
]


def _is_blocked_ip(addr: str) -> bool:
    """Return True if the resolved IP address is in a blocked range."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # unparseable = blocked

    if isinstance(ip, ipaddress.IPv4Address):
        for net in _BLOCKED_IPV4_NETWORKS:
            if ip in net:
                return True
        # Also check settings.extra_blocked_cidrs
        for cidr in _extra_blocked_networks():
            if isinstance(cidr, ipaddress.IPv4Network) and ip in cidr:
                return True
    else:
        for net in _BLOCKED_IPV6_NETWORKS:
            if ip in net:
                return True
        for cidr in _extra_blocked_networks():
            if isinstance(cidr, ipaddress.IPv6Network) and ip in cidr:
                return True

    return False


def _extra_blocked_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    if not settings.extra_blocked_cidrs:
        return []
    result = []
    for cidr in settings.extra_blocked_cidrs.split(","):
        cidr = cidr.strip()
        if cidr:
            try:
                result.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass
    return result


def _resolve_and_check_hostname(hostname: str) -> None:
    """Resolve hostname to ALL its A/AAAA records and reject if any is blocked."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise InvalidDatabaseURL(f"Cannot resolve hostname '{hostname}': {exc}") from exc

    resolved_ips = {info[4][0] for info in infos}
    for ip_str in resolved_ips:
        if _is_blocked_ip(ip_str):
            raise InvalidDatabaseURL(
                f"Database host '{hostname}' resolves to a blocked IP address. "
                "Private, loopback, link-local, and cloud metadata IPs are not allowed."
            )


def validate_database_url(raw: str, *, allow_sqlite: bool = False) -> URL:
    """Validate and sanitise a user-supplied database URL.

    Returns a sanitised sqlalchemy.engine.url.URL or raises InvalidDatabaseURL.

    Hard rules:
      - Length <= 2048 chars; reject newline, null byte, semicolon
      - make_url() must succeed
      - Scheme allow-list (sqlite only when allow_sqlite=True)
      - For sqlite: path must be inside settings.sqlite_user_db_dir,
            no '..' segments, not equal to AUTH_DATABASE_URL path
      - For network DBs: resolve hostname; reject any blocked IP (SSRF)
      - Strip dangerous query params
      - For postgresql in non-dev: require sslmode in {require,verify-ca,verify-full}
    """
    if not isinstance(raw, str):
        raise InvalidDatabaseURL("database_url must be a string")

    if len(raw) > 2048:
        raise InvalidDatabaseURL("database_url exceeds maximum length of 2048 characters")

    for bad_char, name in [("\n", "newline"), ("\0", "null byte"), (";", "semicolon")]:
        if bad_char in raw:
            raise InvalidDatabaseURL(f"database_url contains forbidden character: {name}")

    try:
        url = make_url(raw)
    except Exception as exc:
        raise InvalidDatabaseURL(f"Invalid database URL: {exc}") from exc

    scheme = url.drivername.lower()

    if scheme.startswith("sqlite"):
        if not allow_sqlite:
            raise InvalidDatabaseURL(
                "SQLite user databases are not allowed in this deployment. "
                "Use PostgreSQL or MySQL."
            )
        _validate_sqlite_url(url, raw)
        return url

    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidDatabaseURL(
            f"Unsupported database scheme '{scheme}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SCHEMES))} (or sqlite in dev mode)."
        )

    # Strip dangerous query params
    if url.query:
        clean_query = {k: v for k, v in url.query.items() if k.lower() not in _STRIP_PARAMS}
        url = url.set(query=clean_query)

    # Require SSL in non-development environments
    if scheme.startswith("postgresql") and settings.environment != "development":
        sslmode = (url.query or {}).get("sslmode", "")
        if sslmode not in ("require", "verify-ca", "verify-full"):
            raise InvalidDatabaseURL(
                "PostgreSQL connections require sslmode=require, verify-ca, or verify-full "
                "in non-development environments."
            )

    # Resolve hostname — rejects SSRF targets
    if url.host:
        _resolve_and_check_hostname(url.host)

    return url


def _validate_sqlite_url(url: URL, raw: str) -> None:
    """Extra safety checks for SQLite user databases."""
    # Extract the file path from the URL
    # sqlite:///./path/to/db  →  ./path/to/db
    # sqlite:////abs/path     →  /abs/path
    database = url.database or ""

    # Reject memory databases and special paths
    if database in ("", ":memory:"):
        raise InvalidDatabaseURL("SQLite in-memory databases are not allowed for user databases.")

    path = Path(database).resolve()
    allowed_dir = Path(settings.sqlite_user_db_dir).resolve()

    # Prevent path traversal
    try:
        path.relative_to(allowed_dir)
    except ValueError:
        raise InvalidDatabaseURL(
            f"SQLite database path must be inside '{settings.sqlite_user_db_dir}'. "
            "Path traversal is not allowed."
        )

    # Don't allow accessing the auth DB or query log
    auth_url = make_url(settings.auth_database_url)
    if auth_url.drivername.startswith("sqlite"):
        auth_path = Path(auth_url.database or "").resolve()
        if path == auth_path:
            raise InvalidDatabaseURL("Cannot use the auth database as a user database.")

    # Reject '..' segments in the raw string as an extra check
    if ".." in raw:
        raise InvalidDatabaseURL("Path traversal sequences ('..') are not allowed.")


def assert_url_still_safe(url: URL) -> None:
    """Re-resolve hostname and re-check IP class.

    Called from PipelineFactory.get() immediately before create_engine()
    as defense-in-depth against DNS rebinding (T9).
    """
    if url.host:
        _resolve_and_check_hostname(url.host)
