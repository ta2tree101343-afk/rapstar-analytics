from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from collector.repositories.base import (
    FetchRunRecord,
    PostRecord,
    SnapshotRecord,
    TokenAuditRecord,
)
from collector.repositories.dynamodb_impl import (
    DynamoDBFetchRunRepository,
    DynamoDBLockRepository,
    DynamoDBPostRepository,
    DynamoDBSnapshotRepository,
    DynamoDBTokenAuditRepository,
)


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "ap-northeast-1"


@pytest.fixture
def ddb(aws_credentials):
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="ap-northeast-1")
        _make_table(client, "posts", [("external_post_id", "S")])
        _make_table(client, "snapshots", [("external_post_id", "S"), ("fetched_at", "S")])
        _make_table(client, "fetch_runs", [("run_id", "S")])
        _make_table(client, "token_audit", [("partition", "S"), ("recorded_at", "S")])
        _make_table(client, "lock", [("name", "S")])
        yield client


def _make_table(client, name, keys):
    key_schema = [{"AttributeName": k, "KeyType": "HASH" if i == 0 else "RANGE"} for i, (k, _) in enumerate(keys)]
    attrs = [{"AttributeName": k, "AttributeType": t} for k, t in keys]
    client.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attrs,
        BillingMode="PAY_PER_REQUEST",
    )


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _sample_post(mid="M1", **overrides):
    base = dict(
        external_post_id=mid,
        rapper_name="imag1ne",
        permalink=f"https://instagram.com/p/{mid}",
        posted_at=NOW,
        caption="#RAPSTAR2026",
        media_type="VIDEO",
        media_product_type="REELS",
        classification="entry",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    base.update(overrides)
    return PostRecord(**base)


def test_post_upsert_and_get_roundtrip(ddb):
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    was_new = repo.upsert(_sample_post())
    assert was_new is True
    got = repo.get("M1")
    assert got is not None
    assert got.external_post_id == "M1"
    assert got.classification == "entry"
    assert got.posted_at.tzinfo is not None


def test_post_upsert_second_time_returns_not_new(ddb):
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    repo.upsert(_sample_post())
    was_new = repo.upsert(_sample_post())
    assert was_new is False


def test_post_null_metrics_omitted_not_zero(ddb):
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    # A post with no latest_* attributes.
    repo.upsert(_sample_post())
    raw = ddb.Table("posts").get_item(Key={"external_post_id": "M1"})["Item"]
    assert "latest_view_count" not in raw
    assert "latest_like_count" not in raw


def test_update_latest_metrics_removes_null_attributes(ddb):
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    repo.upsert(_sample_post(latest_view_count=100, latest_like_count=5))
    # Fetch with view_count=None (API omitted) → attribute must be REMOVEd.
    repo.update_latest_metrics(
        external_post_id="M1",
        fetched_at=NOW + timedelta(hours=1),
        view_count=None,
        like_count=6,
        comments_count=0,
    )
    raw = ddb.Table("posts").get_item(Key={"external_post_id": "M1"})["Item"]
    assert "latest_view_count" not in raw
    assert int(raw["latest_like_count"]) == 6
    assert int(raw["latest_comments_count"]) == 0


def test_snapshot_null_metric_omitted(ddb):
    repo = DynamoDBSnapshotRepository(ddb.Table("snapshots"))
    repo.append(SnapshotRecord(
        external_post_id="M1", fetched_at=NOW, view_count=None, like_count=1, comments_count=0,
    ))
    raw = ddb.Table("snapshots").get_item(
        Key={"external_post_id": "M1", "fetched_at": NOW.isoformat()}
    )["Item"]
    assert "view_count" not in raw
    assert int(raw["like_count"]) == 1
    assert int(raw["comments_count"]) == 0


def test_snapshot_reappend_same_key_is_idempotent(ddb):
    repo = DynamoDBSnapshotRepository(ddb.Table("snapshots"))
    for _ in range(3):
        repo.append(SnapshotRecord(
            external_post_id="M1", fetched_at=NOW, view_count=100, like_count=1, comments_count=0,
        ))
    snaps = list(repo.list_for_post("M1"))
    assert len(snaps) == 1
    assert snaps[0].view_count == 100


def test_snapshot_time_series_query_sorted(ddb):
    repo = DynamoDBSnapshotRepository(ddb.Table("snapshots"))
    for i, v in enumerate([100, 150, 200]):
        repo.append(SnapshotRecord(
            external_post_id="M1",
            fetched_at=NOW + timedelta(hours=i),
            view_count=v, like_count=1, comments_count=0,
        ))
    got = list(repo.list_for_post("M1"))
    assert [x.view_count for x in got] == [100, 150, 200]


def test_lock_acquire_release_reacquire(ddb):
    lock = DynamoDBLockRepository(ddb.Table("lock"))
    assert lock.try_acquire("holder-a", ttl_seconds=60) is True
    assert lock.try_acquire("holder-b", ttl_seconds=60) is False
    lock.release("holder-a")
    assert lock.try_acquire("holder-b", ttl_seconds=60) is True


def test_lock_expired_can_be_taken_over(ddb):
    lock = DynamoDBLockRepository(ddb.Table("lock"))
    assert lock.try_acquire("holder-a", ttl_seconds=0) is True
    # Immediately try to acquire — TTL is 0 so expires_at <= now → acquirable
    assert lock.try_acquire("holder-b", ttl_seconds=60) is True


def test_lock_release_by_wrong_holder_noop(ddb):
    lock = DynamoDBLockRepository(ddb.Table("lock"))
    lock.try_acquire("holder-a", ttl_seconds=60)
    lock.release("holder-x")  # should not raise
    # Confirm lock still held by holder-a
    assert lock.try_acquire("holder-b", ttl_seconds=60) is False


def test_token_audit_latest(ddb):
    repo = DynamoDBTokenAuditRepository(ddb.Table("token_audit"))
    for offset in (0, 1, 2):
        repo.record(TokenAuditRecord(
            recorded_at=NOW + timedelta(hours=offset),
            token_fingerprint=f"fp{offset}",
            token_type="long_lived",
            issued_at=NOW,
            expires_at=NOW + timedelta(days=60 - offset),
            data_access_expires_at=None,
            scopes="instagram_basic",
            source="check",
        ))
    latest = repo.latest()
    assert latest is not None
    assert latest.token_fingerprint == "fp2"


def test_fetch_run_start_and_finalize(ddb):
    repo = DynamoDBFetchRunRepository(ddb.Table("fetch_runs"))
    run_id = repo.start(NOW)
    assert isinstance(run_id, str) and len(run_id) > 0
    repo.finalize(FetchRunRecord(
        run_id=run_id, started_at=NOW, finished_at=NOW + timedelta(seconds=5),
        status="success", posts_seen=10, new_posts=2, snapshots_written=10,
        api_calls=1, error_message=None,
    ))
    item = ddb.Table("fetch_runs").get_item(Key={"run_id": run_id})["Item"]
    assert item["status"] == "success"
    assert int(item["posts_seen"]) == 10
    assert "error_message" not in item
