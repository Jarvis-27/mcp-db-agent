"""Unit tests for src.email_sender (ResendEmailSender and factory precedence)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from src.email_sender import (
    LogEmailSender,
    ResendEmailSender,
    SMTPEmailSender,
    make_email_sender,
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self._request = httpx.Request("POST", "https://api.resend.com/emails")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=self._request,
                response=httpx.Response(self.status_code, request=self._request),
            )


def _patch_httpx_client(monkeypatch, response: _FakeResponse) -> MagicMock:
    """Replace httpx.Client with a context-manager mock; return the post mock."""
    post_mock = MagicMock(return_value=response)
    client_instance = MagicMock()
    client_instance.post = post_mock
    client_instance.__enter__ = MagicMock(return_value=client_instance)
    client_instance.__exit__ = MagicMock(return_value=False)
    client_cls = MagicMock(return_value=client_instance)
    monkeypatch.setattr("src.email_sender.httpx.Client", client_cls)
    return post_mock


class TestResendEmailSender:
    def test_send_verification_email_posts_expected_payload(self, monkeypatch):
        post_mock = _patch_httpx_client(monkeypatch, _FakeResponse(200))
        sender = ResendEmailSender(
            api_key="re_test_key",
            from_address="MCP <noreply@example.com>",
        )

        sender.send_verification_email(
            "alice@example.com", "https://app.example.com/verify?token=abc"
        )

        post_mock.assert_called_once()
        args, kwargs = post_mock.call_args
        assert args[0] == "https://api.resend.com/emails"
        assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        payload = kwargs["json"]
        assert payload["from"] == "MCP <noreply@example.com>"
        assert payload["to"] == ["alice@example.com"]
        assert payload["subject"] == "Verify your email address"
        assert "https://app.example.com/verify?token=abc" in payload["html"]

    def test_send_login_email_posts_expected_payload(self, monkeypatch):
        post_mock = _patch_httpx_client(monkeypatch, _FakeResponse(200))
        sender = ResendEmailSender(api_key="re_x", from_address="from@example.com")

        sender.send_login_email("bob@example.com", "https://app.example.com/login?t=xyz")

        payload = post_mock.call_args.kwargs["json"]
        assert payload["to"] == ["bob@example.com"]
        assert payload["subject"] == "Your sign-in link"
        assert "https://app.example.com/login?t=xyz" in payload["html"]

    def test_send_raises_on_http_error(self, monkeypatch):
        _patch_httpx_client(monkeypatch, _FakeResponse(401, "invalid api key"))
        sender = ResendEmailSender(api_key="bad", from_address="from@example.com")

        with pytest.raises(httpx.HTTPStatusError):
            sender.send_verification_email("a@b.com", "https://x/verify")


class TestMakeEmailSender:
    def test_returns_log_sender_when_nothing_configured(self):
        settings = SimpleNamespace(smtp_host=None, resend_api_key=None, resend_from_address=None)
        assert isinstance(make_email_sender(settings), LogEmailSender)

    def test_returns_smtp_sender_when_only_smtp_configured(self):
        settings = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user",
            smtp_password="pass",
            smtp_from_address="from@example.com",
            resend_api_key=None,
            resend_from_address=None,
        )
        assert isinstance(make_email_sender(settings), SMTPEmailSender)

    def test_resend_takes_precedence_over_smtp(self):
        settings = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="u",
            smtp_password="p",
            smtp_from_address="from@example.com",
            resend_api_key="re_key",
            resend_from_address="resend-from@example.com",
        )
        sender = make_email_sender(settings)
        assert isinstance(sender, ResendEmailSender)

    def test_falls_back_when_resend_only_partially_configured(self):
        settings = SimpleNamespace(
            smtp_host=None,
            resend_api_key="re_key",
            resend_from_address=None,
        )
        assert isinstance(make_email_sender(settings), LogEmailSender)
