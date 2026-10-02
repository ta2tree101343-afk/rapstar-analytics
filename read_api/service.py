"""Business logic for the read-only API.

Pure functions that take DynamoDB `Table` objects (or moto-mocked equivalents)
and return dicts in the exact camelCase shape expected by the frontend types
in `frontend/src/api/types.ts`.

Design constraints:
- READ-ONLY: never calls PutItem / UpdateItem / DeleteItem / TransactWriteItems.
- No interpolation of missing metrics; nulls stay null.
- No day-bucketing across posts in compare — each series keeps its own
  fetched_at timestamps verbatim.
- Enforce upper limits on data returned (see constants below) to prevent
  runaway costs / oversized responses.
"""

from __future__ import annotations

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


log = logging.getLogger(__name__)

# Per-page cap for DynamoDB Query. 1000 aligns with DynamoDB's practical
# per-page item ceiling; combined with `max_items` this keeps us from reading
# whole tables by accident.
_DDB_PAGE_ITEM_CAP = 1000

# Compare fetch parallelism. Each worker holds one HTTPS keep-alive connection
# to DynamoDB; boto3 Table resources are safe to share across threads for reads.
_COMPARE_MAX_WORKERS = 10

# --- Limits and policy constants ---

DELTA_TARGET_HOURS = 24
DELTA_TOLERANCE_HOURS = 6

DEFAULT_RANKING_LIMIT = 20
MAX_RANKING_LIMIT = 100

MAX_COMPARE_IDS = 100
MAX_HISTORY_POINTS_PER_POST = 5000
MAX_TOTAL_HISTORY_POINTS = 50_000
# API Gateway synchronous integration and Lambda both cap responses at 6 MB.
# We target a safe fraction of that so envelope overhead (headers, wrapper
# fields, base64 buffering) doesn't push us over.
MAX_COMPARE_RESPONSE_BYTES = 3 * 1024 * 1024  # 3 MB
# Extra byte budget reserved for the response envelope (range, totalEntries,
# truncation fields, JSON array framing). Estimated conservatively so we
# always finish comfortably under MAX_COMPARE_RESPONSE_BYTES.
COMPARE_ENVELOPE_BYTES = 4 * 1024

VALID_RANKING_TYPES = {
    "cumulative_views",
    "cumulative_likes",
    "cumulative_comments",
    "delta_views_24h",
    "delta_likes_24h",
}
VALID_RANGES = {"24h", "7d", "all"}
VALID_SCOPES = {"all", "top10", "selected"}
VALID_METRICS = {"viewCount", "likeCount", "commentsCount"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --- Helpers ---


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _int_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    return int(v)


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"o": offset}, separators=(",", ":")).encode("utf-8"),
    ).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> int:
    if not isinstance(cursor, str) or len(cursor) > 128:
        raise ApiError(400, "invalid_cursor", "cursor is malformed")
    try:
        pad = b"=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + pad)
        data = json.loads(raw)
    except Exception:
        raise ApiError(400, "invalid_cursor", "cursor is not decodable")
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_cursor", "cursor payload invalid")
    offset = data.get("o")
    if not isinstance(offset, int) or offset < 0 or offset > 100_000:
        raise ApiError(400, "invalid_cursor", "cursor offset out of range")
    return offset


# --- DynamoDB access ---


def _query_all_pages(table, kwargs: dict, max_items: Optional[int] = None) -> list[dict]:
    """Query with automatic pagination.

    When `max_items` is provided we push it down to DynamoDB via the `Limit`
    parameter so the database itself stops reading — preventing us from paying
    for 1MB pages we intend to discard. Each successive page's Limit is
    recomputed based on how many items we still need.
    """
    items: list[dict] = []
    k = dict(kwargs)
    while True:
        if max_items is not None:
            need = max_items - len(items)
            if need <= 0:
                return items[:max_items]
            k["Limit"] = min(need, _DDB_PAGE_ITEM_CAP)
        resp = table.query(**k)
        items.extend(resp.get("Items", []))
        if max_items is not None and len(items) >= max_items:
            return items[:max_items]
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        k["ExclusiveStartKey"] = lek


