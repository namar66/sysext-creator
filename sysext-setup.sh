#!/bin/bash
set -euo pipefail

# ⚙️ KONFIGURACE
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-worker-fc${HOST_VERSION}"
IMAGE="registry.fedoraproject.org/fedora:${HOST_VERSION}"
WORKSPACE="$HOME/.cache/sysext-creator-workspace"

echo "⚙️  Setting up Sysext-Creator v1.2.0 (Pure Podman Edition)..."

# 1. Příprava pracovní složky
mkdir -p "$WORKSPACE"

# 2. Vytvoření kontejneru (pokud neexistuje)
if sudo podman container exists "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "✅ Worker container '$CONTAINER_NAME' already exists."
else
    echo "🏗️  Creating persistent worker container..."
    # Mountujeme repozitáře i GPG klíče pro bezpečné ověřování balíčků
    sudo podman create \
        --name "$CONTAINER_NAME" \
        --user root \
        -v "$WORKSPACE:/workspace:Z" \
        -v /etc/yum.repos.d:/etc/yum.repos.d:ro \
        -v /etc/pki/rpm-gpg:/etc/pki/rpm-gpg:ro \
        -w /workspace \
        "$IMAGE" /usr/bin/sleep infinity >/dev/null
    echo "✅ Worker container created."
fi

# 3. Příprava nástrojů uvnitř kontejneru
echo "📦 Installing build tools inside the worker..."
sudo podman start "$CONTAINER_NAME" >/dev/null
sudo podman exec "$CONTAINER_NAME" dnf install -y erofs-utils cpio dnf-utils --nodocs --quiet
echo "✅ Tools installed."

# 4. SAMOINSTALACE DO SYSTÉMU
echo "🚀 Deploying Sysext-Creator as a system extension..."
if [[ -x "./build-bundle.sh" ]]; then
    ./build-bundle.sh
    sudo systemctl restart systemd-sysext.service
    echo -e "\n🎉 Setup complete! You can now use 'sysext-creator' globally."
    echo "   (The original folder can be safely removed.)"
else
    echo "⚠️  Warning: build-bundle.sh not found. Tool was not installed to /usr/bin/."
fi
