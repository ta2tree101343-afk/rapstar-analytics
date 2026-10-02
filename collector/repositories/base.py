from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional, Protocol


@dataclass
class PostRecord:
    external_post_id: str
    rapper_name: Optional[str]
    permalink: str
    posted_at: datetime
    caption: Optional[str]
    media_type: Optional[str]
    media_product_type: Optional[str]
    classification: str
    first_seen_at: datetime
    last_seen_at: datetime
    latest_view_count: Optional[int] = None
    latest_like_count: Optional[int] = None
    latest_comments_count: Optional[int] = None
    latest_fetched_at: Optional[datetime] = None


@dataclass
class SnapshotRecord:
    external_post_id: str
    fetched_at: datetime
    view_count: Optional[int]
    like_count: Optional[int]
    comments_count: Optional[int]


@dataclass
class FetchRunRecord:
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    posts_seen: Optional[int]
    new_posts: Optional[int]
    snapshots_written: Optional[int]
    api_calls: Optional[int]
    error_message: Optional[str]


@dataclass
class TokenAuditRecord:
    recorded_at: datetime
    token_fingerprint: str
    token_type: str
    issued_at: Optional[datetime]
    expires_at: Optional[datetime]
    data_access_expires_at: Optional[datetime]
    scopes: Optional[str]
    source: str


class PostRepository(Protocol):
    def get(self, external_post_id: str) -> Optional[PostRecord]: ...
    def upsert(self, post: PostRecord) -> bool: ...
    def update_latest_metrics(
        self,
        external_post_id: str,
        fetched_at: datetime,
        view_count: Optional[int],
        like_count: Optional[int],
        comments_count: Optional[int],
    ) -> None: ...


class SnapshotRepository(Protocol):
    def append(self, snapshot: SnapshotRecord) -> None: ...
    def list_for_post(self, external_post_id: str) -> Iterator[SnapshotRecord]: ...


class FetchRunRepository(Protocol):
    def start(self, started_at: datetime) -> str: ...
    def finalize(self, run: FetchRunRecord) -> None: ...


class TokenAuditRepository(Protocol):
    def record(self, audit: TokenAuditRecord) -> None: ...
    def latest(self) -> Optional[TokenAuditRecord]: ...


class LockRepository(Protocol):
    """Distributed advisory lock.

    Implementations MUST use conditional writes so a stale lock (past its
    expires_at) can be safely acquired by a new caller without TTL-delete
    dependency.
    """
    def try_acquire(self, holder_id: str, ttl_seconds: int) -> bool: ...
    def release(self, holder_id: str) -> None: ...


@dataclass
class Repositories:
    posts: PostRepository
    snapshots: SnapshotRepository
    fetch_runs: FetchRunRepository
    token_audit: TokenAuditRepository
    lock: LockRepository
