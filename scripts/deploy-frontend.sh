#!/usr/bin/env bash
# Deploy the frontend bundle to the private S3 bucket fronted by CloudFront.
#
# USAGE:
#   STACK=rapstar-analytics-frontend-prod scripts/deploy-frontend.sh
# or:
#   scripts/deploy-frontend.sh --stack rapstar-analytics-frontend-prod
# or explicit:
#   scripts/deploy-frontend.sh --bucket <name> --distribution-id <id>
#
# Bucket name and CloudFront distribution ID are NEVER hard-coded here.
# Either:
#   * `--stack <name>`  — the script reads outputs from the CloudFormation stack
#   * `--bucket <b>` + `--distribution-id <d>` — explicit override
#   * `$STACK`          — same as `--stack` via env var
#
# Flow:
#   1. frontend install + build + typecheck + test
#   2. basic secret / localhost scan on the built dist
#   3. resolve bucket + distribution from the CFN stack (or args)
#   4. sync /assets with immutable 1y cache (hashed filenames)
#   5. copy /index.html with no-cache (shell of the SPA)
#   6. CloudFront invalidation for ONLY /index.html
#
# NOTE: Hashed assets are content-addressed by Vite, so they are never
# overwritten in-place — we don't need to invalidate /assets/*.
set -euo pipefail

# --------- CLI parsing ---------
STACK="${STACK:-}"
BUCKET=""
DIST_ID=""
REGION="${AWS_REGION:-ap-northeast-1}"
SKIP_BUILD=0

while [ $# -gt 0 ]; do
  case "$1" in
    --stack)            STACK="$2";    shift 2 ;;
    --bucket)           BUCKET="$2";   shift 2 ;;
    --distribution-id)  DIST_ID="$2";  shift 2 ;;
    --region)           REGION="$2";   shift 2 ;;
    --skip-build)       SKIP_BUILD=1;  shift ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
DIST_DIR="$FRONTEND_DIR/dist"

echo "==> repo:     $REPO_ROOT"
echo "==> region:   $REGION"
if [ -n "$STACK" ]; then
  echo "==> stack:    $STACK"
fi

# --------- 1. build + typecheck + test (unless --skip-build) ---------
if [ "$SKIP_BUILD" -eq 0 ]; then
  cd "$FRONTEND_DIR"
  echo "==> npm ci"
  npm ci
  echo "==> npm run build"
  rm -rf "$DIST_DIR"
  npm run build
  echo "==> npx tsc -b"
  npx tsc -b
  echo "==> npm run test"
  npm run test -- --run
else
  echo "==> --skip-build set; using existing $DIST_DIR"
fi

# --------- 2. sanity checks on dist ---------
if [ ! -f "$DIST_DIR/index.html" ] || [ ! -d "$DIST_DIR/assets" ]; then
  echo "FAIL: $DIST_DIR missing expected index.html / assets/" >&2
  exit 1
fi

echo "==> scanning dist for obvious leaks"
leak_hits=0
for pattern in \
    "localhost" \
    "127\.0\.0\.1" \
    "VITE_" \
    "AKIA[0-9A-Z]{16}" \
    "aws_secret_access_key" \
    "-----BEGIN [A-Z ]*PRIVATE KEY-----" \
    ; do
  # grep -c returns 1 when there are zero matches — with pipefail active
  # that would abort the loop. `|| true` keeps the pipeline exit 0.
  n=$( { grep -rIEc "$pattern" "$DIST_DIR" 2>/dev/null || true; } | awk -F: '{s+=$2} END {print s+0}')
  if [ "$n" -gt 0 ]; then
    echo "  WARN pattern '$pattern' appears $n time(s)"
    leak_hits=$(( leak_hits + n ))
  fi
done
# `password` is a React form-input constant — not actionable; `token` can
# legitimately appear in Rechart or lexer code — also not actionable. Add
# both to the scan allowlist by NOT including them above.

if [ "$leak_hits" -gt 0 ]; then
  echo "FAIL: $leak_hits suspicious strings in $DIST_DIR — resolve before deploy." >&2
  exit 1
fi
echo "   OK: no obvious leaks."

# --------- 3. resolve bucket + distribution-id ---------
if [ -z "$BUCKET" ] || [ -z "$DIST_ID" ]; then
  if [ -z "$STACK" ]; then
    echo "FAIL: provide --stack <name>, or both --bucket and --distribution-id." >&2
    exit 2
  fi
  echo "==> resolving stack outputs from $STACK"
  outputs="$(aws cloudformation describe-stacks \
    --region "$REGION" \
    --stack-name "$STACK" \
    --query 'Stacks[0].Outputs' --output json)"
  [ -z "$BUCKET" ]  && BUCKET=$(echo "$outputs"  | python3 -c "import json,sys; [print(o['OutputValue']) for o in json.load(sys.stdin) if o['OutputKey']=='FrontendBucketName']")
  [ -z "$DIST_ID" ] && DIST_ID=$(echo "$outputs" | python3 -c "import json,sys; [print(o['OutputValue']) for o in json.load(sys.stdin) if o['OutputKey']=='CloudFrontDistributionId']")
fi

if [ -z "$BUCKET" ] || [ -z "$DIST_ID" ]; then
  echo "FAIL: could not resolve BUCKET='$BUCKET' / DIST_ID='$DIST_ID'" >&2
  exit 2
fi
echo "==> bucket:        $BUCKET"
echo "==> distribution:  $DIST_ID"

# --------- 4. upload /assets with long-cache immutable headers ---------
# These filenames are content-hashed by Vite (`index-<hash>.js`), so they
# are safe to cache for a year. `--delete` prunes assets from previous
# builds that are no longer referenced.
echo "==> aws s3 sync assets/ (long-cache, immutable)"
aws s3 sync "$DIST_DIR/assets/" "s3://$BUCKET/assets/" \
  --region "$REGION" \
  --delete \
  --cache-control "public,max-age=31536000,immutable"

# --------- 5. upload everything else EXCEPT index.html with mid cache ---------
# Covers any `public/` static files (favicon.ico, robots.txt, PNGs, nested
# directories like `/images/*`) that Vite copied into dist/ at the top level.
# `sync` descends into subdirectories, so `public/images/logo.svg` lands at
# `s3://BUCKET/images/logo.svg` with the mid-term cache below.
# Excludes:
#   - assets/*   — already handled above with immutable 1y
#   - index.html — handled below with no-cache
echo "==> aws s3 sync (public/ static tree, mid-cache)"
aws s3 sync "$DIST_DIR/" "s3://$BUCKET/" \
  --region "$REGION" \
  --delete \
  --exclude "assets/*" \
  --exclude "index.html" \
  --cache-control "public,max-age=3600"

# --------- 6. upload index.html last with no-cache ---------
# The entry document must be revalidated on every visit so a new deploy
# takes effect without /* invalidation. CloudFront + our origin-driven cache
# policy honor the Cache-Control header below. We upload LAST so clients
# never see a fresh index.html pointing to assets that haven't been
# published yet.
echo "==> aws s3 cp index.html (no-cache)"
aws s3 cp "$DIST_DIR/index.html" "s3://$BUCKET/index.html" \
  --region "$REGION" \
  --cache-control "no-cache" \
  --content-type "text/html; charset=utf-8"

# --------- 6. targeted CloudFront invalidation ---------
echo "==> cloudfront create-invalidation (/index.html only)"
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/index.html" \
  --query 'Invalidation.{Id:Id,Status:Status,Paths:InvalidationBatch.Paths.Items}'

echo
echo "DONE. Give CloudFront ~30s to settle the invalidation."
