from __future__ import annotations

import json
import time

import httpx
import pytest

from app.config.models import ProviderConfig
from app.core.errors import GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.credentials.google_code_assist import (
    gemini_cli_credentials_path,
    gemini_cli_keychain_path,
    parse_credential_ref,
)
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


def test_gemini_cli_credentials_path_uses_home_gemini_dir(tmp_path) -> None:
    assert gemini_cli_credentials_path(tmp_path) == tmp_path / ".gemini" / "oauth_creds.json"
    assert gemini_cli_keychain_path(tmp_path) == tmp_path / ".gemini" / "gemini-credentials.json"


def test_gemini_oauth_redirect_uri_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_OAUTH_REDIRECT_URI", "http://127.0.0.1:8085/authcode")

    assert google_code_assist.gemini_oauth_redirect_uri() == "http://127.0.0.1:8085/authcode"


def test_google_oauth_client_credentials_use_builtin_default(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GEMINI_OAUTH_CLIENT_SECRET", raising=False)

    client_id, client_secret = google_code_assist._gemini_oauth_client_credentials()  # noqa: SLF001

    assert client_id == "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
    assert client_secret is None


def test_local_oauth_callback_listener_receives_code() -> None:
    listener = google_code_assist.start_oauth_callback_listener("http://127.0.0.1:0/authcode")
    try:
        assert listener.redirect_uri.startswith("http://127.0.0.1:")
        response = httpx.get(
            f"{listener.redirect_uri}?code=auth-code-123&state=state-123",
            timeout=5,
        )
        assert response.status_code == 200
        code, error = listener.wait_for_code(expected_state="state-123", timeout_seconds=2)
        assert error is None
        assert code == "auth-code-123"
    finally:
        listener.close()


def test_imported_gemini_cli_credentials_normalizes_expiry_date() -> None:
    credentials = google_code_assist._normalize_imported_credentials(  # noqa: SLF001
        {"access_token": "token", "expiry_date": 1_800_000_000_000}
    )

    assert credentials["expires_at"] == 1_800_000_000


def test_imported_gemini_cli_credentials_normalizes_keychain_token_shape() -> None:
    credentials = google_code_assist._normalize_imported_credentials(  # noqa: SLF001
        {
            "serverName": "main-account",
            "token": {
                "accessToken": "token",
                "refreshToken": "refresh",
                "tokenType": "Bearer",
                "expiresAt": 1_800_000_000_000,
            },
        }
    )

    assert credentials["access_token"] == "token"
    assert credentials["refresh_token"] == "refresh"
    assert credentials["expires_at"] == 1_800_000_000


def test_load_gemini_cli_file_keychain_reads_main_account(tmp_path, monkeypatch) -> None:
    source = tmp_path / ".gemini" / "gemini-credentials.json"
    source.parent.mkdir(parents=True)
    source.write_text("encrypted", encoding="utf-8")
    decrypted = json.dumps(
        {
            "gemini-cli-oauth": {
                "main-account": json.dumps(
                    {
                        "serverName": "main-account",
                        "token": {
                            "accessToken": "token",
                            "refreshToken": "refresh",
                            "expiresAt": 1_800_000_000_000,
                        },
                    }
                )
            }
        }
    )
    monkeypatch.setattr(google_code_assist, "_decrypt_gemini_cli_file_keychain", lambda _value: decrypted)

    credentials = google_code_assist._load_gemini_cli_credentials_source(source)  # noqa: SLF001

    assert credentials["token"]["accessToken"] == "token"


def test_import_gemini_cli_credentials_copies_profile(tmp_path, monkeypatch) -> None:
    source = tmp_path / "home" / ".gemini" / "oauth_creds.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "access_token": "token",
                "refresh_token": "refresh",
                "expiry_date": int((time.time() + 3600) * 1000),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(google_code_assist, "fetch_user_email", lambda _token: "user@example.com")

    path, credentials = google_code_assist.import_gemini_cli_credentials(
        source_path=source,
        base_dir=tmp_path / "data" / "credentials",
    )

    assert path == tmp_path / "data" / "credentials" / "google_code_assist" / "main.json"
    assert path.exists()
    assert credentials["credential_source"] == "gemini_cli"
    assert credentials["account_email"] == "user@example.com"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "project_id" not in saved
