"""Consumers (recipients) of insight events: configuration and delivery channels."""

import hashlib
import hmac
import json
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import yaml
from pydantic import BaseModel, ConfigDict

from events.email import render_email
from events.insight import Severity

CONSUMERS_FILE = Path(__file__).resolve().parent / "consumers.yaml"


class ConsumerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["email", "webhook"]
    types: list[Literal["anomaly", "briefing", "forecast_deviation", "data_quality"]]
    min_severity: Severity = "warning"
    max_age_days: int = 2
    # Highest data class this consumer may receive (plan section 8). Email leaves the system via an
    # external SMTP provider, so confidential events (decisions, meetings) never go there.
    max_data_class: Literal["public", "internal", "confidential"] = "internal"
    to_env: str | None = None
    url_env: str | None = None
    secret_env: str | None = None


class Sender(Protocol):
    def send(self, event_id: str, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: str | None
    password: str | None
    starttls: bool
    sender: str

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        # Defaults target the local Mailpit container (infra/docker-compose.yml).
        return cls(
            host=os.getenv("BIS_SMTP_HOST", "127.0.0.1"),
            port=int(os.getenv("BIS_SMTP_PORT", "1025")),
            user=os.getenv("BIS_SMTP_USER") or None,
            password=os.getenv("BIS_SMTP_PASSWORD") or None,
            starttls=os.getenv("BIS_SMTP_STARTTLS", "false").lower() == "true",
            sender=os.getenv("BIS_ALERT_FROM", "BI-System <alerts@bis.local>"),
        )


class EmailSender:
    def __init__(self, recipients: list[str], smtp: SmtpSettings, dashboard_url: str):
        self.recipients = recipients
        self.smtp = smtp
        self.dashboard_url = dashboard_url

    def send(self, event_id: str, payload: dict[str, Any]) -> None:
        subject, html, text = render_email(payload, self.dashboard_url)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.smtp.sender
        message["To"] = ", ".join(self.recipients)
        # Lets mail clients and the SMTP provider de-duplicate retried deliveries.
        message["Message-ID"] = f"<{event_id}@bis.local>"
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        with smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=15) as smtp:
            if self.smtp.starttls:
                smtp.starttls()
            if self.smtp.user and self.smtp.password:
                smtp.login(self.smtp.user, self.smtp.password)
            smtp.send_message(message)


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookSender:
    """POSTs the event as JSON. Receivers verify X-BIS-Signature (HMAC-SHA256 of the raw body),
    de-duplicate by X-BIS-Event-Id and dispatch on X-BIS-Event-Type (= schema_version)."""

    def __init__(self, url: str, secret: str, client: httpx.Client | None = None):
        self.url = url
        self.secret = secret
        self.client = client or httpx.Client(timeout=10)

    def send(self, event_id: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        response = self.client.post(
            self.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-BIS-Event-Id": event_id,
                "X-BIS-Event-Type": str(payload.get("schema_version", "")),
                "X-BIS-Signature": signature(self.secret, body),
            },
        )
        response.raise_for_status()


def load_consumers(path: Path = CONSUMERS_FILE) -> list[ConsumerConfig]:
    return [ConsumerConfig.model_validate(c) for c in yaml.safe_load(path.read_text(encoding="utf-8")) or []]


def build_sender(config: ConsumerConfig, env: dict[str, str] | None = None) -> Sender | None:
    """Sender for an active consumer, or None when its required variables are not set."""
    env = dict(os.environ) if env is None else env
    if config.type == "email":
        recipients = [a.strip() for a in env.get(config.to_env or "", "").split(",") if a.strip()]
        if not recipients:
            return None
        return EmailSender(
            recipients, SmtpSettings.from_env(), env.get("BIS_DASHBOARD_URL", "http://127.0.0.1:5173")
        )
    url, secret = env.get(config.url_env or ""), env.get(config.secret_env or "")
    if not url or not secret:
        return None
    return WebhookSender(url, secret)
