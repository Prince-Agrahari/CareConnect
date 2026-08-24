"""SendGrid implementation of the email client protocol."""

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.core.config import settings
from app.integrations.email import EmailError


class SendGridEmailClient:
    def send(self, *, recipient: str, subject: str, body: str) -> None:
        api_key = settings.SENDGRID_API_KEY
        sender = settings.SENDGRID_FROM_EMAIL
        if not api_key or not sender:
            raise EmailError("SENDGRID_API_KEY or SENDGRID_FROM_EMAIL is not configured")
        try:
            message = Mail(
                from_email=sender,
                to_emails=recipient,
                subject=subject,
                plain_text_content=body,
            )
            response = SendGridAPIClient(api_key).send(message)
            if int(getattr(response, "status_code", 0)) >= 400:
                raise EmailError(f"SendGrid rejected the message ({response.status_code})")
        except EmailError:
            raise
        except Exception as exc:
            raise EmailError(str(exc) or "SendGrid request failed") from exc
