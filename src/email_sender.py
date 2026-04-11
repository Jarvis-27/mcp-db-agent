"""Email sender abstraction for verification and owner login links."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        ...

    def send_login_email(self, to_address: str, login_url: str) -> None:
        ...


class LogEmailSender:
    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        logger.info("[DEV EMAIL] Verification URL for %s:\n  %s", to_address, verification_url)

    def send_login_email(self, to_address: str, login_url: str) -> None:
        logger.info("[DEV EMAIL] Login URL for %s:\n  %s", to_address, login_url)


class SMTPEmailSender:
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

    def send_login_email(self, to_address: str, login_url: str) -> None:
        body = (
            "<p>Use the link below to sign in to your tenant owner session:</p>"
            f'<p><a href="{login_url}">{login_url}</a></p>'
            "<p>This link expires shortly. If you did not request it, you can ignore this email.</p>"
        )
        self._send(to_address, "Your sign-in link", body)


def make_email_sender(settings) -> EmailSender:  # type: ignore[type-arg]
    if getattr(settings, "smtp_host", None):
        return SMTPEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or "",
            password=settings.smtp_password or "",
            from_address=settings.smtp_from_address or "",
        )
    return LogEmailSender()
