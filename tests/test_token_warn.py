from datetime import datetime, timedelta, timezone

import pytest

from collector.db import AccessTokenRecord, make_engine, make_session_factory, utcnow
from collector.token_warn import check_token_status


@pytest.fixture
def sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    return make_session_factory(engine)


def _insert(sf, expires_at):
    with sf() as s:
        s.add(AccessTokenRecord(
            recorded_at=utcnow(),
            token_fingerprint="EAAxxxxx...abcd",
            token_type="long_lived",
            issued_at=utcnow(),
            expires_at=expires_at,
            scopes="instagram_basic",
            source="check",
        ))
        s.commit()


def test_no_records_yields_unknown(sf):
    s = check_token_status(sf)
    assert s.status == "unknown"
    assert s.days_remaining is None
    assert "有効期限情報なし" in s.message()


def test_expiring_soon_yields_warn(sf):
    _insert(sf, datetime.now(timezone.utc) + timedelta(days=3))
    s = check_token_status(sf, warn_days=7)
    assert s.status == "warn"
    assert "TOKEN_EXPIRES_SOON" in s.message()
    assert s.days_remaining is not None and 2.9 < s.days_remaining < 3.1


def test_expired_yields_expired(sf):
    _insert(sf, datetime.now(timezone.utc) - timedelta(days=1))
    s = check_token_status(sf)
    assert s.status == "expired"
    assert "TOKEN_EXPIRED" in s.message()


def test_healthy_yields_ok(sf):
    _insert(sf, datetime.now(timezone.utc) + timedelta(days=30))
    s = check_token_status(sf, warn_days=7)
    assert s.status == "ok"
    assert "ok" in s.message()


def test_uses_most_recent_row(sf):
    # Insert an older warn-worthy row, then a healthier newer row.
    _insert(sf, datetime.now(timezone.utc) + timedelta(days=1))
    _insert(sf, datetime.now(timezone.utc) + timedelta(days=59))
    s = check_token_status(sf, warn_days=7)
    assert s.status == "ok"
