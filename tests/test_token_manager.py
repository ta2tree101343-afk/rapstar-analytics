import os
import stat
from datetime import datetime, timezone

import pytest

from collector.token_manager import (
    LONG_LIVED_THRESHOLD_SECONDS,
    atomic_update_env,
    build_app_access_token,
    fingerprint,
    parse_debug_response,
    TokenManagerError,
)


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def test_fingerprint_short_token_masks_fully():
    assert fingerprint("abc") == "***"
    assert fingerprint("") == ""


def test_fingerprint_long_token_shows_head_tail():
    tok = "EAABC" + "X" * 200 + "WXYZ"
    fp = fingerprint(tok)
    assert fp.startswith("EAABCXXX")
    assert fp.endswith("WXYZ")
    assert "..." in fp
    assert tok not in fp


def test_build_app_access_token_format():
    assert build_app_access_token("123", "abc") == "123|abc"


def test_build_app_access_token_missing_raises():
    with pytest.raises(TokenManagerError):
        build_app_access_token("", "abc")
    with pytest.raises(TokenManagerError):
        build_app_access_token("123", "")


def test_parse_debug_response_short_lived():
    now = _now()
    payload = {"data": {
        "is_valid": True,
        "issued_at": now - 60,
        "expires_at": now + 3600,  # 1 hour → short-lived
        "scopes": ["instagram_basic"],
    }}
    r = parse_debug_response(payload)
    assert r.is_valid is True
    assert r.token_type == "short_lived"
    assert r.expires_at is not None


def test_parse_debug_response_long_lived():
    now = _now()
    payload = {"data": {
        "is_valid": True,
        "issued_at": now - 60,
        "expires_at": now + LONG_LIVED_THRESHOLD_SECONDS + 3600,  # >30 days
        "scopes": ["instagram_basic", "pages_read_engagement"],
    }}
    r = parse_debug_response(payload)
    assert r.token_type == "long_lived"
    assert "instagram_basic" in r.scopes


def test_parse_debug_response_never_expires():
    payload = {"data": {"is_valid": True, "expires_at": 0, "issued_at": _now()}}
    r = parse_debug_response(payload)
    assert r.token_type == "never_expires"
    assert r.expires_at is None


def test_atomic_update_env_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "META_APP_ID=111\n"
        "META_APP_SECRET=222\n"
        "IG_USER_ACCESS_TOKEN=OLD\n"
        "IG_BUSINESS_ACCOUNT_ID=333\n"
        "TARGET_IG_USERNAME=rapstar_starz\n",
        encoding="utf-8",
    )
    atomic_update_env(env, {"IG_USER_ACCESS_TOKEN": "NEW_LONG_TOKEN"})
    text = env.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "# comment" in lines
    assert "META_APP_ID=111" in lines
    assert "META_APP_SECRET=222" in lines
    assert "IG_USER_ACCESS_TOKEN=NEW_LONG_TOKEN" in lines
    assert "IG_USER_ACCESS_TOKEN=OLD" not in lines
    assert "IG_BUSINESS_ACCOUNT_ID=333" in lines
    assert "TARGET_IG_USERNAME=rapstar_starz" in lines
    assert lines.index("IG_USER_ACCESS_TOKEN=NEW_LONG_TOKEN") == 3


def test_atomic_update_env_sets_600_perm(tmp_path):
    env = tmp_path / ".env"
    env.write_text("IG_USER_ACCESS_TOKEN=OLD\n", encoding="utf-8")
    atomic_update_env(env, {"IG_USER_ACCESS_TOKEN": "NEW"})
    mode = stat.S_IMODE(os.stat(env).st_mode)
    assert mode == 0o600


def test_atomic_update_env_appends_new_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\n", encoding="utf-8")
    atomic_update_env(env, {"C": "3"})
    lines = env.read_text().splitlines()
    assert lines == ["A=1", "B=2", "C=3"]


def test_atomic_update_env_missing_file_raises(tmp_path):
    with pytest.raises(TokenManagerError):
        atomic_update_env(tmp_path / "nonexistent.env", {"A": "1"})


def test_atomic_update_env_never_leaves_partial_on_success(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nIG_USER_ACCESS_TOKEN=OLD\n", encoding="utf-8")
    atomic_update_env(env, {"IG_USER_ACCESS_TOKEN": "NEW"})
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".env.") and p.name.endswith(".tmp")]
    assert leftovers == []
