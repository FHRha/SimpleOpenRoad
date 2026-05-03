"""Gemini CLI OAuth helpers used by the experimental provider."""

from __future__ import annotations

import json
import secrets
import base64
import hashlib
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
CODE_ASSIST_VERSION = "v1internal"


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    redirect_uri: str
    code_verifier: str | None = None


def credential_path(profile: str = "main", base_dir: str | Path = "data/credentials") -> Path:
    safe_profile = "".join(ch for ch in profile if ch.isalnum() or ch in {"-", "_"}).strip()
    if not safe_profile:
        safe_profile = "main"
    return Path(base_dir) / "google_code_assist" / f"{safe_profile}.json"


def parse_credential_ref(value: str) -> tuple[str, Path | None]:
    raw = value.strip()
    if raw.startswith("oauth-file:"):
        return "main", Path(raw.removeprefix("oauth-file:")).expanduser()
    if raw.startswith("oauth:google_code_assist/"):
        return raw.rsplit("/", 1)[-1].strip() or "main", None
    if raw.startswith("oauth:"):
        return raw.rsplit("/", 1)[-1].strip() or "main", None
    return raw or "main", None


def build_auth_url(
    redirect_uri: str,
    client_id: str,
    state: str | None = None,
    code_verifier: str | None = None,
) -> OAuthStart:
    state_value = state or secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state_value,
    }
    if code_verifier:
        params["code_challenge_method"] = "S256"
        params["code_challenge"] = _code_challenge(code_verifier)
    return OAuthStart(
        auth_url=f"{AUTH_URL}?{urlencode(params)}",
        state=state_value,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )


def exchange_code(
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    code_verifier: str | None = None,
) -> dict[str, Any]:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    with httpx.Client(timeout=30) as client:
        response = client.post(TOKEN_URL, data=data)
    response.raise_for_status()
    payload = response.json()
    return _normalize_token_payload(payload)


