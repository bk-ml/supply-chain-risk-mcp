"""Unit tests for GeminiBackend — mocked google.genai client, no real API
calls. Specifically exercises the retry loop (429/5xx -> retry -> succeed),
which was previously only manually smoke-tested on the happy path and one
immediate-failure path — the actual "fails once, retries, succeeds" branch
had never been verified before this file.
"""

from unittest.mock import MagicMock

import pytest

from orchestration.llm_backend import GeminiBackend, LLMBackendError


def _fake_response(text: str):
    resp = MagicMock()
    resp.text = text
    return resp


@pytest.fixture
def backend(mocker):
    # Patch the Client import inside GeminiBackend.__init__ so no real
    # credentials or network calls happen.
    mocker.patch("google.genai.Client")
    return GeminiBackend(api_key="fake-key", max_retries=2, retry_base_delay_seconds=0.01)


@pytest.mark.asyncio
async def test_happy_path_returns_text(backend, mocker):
    mocker.patch.object(
        backend._client.models, "generate_content",
        return_value=_fake_response("hello"),
    )
    result = await backend.complete("system", "user")
    assert result == "hello"


@pytest.mark.asyncio
async def test_empty_response_raises_llm_backend_error(backend, mocker):
    mocker.patch.object(
        backend._client.models, "generate_content",
        return_value=_fake_response(""),
    )
    with pytest.raises(LLMBackendError):
        await backend.complete("system", "user")


@pytest.mark.asyncio
async def test_rate_limit_retries_then_succeeds(backend, mocker):
    from google.genai import errors as genai_errors

    rate_limit_error = genai_errors.ClientError(
        429, {"error": {"message": "rate limited"}}, response=MagicMock()
    )
    mock_call = mocker.patch.object(
        backend._client.models, "generate_content",
        side_effect=[rate_limit_error, _fake_response("recovered")],
    )

    result = await backend.complete("system", "user")

    assert result == "recovered"
    assert mock_call.call_count == 2  # confirms it actually retried, not just succeeded once


@pytest.mark.asyncio
async def test_rate_limit_exhausts_retries_and_raises(backend, mocker):
    from google.genai import errors as genai_errors

    rate_limit_error = genai_errors.ClientError(
        429, {"error": {"message": "rate limited"}}, response=MagicMock()
    )
    mock_call = mocker.patch.object(
        backend._client.models, "generate_content",
        side_effect=rate_limit_error,  # every call fails
    )

    with pytest.raises(LLMBackendError):
        await backend.complete("system", "user")

    assert mock_call.call_count == backend._max_retries + 1


@pytest.mark.asyncio
async def test_non_retryable_client_error_fails_fast(backend, mocker):
    from google.genai import errors as genai_errors

    bad_request_error = genai_errors.ClientError(
        400, {"error": {"message": "bad request"}}, response=MagicMock()
    )
    mock_call = mocker.patch.object(
        backend._client.models, "generate_content",
        side_effect=bad_request_error,
    )

    with pytest.raises(LLMBackendError):
        await backend.complete("system", "user")

    # 400 is not retryable — should fail on the first attempt, not retry.
    assert mock_call.call_count == 1


@pytest.mark.asyncio
async def test_server_error_retries_then_succeeds(backend, mocker):
    from google.genai import errors as genai_errors

    server_error = genai_errors.ServerError(
        500, {"error": {"message": "internal error"}}, response=MagicMock()
    )
    mock_call = mocker.patch.object(
        backend._client.models, "generate_content",
        side_effect=[server_error, _fake_response("recovered")],
    )

    result = await backend.complete("system", "user")

    assert result == "recovered"
    assert mock_call.call_count == 2