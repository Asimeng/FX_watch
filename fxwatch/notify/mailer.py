"""Email delivery backends."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Protocol

from fxwatch.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str | None = None
    unsubscribe_url: str | None = None


class MailError(RuntimeError):
    pass


class Mailer(Protocol):
    def send(self, email: OutgoingEmail) -> None: ...


def build_message(settings: Settings, email: OutgoingEmail) -> EmailMessage:
    sender = settings.sender_address or "fxwatch@localhost"
    msg = EmailMessage()
    msg["From"] = formataddr((settings.mail_from_name, sender))
    msg["To"] = email.to
    msg["Subject"] = email.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] or "localhost")
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to
    if email.unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{email.unsubscribe_url}>"
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(email.text)
    if email.html:
        msg.add_alternative(email.html, subtype="html")
    return msg


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, email: OutgoingEmail) -> None:
        s = self.settings
        msg = build_message(s, email)
        context = ssl.create_default_context()
        try:
            smtp: smtplib.SMTP
            if s.smtp_ssl:
                smtp = smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
                )
            else:
                smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            with smtp:
                if s.smtp_starttls and not s.smtp_ssl:
                    smtp.starttls(context=context)
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"{type(exc).__name__}: {exc}") from exc
        log.info(
            "email sent", extra={"to_domain": email.to.rsplit("@", 1)[-1], "subject": email.subject}
        )


class ConsoleMailer:
    """Development backend: prints emails to the log and keeps them in memory."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sent: list[OutgoingEmail] = []

    def send(self, email: OutgoingEmail) -> None:
        self.sent.append(email)
        log.info("[console mail] To: %s | %s\n%s", email.to, email.subject, email.text)


def get_mailer(settings: Settings) -> Mailer:
    if settings.mail_backend == "smtp":
        return SmtpMailer(settings)
    return ConsoleMailer(settings)
