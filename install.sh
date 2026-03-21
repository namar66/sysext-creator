#!/bin/bash

# Sysext-Creator Ultimate Installer & Uninstaller
# Usage:
#   ./install.sh            - Installs the entire suite
#   ./install.sh uninstall  - Completely removes the suite

set -e

# Define target paths
OPT_DIR="/opt/sysext-creator"
BIN_DIR="/usr/local/bin"
USER_BIN_DIR="$HOME/.local/bin"
SYSTEMD_SYS_DIR="/etc/systemd/system"
SYSTEMD_USR_DIR="$HOME/.config/systemd/user"
EXT_DIR="/var/lib/extensions"
BUILD_OUTPUT="$HOME/sysext-builds/sysext-creator.raw"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APP_DIR="$HOME/.local/share/applications"

# ==========================================
# ARGUMENT PARSING & UNINSTALL LOGIC
# ==========================================
case "$1" in
    "")
        # No argument ($1 is empty) do install
        ;;

    uninstall|uinstall|remove|--uninstall)
        echo "=== Uninstalling Sysext-Creator ==="

        echo "[1/5] Stopping systemd services and timers..."
        sudo systemctl disable --now sysext-creator-daemon.service 2>/dev/null || true
        systemctl --user disable --now sysext-autoupdater.timer 2>/dev/null || true
        systemctl --user disable --now sysext-autoupdater.service 2>/dev/null || true

        echo "[2/5] Removing scripts and binaries..."
        sudo rm -rf "$OPT_DIR"
        sudo rm -f "$BIN_DIR/sysext-creator-builder.py"
        sudo rm -f "$BIN_DIR/sysext-cli"
        rm -f "$USER_BIN_DIR/sysext-creator-gui"
        rm -f "$USER_BIN_DIR/sysext-autoupdater.py"

        echo "[3/5] Removing desktop icon and shortcut..."
        rm -f "$APP_DIR/sysext-creator.desktop"
        rm -f "$ICON_DIR/sysext-creator.png"
        update-desktop-database "$APP_DIR" 2>/dev/null || true

        echo "[4/5] Removing systemd unit files..."
        sudo rm -f "$SYSTEMD_SYS_DIR/sysext-creator-daemon.service"
        rm -f "$SYSTEMD_USR_DIR/sysext-autoupdater.service"
        rm -f "$SYSTEMD_USR_DIR/sysext-autoupdater.timer"
        sudo systemctl daemon-reload
        systemctl --user daemon-reload

        echo "[5/5] Cleaning up Toolbox container and base extension..."
        podman rm -f sysext-builder 2>/dev/null || true
        if [ -f "$EXT_DIR/sysext-creator.raw" ]; then
            sudo rm -f "$EXT_DIR/sysext-creator.raw"
            sudo systemd-sysext refresh
        fi

        echo "=== Uninstallation Completed Successfully! ==="
        echo "Note: Your custom generated extensions in ~/sysext-builds and $EXT_DIR were kept safe."
        exit 0
        ;;

    *)
        # Jakýkoliv jiný, neznámý argument -> Vyhodíme chybu a končíme
        echo "Error: Unknown argument '$1'"
        echo "Usage: ./install.sh [uninstall]"
        exit 1
        ;;
esac

# ==========================================
# INSTALL LOGIC
# ==========================================
echo "=== Sysext-Creator Setup ==="

# Check if all files are present in the current directory
REQUIRED_FILES=("sysext-creator-daemon.py" "sysext-creator-builder.py" "sysext-cli.py" "sysext-creator-gui.py" "sysext-autoupdater.py")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "Error: Missing $file in the current directory."
        exit 1
    fi
done

# Ensure user directories exist
mkdir -p "$USER_BIN_DIR"
mkdir -p "$SYSTEMD_USR_DIR"

echo "[1/8] Setting up Toolbox container..."
if ! podman container exists sysext-builder; then
    echo "Creating sysext-builder container..."
    toolbox create -c sysext-builder
else
    echo "Container sysext-builder already exists."
fi

echo "[2/8] Copying scripts to target directories..."
sudo mkdir -p "$OPT_DIR"
sudo cp sysext-creator-daemon.py "$OPT_DIR/"
sudo chmod +x "$OPT_DIR/sysext-creator-daemon.py"

sudo mkdir -p "$BIN_DIR"
sudo cp sysext-creator-builder.py "$BIN_DIR/"
sudo chmod +x "$BIN_DIR/sysext-creator-builder.py"

sudo cp sysext-cli.py "$BIN_DIR/sysext-cli"
sudo chmod +x "$BIN_DIR/sysext-cli"

cp sysext-creator-gui.py "$USER_BIN_DIR/sysext-creator-gui"
chmod +x "$USER_BIN_DIR/sysext-creator-gui"

cp sysext-autoupdater.py "$USER_BIN_DIR/"
chmod +x "$USER_BIN_DIR/sysext-autoupdater.py"

echo "[3/8] Building core dependencies (python3-varlink, python3-pyqt6)..."
toolbox run -c sysext-builder python3 "/run/host$BIN_DIR/sysext-creator-builder.py" sysext-creator python3-varlink python3-pyqt6

echo "[4/8] Deploying dependency layer..."
if [ ! -f "$BUILD_OUTPUT" ]; then
    echo "Error: Build failed, $BUILD_OUTPUT not found."
    exit 1
fi

sudo mkdir -p "$EXT_DIR"
sudo cp "$BUILD_OUTPUT" "$EXT_DIR/"
sudo restorecon -v "$EXT_DIR/sysext-creator.raw"
sudo systemd-sysext refresh

echo "[5/8] Configuring Daemon Service..."
cat <<EOF | sudo tee "$SYSTEMD_SYS_DIR/sysext-creator-daemon.service" > /dev/null
[Unit]
Description=Sysext Creator Daemon
After=network.target systemd-sysext.service
Requires=systemd-sysext.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $OPT_DIR/sysext-creator-daemon.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-daemon.service

echo "[6/8] Configuring Auto-Updater Timer..."
cat <<EOF | tee "$SYSTEMD_USR_DIR/sysext-autoupdater.service" > /dev/null
[Unit]
Description=Sysext Creator Auto-Updater
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $USER_BIN_DIR/sysext-autoupdater.py
EOF

cat <<EOF | tee "$SYSTEMD_USR_DIR/sysext-autoupdater.timer" > /dev/null
[Unit]
Description=Weekly Timer for Sysext Auto-Updater

[Timer]
OnCalendar=Mon *-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sysext-autoupdater.timer

echo "[7/8] Installing Desktop Shortcut and Icon..."
if [ -f "sysext-creator.png" ]; then
    mkdir -p "$ICON_DIR"
    cp sysext-creator.png "$ICON_DIR/"
else
    echo "Warning: sysext-creator.png not found. Skipping icon copy."
fi

mkdir -p "$APP_DIR"
cat <<EOF > "$APP_DIR/sysext-creator.desktop"
[Desktop Entry]
Name=Sysext Creator
Comment=Manage Atomic System Extensions for Fedora
Exec=$USER_BIN_DIR/sysext-creator-gui
Icon=sysext-creator
Terminal=false
Type=Application
Categories=System;Utility;Settings;
EOF

update-desktop-database "$APP_DIR" 2>/dev/null || true

echo "[8/8] Cleaning up temporary builds..."
# Volitelně můžeme smazat lokální kopii sysext-creator.raw
# rm -f "$BUILD_OUTPUT"

echo "=== Installation Completed Successfully! ==="
echo "You can now launch 'Sysext Creator' from your application menu or run 'sysext-cli'."
