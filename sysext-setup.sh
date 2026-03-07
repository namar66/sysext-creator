#!/bin/bash
set -euo pipefail

echo "🚀 Starting Sysext-Creator environment setup (v1.4.1)..."

# 1. CONSTANTS & PREPARATION
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"
# 🆕 Safety check for Silverblue: Ensure the system extensions directory exists
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
REFRESH_NEEDED=0
shopt -s nullglob

# A. Version Requests
for req_file in "$STAGING_DIR"/*.version-req; do
    pkg_name=$(basename "$req_file" .version-req)
    res_file="$STAGING_DIR/${pkg_name}.version-res"
    if [ -f "$EXT_DIR/${pkg_name}.raw" ]; then
        systemd-dissect --with "$EXT_DIR/${pkg_name}.raw" cat "usr/lib/extension-release.d/extension-release.${pkg_name}" 2>/dev/null | grep "^SYSEXT_VERSION_ID=" | cut -d'=' -f2 > "$res_file" || touch "$res_file"
    else
        touch "$res_file"
    fi
    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$req_file"
done

# B. /etc Removals
for etc_rm in "$STAGING_DIR"/*.etc.remove; do
    while IFS= read -r f; do [[ "$f" == /etc/* && "$f" != *..* ]] && rm -f "$f"; done < "$etc_rm"
    rm -f "$etc_rm"
done

# C. Deletions
for del_file in "$STAGING_DIR"/*.delete; do
    pkg_name=$(basename "$del_file" .delete)
    rm -f "$EXT_DIR/${pkg_name}.raw"
    rm -f "$del_file"
    REFRESH_NEEDED=1
done

# D. New Images (*.raw)
for raw_file in "$STAGING_DIR"/*.raw; do
    mv "$raw_file" "$EXT_DIR/"
    pkg_file=$(basename "$raw_file")
    chown root:root "$EXT_DIR/$pkg_file"
    chmod 0644 "$EXT_DIR/$pkg_file"
    REFRESH_NEEDED=1
done

if [ $REFRESH_NEEDED -eq 1 ]; then
    systemd-sysext refresh || echo "Warning: Refresh failed"
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

# 4. STEP: Bootstrap Distrobox (Now that Daemon is watching)
if ! command -v distrobox &> /dev/null; then
    echo "📦 Distrobox not found. Bootstrapping via official Fedora RPM..."

    BOOTSTRAP_DIR=$(mktemp -d)
    DUMMY_VERSION="0.0.1.fcfc${HOST_VERSION}"

    # 1. Spustíme dočasný kontejner, který stáhne RPM a vytvoří obraz
    # Pracujeme pouze uvnitř BOOTSTRAP_DIR, abychom se vyhnuli problémům s SELinuxem na hostiteli
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

    # 2. Přesuneme hotový obraz na staging rampu (již jako běžný uživatel na hostiteli)
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

# 5. STEP: Container & Tools Setup
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
echo "=> Creating build container '$CONTAINER_NAME'..."
distrobox create --name "$CONTAINER_NAME" --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} --volume "$STAGING_DIR":"$STAGING_DIR":rw -Y

echo "=> Installing dependencies inside container..."
distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils

# Deploy local scripts
mkdir -p ~/.local/bin
cp "sysext-creator.sh" "$HOME/.local/bin/sysext-creator"
cp "sysext-creator-core.sh" "$HOME/.local/bin/sysext-creator-core"
chmod +x ~/.local/bin/sysext-creator*

# User timer for updates
mkdir -p ~/.config/systemd/user/
cat << 'EOF' > ~/.config/systemd/user/sysext-update.service
[Service]
Type=oneshot
ExecStart=/bin/bash -c "$HOME/.local/bin/sysext-creator update"
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

echo "--------------------------------------------------------"
echo "✅ Setup complete! System is now self-bootstrapped."
echo "--------------------------------------------------------"
