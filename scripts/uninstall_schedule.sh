#!/usr/bin/env bash
set -euo pipefail

AGENT_PATH="$HOME/Library/LaunchAgents/com.rapstar-analytics.collect.plist"
LABEL="com.rapstar-analytics.collect"

if [ -f "$AGENT_PATH" ]; then
    launchctl bootout "gui/$(id -u)" "$AGENT_PATH" 2>/dev/null || true
    rm -f "$AGENT_PATH"
    echo "[ok] uninstalled: $AGENT_PATH"
else
    echo "[info] not installed"
fi
