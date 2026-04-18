"""Vertex AI OpenAI-compatible adapter with Google Cloud auth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.providers.openai_compatible import OpenAICompatibleAdapter


class VertexAIAdapter(OpenAICompatibleAdapter):
    cloud_platform_scope = "https://www.googleapis.com/auth/cloud-platform"

    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="vertex_ai", config=config)
        self._credentials_cache: dict[str, Any] = {}

    def _build_headers(self, key: KeyConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.auth_required:
            headers["Authorization"] = f"Bearer {self._resolve_access_token(key)}"
        headers.update(self.extra_headers)
        headers.update(self.config.headers)
        return headers

    def _resolve_access_token(self, key: KeyConfig) -> str:
        raw = str(key.key or "").strip()
        if not raw:
            raise GatewayError(
                message="Vertex AI key value is missing. Use an access token, service account JSON path, or 'adc'.",
                error_class=ErrorClass.AUTH_INVALID,
                status_code=401,
                provider=self.provider_name,
                key_id=key.id,
            )
        if raw.lower() not in {"adc"} and not (raw.lower().endswith(".json") and Path(raw).is_file()):
            return raw
        credentials = self._credential_for_key(key, raw)
        if not getattr(credentials, "valid", False):
            request = self._google_auth_request()
            credentials.refresh(request)
        token = getattr(credentials, "token", None)
        if not token:
            raise GatewayError(
                message="Vertex AI credentials did not produce an access token.",
                error_class=ErrorClass.AUTH_INVALID,
                status_code=401,
                provider=self.provider_name,
                key_id=key.id,
            )
        return str(token)

    def _credential_for_key(self, key: KeyConfig, raw: str):
        cached = self._credentials_cache.get(key.id)
        if cached is not None:
            return cached
        if raw.lower() == "adc":
            credentials = self._google_default_credentials()
        else:
            credentials = self._google_service_account_credentials(raw)
        self._credentials_cache[key.id] = credentials
        return credentials

    def _google_default_credentials(self):
        try:
            import google.auth
        except ImportError as exc:  # pragma: no cover - exercised through runtime error path
            raise GatewayError(
                message="google-auth is required for Vertex AI ADC authentication.",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=500,
                provider=self.provider_name,
                key_id=None,
            ) from exc
        credentials, _ = google.auth.default(scopes=[self.cloud_platform_scope])
        return credentials

    def _google_service_account_credentials(self, path: str):
        try:
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - exercised through runtime error path
            raise GatewayError(
                message="google-auth is required for Vertex AI service account authentication.",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=500,
                provider=self.provider_name,
                key_id=None,
            ) from exc
        try:
            return service_account.Credentials.from_service_account_file(
                path,
                scopes=[self.cloud_platform_scope],
            )
        except Exception as exc:  # noqa: BLE001
            raise GatewayError(
                message=f"Vertex AI service account credentials could not be loaded: {exc}",
                error_class=ErrorClass.AUTH_INVALID,
                status_code=401,
                provider=self.provider_name,
                key_id=None,
            ) from exc

    @staticmethod
    def _google_auth_request():
        try:
            from google.auth.transport.requests import Request
        except ImportError as exc:  # pragma: no cover - exercised through runtime error path
            raise GatewayError(
                message="google-auth and requests are required for Vertex AI token refresh.",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=500,
                provider="vertex_ai",
                key_id=None,
            ) from exc
        return Request()
