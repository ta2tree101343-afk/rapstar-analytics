"""Verify migrate_meta preserves latest_* attributes that were set by Lambda.

This guards the "migrate before Lambda" order but also the reverse (in case
someone re-runs migration after some cloud data has accumulated).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from collector.repositories.base import PostRecord
from collector.repositories.dynamodb_impl import DynamoDBPostRepository


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


@pytest.fixture
def ddb():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")
    with mock_aws():
        r = boto3.resource("dynamodb", region_name="ap-northeast-1")
        r.create_table(
            TableName="posts",
            KeySchema=[{"AttributeName": "external_post_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "external_post_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield r


def _meta_post(mid="M1"):
    return PostRecord(
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


def test_migrate_meta_preserves_lambda_latest_metrics(ddb):
    """Order: Lambda writes → migration runs → latest_* must survive."""
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    # Simulate a Lambda write that populated latest_*
    lambda_populated = PostRecord(
        external_post_id="M1", rapper_name="imag1ne",
        permalink="https://instagram.com/p/M1", posted_at=NOW,
        caption="#RAPSTAR2026", media_type="VIDEO", media_product_type="REELS",
        classification="entry", first_seen_at=NOW, last_seen_at=NOW + timedelta(hours=1),
        latest_view_count=163499, latest_like_count=2713, latest_comments_count=18,
        latest_fetched_at=NOW + timedelta(hours=1),
    )
    repo.upsert(lambda_populated)

    # Migration runs with SQLite-derived data (no latest_*)
    was_new = repo.migrate_meta(_meta_post("M1"))
    assert was_new is False  # already existed

    raw = ddb.Table("posts").get_item(Key={"external_post_id": "M1"})["Item"]
    # latest_* MUST still be present
    assert int(raw["latest_view_count"]) == 163499
    assert int(raw["latest_like_count"]) == 2713
    assert int(raw["latest_comments_count"]) == 18
    # metadata unchanged
    assert raw["classification"] == "entry"


def test_migrate_meta_creates_when_absent(ddb):
    """Order: migration first → new item created without latest_*."""
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    was_new = repo.migrate_meta(_meta_post("M2"))
    assert was_new is True
    raw = ddb.Table("posts").get_item(Key={"external_post_id": "M2"})["Item"]
    assert raw["external_post_id"] == "M2"
    assert raw["classification"] == "entry"
    assert "latest_view_count" not in raw
    assert "latest_like_count" not in raw


def test_migrate_meta_idempotent_second_run(ddb):
    """Re-running migration must not damage the item."""
    repo = DynamoDBPostRepository(ddb.Table("posts"))
    repo.migrate_meta(_meta_post("M3"))
    # Now imagine Lambda ran between migrations
    from collector.repositories.dynamodb_impl import DynamoDBPostRepository as _  # noqa
    repo.update_latest_metrics("M3", NOW, view_count=1000, like_count=10, comments_count=1)
    # Second migration pass (idempotency check)
    repo.migrate_meta(_meta_post("M3"))
    raw = ddb.Table("posts").get_item(Key={"external_post_id": "M3"})["Item"]
    assert int(raw["latest_view_count"]) == 1000
    assert int(raw["latest_like_count"]) == 10
