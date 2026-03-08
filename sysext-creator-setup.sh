#!/bin/bash
set -euo pipefail

echo "🚀 Starting Sysext-Creator environment setup (v1.5.0)..."

# 1. CONSTANTS & PREPARATION
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"

# Safety check for Silverblue/Kinoite: Ensure the system extensions directory exists
if [ ! -d "$EXT_DIR" ]; then
    echo "⚙️ Creating missing extensions directory: $EXT_DIR"
    sudo systemctl enable --now systemd-sysext.service
    sudo mkdir -p "$EXT_DIR"
    sudo chmod 0755 "$EXT_DIR"
fi

# 2. STEP: Install the Host Daemon (The Foundation)
echo "=> Installing deployment daemon (requires sudo)..."

sudo tee /usr/local/bin/sysext-creator-deploy.sh > /dev/null << 'EOF'
#!/bin/bash
set -euo pipefail
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"
LOG_FILE="/var/log/sysext-creator.log"
REFRESH_NEEDED=0

shopt -s nullglob
shopt -s dotglob

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') INFO: $1" >> "$LOG_FILE"; }
err() { echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: $1" >> "$LOG_FILE"; }

# A. Version Requests
for req_file in "$STAGING_DIR"/*.version-req; do
    pkg_name=$(basename "$req_file" .version-req)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$req_file"; continue; }

    res_file="$STAGING_DIR/${pkg_name}.version-res"
    if [[ -f "$EXT_DIR/${pkg_name}.raw" ]]; then
        systemd-dissect --with "$EXT_DIR/${pkg_name}.raw" cat "usr/lib/extension-release.d/extension-release.${pkg_name}" 2>/dev/null | grep "^SYSEXT_VERSION_ID=" | cut -d'=' -f2 > "$res_file" || touch "$res_file"
    else
        touch "$res_file"
    fi
    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$req_file"
done

# B. /etc Removals
for etc_rm in "$STAGING_DIR"/*.etc.remove; do
    [[ ! -s "$etc_rm" ]] && { rm -f "$etc_rm"; continue; }
    while IFS= read -r f; do [[ "$f" == /etc/* && "$f" != *..* ]] && rm -f "$f"; done < "$etc_rm"
    rm -f "$etc_rm"
done

# C. Deletions
for del_file in "$STAGING_DIR"/*.delete; do
    pkg_name=$(basename "$del_file" .delete)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$del_file"; continue; }

    log "Removing extension: $pkg_name"
    rm -f "$EXT_DIR/${pkg_name}.raw"
    rm -f "$del_file"
    REFRESH_NEEDED=1
done

# D. New Images (*.raw)
for raw_file in "$STAGING_DIR"/*.raw; do
    [[ ! -s "$raw_file" ]] && { rm -f "$raw_file"; continue; }

    pkg_file=$(basename "$raw_file")
    log "Deploying new extension: $pkg_file"

    if mv "$raw_file" "$EXT_DIR/"; then
        chown root:root "$EXT_DIR/$pkg_file"
        chmod 0644 "$EXT_DIR/$pkg_file"

        # Ochrana SELinuxu
        if command -v restorecon >/dev/null 2>&1; then
            restorecon "$EXT_DIR/$pkg_file" || err "Failed to restorecon $pkg_file"
        fi
        REFRESH_NEEDED=1
    else
        err "Failed to move $raw_file to $EXT_DIR"
    fi
done

if [[ $REFRESH_NEEDED -eq 1 ]]; then
    log "Refreshing systemd-sysext..."
    systemd-sysext refresh || err "Systemd-sysext refresh failed!"
fi
exit 0
EOF
sudo chmod +x /usr/local/bin/sysext-creator-deploy.sh

# 3. STEP: Systemd Configuration (Folder managed by Systemd)
echo "=> Configuring systemd units..."

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

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

# 4. STEP: Bootstrap Distrobox
if ! command -v distrobox &> /dev/null; then
    echo "📦 Distrobox not found. Bootstrapping via official Fedora RPM..."
    BOOTSTRAP_DIR=$(mktemp -d)
    DUMMY_VERSION="0.0.1.fcfc${HOST_VERSION}"

    podman run --rm \
        -v "$BOOTSTRAP_DIR:/mnt:Z" \
        registry.fedoraproject.org/fedora:${HOST_VERSION} \
        sh -c "
            dnf download -y distrobox erofs-utils cpio >/dev/null && \
            dnf install -y erofs-utils cpio >/dev/null && \
            mkdir -p /mnt/root/usr/lib/extension-release.d && \
            rpm2cpio distrobox*.rpm | cpio -idm -D /mnt/root && \
            echo -e 'ID=fedora\nVERSION_ID=${HOST_VERSION}\nSYSEXT_VERSION_ID=${DUMMY_VERSION}' > /mnt/root/usr/lib/extension-release.d/extension-release.distrobox && \
            mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 /mnt/distrobox.raw /mnt/root
        "

    if [ -f "$BOOTSTRAP_DIR/distrobox.raw" ]; then
        mv "$BOOTSTRAP_DIR/distrobox.raw" "$STAGING_DIR/"
        echo "=> Distrobox RPM extension created and dispatched to staging."
    else
        echo "❌ Error: Bootstrap failed to create distrobox.raw"
        exit 1
    fi

    rm -rf "$BOOTSTRAP_DIR"
    echo "=> Waiting for daemon to activate Distrobox..."
    sleep 3
fi

# 5. STEP: Container & CLI Tools Setup
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
echo "=> Creating build container '$CONTAINER_NAME'..."
distrobox create \
    --name "$CONTAINER_NAME" \
    --image "registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION}" \
    --volume "$STAGING_DIR":"$STAGING_DIR":rw \
    --volume "/etc/yum.repos.d:/etc/yum.repos.d:ro" \
    -Y

echo "=> Installing dependencies inside container..."
distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils

echo "=> Deploying scripts and GUI to ~/.local/bin..."
mkdir -p "$HOME/.local/bin"
cp "sysext-creator.sh" "$HOME/.local/bin/sysext-creator"
cp "sysext-creator-core.sh" "$HOME/.local/bin/sysext-creator-core"
cp "sysext-gui" "$HOME/.local/bin/sysext-gui"
chmod +x "$HOME/.local/bin/sysext-creator"* "$HOME/.local/bin/sysext-gui"

# User timer for updates
echo "=> Configuring automatic updates..."
mkdir -p "$HOME/.config/systemd/user/"
cat << EOF > "$HOME/.config/systemd/user/sysext-update.service"
[Unit]
Description=Automatická aktualizace systémových rozšíření Sysext
After=graphical-session.target

[Service]
Type=oneshot
ExecStartPre=/usr/bin/notify-send "Sysext-Creator" "Zahajuji automatickou kontrolu a aktualizaci rozšíření..." --icon sysext-creator-icon --app-name "Sysext-Creator"
ExecStart=$HOME/.local/bin/sysext-creator update
ExecStartPost=/usr/bin/notify-send "Sysext-Creator" "Automatická aktualizace byla úspěšně dokončena." --icon sysext-creator-icon --app-name "Sysext-Creator"
EOF

cat << 'EOF' > ~/.config/systemd/user/sysext-update.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

# 6. STEP: GUI & Desktop Integration
echo "=> Instaluji ikonu aplikace..."
mkdir -p "$HOME/.local/share/icons"
if [ -f "sysext-creator-icon.png" ]; then
    cp "sysext-creator-icon.png" "$HOME/.local/share/icons/"
else
    echo "⚠️ Varování: sysext-creator-icon.png nenalezeno ve složce instalátoru."
fi

echo "=> Vytvářím zástupce v menu aplikací (.desktop)..."
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
# Zde používáme 'EOF' bez uvozovek, aby se $HOME správně nahradil za absolutní cestu uživatele
cat << EOF > "$APP_DIR/sysext-creator.desktop"
[Desktop Entry]
Name=Sysext-Creator
Comment=Správa systémových rozšíření pro atomickou Fedoru
Exec=$HOME/.local/bin/sysext-gui
Icon=sysext-creator-icon
Terminal=false
Type=Application
Categories=System;Settings;
Keywords=fedora;atomic;sysext;extension;dnf;
StartupNotify=true
X-KDE-StartupNotify=true
EOF
chmod +x "$APP_DIR/sysext-creator.desktop"

# Obnovení databáze ikon a aplikací, aby se hned ukázal v menu
if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
fi

# 7. STEP: KDE Dolphin Integration
echo "=> Kontroluji desktopové prostředí pro volitelnou integraci..."
if grep -iq "kinoite" /etc/os-release || [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]]; then
    echo "=> Detekováno prostředí KDE Plasma. Instaluji integraci pro Dolphin..."
    MENU_DIR="$HOME/.local/share/kio/servicemenus"
    mkdir -p "$MENU_DIR"

    cat << 'EOF' > "$MENU_DIR/sysext-install.desktop"
[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=application/x-rpm;
Actions=installAsSysext;
X-KDE-Priority=TopLevel
Icon=package-x-generic

[Desktop Action installAsSysext]
Name=Instalovat jako System Extension
Icon=system-software-install
Exec=konsole -e bash -c "~/.local/bin/sysext-creator install '%f'; echo -e '\n✨ Hotovo! Okno se zavře za 3 sekundy...'; sleep 3"
EOF
    chmod +x "$MENU_DIR/sysext-install.desktop"

    if command -v kbuildsycoca6 &> /dev/null; then
        kbuildsycoca6 &>/dev/null || true
        echo "✅ Kontextové menu pro Dolphin bylo úspěšně přidáno."
    fi
else
    echo "=> Prostředí KDE nebylo detekováno (běžíte pravděpodobně na GNOME/Silverblue). Přeskakuji integraci Dolphinu."
fi

# 8. STEP: Bash Completion Setup
echo "=> Konfiguruji automatické doplňování pro Bash..."
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
mkdir -p "$COMPLETION_DIR"

cat << 'EOF' > "$COMPLETION_DIR/sysext-creator"
_sysext_creator_completions() {
    local cur prev cmds
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds="install update check-update rm list search"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return 0
    fi

    case "${prev}" in
        install|search)
            compopt -o default
            COMPREPLY=()
            ;;
        rm)
            local installed=$(ls /var/lib/extensions/*.raw 2>/dev/null | xargs -n1 basename -s .raw 2>/dev/null || true)
            COMPREPLY=( $(compgen -W "${installed}" -- "${cur}") )
            ;;
        *)
            ;;
    esac
}
complete -F _sysext_creator_completions sysext-creator
EOF

source "$COMPLETION_DIR/sysext-creator" 2>/dev/null || true
echo "✅ Bash completion úspěšně nainstalován."

echo "--------------------------------------------------------"
echo "✅ Setup complete! System is now self-bootstrapped."
echo "📦 Nyní můžete aplikaci Sysext-Creator najít ve svém Start Menu!"
echo "--------------------------------------------------------"
