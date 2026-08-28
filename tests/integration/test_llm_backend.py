"""Real end-to-end test: calls the actual Gemini API. Network-dependent and
costs real (free-tier) quota, so kept separate from the fast unit suite —
same pattern as test_mcp_client_integration.py.

Run explicitly with:
    pytest tests/test_llm_backend_integration.py -v -m integration
"""

import os

import pytest
from dotenv import load_dotenv

from orchestration.llm_backend import GeminiBackend, LLMBackendError

load_dotenv()

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_completion_happy_path():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    result = await backend.complete("You are terse.", "Say hello in exactly 3 words.")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_real_bad_model_name_raises_llm_backend_error():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"], model="not-a-real-model")
    with pytest.raises(LLMBackendError):
        await backend.complete("test", "test")