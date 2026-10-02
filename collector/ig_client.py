from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from .config import Settings


GRAPH_HOST = "https://graph.facebook.com"

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count,view_count"
)


class InstagramAPIError(RuntimeError):
    """Raised when the Graph API returns an error we cannot recover from mid-run."""


@dataclass(frozen=True)
class PageResult:
    items: list[dict[str, Any]]
    after: str | None


class BusinessDiscoveryClient:
    def __init__(self, settings: Settings, page_size: int = 25, request_gap_sec: float = 1.0):
        self._settings = settings
        self._page_size = page_size
        self._request_gap_sec = request_gap_sec
        self.api_calls = 0

    def _url(self) -> str:
        return f"{GRAPH_HOST}/{self._settings.api_version}/{self._settings.my_ig_user_id}"

    def _bd_fields(self, after: str | None) -> str:
        media_expr = f"media.limit({self._page_size})"
        if after:
            media_expr += f".after({after})"
        media_expr += f"{{{MEDIA_FIELDS}}}"
        return (
            f"business_discovery.username({self._settings.target_username})"
            f"{{id,username,media_count,{media_expr}}}"
        )

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        self.api_calls += 1
        resp = requests.get(self._url(), params=params, timeout=30)
        try:
            data = resp.json()
        except ValueError:
            body = self._settings.redact_secrets(resp.text[:500])
            raise InstagramAPIError(
                f"Graph API がJSON以外を返しました: status={resp.status_code} body={body}"
            )
        if resp.status_code >= 400:
            body = self._settings.redact_secrets(
                json.dumps(data, ensure_ascii=False, indent=2)
            )
            raise InstagramAPIError(f"Graph API エラー: status={resp.status_code} body={body}")
        return data

    def fetch_page(self, after: str | None = None) -> PageResult:
        data = self._call({
            "fields": self._bd_fields(after),
            "access_token": self._settings.access_token,
        })
        bd = data.get("business_discovery") or {}
        media = bd.get("media") or {}
        items = media.get("data") or []
        paging = media.get("paging") or {}
        cursors = paging.get("cursors") or {}
        next_after = cursors.get("after") if items else None
        return PageResult(items=items, after=next_after)

    def iter_media(self, max_items: int | None = None) -> Iterator[dict[str, Any]]:
        after: str | None = None
        yielded = 0
        seen_after: set[str] = set()
        while True:
            page = self.fetch_page(after=after)
            if not page.items:
                break
            for item in page.items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not page.after or page.after in seen_after:
                break
            seen_after.add(page.after)
            after = page.after
            if self._request_gap_sec > 0:
                time.sleep(self._request_gap_sec)
