#!/bin/bash
set -euo pipefail

# ======================================================================
# UNINSTALL LOGIC
# ======================================================================
if [[ "${1:-}" == "uninstall" ]]; then
    echo "🧹 Starting complete removal of local Sysext-Creator installation..."

    echo "=> Stopping and removing systemd services..."
    sudo systemctl stop sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo systemctl disable sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.path
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.service

    # Cleanup legacy Healer
    sudo systemctl stop sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
    sudo systemctl disable sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-heal.service
    sudo rm -f /etc/systemd/system/sysext-creator-heal.timer
    sudo rm -f /usr/local/bin/sysext-creator-healer
    sudo systemctl daemon-reload

    echo "=> Removing host daemon..."
    sudo rm -f /usr/local/bin/sysext-creator-deploy.sh

    echo "=> Removing user binaries and GUI..."
    rm -f "$HOME/.local/bin/sysext-creator"
    rm -f "$HOME/.local/bin/sysext-creator-core"
    rm -f "$HOME/.local/bin/sysext-gui"
    rm -f "$HOME/.local/bin/sysext-gui-wrapper-gui"
    rm -f "$HOME/.local/bin/sysext-creator-test"

    echo "=> Removing desktop integration, menu, and bash completion..."
    rm -f "$HOME/.local/share/applications/sysext-creator.desktop"
    rm -f "$HOME/.local/share/icons/hicolor/512x512/apps/sysext-creator-icon.png"
    rm -f "$HOME/.local/share/kio/servicemenus/sysext-creator-install.desktop"
    rm -f "$HOME/.local/share/bash-completion/completions/sysext-creator"

    if command -v kbuildsycoca6 &> /dev/null; then
        kbuildsycoca6 &>/dev/null || true
        echo "✅ KDE menu updated."
    fi
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi

    echo ""
    read -p "Do you want to remove ALL installed raw images in /var/lib/extensions? (yes/no): " remove_all
    if [[ "$remove_all" == "yes" ]]; then
        echo "=> Removing ALL RAW images..."
        sudo rm -f /var/lib/extensions/*.raw
    else
        echo "=> Keeping user images, removing only Sysext-Creator itself..."
        sudo rm -f /var/lib/extensions/sysext-creator*.raw
    fi

    echo "=> Unmounting system extensions..."
    sudo systemd-sysext refresh

    echo "--------------------------------------------------------"
    echo "✅ Local Sysext-Creator installation has been completely removed."
    echo "--------------------------------------------------------"
    exit 0
fi

# ======================================================================
# INSTALL LOGIC
# ======================================================================
echo "🚀 Starting Sysext-Creator environment setup (v2.0)..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"

if [ ! -d "$EXT_DIR" ]; then
    echo "⚙️ Creating missing extensions directory: $EXT_DIR"
    sudo systemctl enable --now systemd-sysext.service
    sudo mkdir -p "$EXT_DIR"
    sudo chmod 0755 "$EXT_DIR"
fi

echo "=> Cleaning up deprecated legacy services (Auto-Healer)..."
sudo systemctl stop sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
sudo systemctl disable sysext-creator-heal.service sysext-creator-heal.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/sysext-creator-heal.service
sudo rm -f /etc/systemd/system/sysext-creator-heal.timer
sudo rm -f /usr/local/bin/sysext-creator-healer

echo "=> Installing deployment daemon (requires sudo)..."
if [[ ! -f "$SCRIPT_DIR/sysext-creator-deploy.sh" ]]; then
    echo "❌ Error: sysext-creator-deploy.sh not found in $SCRIPT_DIR!"
    exit 1
fi

sudo cp "$SCRIPT_DIR/sysext-creator-deploy.sh" /usr/local/bin/sysext-creator-deploy.sh
sudo chown root:root /usr/local/bin/sysext-creator-deploy.sh
sudo chmod +x /usr/local/bin/sysext-creator-deploy.sh

sudo tee /etc/systemd/system/sysext-creator-deploy.service > /dev/null << 'EOF'
[Unit]
Description=Deploy staged systemd-sysext images
After=systemd-sysext.service
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sysext-creator-deploy.sh
EOF

sudo tee /etc/systemd/system/sysext-creator-deploy.path > /dev/null << 'EOF'
[Unit]
Description=Monitor sysext staging directory

[Path]
PathChanged=/var/tmp/sysext-staging
MakeDirectory=yes
DirectoryMode=0777

[Install]
WantedBy=multi-user.target
EOF

echo "=> Fixing SELinux contexts for systemd services..."
if command -v restorecon &> /dev/null; then
    sudo restorecon -v /etc/systemd/system/sysext-creator-deploy.service
    sudo restorecon -v /etc/systemd/system/sysext-creator-deploy.path
    sudo restorecon -v /usr/local/bin/sysext-creator-deploy.sh
fi

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

echo "=> Setting up user binaries in ~/.local/bin..."
mkdir -p "$HOME/.local/bin"
cp "$SCRIPT_DIR/sysext-creator-core.sh" "$HOME/.local/bin/sysext-creator-core"
cp "$SCRIPT_DIR/sysext-creator.sh" "$HOME/.local/bin/sysext-creator"
chmod +x "$HOME/.local/bin/sysext-creator-core" "$HOME/.local/bin/sysext-creator"

echo "=> Checking installed podman..."
if ! command -v podman &> /dev/null; then
    echo "❌ Error: Podman is required. Run on an atomic version of Fedora."
    exit 1
fi

if [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]] || pgrep -x plasmashell > /dev/null; then
    echo "=> KDE environment detected. Adding context menu to Dolphin..."
    SERVICE_DIR="$HOME/.local/share/kio/servicemenus/"
    mkdir -p "$SERVICE_DIR"
    cp "$SCRIPT_DIR/sysext-creator-install.desktop" "$HOME/.local/share/kio/servicemenus/sysext-creator-install.desktop"
    chmod +x "$HOME/.local/share/kio/servicemenus/sysext-creator-install.desktop"
    echo "✅ Action for .rpm files successfully added."
    
    echo "=> Setting up GUI application..."
    cp "$SCRIPT_DIR/sysext-gui" "$HOME/.local/bin/"
    cp "$SCRIPT_DIR/sysext-gui-wrapper-gui.sh" "$HOME/.local/bin/sysext-gui-wrapper"
    chmod +x "$HOME/.local/bin/sysext-gui" "$HOME/.local/bin/sysext-gui-wrapper"

    echo "=> Installing desktop entry and icon..."
    mkdir -p "$HOME/.local/share/applications"
    mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
    cp "$SCRIPT_DIR/sysext-creator-icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/"
    cp "$SCRIPT_DIR/sysext-creator.desktop" "$HOME/.local/share/applications/"
    
    if command -v kbuildsycoca6 &> /dev/null; then
        kbuildsycoca6 &>/dev/null || true
        echo "✅ KDE menu updated."
    fi
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" || true
    fi
else
    echo "=> KDE environment not detected (likely GNOME/Silverblue). Installing CLI version only."
fi

echo "=> Configuring Bash auto-completion..."
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
mkdir -p "$COMPLETION_DIR"

if [[ -f "$SCRIPT_DIR/bash-completion" ]]; then
    cp "$SCRIPT_DIR/bash-completion" "$COMPLETION_DIR/sysext-creator"
    source "$COMPLETION_DIR/sysext-creator" 2>/dev/null || true
else
    echo "⚠️ Warning: bash-completion file is missing in the repository."
fi

echo "=> Copying integration test tool..."
cp "$SCRIPT_DIR/sysext-creator-test.sh" "$HOME/.local/bin/sysext-creator-test"
chmod +x "$HOME/.local/bin/sysext-creator-test"

echo -e "\n================================================================================"
echo "✅ Sysext-Creator (v2.0) local installation successfully completed!"
echo "================================================================================"
echo "⏳ Running automatic diagnostics and E2E Test..."
echo "Test packages will be created and deleted in the background during the test."

sysext-creator-test

echo -e "\nIf the tests passed (green), the system is ready to use."
echo "--------------------------------------------------------"
echo "✅ Local installation complete!"
