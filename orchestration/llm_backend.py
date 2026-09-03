"""
LLM backend abstraction. Every agent depends on this interface, not on any
specific SDK — swapping providers should mean adding a new class here, not
touching agent code.

Design decisions (document in README):
- complete() returns raw text only. Structured JSON parsing (into TriageResult,
  SynthesisOutput, etc.) happens one layer up, in agent code — the backend's
  job is "get text back from the model," nothing schema-aware.
- Async, to match the rest of the orchestration layer (Option A's clients are
  all async; the orchestrator and MCP client will be too).
- temperature defaults to 0.0 — Triage classification and Synthesis structured
  output want determinism for eval reproducibility, not creativity.
- Retries for transient failures (rate limits, timeouts) live INSIDE each
  backend implementation, since retry shape is provider-specific. The
  interface contract is simply "eventually returns text, or raises
  LLMBackendError" — callers don't manage retries themselves.
"""

from __future__ import annotations

import abc
import asyncio
import logging

logger = logging.getLogger(__name__)


class LLMBackendError(Exception):
    """Raised when a backend fails after exhausting its retries."""


class LLMBackend(abc.ABC):
    @abc.abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
    ) -> str:
        """Return the model's raw text completion.

        Raises:
            LLMBackendError: on failure after retries are exhausted.
        """
        raise NotImplementedError


class GeminiBackend(LLMBackend):
    """Backend implementation using google-genai (NOT the deprecated
    google-generativeai package). Confirmed working model string as of
    2026-08-27: gemini-3.6-flash — gemini-2.0-flash has been retired.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.6-flash",
        max_retries: int = 2,
        retry_base_delay_seconds: float = 1.0,
    ):
        # Deferred import so the base module doesn't hard-require google-genai
        # to be installed just to use the abstraction / other backends.
        from google.genai import Client

        self._client = Client(api_key=api_key)
        self._model = model
        self._max_retries = max_retries
        self._retry_base_delay_seconds = retry_base_delay_seconds

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
    ) -> str:
        from google.genai import errors as genai_errors
        from google.genai.types import GenerateContentConfig

        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                # google-genai's client is sync; run in a thread so this
                # coroutine doesn't block the orchestrator's event loop.
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=user_prompt,
                    config=GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=temperature,
                    ),
                )
                if not response.text:
                    raise LLMBackendError(
                        f"Gemini returned an empty response for model {self._model}"
                    )
                return response.text

            except genai_errors.ClientError as e:
                # 4xx: rate limit (429) is worth retrying briefly; other 4xx
                # (bad request, model not found) are not — fail fast.
                # Note: the attribute is `.code`, not `.status_code` — confirmed
                # against google-genai's APIError base class source.
                status = getattr(e, "code", None)
                if status == 429 and attempt < self._max_retries:
                    delay = self._retry_base_delay_seconds * (2 ** attempt)
                    logger.warning(
                        "Gemini rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                raise LLMBackendError(f"Gemini client error: {e}") from e

            except genai_errors.ServerError as e:
                # 5xx: worth retrying.
                if attempt < self._max_retries:
                    delay = self._retry_base_delay_seconds * (2 ** attempt)
                    logger.warning(
                        "Gemini server error (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, self._max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                raise LLMBackendError(f"Gemini server error after retries: {e}") from e

        raise LLMBackendError(
            f"Gemini failed after {self._max_retries} retries: {last_exc}"
        )