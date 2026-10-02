"""Exchange a short-lived Facebook User access token for a long-lived one.

Reads META_APP_ID, META_APP_SECRET, IG_USER_ACCESS_TOKEN from .env.
On success, atomically updates IG_USER_ACCESS_TOKEN in .env preserving other lines,
and records the new token metadata into `access_tokens`.

Never prints the App Secret nor any access token; only fingerprints appear in logs.

If the current token is already long-lived (>30 days remaining), the script exits
without exchanging unless --force is passed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.config import load_settings, PROJECT_ROOT  # noqa: E402
from collector.db import make_engine, make_session_factory  # noqa: E402
from collector.token_manager import (  # noqa: E402
    TokenManagerError,
    atomic_update_env,
    build_app_access_token,
    call_debug_token,
    call_exchange_long_lived,
    fingerprint,
    record_token,
)


def _read_env(key: str) -> str:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.lstrip()
        if s.startswith(f"{key}="):
            return s.split("=", 1)[1].strip()
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Exchange short-lived → long-lived token")
    p.add_argument("--force", action="store_true", help="Exchange even if current token is already long-lived")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    app_id = _read_env("META_APP_ID")
    app_secret = _read_env("META_APP_SECRET")

    if not app_id or not app_secret:
        print("[error] META_APP_ID / META_APP_SECRET が .env に未設定です。")
        return 2

    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)

    app_token = build_app_access_token(app_id, app_secret)

    try:
        current = call_debug_token(settings.access_token, app_token, settings.api_version)
    except TokenManagerError as e:
        print(f"[error] 現在のトークンを確認できません: {settings.redact_secrets(str(e))}")
        return 3

    print(f"current fingerprint : {fingerprint(settings.access_token)}")
    print(f"current type        : {current.token_type}")
    remaining = current.days_until_expiry()
    if remaining is not None:
        print(f"current days_left   : {remaining:.1f}")

    record_token(sf, settings.access_token, current, source="check")

    if current.token_type == "long_lived" and not args.force:
        print("[info] 既に長期トークンです。--force なしでは交換しません。")
        return 0

    try:
        new_token, expires_in = call_exchange_long_lived(
            app_id=app_id,
            app_secret=app_secret,
            short_token=settings.access_token,
            api_version=settings.api_version,
        )
    except TokenManagerError as e:
        print(f"[error] 交換に失敗しました。既存の .env は変更しません: {settings.redact_secrets(str(e))}")
        return 4

    try:
        new_debug = call_debug_token(new_token, app_token, settings.api_version)
    except TokenManagerError as e:
        print(f"[error] 新トークンの診断に失敗しました。.env は変更しません: {e}")
        return 5

    env_path = PROJECT_ROOT / ".env"
    try:
        atomic_update_env(env_path, {"IG_USER_ACCESS_TOKEN": new_token})
        os.chmod(env_path, 0o600)
    except Exception as e:  # noqa: BLE001
        print(f"[error] .env 更新に失敗しました: {e}")
        return 6

    record_token(sf, new_token, new_debug, source="exchange")

    print("=== 交換完了 ===")
    print(f"new fingerprint     : {fingerprint(new_token)}")
    print(f"new type            : {new_debug.token_type}")
    print(f"new expires_at (UTC): {new_debug.expires_at.isoformat() if new_debug.expires_at else '(none)'}")
    if expires_in is not None:
        print(f"expires_in (sec)    : {expires_in} (~{expires_in/86400:.1f} days)")
    print("[ok] .env を更新しました。他の環境変数は保持されています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
