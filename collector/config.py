from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "rapstar.db"


@dataclass(frozen=True)
class Settings:
    access_token: str
    my_ig_user_id: str
    target_username: str
    api_version: str
    database_url: str

    def redact_secrets(self, text: str) -> str:
        for s in (self.access_token,):
            if s:
                text = text.replace(s, "***REDACTED***")
        return text


def load_settings(require_credentials: bool = True) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    def _get(key: str, default: str | None = None, required: bool = True) -> str:
        val = os.environ.get(key, default)
        if required and not val:
            raise RuntimeError(f"環境変数 {key} が未設定です。.env を確認してください。")
        return val or ""

    access_token = _get("IG_USER_ACCESS_TOKEN", required=require_credentials)
    my_ig_user_id = _get("IG_BUSINESS_ACCOUNT_ID", required=require_credentials)
    target_username = _get("TARGET_IG_USERNAME", default="rapstar_starz", required=False)
    api_version = _get("GRAPH_API_VERSION", default="v26.0", required=False)
    database_url = _get(
        "DATABASE_URL",
        default=f"sqlite:///{DEFAULT_DB_PATH}",
        required=False,
    )
    return Settings(
        access_token=access_token,
        my_ig_user_id=my_ig_user_id,
        target_username=target_username,
        api_version=api_version,
        database_url=database_url,
    )
