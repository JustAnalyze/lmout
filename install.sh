#!/bin/bash

# Exit on error
set -e

echo "🚀 Starting Lock Me Out installation..."

# 1. Install the tool using uv
echo "📦 Installing lmout via uv tool install..."
uv tool install --reinstall .

# 2. Get the absolute path of the installed binary, ignoring the local directory
echo "📍 Finding installed lmout path..."
LMOUT_PATH=$(PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "$(pwd)" | tr '\n' ':') which lmout)
echo "📍 lmout installed at: $LMOUT_PATH"

# 3. Create systemd user directory if it doesn't exist
mkdir -p "$HOME/.config/systemd/user/"

# 4. Generate/Update the systemd service file with the correct path
echo "⚙️ Configuring systemd user service..."
cat <<EOF >"$HOME/.config/systemd/user/lmout.service"
[Unit]
Description=Lock Me Out Daemon
After=network.target

[Service]
ExecStart=$LMOUT_PATH run
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

# 5. Reload systemd, enable and start the service
echo "🔄 Reloading systemd and starting service..."
systemctl --user daemon-reload
systemctl --user enable lmout.service
systemctl --user restart lmout.service

echo "✅ Installation complete!"
echo "✨ The lmout daemon is now running in the background and will start on boot."
echo "📋 You can check its status with: systemctl --user status lmout.service"
echo "🔍 You can view logs with: journalctl --user -u lmout.service -f"
echo ""
echo "Try running 'lmout list' to get started!"