def list_entry_posts(posts_table) -> list[dict]:
    """Return all posts with classification='entry' via GSI Query (never Scan)."""
    return _query_all_pages(
        posts_table,
        {
            "IndexName": "classification-posted_at-index",
            "KeyConditionExpression": "classification = :c",
            "ExpressionAttributeValues": {":c": "entry"},
            "ScanIndexForward": False,  # newest first
        },
    )


def get_post_item(posts_table, post_id: str) -> Optional[dict]:
    resp = posts_table.get_item(Key={"external_post_id": post_id})
    return resp.get("Item")


def query_snapshots(
    snapshots_table,
    post_id: str,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    ascending: bool = True,
    max_items: Optional[int] = MAX_HISTORY_POINTS_PER_POST,
) -> list[dict]:
    key = "external_post_id = :pk"
    vals: dict[str, Any] = {":pk": post_id}
    if start_iso and end_iso:
        key += " AND fetched_at BETWEEN :s AND :e"
        vals[":s"] = start_iso
        vals[":e"] = end_iso
    elif start_iso:
        key += " AND fetched_at >= :s"
        vals[":s"] = start_iso
    elif end_iso:
        key += " AND fetched_at <= :e"
        vals[":e"] = end_iso
    return _query_all_pages(
        snapshots_table,
        {
            "KeyConditionExpression": key,
            "ExpressionAttributeValues": vals,
            "ScanIndexForward": ascending,
        },
        max_items=max_items,
    )


