#!/bin/bash
set -euo pipefail

# 📍 Zjištění fyzické polohy tohoto skriptu (absolutní cesta)
SRC_DIR=$(dirname "$(realpath "$0")")

# Načtení verze s využitím přesné cesty
TOOL_VERSION=$(grep -m 1 '^TOOL_VERSION=' "$SRC_DIR/sysext-creator.sh" | cut -d'"' -f2 || echo "unknown")
FC_CURRENT=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
FC_NEXT=$((FC_CURRENT + 1))
EXT_DIR="/var/lib/extensions"

echo "📦 Bundling Sysext-Creator v${TOOL_VERSION}..."

for VER in $FC_CURRENT $FC_NEXT; do
    echo "   -> Baking for Fedora $VER..."

    WORKDIR=$(mktemp -d)
    trap 'rm -rf "$WORKDIR"' EXIT
    BUILD_DIR="$WORKDIR/build_root"

    mkdir -p "$BUILD_DIR/usr/bin"
    mkdir -p "$BUILD_DIR/usr/share/kio/servicemenus"

    # Kopírování souborů z adresáře, kde se právě nachází tento bundler
    cp "$SRC_DIR/sysext-creator.sh" "$BUILD_DIR/usr/bin/sysext-creator"
    cp "$SRC_DIR/sysext-creator-core.sh" "$BUILD_DIR/usr/bin/sysext-creator-core"
    cp "$SRC_DIR/sysext-setup.sh" "$BUILD_DIR/usr/bin/sysext-setup"
    cp "$SRC_DIR/build-bundle.sh" "$BUILD_DIR/usr/bin/sysext-creator-bundle"
    cp "$SRC_DIR/sysext-install.desktop" "$BUILD_DIR/usr/share/kio/servicemenus/"
    chmod +x "$BUILD_DIR/usr/bin/"*

    mkdir -p "$BUILD_DIR/usr/lib/extension-release.d"
    echo -e "ID=fedora\nVERSION_ID=$VER" > "$BUILD_DIR/usr/lib/extension-release.d/extension-release.sysext-creator"

    TARGET_RAW="sysext-creator-v${TOOL_VERSION}-fc${VER}.raw"
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$WORKDIR/$TARGET_RAW" "$BUILD_DIR" >/dev/null 2>&1

    sudo rm -f "$EXT_DIR/sysext-creator-"*"-fc${VER}.raw"
    sudo mv "$WORKDIR/$TARGET_RAW" "$EXT_DIR/"

    trap - EXIT
    rm -rf "$WORKDIR"
done

echo "✨ Bundle complete! Images deployed to $EXT_DIR."
