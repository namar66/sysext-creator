#!/bin/bash
set -euo pipefail

# ======================================================================
# UNINSTALL LOGIC
# ======================================================================
if [[ "${1:-}" == "uninstall" ]]; then
    echo "🧹 Starting complete and safe removal of Sysext-Creator..."

    echo "=> Stopping services and timers..."
    systemctl --user stop sysext-update.timer sysext-update.service 2>/dev/null || true
    systemctl --user disable sysext-update.timer 2>/dev/null || true

    # Cleanup legacy Healer
    sudo systemctl stop sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
    sudo systemctl disable sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-heal.service
    sudo rm -f /etc/systemd/system/sysext-creator-heal.timer
    sudo rm -f /usr/local/bin/sysext-creator-healer

    sudo systemctl stop sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo systemctl disable sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.path
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.service
    sudo systemctl daemon-reload

    echo ""
    read -p "Do you want to remove ALL installed raw images in /var/lib/extensions? (yes/no): " remove_all
    if [[ "$remove_all" == "yes" ]]; then
        echo "=> Removing ALL RAW images..."
        sudo rm -f /var/lib/extensions/*.raw
    else
        echo "=> Removing only Sysext-Creator..."
        sudo rm -f /var/lib/extensions/sysext-creator*.raw
    fi

    echo "=> Unmounting system extensions..."
    sudo systemd-sysext refresh

    echo "--------------------------------------------------------"
    echo "✅ Sysext-Creator has been completely removed."
    echo "--------------------------------------------------------"
    exit 0
fi

# ======================================================================
# INSTALL LOGIC
# ======================================================================
echo "🚀 Activating Sysext-Creator from RAW image..."

if [ ! -f "/usr/bin/sysext-creator" ]; then
    echo "❌ Error: Sysext-Creator is not mounted."
    echo "Ensure the image is in /var/lib/extensions and run 'sudo systemd-sysext refresh'."
    exit 1
fi

echo "=> Cleaning up deprecated legacy services (Auto-Healer)..."
sudo systemctl stop sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
sudo systemctl disable sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/sysext-creator-heal.service
sudo rm -f /etc/systemd/system/sysext-creator-heal.timer
sudo rm -f /usr/local/bin/sysext-creator-healer

echo "=> Reloading systemd services and enabling staging daemon..."
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

echo "=> Setting up automatic updates (User Session)..."
systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

echo "=> Checking Podman container environment..."
/usr/bin/sysext-creator list > /dev/null 2>&1 || true

# Setup COPR repo on host for resolving dependencies
echo "=> Setup COPR repo on host for resolving dependencies..."
REPO_URL="https://copr.fedorainfracloud.org/coprs/nadmartin/sysext-creator/repo/fedora-$(rpm -E %fedora)/nadmartin-sysext-creator-fedora-$(rpm -E %fedora).repo"
REPO_FILE="nadmartin-sysext-creator-fedora-$(rpm -E %fedora).repo"
curl -sL -O "$REPO_URL"
sudo install -o 0 -g 0 -m644 "$REPO_FILE" "/etc/yum.repos.d/$REPO_FILE"
rm -f "$REPO_FILE"

if [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]] || pgrep -x plasmashell > /dev/null; then
    if command -v kbuildsycoca6 &> /dev/null; then
        kbuildsycoca6 &>/dev/null || true
        echo "✅ KDE menu updated."
    fi
fi

echo "--------------------------------------------------------"
echo "✅ Activation complete!"
echo "📦 You can now launch Sysext-Creator from the application menu."
echo "⏳ Running automatic diagnostics and E2E Test..."
echo "Test packages will be created and deleted in the background during the test."

sysext-creator-test

echo -e "\nIf the tests passed (green), the system is ready to use."
echo "--------------------------------------------------------"
echo -e "\n================================================================================"
echo "✅ Sysext-Creator (v2.0) RAW activation successfully completed!"
echo "================================================================================"