def refresh_access_token(credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = str(credentials.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("Gemini CLI OAuth credentials do not contain refresh_token")
    client_id = str(credentials.get("oauth_client_id") or "").strip()
    client_secret = str(credentials.get("oauth_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            "Gemini CLI OAuth credentials do not contain oauth_client_id/oauth_client_secret. "
            "Run: sor providers connect google --manual-code"
        )
    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    response.raise_for_status()
    payload = _normalize_token_payload(response.json())
    payload["refresh_token"] = refresh_token
    credentials.update(payload)
    return credentials


def ensure_access_token(credentials: dict[str, Any], leeway_seconds: int = 60) -> dict[str, Any]:
    expires_at = int(credentials.get("expires_at") or 0)
    access_token = str(credentials.get("access_token") or "").strip()
    if access_token and expires_at > int(time.time()) + leeway_seconds:
        return credentials
    return refresh_access_token(credentials)


def fetch_user_email(access_token: str) -> str | None:
    with httpx.Client(timeout=30) as client:
        response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code >= 400:
        return None
    payload = response.json()
    email = payload.get("email") if isinstance(payload, dict) else None
    return str(email) if email else None


def load_credentials(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_credentials(path: Path, credentials: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(credentials, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def code_assist_post(access_token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{CODE_ASSIST_ENDPOINT}/{CODE_ASSIST_VERSION}:{method}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    response.raise_for_status()
    return response.json()


def setup_user(credentials: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    credentials = ensure_access_token(credentials)
    access_token = str(credentials["access_token"])
    metadata = _without_none(
        {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": project_id,
        }
    )
    load_payload = _without_none(
        {
            "cloudaicompanionProject": project_id,
            "metadata": metadata,
        }
    )
    load_result = code_assist_post(access_token, "loadCodeAssist", load_payload)
    project = load_result.get("cloudaicompanionProject") or project_id
    tier = load_result.get("paidTier") or load_result.get("currentTier") or {}

    if not project:
        allowed = load_result.get("allowedTiers") or []
        selected = next((item for item in allowed if item.get("isDefault")), None) or (allowed[0] if allowed else None)
        if selected and selected.get("id"):
            onboard = code_assist_post(
                access_token,
                "onboardUser",
                _without_none(
                    {
                        "tierId": selected.get("id"),
                        "cloudaicompanionProject": project_id if selected.get("id") != "free-tier" else None,
                        "metadata": metadata,
                    }
                ),
            )
            response = onboard.get("response") or {}
            companion_project = response.get("cloudaicompanionProject") or {}
            project = companion_project.get("id") or project_id
            tier = selected

    if not project:
        ineligible = load_result.get("ineligibleTiers") or []
        reason = ", ".join(str(item.get("reasonMessage") or item.get("reasonCode")) for item in ineligible)
        raise ValueError(reason or "Gemini CLI OAuth did not return a usable project")

    credentials["project_id"] = project
    credentials["user_tier"] = tier.get("id")
    credentials["user_tier_name"] = tier.get("name")
    return credentials


def run_local_oauth_flow(
    profile: str = "main",
    client_id: str = "",
    client_secret: str = "",
    callback_host: str = "127.0.0.1",
    callback_port: int = 8765,
    open_browser: bool = False,
    project_id: str | None = None,
    base_dir: str | Path = "data/credentials",
) -> tuple[Path, dict[str, Any], str]:
    client_id = _require_oauth_value(client_id, "client_id")
    client_secret = _require_oauth_value(client_secret, "client_secret")
    redirect_uri = f"http://127.0.0.1:{callback_port}/oauth2callback"
    oauth = build_auth_url(redirect_uri, client_id=client_id)
    captured: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            query = parse_qs(urlparse(self.path).query)
            if not self.path.startswith("/oauth2callback"):
                self.send_response(404)
                self.end_headers()
                return
            captured["state"] = query.get("state", [""])[0]
            captured["code"] = query.get("code", [""])[0]
            captured["error"] = query.get("error", [""])[0]
            self.send_response(200 if captured.get("code") else 400)
            self.end_headers()
            self.wfile.write(b"Gemini CLI OAuth authentication received. You can close this tab.")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((callback_host, callback_port), CallbackHandler)
    if open_browser:
        webbrowser.open(oauth.auth_url)
    print(f"Open this URL in your browser:\n{oauth.auth_url}\n")
    print(f"Waiting for callback on {callback_host}:{callback_port} ...")
    server.handle_request()
    server.server_close()

    if captured.get("error"):
        raise ValueError(f"Google OAuth error: {captured['error']}")
    if captured.get("state") != oauth.state:
        raise ValueError("OAuth state mismatch")
    if not captured.get("code"):
        raise ValueError("OAuth callback did not include an authorization code")

    credentials = exchange_code(captured["code"], oauth.redirect_uri, client_id, client_secret)
    credentials["oauth_client_id"] = client_id
    credentials["oauth_client_secret"] = client_secret
    email = fetch_user_email(str(credentials.get("access_token") or ""))
    if email:
        credentials["account_email"] = email
    credentials = setup_user(credentials, project_id=project_id)
    path = credential_path(profile, base_dir=base_dir)
    save_credentials(path, credentials)
    return path, credentials, oauth.auth_url


def run_manual_oauth_flow(
    profile: str = "main",
    client_id: str = "",
    client_secret: str = "",
    project_id: str | None = None,
    base_dir: str | Path = "data/credentials",
) -> tuple[Path, dict[str, Any], str]:
    client_id = _require_oauth_value(client_id, "client_id")
    client_secret = _require_oauth_value(client_secret, "client_secret")
    redirect_uri = "https://codeassist.google.com/authcode"
    code_verifier = secrets.token_urlsafe(64)
    oauth = build_auth_url(redirect_uri, client_id=client_id, code_verifier=code_verifier)
    print("Open this URL in your browser:")
    print(oauth.auth_url)
    print()
    print("Paste only the authorization code here. Type 'q' to cancel.")
    code = _prompt_authorization_code(oauth.auth_url)

    credentials = exchange_code(code, oauth.redirect_uri, client_id, client_secret, code_verifier=code_verifier)
    credentials["oauth_client_id"] = client_id
    credentials["oauth_client_secret"] = client_secret
    email = fetch_user_email(str(credentials.get("access_token") or ""))
    if email:
        credentials["account_email"] = email
    credentials = setup_user(credentials, project_id=project_id)
    path = credential_path(profile, base_dir=base_dir)
    save_credentials(path, credentials)
    return path, credentials, oauth.auth_url


def _normalize_token_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    expires_in = int(result.get("expires_in") or 3600)
    result["expires_at"] = int(time.time()) + expires_in
    return result


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _prompt_authorization_code(auth_url: str) -> str:
    while True:
        try:
            code = input("Paste authorization code: ").strip()
        except KeyboardInterrupt:
            print("\nInterrupted while waiting for the code. The wizard is still running.")
            print("Open this URL in your browser:")
            print(auth_url)
            print("Paste the authorization code, or type 'q' to cancel.")
            continue
        except EOFError as exc:
            raise ValueError("Authorization code input was closed") from exc

        if code.lower() in {"q", "quit", "exit", "cancel"}:
            raise ValueError("Authorization cancelled")
        if _looks_like_authorization_code(code):
            return code
        print("That does not look like an authorization code.")
        print("Paste only the code from the browser page, not the full URL or terminal text.")


def _looks_like_authorization_code(value: str) -> bool:
    if not value or any(ch.isspace() for ch in value):
        return False
    if "http://" in value.lower() or "https://" in value.lower():
        return False
    if any(ord(ch) < 32 for ch in value):
        return False
    return len(value) >= 20


def _require_oauth_value(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Gemini CLI OAuth {name} is required")
    return normalized
