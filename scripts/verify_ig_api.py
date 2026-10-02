"""Instagram Graph API 疎通検証スクリプト (STEP 0)

前提:
- 自分の Instagram Business/Creator アカウントを Facebook ページに連携済み
- Meta App (Business) を作成し Instagram Graph API 製品を追加済み
- 必要権限 (instagram_basic, instagram_manage_insights, pages_read_engagement) を
  含む長期ユーザートークンを取得済み

使い方:
    python -m venv .venv && source .venv/bin/activate
    pip install requests python-dotenv
    cp .env.example .env  # 値を埋める
    python scripts/verify_ig_api.py

このスクリプトは *取得結果を捏造しない*。API が返さなかった項目は None のまま出力する。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests
from dotenv import load_dotenv


GRAPH_HOST = "https://graph.facebook.com"


def get_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"[FATAL] 環境変数 {key} が未設定です。.env を確認してください。")
    return val


def _redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***REDACTED***")
    return text


def call(url: str, params: dict[str, Any]) -> dict[str, Any]:
    resp = requests.get(url, params=params, timeout=30)
    token = params.get("access_token", "")
    try:
        data = resp.json()
    except ValueError:
        body = _redact(resp.text[:500], [token])
        sys.exit(f"[FATAL] レスポンスが JSON ではありません: status={resp.status_code} body={body}")
    if resp.status_code >= 400:
        body = _redact(json.dumps(data, ensure_ascii=False, indent=2), [token])
        print(f"[ERROR] status={resp.status_code}")
        print(body)
        sys.exit(1)
    return data


def main() -> None:
    load_dotenv()
    access_token = get_env("IG_USER_ACCESS_TOKEN")
    my_ig_user_id = get_env("IG_BUSINESS_ACCOUNT_ID")
    target_username = os.environ.get("TARGET_IG_USERNAME", "rapstar_starz")
    api_version = os.environ.get("GRAPH_API_VERSION", "v26.0")

    print(f"=== Instagram Graph API 疎通検証 ===")
    print(f"API バージョン    : {api_version}")
    print(f"自分の IG User ID : {my_ig_user_id}")
    print(f"対象アカウント     : @{target_username}")
    print()

    print("--- STEP A: 自分の IG Business Account 情報を取得 ---")
    me_url = f"{GRAPH_HOST}/{api_version}/{my_ig_user_id}"
    me = call(me_url, {
        "fields": "id,username,name,account_type,followers_count,media_count",
        "access_token": access_token,
    })
    print(json.dumps(me, ensure_ascii=False, indent=2))
    print()

    print(f"--- STEP B: business_discovery で @{target_username} の User 情報を取得 ---")
    bd_user_fields = f"business_discovery.username({target_username}){{id,username,followers_count,media_count}}"
    bd_user = call(me_url, {
        "fields": bd_user_fields,
        "access_token": access_token,
    })
    print(json.dumps(bd_user, ensure_ascii=False, indent=2))
    print()

    if "business_discovery" not in bd_user:
        sys.exit(f"[FATAL] business_discovery が返りません。対象アカウントが Business/Creator でない、"
                 f"または非公開の可能性があります。")

    print(f"--- STEP C: business_discovery で @{target_username} の最新メディアを最大3件取得 ---")
    media_fields = (
        "id,caption,media_type,media_product_type,media_url,permalink,timestamp,"
        "thumbnail_url,like_count,comments_count,view_count,is_shared_to_feed"
    )
    bd_media = call(me_url, {
        "fields": f"business_discovery.username({target_username}){{media.limit(3){{{media_fields}}}}}",
        "access_token": access_token,
    })
    print(json.dumps(bd_media, ensure_ascii=False, indent=2))
    print()

    print("--- STEP D: 取得可否サマリ ---")
    items = (bd_media.get("business_discovery", {}).get("media", {}).get("data") or [])
    if not items:
        print("[WARN] メディアが1件も返りませんでした。")
    else:
        wanted = media_fields.split(",")
        for i, m in enumerate(items, 1):
            present = [f for f in wanted if f in m and m[f] is not None]
            absent = [f for f in wanted if f not in m or m[f] is None]
            print(f"[Media #{i}] permalink={m.get('permalink')}")
            print(f"  取得できた   : {present}")
            print(f"  取得できず   : {absent}")

    print()
    print("=== 完了。上記結果を STEP 1 の設計に反映します。 ===")


if __name__ == "__main__":
    main()
