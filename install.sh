#!/bin/bash

# Sysext Creator Pro - Ultimate Local Installer
# Installs CLI, Builder, Doctor, Bash Completion, and optionally GUI

export LANG=C
export LC_ALL=C

# ==========================================
# CONFIGURATION
# ==========================================
APP_NAME="Sysext Creator Pro"
BIN_PATH="$HOME/.local/bin"
COMPLETION_PATH="$HOME/.local/share/bash-completion/completions"
ICON_PATH="$HOME/.local/share/icons/hicolor/256x256/apps"
DESKTOP_PATH="$HOME/.local/share/applications"

# Source files
CLI_SCRIPT="sysext-cli.py"
GUI_SCRIPT="sysext-gui-pro.py"
BUILDER_SCRIPT="sysext-creator-builder.py"
DOCTOR_SCRIPT="sysext-doctor.py"
BASH_COMP="sysext-cli.bash"
ICON_SOURCE="sysext-creator-icon.png"

function log() {
    echo -e "\033[1;34m[$APP_NAME Install]\033[0m $1"
}

log "Initializing local user installation..."

# --- 1. Validate Base Source Files ---
for file in "$CLI_SCRIPT" "$BUILDER_SCRIPT" "$DOCTOR_SCRIPT" "$BASH_COMP"; do
    if [ ! -f "$file" ]; then
        echo "❌ ERROR: Missing core file: $file"
        exit 1
    fi
done

# --- 2. Install Core CLI & Backend ---
log "Installing core backend and CLI to $BIN_PATH..."
mkdir -p "$BIN_PATH"
install -m 755 "$CLI_SCRIPT" "$BIN_PATH/sysext-cli"
install -m 755 "$BUILDER_SCRIPT" "$BIN_PATH/$BUILDER_SCRIPT"
install -m 755 "$DOCTOR_SCRIPT" "$BIN_PATH/$DOCTOR_SCRIPT"

log "Installing Bash completion..."
mkdir -p "$COMPLETION_PATH"
install -m 644 "$BASH_COMP" "$COMPLETION_PATH/sysext-cli"
toolbox create sysext-builder
# --- 3. Optional GUI Installation ---
echo ""
read -p "🖥️  Do you want to install the Graphical User Interface (GUI)? [y/N] " install_gui
echo ""

if [[ "$install_gui" =~ ^[Yy]$ ]]; then
    if [ ! -f "$GUI_SCRIPT" ] || [ ! -f "$ICON_SOURCE" ]; then
        echo "❌ ERROR: Missing GUI files ($GUI_SCRIPT or $ICON_SOURCE)."
        echo "Please make sure they exist in the current directory."
        exit 1
    fi

    log "Installing GUI script..."
    install -m 755 "$GUI_SCRIPT" "$BIN_PATH/sysext-gui-pro"

    log "Installing icon and desktop entry..."
    mkdir -p "$ICON_PATH" "$DESKTOP_PATH"
    cp -f "$ICON_SOURCE" "$ICON_PATH/sysext-creator.png"

    echo "[Desktop Entry]
Version=3.1
Type=Application
Name=$APP_NAME
Comment=Manage Systemd System Extensions and Layers on Atomic Fedora
Exec=$BIN_PATH/sysext-gui-pro
Icon=sysext-creator
Categories=System;Settings;Qt;
Terminal=false
StartupNotify=true" > "$DESKTOP_PATH/sysext-creator.desktop"

    if command -v update-desktop-database > /dev/null; then
        update-desktop-database -q "$DESKTOP_PATH"
    fi
    if command -v gtk-update-icon-cache > /dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
    fi
    
    log "GUI files installed successfully!"
    
    # The magical meta-step: building PyQt6 dependencies using our own CLI
    log "Building the 'pyqt6-deps' system extension using sysext-cli..."
    echo "This will download python3-pyqt6 and qt6-qtwayland to ensure the GUI works."
    
    # We call the CLI directly from where we just installed it
    "$BIN_PATH/sysext-cli" install pyqt6-deps python3-pyqt6
else
    log "Skipping GUI installation."
fi

echo ""
log "✅ SUCCESS! Installation complete."
log "You can now use 'sysext-cli' from your terminal."
if [[ "$install_gui" =~ ^[Yy]$ ]]; then
    log "The GUI is available in your application menu as '$APP_NAME'."
fi
log "Note: You might need to restart your terminal for bash completion to take effect."
