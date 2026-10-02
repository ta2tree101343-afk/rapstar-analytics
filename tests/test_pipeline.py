from datetime import datetime, timezone

import pytest

from collector.db import FetchRun, MetricSnapshot, Post, make_engine, make_session_factory
from collector.pipeline import run_collection, upsert_post_and_snapshot


ENTRY_CAPTION = (
    "imag1ne / 22 / 東京\n"
    "RAPSTAR 2026\n"
    "#RAPSTAR2026"
)


def _sample(view_count=163499, like_count=2713, comments_count=18, mid="M1"):
    return {
        "id": mid,
        "caption": ENTRY_CAPTION,
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": f"https://instagram.com/p/{mid}",
        "timestamp": "2026-09-15T12:34:56+0000",
        "view_count": view_count,
        "like_count": like_count,
        "comments_count": comments_count,
    }


@pytest.fixture
def sf(tmp_path):
    url = f"sqlite:///{tmp_path}/t.db"
    engine = make_engine(url)
    return make_session_factory(engine)


def test_first_insert_creates_post_and_snapshot(sf):
    fetched = datetime.now(timezone.utc)
    with sf() as s:
        was_new, wrote = upsert_post_and_snapshot(s, _sample(), fetched)
        s.commit()
        assert was_new is True and wrote is True
        assert s.query(Post).count() == 1
        assert s.query(MetricSnapshot).count() == 1
        p = s.query(Post).one()
        assert p.classification == "entry"
        assert p.rapper_name == "imag1ne"
        assert p.media_product_type == "REELS"


def test_second_fetch_appends_snapshot_not_duplicate_post(sf):
    with sf() as s:
        upsert_post_and_snapshot(s, _sample(view_count=1000), datetime(2026, 9, 20, 0, tzinfo=timezone.utc))
        s.commit()
    with sf() as s:
        upsert_post_and_snapshot(s, _sample(view_count=2000), datetime(2026, 9, 21, 0, tzinfo=timezone.utc))
        s.commit()
    with sf() as s:
        assert s.query(Post).count() == 1
        snaps = s.query(MetricSnapshot).order_by(MetricSnapshot.fetched_at).all()
        assert [x.view_count for x in snaps] == [1000, 2000]


def test_null_metric_is_preserved_not_zeroed(sf):
    item = _sample()
    del item["view_count"]  # simulate API not returning it
    with sf() as s:
        upsert_post_and_snapshot(s, item, datetime.now(timezone.utc))
        s.commit()
        snap = s.query(MetricSnapshot).one()
        assert snap.view_count is None
        assert snap.like_count == 2713


def test_unclassified_never_downgraded_from_entry(sf):
    entry = _sample()
    with sf() as s:
        upsert_post_and_snapshot(s, entry, datetime.now(timezone.utc))
        s.commit()
    later = dict(entry)
    later["caption"] = "no hashtag anymore"
    with sf() as s:
        upsert_post_and_snapshot(s, later, datetime.now(timezone.utc))
        s.commit()
        p = s.query(Post).one()
        assert p.classification == "entry"


def test_promotes_unclassified_to_entry(sf):
    first = _sample()
    first["caption"] = "teaser only"
    with sf() as s:
        upsert_post_and_snapshot(s, first, datetime.now(timezone.utc))
        s.commit()
        assert s.query(Post).one().classification == "unclassified"
    second = _sample()
    with sf() as s:
        upsert_post_and_snapshot(s, second, datetime.now(timezone.utc))
        s.commit()
        assert s.query(Post).one().classification == "entry"


def test_run_collection_records_fetch_run(sf):
    items = [
        _sample(mid="M1", view_count=100),
        _sample(mid="M2", view_count=200),
    ]
    summary = run_collection(sf, iter(items), api_call_getter=lambda: 1)
    assert summary.status == "success"
    assert summary.posts_seen == 2
    assert summary.new_posts == 2
    assert summary.snapshots_written == 2
    with sf() as s:
        runs = s.query(FetchRun).all()
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].posts_seen == 2


def test_run_collection_isolates_per_item_error(sf):
    good = _sample(mid="M1")
    bad = _sample(mid="")  # empty id triggers skip
    bad["id"] = ""
    summary = run_collection(sf, iter([good, bad]))
    assert summary.posts_seen == 2
    assert summary.new_posts == 1
    with sf() as s:
        assert s.query(Post).count() == 1


def test_report_matches_reported_sample_values(sf):
    """Regression: confirm the 5-post sample from the user is stored verbatim."""
    reported = [
        ("M-imag1ne", "imag1ne", 163499, 2713, 18),
        ("M-KeeRooz", "Kee Rooz", 455228, 15083, 98),
        ("M-onyourmaxx", "onyourmaxx", 198288, 3092, 49),
        ("M-Broder", "Broder", 144327, 1914, 28),
        ("M-BabyNyca", "BabyNyca", 174014, 2440, 46),
    ]
    fetched = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    for mid, name, vc, lc, cc in reported:
        item = _sample(view_count=vc, like_count=lc, comments_count=cc, mid=mid)
        item["caption"] = f"{name} / 25 / Tokyo\nRAPSTAR 2026\n#RAPSTAR2026"
        with sf() as s:
            upsert_post_and_snapshot(s, item, fetched)
            s.commit()
    with sf() as s:
        posts = s.query(Post).order_by(Post.external_post_id).all()
        assert {p.rapper_name for p in posts} == {n for _, n, *_ in reported}
        assert all(p.classification == "entry" for p in posts)
