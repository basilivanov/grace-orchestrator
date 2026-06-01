#!/bin/bash
# Install GRACE Control Plane as a systemd service
# Usage: bash deploy/install.sh

set -e

SERVICE="grace-orchestrator"
UNIT_FILE="/etc/systemd/system/${SERVICE}.service"

echo "=== GRACE Control Plane Installer ==="
echo ""

# Check if running as root for systemd install
if [ "$EUID" -ne 0 ]; then
    echo "This script needs root to install systemd service."
    echo "Re-running with sudo..."
    exec sudo bash "$0" "$@"
fi

# Copy service file
cp deploy/grace-orchestrator.service "$UNIT_FILE"

# Replace %h with actual home
HOME_DIR=$(eval echo ~${SUDO_USER:-$USER})
sed -i "s|%h|$HOME_DIR|g" "$UNIT_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

echo ""
echo "Service installed and started!"
echo ""
echo "  Status:  systemctl status $SERVICE"
echo "  Logs:    journalctl -u $SERVICE -f"
echo "  Stop:    systemctl stop $SERVICE"
echo ""
echo "Dashboard: http://127.0.0.1:8042/"

# Show initial status
sleep 2
systemctl status "$SERVICE" --no-pager 2>/dev/null || true
