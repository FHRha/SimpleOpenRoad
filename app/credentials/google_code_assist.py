"""Gemini CLI OAuth helpers used by the experimental provider."""

from __future__ import annotations

import json
import getpass
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx


USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
CODE_ASSIST_VERSION = "v1internal"
GEMINI_CLI_KEYCHAIN_FILE = "gemini-credentials.json"
GEMINI_CLI_KEYCHAIN_SERVICE = "gemini-cli-oauth"
GEMINI_CLI_MAIN_ACCOUNT = "main-account"


def credential_path(profile: str = "main", base_dir: str | Path = "data/credentials") -> Path:
    safe_profile = "".join(ch for ch in profile if ch.isalnum() or ch in {"-", "_"}).strip()
    if not safe_profile:
        safe_profile = "main"
    return Path(base_dir) / "google_code_assist" / f"{safe_profile}.json"


def gemini_cli_credentials_path(home: str | Path | None = None) -> Path:
    base = Path(home).expanduser() if home is not None else Path.home()
    return base / ".gemini" / "oauth_creds.json"


def gemini_cli_keychain_path(home: str | Path | None = None) -> Path:
    base = Path(home).expanduser() if home is not None else Path.home()
    return base / ".gemini" / GEMINI_CLI_KEYCHAIN_FILE


def parse_credential_ref(value: str) -> tuple[str, Path | None]:
    raw = value.strip()
    if raw.startswith("oauth-file:"):
        return "main", Path(raw.removeprefix("oauth-file:")).expanduser()
    if raw.startswith("oauth:google_code_assist/"):
        return raw.rsplit("/", 1)[-1].strip() or "main", None
    if raw.startswith("oauth:"):
        return raw.rsplit("/", 1)[-1].strip() or "main", None
    return raw or "main", None


def refresh_access_token(credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = str(credentials.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("Gemini CLI OAuth credentials do not contain refresh_token")
    raise ValueError(
        "Gemini CLI OAuth token is expired and cannot be refreshed directly by SimpleOpenRoad. "
        "Run the official Gemini CLI login again, then run: sor providers connect google"
    )


def ensure_access_token(credentials: dict[str, Any], leeway_seconds: int = 60) -> dict[str, Any]:
    expires_at = _credential_expires_at(credentials)
    access_token = str(credentials.get("access_token") or "").strip()
    if access_token and expires_at > int(time.time()) + leeway_seconds:
        return credentials
    return refresh_access_token(credentials)


def fetch_user_email(access_token: str) -> str | None:
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError:
        return None
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
    if response.status_code >= 400:
        body = response.text[:1200]
        if response.status_code == 403 and method == "loadCodeAssist":
            raise ValueError(
                "Google Code Assist rejected the imported Gemini CLI credentials with 403 on loadCodeAssist. "
                "Run the official Gemini CLI again with the same Google account, make sure the account has "
                "Gemini Code Assist / AI Pro access, then run: sor providers connect google. "
                "Upstream response: "
                f"{body}"
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


def import_gemini_cli_credentials(
    profile: str = "main",
    source_path: str | Path | None = None,
    project_id: str | None = None,
    base_dir: str | Path = "data/credentials",
) -> tuple[Path, dict[str, Any]]:
    source = Path(source_path).expanduser() if source_path else _default_gemini_cli_credentials_source()
    if not source.exists():
        raise ValueError(
            f"Gemini CLI credentials were not found at {source}. "
            "Run the official Gemini CLI and sign in with Google first. "
            "On a headless VPS, prefer: GEMINI_FORCE_FILE_STORAGE=true gemini"
        )
    credentials = _load_gemini_cli_credentials_source(source)
    credentials["credential_source"] = "gemini_cli"
    credentials["source_path"] = str(source)
    credentials = _normalize_imported_credentials(credentials)
    if project_id:
        credentials["project_id"] = project_id
    email = fetch_user_email(str(credentials.get("access_token") or ""))
    if email:
        credentials["account_email"] = email
    path = credential_path(profile, base_dir=base_dir)
    save_credentials(path, credentials)
    return path, credentials


def _normalize_imported_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    result = _normalize_gemini_cli_token_shape(credentials)
    expires_at = _credential_expires_at(result)
    if expires_at:
        result["expires_at"] = expires_at
    if not result.get("access_token"):
        raise ValueError("Imported Gemini CLI credentials do not contain access_token")
    return result


def _default_gemini_cli_credentials_source() -> Path:
    legacy = gemini_cli_credentials_path()
    if legacy.exists():
        return legacy
    return gemini_cli_keychain_path()


def _load_gemini_cli_credentials_source(source: Path) -> dict[str, Any]:
    if source.name == GEMINI_CLI_KEYCHAIN_FILE:
        return _load_gemini_cli_file_keychain(source)
    return load_credentials(source)


def _load_gemini_cli_file_keychain(source: Path) -> dict[str, Any]:
    encrypted = source.read_text(encoding="utf-8").strip()
    decrypted = _decrypt_gemini_cli_file_keychain(encrypted)
    data = json.loads(decrypted)
    service = data.get(GEMINI_CLI_KEYCHAIN_SERVICE)
    if not isinstance(service, dict):
        raise ValueError(f"Gemini CLI file storage does not contain {GEMINI_CLI_KEYCHAIN_SERVICE}")
    account = service.get(GEMINI_CLI_MAIN_ACCOUNT)
    if not isinstance(account, str) or not account.strip():
        raise ValueError(f"Gemini CLI file storage does not contain {GEMINI_CLI_MAIN_ACCOUNT}")
    credentials = json.loads(account)
    if not isinstance(credentials, dict):
        raise ValueError("Gemini CLI file storage contains invalid OAuth credentials")
    return credentials


def _decrypt_gemini_cli_file_keychain(encrypted: str) -> str:
    parts = encrypted.split(":")
    if len(parts) != 3:
        raise ValueError("Gemini CLI credentials file is not in the expected encrypted format")
    script = """
const crypto = require("node:crypto");
const os = require("node:os");
const encrypted = process.argv[1];
const hostname = process.argv[2];
const username = process.argv[3];
const [ivHex, tagHex, dataHex] = encrypted.split(":");
const salt = `${hostname}-${username}-gemini-cli`;
const key = crypto.scryptSync("gemini-cli-oauth", salt, 32);
const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivHex, "hex"));
decipher.setAuthTag(Buffer.from(tagHex, "hex"));
let out = decipher.update(dataHex, "hex", "utf8");
out += decipher.final("utf8");
process.stdout.write(out);
""".strip()
    try:
        result = subprocess.run(
            ["node", "-e", script, encrypted, platform.node(), getpass.getuser()],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise ValueError("Node.js is required to import Gemini CLI encrypted file credentials") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValueError(f"Could not decrypt Gemini CLI credentials file: {detail}") from exc
    return result.stdout


def _normalize_gemini_cli_token_shape(credentials: dict[str, Any]) -> dict[str, Any]:
    token = credentials.get("token")
    if isinstance(token, dict):
        return {
            **credentials,
            "access_token": token.get("accessToken"),
            "refresh_token": token.get("refreshToken"),
            "token_type": token.get("tokenType"),
            "scope": token.get("scope"),
            "expiry_date": token.get("expiresAt"),
        }
    return dict(credentials)


def _credential_expires_at(credentials: dict[str, Any]) -> int:
    expires_at = int(credentials.get("expires_at") or 0)
    if expires_at:
        return expires_at
    expiry_date = int(credentials.get("expiry_date") or 0)
    if expiry_date:
        return int(expiry_date / 1000) if expiry_date > 10_000_000_000 else expiry_date
    return 0


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
