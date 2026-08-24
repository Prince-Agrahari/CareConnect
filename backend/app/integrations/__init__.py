"""External integrations. Appointment and leave services must not import Gemini directly."""

from app.integrations.calendar import CalendarClient, CalendarError, get_calendar_client, set_calendar_client
from app.integrations.email import EmailClient, EmailError, get_email_client, set_email_client
from app.integrations.llm import LLMClient, LLMError, get_llm_client, set_llm_client

__all__ = [
    "CalendarClient",
    "CalendarError",
    "EmailClient",
    "EmailError",
    "LLMClient",
    "LLMError",
    "get_calendar_client",
    "get_email_client",
    "get_llm_client",
    "set_calendar_client",
    "set_email_client",
    "set_llm_client",
]
