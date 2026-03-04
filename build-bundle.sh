#!/bin/bash
set -euo pipefail

# 📍 Zjištění cest (odolné vůči sudo)
REAL_USER=${SUDO_USER:-$USER}
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
WORKSPACE="$REAL_HOME/.cache/sysext-creator-workspace"

SRC_DIR=$(dirname "$(realpath "$0")")
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-worker-fc${HOST_VERSION}"
EXT_DIR="/var/lib/extensions"

# Načtení verze
TOOL_VERSION=$(grep -m 1 '^TOOL_VERSION=' "$SRC_DIR/sysext-creator.sh" | cut -d'"' -f2 || echo "unknown")
FC_NEXT=$((HOST_VERSION + 1))

echo "📦 Bundling Sysext-Creator v${TOOL_VERSION}..."

for VER in $HOST_VERSION $FC_NEXT; do
    echo "   -> Baking for Fedora $VER..."

    # Musíme zajistit, aby složku mohl číst kontejner (oprávnění)
    BUILD_ID=$(date +%s)
    TEMP_BUILD="$WORKSPACE/build-$BUILD_ID"
    mkdir -p "$TEMP_BUILD/usr/bin"
    mkdir -p "$TEMP_BUILD/usr/share/kio/servicemenus"
    mkdir -p "$TEMP_BUILD/usr/lib/extension-release.d"

    # Definice názvů pro systemd-sysext kompatibilitu
    IMAGE_NAME="sysext-creator-v${TOOL_VERSION}-fc${VER}"
    TARGET_RAW="${IMAGE_NAME}.raw"

    # Příprava souborů
    cp "$SRC_DIR/sysext-creator.sh" "$TEMP_BUILD/usr/bin/sysext-creator"
    cp "$SRC_DIR/sysext-creator-core.sh" "$TEMP_BUILD/usr/bin/sysext-creator-core"
    cp "$SRC_DIR/sysext-setup.sh" "$TEMP_BUILD/usr/bin/sysext-setup"
    cp "$SRC_DIR/build-bundle.sh" "$TEMP_BUILD/usr/bin/sysext-creator-bundle"
    cp "$SRC_DIR/sysext-install.desktop" "$TEMP_BUILD/usr/share/kio/servicemenus/"
    chmod +x "$TEMP_BUILD/usr/bin/"*

    # Metadata MUSÍ mít stejný název jako výsledný .raw soubor
    echo -e "ID=fedora\nVERSION_ID=$VER" > "$TEMP_BUILD/usr/lib/extension-release.d/extension-release.${IMAGE_NAME}"

    # Cesty pro kontejner
    CONTAINER_BUILD_DIR="/workspace/build-$BUILD_ID"
    CONTAINER_TARGET_PATH="/workspace/$TARGET_RAW"

    # Pečení v kontejneru
    sudo podman exec -w /workspace "$CONTAINER_NAME" \
        mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$CONTAINER_TARGET_PATH" "$CONTAINER_BUILD_DIR" >/dev/null

    # Nasazení na hostitele
    sudo rm -f "$EXT_DIR/sysext-creator-"*"-fc${VER}.raw"
    sudo mv "$WORKSPACE/$TARGET_RAW" "$EXT_DIR/"
    
    # Úklid
    rm -rf "$TEMP_BUILD"
done

echo "✨ Bundle complete! Images deployed to $EXT_DIR."
