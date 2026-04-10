"""Email sender abstraction.

Provides a Protocol (interface) and two concrete implementations:
- LogEmailSender: dev/test default — logs messages instead of sending.
- SMTPEmailSender: production — uses smtplib with STARTTLS.

Use make_email_sender(settings) to get the right implementation at runtime.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class EmailSender(Protocol):
    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        """Send an email verification link to the user."""
        ...

    def send_api_key_email(self, to_address: str, api_key: str) -> None:
        """Send the newly issued API key to the user."""
        ...


# ---------------------------------------------------------------------------
# Log implementation (development / no SMTP configured)
# ---------------------------------------------------------------------------


class LogEmailSender:
    """Logs email content instead of sending. Safe for dev and tests."""

    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        logger.info(
            "[DEV EMAIL] Verification URL for %s:\n  %s",
            to_address,
            verification_url,
        )

    def send_api_key_email(self, to_address: str, api_key: str) -> None:
        logger.info(
            "[DEV EMAIL] API Key for %s:\n  %s\n  Store this key now — it will not be shown again.",
            to_address,
            api_key,
        )


# ---------------------------------------------------------------------------
# SMTP implementation (production)
# ---------------------------------------------------------------------------


class SMTPEmailSender:
    """Sends real emails via SMTP with STARTTLS."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address

    def _send(self, to_address: str, subject: str, body_html: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = to_address
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(self._host, self._port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._username, self._password)
            smtp.sendmail(self._from_address, to_address, msg.as_string())

    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        body = (
            "<p>Thanks for signing up. Click the link below to verify your email address:</p>"
            f'<p><a href="{verification_url}">{verification_url}</a></p>'
            "<p>This link expires in 60 minutes.</p>"
        )
        self._send(to_address, "Verify your email address", body)

    def send_api_key_email(self, to_address: str, api_key: str) -> None:
        body = (
            "<p>Your account has been approved. Here is your API key:</p>"
            f"<pre>{api_key}</pre>"
            "<p><strong>Store this key now — it will not be shown again.</strong></p>"
        )
        self._send(to_address, "Your API key is ready", body)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_email_sender(settings) -> EmailSender:  # type: ignore[type-arg]
    """Return the appropriate EmailSender based on settings.

    Uses SMTPEmailSender when smtp_host is configured; falls back to
    LogEmailSender (no-op + log) for local development.
    """
    if getattr(settings, "smtp_host", None):
        return SMTPEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or "",
            password=settings.smtp_password or "",
            from_address=settings.smtp_from_address or "",
        )
    return LogEmailSender()
