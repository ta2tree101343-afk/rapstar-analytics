"""Integration test for the Lambda handler using moto for DynamoDB/SSM.

The Instagram Graph API and CloudWatch calls are stubbed via monkeypatch.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws


TABLES = {
    "posts": [("external_post_id", "S")],
    "snapshots": [("external_post_id", "S"), ("fetched_at", "S")],
    "fetch_runs": [("run_id", "S")],
    "token_audit": [("partition", "S"), ("recorded_at", "S")],
    "lock": [("name", "S")],
}


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        for name, keys in TABLES.items():
            ks = [{"AttributeName": k, "KeyType": "HASH" if i == 0 else "RANGE"} for i, (k, _) in enumerate(keys)]
            attrs = [{"AttributeName": k, "AttributeType": t} for k, t in keys]
            ddb.create_table(TableName=name, KeySchema=ks, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")

        monkeypatch.setenv("IG_BUSINESS_ACCOUNT_ID", "99999999999999999")
        monkeypatch.setenv("TARGET_IG_USERNAME", "rapstar_starz")
        monkeypatch.setenv("GRAPH_API_VERSION", "v26.0")
        monkeypatch.setenv("POSTS_TABLE", "posts")
        monkeypatch.setenv("SNAPSHOTS_TABLE", "snapshots")
        monkeypatch.setenv("FETCH_RUNS_TABLE", "fetch_runs")
        monkeypatch.setenv("TOKEN_AUDIT_TABLE", "token_audit")
        monkeypatch.setenv("LOCK_TABLE", "lock")
        monkeypatch.setenv("IG_TOKEN_PARAM", "/rapstar/token")
        monkeypatch.setenv("META_APP_SECRET_PARAM", "/rapstar/app-secret")
        monkeypatch.setenv("META_APP_ID_PARAM", "/rapstar/app-id")
        monkeypatch.setenv("COLLECT_MODE", "both")

        ssm = boto3.client("ssm", region_name="ap-northeast-1")
        ssm.put_parameter(Name="/rapstar/token", Value="EAA-fake-token", Type="SecureString")
        ssm.put_parameter(Name="/rapstar/app-secret", Value="fake-secret", Type="SecureString")
        ssm.put_parameter(Name="/rapstar/app-id", Value="1234567890", Type="String")

        yield ddb


SAMPLE_ITEMS = [
    {
        "id": "MED1",
        "caption": "imag1ne / 22 / 東京\nRAPSTAR 2026\n#RAPSTAR2026",
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": "https://instagram.com/reel/DDDDD",
        "timestamp": "2026-09-15T12:34:56+0000",
        "view_count": 163499,
        "like_count": 2713,
        "comments_count": 18,
    },
    {
        "id": "MED2",
        "caption": "Kee Rooz / 25 / 大阪\n#RAPSTAR2026",
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": "https://instagram.com/reel/EEEEE",
        "timestamp": "2026-09-14T10:00:00+0000",
        # view_count intentionally missing to test NULL behavior
        "like_count": 15083,
        "comments_count": 98,
    },
]


def test_handler_writes_posts_and_snapshots(aws, monkeypatch):
    from collector.aws import handler as h

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            for x in SAMPLE_ITEMS:
                yield x

    from collector.token_manager import DebugResult
    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", lambda *a, **kw: DebugResult(
        is_valid=True, token_type="long_lived",
        issued_at=datetime.now(timezone.utc), expires_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
        data_access_expires_at=None, scopes=["instagram_basic"], raw={},
    ))
    monkeypatch.setattr(h, "_emit_token_metric", lambda days: None)

    result = h.lambda_handler({}, None)
    assert result["status"] == "success"
    assert result["posts_seen"] == 2
    assert result["new_posts"] == 2
    assert result["snapshots_written"] == 2

    posts_table = aws.Table("posts")
    p1 = posts_table.get_item(Key={"external_post_id": "MED1"})["Item"]
    assert p1["classification"] == "entry"
    assert int(p1["latest_view_count"]) == 163499
    assert int(p1["latest_like_count"]) == 2713

    p2 = posts_table.get_item(Key={"external_post_id": "MED2"})["Item"]
    assert "latest_view_count" not in p2  # NULL preserved as missing
    assert int(p2["latest_like_count"]) == 15083


def test_handler_second_run_appends_snapshot_no_new_post(aws, monkeypatch):
    from collector.aws import handler as h

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            for x in SAMPLE_ITEMS:
                yield x

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", lambda *a, **kw: (_ for _ in ()).throw(Exception("skip")))
    monkeypatch.setattr(h, "_emit_token_metric", lambda days: None)

    h.lambda_handler({}, None)  # first
    result = h.lambda_handler({}, None)  # second
    assert result["new_posts"] == 0
    assert result["snapshots_written"] == 2

    snaps = aws.Table("snapshots").scan()["Items"]
    assert len(snaps) == 4


def test_handler_skipped_when_lock_held(aws, monkeypatch):
    from collector.aws import handler as h
    from collector.repositories.dynamodb_impl import DynamoDBLockRepository

    lock = DynamoDBLockRepository(aws.Table("lock"))
    assert lock.try_acquire("someone-else", ttl_seconds=600)

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 0
        def iter_media(self, max_items=None):
            return iter([])

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    result = h.lambda_handler({}, None)
    assert result == {"status": "skipped_locked"}


# -------- EMF application metrics --------
#
# These tests capture `print` output (where _emit_run_metrics writes its EMF
# JSON line), parse it, and assert that:
#   - metric flags (CollectorRunSuccess/Partial/Failure/MetaApiFailure) are 0/1
#     per run outcome
#   - Dimensions list contains ONLY FunctionName + Environment (no runId,
#     postId, error-message etc.)
#   - SnapshotsWritten mirrors the actual summary value
#   - runId appears as a plain log field, not a dimension
import json
import re
from collector.token_manager import DebugResult as _DebugResult


def _emf_from_captured(captured_out: str) -> dict:
    """Pick out the single EMF JSON line that lambda_handler prints."""
    for line in captured_out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_aws" in obj and "CloudWatchMetrics" in obj.get("_aws", {}):
            return obj
    raise AssertionError(f"no EMF line found in: {captured_out!r}")


def _ok_debug_token(*a, **kw):
    return _DebugResult(
        is_valid=True, token_type="long_lived",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
        data_access_expires_at=None, scopes=["instagram_basic"], raw={},
    )


def _stub_token_metric(_days):
    return None


def test_emf_success_run(aws, monkeypatch, capsys):
    from collector.aws import handler as h

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            for x in SAMPLE_ITEMS:
                yield x

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", _ok_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    result = h.lambda_handler({}, None)
    assert result["status"] == "success"

    emf = _emf_from_captured(capsys.readouterr().out)
    assert emf["CollectorRunSuccess"] == 1
    assert emf["CollectorRunPartial"] == 0
    assert emf["CollectorRunFailure"] == 0
    assert emf["MetaApiFailure"] == 0
    assert emf["SnapshotsWritten"] == result["snapshots_written"] == 2


def test_emf_partial_when_single_item_fails(aws, monkeypatch, capsys):
    from collector.aws import handler as h

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            for x in SAMPLE_ITEMS:
                yield x

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", _ok_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    real_persist = h._persist
    call_count = {"n": 0}

    def flaky_persist(repos, item, fetched_at, mode):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom (test-only per-item failure)")
        return real_persist(repos, item, fetched_at, mode)

    monkeypatch.setattr(h, "_persist", flaky_persist)

    result = h.lambda_handler({}, None)
    assert result["status"] == "partial"

    emf = _emf_from_captured(capsys.readouterr().out)
    assert emf["CollectorRunPartial"] == 1
    assert emf["CollectorRunSuccess"] == 0
    assert emf["CollectorRunFailure"] == 0
    assert emf["MetaApiFailure"] == 0


def test_emf_failure_from_instagram_api_error(aws, monkeypatch, capsys):
    from collector.aws import handler as h
    from collector.ig_client import InstagramAPIError

    class ApiBlockedClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            raise InstagramAPIError(
                "Graph API エラー: status=400 body={...}"
            )

    monkeypatch.setattr(h, "BusinessDiscoveryClient", ApiBlockedClient)
    monkeypatch.setattr(h, "call_debug_token", _ok_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    result = h.lambda_handler({}, None)
    assert result["status"] == "error"

    emf = _emf_from_captured(capsys.readouterr().out)
    assert emf["CollectorRunFailure"] == 1
    assert emf["MetaApiFailure"] == 1
    assert emf["CollectorRunSuccess"] == 0
    assert emf["CollectorRunPartial"] == 0


def test_emf_failure_from_generic_exception_does_not_flag_meta(aws, monkeypatch, capsys):
    from collector.aws import handler as h

    class BrokenClient:
        def __init__(self, *a, **kw):
            self.api_calls = 0
        def iter_media(self, max_items=None):
            raise RuntimeError("some non-Meta runtime failure")

    monkeypatch.setattr(h, "BusinessDiscoveryClient", BrokenClient)
    monkeypatch.setattr(h, "call_debug_token", _ok_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    result = h.lambda_handler({}, None)
    assert result["status"] == "error"

    emf = _emf_from_captured(capsys.readouterr().out)
    assert emf["CollectorRunFailure"] == 1
    # Not a Meta API error — must NOT flip MetaApiFailure.
    assert emf["MetaApiFailure"] == 0


def test_emf_token_debug_failure_but_main_success_is_still_success(aws, monkeypatch, capsys):
    from collector.aws import handler as h
    from collector.token_manager import TokenManagerError

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            for x in SAMPLE_ITEMS:
                yield x

    def broken_debug_token(*a, **kw):
        raise TokenManagerError("debug_token error status=400: {\"error\":{...}}")

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", broken_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    result = h.lambda_handler({}, None)
    # Main collection succeeded so the run is Success — the earlier token
    # debug failure must NOT flip MetaApiFailure or CollectorRunFailure.
    assert result["status"] == "success"

    emf = _emf_from_captured(capsys.readouterr().out)
    assert emf["CollectorRunSuccess"] == 1
    assert emf["MetaApiFailure"] == 0


def test_emf_dimensions_exclude_high_cardinality_fields(aws, monkeypatch, capsys):
    from collector.aws import handler as h

    class FakeClient:
        def __init__(self, *a, **kw):
            self.api_calls = 1
        def iter_media(self, max_items=None):
            yield from SAMPLE_ITEMS

    monkeypatch.setattr(h, "BusinessDiscoveryClient", FakeClient)
    monkeypatch.setattr(h, "call_debug_token", _ok_debug_token)
    monkeypatch.setattr(h, "_emit_token_metric", _stub_token_metric)

    h.lambda_handler({}, None)
    emf = _emf_from_captured(capsys.readouterr().out)

    # Exactly one dimension set, exactly these two keys, in this order.
    dim_sets = emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
    assert dim_sets == [["FunctionName", "Environment"]]
    # And neither runId, postId, status, nor error-message leaks in there.
    for banned in ("runId", "postId", "status", "errorMessage"):
        assert banned not in dim_sets[0]

    # But runId SHOULD be present as a plain log field (searchable in Logs
    # Insights, no CloudWatch Metrics cost).
    assert "runId" in emf
    assert re.fullmatch(r"[0-9a-f-]{36}", emf["runId"]), "runId must be a plain UUID string"
