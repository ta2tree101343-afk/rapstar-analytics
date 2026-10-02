"""/api/compare: response-size and batched-cancellation tests.

Complements test_read_api_compare_scale.py which exercises point-count limits.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _setup(dynamodb, num_posts, snaps_per_post, caption_padding=""):
    from tests.test_read_api import TABLES, _create, _put_post, _put_snap
    for name, spec in TABLES.items():
        _create(dynamodb, name, spec)
    posts = dynamodb.Table("posts")
    snapshots = dynamodb.Table("snapshots")
    for i in range(num_posts):
        pid = f"P{i:03d}"
        views = 10_000_000 - i * 1000
        posts.put_item(Item={
            "external_post_id": pid,
            "rapper_name": f"Rapper_{i}",
            "permalink": f"https://instagram.com/reel/{pid}",
            "posted_at": (NOW.replace()).isoformat(),
            "classification": "entry",
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "latest_view_count": views,
            "latest_like_count": 100 + i,
            "latest_comments_count": 10 + i,
            "latest_fetched_at": NOW.isoformat(),
        })
        for h in range(snaps_per_post):
            _put_snap(snapshots, pid=pid, hours_ago=h, view=views - h, like=100 + i - h, comments=10 + i)
    return posts, snapshots


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setenv("POSTS_TABLE", "posts")
    monkeypatch.setenv("SNAPSHOTS_TABLE", "snapshots")
    monkeypatch.setenv("FETCH_RUNS_TABLE", "fetch_runs")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        yield ddb


def _call(path, query=None):
    from read_api.handler import lambda_handler
    return lambda_handler({
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": path,
        "queryStringParameters": query or {},
    }, None)


def _body(resp):
    return json.loads(resp["body"])


def test_response_bytes_stay_within_budget_when_full(env):
    """No truncation: JSON payload must remain under the byte budget."""
    _setup(env, num_posts=5, snaps_per_post=20)
    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    assert r["statusCode"] == 200
    body_bytes = len(r["body"].encode("utf-8"))
    from read_api.service import MAX_COMPARE_RESPONSE_BYTES
    assert body_bytes <= MAX_COMPARE_RESPONSE_BYTES


def test_response_truncates_by_byte_size_before_hitting_point_cap(env, monkeypatch):
    """Force a small byte budget → truncation kicks in even though total
    points are far under MAX_TOTAL_HISTORY_POINTS."""
    from read_api import service as svc

    # 20 posts × 20 snapshots = 400 points, well below 50k.
    _setup(env, num_posts=20, snaps_per_post=20)

    monkeypatch.setattr(svc, "MAX_COMPARE_RESPONSE_BYTES", 8 * 1024)  # 8 KB
    monkeypatch.setattr(svc, "COMPARE_ENVELOPE_BYTES", 512)

    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    assert r["statusCode"] == 200
    b = _body(r)
    assert b.get("truncated") is True
    assert b["truncatedReason"] == "response_too_large"
    assert 0 < b["truncatedIncluded"] < 20
    assert b["truncatedOmitted"] == 20 - b["truncatedIncluded"]
    assert len(r["body"].encode("utf-8")) <= 8 * 1024 + 2048  # small headroom for envelope


def test_truncation_stops_starting_new_dynamodb_queries(env, monkeypatch):
    """After truncation is triggered in a batch, subsequent batches must not
    issue any further DynamoDB Query calls."""
    from read_api import service as svc

    _setup(env, num_posts=25, snaps_per_post=5)  # more than one batch of 10

    monkeypatch.setattr(svc, "MAX_COMPARE_RESPONSE_BYTES", 2 * 1024)
    monkeypatch.setattr(svc, "COMPARE_ENVELOPE_BYTES", 256)

    query_count = {"n": 0}
    orig_query = env.meta.client.query

    def spy_query(**kwargs):
        query_count["n"] += 1
        return orig_query(**kwargs)

    env.meta.client.query = spy_query

    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    b = _body(r)
    assert b.get("truncated") is True
    # We should have queried far fewer than 25 posts. Batching + early-abort
    # keeps this at most 1 full batch (10) plus the entry list GSI query.
    # Allow a generous ceiling to keep the test stable across moto internals.
    assert query_count["n"] <= 15, f"issued {query_count['n']} queries — too many"
    # And strictly fewer than the naive N+1 (25 + 1 = 26)
    assert query_count["n"] < 26


def test_no_truncation_when_all_fits(env):
    """The `truncated` field is omitted (or false) when everything fits."""
    _setup(env, num_posts=3, snaps_per_post=5)
    r = _call("/api/compare", {"range": "all", "scope": "all"})
    b = _body(r)
    assert b["totalEntries"] == 3
    assert len(b["series"]) == 3
    assert not b.get("truncated", False)


def test_truncated_response_preserves_priority_order(env, monkeypatch):
    """The most important entries (by latest metric) must appear even when
    the response is truncated."""
    from read_api import service as svc

    _setup(env, num_posts=15, snaps_per_post=10)
    monkeypatch.setattr(svc, "MAX_COMPARE_RESPONSE_BYTES", 6 * 1024)
    monkeypatch.setattr(svc, "COMPARE_ENVELOPE_BYTES", 256)

    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    b = _body(r)
    assert b.get("truncated") is True
    assert any(s["postId"] == "P000" for s in b["series"])
    ids = [s["postId"] for s in b["series"]]
    assert ids == sorted(ids)  # since P000 < P001 lex-wise, and priority = numeric asc
