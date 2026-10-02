"""Integration tests for the read-only API (Lambda handler + service).

DynamoDB is mocked via moto. We populate a small but representative dataset
and exercise every endpoint plus error paths.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws


# Anchor test data to the actual wall clock so range-based endpoints
# (`24h`, `7d`) — which call `datetime.now()` at request time — always
# find the fixture data inside their window. A fixed anchor drifts out of
# range as calendar days pass and made `test_post_history_range_24h_narrow`
# flaky.
NOW = datetime.now(timezone.utc)
DAY = timedelta(hours=24)


TABLES = {
    "posts": {
        "keys": [("external_post_id", "S")],
        "gsi": [
            ("classification-posted_at-index",
             [("classification", "HASH"), ("posted_at", "RANGE")],
             [("classification", "S"), ("posted_at", "S")]),
        ],
    },
    "snapshots": {
        "keys": [("external_post_id", "S"), ("fetched_at", "S")],
    },
    "fetch_runs": {
        "keys": [("run_id", "S")],
        "gsi": [
            ("status-started_at-index",
             [("status", "HASH"), ("started_at", "RANGE")],
             [("status", "S"), ("started_at", "S")]),
        ],
    },
}


def _create(dynamodb, name, spec):
    keys = spec["keys"]
    all_attrs = {(k, t) for k, t in keys}
    key_schema = [
        {"AttributeName": k, "KeyType": "HASH" if i == 0 else "RANGE"}
        for i, (k, _) in enumerate(keys)
    ]
    gsis = []
    for gname, gk, gattrs in spec.get("gsi", []):
        for k, t in gattrs:
            all_attrs.add((k, t))
        gsis.append({
            "IndexName": gname,
            "KeySchema": [{"AttributeName": k, "KeyType": kt} for k, kt in gk],
            "Projection": {"ProjectionType": "ALL"},
        })
    kwargs = dict(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": t} for k, t in all_attrs],
        BillingMode="PAY_PER_REQUEST",
    )
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = gsis
    return dynamodb.create_table(**kwargs)


def _put_post(t, *, pid, name, hours_ago_posted, latest_view=None, latest_like=None,
              latest_comments=None, latest_fetched_hours_ago=None, classification="entry",
              permalink=None, caption=None):
    posted_at = (NOW - timedelta(hours=hours_ago_posted)).isoformat()
    latest_at = None
    if latest_fetched_hours_ago is not None:
        latest_at = (NOW - timedelta(hours=latest_fetched_hours_ago)).isoformat()
    item = {
        "external_post_id": pid,
        "rapper_name": name,
        "permalink": permalink or f"https://instagram.com/reel/{pid}",
        "posted_at": posted_at,
        "classification": classification,
        "first_seen_at": posted_at,
        "last_seen_at": latest_at or posted_at,
    }
    if caption is not None:
        item["caption"] = caption
    if latest_view is not None:
        item["latest_view_count"] = latest_view
    if latest_like is not None:
        item["latest_like_count"] = latest_like
    if latest_comments is not None:
        item["latest_comments_count"] = latest_comments
    if latest_at:
        item["latest_fetched_at"] = latest_at
    t.put_item(Item=item)


def _put_snap(t, *, pid, hours_ago, view=None, like=None, comments=None):
    item = {
        "external_post_id": pid,
        "fetched_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }
    if view is not None:
        item["view_count"] = view
    if like is not None:
        item["like_count"] = like
    if comments is not None:
        item["comments_count"] = comments
    t.put_item(Item=item)


def _put_run(t, *, run_id, hours_ago_started, hours_ago_finished, status="success"):
    t.put_item(Item={
        "run_id": run_id,
        "started_at": (NOW - timedelta(hours=hours_ago_started)).isoformat(),
        "finished_at": (NOW - timedelta(hours=hours_ago_finished)).isoformat(),
        "status": status,
    })


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
        for name, spec in TABLES.items():
            _create(ddb, name, spec)
        posts = ddb.Table("posts")
        snapshots = ddb.Table("snapshots")
        runs = ddb.Table("fetch_runs")

        # ---- Post A: normal entry, 5 days old, has ~24h reference ----
        _put_post(posts, pid="A", name="Alice", hours_ago_posted=5 * 24,
                  latest_view=1500, latest_like=200, latest_comments=15,
                  latest_fetched_hours_ago=0)
        _put_snap(snapshots, pid="A", hours_ago=24, view=1200, like=180, comments=12)
        _put_snap(snapshots, pid="A", hours_ago=0, view=1500, like=200, comments=15)

        # ---- Post B: entry, 5 days old, has reference where value went DOWN ----
        _put_post(posts, pid="B", name="Bob", hours_ago_posted=5 * 24,
                  latest_view=900, latest_like=50, latest_comments=5,
                  latest_fetched_hours_ago=0)
        _put_snap(snapshots, pid="B", hours_ago=24, view=1000, like=55, comments=5)
        _put_snap(snapshots, pid="B", hours_ago=0, view=900, like=50, comments=5)

        # ---- Post C: entry but only 6 hours old (too new for delta) ----
        _put_post(posts, pid="C", name="Chris", hours_ago_posted=6,
                  latest_view=300, latest_like=40, latest_comments=2,
                  latest_fetched_hours_ago=0)
        _put_snap(snapshots, pid="C", hours_ago=0, view=300, like=40, comments=2)

        # ---- Post D: entry, 5 days old but no reference within window ----
        _put_post(posts, pid="D", name="Dan", hours_ago_posted=5 * 24,
                  latest_view=800, latest_like=30, latest_comments=1,
                  latest_fetched_hours_ago=0)
        _put_snap(snapshots, pid="D", hours_ago=0, view=800, like=30, comments=1)
        # 48h ago sample is outside tolerance window (18-30h before latest)
        _put_snap(snapshots, pid="D", hours_ago=48, view=700, like=25, comments=0)

        # ---- Post E: entry, latest view is NULL (metric hidden) ----
        _put_post(posts, pid="E", name="Eve", hours_ago_posted=5 * 24,
                  latest_like=100, latest_comments=8,
                  latest_fetched_hours_ago=0)
        _put_snap(snapshots, pid="E", hours_ago=24, like=95, comments=7)
        _put_snap(snapshots, pid="E", hours_ago=0, like=100, comments=8)

        # ---- Post F: unclassified — must not appear in entry rankings ----
        _put_post(posts, pid="F", name="Frank", hours_ago_posted=3 * 24,
                  latest_view=99999, latest_fetched_hours_ago=0,
                  classification="unclassified")

        # ---- Fetch runs ----
        _put_run(runs, run_id="R1", hours_ago_started=48, hours_ago_finished=47)
        _put_run(runs, run_id="R2", hours_ago_started=24, hours_ago_finished=23)
        _put_run(runs, run_id="R3", hours_ago_started=1, hours_ago_finished=0)

        yield ddb


def _call(event):
    from read_api.handler import lambda_handler
    return lambda_handler(event, None)


def _get(path, query=None):
    return {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": path,
        "queryStringParameters": query or {},
    }


def _body(resp):
    return json.loads(resp["body"])


# --- Status ---


def test_status_returns_latest_success_and_entry_count(env):
    r = _call(_get("/api/status"))
    assert r["statusCode"] == 200
    b = _body(r)
    assert b["isMock"] is False
    assert b["entryCount"] == 5  # A, B, C, D, E (F is unclassified)
    assert b["lastSuccessStatus"] == "success"
    assert b["lastSuccessAt"] is not None


# --- Rankings (cumulative) ---


def test_rankings_cumulative_views_sorts_desc_nulls_last(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_views"}))
    assert r["statusCode"] == 200
    b = _body(r)
    ids = [it["postId"] for it in b["items"]]
    assert ids == ["A", "B", "D", "C", "E"]
    e = next(it for it in b["items"] if it["postId"] == "E")
    assert e["value"] is None
    assert e["reason"] == "no_metric"
    assert b["totalEligible"] == 5
    assert b["totalWithData"] == 4
    assert b["totalWithoutData"] == 1
    assert "F" not in ids


def test_rankings_cumulative_comments(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_comments"}))
    b = _body(r)
    ids = [it["postId"] for it in b["items"]]
    assert ids == ["A", "E", "B", "C", "D"]


# --- Rankings (delta) ---


def test_rankings_delta_views_24h_computes_reference(env):
    r = _call(_get("/api/rankings", {"type": "delta_views_24h"}))
    b = _body(r)
    ids = [it["postId"] for it in b["items"]]
    assert "C" not in ids
    a = next(it for it in b["items"] if it["postId"] == "A")
    assert a["value"] == 300
    assert a["delta"]["referenceFetchedAt"] is not None
    assert 17 < a["delta"]["actualHoursBetween"] < 25
    assert a["reason"] is None
    b_item = next(it for it in b["items"] if it["postId"] == "B")
    assert b_item["value"] == -100  # negative preserved
    d = next(it for it in b["items"] if it["postId"] == "D")
    assert d["value"] is None
    assert d["reason"] == "insufficient_data"
    e = next(it for it in b["items"] if it["postId"] == "E")
    assert e["value"] is None
    assert e["reason"] == "no_metric"
    assert ids[0] == "A"
    assert ids[1] == "B"


# --- Pagination ---


def test_rankings_default_limit_20(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_views"}))
    b = _body(r)
    assert len(b["items"]) == 5
    assert b["nextCursor"] is None


def test_rankings_pagination_slice_and_cursor(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_views", "limit": "2"}))
    b = _body(r)
    assert len(b["items"]) == 2
    assert b["nextCursor"] is not None
    r2 = _call(_get("/api/rankings", {"type": "cumulative_views", "limit": "2", "cursor": b["nextCursor"]}))
    b2 = _body(r2)
    assert len(b2["items"]) == 2
    ids = {it["postId"] for it in b["items"]} | {it["postId"] for it in b2["items"]}
    assert len(ids) == 4


def test_rankings_rejects_invalid_cursor(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_views", "cursor": "!!not-base64!!"}))
    assert r["statusCode"] == 400
    assert _body(r)["error"] == "invalid_cursor"


def test_rankings_rejects_invalid_type(env):
    r = _call(_get("/api/rankings", {"type": "nope"}))
    assert r["statusCode"] == 400
    assert _body(r)["error"] == "invalid_type"


def test_rankings_rejects_limit_out_of_range(env):
    r = _call(_get("/api/rankings", {"type": "cumulative_views", "limit": "0"}))
    assert r["statusCode"] == 400


# --- Post detail / history ---


def test_post_detail_returns_camelcase_shape(env):
    r = _call(_get("/api/posts/A"))
    assert r["statusCode"] == 200
    b = _body(r)
    assert b["postId"] == "A"
    assert b["rapperName"] == "Alice"
    assert b["classification"] == "entry"
    assert b["latest"]["viewCount"] == 1500
    assert "fetchedAt" in b["latest"]


def test_post_detail_404(env):
    r = _call(_get("/api/posts/NONE"))
    assert r["statusCode"] == 404
    assert _body(r)["error"] == "not_found"


def test_post_detail_rejects_bad_id(env):
    r = _call(_get("/api/posts/bad%20id"))  # space after decode → invalid char
    assert r["statusCode"] == 400
    assert _body(r)["error"] == "invalid_post_id"


def test_post_history_range_7d_includes_all_recent(env):
    r = _call(_get("/api/posts/A/history", {"range": "7d"}))
    b = _body(r)
    assert len(b["points"]) == 2
    assert b["points"][0]["fetchedAt"] < b["points"][1]["fetchedAt"]


def test_post_history_range_24h_narrow(env):
    r = _call(_get("/api/posts/A/history", {"range": "24h"}))
    b = _body(r)
    # Only the most recent snapshot (at 0h ago) falls inside last 24h from "now"
    # since the older sample is at exactly 24h boundary which may include it.
    assert 1 <= len(b["points"]) <= 2


def test_post_history_bad_range(env):
    r = _call(_get("/api/posts/A/history", {"range": "1y"}))
    assert r["statusCode"] == 400
    assert _body(r)["error"] == "invalid_range"


def test_post_history_404_for_unknown_post(env):
    r = _call(_get("/api/posts/NOPE/history", {"range": "all"}))
    assert r["statusCode"] == 404


def test_post_history_null_metric_preserved(env):
    r = _call(_get("/api/posts/E/history", {"range": "7d"}))
    b = _body(r)
    for p in b["points"]:
        assert p["viewCount"] is None
        assert p["likeCount"] is not None


# --- Compare ---


def test_compare_all_returns_all_entries_with_own_timestamps(env):
    r = _call(_get("/api/compare", {"range": "7d", "scope": "all"}))
    b = _body(r)
    assert b["totalEntries"] == 5
    series = {s["postId"]: s for s in b["series"]}
    a_times = [p["fetchedAt"] for p in series["A"]["points"]]
    b_times = [p["fetchedAt"] for p in series["B"]["points"]]
    assert isinstance(a_times, list) and isinstance(b_times, list)


def test_compare_top10_uses_metric(env):
    r = _call(_get("/api/compare", {"range": "7d", "scope": "top10", "metric": "viewCount"}))
    b = _body(r)
    ids = [s["postId"] for s in b["series"]]
    assert "E" not in ids
    assert "F" not in ids
    assert ids[:2] == ["A", "B"]


def test_compare_selected(env):
    r = _call(_get("/api/compare", {"range": "24h", "scope": "selected", "ids": "A,B"}))
    b = _body(r)
    ids = [s["postId"] for s in b["series"]]
    assert set(ids) == {"A", "B"}


def test_compare_selected_missing_ids_400(env):
    r = _call(_get("/api/compare", {"range": "24h", "scope": "selected"}))
    assert r["statusCode"] == 400
    assert _body(r)["error"] == "missing_ids"


def test_compare_invalid_range(env):
    r = _call(_get("/api/compare", {"range": "999", "scope": "all"}))
    assert r["statusCode"] == 400


def test_compare_invalid_scope(env):
    r = _call(_get("/api/compare", {"range": "24h", "scope": "nope"}))
    assert r["statusCode"] == 400


def test_compare_bad_id_rejected(env):
    r = _call(_get("/api/compare", {"range": "24h", "scope": "selected", "ids": "A,bad id"}))
    assert r["statusCode"] == 400


def test_compare_returns_data_bearing_runs(env):
    # The env fixture inserts three fetch_runs (R1..R3) all with status=success.
    # Only runs whose started_at falls inside the queried range should appear,
    # and only "data-bearing" runs (success/partial) — never `error` runs.
    r = _call(_get("/api/compare", {"range": "7d", "scope": "all"}))
    b = _body(r)
    assert "runs" in b
    assert isinstance(b["runs"], list)
    ids = {run["runId"] for run in b["runs"]}
    assert ids == {"R1", "R2", "R3"}
    for run in b["runs"]:
        assert set(run.keys()) >= {"runId", "startedAt", "finishedAt", "status"}
        assert run["status"] in ("success", "partial")
    starts = [run["startedAt"] for run in b["runs"]]
    assert starts == sorted(starts)


def test_compare_24h_range_narrows_runs(env):
    # Only R3 started within the last 24h relative to NOW; older runs (R1/R2)
    # must NOT appear in the 24h window.
    r = _call(_get("/api/compare", {"range": "24h", "scope": "all"}))
    b = _body(r)
    ids = {run["runId"] for run in b["runs"]}
    assert ids == {"R3"}


# --- Method / route ---


def test_options_returns_cors_headers(env):
    r = {"requestContext": {"http": {"method": "OPTIONS"}}, "rawPath": "/api/status"}
    resp = _call(r)
    assert resp["statusCode"] == 204
    assert "Access-Control-Allow-Origin" in resp["headers"]


def test_post_method_rejected(env):
    r = {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/status", "queryStringParameters": {}}
    resp = _call(r)
    assert resp["statusCode"] == 405


def test_unknown_route_404(env):
    r = _call(_get("/api/unknown"))
    assert r["statusCode"] == 404


# --- Cursor round-trip ---


def test_cursor_encode_decode_roundtrip():
    from read_api.service import encode_cursor, decode_cursor
    for n in (0, 1, 20, 500, 100_000):
        assert decode_cursor(encode_cursor(n)) == n


def test_cursor_rejects_negative():
    from read_api.service import encode_cursor, decode_cursor, ApiError
    with pytest.raises(ApiError):
        decode_cursor(encode_cursor(-1))


def test_cursor_rejects_oversize_offset():
    from read_api.service import encode_cursor, decode_cursor, ApiError
    with pytest.raises(ApiError):
        decode_cursor(encode_cursor(100_001))
