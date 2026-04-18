from __future__ import annotations

from pathlib import Path

import pytest

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import GatewayError
from app.providers.vertex_ai import VertexAIAdapter


class _FakeCredentials:
    def __init__(self, token: str = "token-123", valid: bool = False):
        self.token = token
        self.valid = valid

    def refresh(self, _request) -> None:
        self.valid = True


def test_vertex_ai_adapter_uses_access_token_directly() -> None:
    adapter = VertexAIAdapter(
        ProviderConfig(
            endpoint="https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        )
    )

    headers = adapter._build_headers(KeyConfig(id="vertex-main", key="ya29.direct-token"))

    assert headers["Authorization"] == "Bearer ya29.direct-token"


def test_vertex_ai_adapter_uses_adc_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = VertexAIAdapter(
        ProviderConfig(
            endpoint="https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        )
    )
    fake_credentials = _FakeCredentials()
    monkeypatch.setattr(adapter, "_google_default_credentials", lambda: fake_credentials)
    monkeypatch.setattr(adapter, "_google_auth_request", lambda: object())

    headers = adapter._build_headers(KeyConfig(id="vertex-main", key="adc"))

    assert headers["Authorization"] == "Bearer token-123"


def test_vertex_ai_adapter_uses_service_account_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = VertexAIAdapter(
        ProviderConfig(
            endpoint="https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        )
    )
    credentials_path = tmp_path / "service-account.json"
    credentials_path.write_text("{}", encoding="utf-8")
    fake_credentials = _FakeCredentials()
    monkeypatch.setattr(adapter, "_google_service_account_credentials", lambda path: fake_credentials)
    monkeypatch.setattr(adapter, "_google_auth_request", lambda: object())

    headers = adapter._build_headers(KeyConfig(id="vertex-main", key=str(credentials_path)))

    assert headers["Authorization"] == "Bearer token-123"


def test_vertex_ai_adapter_rejects_missing_key_value() -> None:
    adapter = VertexAIAdapter(
        ProviderConfig(
            endpoint="https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        )
    )

    with pytest.raises(GatewayError) as exc:
        adapter._build_headers(KeyConfig(id="vertex-main", key=""))

    assert exc.value.error_class.value == "auth_invalid"
