"""Phase 1: split onboarding status and account status into distinct columns.

Before this migration, tenants.status held both onboarding progress states
(pending_email_verification, pending_db_connection, pending_review) AND account
lifecycle states (active, suspended, closed) in a single overloaded column.

After this migration:
- tenants.status        — onboarding progress only:
                          pending_email_verification | pending_db_connection |
                          setup_complete | pending_review
- tenants.account_status — account health:
                          active | restricted | suspended | closed
- tenants.billing_status — default changed from 'not_started' to 'free'
- tenants.plan_code      — default changed from 'new_trial' to 'free'

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-11 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add account_status column (default active for all existing rows).
    op.add_column(
        "tenants",
        sa.Column(
            "account_status",
            sa.String(40),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index("ix_tenants_account_status", "tenants", ["account_status"])

    conn = op.get_bind()

    # 2. Populate account_status from the legacy status column.
    conn.execute(
        sa.text(
            """
            UPDATE tenants
            SET account_status = CASE
                WHEN status = 'suspended' THEN 'suspended'
                WHEN status = 'closed'    THEN 'closed'
                WHEN status = 'pending_review' THEN 'restricted'
                ELSE 'active'
            END
            """
        )
    )

    # 3. Migrate tenants.status to pure onboarding states.
    #    Rows that were 'active', 'suspended', or 'closed' have completed setup.
    conn.execute(
        sa.text(
            """
            UPDATE tenants
            SET status = 'setup_complete'
            WHERE status IN ('active', 'suspended', 'closed')
            """
        )
    )

    # 4. Update billing_status and plan_code defaults.
    conn.execute(
        sa.text("UPDATE tenants SET billing_status = 'free' WHERE billing_status = 'not_started'")
    )
    conn.execute(sa.text("UPDATE tenants SET plan_code = 'free' WHERE plan_code = 'new_trial'"))


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse billing/plan defaults.
    conn.execute(
        sa.text("UPDATE tenants SET billing_status = 'not_started' WHERE billing_status = 'free'")
    )
    conn.execute(sa.text("UPDATE tenants SET plan_code = 'new_trial' WHERE plan_code = 'free'"))

    # Restore the overloaded status column from account_status.
    conn.execute(
        sa.text(
            """
            UPDATE tenants
            SET status = CASE
                WHEN account_status = 'suspended' THEN 'suspended'
                WHEN account_status = 'closed'    THEN 'closed'
                WHEN account_status = 'restricted' THEN 'pending_review'
                ELSE CASE
                    WHEN status = 'setup_complete' THEN 'active'
                    ELSE status
                END
            END
            """
        )
    )

    op.drop_index("ix_tenants_account_status", table_name="tenants")
    op.drop_column("tenants", "account_status")
