"""Tests verifying that removed admin routes return 404 and 405."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import api_app


@pytest.fixture
def client():
    return TestClient(api_app, raise_server_exceptions=False)


def test_old_admin_list_pending_returns_404(client):
    resp = client.get("/v1/admin/tenants/pending", headers={"X-Admin-Key": "any-key"})
    assert resp.status_code == 404


def test_old_admin_approve_returns_404(client):
    resp = client.post("/v1/admin/tenants/some-id/approve", headers={"X-Admin-Key": "any-key"})
    assert resp.status_code == 404


def test_old_admin_suspend_returns_404(client):
    resp = client.post("/v1/admin/tenants/some-id/suspend", headers={"X-Admin-Key": "any-key"})
    assert resp.status_code == 404


def test_old_admin_close_returns_404(client):
    resp = client.post("/v1/admin/tenants/some-id/close", headers={"X-Admin-Key": "any-key"})
    assert resp.status_code == 404


def test_old_register_route_returns_404(client):
    resp = client.post("/v1/users/register", json={"email": "x@x.com"})
    assert resp.status_code == 404


def test_old_onboarding_verify_route_returns_404(client):
    resp = client.get("/v1/onboarding/verify-email?token=abc")
    assert resp.status_code == 404


def test_old_onboarding_status_route_returns_404(client):
    resp = client.get("/v1/onboarding/status")
    assert resp.status_code == 404


def test_old_onboarding_database_route_returns_404(client):
    resp = client.post("/v1/onboarding/database", json={})
    assert resp.status_code == 404


def test_old_api_keys_route_returns_404(client):
    resp = client.get("/v1/api-keys")
    assert resp.status_code == 404


def test_old_users_me_route_returns_404(client):
    resp = client.get("/v1/users/me")
    assert resp.status_code == 404


def test_old_setup_payloads_route_returns_404(client):
    resp = client.post("/v1/setup/payloads", json={})
    assert resp.status_code == 404


def test_old_dashboard_summary_route_returns_404(client):
    resp = client.get("/v1/dashboard/summary")
    assert resp.status_code == 404


def test_old_usage_recent_route_returns_404(client):
    resp = client.get("/v1/usage/recent")
    assert resp.status_code == 404
