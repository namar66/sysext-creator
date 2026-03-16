#!/usr/bin/env bash

# Sysext-Creator Installer v1.0
# Deploys daemon to system, GUI/Builder to user space, and sets up systemd.

set -e

echo "========================================"
echo " Installing Sysext Manager...           "
echo "========================================"

# 1. Define Paths
USER_BIN="$HOME/.local/bin"
USER_APP="$HOME/.local/share/applications"
DAEMON_DIR="/usr/local/libexec"
EXT_DIR="/var/lib/extensions"

# Ensure user directories exist
mkdir -p "$USER_BIN" "$USER_APP"

# 2. Install User Components (GUI and Builder)
echo "[1/5] Installing user components to ~/.local/bin..."
cp sysext-creator-gui.py "$USER_BIN/sysext-creator-gui"
chmod +x "$USER_BIN/sysext-creator-gui"

cp sysext-creator-builder.py "$USER_BIN/sysext-builder"
chmod +x "$USER_BIN/sysext-builder"
echo "Installing CLI tool..."
cp sysext-cli.py "$USER_BIN/sysext-cli"
chmod +x "$USER_BIN/sysext-cli"

echo "Setting up auto-update user service and timer..."
USER_SYSTEMD="$HOME/.config/systemd/user"
mkdir -p "$USER_SYSTEMD"

cp sysext-update.service "$USER_SYSTEMD/"
cp sysext-update.timer "$USER_SYSTEMD/"

# Aktivace timeru pro aktuálního uživatele
systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer
# 3. Create Desktop Entry (KDE / GNOME Menu)
echo "[2/5] Creating Desktop entry..."
cat <<EOF > "$USER_APP/sysext-creator.desktop"
[Desktop Entry]
Name=Sysext Manager
Comment=Manage atomic system extensions via systemd-sysext
Exec=$USER_BIN/sysext-creator-gui
Icon=system-software-install
Terminal=false
Type=Application
Categories=System;Settings;
EOF
update-desktop-database "$USER_APP" || true

# 4. Build and Deploy python3-varlink dependency
echo "[3/5] Building python3-varlink dependency via Toolbox..."
# This uses your existing toolbox container to build the extension
toolbox run -c sysext-creator-builder-fc43 python3 "$USER_BIN/sysext-builder" python3-varlink python3-varlink

# 5. Install System Components (Requires sudo)
echo "[4/5] Installing system daemon and extensions (requires sudo)..."
sudo mkdir -p "$DAEMON_DIR" "$EXT_DIR"

# Move the newly built varlink extension to the system directory
if [ -f "$HOME/sysext-builds/python3-varlink.raw" ]; then
    sudo cp "$HOME/sysext-builds/python3-varlink.raw" "$EXT_DIR/"
    sudo restorecon -v "$EXT_DIR/python3-varlink.raw"
else
    echo "Error: python3-varlink.raw was not built successfully! Check toolbox output."
    exit 1
fi

# Install daemon binary
sudo cp sysext-creator-daemon.py "$DAEMON_DIR/sysext-creator-daemon.py"
sudo chmod +x "$DAEMON_DIR/sysext-creator-daemon.py"

# Install systemd service
sudo cp sysext-creator.service /etc/systemd/system/

# 6. Enable and start the service
echo "[5/5] Refreshing system extensions and starting service..."
# Refresh extensions FIRST so python3-varlink is mounted for the daemon
sudo systemd-sysext refresh

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator.service

echo "========================================"
echo " Installation Complete!                 "
echo " You can now launch 'Sysext Manager'    "
echo " from your application menu.            "
echo "========================================"