def latest_success_run(fetch_runs_table) -> Optional[dict]:
    """Return the most recent successful fetch run.

    The GSI `status-started_at-index` has KEYS_ONLY projection, so a subsequent
    GetItem retrieves the full attributes.
    """
    resp = fetch_runs_table.query(
        IndexName="status-started_at-index",
        KeyConditionExpression="#s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "success"},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    run_id = items[0].get("run_id")
    if not run_id:
        return None
    got = fetch_runs_table.get_item(Key={"run_id": run_id})
    return got.get("Item")


def list_data_bearing_runs_in_range(
    fetch_runs_table,
    start_iso: Optional[str],
) -> list[dict]:
    """Return `[{run_id, started_at, finished_at, status}, ...]` for runs whose
    `started_at >= start_iso` and whose status implies snapshots were written
    (`success` or `partial`).

    These runs are exactly the ones the frontend can present as selectable
    "collection cycles" — a failed run (status=`error`, snapshots_written=0)
    has no observable measurements in the snapshots table and cannot back a
    cycle, so we exclude it here rather than making the frontend re-check.

    Uses the `status-started_at-index` GSI (KEYS_ONLY) then hydrates each run
    with a batch of GetItems.
    """
    wanted_statuses = ("success", "partial")
    ids: list[str] = []
    for st in wanted_statuses:
        kwargs: dict[str, Any] = {
            "IndexName": "status-started_at-index",
            "KeyConditionExpression": "#s = :s",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": st},
            "ScanIndexForward": True,
        }
        if start_iso:
            kwargs["KeyConditionExpression"] += " AND started_at >= :sa"
            kwargs["ExpressionAttributeValues"][":sa"] = start_iso
        resp = fetch_runs_table.query(**kwargs)
        for it in resp.get("Items", []) or []:
            rid = it.get("run_id")
            if rid:
                ids.append(rid)
    # Hydrate. The table is small (one row per daily run over months) so
    # per-id GetItem is acceptable; batch_get_item would need chunking at 100.
    out: list[dict] = []
    for rid in ids:
        got = fetch_runs_table.get_item(Key={"run_id": rid}).get("Item")
        if not got:
            continue
        started = got.get("started_at")
        finished = got.get("finished_at")
        if not started or not finished:
            continue
        # Skip runs that reported success but wrote no snapshots — nothing to
        # associate with in the frontend cycle view.
        written = got.get("snapshots_written")
        if written is not None:
            try:
                if int(written) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
        out.append(
            {
                "runId": rid,
                "startedAt": started,
                "finishedAt": finished,
                "status": got.get("status"),
                "snapshotsWritten": _int_or_none(written),
            }
        )
    out.sort(key=lambda r: r["startedAt"])
    return out


# --- Shape transforms ---


def _cumulative_from_item(item: dict) -> dict:
    return {
        "viewCount": _int_or_none(item.get("latest_view_count")),
        "likeCount": _int_or_none(item.get("latest_like_count")),
        "commentsCount": _int_or_none(item.get("latest_comments_count")),
    }


def _post_base(item: dict) -> dict:
    return {
        "postId": item["external_post_id"],
        "rapperName": item.get("rapper_name"),
        "permalink": item["permalink"],
        "postedAt": item["posted_at"],
        "latestFetchedAt": item.get("latest_fetched_at"),
        "cumulative": _cumulative_from_item(item),
    }


def _post_age_hours(posted_at_iso: str, latest_at_iso: Optional[str]) -> Optional[float]:
    if not latest_at_iso:
        return None
    posted = _parse_iso(posted_at_iso)
    latest = _parse_iso(latest_at_iso)
    if not posted or not latest:
        return None
    return (latest - posted).total_seconds() / 3600.0


def _find_reference_snapshot(
    snapshots_table,
    post_id: str,
    latest_at_iso: str,
    metric_field: str,
) -> Optional[tuple[int, str, float]]:
    """Return (reference_value, reference_fetched_at_iso, hours_between) or None.

    Searches the window [latest - 30h, latest - 18h] and returns the snapshot
    whose fetched_at is closest to (latest - 24h) AND which has a non-null
    value for `metric_field`.
    """
    latest = _parse_iso(latest_at_iso)
    if not latest:
        return None
    target = latest - timedelta(hours=DELTA_TARGET_HOURS)
    win_start = latest - timedelta(hours=DELTA_TARGET_HOURS + DELTA_TOLERANCE_HOURS)
    win_end = latest - timedelta(hours=DELTA_TARGET_HOURS - DELTA_TOLERANCE_HOURS)

    snaps = query_snapshots(
        snapshots_table,
        post_id,
        start_iso=_iso(win_start),
        end_iso=_iso(win_end),
        ascending=True,
    )
    best = None
    best_diff = None
    for s in snaps:
        v = s.get(metric_field)
        if v is None:
            continue
        s_at = _parse_iso(s["fetched_at"])
        if not s_at:
            continue
        diff = abs((s_at - target).total_seconds())
        if best is None or diff < (best_diff or 0):
            best = s
            best_diff = diff
    if best is None:
        return None
    ref_at = _parse_iso(best["fetched_at"])
    hours = (latest - ref_at).total_seconds() / 3600.0 if ref_at else 0.0
    return int(best[metric_field]), best["fetched_at"], hours


def _snapshot_to_point(s: dict) -> dict:
    return {
        "fetchedAt": s["fetched_at"],
        "viewCount": _int_or_none(s.get("view_count")),
        "likeCount": _int_or_none(s.get("like_count")),
        "commentsCount": _int_or_none(s.get("comments_count")),
    }


# --- Endpoint builders ---


def build_status(posts_table, fetch_runs_table) -> dict:
    run = latest_success_run(fetch_runs_table)
    entries = list_entry_posts(posts_table)
    latest = None
    for e in entries:
        f = e.get("latest_fetched_at")
        if f and (latest is None or f > latest):
            latest = f
    finished = run.get("finished_at") if run else None
    return {
        "lastSuccessAt": finished,
        "lastSuccessStatus": run.get("status") if run else None,
        "entryCount": len(entries),
        "updatedAt": latest or finished,
        "isMock": False,
    }


def _cumulative_value(item: dict, ranking_type: str) -> Optional[int]:
    if ranking_type == "cumulative_views":
        return _int_or_none(item.get("latest_view_count"))
    if ranking_type == "cumulative_likes":
        return _int_or_none(item.get("latest_like_count"))
    if ranking_type == "cumulative_comments":
        return _int_or_none(item.get("latest_comments_count"))
    return None


def _delta_fields(ranking_type: str) -> tuple[str, str]:
    if ranking_type == "delta_views_24h":
        return "latest_view_count", "view_count"
    return "latest_like_count", "like_count"


def build_rankings_full(posts_table, snapshots_table, ranking_type: str) -> list[dict]:
    """Compute the full sorted ranking list (before pagination)."""
    if ranking_type not in VALID_RANKING_TYPES:
        raise ApiError(400, "invalid_type", f"unknown ranking type: {ranking_type}")

    entries = list_entry_posts(posts_table)
    result: list[dict] = []

    for item in entries:
        base = _post_base(item)

        if ranking_type.startswith("cumulative_"):
            v = _cumulative_value(item, ranking_type)
            base["value"] = v
            base["valueLabel"] = "" if v is None else str(v)
            base["reason"] = "no_metric" if v is None else None
            base["delta"] = None
            result.append(base)
            continue

        latest_field, snap_field = _delta_fields(ranking_type)
        latest_val = _int_or_none(item.get(latest_field))
        latest_at = item.get("latest_fetched_at")
        age_h = _post_age_hours(item.get("posted_at", ""), latest_at)

        # Per spec: exclude posts <24h old from delta rankings entirely.
        if age_h is not None and age_h < DELTA_TARGET_HOURS:
            continue

        if latest_val is None or latest_at is None:
            base["value"] = None
            base["valueLabel"] = ""
            base["reason"] = "no_metric"
            base["delta"] = None
            result.append(base)
            continue

        ref = _find_reference_snapshot(snapshots_table, item["external_post_id"], latest_at, snap_field)
        if ref is None:
            base["value"] = None
            base["valueLabel"] = ""
            base["reason"] = "insufficient_data"
            base["delta"] = None
            result.append(base)
            continue

        ref_val, ref_at, hours = ref
        delta = latest_val - ref_val
        base["value"] = delta
        base["valueLabel"] = str(delta)
        base["reason"] = None
        base["delta"] = {
            "referenceFetchedAt": ref_at,
            "actualHoursBetween": hours,
        }
        result.append(base)

    # Sort: value desc; nulls last; stable tie-break by postId.
    def sort_key(it: dict):
        v = it["value"]
        return (0 if v is not None else 1, -v if v is not None else 0, it["postId"])

    result.sort(key=sort_key)
    return result


def build_rankings_response(
    posts_table,
    snapshots_table,
    ranking_type: str,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> dict:
    """Return the sorted ranking.

    Pagination policy:
      - If neither `limit` nor `cursor` is provided, return the ENTIRE sorted
        list. This matches the existing frontend contract (mockClient returns
        all items; RankingsPage does client-side `slice(0, displayCount)` for
        「もっと見る」).
      - If either is provided, honor server-side pagination and include a
        `nextCursor` when more items remain.
    """
    all_items = build_rankings_full(posts_table, snapshots_table, ranking_type)
    total_eligible = len(all_items)
    total_with_data = sum(1 for it in all_items if it["value"] is not None)

    if limit is None and cursor is None:
        return {
            "type": ranking_type,
            "items": all_items,
            "totalEligible": total_eligible,
            "totalWithData": total_with_data,
            "totalWithoutData": total_eligible - total_with_data,
            "nextCursor": None,
            "isMock": False,
        }

    effective_limit = limit if limit is not None else DEFAULT_RANKING_LIMIT
    offset = decode_cursor(cursor) if cursor else 0
    end = offset + effective_limit
    slice_items = all_items[offset:end]
    next_cursor = encode_cursor(end) if end < total_eligible else None

    return {
        "type": ranking_type,
        "items": slice_items,
        "totalEligible": total_eligible,
        "totalWithData": total_with_data,
        "totalWithoutData": total_eligible - total_with_data,
        "nextCursor": next_cursor,
        "isMock": False,
    }


def build_post_detail(posts_table, post_id: str) -> dict:
    item = get_post_item(posts_table, post_id)
    if not item:
        raise ApiError(404, "not_found", "post not found")
    return {
        "postId": item["external_post_id"],
        "rapperName": item.get("rapper_name"),
        "permalink": item["permalink"],
        "postedAt": item["posted_at"],
        "caption": item.get("caption"),
        "classification": item.get("classification", "unclassified"),
        "latest": {
            "viewCount": _int_or_none(item.get("latest_view_count")),
            "likeCount": _int_or_none(item.get("latest_like_count")),
            "commentsCount": _int_or_none(item.get("latest_comments_count")),
            "fetchedAt": item.get("latest_fetched_at"),
        },
        "isMock": False,
    }


def _range_start(range_: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    if range_ == "24h":
        return now - timedelta(hours=24)
    if range_ == "7d":
        return now - timedelta(days=7)
    if range_ == "all":
        return None
    raise ApiError(400, "invalid_range", f"unknown range: {range_}")


def build_post_history(posts_table, snapshots_table, post_id: str, range_: str) -> dict:
    if not get_post_item(posts_table, post_id):
        raise ApiError(404, "not_found", "post not found")
    start = _range_start(range_)
    snaps = query_snapshots(
        snapshots_table,
        post_id,
        start_iso=_iso(start),
        ascending=True,
        max_items=MAX_HISTORY_POINTS_PER_POST,
    )
    return {
        "postId": post_id,
        "range": range_,
        "points": [_snapshot_to_point(s) for s in snaps],
        "isMock": False,
    }


def _priority_key(entry: dict, priority_field: str):
    v = entry.get(priority_field)
    return (0, -int(v)) if v is not None else (1, 0)


def _series_dict(entry: dict, points: list[dict]) -> dict:
    return {
        "postId": entry["external_post_id"],
        "rapperName": entry.get("rapper_name"),
        "permalink": entry["permalink"],
        "postedAt": entry["posted_at"],
        "points": points,
    }


def _byte_size(obj: Any) -> int:
    """UTF-8 byte length of the JSON-serialized value. This is exactly the
    payload cost the response will carry."""
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


def build_compare(
    posts_table,
    snapshots_table,
    range_: str,
    scope: str = "all",
    ids: Optional[list[str]] = None,
    metric: str = "viewCount",
    fetch_runs_table=None,
) -> dict:
    """Return per-post history series with hard caps on both point count and
    response byte size.

    Loading strategy:
      1. Resolve target `entries` from `scope`.
      2. Sort by `latest_<metric>` desc so the "most important" series win
         if the cap is hit (scope=selected preserves caller order).
      3. Fetch snapshots in **batches of _COMPARE_MAX_WORKERS**. After each
         batch we re-evaluate the accumulated budget:
           - If the batch would push us past either cap, stop starting the
             remaining batches — **no more DynamoDB queries are issued**.
           - Individual entries within a completed batch are still checked
             one-by-one against the byte / point cap.
      4. On cap hit: return the partial set with `truncated=true`,
         `truncatedReason`, `truncatedIncluded`, `truncatedOmitted` so the
         frontend can display "shown X / total N" and prompt narrowing.

    We NEVER read more from DynamoDB than a running budget allows:
      - Per-post DDB `Limit` push-down via `_query_all_pages` (max 5000/post).
      - Batched parallelism so cancellation costs at most one batch of work
        (≤ _COMPARE_MAX_WORKERS in-flight queries) after the cap is hit.
    """
    if range_ not in VALID_RANGES:
        raise ApiError(400, "invalid_range", f"unknown range: {range_}")
    if scope not in VALID_SCOPES:
        raise ApiError(400, "invalid_scope", f"unknown scope: {scope}")
    if metric not in VALID_METRICS:
        raise ApiError(400, "invalid_metric", f"unknown metric: {metric}")

    entries = list_entry_posts(posts_table)
    total_entries = len(entries)

    priority_field = {
        "viewCount": "latest_view_count",
        "likeCount": "latest_like_count",
        "commentsCount": "latest_comments_count",
    }[metric]

    if scope == "top10":
        entries = sorted(
            (e for e in entries if e.get(priority_field) is not None),
            key=lambda e: int(e[priority_field]),
            reverse=True,
        )[:10]
    elif scope == "selected":
        if not ids:
            raise ApiError(400, "missing_ids", "scope=selected requires ids")
        if len(ids) > MAX_COMPARE_IDS:
            raise ApiError(400, "too_many_ids", f"max {MAX_COMPARE_IDS} ids allowed")
        by_id = {e["external_post_id"]: e for e in entries}
        entries = [by_id[i] for i in ids if i in by_id]
    else:
        # scope=all — sort by importance so truncation drops the least popular first.
        entries.sort(key=lambda e: _priority_key(e, priority_field))

    start = _range_start(range_)
    start_iso = _iso(start)

    def _fetch(entry):
        return entry, query_snapshots(
            snapshots_table,
            entry["external_post_id"],
            start_iso=start_iso,
            ascending=True,
            max_items=MAX_HISTORY_POINTS_PER_POST,
        )

    total_points = 0
    series_byte_budget = MAX_COMPARE_RESPONSE_BYTES - COMPARE_ENVELOPE_BYTES
    total_series_bytes = 0
    truncated = False
    truncated_reason: Optional[str] = None
    series: list[dict] = []
    entries_completed = 0  # how many entries we actually issued DDB queries for
    cursor = 0

    while cursor < len(entries):
        batch = entries[cursor : cursor + _COMPARE_MAX_WORKERS]
        cursor += len(batch)

        if len(batch) == 1:
            batch_results = [_fetch(batch[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(_fetch, e) for e in batch]
                results_by_pos = {}
                for idx, f in enumerate(futures):
                    results_by_pos[idx] = f
                batch_results = [results_by_pos[i].result() for i in range(len(batch))]

        entries_completed += len(batch_results)

        for entry, snaps in batch_results:
            points = [_snapshot_to_point(s) for s in snaps]
            new_series = _series_dict(entry, points)
            new_points = len(points)
            # Byte cost of adding this element to the series array. A leading
            # comma appears from the 2nd element onward; we approximate with +1.
            new_bytes = _byte_size(new_series) + (1 if series else 0)

            would_exceed_points = total_points + new_points > MAX_TOTAL_HISTORY_POINTS
            would_exceed_bytes = total_series_bytes + new_bytes > series_byte_budget

            if would_exceed_points or would_exceed_bytes:
                truncated = True
                truncated_reason = "response_too_large"
                break

            total_points += new_points
            total_series_bytes += new_bytes
            series.append(new_series)

        if truncated:
            break

    # Collection runs (data-bearing only) covering the same range. The frontend
    # uses these intervals to assign each snapshot to a "collection cycle" so
    # that selecting a point on the graph maps to the whole cycle rather than
    # a single microsecond-precision `fetched_at`. When the caller doesn't
    # provide `fetch_runs_table` (backward-compat), we simply omit `runs`.
    runs: list[dict] = []
    if fetch_runs_table is not None:
        try:
            runs = list_data_bearing_runs_in_range(fetch_runs_table, start_iso)
        except Exception:  # noqa: BLE001 — runs are auxiliary; don't fail compare
            log.exception("failed to list fetch runs; returning empty runs")
            runs = []

    body = {
        "range": range_,
        "series": series,
        "totalEntries": total_entries,
        "runs": runs,
        "isMock": False,
    }
    if truncated:
        body["truncated"] = True
        body["truncatedReason"] = truncated_reason
        body["truncatedIncluded"] = len(series)
        body["truncatedOmitted"] = len(entries) - len(series)
    return body
