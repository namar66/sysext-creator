#!/bin/bash

# Sysext-Creator Ultimate Installer v2.1
# Features: Sticky-Bit Drop-Zone, Hardened Systemd Service

set -e

# Cesty
OPT_DIR="/opt/sysext-creator"
BIN_DIR="/usr/local/bin"
USER_BIN_DIR="$HOME/.local/bin"
SYSTEMD_SYS_DIR="/etc/systemd/system"
SYSTEMD_USR_DIR="$HOME/.config/systemd/user"
EXT_DIR="/var/lib/extensions"
BUILD_OUTPUT="/var/tmp/sysext-creator/sysext-creator.raw"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APP_DIR="$HOME/.local/share/applications"
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions/"
USER_KIO_DIR="$HOME/.local/share/kio/servicemenus/"

case "$1" in
    uninstall|remove|--uninstall)
        echo "=== Uninstalling Sysext-Creator ==="
        sudo systemctl disable --now sysext-creator-daemon.service 2>/dev/null || true
        systemctl --user disable --now sysext-autoupdater.timer 2>/dev/null || true

        sudo rm -rf "$OPT_DIR"
        sudo rm -f "$BIN_DIR/sysext-creator-builder.py" "$BIN_DIR/sysext-cli"
        rm -f "$USER_BIN_DIR/sysext-creator-gui" "$USER_BIN_DIR/sysext-autoupdater.py"
        rm -f "$APP_DIR/sysext-creator.desktop" "$ICON_DIR/sysext-creator.png"

        sudo rm -f "$SYSTEMD_SYS_DIR/sysext-creator-daemon.service"
        rm -f "$SYSTEMD_USR_DIR/sysext-autoupdater.service" "$SYSTEMD_USR_DIR/sysext-autoupdater.timer"

        sudo systemctl daemon-reload
        systemctl --user daemon-reload
        echo "=== Uninstallation Completed! ==="
        echo "Note: Extensions in /var/tmp/sysext-creator and $EXT_DIR were kept."
        exit 0
        ;;
esac

echo "=== Sysext-Creator Setup v2.1 ==="

# Kontrola souborů
REQUIRED_FILES=("sysext-creator-daemon.py" "sysext-creator-builder.py" "sysext-cli.py" "sysext-creator-gui.py" "sysext-autoupdater.py" "sysext-creator-install.desktop" "sysext-cli.bash")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then echo "Error: Missing $file"; exit 1; fi
done

mkdir -p "$USER_BIN_DIR" "$SYSTEMD_USR_DIR"

# --- BEZPEČNOSTNÍ NASTAVENÍ DROP-ZONE ---
echo "[1/9] Setting up Secure Drop-Zone..."
sudo mkdir -p /var/tmp/sysext-creator
sudo chmod 1777 /var/tmp/sysext-creator # Každý může psát, jen majitel mazat

echo "[2/9] Setting up Toolbox container..."
if ! podman container exists sysext-builder; then
    toolbox create -c sysext-builder
fi

echo "[3/9] Copying scripts..."
sudo mkdir -p "$OPT_DIR"
sudo cp -f sysext-creator-daemon.py "$OPT_DIR/"
sudo chmod +x "$OPT_DIR/sysext-creator-daemon.py"

sudo cp -f sysext-creator-builder.py "$BIN_DIR/"
sudo chmod +x "$BIN_DIR/sysext-creator-builder.py"

sudo cp -f sysext-cli.py "$BIN_DIR/sysext-cli"
sudo chmod +x "$BIN_DIR/sysext-cli"

cp -f sysext-creator-gui.py "$USER_BIN_DIR/sysext-creator-gui"
chmod +x "$USER_BIN_DIR/sysext-creator-gui"

cp -f sysext-autoupdater.py "$USER_BIN_DIR/"
chmod +x "$USER_BIN_DIR/sysext-autoupdater.py"

echo "[4/9] Building core dependencies..."
toolbox run -c sysext-builder python3 "/run/host$BIN_DIR/sysext-creator-builder.py" sysext-creator-deps python3-varlink python3-pyqt6 erofs-utils

echo "[5/9] Deploying dependency layer..."
sudo mkdir -p "$EXT_DIR"
sudo cp "/var/tmp/sysext-creator/sysext-creator-deps.raw" "$EXT_DIR/sysext-creator.raw"
sudo restorecon -v "$EXT_DIR/sysext-creator.raw"
sudo systemd-sysext refresh

echo "[6/9] Configuring Hardened Daemon Service..."
cat <<EOF | sudo tee "$SYSTEMD_SYS_DIR/sysext-creator-daemon.service" > /dev/null
[Unit]
Description=Sysext Creator Daemon
After=network.target systemd-sysext.service
Requires=systemd-sysext.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $OPT_DIR/sysext-creator-daemon.py
Restart=on-failure
# Hardening
NoNewPrivileges=yes
RestrictSUIDSGID=yes
LockPersonality=yes
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-daemon.service

echo "[7/9] Configuring Auto-Updater..."
cat <<EOF | tee "$SYSTEMD_USR_DIR/sysext-autoupdater.service" > /dev/null
[Unit]
Description=Sysext Creator Auto-Updater
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

echo "[8/9] Desktop Integration..."
mkdir -p "$APP_DIR"
cat <<EOF > "$APP_DIR/sysext-creator.desktop"
[Desktop Entry]
Name=Sysext Creator
Exec=$USER_BIN_DIR/sysext-creator-gui
Icon=sysext-creator
Terminal=false
Type=Application
Categories=System;Utility;
EOF

echo "[9/9] Bash Completion..."
if [ -d "$COMPLETION_DIR" ]; then
    sudo cp sysext-cli.bash "$COMPLETION_DIR/sysext-cli"
    sudo chmod 644 "$COMPLETION_DIR/sysext-cli"
fi

echo "=== Installation Completed Successfully! ==="
