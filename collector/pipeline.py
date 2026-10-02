from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .classifier import classify_caption
from .db import FetchRun, MetricSnapshot, Post, utcnow


log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    posts_seen: int = 0
    new_posts: int = 0
    snapshots_written: int = 0
    classification_counts: dict[str, int] | None = None
    api_calls: int = 0
    status: str = "success"
    error_message: str | None = None


def _parse_ig_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # Graph API returns ISO8601 like "2026-09-15T12:34:56+0000"
    try:
        return datetime.fromisoformat(raw.replace("+0000", "+00:00"))
    except ValueError:
        return None


def upsert_post_and_snapshot(
    session: Session,
    item: dict[str, Any],
    fetched_at: datetime,
    mode: str = "both",
) -> tuple[bool, bool]:
    """Upsert one media into `posts` and optionally append one `metric_snapshots` row.

    mode:
      - 'both'            : upsert post AND append snapshot (default)
      - 'new-only'        : upsert post ONLY; no snapshot written
      - 'snapshots-only'  : append snapshot for known post; do NOT create new posts

    Returns (was_new_post, snapshot_written).
    """
    external_id = item.get("id")
    if not external_id:
        return (False, False)

    caption = item.get("caption")
    classification = classify_caption(caption)
    posted_at = _parse_ig_timestamp(item.get("timestamp"))
    permalink = item.get("permalink") or ""

    if posted_at is None or not permalink:
        log.warning("skip media %s: missing timestamp or permalink", external_id)
        return (False, False)

    existing = session.get(Post, external_id)
    was_new = False
    if existing is None:
        if mode == "snapshots-only":
            return (False, False)
        session.add(
            Post(
                external_post_id=external_id,
                rapper_name=classification.rapper_name,
                permalink=permalink,
                posted_at=posted_at,
                caption=caption,
                media_type=item.get("media_type"),
                media_product_type=item.get("media_product_type"),
                classification=classification.status,
                first_seen_at=fetched_at,
                last_seen_at=fetched_at,
            )
        )
        was_new = True
    else:
        if existing.classification == "unclassified" and classification.status == "entry":
            existing.classification = "entry"
        if classification.rapper_name and not existing.rapper_name:
            existing.rapper_name = classification.rapper_name
        existing.caption = caption
        existing.media_type = item.get("media_type") or existing.media_type
        existing.media_product_type = item.get("media_product_type") or existing.media_product_type
        existing.last_seen_at = fetched_at

    if mode == "new-only":
        return (was_new, False)

    snapshot = MetricSnapshot(
        external_post_id=external_id,
        fetched_at=fetched_at,
        view_count=item.get("view_count"),
        like_count=item.get("like_count"),
        comments_count=item.get("comments_count"),
    )
    session.add(snapshot)
    return (was_new, True)


def run_collection(
    session_factory,
    media_iter: Iterable[dict[str, Any]],
    api_call_getter=lambda: 0,
    mode: str = "both",
) -> RunSummary:
    """Consume a media iterator and persist to DB. One transaction per media."""
    summary = RunSummary(classification_counts={})
    started_at = utcnow()

    with session_factory() as session:
        run = FetchRun(started_at=started_at, status="running")
        session.add(run)
        session.commit()
        run_id = run.id

    try:
        try:
            for item in media_iter:
                summary.posts_seen += 1
                fetched_at = utcnow()
                with session_factory() as session:
                    try:
                        was_new, wrote = upsert_post_and_snapshot(session, item, fetched_at, mode=mode)
                        session.commit()
                    except Exception as e:  # noqa: BLE001 — per-item isolation
                        session.rollback()
                        log.exception("failed to persist media %s: %s", item.get("id"), e)
                        summary.status = "partial"
                        continue
                if was_new:
                    summary.new_posts += 1
                if wrote:
                    summary.snapshots_written += 1
                cls = classify_caption(item.get("caption")).status
                counts = summary.classification_counts or {}
                counts[cls] = counts.get(cls, 0) + 1
                summary.classification_counts = counts
        except KeyboardInterrupt:
            summary.status = "interrupted"
            summary.error_message = "KeyboardInterrupt"
            raise
        except Exception as e:  # noqa: BLE001 — top-level failure
            summary.status = "error"
            summary.error_message = str(e)
    finally:
        summary.api_calls = api_call_getter()
        try:
            with session_factory() as session:
                run = session.get(FetchRun, run_id)
                if run is not None:
                    run.finished_at = utcnow()
                    run.status = summary.status
                    run.posts_seen = summary.posts_seen
                    run.new_posts = summary.new_posts
                    run.snapshots_written = summary.snapshots_written
                    run.api_calls = summary.api_calls
                    run.error_message = summary.error_message
                    session.commit()
        except Exception:  # noqa: BLE001 — ensure finally never masks the original
            log.exception("failed to finalize FetchRun row (run_id=%s)", run_id)

    return summary
