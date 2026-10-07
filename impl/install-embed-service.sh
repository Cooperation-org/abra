#!/usr/bin/env bash
# Install the abra embed service as a macOS login agent (starts at login, restarts on exit).
# Re-run after moving the repo or venv. Remove: launchctl bootout gui/$(id -u)/local.abra.embed
set -euo pipefail

IMPL_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$IMPL_DIR/.venv/bin/python"
SERVER="$IMPL_DIR/pgvector/embed_server.py"
LABEL="local.abra.embed"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.abra/embed.log"

[ -x "$PYTHON" ] || { echo "venv missing: $PYTHON" >&2; exit 1; }
mkdir -p "$HOME/.abra" "$HOME/Library/LaunchAgents"

# Cache the model now so the agent can start offline.
"$PYTHON" -c "import sys; sys.path.insert(0, '$IMPL_DIR/pgvector'); import embedding; embedding.local_model()"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SERVER</string>
    </array>
    <key>WorkingDirectory</key><string>$IMPL_DIR/pgvector</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HF_HUB_OFFLINE</key><string>1</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardErrorPath</key><string>$LOG</string>
    <key>StandardOutPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST (log: $LOG)"
