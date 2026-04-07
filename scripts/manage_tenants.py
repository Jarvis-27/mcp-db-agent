#!/usr/bin/env python3
"""CLI for managing tenants in the MCP Database Agent.

Usage:
    # Add a new tenant — prints the generated API key
    uv run scripts/manage_tenants.py add "Acme Corp" "postgresql://user:pass@host/acme_db"

    # List all tenants (API keys are masked)
    uv run scripts/manage_tenants.py list

    # Deactivate a tenant by API key
    uv run scripts/manage_tenants.py deactivate mdb_abc123...

    # Test a tenant's database connection
    uv run scripts/manage_tenants.py test mdb_abc123...
"""

import argparse
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.core.tenant_registry import TenantRegistry


def cmd_add(args: argparse.Namespace) -> None:
    registry = TenantRegistry()
    api_key = registry.create_tenant(args.name, args.database_url)
    print("\nTenant created successfully!")
    print(f"  Name:     {args.name}")
    print(f"  API Key:  {api_key}")
    print("\nGive this API key to the client. They will pass it as the")
    print("'api_key' parameter when calling any tool.\n")


def cmd_list(args: argparse.Namespace) -> None:
    registry = TenantRegistry()
    tenants = registry.list_tenants()
    if not tenants:
        print("No tenants registered.")
        return
    print(f"\n{'Name':<25} {'API Key (masked)':<20} {'Database':<40} {'Active':<8} {'Created'}")
    print("-" * 120)
    for t in tenants:
        print(
            f"{t['name']:<25} {t['api_key']:<20} {t['database_url']:<40} {str(t['is_active']):<8} {t['created_at']}"
        )
    print()


def cmd_deactivate(args: argparse.Namespace) -> None:
    registry = TenantRegistry()
    if registry.deactivate(args.api_key):
        print(f"Tenant deactivated: {args.api_key[:12]}...")
    else:
        print(f"No tenant found with key: {args.api_key[:12]}...")
        sys.exit(1)


def cmd_test(args: argparse.Namespace) -> None:
    from sqlalchemy import create_engine, text

    registry = TenantRegistry()
    db_url = registry.resolve(args.api_key)
    if not db_url:
        print(f"Invalid or inactive API key: {args.api_key[:12]}...")
        sys.exit(1)

    print("Testing connection...")
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Connection successful!")
        engine.dispose()
    except Exception as exc:
        print(f"Connection failed: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage MCP Database Agent tenants")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Register a new tenant")
    add_p.add_argument("name", help="Tenant display name (e.g. 'Acme Corp')")
    add_p.add_argument("database_url", help="Database connection URL (e.g. postgresql://...)")
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", help="List all tenants")
    list_p.set_defaults(func=cmd_list)

    deact_p = sub.add_parser("deactivate", help="Deactivate a tenant")
    deact_p.add_argument("api_key", help="Full API key of the tenant to deactivate")
    deact_p.set_defaults(func=cmd_deactivate)

    test_p = sub.add_parser("test", help="Test a tenant's database connection")
    test_p.add_argument("api_key", help="Full API key of the tenant to test")
    test_p.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
