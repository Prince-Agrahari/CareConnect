"""Email client abstraction. Notification jobs must not import SendGrid directly."""

from typing import Protocol, runtime_checkable


class EmailError(Exception):
    """Raised when an email provider call fails. Callers must not roll back appointments."""


@runtime_checkable
class EmailClient(Protocol):
    def send(self, *, recipient: str, subject: str, body: str) -> None:
        """Send one email. Must raise EmailError on failure."""


_override_client: EmailClient | None = None


def set_email_client(client: EmailClient | None) -> None:
    global _override_client
    _override_client = client


def get_email_client() -> EmailClient:
    if _override_client is not None:
        return _override_client
    from app.integrations.sendgrid import SendGridEmailClient

    return SendGridEmailClient()
