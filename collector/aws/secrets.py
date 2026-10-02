from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import boto3


class SSMSecretProvider:
    """Reads secrets from AWS SSM Parameter Store SecureString.

    Parameter names are configured via environment variables so the SAM template
    can wire them without embedding secret values.
    """

    def __init__(self, region: Optional[str] = None):
        self._region = region or os.environ.get("AWS_REGION", "ap-northeast-1")
        self._client = boto3.client("ssm", region_name=self._region)

    @lru_cache(maxsize=8)
    def get(self, parameter_name: str, decrypt: bool = True) -> str:
        resp = self._client.get_parameter(Name=parameter_name, WithDecryption=decrypt)
        return resp["Parameter"]["Value"]
