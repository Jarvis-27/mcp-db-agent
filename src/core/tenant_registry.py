"""Tenant registry — maps API keys to database connection URLs.

Backed by a dedicated SQLite database so tenant configuration persists
across server restarts without touching any user database.
"""

import datetime
import secrets
from pathlib import Path

from sqlalchemy import Column, DateTime, String, Text, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

_DEFAULT_DB_PATH = str(Path(__file__).parent.parent.parent / "tenants.db")


class _Base(DeclarativeBase):
    pass


class _Tenant(_Base):
    __tablename__ = "tenants"

    api_key = Column(String(64), primary_key=True)
    name = Column(Text, nullable=False)
    database_url = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)


class TenantRegistry:
    """Manages tenant API keys and their associated database URLs."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._engine = create_engine(f"sqlite:///{db_path}")
        _Base.metadata.create_all(self._engine)

    def create_tenant(self, name: str, database_url: str) -> str:
        """Register a new tenant and return a generated API key."""
        api_key = f"mdb_{secrets.token_hex(24)}"
        with Session(self._engine) as session:
            tenant = _Tenant(
                api_key=api_key,
                name=name,
                database_url=database_url,
                is_active=True,
                created_at=datetime.datetime.utcnow(),
            )
            session.add(tenant)
            session.commit()
        return api_key

    def resolve(self, api_key: str) -> str | None:
        """Return the database_url for an active API key, or None."""
        with Session(self._engine) as session:
            tenant = (
                session.query(_Tenant)
                .filter(_Tenant.api_key == api_key, _Tenant.is_active.is_(True))
                .first()
            )
            return tenant.database_url if tenant else None

    def deactivate(self, api_key: str) -> bool:
        """Deactivate a tenant. Returns True if found and deactivated."""
        with Session(self._engine) as session:
            tenant = session.query(_Tenant).filter(_Tenant.api_key == api_key).first()
            if not tenant:
                return False
            tenant.is_active = False
            session.commit()
            return True

    def list_tenants(self) -> list[dict[str, object]]:
        """Return all tenants (active and inactive)."""
        with Session(self._engine) as session:
            rows = session.query(_Tenant).order_by(_Tenant.created_at.desc()).all()
            return [
                {
                    "api_key": r.api_key[:12] + "...",  # Mask for safety
                    "name": r.name,
                    "database_url": _mask_url(r.database_url),
                    "is_active": r.is_active,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]


def _mask_url(url: str) -> str:
    """Mask password in database URLs for display."""
    # postgresql://user:secret@host/db → postgresql://user:***@host/db
    import re

    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)
