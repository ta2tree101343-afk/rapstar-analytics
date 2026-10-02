"""Inspect the current IG_USER_ACCESS_TOKEN.

Prints token type (short_lived / long_lived / never_expires), expiration in UTC ISO 8601,
days remaining, and scopes. Records the observation to `access_tokens` table.

Never prints the token value itself — only a short fingerprint (first 8 + last 4 chars).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.config import load_settings, PROJECT_ROOT  # noqa: E402
from collector.db import make_engine, make_session_factory  # noqa: E402
from collector.token_manager import (  # noqa: E402
    build_app_access_token,
    call_debug_token,
    fingerprint,
    record_token,
    TokenManagerError,
)


WARN_DAYS = 7


def main() -> int:
    settings = load_settings()
    app_id = (Path(PROJECT_ROOT / ".env").exists() and _read_env("META_APP_ID")) or ""
    app_secret = _read_env("META_APP_SECRET") or ""

    if not app_id or not app_secret:
        print("[error] META_APP_ID / META_APP_SECRET が .env に未設定です。")
        print("        Meta for Developers → 対象アプリ → 設定 → ベーシック から取得してください。")
        return 2

    app_token = build_app_access_token(app_id, app_secret)

    try:
        debug = call_debug_token(settings.access_token, app_token, settings.api_version)
    except TokenManagerError as e:
        # Ensure the message never leaks the token
        print(f"[error] {settings.redact_secrets(str(e))}")
        return 3

    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    record_token(sf, settings.access_token, debug, source="check")

    days = debug.days_until_expiry()
    print("=== IG User Access Token 診断 ===")
    print(f"fingerprint            : {fingerprint(settings.access_token)}")
    print(f"is_valid               : {debug.is_valid}")
    print(f"token_type             : {debug.token_type}")
    print(f"issued_at (UTC)        : {_iso(debug.issued_at)}")
    print(f"expires_at (UTC)       : {_iso(debug.expires_at)}")
    print(f"data_access_expires_at : {_iso(debug.data_access_expires_at)}")
    print(f"scopes                 : {','.join(debug.scopes) if debug.scopes else '(none)'}")
    if days is not None:
        print(f"days_until_expiry      : {days:.1f}")
        if days < WARN_DAYS:
            print(f"[WARN] トークン有効期限まで {days:.1f} 日です。exchange_token.py で更新してください。")

    if not debug.is_valid:
        return 4
    return 0


def _iso(dt) -> str:
    return dt.isoformat() if dt else "(none)"


def _read_env(key: str) -> str:
    """Read a key from .env directly without printing values."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.lstrip()
        if s.startswith(f"{key}="):
            return s.split("=", 1)[1].strip()
    return ""


if __name__ == "__main__":
    sys.exit(main())
