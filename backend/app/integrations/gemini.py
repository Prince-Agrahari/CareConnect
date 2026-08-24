"""Gemini implementation of the LLM client protocol."""

import google.generativeai as genai

from app.core.config import settings
from app.integrations.llm import LLMError

GEMINI_TIMEOUT_SECONDS = 30


def _llm_error_message(exc: Exception) -> str:
    combined = f"{type(exc).__name__} {exc}".lower()
    if any(token in combined for token in ("timeout", "timed out", "deadline")):
        return "Gemini request timed out"
    return str(exc) or "Gemini request failed"


class GeminiLLMClient:
    def generate(self, prompt: str) -> str:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not configured")
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=settings.GEMINI_MODEL)
            response = model.generate_content(
                prompt,
                request_options={"timeout": GEMINI_TIMEOUT_SECONDS},
            )
            text = getattr(response, "text", None)
            if not text or not str(text).strip():
                raise LLMError("Gemini returned an empty response")
            return str(text)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(_llm_error_message(exc)) from exc
