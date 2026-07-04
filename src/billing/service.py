"""Billing orchestration for Stripe-backed plan transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from src.auth.onboarding import (
    ACCOUNT_ACTIVE,
    BILLING_ACTIVE_PAID,
    BILLING_CANCELED,
    BILLING_FREE,
    BILLING_PAST_DUE,
    BILLING_TRIALING,
    SETUP_COMPLETE,
)
from src.auth.user_store import StateTransitionError, UserStore
from src.config import Settings
from src.entitlements.service import EntitlementService

from .stripe_client import StripeCheckoutSession, StripeClient, StripePortalSession

log = logging.getLogger(__name__)


class BillingConfigurationError(RuntimeError):
    """Raised when billing endpoints are called without complete Stripe settings."""


@dataclass(frozen=True)
class BillingSummary:
    user_id: str
    plan_code: str
    plan_display_name: str
    billing_status: str
    daily_limit: int
    daily_used: int
    daily_remaining: int
    checkout_available: bool
    portal_available: bool
    stripe_customer_configured: bool
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    billing_current_period_end: datetime | None


@dataclass(frozen=True)
class BillingEventResult:
    event_id: str
    event_type: str
    processed: bool
    duplicate: bool
    user_id: str | None = None
    billing_status: str | None = None
    plan_code: str | None = None


@dataclass(frozen=True)
class BillingConfirmResult:
    """Outcome of a synchronous post-redirect checkout-session confirmation.

    Returned by :meth:`BillingService.confirm_checkout_session`, which bridges
    the brief window between Stripe's redirect to the success URL and the
    eventual `checkout.session.completed` webhook. The webhook remains the
    source of truth for ongoing subscription lifecycle events.
    """

    summary: BillingSummary
    processed: bool
    already_pro: bool
    not_paid: bool


class BillingService:
    """Coordinates app billing state with Stripe-confirmed events."""

    def __init__(
        self,
        *,
        user_store: UserStore,
        stripe_client: StripeClient,
        settings: Settings,
    ) -> None:
        self._user_store = user_store
        self._stripe_client = stripe_client
        self._settings = settings
        self._entitlements = EntitlementService()

    def build_summary(self, user_id: str) -> BillingSummary:
        user = self._user_store.get_user_row(user_id)
        if user is None:
            raise LookupError("User not found")

        snapshot = self._user_store.get_effective_quota_snapshot(user_id)
        if snapshot is None:
            raise LookupError("User not found")
        plan_code = snapshot.plan_code
        plan = self._entitlements.get_plan(plan_code)
        daily_used = snapshot.daily_count
        stripe_customer_id = (
            str(user.stripe_customer_id) if user.stripe_customer_id is not None else None
        )
        billing_configured = self._settings.stripe_billing_is_configured()
        checkout_eligible = (
            str(user.account_status) == ACCOUNT_ACTIVE
            and str(user.onboarding_status) == SETUP_COMPLETE
        )
        return BillingSummary(
            user_id=user_id,
            plan_code=plan.code,
            plan_display_name=plan.display_name,
            billing_status=str(user.billing_status),
            daily_limit=plan.ask_database_per_day,
            daily_used=daily_used,
            daily_remaining=max(0, plan.ask_database_per_day - daily_used),
            checkout_available=billing_configured and checkout_eligible and plan.code != "pro",
            portal_available=billing_configured and stripe_customer_id is not None,
            stripe_customer_configured=stripe_customer_id is not None,
            stripe_subscription_id=(
                str(user.stripe_subscription_id)
                if user.stripe_subscription_id is not None
                else None
            ),
            stripe_price_id=str(user.stripe_price_id) if user.stripe_price_id is not None else None,
            billing_current_period_end=(
                _ensure_utc(cast(datetime, user.billing_current_period_end))
                if user.billing_current_period_end is not None
                else None
            ),
        )

    async def create_checkout_session(self, user_id: str) -> StripeCheckoutSession:
        self._require_billing_configured()
        user = self._user_store.get_user_row(user_id)
        if user is None:
            raise LookupError("User not found")
        if (
            str(user.account_status) != ACCOUNT_ACTIVE
            or str(user.onboarding_status) != SETUP_COMPLETE
        ):
            raise StateTransitionError("Complete account setup before upgrading.")

        # Block a second subscription for users who already have an active one.
        # Without this, a user could POST directly to the checkout endpoint
        # (bypassing the UI's advisory `checkout_available` flag) and end up
        # paying for two live Stripe subscriptions, only one of which the app
        # tracks.
        if str(user.plan_code) == "pro" or str(user.billing_status) in {
            BILLING_ACTIVE_PAID,
            BILLING_TRIALING,
        }:
            raise StateTransitionError(
                "You already have an active Pro subscription. "
                "Manage it from the billing portal instead."
            )

        stripe_customer_id = (
            str(user.stripe_customer_id) if user.stripe_customer_id is not None else None
        )
        if stripe_customer_id is None:
            stripe_customer_id = await self._stripe_client.create_customer(
                email=str(user.email),
                user_id=user_id,
            )
            self._user_store.set_stripe_customer_id(user_id, stripe_customer_id)

        return await self._stripe_client.create_checkout_session(
            customer_id=stripe_customer_id,
            user_id=user_id,
            price_id=self._settings.stripe_pro_price_id,
            success_url=self._settings.stripe_checkout_success_url_effective(),
            cancel_url=self._settings.stripe_checkout_cancel_url_effective(),
        )

    async def create_portal_session(self, user_id: str) -> StripePortalSession:
        self._require_billing_configured()
        user = self._user_store.get_user_row(user_id)
        if user is None:
            raise LookupError("User not found")
        if user.stripe_customer_id is None:
            raise StateTransitionError("No Stripe customer exists for this account yet.")

        return await self._stripe_client.create_portal_session(
            customer_id=str(user.stripe_customer_id),
            return_url=self._settings.stripe_customer_portal_return_url_effective(),
        )

    async def confirm_checkout_session(self, user_id: str, session_id: str) -> BillingConfirmResult:
        """Synchronously apply a completed checkout session to the user.

        Bridges the post-redirect race when Stripe's `checkout.session.completed`
        webhook has not yet arrived (or, in local dev, isn't being forwarded).
        Safe to call alongside the webhook handler: both write through
        :meth:`UserStore.apply_billing_update`, which is state-overwriting, and
        idempotency rows live under separate `event_id` namespaces
        (``confirm:cs_xxx`` vs ``evt_xxx``).
        """
        self._require_billing_configured()
        user = self._user_store.get_user_row(user_id)
        if user is None:
            raise LookupError("User not found")

        session = await self._stripe_client.get_checkout_session(session_id)

        session_user_id = _user_id_from_metadata(session)
        if session_user_id != user_id:
            log.info(
                "billing_confirm_session_wrong_user",
                extra={
                    "user_id": user_id,
                    "session_id": session_id,
                    "session_user_id": session_user_id,
                },
            )
            raise StateTransitionError("Checkout session does not belong to this user.")

        if str(session.get("mode") or "") != "subscription":
            raise ValueError("Only subscription-mode checkout sessions can be confirmed.")

        summary = self.build_summary(user_id)
        paid = str(session.get("payment_status") or "") == "paid" and (
            str(session.get("status") or "") == "complete"
        )
        if not paid:
            log.info(
                "billing_confirm_session_not_paid",
                extra={
                    "user_id": user_id,
                    "session_id": session_id,
                    "payment_status": session.get("payment_status"),
                    "status": session.get("status"),
                },
            )
            return BillingConfirmResult(
                summary=summary, processed=False, already_pro=False, not_paid=True
            )

        confirm_event_id = f"confirm:{session_id}"
        if (
            self._user_store.has_processed_billing_event(confirm_event_id)
            or summary.plan_code == "pro"
        ):
            log.info(
                "billing_confirm_session_already_pro",
                extra={"user_id": user_id, "session_id": session_id},
            )
            return BillingConfirmResult(
                summary=self.build_summary(user_id),
                processed=False,
                already_pro=True,
                not_paid=False,
            )

        subscription_obj = session.get("subscription")
        if not isinstance(subscription_obj, dict):
            subscription_obj = {}
        customer_id = _stripe_id(session.get("customer"))
        subscription_id = _stripe_id(session.get("subscription")) or _stripe_id(
            subscription_obj.get("id")
        )

        self._user_store.apply_billing_update(
            user_id=user_id,
            billing_status=BILLING_ACTIVE_PAID,
            plan_code="pro",
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            stripe_price_id=_price_id_from_subscription(subscription_obj)
            or self._settings.stripe_pro_price_id,
            billing_current_period_end=_period_end_from_subscription(subscription_obj),
            billing_last_event_id=confirm_event_id,
        )
        self._user_store.record_billing_webhook_event(
            event_id=confirm_event_id,
            event_type="confirm.checkout.session",
            user_id=user_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        log.info(
            "billing_confirm_session_upgraded",
            extra={"user_id": user_id, "session_id": session_id},
        )
        return BillingConfirmResult(
            summary=self.build_summary(user_id),
            processed=True,
            already_pro=False,
            not_paid=False,
        )

    def process_webhook_event(self, event: dict[str, Any]) -> BillingEventResult:
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id or not event_type:
            raise ValueError("Stripe event is missing id or type.")

        if self._user_store.has_processed_billing_event(event_id):
            return BillingEventResult(
                event_id=event_id,
                event_type=event_type,
                processed=False,
                duplicate=True,
            )

        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            obj = {}

        user_id: str | None = None
        billing_status: str | None = None
        plan_code: str | None = None
        customer_id = _stripe_id(obj.get("customer"))
        subscription_id = _stripe_id(obj.get("subscription"))

        if event_type == "checkout.session.completed":
            user_id = _user_id_from_metadata(obj)
            if not user_id:
                raise ValueError("Checkout session is missing metadata.user_id.")
            self._user_store.apply_billing_update(
                user_id=user_id,
                billing_status=BILLING_ACTIVE_PAID,
                plan_code="pro",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                stripe_price_id=self._settings.stripe_pro_price_id,
                billing_last_event_id=event_id,
            )
            billing_status = BILLING_ACTIVE_PAID
            plan_code = "pro"
        elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
            subscription_id = _stripe_id(obj.get("id")) or subscription_id
            customer_id = _stripe_id(obj.get("customer"))
            user_id = _user_id_from_metadata(obj) or self._user_id_for_customer(customer_id)
            if not user_id:
                raise ValueError("Subscription event could not be mapped to a user.")
            billing_status, plan_code = _status_to_billing_state(str(obj.get("status") or ""))
            self._user_store.apply_billing_update(
                user_id=user_id,
                billing_status=billing_status,
                plan_code=plan_code,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                stripe_price_id=_price_id_from_subscription(obj)
                or self._settings.stripe_pro_price_id,
                billing_current_period_end=_period_end_from_subscription(obj),
                billing_last_event_id=event_id,
            )
        elif event_type == "customer.subscription.deleted":
            subscription_id = _stripe_id(obj.get("id")) or subscription_id
            customer_id = _stripe_id(obj.get("customer"))
            user_id = self._user_id_for_customer(customer_id)
            if user_id and self._is_current_subscription(user_id, subscription_id):
                billing_status = BILLING_CANCELED
                plan_code = "free"
                self._user_store.apply_billing_update(
                    user_id=user_id,
                    billing_status=billing_status,
                    plan_code=plan_code,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    stripe_price_id=_price_id_from_subscription(obj),
                    billing_current_period_end=_period_end_from_subscription(obj),
                    billing_last_event_id=event_id,
                )
        elif event_type == "invoice.payment_failed":
            customer_id = _stripe_id(obj.get("customer"))
            subscription_id = _stripe_id(obj.get("subscription"))
            user_id = self._user_id_for_customer(customer_id)
            if user_id:
                billing_status = BILLING_PAST_DUE
                plan_code = "free"
                self._user_store.apply_billing_update(
                    user_id=user_id,
                    billing_status=billing_status,
                    plan_code=plan_code,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    billing_last_event_id=event_id,
                )

        recorded = self._user_store.record_billing_webhook_event(
            event_id=event_id,
            event_type=event_type,
            user_id=user_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        return BillingEventResult(
            event_id=event_id,
            event_type=event_type,
            processed=recorded,
            duplicate=not recorded,
            user_id=user_id,
            billing_status=billing_status,
            plan_code=plan_code,
        )

    def _require_billing_configured(self) -> None:
        if not self._settings.stripe_billing_is_configured():
            raise BillingConfigurationError(
                "Stripe billing is not configured. Set STRIPE_SECRET_KEY, "
                "STRIPE_WEBHOOK_SECRET, and STRIPE_PRO_PRICE_ID."
            )

    def _user_id_for_customer(self, customer_id: str | None) -> str | None:
        if not customer_id:
            return None
        user = self._user_store.get_user_by_stripe_customer_id(customer_id)
        return str(user.id) if user is not None else None

    def _is_current_subscription(self, user_id: str, subscription_id: str | None) -> bool:
        """Return True unless the event targets a subscription the user has replaced.

        Stripe does not guarantee delivery order and retries failed deliveries
        for hours. A delayed ``customer.subscription.deleted`` for a *superseded*
        subscription must not downgrade a user who has since started a new one.
        When we have no stored subscription id, or the ids match, the event is
        treated as current (fail-open so genuine cancellations still apply).
        """
        if not subscription_id:
            return True
        user = self._user_store.get_user_row(user_id)
        stored = (
            str(user.stripe_subscription_id)
            if user is not None and user.stripe_subscription_id is not None
            else None
        )
        if stored is None:
            return True
        return stored == subscription_id


def _status_to_billing_state(status: str) -> tuple[str, str]:
    if status == "active":
        return BILLING_ACTIVE_PAID, "pro"
    if status == "trialing":
        return BILLING_TRIALING, "pro"
    if status == "past_due":
        return BILLING_PAST_DUE, "free"
    if status in {"canceled", "unpaid", "incomplete_expired"}:
        return BILLING_CANCELED, "free"
    return BILLING_FREE, "free"


def _user_id_from_metadata(obj: dict[str, Any]) -> str | None:
    metadata = obj.get("metadata")
    if isinstance(metadata, dict) and metadata.get("user_id"):
        return str(metadata["user_id"])
    client_reference_id = obj.get("client_reference_id")
    return str(client_reference_id) if client_reference_id else None


def _stripe_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("id"):
        return str(value["id"])
    return None


def _price_id_from_subscription(subscription: dict[str, Any]) -> str | None:
    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    price = first.get("price")
    if isinstance(price, dict) and price.get("id"):
        return str(price["id"])
    return None


def _period_end_from_subscription(subscription: dict[str, Any]) -> datetime | None:
    raw = subscription.get("current_period_end")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
