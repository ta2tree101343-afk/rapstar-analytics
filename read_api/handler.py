"""AWS Lambda entry point for the read-only public API.

Route table:
    GET  /api/status
    GET  /api/rankings?type=<t>&limit=<n>&cursor=<c>
    GET  /api/posts/{postId}
    GET  /api/posts/{postId}/history?range=24h|7d|all
    GET  /api/compare?range=&scope=&ids=&metric=
    OPTIONS *   -> CORS preflight

The handler NEVER performs writes and NEVER reads secrets. It has no
knowledge of Instagram tokens, App IDs, or App Secrets.

Handler: `read_api.handler.lambda_handler`

Layout: this module lives in its OWN top-level package `read_api/` so its SAM
`CodeUri` can point at a directory that is fully disjoint from the collector
Lambda's code. That way, changes here do not force a re-deploy of the
collector Lambda in the sibling stack.
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import unquote

import boto3

# In Lambda runtime, SAM packages handler.py and service.py at the ZIP root
# with CodeUri: ../read_api/, so absolute imports work. In local dev/tests
# we import via `from read_api.handler import ...`, which puts us inside
# the `read_api` package and needs relative imports. Support both.
try:
    from . import service as svc
    from .service import ApiError
except ImportError:  # pragma: no cover — hit only in Lambda runtime
    import service as svc  # type: ignore[import-not-found,no-redef]
    from service import ApiError  # type: ignore[import-not-found,no-redef]


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


_ID_ALLOWED = re.compile(r"^[A-Za-z0-9._\-:]+$")


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
    }


def _resp(status: int, body: dict, cache_seconds: int = 300) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": f"public, max-age={cache_seconds}",
            **_cors_headers(),
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _error(status: int, code: str, message: str) -> dict:
    return _resp(status, {"error": code, "message": message}, cache_seconds=0)


def _get_tables():
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
    )
    return {
        "posts": dynamodb.Table(os.environ["POSTS_TABLE"]),
        "snapshots": dynamodb.Table(os.environ["SNAPSHOTS_TABLE"]),
        "fetch_runs": dynamodb.Table(os.environ["FETCH_RUNS_TABLE"]),
    }


POST_HISTORY_RE = re.compile(r"^/api/posts/([^/]+)/history$")
POST_DETAIL_RE = re.compile(r"^/api/posts/([^/]+)$")


def _parse_int(v, default, minimum=None, maximum=None):
    if v is None:
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_int", "not an integer")
    if minimum is not None and n < minimum:
        raise ApiError(400, "out_of_range", f"below minimum {minimum}")
    if maximum is not None and n > maximum:
        raise ApiError(400, "out_of_range", f"above maximum {maximum}")
    return n


def _validate_post_id(v: str) -> str:
    if not v or len(v) > 128 or not _ID_ALLOWED.match(v):
        raise ApiError(400, "invalid_post_id", "post id has invalid characters")
    return v


def lambda_handler(event, context):  # noqa: ARG001
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "GET")
    raw_path = event.get("rawPath", "")
    query = event.get("queryStringParameters") or {}

    if method == "OPTIONS":
        return _resp(204, {}, cache_seconds=600)

    if method != "GET":
        return _error(405, "method_not_allowed", f"{method} not allowed")

    try:
        tables = _get_tables()

        if raw_path == "/api/status":
            body = svc.build_status(tables["posts"], tables["fetch_runs"])
            return _resp(200, body, cache_seconds=60)

        if raw_path == "/api/rankings":
            r_type = query.get("type", "cumulative_views")
            if r_type not in svc.VALID_RANKING_TYPES:
                raise ApiError(400, "invalid_type", f"unknown ranking type: {r_type}")
            # Preserve the frontend contract: without ?limit/?cursor the API
            # returns the full sorted list so RankingsPage can slice locally
            # for its "もっと見る" button. Once frontend adopts cursor-based
            # pagination, pass ?limit=20 to receive nextCursor.
            limit = _parse_int(
                query.get("limit"),
                default=None,
                minimum=1,
                maximum=svc.MAX_RANKING_LIMIT,
            )
            cursor = query.get("cursor")
            body = svc.build_rankings_response(
                tables["posts"], tables["snapshots"], r_type, limit=limit, cursor=cursor,
            )
            return _resp(200, body, cache_seconds=300)

        m = POST_HISTORY_RE.match(raw_path)
        if m:
            post_id = _validate_post_id(unquote(m.group(1)))
            range_ = query.get("range", "7d")
            if range_ not in svc.VALID_RANGES:
                raise ApiError(400, "invalid_range", f"unknown range: {range_}")
            body = svc.build_post_history(tables["posts"], tables["snapshots"], post_id, range_)
            return _resp(200, body, cache_seconds=300)

        m = POST_DETAIL_RE.match(raw_path)
        if m:
            post_id = _validate_post_id(unquote(m.group(1)))
            body = svc.build_post_detail(tables["posts"], post_id)
            return _resp(200, body, cache_seconds=300)

        if raw_path == "/api/compare":
            range_ = query.get("range", "7d")
            scope = query.get("scope", "all")
            metric = query.get("metric", "viewCount")
            ids_raw = query.get("ids")
            ids = None
            if ids_raw:
                ids = [i for i in ids_raw.split(",") if i]
                for pid in ids:
                    _validate_post_id(pid)
            body = svc.build_compare(
                tables["posts"], tables["snapshots"], range_, scope=scope, ids=ids, metric=metric,
                fetch_runs_table=tables["fetch_runs"],
            )
            return _resp(200, body, cache_seconds=300)

        return _error(404, "not_found", "route not found")

    except ApiError as e:
        return _error(e.status, e.code, e.message)
    except Exception:
        log.exception("unhandled error in read API")
        return _error(500, "internal_error", "an internal error occurred")
