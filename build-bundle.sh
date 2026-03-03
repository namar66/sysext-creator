#!/bin/bash
set -euo pipefail

# 1. Host and App version detection
HOST_VER=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
APP_VER=$(grep -E '^readonly SYSEXT_CREATOR_VERSION=' sysext-creator-core.sh | cut -d'"' -f2)

if [[ -z "$APP_VER" ]]; then
    echo "❌ Error: Could not detect version from sysext-creator-core.sh!"
    exit 1
fi

OUTPUT_RAW="sysext-creator-v${APP_VER}-fc${HOST_VER}.raw"

# We capture your current UID/GID to fix permissions later
USER_UID=$(id -u)
USER_GID=$(id -g)

echo "💎 Bootstrapping Meta-Image: $OUTPUT_RAW using sudo podman..."

# Running with sudo podman
sudo podman run --rm -i -v "$PWD:/workspace:Z" -w /workspace "registry.fedoraproject.org/fedora:${HOST_VER}" bash -s "$HOST_VER" "$OUTPUT_RAW" "$APP_VER" "$USER_UID" "$USER_GID" << 'EOF'
set -euo pipefail

CONTAINER_HOST_VER="$1"
CONTAINER_OUTPUT_RAW="$2"
CONTAINER_APP_VER="$3"
OWNER_UID="$4"
OWNER_GID="$5"

echo "📦 Installing build tools..."
dnf install -y erofs-utils cpio dnf-utils > /dev/null 2>&1

echo "🏗️ Preparing build root..."
rm -rf build_root && mkdir -p build_root/usr/bin build_root/usr/lib/extension-release.d build_root/usr/share/bash-completion/completions

# 1. Bash Completion
cat << 'COMPLETION' > build_root/usr/share/bash-completion/completions/sysext-creator
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
        installed_pkgs=$(ls /var/lib/extensions/*.raw 2>/dev/null | xargs -n 1 basename 2>/dev/null | sed -E 's/-[0-9].*//' | sort -u)
        COMPREPLY=( $(compgen -W "${installed_pkgs}" -- "${cur}") )
        return 0
    fi
    COMPREPLY=()
}
complete -F _sysext_creator_completions sysext-creator
COMPLETION

# 2. Scripts
cp sysext-creator.sh build_root/usr/bin/sysext-creator
cp sysext-creator-core.sh build_root/usr/bin/sysext-creator-core
cp sysext-setup.sh build_root/usr/bin/sysext-setup
chmod +x build_root/usr/bin/*

# 3. Dependencies
mkdir -p build_temp && cd build_temp
dnf download distrobox erofs-utils > /dev/null 2>&1
for f in *.rpm; do
    rpm2cpio "$f" | cpio -idm -D ../build_root --quiet 2>/dev/null || true
done
cd .. && rm -rf build_temp

# 4. Metadata
cat << META > "build_root/usr/lib/extension-release.d/extension-release.sysext-creator-v${CONTAINER_APP_VER}-fc${CONTAINER_HOST_VER}"
ID=fedora
VERSION_ID=${CONTAINER_HOST_VER}
META

# 5. Bake
echo "🔥 Baking EROFS image..."
mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$CONTAINER_OUTPUT_RAW" build_root > /dev/null

# 🔑 FIX: Return ownership to the host user
chown "${OWNER_UID}:${OWNER_GID}" "$CONTAINER_OUTPUT_RAW"
rm -rf build_root
EOF

echo "✅ DONE! Your final self-contained tool is ready: $OUTPUT_RAW"
