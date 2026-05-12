"""Tests for Stripe-backed billing endpoints and entitlement transitions."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import pytest
from cachetools import TTLCache
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.auth.url_guard as ug_module
from src.api import app as api_module
from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore
from src.billing.stripe_client import StripeCheckoutSession, StripePortalSession

_VALID_URL = "postgresql://user:pass@8.8.8.8/db"
_WEBHOOK_SECRET = "whsec_test_secret"


@dataclass
class MockStripeClient:
    customer_id: str = "cus_test_123"
    checkout_id: str = "cs_test_123"
    checkout_url: str = "https://checkout.stripe.test/session"
    portal_id: str = "bps_test_123"
    portal_url: str = "https://billing.stripe.test/session"

    def __post_init__(self) -> None:
        self.created_customers: list[dict[str, str]] = []
        self.checkout_sessions: list[dict[str, str]] = []
        self.portal_sessions: list[dict[str, str]] = []

    async def create_customer(self, *, email: str, user_id: str) -> str:
        self.created_customers.append({"email": email, "user_id": user_id})
        return self.customer_id

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> StripeCheckoutSession:
        self.checkout_sessions.append(
            {
                "customer_id": customer_id,
                "user_id": user_id,
                "price_id": price_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return StripeCheckoutSession(id=self.checkout_id, url=self.checkout_url)

    async def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> StripePortalSession:
        self.portal_sessions.append({"customer_id": customer_id, "return_url": return_url})
        return StripePortalSession(id=self.portal_id, url=self.portal_url)


@pytest.fixture(autouse=True)
def app_state(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    store = UserStore(engine, cipher)
    stripe_client = MockStripeClient()

    api_app.state.user_store = store
    api_app.state.cipher = cipher
    api_app.state.auth_key_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.user_session_cache = TTLCache(maxsize=100, ttl=60)
    api_app.state.factory = None
    api_app.state.stripe_client = stripe_client

    monkeypatch.setattr(ug_module.settings, "environment", "development")
    monkeypatch.setattr(api_module.settings, "registration_open", True)
    monkeypatch.setattr(api_module.settings, "allow_sqlite_user_dbs", False)
    monkeypatch.setattr(api_module.settings, "billing_gate_enabled", False)
    monkeypatch.setattr(api_module.settings, "mfa_gate_enabled", False)
    monkeypatch.setattr(api_module.settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(api_module.settings, "stripe_webhook_secret", _WEBHOOK_SECRET)
    monkeypatch.setattr(api_module.settings, "stripe_pro_price_id", "price_pro_123")
    monkeypatch.setattr(api_module.settings, "stripe_api_base", "https://api.stripe.test")
    monkeypatch.setattr(api_module.settings, "frontend_base_url", "http://localhost:3000")

    yield store, stripe_client

    if hasattr(api_app.state, "stripe_client"):
        delattr(api_app.state, "stripe_client")
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(api_app)


def _active_session(store: UserStore, email: str = "billing@example.com") -> tuple[str, str]:
    user_id = store.create_user(email)
    store.set_email_verified(user_id)
    store.transition_user_state(user_id, "pending_db_connection")
    store.upsert_user_database(user_id, store._cipher.encrypt(_VALID_URL))
    store.activate_user(user_id)
    token = store.issue_user_session(user_id, ttl_hours=24)
    return user_id, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signed_event(event: dict) -> tuple[bytes, str]:
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    signed = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(_WEBHOOK_SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


def test_billing_summary_reports_free_plan(client, app_state):
    store, _stripe_client = app_state
    _user_id, token = _active_session(store)

    resp = client.get("/v1/account/billing", headers=_auth(token))

    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_code"] == "free"
    assert data["billing_status"] == "free"
    assert data["daily_limit"] == 25
    assert data["checkout_available"] is True
    assert data["portal_available"] is False


def test_checkout_session_creates_customer_and_returns_stripe_url(client, app_state):
    store, stripe_client = app_state
    user_id, token = _active_session(store)

    resp = client.post("/v1/account/billing/checkout-session", headers=_auth(token), json={})

    assert resp.status_code == 200
    assert resp.json() == {"id": "cs_test_123", "url": stripe_client.checkout_url}
    assert stripe_client.created_customers == [{"email": "billing@example.com", "user_id": user_id}]
    assert stripe_client.checkout_sessions[0]["price_id"] == "price_pro_123"
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.stripe_customer_id) == "cus_test_123"


def test_portal_session_requires_existing_customer(client, app_state):
    store, _stripe_client = app_state
    _user_id, token = _active_session(store)

    resp = client.post("/v1/account/billing/portal-session", headers=_auth(token), json={})

    assert resp.status_code == 409
    assert "No Stripe customer" in resp.json()["detail"]


def test_portal_session_returns_stripe_url(client, app_state):
    store, stripe_client = app_state
    user_id, token = _active_session(store)
    store.set_stripe_customer_id(user_id, "cus_existing")

    resp = client.post("/v1/account/billing/portal-session", headers=_auth(token), json={})

    assert resp.status_code == 200
    assert resp.json() == {"id": "bps_test_123", "url": stripe_client.portal_url}
    assert stripe_client.portal_sessions == [
        {"customer_id": "cus_existing", "return_url": "http://localhost:3000/app/billing"}
    ]


def test_checkout_completed_webhook_upgrades_user_and_is_idempotent(client, app_state):
    store, _stripe_client = app_state
    user_id, _token = _active_session(store)
    event = {
        "id": "evt_checkout_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_checkout",
                "subscription": "sub_checkout",
                "metadata": {"user_id": user_id},
            }
        },
    }
    payload, signature = _signed_event(event)

    resp = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )
    duplicate = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] is True
    assert resp.json()["billing_status"] == "active_paid"
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.plan_code) == "pro"
    assert str(user.billing_status) == "active_paid"
    assert str(user.stripe_customer_id) == "cus_checkout"
    assert str(user.stripe_subscription_id) == "sub_checkout"


def test_subscription_past_due_webhook_restricts_to_free(client, app_state):
    store, _stripe_client = app_state
    user_id, _token = _active_session(store)
    store.apply_billing_update(
        user_id=user_id,
        billing_status="active_paid",
        plan_code="pro",
        stripe_customer_id="cus_due",
        stripe_subscription_id="sub_due",
    )
    event = {
        "id": "evt_due_1",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_due",
                "customer": "cus_due",
                "status": "past_due",
                "items": {"data": [{"price": {"id": "price_pro_123"}}]},
            }
        },
    }
    payload, signature = _signed_event(event)

    resp = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert resp.status_code == 200
    assert resp.json()["billing_status"] == "past_due"
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.plan_code) == "free"
    assert str(user.billing_status) == "past_due"


def test_subscription_deleted_webhook_downgrades_to_free(client, app_state):
    store, _stripe_client = app_state
    user_id, _token = _active_session(store)
    store.apply_billing_update(
        user_id=user_id,
        billing_status="active_paid",
        plan_code="pro",
        stripe_customer_id="cus_cancel",
        stripe_subscription_id="sub_cancel",
    )
    event = {
        "id": "evt_cancel_1",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_cancel", "customer": "cus_cancel"}},
    }
    payload, signature = _signed_event(event)

    resp = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": signature},
    )

    assert resp.status_code == 200
    user = store.get_user_row(user_id)
    assert user is not None
    assert str(user.plan_code) == "free"
    assert str(user.billing_status) == "canceled"


def test_webhook_rejects_invalid_signature(client, app_state):
    _store, _stripe_client = app_state
    payload = b'{"id":"evt_bad","type":"checkout.session.completed"}'

    resp = client.post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=123,v1=bad"},
    )

    assert resp.status_code == 400
