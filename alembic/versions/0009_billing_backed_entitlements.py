"""Add Stripe billing linkage and webhook idempotency.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("stripe_customer_id", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("stripe_subscription_id", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("stripe_price_id", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column("billing_current_period_end", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("billing_last_event_id", sa.String(255), nullable=True))
        batch_op.create_index(
            "ix_users_stripe_customer_id",
            ["stripe_customer_id"],
            unique=True,
        )
        batch_op.create_index(
            "ix_users_stripe_subscription_id",
            ["stripe_subscription_id"],
        )

    op.create_table(
        "billing_webhook_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_billing_webhook_events_user_id", "billing_webhook_events", ["user_id"])
    op.create_index(
        "ix_billing_webhook_events_stripe_customer_id",
        "billing_webhook_events",
        ["stripe_customer_id"],
    )
    op.create_index(
        "ix_billing_webhook_events_stripe_subscription_id",
        "billing_webhook_events",
        ["stripe_subscription_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_webhook_events_stripe_subscription_id",
        table_name="billing_webhook_events",
    )
    op.drop_index(
        "ix_billing_webhook_events_stripe_customer_id",
        table_name="billing_webhook_events",
    )
    op.drop_index("ix_billing_webhook_events_user_id", table_name="billing_webhook_events")
    op.drop_table("billing_webhook_events")

    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.drop_index("ix_users_stripe_subscription_id")
        batch_op.drop_index("ix_users_stripe_customer_id")
        batch_op.drop_column("billing_last_event_id")
        batch_op.drop_column("billing_current_period_end")
        batch_op.drop_column("stripe_price_id")
        batch_op.drop_column("stripe_subscription_id")
        batch_op.drop_column("stripe_customer_id")
