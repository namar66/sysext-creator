#!/bin/bash

# Stop on any error
set -euo pipefail

echo "🚀 Starting Sysext-Creator environment setup..."

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STAGING_DIR="/var/tmp/sysext-staging"

# STEP 1: Host Daemon Installation (The only step requiring sudo)
echo "=> Installing event-driven deployment daemon (sudo password may be required)..."

# Daemon script deployment
sudo tee /usr/local/bin/sysext-creator-deploy.sh > /dev/null << 'EOF'
#!/bin/bash
set -euo pipefail
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"
REFRESH_NEEDED=0
shopt -s nullglob

for req_file in "$STAGING_DIR"/*.version-req; do
    filename=$(basename "$req_file")
    pkg_name="${filename%.version-req}"
    res_file="$STAGING_DIR/${pkg_name}.version-res"
    if [ -f "$EXT_DIR/${pkg_name}.raw" ]; then
        systemd-dissect --with "$EXT_DIR/${pkg_name}.raw" cat "usr/lib/extension-release.d/extension-release.${pkg_name}" 2>/dev/null | grep "^SYSEXT_VERSION_ID=" | cut -d'=' -f2 > "$res_file" || touch "$res_file"
    else
        touch "$res_file"
    fi
    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$req_file"
done

for etc_rm_file in "$STAGING_DIR"/*.etc.remove; do
    filename=$(basename "$etc_rm_file")
    pkg_name="${filename%.etc.remove}"
    while IFS= read -r filepath; do
        if [[ "$filepath" == /etc/* && "$filepath" != *..* ]]; then
            [ -f "$filepath" ] && rm -f "$filepath"
        fi
    done < "$etc_rm_file"
    rm -f "$etc_rm_file"
done

for del_file in "$STAGING_DIR"/*.delete; do
    filename=$(basename "$del_file")
    pkg_name="${filename%.delete}"
    rm -f "$EXT_DIR/${pkg_name}.raw"
    rm -f "$del_file"
    REFRESH_NEEDED=1
done

for etc_file in "$STAGING_DIR"/*.etc.tar.gz; do
    tar -xzf "$etc_file" -C /etc/ --skip-old-files
    rm -f "$etc_file"
done

for raw_file in "$STAGING_DIR"/*.raw; do
    filename=$(basename "$raw_file")
    rm -f "$EXT_DIR/$filename"
    mv "$raw_file" "$EXT_DIR/"
    chown root:root "$EXT_DIR/$filename"
    chmod 0644 "$EXT_DIR/$filename"
    REFRESH_NEEDED=1
done

if [ $REFRESH_NEEDED -eq 1 ]; then
    systemd-sysext refresh || echo "⚠️ Warning: Refresh failed, but daemon continues running."
fi

# Immortal daemon: Always exit 0 so .path doesn't get stuck
exit 0
EOF
sudo chmod +x /usr/local/bin/sysext-creator-deploy.sh

# Systemd Service for the daemon
sudo tee /etc/systemd/system/sysext-creator-deploy.service > /dev/null << 'EOF'
[Unit]
Description=Deploy staged systemd-sysext images
After=systemd-sysext.service
# 🆕 Disable start limits so the daemon never enters a "failed" state due to frequency
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sysext-creator-deploy.sh
EOF

# Systemd Path for the daemon (folder watcher)
sudo tee /etc/systemd/system/sysext-creator-deploy.path > /dev/null << 'EOF'
[Unit]
Description=Monitor sysext staging directory for new images

[Path]
PathChanged=/var/tmp/sysext-staging
MakeDirectory=yes
DirectoryMode=0777
TriggerLimitIntervalSec=0.1s

[Install]
WantedBy=multi-user.target
EOF

# Activate the daemon
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

# STEP 2: Distrobox Check
if ! command -v distrobox &> /dev/null; then
    echo "❌ Error: Distrobox not found. Please install it before running this script."
    exit 1
else
    echo "=> Distrobox found, continuing..."
fi

# STEP 3: Create Container
echo "=> Creating container '$CONTAINER_NAME' (this might take a while)..."
distrobox create --name "$CONTAINER_NAME" --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} --volume $STAGING_DIR:$STAGING_DIR:rw -Y

echo "=> Installing required packages inside the container..."
distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils

# STEP 4: Install Scripts
echo "=> Copying tools to ~/.local/bin..."
mkdir -p ~/.local/bin

if [ -f "sysext-creator" ]; then
    cp sysext-creator ~/.local/bin/sysext-creator
    cp sysext-creator-core ~/.local/bin/sysext-creator-core
elif [ -f "sysext-creator.sh" ]; then
    cp sysext-creator.sh ~/.local/bin/sysext-creator
    cp sysext-creator-core.sh ~/.local/bin/sysext-creator-core
else
    echo "❌ Error: Cannot find 'sysext-creator' files in the current directory!"
    exit 1
fi

chmod +x ~/.local/bin/sysext-creator-core
chmod +x ~/.local/bin/sysext-creator

# STEP 5: Systemd Timer for Auto-updates
echo "=> Setting up automatic daily background updates..."
mkdir -p ~/.config/systemd/user/

cat << 'EOF' > ~/.config/systemd/user/sysext-update.service
[Unit]
Description=Auto-update Sysext-Creator images

[Service]
Type=oneshot
ExecStart=/bin/bash -c "$HOME/.local/bin/sysext-creator update"
EOF

cat << 'EOF' > ~/.config/systemd/user/sysext-update.timer
[Unit]
Description=Daily Auto-update for Sysext-Creator

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

# STEP 6: Bash Completion
echo "=> Setting up bash completion..."
mkdir -p ~/.local/share/bash-completion/completions

cat << 'EOF' > ~/.local/share/bash-completion/completions/sysext-creator
_sysext_creator_completions() {
    local cur prev commands installed_pkgs

    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="install update rm list upgrade-box"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
        return 0
    fi

    if [[ "${prev}" == "rm" ]]; then
        installed_pkgs=$(ls /var/lib/extensions/*.raw 2>/dev/null | xargs -n 1 basename -s .raw 2>/dev/null | sort -u)
        COMPREPLY=( $(compgen -W "${installed_pkgs}" -- "${cur}") )
        return 0
    fi
    COMPREPLY=()
}
complete -F _sysext_creator_completions sysext-creator
EOF

echo "--------------------------------------------------------"
echo "✅ Installation complete and system is fully event-driven!"
echo "✨ Just restart your terminal to load the completion."
echo "Then try installing your first package: sysext-creator install mc"
echo "--------------------------------------------------------"
