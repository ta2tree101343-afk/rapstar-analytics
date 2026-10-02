"""Collect RAPSTAR official Instagram media snapshots via Business Discovery.

Usage:
    python scripts/collect.py                                # full scan, upsert + snapshot
    python scripts/collect.py --mode new-only                # only detect new posts
    python scripts/collect.py --mode snapshots-only          # only append snapshots
    python scripts/collect.py --limit 10                     # cap items per run
    python scripts/collect.py --dry-run                      # no DB writes

Concurrent runs are prevented via an advisory file lock at data/collect.lock.
Token expiry warnings come from the local DB (populated by scripts/check_token.py).
Secrets are never printed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.config import PROJECT_ROOT, load_settings
from collector.db import make_engine, make_session_factory
from collector.ig_client import BusinessDiscoveryClient
from collector.lock import LockBusyError, exclusive_lock
from collector.pipeline import run_collection
from collector.token_warn import check_token_status


VALID_MODES = ("both", "new-only", "snapshots-only")
LOCK_PATH = PROJECT_ROOT / "data" / "collect.lock"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAPSTAR IG data collector")
    p.add_argument("--limit", type=int, default=None, help="Maximum media to fetch")
    p.add_argument("--mode", choices=VALID_MODES, default="both")
    p.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("collect")

    settings = load_settings()
    client = BusinessDiscoveryClient(settings)

    try:
        with exclusive_lock(LOCK_PATH):
            engine = make_engine(settings.database_url)
            session_factory = make_session_factory(engine)

            # Token expiry warning (DB-only, no API call, never prints token)
            status = check_token_status(session_factory)
            log.info(status.message())

            if args.dry_run:
                from collector.classifier import classify_caption

                seen = entry = unclassified = 0
                for item in client.iter_media(max_items=args.limit):
                    seen += 1
                    if classify_caption(item.get("caption")).status == "entry":
                        entry += 1
                    else:
                        unclassified += 1
                print(
                    f"[dry-run] mode={args.mode} seen={seen} entry={entry} "
                    f"unclassified={unclassified} api_calls={client.api_calls}"
                )
                return 0

            summary = run_collection(
                session_factory=session_factory,
                media_iter=client.iter_media(max_items=args.limit),
                api_call_getter=lambda: client.api_calls,
                mode=args.mode,
            )

            print(
                f"status={summary.status} mode={args.mode} "
                f"posts_seen={summary.posts_seen} new_posts={summary.new_posts} "
                f"snapshots={summary.snapshots_written} "
                f"api_calls={summary.api_calls} "
                f"classification={summary.classification_counts}"
            )
            if summary.error_message:
                print(f"error: {settings.redact_secrets(summary.error_message)}")
                return 2
            return 0
    except LockBusyError as e:
        print(f"[skip] {e}")
        return 75  # EX_TEMPFAIL-ish
    except KeyboardInterrupt:
        print("[interrupted]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
