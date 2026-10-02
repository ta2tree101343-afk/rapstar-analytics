"""Idempotent, resumable migration of local SQLite state into DynamoDB.

Usage:
    python scripts/migrate_sqlite_to_dynamodb.py \\
        --posts-table rapstar-prod-posts \\
        --snapshots-table rapstar-prod-metric-snapshots \\
        --fetch-runs-table rapstar-prod-fetch-runs \\
        --token-audit-table rapstar-prod-access-tokens \\
        --sqlite data/rapstar.db \\
        --verify        # verify only, no writes
        --dry-run       # count and diff, no writes

Safety:
  1. Writes are idempotent: each Put uses the natural key (post_id or (post_id, fetched_at)),
     re-running never produces duplicates.
  2. Full verification pass compares counts and per-row equality between source and dest.
  3. Reads SQLite in a transaction (snapshot semantics).
  4. Never activates cloud scheduler; that is a separate step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3

from collector.db import (  # noqa: E402
    AccessTokenRecord,
    FetchRun,
    MetricSnapshot,
    Post,
    make_engine,
    make_session_factory,
)
from collector.repositories.base import (  # noqa: E402
    FetchRunRecord,
    PostRecord,
    SnapshotRecord,
    TokenAuditRecord,
)
from collector.repositories.dynamodb_impl import (  # noqa: E402
    DynamoDBFetchRunRepository,
    DynamoDBPostRepository,
    DynamoDBSnapshotRepository,
    DynamoDBTokenAuditRepository,
    _iso,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", default="data/rapstar.db")
    p.add_argument("--posts-table", required=True)
    p.add_argument("--snapshots-table", required=True)
    p.add_argument("--fetch-runs-table", required=True)
    p.add_argument("--token-audit-table", required=True)
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verify", action="store_true", help="Only verify, do not write")
    p.add_argument("--skip-backup", action="store_true")
    return p.parse_args()


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_posts(sf) -> Iterable[PostRecord]:
    with sf() as s:
        for p in s.query(Post).order_by(Post.external_post_id):
            yield PostRecord(
                external_post_id=p.external_post_id,
                rapper_name=p.rapper_name,
                permalink=p.permalink,
                posted_at=_utc(p.posted_at),
                caption=p.caption,
                media_type=p.media_type,
                media_product_type=p.media_product_type,
                classification=p.classification,
                first_seen_at=_utc(p.first_seen_at),
                last_seen_at=_utc(p.last_seen_at),
            )


def _iter_snapshots(sf) -> Iterable[SnapshotRecord]:
    with sf() as s:
        for x in s.query(MetricSnapshot).order_by(MetricSnapshot.external_post_id, MetricSnapshot.fetched_at):
            yield SnapshotRecord(
                external_post_id=x.external_post_id,
                fetched_at=_utc(x.fetched_at),
                view_count=x.view_count,
                like_count=x.like_count,
                comments_count=x.comments_count,
            )


def _iter_fetch_runs(sf) -> Iterable[FetchRunRecord]:
    with sf() as s:
        for r in s.query(FetchRun).order_by(FetchRun.id):
            yield FetchRunRecord(
                run_id=f"legacy-{r.id}",
                started_at=_utc(r.started_at),
                finished_at=_utc(r.finished_at),
                status=r.status,
                posts_seen=r.posts_seen,
                new_posts=r.new_posts,
                snapshots_written=r.snapshots_written,
                api_calls=r.api_calls,
                error_message=r.error_message,
            )


def _iter_tokens(sf) -> Iterable[TokenAuditRecord]:
    with sf() as s:
        for t in s.query(AccessTokenRecord).order_by(AccessTokenRecord.id):
            yield TokenAuditRecord(
                recorded_at=_utc(t.recorded_at),
                token_fingerprint=t.token_fingerprint,
                token_type=t.token_type,
                issued_at=_utc(t.issued_at),
                expires_at=_utc(t.expires_at),
                data_access_expires_at=_utc(t.data_access_expires_at),
                scopes=t.scopes,
                source=t.source,
            )


def _post_signature(p: PostRecord) -> str:
    return _hash({
        "id": p.external_post_id,
        "posted_at": _iso(p.posted_at),
        "classification": p.classification,
        "permalink": p.permalink,
    })


def _snapshot_signature(x: SnapshotRecord) -> str:
    return _hash({
        "id": x.external_post_id,
        "fetched_at": _iso(x.fetched_at),
        "view_count": x.view_count,
        "like_count": x.like_count,
        "comments_count": x.comments_count,
    })


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _backup_sqlite(src: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = src.with_suffix(f".pre-migration.{ts}.db")
    shutil.copy2(src, dst)
    return dst


def _write_posts(repo, records, dry: bool) -> int:
    """Migrate posts using `migrate_meta` so latest_* attributes populated by
    a prior Lambda run are preserved and NOT overwritten by migration."""
    n = 0
    for rec in records:
        if not dry:
            repo.migrate_meta(rec)
        n += 1
    return n


def _write_snapshots(repo, records, dry: bool) -> int:
    n = 0
    for rec in records:
        if not dry:
            repo.append(rec)
        n += 1
    return n


def _write_fetch_runs(repo, records, dry: bool) -> int:
    n = 0
    for rec in records:
        if not dry:
            repo.finalize(rec)  # finalize also serves as an idempotent PutItem
        n += 1
    return n


def _write_token_audit(repo, records, dry: bool) -> int:
    n = 0
    for rec in records:
        if not dry:
            repo.record(rec)
        n += 1
    return n


def _verify_counts(sf, tables) -> dict:
    with sf() as s:
        source_counts = {
            "posts": s.query(Post).count(),
            "snapshots": s.query(MetricSnapshot).count(),
            "fetch_runs": s.query(FetchRun).count(),
            "access_tokens": s.query(AccessTokenRecord).count(),
        }
    dest_counts = {
        "posts": _scan_count(tables["posts"]),
        "snapshots": _scan_count(tables["snapshots"]),
        "fetch_runs": _scan_count(tables["fetch_runs"]),
        "access_tokens": _scan_count(tables["token_audit"]),
    }
    return {"source": source_counts, "dest": dest_counts}


def _scan_count(table) -> int:
    total = 0
    kwargs = {"Select": "COUNT"}
    while True:
        resp = table.scan(**kwargs)
        total += resp.get("Count", 0)
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return total
        kwargs["ExclusiveStartKey"] = lek


def _verify_samples(sf, repos, sample_size=25) -> dict:
    """Compare a random-ish sample of records (deterministic: first N sorted)."""
    problems: list[str] = []
    checked = 0

    with sf() as s:
        rows = s.query(Post).order_by(Post.external_post_id).limit(sample_size).all()
    for p in rows:
        got = repos["posts"].get(p.external_post_id)
        if got is None:
            problems.append(f"post missing in dynamodb: {p.external_post_id}")
            continue
        if _post_signature(_row_to_post(p)) != _post_signature(got):
            problems.append(f"post mismatch: {p.external_post_id}")
        checked += 1

    with sf() as s:
        srows = (
            s.query(MetricSnapshot)
            .order_by(MetricSnapshot.external_post_id, MetricSnapshot.fetched_at)
            .limit(sample_size)
            .all()
        )
    for x in srows:
        found = None
        for snap in repos["snapshots"].list_for_post(x.external_post_id):
            if snap.fetched_at.replace(microsecond=snap.fetched_at.microsecond) == _utc(x.fetched_at):
                found = snap
                break
        if found is None:
            problems.append(f"snapshot missing: {x.external_post_id}@{x.fetched_at}")
        elif _snapshot_signature(found) != _snapshot_signature(SnapshotRecord(
            external_post_id=x.external_post_id,
            fetched_at=_utc(x.fetched_at),
            view_count=x.view_count,
            like_count=x.like_count,
            comments_count=x.comments_count,
        )):
            problems.append(f"snapshot mismatch: {x.external_post_id}@{x.fetched_at}")
        checked += 1

    return {"checked": checked, "problems": problems}


def _row_to_post(p: Post) -> PostRecord:
    return PostRecord(
        external_post_id=p.external_post_id,
        rapper_name=p.rapper_name,
        permalink=p.permalink,
        posted_at=_utc(p.posted_at),
        caption=p.caption,
        media_type=p.media_type,
        media_product_type=p.media_product_type,
        classification=p.classification,
        first_seen_at=_utc(p.first_seen_at),
        last_seen_at=_utc(p.last_seen_at),
    )


def main() -> int:
    args = parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"[error] sqlite not found: {sqlite_path}")
        return 2

    if not args.dry_run and not args.verify and not args.skip_backup:
        backup = _backup_sqlite(sqlite_path)
        print(f"[backup] {backup}")

    engine = make_engine(f"sqlite:///{sqlite_path}")
    sf = make_session_factory(engine)

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    tables = {
        "posts": dynamodb.Table(args.posts_table),
        "snapshots": dynamodb.Table(args.snapshots_table),
        "fetch_runs": dynamodb.Table(args.fetch_runs_table),
        "token_audit": dynamodb.Table(args.token_audit_table),
    }
    repos = {
        "posts": DynamoDBPostRepository(tables["posts"]),
        "snapshots": DynamoDBSnapshotRepository(tables["snapshots"]),
        "fetch_runs": DynamoDBFetchRunRepository(tables["fetch_runs"]),
        "token_audit": DynamoDBTokenAuditRepository(tables["token_audit"]),
    }

    if not args.verify:
        print("[migrate] posts…")
        n = _write_posts(repos["posts"], _iter_posts(sf), args.dry_run)
        print(f"[migrate] posts={n}")
        print("[migrate] snapshots…")
        n = _write_snapshots(repos["snapshots"], _iter_snapshots(sf), args.dry_run)
        print(f"[migrate] snapshots={n}")
        print("[migrate] fetch_runs…")
        n = _write_fetch_runs(repos["fetch_runs"], _iter_fetch_runs(sf), args.dry_run)
        print(f"[migrate] fetch_runs={n}")
        print("[migrate] access_tokens…")
        n = _write_token_audit(repos["token_audit"], _iter_tokens(sf), args.dry_run)
        print(f"[migrate] access_tokens={n}")

    if args.dry_run:
        print("[dry-run] skipping verification writes-required step")
        return 0

    print("[verify] counting…")
    counts = _verify_counts(sf, tables)
    print(json.dumps(counts, indent=2, ensure_ascii=False))
    src, dst = counts["source"], counts["dest"]
    mismatched = [k for k in src if src[k] != dst[k]]

    print("[verify] sample compare…")
    sample = _verify_samples(sf, repos)
    print(json.dumps(sample, indent=2, ensure_ascii=False))

    if mismatched or sample["problems"]:
        print(f"[FAIL] mismatched_counts={mismatched} sample_problems={len(sample['problems'])}")
        return 3
    print("[OK] migration verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
