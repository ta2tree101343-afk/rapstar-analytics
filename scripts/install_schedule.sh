#!/usr/bin/env bash
# Install the RAPSTAR Analytics collection launchd agent for the current user.
# Usage:
#     bash scripts/install_schedule.sh [HH] [MM]
# Defaults to 09:00 local time daily.
#
# The launchd agent runs `scripts/collect.py` daily. If the Mac is asleep at
# the scheduled time, launchd runs the job once when the Mac wakes.

set -euo pipefail

HOUR="${1:-9}"
MINUTE="${2:-0}"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$PROJECT_ROOT/scripts/schedule/com.rapstar-analytics.collect.plist.template"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT_PATH="$AGENT_DIR/com.rapstar-analytics.collect.plist"
LABEL="com.rapstar-analytics.collect"

if [ ! -f "$TEMPLATE" ]; then
    echo "template not found: $TEMPLATE" >&2
    exit 1
fi
if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo ".venv/bin/python が見つかりません。先に venv を作成し依存を入れてください。" >&2
    exit 1
fi

mkdir -p "$AGENT_DIR" "$PROJECT_ROOT/logs"

# If already loaded, unload first to apply changes cleanly.
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo "[info] existing agent detected; bootout first"
    launchctl bootout "gui/$(id -u)" "$AGENT_PATH" 2>/dev/null || true
fi

sed \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    -e "s|__HOUR__|$HOUR|g" \
    -e "s|__MINUTE__|$MINUTE|g" \
    "$TEMPLATE" > "$AGENT_PATH"

chmod 0644 "$AGENT_PATH"

launchctl bootstrap "gui/$(id -u)" "$AGENT_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "[ok] installed: $AGENT_PATH"
echo "     schedule: daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE") (local time)"
echo
echo "manual run    : launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "check status  : launchctl print gui/$(id -u)/$LABEL | grep -E 'state|last exit'"
echo "logs (stdout) : tail -f $PROJECT_ROOT/logs/collect.out.log"
echo "logs (stderr) : tail -f $PROJECT_ROOT/logs/collect.err.log"
echo "uninstall     : bash scripts/uninstall_schedule.sh"
