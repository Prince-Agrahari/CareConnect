"""LLM client abstraction. Appointment code must not import Gemini directly."""

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when a language-model call fails. Callers must not roll back saved clinical work."""


@runtime_checkable
class LLMClient(Protocol):
    def generate(self, prompt: str) -> str:
        """Return raw model text. Must raise LLMError on failure."""


_override_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Test hook. Production code uses Gemini unless overridden."""
    global _override_client
    _override_client = client


def get_llm_client() -> LLMClient:
    if _override_client is not None:
        return _override_client
    from app.integrations.gemini import GeminiLLMClient

    return GeminiLLMClient()
