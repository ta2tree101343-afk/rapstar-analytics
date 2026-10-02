#!/usr/bin/env bash
# Fail if a SAM build directory contains files that must never ship inside a
# Lambda deployment package: production DBs, env files, repo-level data /
# backups / frontend trees, private keys / certificates.
#
# Usage:
#   scripts/check-sam-build.sh <path-to-sam-build-dir>
#
# Typical:
#   cd infrastructure
#   sam build --template-file template.yaml
#   ../scripts/check-sam-build.sh .aws-sam/build
#
#   sam build --template-file read-api-template.yaml \
#     --build-dir .aws-sam/build-read-api
#   ../scripts/check-sam-build.sh .aws-sam/build-read-api
#
# Exit codes:
#   0 — clean
#   1 — one or more sensitive entries found (deploy MUST NOT proceed)
#   2 — build directory missing / unusable
#
# Design notes:
# - This is a post-build guard. The primary defence is CodeUri scoping and
#   the Makefile builder (see infrastructure/collector-lambda/Makefile) —
#   this script is a second net for the day someone widens CodeUri or adds
#   a bad file.
# - `sam build --exclude` is NOT a file-level filter; do not rely on it.
# - Private-key patterns (*.pem/*.key/*.p12/*.pfx) are ALSO scanned. See the
#   false-positive note at the bottom of this file.
set -euo pipefail

BUILD_DIR="${1:-}"

if [ -z "$BUILD_DIR" ]; then
  echo "usage: $0 <sam-build-dir>" >&2
  exit 2
fi

if [ ! -d "$BUILD_DIR" ]; then
  echo "FAIL: build directory not found: $BUILD_DIR" >&2
  exit 2
fi

echo "scanning: $BUILD_DIR"

declare -i total_hits=0

report() {
  local label="$1"; shift
  # shellcheck disable=SC2124
  local matches
  matches="$(find "$BUILD_DIR" "$@" -print 2>/dev/null || true)"
  if [ -n "$matches" ]; then
    local count
    count="$(printf '%s\n' "$matches" | wc -l | tr -d ' ')"
    echo "  LEAK [$label] — $count match(es):"
    printf '%s\n' "$matches" | sed 's/^/    /'
    total_hits=$(( total_hits + count ))
  else
    echo "  OK   [$label]"
  fi
}

# --- Direct data leaks: production databases ---
report "database files"    -type f \( -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" \)

# --- Secrets ---
report "env files"         -type f -name ".env*"

# --- Repo-level directories that must never ship ---
report "data directory"    -type d -name "data"
report "backups directory" -type d -name "backups"
report "frontend tree"     -type d -name "frontend"
report "playwright dumps"  -type d -name ".playwright-mcp"

# --- Private keys / certificates ---
# NOTE: file-extension sweep is a precaution, not a precise detector.
# Documented legitimate match:
#   certifi/cacert.pem — public CA bundle shipped by the `certifi` package.
#     Not a secret, required at runtime for TLS. Exempted below.
# Everything else is flagged for human review:
#   *.pem elsewhere — unexpected (could be a leaked private key).
#   *.key           — rarely legitimate in a Python Lambda; always flag.
#   *.p12 / *.pfx   — no legitimate reason to appear in a Lambda zip.
report "PEM/key/certificates" -type f \
  \( -name "*.pem" -o -name "*.key" -o -name "*.p12" -o -name "*.pfx" \) \
  -not -path "*/certifi/cacert.pem"

echo
if [ "$total_hits" -gt 0 ]; then
  echo "FAIL: $total_hits sensitive entries detected in $BUILD_DIR"
  echo "      Do NOT run 'sam deploy' until these are removed from the build."
  exit 1
fi

echo "PASS: no disallowed artefacts in $BUILD_DIR"
