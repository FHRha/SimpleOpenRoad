from __future__ import annotations

import json

import pytest

from app.config.models import ProviderConfig
from app.core.errors import GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.credentials.google_code_assist import build_auth_url, parse_credential_ref
from app.credentials import google_code_assist
from app.providers.google_code_assist import GoogleCodeAssistAdapter


def _adapter() -> GoogleCodeAssistAdapter:
    return GoogleCodeAssistAdapter(
        ProviderConfig(
            endpoint="https://cloudcode-pa.googleapis.com",
            keys=[],
        )
    )


def _request() -> UnifiedLLMRequest:
    return UnifiedLLMRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(role="system", content="be concise"),
            ChatMessage(role="user", content="hello"),
        ],
        temperature=0.2,
        max_tokens=32,
    )


def test_google_code_assist_payload_matches_code_assist_shape() -> None:
    payload = _adapter()._to_code_assist_payload(_request(), "project-1")  # noqa: SLF001

    assert payload["model"] == "gemini-2.5-pro"
    assert payload["project"] == "project-1"
    assert payload["request"]["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert payload["request"]["systemInstruction"]["parts"][0]["text"] == "be concise"
    assert payload["request"]["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 32}


def test_google_code_assist_response_maps_to_openai_payload() -> None:
    payload = _adapter()._map_non_stream_to_openai(  # noqa: SLF001
        {
            "response": {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
            }
        },
        _request(),
    )

    assert json.dumps(payload)
    assert payload["choices"][0]["message"]["content"] == "ok"
    assert payload["usage"]["total_tokens"] == 3


def test_google_code_assist_empty_response_raises_gateway_error() -> None:
    with pytest.raises(GatewayError, match="no assistant text"):
        _adapter()._map_non_stream_to_openai({"response": {"candidates": []}}, _request())  # noqa: SLF001


def test_google_oauth_ref_parsing() -> None:
    assert parse_credential_ref("oauth:google_code_assist/main")[0] == "main"
    profile, path = parse_credential_ref("oauth-file:/tmp/google.json")
    assert profile == "main"
    assert str(path).endswith("google.json")


def test_google_oauth_url_uses_loopback_redirect_and_required_scopes() -> None:
    flow = build_auth_url("http://127.0.0.1:8765/oauth2callback", client_id="test-client-id", state="s")

    assert "client_id=test-client-id" in flow.auth_url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Foauth2callback" in flow.auth_url
    assert "cloud-platform" in flow.auth_url
    assert flow.state == "s"


def test_google_manual_oauth_url_uses_codeassist_redirect_and_pkce() -> None:
    flow = build_auth_url(
        "https://codeassist.google.com/authcode",
        client_id="test-client-id",
        state="s",
        code_verifier="v" * 64,
    )

    assert "redirect_uri=https%3A%2F%2Fcodeassist.google.com%2Fauthcode" in flow.auth_url
    assert "code_challenge_method=S256" in flow.auth_url
    assert flow.code_verifier == "v" * 64


def test_google_authorization_code_validation_rejects_terminal_noise() -> None:
    assert google_code_assist._looks_like_authorization_code("4/0Aan...valid-looking-code")  # noqa: SLF001
    assert not google_code_assist._looks_like_authorization_code("")  # noqa: SLF001
    assert not google_code_assist._looks_like_authorization_code("https://accounts.google.com/o/oauth2/v2/auth")  # noqa: SLF001
    assert not google_code_assist._looks_like_authorization_code("^Croot@server:~#")  # noqa: SLF001
    assert not google_code_assist._looks_like_authorization_code("code with spaces")  # noqa: SLF001
