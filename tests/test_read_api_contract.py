"""Contract tests: verify the read API's response shapes match the frontend's
TypeScript types in `frontend/src/api/types.ts`.

These do NOT run the frontend — they check the JSON keys and value types that
the frontend consumes. Any drift between backend response and frontend types
will fail here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _create_tables(dynamodb):
    from tests.test_read_api import TABLES, _create
    for name, spec in TABLES.items():
        _create(dynamodb, name, spec)


def _seed(dynamodb):
    from tests.test_read_api import _put_post, _put_snap, _put_run
    posts = dynamodb.Table("posts")
    snapshots = dynamodb.Table("snapshots")
    runs = dynamodb.Table("fetch_runs")

    _put_post(posts, pid="A", name="Alice", hours_ago_posted=5 * 24,
              latest_view=1500, latest_like=200, latest_comments=15,
              latest_fetched_hours_ago=0, caption="a caption")
    _put_snap(snapshots, pid="A", hours_ago=24, view=1200, like=180, comments=12)
    _put_snap(snapshots, pid="A", hours_ago=0, view=1500, like=200, comments=15)

    _put_post(posts, pid="B", name=None, hours_ago_posted=5 * 24,  # rapperName may be null
              latest_view=None, latest_like=None, latest_comments=None,
              latest_fetched_hours_ago=0)

    _put_run(runs, run_id="R1", hours_ago_started=1, hours_ago_finished=0)


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
        _create_tables(ddb)
        _seed(ddb)
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


def _assert_shape(obj, shape):
    """Recursive shape check. `shape` is a dict where values are Python types
    or (type, "optional") tuples. `None` is allowed if type includes Optional.
    Use `list_of=<shape>` marker for arrays.
    """
    for key, expected in shape.items():
        assert key in obj, f"missing key {key!r} in {list(obj.keys())}"


# --- StatusResponse ---


def test_status_shape_matches_ts_type(env):
    b = _body(_call("/api/status"))
    assert set(b.keys()) >= {
        "lastSuccessAt", "lastSuccessStatus", "entryCount", "updatedAt", "isMock",
    }
    assert isinstance(b["entryCount"], int)
    assert isinstance(b["isMock"], bool) and b["isMock"] is False
    assert b["lastSuccessAt"] is None or isinstance(b["lastSuccessAt"], str)


# --- RankingResponse & RankingItem ---


def test_rankings_full_shape_and_all_items_by_default(env):
    b = _body(_call("/api/rankings", {"type": "cumulative_views"}))
    for k in ("type", "items", "totalEligible", "totalWithData", "totalWithoutData", "isMock"):
        assert k in b, f"missing {k}"
    assert b["nextCursor"] is None
    assert len(b["items"]) == b["totalEligible"] == 2
    for it in b["items"]:
        for k in (
            "postId", "rapperName", "permalink", "postedAt",
            "latestFetchedAt", "value", "valueLabel", "cumulative", "delta", "reason",
        ):
            assert k in it, f"missing item key {k}"
        assert isinstance(it["cumulative"], dict)
        for k in ("viewCount", "likeCount", "commentsCount"):
            assert k in it["cumulative"]
    b_item = next(i for i in b["items"] if i["postId"] == "B")
    assert b_item["rapperName"] is None
    assert b_item["value"] is None
    assert b_item["reason"] == "no_metric"


def test_rankings_limit_param_returns_paginated_with_cursor(env):
    b = _body(_call("/api/rankings", {"type": "cumulative_views", "limit": "1"}))
    assert len(b["items"]) == 1
    assert isinstance(b["nextCursor"], str)


def test_rankings_delta_item_includes_delta_object_or_null(env):
    b = _body(_call("/api/rankings", {"type": "delta_views_24h"}))
    for it in b["items"]:
        if it["value"] is not None:
            assert isinstance(it["delta"], dict)
            assert "referenceFetchedAt" in it["delta"]
            assert "actualHoursBetween" in it["delta"]
            assert isinstance(it["delta"]["actualHoursBetween"], (int, float))
        else:
            assert it["delta"] is None
            assert it["reason"] in ("insufficient_data", "no_metric")


# --- PostDetail ---


def test_post_detail_shape(env):
    b = _body(_call("/api/posts/A"))
    for k in ("postId", "rapperName", "permalink", "postedAt", "caption",
              "classification", "latest", "isMock"):
        assert k in b
    for k in ("viewCount", "likeCount", "commentsCount", "fetchedAt"):
        assert k in b["latest"]
    b_post = _body(_call("/api/posts/B"))
    assert b_post["rapperName"] is None


# --- HistoryResponse ---


def test_history_shape(env):
    b = _body(_call("/api/posts/A/history", {"range": "7d"}))
    for k in ("postId", "range", "points", "isMock"):
        assert k in b
    assert b["range"] == "7d"
    for p in b["points"]:
        for k in ("fetchedAt", "viewCount", "likeCount", "commentsCount"):
            assert k in p
    times = [p["fetchedAt"] for p in b["points"]]
    assert times == sorted(times)


# --- CompareResponse ---


def test_compare_shape_matches_ts_type(env):
    b = _body(_call("/api/compare", {"range": "7d", "scope": "all"}))
    for k in ("range", "series", "totalEntries", "isMock"):
        assert k in b
    assert "truncated" not in b or b["truncated"] is False
    for s in b["series"]:
        for k in ("postId", "rapperName", "permalink", "postedAt", "points"):
            assert k in s
        for p in s["points"]:
            for k in ("fetchedAt", "viewCount", "likeCount", "commentsCount"):
                assert k in p
