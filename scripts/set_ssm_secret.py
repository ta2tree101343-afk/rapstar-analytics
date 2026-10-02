"""Interactively store a SecureString into AWS SSM Parameter Store.

The secret value is read via getpass so it never appears on the command line,
in shell history, or in argparse-echoed help. The value is passed to boto3 in
memory and immediately dropped; no logging of the value at any point.

Usage:
    python scripts/set_ssm_secret.py --name /rapstar-analytics/ig-user-access-token
    python scripts/set_ssm_secret.py --name /rapstar-analytics/meta-app-secret

For non-secret values (App ID etc.) pass --type String:
    python scripts/set_ssm_secret.py --name /rapstar-analytics/meta-app-id --type String
"""

from __future__ import annotations

import argparse
import getpass
import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Interactively set an SSM parameter without CLI exposure")
    p.add_argument("--name", required=True, help="Full parameter name, e.g. /rapstar-analytics/ig-user-access-token")
    p.add_argument("--type", choices=["SecureString", "String"], default="SecureString")
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--profile", default=None, help="AWS CLI profile name")
    p.add_argument("--no-overwrite", action="store_true", help="Fail if parameter already exists (default: overwrite)")
    return p.parse_args()


def _fingerprint(v: str) -> str:
    if len(v) <= 12:
        return "***"
    return f"len={len(v)} head={v[:4]}... tail=...{v[-4:]}"


def main() -> int:
    args = parse_args()

    prompt1 = f"Enter value for {args.name}: "
    prompt2 = f"Re-enter value to confirm:      "

    try:
        v1 = getpass.getpass(prompt1)
        if not v1.strip():
            print("[error] empty value; aborting.")
            return 2
        v2 = getpass.getpass(prompt2)
    except (EOFError, KeyboardInterrupt):
        print("\n[abort] user cancelled.")
        return 130

    if v1 != v2:
        print("[error] values did not match; aborting.")
        return 3

    # Strip only surrounding whitespace/newlines that come from paste artifacts.
    value = v1.strip()

    # Fingerprint for confirmation log (no secret leakage)
    print(f"[info] {args.name}: {_fingerprint(value)}  type={args.type}")

    try:
        session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
        client = session.client("ssm", region_name=args.region)
        kwargs = {
            "Name": args.name,
            "Value": value,
            "Type": args.type,
            "Overwrite": not args.no_overwrite,
        }
        if args.type == "SecureString":
            kwargs["KeyId"] = "alias/aws/ssm"  # AWS-managed key, no extra cost
        resp = client.put_parameter(**kwargs)
        del value  # eagerly drop from memory
    except (NoCredentialsError, ProfileNotFound) as e:
        print(f"[error] AWS credentials not configured: {e}")
        return 4
    except ClientError as e:
        print(f"[error] SSM put_parameter failed: {e.response.get('Error', {}).get('Code')}")
        return 5

    print(f"[ok] stored {args.name} (version={resp.get('Version')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
