from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from .db import AccessTokenRecord


@dataclass(frozen=True)
class TokenStatus:
    status: str  # 'ok' | 'warn' | 'expired' | 'unknown'
    days_remaining: float | None
    expires_at: datetime | None
    fingerprint: str | None

    def message(self) -> str:
        if self.status == "unknown":
            return "[TOKEN] 有効期限情報なし。scripts/check_token.py を実行して記録してください。"
        if self.status == "expired":
            return f"[TOKEN_EXPIRED] fingerprint={self.fingerprint} expires_at={self.expires_at}"
        if self.status == "warn":
            return (
                f"[TOKEN_EXPIRES_SOON] fingerprint={self.fingerprint} "
                f"days_remaining={self.days_remaining:.1f}"
            )
        return f"[TOKEN] ok days_remaining={self.days_remaining:.1f}"


def check_token_status(session_factory, warn_days: float = 7.0) -> TokenStatus:
    """Look up the most recent access_tokens row and classify its remaining validity.

    Does not make any API call. Uses only DB state populated by check_token / exchange_token.
    """
    with session_factory() as session:
        row = session.execute(
            select(AccessTokenRecord).order_by(AccessTokenRecord.id.desc()).limit(1)
        ).scalar_one_or_none()

    if row is None or row.expires_at is None:
        return TokenStatus(
            status="unknown",
            days_remaining=None,
            expires_at=None,
            fingerprint=row.token_fingerprint if row else None,
        )

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        # SQLite stores naive datetimes; we always write UTC, so re-attach UTC on read.
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    remaining_sec = (expires_at - now).total_seconds()
    days = remaining_sec / 86400.0
    if remaining_sec <= 0:
        status = "expired"
    elif days < warn_days:
        status = "warn"
    else:
        status = "ok"
    return TokenStatus(
        status=status,
        days_remaining=days,
        expires_at=expires_at,
        fingerprint=row.token_fingerprint,
    )
