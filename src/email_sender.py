"""Email sender abstraction for verification and account sign-in links."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


_VERIFICATION_SUBJECT = "Verify your email address"
_VERIFICATION_BODY = (
    "<p>Thanks for signing up. Click the link below to verify your email address:</p>"
    '<p><a href="{url}">{url}</a></p>'
    "<p>This link expires in 60 minutes.</p>"
)
_LOGIN_SUBJECT = "Your sign-in link"
_LOGIN_BODY = (
    "<p>Use the link below to sign in to your account:</p>"
    '<p><a href="{url}">{url}</a></p>'
    "<p>This link expires shortly. If you did not request it, you can ignore this email.</p>"
)


class EmailSender(Protocol):
    def send_verification_email(self, to_address: str, verification_url: str) -> None: ...

    def send_login_email(self, to_address: str, login_url: str) -> None: ...


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
        self._send(
            to_address,
            _VERIFICATION_SUBJECT,
            _VERIFICATION_BODY.format(url=verification_url),
        )

    def send_login_email(self, to_address: str, login_url: str) -> None:
        self._send(
            to_address,
            _LOGIN_SUBJECT,
            _LOGIN_BODY.format(url=login_url),
        )


class ResendEmailSender:
    _API_URL = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str,
        from_address: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._from_address = from_address
        self._timeout = timeout

    def _send(self, to_address: str, subject: str, body_html: str) -> None:
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self._API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from_address,
                    "to": [to_address],
                    "subject": subject,
                    "html": body_html,
                },
            )
        if response.status_code >= 400:
            logger.error(
                "Resend send failed for %s (%s): %s",
                to_address,
                response.status_code,
                response.text,
            )
            response.raise_for_status()

    def send_verification_email(self, to_address: str, verification_url: str) -> None:
        self._send(
            to_address,
            _VERIFICATION_SUBJECT,
            _VERIFICATION_BODY.format(url=verification_url),
        )

    def send_login_email(self, to_address: str, login_url: str) -> None:
        self._send(
            to_address,
            _LOGIN_SUBJECT,
            _LOGIN_BODY.format(url=login_url),
        )


def make_email_sender(settings) -> EmailSender:  # type: ignore[type-arg]
    if getattr(settings, "resend_api_key", None) and getattr(
        settings, "resend_from_address", None
    ):
        return ResendEmailSender(
            api_key=settings.resend_api_key,
            from_address=settings.resend_from_address,
        )
    if getattr(settings, "smtp_host", None):
        return SMTPEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or "",
            password=settings.smtp_password or "",
            from_address=settings.smtp_from_address or "",
        )
    return LogEmailSender()
