"""AWS Lambda entry point for the collector.

Handler: `collector.aws.handler.lambda_handler`

Environment variables (set by SAM template):
    IG_BUSINESS_ACCOUNT_ID      - your IG Business Account ID
    TARGET_IG_USERNAME          - the account whose media to fetch
    GRAPH_API_VERSION           - e.g. v26.0
    IG_TOKEN_PARAM              - SSM param name storing the user access token
    META_APP_SECRET_PARAM       - SSM param name storing app secret
    META_APP_ID_PARAM           - SSM param name storing app id (plain-text OK)
    POSTS_TABLE                 - DynamoDB table names
    SNAPSHOTS_TABLE
    FETCH_RUNS_TABLE
    TOKEN_AUDIT_TABLE
    LOCK_TABLE
    LOCK_TTL_SECONDS            - default 900
    COLLECT_MODE                - 'both' | 'new-only' | 'snapshots-only' (default 'both')
    COLLECT_LIMIT               - optional max media per run
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

from ..classifier import classify_caption
from ..config import Settings
from ..ig_client import BusinessDiscoveryClient, InstagramAPIError
from ..pipeline import RunSummary
from ..repositories import (
    FetchRunRecord,
    PostRecord,
    SnapshotRecord,
    TokenAuditRecord,
)
from ..repositories.dynamodb_impl import build_dynamodb_repositories
from ..token_manager import (
    build_app_access_token,
    call_debug_token,
    fingerprint,
)
from .secrets import SSMSecretProvider


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_settings(secrets: SSMSecretProvider) -> tuple[Settings, str, str]:
    token = secrets.get(os.environ["IG_TOKEN_PARAM"], decrypt=True)
    app_secret = secrets.get(os.environ["META_APP_SECRET_PARAM"], decrypt=True)
    app_id = secrets.get(os.environ["META_APP_ID_PARAM"], decrypt=False)
    settings = Settings(
        access_token=token,
        my_ig_user_id=os.environ["IG_BUSINESS_ACCOUNT_ID"],
        target_username=os.environ.get("TARGET_IG_USERNAME", "rapstar_starz"),
        api_version=os.environ.get("GRAPH_API_VERSION", "v26.0"),
        database_url="",  # not used in Lambda
    )
    return settings, app_id, app_secret


def _emit_token_metric(days_remaining: float) -> None:
    """Publish a CloudWatch custom metric so an alarm can fire on <7 days."""
    try:
        cw = boto3.client("cloudwatch")
        cw.put_metric_data(
            Namespace="RapstarAnalytics",
            MetricData=[{
                "MetricName": "TokenDaysRemaining",
                "Value": float(days_remaining),
                "Unit": "None",
            }],
        )
    except Exception:  # noqa: BLE001 — metrics must never break the collector
        log.exception("failed to publish TokenDaysRemaining metric")


def _emit_run_metrics(
    summary: RunSummary,
    meta_api_failure: bool,
    run_id: str,
) -> None:
    """Emit application-level run metrics via CloudWatch Embedded Metric Format.

    Written as a single JSON line to stdout; CloudWatch Logs' EMF parser
    picks up the `_aws` envelope and projects the fields listed under
    `Metrics` into `RapstarAnalytics` namespace. Dimensions are intentionally
    low-cardinality (FunctionName, Environment); `runId` is included as a
    searchable log field only — it is NOT a dimension and so does not
    multiply metric cost.

    MetaApiFailure=1 is set ONLY when the outer collection loop was aborted
    by an `InstagramAPIError` (i.e. Instagram Graph API refused the request
    for an app- or token-level reason). A `TokenManagerError` during
    best-effort token debug does NOT flip this flag — if the main collection
    then succeeds, the run as a whole is still Success.

    Never raises: EMF emission is best-effort just like `_emit_token_metric`.
    """
    try:
        emf = {
            "_aws": {
                "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": "RapstarAnalytics",
                    "Dimensions": [["FunctionName", "Environment"]],
                    "Metrics": [
                        {"Name": "CollectorRunSuccess", "Unit": "Count"},
                        {"Name": "CollectorRunPartial", "Unit": "Count"},
                        {"Name": "CollectorRunFailure", "Unit": "Count"},
                        {"Name": "MetaApiFailure",      "Unit": "Count"},
                        {"Name": "SnapshotsWritten",    "Unit": "Count"},
                    ],
                }],
            },
            "FunctionName": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown"),
            "Environment":  os.environ.get("ENVIRONMENT", "prod"),
            "runId": run_id,
            "status": summary.status,
            "CollectorRunSuccess": 1 if summary.status == "success" else 0,
            "CollectorRunPartial": 1 if summary.status == "partial" else 0,
            "CollectorRunFailure": 1 if summary.status == "error"   else 0,
            "MetaApiFailure":      1 if meta_api_failure else 0,
            "SnapshotsWritten":    int(summary.snapshots_written or 0),
        }
        # EMF spec: single JSON line to stdout. `print` is fine with Lambda
        # LogFormat=Text — CloudWatch Logs recognises the `_aws` envelope and
        # extracts metrics automatically.
        print(json.dumps(emf, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — metrics must never break the collector
        log.exception("failed to emit run EMF metrics")


def lambda_handler(event, context):  # noqa: ARG001
    logging.basicConfig(level=logging.INFO)
    secrets = SSMSecretProvider()
    settings, app_id, app_secret = _load_settings(secrets)

    repos = build_dynamodb_repositories(
        posts_table_name=os.environ["POSTS_TABLE"],
        snapshots_table_name=os.environ["SNAPSHOTS_TABLE"],
        fetch_runs_table_name=os.environ["FETCH_RUNS_TABLE"],
        token_audit_table_name=os.environ["TOKEN_AUDIT_TABLE"],
        lock_table_name=os.environ["LOCK_TABLE"],
    )

    holder_id = str(uuid.uuid4())
    ttl_seconds = int(os.environ.get("LOCK_TTL_SECONDS", "900"))
    if not repos["lock"].try_acquire(holder_id, ttl_seconds):
        log.warning("another collector run is in progress; skipping")
        return {"status": "skipped_locked"}

    try:
        try:
            debug = call_debug_token(
                settings.access_token,
                build_app_access_token(app_id, app_secret),
                settings.api_version,
            )
            repos["token_audit"].record(TokenAuditRecord(
                recorded_at=_now(),
                token_fingerprint=fingerprint(settings.access_token),
                token_type=debug.token_type,
                issued_at=debug.issued_at,
                expires_at=debug.expires_at,
                data_access_expires_at=debug.data_access_expires_at,
                scopes=",".join(debug.scopes) if debug.scopes else None,
                source="lambda",
            ))
            if debug.expires_at is not None:
                days = debug.days_until_expiry()
                if days is not None:
                    _emit_token_metric(days)
        except Exception:  # noqa: BLE001 — token diagnostics are best-effort
            log.exception("token debug failed; continuing")

        client = BusinessDiscoveryClient(settings, request_gap_sec=0.5)
        mode = os.environ.get("COLLECT_MODE", "both")
        limit_env = os.environ.get("COLLECT_LIMIT")
        max_items = int(limit_env) if limit_env else None

        run_id = repos["fetch_runs"].start(_now())
        summary = RunSummary(classification_counts={})
        started_at = _now()
        meta_api_failure = False

        try:
            for item in client.iter_media(max_items=max_items):
                summary.posts_seen += 1
                fetched_at = _now()
                try:
                    was_new = _persist(repos, item, fetched_at, mode)
                    if was_new:
                        summary.new_posts += 1
                    if mode != "new-only" and (mode != "snapshots-only" or not was_new):
                        summary.snapshots_written += 1
                except Exception:  # noqa: BLE001 — per-item isolation
                    log.exception("failed to persist media %s", item.get("id"))
                    summary.status = "partial"
                cls = classify_caption(item.get("caption")).status
                counts = summary.classification_counts or {}
                counts[cls] = counts.get(cls, 0) + 1
                summary.classification_counts = counts
        except InstagramAPIError as e:
            # Meta Graph API-level refusal (HTTP ≥ 400, non-JSON body, etc.).
            # We tag this separately from a generic failure so the operator
            # can distinguish "our bug" from "Meta rejected us".
            summary.status = "error"
            summary.error_message = settings.redact_secrets(str(e))
            meta_api_failure = True
        except Exception as e:  # noqa: BLE001
            summary.status = "error"
            summary.error_message = settings.redact_secrets(str(e))
        finally:
            summary.api_calls = client.api_calls
            repos["fetch_runs"].finalize(FetchRunRecord(
                run_id=run_id,
                started_at=started_at,
                finished_at=_now(),
                status=summary.status,
                posts_seen=summary.posts_seen,
                new_posts=summary.new_posts,
                snapshots_written=summary.snapshots_written,
                api_calls=summary.api_calls,
                error_message=summary.error_message,
            ))
            # Emit application metrics via EMF. Separate try/except inside so
            # that even if fetch_runs.finalize raised, we still surface the
            # run result to CloudWatch Metrics (and vice versa).
            _emit_run_metrics(summary, meta_api_failure, run_id)

        return {
            "status": summary.status,
            "posts_seen": summary.posts_seen,
            "new_posts": summary.new_posts,
            "snapshots_written": summary.snapshots_written,
            "api_calls": summary.api_calls,
            "classification": summary.classification_counts,
        }
    finally:
        repos["lock"].release(holder_id)


def _persist(repos, item: dict, fetched_at: datetime, mode: str) -> bool:
    """Persist a single media item. Returns was_new_post."""
    from ..pipeline import _parse_ig_timestamp

    external_id = item.get("id")
    if not external_id:
        return False
    posted_at = _parse_ig_timestamp(item.get("timestamp"))
    permalink = item.get("permalink") or ""
    if posted_at is None or not permalink:
        log.warning("skip media %s: missing timestamp or permalink", external_id)
        return False

    caption = item.get("caption")
    cls = classify_caption(caption)
    existing = repos["posts"].get(external_id)
    was_new = existing is None

    if existing is None:
        if mode == "snapshots-only":
            return False
        repos["posts"].upsert(PostRecord(
            external_post_id=external_id,
            rapper_name=cls.rapper_name,
            permalink=permalink,
            posted_at=posted_at,
            caption=caption,
            media_type=item.get("media_type"),
            media_product_type=item.get("media_product_type"),
            classification=cls.status,
            first_seen_at=fetched_at,
            last_seen_at=fetched_at,
            latest_view_count=item.get("view_count") if mode != "new-only" else None,
            latest_like_count=item.get("like_count") if mode != "new-only" else None,
            latest_comments_count=item.get("comments_count") if mode != "new-only" else None,
            latest_fetched_at=fetched_at if mode != "new-only" else None,
        ))
    else:
        promoted = (existing.classification == "unclassified" and cls.status == "entry")
        merged = PostRecord(
            external_post_id=existing.external_post_id,
            rapper_name=existing.rapper_name or cls.rapper_name,
            permalink=existing.permalink,
            posted_at=existing.posted_at,
            caption=caption,
            media_type=item.get("media_type") or existing.media_type,
            media_product_type=item.get("media_product_type") or existing.media_product_type,
            classification="entry" if promoted else existing.classification,
            first_seen_at=existing.first_seen_at,
            last_seen_at=fetched_at,
            latest_view_count=existing.latest_view_count,
            latest_like_count=existing.latest_like_count,
            latest_comments_count=existing.latest_comments_count,
            latest_fetched_at=existing.latest_fetched_at,
        )
        repos["posts"].upsert(merged)

    if mode == "new-only":
        return was_new

    if mode == "snapshots-only" and was_new:
        return False

    repos["snapshots"].append(SnapshotRecord(
        external_post_id=external_id,
        fetched_at=fetched_at,
        view_count=item.get("view_count"),
        like_count=item.get("like_count"),
        comments_count=item.get("comments_count"),
    ))
    repos["posts"].update_latest_metrics(
        external_post_id=external_id,
        fetched_at=fetched_at,
        view_count=item.get("view_count"),
        like_count=item.get("like_count"),
        comments_count=item.get("comments_count"),
    )
    return was_new
