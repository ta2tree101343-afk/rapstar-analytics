"""DynamoDB implementations of the repository interfaces.

Design notes:
- Timestamps are stored as ISO 8601 UTC strings (e.g. "2026-09-20T12:34:56.789+00:00").
  ISO 8601 lexicographic order equals chronological order, which we exploit for
  Query sort keys on `metric_snapshots.fetched_at`.
- NULL is represented by omitting the attribute (never store 0 as a placeholder).
- Lock uses conditional PutItem to survive TTL deletion latency.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import boto3
from botocore.exceptions import ClientError

from .base import (
    FetchRunRecord,
    PostRecord,
    SnapshotRecord,
    TokenAuditRecord,
)


TOKEN_AUDIT_PARTITION = "audit"
LOCK_NAME = "collector"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s)


def _prune_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class DynamoDBPostRepository:
    def __init__(self, table):
        self._t = table

    def get(self, external_post_id: str) -> Optional[PostRecord]:
        resp = self._t.get_item(Key={"external_post_id": external_post_id})
        item = resp.get("Item")
        if not item:
            return None
        return PostRecord(
            external_post_id=item["external_post_id"],
            rapper_name=item.get("rapper_name"),
            permalink=item["permalink"],
            posted_at=_parse_iso(item["posted_at"]),
            caption=item.get("caption"),
            media_type=item.get("media_type"),
            media_product_type=item.get("media_product_type"),
            classification=item["classification"],
            first_seen_at=_parse_iso(item["first_seen_at"]),
            last_seen_at=_parse_iso(item["last_seen_at"]),
            latest_view_count=_as_int(item.get("latest_view_count")),
            latest_like_count=_as_int(item.get("latest_like_count")),
            latest_comments_count=_as_int(item.get("latest_comments_count")),
            latest_fetched_at=_parse_iso(item.get("latest_fetched_at")),
        )

    def upsert(self, post: PostRecord) -> bool:
        """PutItem. Returns True if a new record was created."""
        existing = self.get(post.external_post_id)
        item = _prune_none({
            "external_post_id": post.external_post_id,
            "rapper_name": post.rapper_name,
            "permalink": post.permalink,
            "posted_at": _iso(post.posted_at),
            "caption": post.caption,
            "media_type": post.media_type,
            "media_product_type": post.media_product_type,
            "classification": post.classification,
            "first_seen_at": _iso(post.first_seen_at),
            "last_seen_at": _iso(post.last_seen_at),
            "latest_view_count": post.latest_view_count,
            "latest_like_count": post.latest_like_count,
            "latest_comments_count": post.latest_comments_count,
            "latest_fetched_at": _iso(post.latest_fetched_at),
        })
        self._t.put_item(Item=item)
        return existing is None

    def migrate_meta(self, post: PostRecord) -> bool:
        """UpdateItem that sets only the immutable metadata fields.

        Never touches `latest_*` attributes, so this is safe to run *after*
        a Lambda invocation has already populated latest metrics — the
        Lambda-populated values are preserved. If the post does not yet
        exist, an item is created with only metadata (latest_* stay absent
        until the next collector run appends a snapshot).

        Returns True if a new item was created, False if it already existed.
        """
        existing = self.get(post.external_post_id)
        set_exprs = [
            "rapper_name = if_not_exists(rapper_name, :rapper_name)",
            "permalink = :permalink",
            "posted_at = :posted_at",
            "caption = if_not_exists(caption, :caption)",
            "media_type = if_not_exists(media_type, :media_type)",
            "media_product_type = if_not_exists(media_product_type, :media_product_type)",
            "classification = if_not_exists(classification, :classification)",
            "first_seen_at = if_not_exists(first_seen_at, :first_seen_at)",
            "last_seen_at = if_not_exists(last_seen_at, :last_seen_at)",
        ]
        vals = {
            ":rapper_name": post.rapper_name if post.rapper_name is not None else "",
            ":permalink": post.permalink,
            ":posted_at": _iso(post.posted_at),
            ":caption": post.caption if post.caption is not None else "",
            ":media_type": post.media_type if post.media_type is not None else "",
            ":media_product_type": post.media_product_type if post.media_product_type is not None else "",
            ":classification": post.classification,
            ":first_seen_at": _iso(post.first_seen_at),
            ":last_seen_at": _iso(post.last_seen_at),
        }
        self._t.update_item(
            Key={"external_post_id": post.external_post_id},
            UpdateExpression="SET " + ", ".join(set_exprs),
            ExpressionAttributeValues=vals,
        )
        return existing is None

    def update_latest_metrics(
        self,
        external_post_id: str,
        fetched_at: datetime,
        view_count: Optional[int],
        like_count: Optional[int],
        comments_count: Optional[int],
    ) -> None:
        set_exprs: list[str] = ["latest_fetched_at = :ts", "last_seen_at = :ts"]
        remove_exprs: list[str] = []
        vals: dict[str, Any] = {":ts": _iso(fetched_at)}
        for k, v in (
            ("latest_view_count", view_count),
            ("latest_like_count", like_count),
            ("latest_comments_count", comments_count),
        ):
            if v is None:
                remove_exprs.append(k)
            else:
                set_exprs.append(f"{k} = :{k}")
                vals[f":{k}"] = v
        parts = [f"SET {', '.join(set_exprs)}"]
        if remove_exprs:
            parts.append(f"REMOVE {', '.join(remove_exprs)}")
        self._t.update_item(
            Key={"external_post_id": external_post_id},
            UpdateExpression=" ".join(parts),
            ExpressionAttributeValues=vals,
        )


class DynamoDBSnapshotRepository:
    def __init__(self, table):
        self._t = table

    def append(self, snap: SnapshotRecord) -> None:
        item = _prune_none({
            "external_post_id": snap.external_post_id,
            "fetched_at": _iso(snap.fetched_at),
            "view_count": snap.view_count,
            "like_count": snap.like_count,
            "comments_count": snap.comments_count,
        })
        # (post_id, fetched_at) is a natural idempotency key. Re-put is a no-op for identical values.
        self._t.put_item(Item=item)

    def list_for_post(self, external_post_id: str) -> Iterator[SnapshotRecord]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "external_post_id = :pk",
            "ExpressionAttributeValues": {":pk": external_post_id},
            "ScanIndexForward": True,
        }
        while True:
            resp = self._t.query(**kwargs)
            for item in resp.get("Items", []):
                yield SnapshotRecord(
                    external_post_id=item["external_post_id"],
                    fetched_at=_parse_iso(item["fetched_at"]),
                    view_count=_as_int(item.get("view_count")),
                    like_count=_as_int(item.get("like_count")),
                    comments_count=_as_int(item.get("comments_count")),
                )
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek


class DynamoDBFetchRunRepository:
    def __init__(self, table):
        self._t = table

    def start(self, started_at: datetime) -> str:
        import uuid

        run_id = str(uuid.uuid4())
        self._t.put_item(Item={
            "run_id": run_id,
            "started_at": _iso(started_at),
            "status": "running",
        })
        return run_id

    def finalize(self, run: FetchRunRecord) -> None:
        item = _prune_none({
            "run_id": run.run_id,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "status": run.status,
            "posts_seen": run.posts_seen,
            "new_posts": run.new_posts,
            "snapshots_written": run.snapshots_written,
            "api_calls": run.api_calls,
            "error_message": run.error_message,
        })
        self._t.put_item(Item=item)


class DynamoDBTokenAuditRepository:
    def __init__(self, table):
        self._t = table

    def record(self, audit: TokenAuditRecord) -> None:
        item = _prune_none({
            "partition": TOKEN_AUDIT_PARTITION,
            "recorded_at": _iso(audit.recorded_at),
            "token_fingerprint": audit.token_fingerprint,
            "token_type": audit.token_type,
            "issued_at": _iso(audit.issued_at),
            "expires_at": _iso(audit.expires_at),
            "data_access_expires_at": _iso(audit.data_access_expires_at),
            "scopes": audit.scopes,
            "source": audit.source,
        })
        self._t.put_item(Item=item)

    def latest(self) -> Optional[TokenAuditRecord]:
        resp = self._t.query(
            KeyConditionExpression="#p = :p",
            ExpressionAttributeNames={"#p": "partition"},
            ExpressionAttributeValues={":p": TOKEN_AUDIT_PARTITION},
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items") or []
        if not items:
            return None
        item = items[0]
        return TokenAuditRecord(
            recorded_at=_parse_iso(item["recorded_at"]),
            token_fingerprint=item["token_fingerprint"],
            token_type=item["token_type"],
            issued_at=_parse_iso(item.get("issued_at")),
            expires_at=_parse_iso(item.get("expires_at")),
            data_access_expires_at=_parse_iso(item.get("data_access_expires_at")),
            scopes=item.get("scopes"),
            source=item["source"],
        )


class DynamoDBLockRepository:
    """Advisory lock via conditional PutItem.

    Acquisition succeeds if either:
      - The lock item does not exist, OR
      - The existing lock has expired (expires_at <= now)

    This avoids relying on DynamoDB TTL deletion (which is not immediate).
    """

    def __init__(self, table):
        self._t = table

    def try_acquire(self, holder_id: str, ttl_seconds: int) -> bool:
        now = int(time.time())
        try:
            self._t.put_item(
                Item={
                    "name": LOCK_NAME,
                    "holder_id": holder_id,
                    "acquired_at": now,
                    "expires_at": now + int(ttl_seconds),
                },
                ConditionExpression="attribute_not_exists(#n) OR expires_at <= :now",
                ExpressionAttributeNames={"#n": "name"},
                ExpressionAttributeValues={":now": now},
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def release(self, holder_id: str) -> None:
        try:
            self._t.delete_item(
                Key={"name": LOCK_NAME},
                ConditionExpression="holder_id = :h",
                ExpressionAttributeValues={":h": holder_id},
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                # Someone else took over — do nothing.
                return
            raise


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    return int(v)


def build_dynamodb_repositories(
    posts_table_name: str,
    snapshots_table_name: str,
    fetch_runs_table_name: str,
    token_audit_table_name: str,
    lock_table_name: str,
    dynamodb_resource=None,
):
    dynamodb = dynamodb_resource or boto3.resource(
        "dynamodb", region_name=os.environ.get("AWS_REGION", "ap-northeast-1")
    )
    return {
        "posts": DynamoDBPostRepository(dynamodb.Table(posts_table_name)),
        "snapshots": DynamoDBSnapshotRepository(dynamodb.Table(snapshots_table_name)),
        "fetch_runs": DynamoDBFetchRunRepository(dynamodb.Table(fetch_runs_table_name)),
        "token_audit": DynamoDBTokenAuditRepository(dynamodb.Table(token_audit_table_name)),
        "lock": DynamoDBLockRepository(dynamodb.Table(lock_table_name)),
    }
