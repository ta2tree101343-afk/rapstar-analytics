from datetime import datetime, timezone

import pytest

from collector.db import MetricSnapshot, Post, make_engine, make_session_factory
from collector.pipeline import upsert_post_and_snapshot


CAPTION = "imag1ne\n#RAPSTAR2026"


def _item(mid="M1", vc=100):
    return {
        "id": mid,
        "caption": CAPTION,
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": f"https://instagram.com/p/{mid}",
        "timestamp": "2026-09-15T12:34:56+0000",
        "view_count": vc,
        "like_count": 1,
        "comments_count": 0,
    }


@pytest.fixture
def sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    return make_session_factory(engine)


def test_new_only_writes_post_no_snapshot(sf):
    fetched = datetime.now(timezone.utc)
    with sf() as s:
        was_new, wrote = upsert_post_and_snapshot(s, _item(), fetched, mode="new-only")
        s.commit()
        assert was_new is True and wrote is False
        assert s.query(Post).count() == 1
        assert s.query(MetricSnapshot).count() == 0


def test_snapshots_only_skips_unknown_post(sf):
    fetched = datetime.now(timezone.utc)
    with sf() as s:
        was_new, wrote = upsert_post_and_snapshot(s, _item(), fetched, mode="snapshots-only")
        s.commit()
        assert was_new is False and wrote is False
        assert s.query(Post).count() == 0
        assert s.query(MetricSnapshot).count() == 0


def test_snapshots_only_writes_for_known_post(sf):
    fetched1 = datetime.now(timezone.utc)
    with sf() as s:
        upsert_post_and_snapshot(s, _item(vc=100), fetched1, mode="both")
        s.commit()
    fetched2 = datetime.now(timezone.utc)
    with sf() as s:
        was_new, wrote = upsert_post_and_snapshot(s, _item(vc=200), fetched2, mode="snapshots-only")
        s.commit()
        assert was_new is False and wrote is True
        snaps = s.query(MetricSnapshot).order_by(MetricSnapshot.id).all()
        assert [x.view_count for x in snaps] == [100, 200]


def test_both_is_default_and_writes_both(sf):
    fetched = datetime.now(timezone.utc)
    with sf() as s:
        was_new, wrote = upsert_post_and_snapshot(s, _item(), fetched)
        s.commit()
        assert was_new is True and wrote is True
        assert s.query(Post).count() == 1
        assert s.query(MetricSnapshot).count() == 1
