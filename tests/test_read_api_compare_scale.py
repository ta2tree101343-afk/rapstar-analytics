"""Verify /api/compare behaves correctly at scale:

1. DynamoDB Query cost is bounded by max_items via the `Limit` parameter.
2. When total point budget is exceeded, the response is truncated with an
   explicit flag rather than dropped or a 5xx error.
3. Truncation drops the least-popular entries first, keeping the most
   important series in the response.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _setup(dynamodb):
    from tests.test_read_api import TABLES, _create, _put_post, _put_snap
    for name, spec in TABLES.items():
        _create(dynamodb, name, spec)
    posts = dynamodb.Table("posts")
    snapshots = dynamodb.Table("snapshots")
    # Create 5 entries, each with 20 snapshots. total = 100 points, well
    # under the real MAX_TOTAL_HISTORY_POINTS (50k). We monkeypatch the limit
    # per-test to force truncation.
    for i in range(5):
        pid = f"P{i}"
        views = 10_000 - i * 1000  # P0 has highest views, P4 lowest
        _put_post(posts, pid=pid, name=f"R{i}", hours_ago_posted=30 * 24,
                  latest_view=views, latest_like=100 + i, latest_comments=10 + i,
                  latest_fetched_hours_ago=0)
        for h in range(20):
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
        _setup(ddb)
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


def test_query_limit_pushdown_prevents_overread(env):
    """When max_items is set, DynamoDB Query is called with Limit and stops
    reading once the cap is reached."""
    from read_api import service as svc

    seen_limits: list = []

    class SpyTable:
        def __init__(self, inner):
            self._inner = inner

        def query(self, **kwargs):
            seen_limits.append(kwargs.get("Limit"))
            return self._inner.query(**kwargs)

    spy = SpyTable(env.Table("snapshots"))
    got = svc.query_snapshots(spy, "P0", ascending=True, max_items=5)
    assert len(got) == 5
    assert seen_limits, "no query calls observed"
    for lim in seen_limits:
        assert lim is not None
        assert lim <= 5


def test_compare_truncates_when_budget_exceeded(env, monkeypatch):
    """Force MAX_TOTAL_HISTORY_POINTS low to trigger truncation, then verify
    the response is partial with explicit flags rather than an error."""
    from read_api import service as svc

    # 5 posts × 20 points each = 100 points; cap at 45 → keep 2 posts (40 points).
    monkeypatch.setattr(svc, "MAX_TOTAL_HISTORY_POINTS", 45)

    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    assert r["statusCode"] == 200, r
    b = _body(r)
    assert b.get("truncated") is True
    assert b["truncatedReason"] == "response_too_large"
    assert b["truncatedIncluded"] == 2
    assert b["truncatedOmitted"] == 3
    kept_ids = {s["postId"] for s in b["series"]}
    assert kept_ids == {"P0", "P1"}
    assert b["totalEntries"] == 5


def test_compare_untruncated_when_budget_ample(env):
    """No truncation when budget covers everything."""
    r = _call("/api/compare", {"range": "all", "scope": "all", "metric": "viewCount"})
    b = _body(r)
    assert "truncated" not in b or b["truncated"] is False
    assert len(b["series"]) == 5


def test_compare_parallel_fetch_returns_series_in_priority_order(env):
    """Even though parallel workers finish in arbitrary order, the final
    series list is emitted in priority order (highest metric first for
    scope=all)."""
    r = _call("/api/compare", {"range": "24h", "scope": "all", "metric": "viewCount"})
    b = _body(r)
    ids = [s["postId"] for s in b["series"]]
    assert ids == ["P0", "P1", "P2", "P3", "P4"]


def test_compare_selected_preserves_caller_order(env):
    """When the caller supplies specific ids, we respect their order rather
    than re-sorting by metric."""
    r = _call("/api/compare", {"range": "24h", "scope": "selected", "ids": "P3,P0,P2"})
    b = _body(r)
    ids = [s["postId"] for s in b["series"]]
    assert ids == ["P3", "P0", "P2"]
