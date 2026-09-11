"""SMTP sender for the MVP (architecture §13). A transactional API sender can replace it."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from app.core.config import Settings
from app.notifications.email.base import DeliveryResult
from app.notifications.templates import render


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(
        self, to: str, template: str, params: dict[str, Any], idempotency_key: str
    ) -> DeliveryResult:
        locale = str(params.get("locale", "en"))
        subject, text_body, html_body = render(template, locale, params)

        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        # Lets a retry be recognised as the same message by the provider and by the recipient.
        message["Message-ID"] = f"<{idempotency_key}@research-management>"
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        try:
            await asyncio.to_thread(self._deliver, message)
        except (smtplib.SMTPException, OSError) as error:
            return DeliveryResult(accepted=False, detail=str(error))
        return DeliveryResult(accepted=True)

    def _deliver(self, message: EmailMessage) -> None:
        settings = self._settings
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as client:
            if settings.smtp_user:
                client.starttls()
                client.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            client.send_message(message)
