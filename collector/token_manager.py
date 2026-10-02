from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


GRAPH_HOST = "https://graph.facebook.com"
LONG_LIVED_THRESHOLD_SECONDS = 30 * 24 * 3600  # >30 days remaining → treat as long-lived


class TokenManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class DebugResult:
    is_valid: bool
    token_type: str  # 'short_lived' | 'long_lived' | 'never_expires'
    issued_at: datetime | None
    expires_at: datetime | None
    data_access_expires_at: datetime | None
    scopes: list[str]
    raw: dict[str, Any]

    def days_until_expiry(self, now: datetime | None = None) -> float | None:
        if self.expires_at is None:
            return None
        ref = now or datetime.now(timezone.utc)
        return (self.expires_at - ref).total_seconds() / 86400.0


def build_app_access_token(app_id: str, app_secret: str) -> str:
    if not app_id or not app_secret:
        raise TokenManagerError(
            "META_APP_ID / META_APP_SECRET が未設定のため App Access Token を構築できません。"
        )
    return f"{app_id}|{app_secret}"


def fingerprint(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 12:
        return "***"
    return f"{token[:8]}...{token[-4:]}"


def _unix_to_utc(ts: int | None) -> datetime | None:
    if ts is None or ts == 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_debug_response(payload: dict[str, Any]) -> DebugResult:
    data = payload.get("data") or {}
    expires_at_raw = data.get("expires_at")
    issued_at_raw = data.get("issued_at")

    expires_at = _unix_to_utc(expires_at_raw)
    issued_at = _unix_to_utc(issued_at_raw)

    if expires_at_raw == 0:
        token_type = "never_expires"
    elif expires_at is None:
        token_type = "short_lived"
    else:
        now = datetime.now(timezone.utc)
        remaining = (expires_at - now).total_seconds()
        token_type = "long_lived" if remaining > LONG_LIVED_THRESHOLD_SECONDS else "short_lived"

    return DebugResult(
        is_valid=bool(data.get("is_valid", False)),
        token_type=token_type,
        issued_at=issued_at,
        expires_at=expires_at,
        data_access_expires_at=_unix_to_utc(data.get("data_access_expires_at")),
        scopes=list(data.get("scopes") or []),
        raw=data,
    )


def call_debug_token(
    input_token: str,
    app_access_token: str,
    api_version: str,
    session: requests.Session | None = None,
) -> DebugResult:
    """Call /debug_token. Never logs the URL or token values."""
    s = session or requests.Session()
    resp = s.get(
        f"{GRAPH_HOST}/{api_version}/debug_token",
        params={"input_token": input_token, "access_token": app_access_token},
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        raise TokenManagerError(f"debug_token: non-JSON response status={resp.status_code}")
    if resp.status_code >= 400 or "error" in payload:
        # Redact any token appearance from error body
        redacted = json.dumps(payload, ensure_ascii=False)
        for secret in (input_token, app_access_token):
            if secret:
                redacted = redacted.replace(secret, "***REDACTED***")
        raise TokenManagerError(f"debug_token error status={resp.status_code}: {redacted}")
    return parse_debug_response(payload)


def call_exchange_long_lived(
    app_id: str,
    app_secret: str,
    short_token: str,
    api_version: str,
    session: requests.Session | None = None,
) -> tuple[str, int | None]:
    """Exchange short-lived for long-lived. Returns (new_token, expires_in_seconds)."""
    s = session or requests.Session()
    resp = s.get(
        f"{GRAPH_HOST}/{api_version}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        raise TokenManagerError(f"exchange: non-JSON response status={resp.status_code}")
    if resp.status_code >= 400 or "error" in payload:
        redacted = json.dumps(payload, ensure_ascii=False)
        for secret in (app_secret, short_token):
            if secret:
                redacted = redacted.replace(secret, "***REDACTED***")
        raise TokenManagerError(f"exchange error status={resp.status_code}: {redacted}")
    new_token = payload.get("access_token")
    if not new_token:
        raise TokenManagerError("exchange response missing access_token")
    return new_token, payload.get("expires_in")


def atomic_update_env(env_path: Path, updates: dict[str, str]) -> None:
    """Update .env in place preserving other keys, comments, and line order.

    Writes to a tmp file in the same directory with mode 0o600, then atomically renames.
    If the target file was 0o600 originally we keep it, otherwise we harden it.
    """
    if not env_path.exists():
        raise TokenManagerError(f".env not found at {env_path}")

    original_text = env_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)
    remaining = dict(updates)

    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        matched_key = None
        for k in remaining:
            if stripped.startswith(f"{k}="):
                matched_key = k
                break
        if matched_key is not None:
            eol = "\n" if line.endswith("\n") else ""
            new_lines.append(f"{matched_key}={remaining.pop(matched_key)}{eol}")
        else:
            new_lines.append(line)

    for k, v in remaining.items():
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{k}={v}\n")

    dir_ = env_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_, delete=False, prefix=".env.", suffix=".tmp"
    ) as tf:
        tf.write("".join(new_lines))
        tmp_path = Path(tf.name)
    try:
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, env_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise


def record_token(
    session_factory,
    token_value: str,
    debug: DebugResult,
    source: str,
) -> None:
    from .db import AccessTokenRecord, utcnow

    with session_factory() as session:
        session.add(
            AccessTokenRecord(
                recorded_at=utcnow(),
                token_fingerprint=fingerprint(token_value),
                token_type=debug.token_type,
                issued_at=debug.issued_at,
                expires_at=debug.expires_at,
                data_access_expires_at=debug.data_access_expires_at,
                scopes=",".join(debug.scopes) if debug.scopes else None,
                source=source,
            )
        )
        session.commit()
