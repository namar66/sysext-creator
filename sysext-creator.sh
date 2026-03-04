#!/bin/bash
set -e

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
SENTINEL_FILE="$HOME/.local/state/sysext-creator/presetup_done"

# 1. Check if setup is done and container exists
if [[ ! -f "$SENTINEL_FILE" ]] || ! distrobox list | grep -q "$CONTAINER_NAME"; then
    echo "⚠️  System is not configured or container is missing."
    if command -v sysext-setup &>/dev/null; then
        echo "=> Running sysext-setup to fix this..."
        sysext-setup
    else
        echo "❌ ERROR: Configuration tool sysext-setup is missing!"
        exit 1
    fi
    # If container still doesn't exist after setup, abort
    if ! distrobox list | grep -q "$CONTAINER_NAME"; then
        echo "❌ ERROR: Failed to create the container."
        exit 1
    fi
fi

# 2. OS Upgrade and cleanup (runs on the host)
if [ "${1:-}" == "upgrade-box" ]; then
    sysext-setup
    echo "🔄 Rebuilding applications for the new OS version..."
    distrobox-enter -n "$CONTAINER_NAME" -- /run/host/usr/bin/sysext-creator-core update

    OLD_BOXES=$(distrobox list --no-color | grep -o "sysext-box-fc[0-9]*" | grep -v "$CONTAINER_NAME" | sort -u || true)
    if [ -n "$OLD_BOXES" ]; then
        echo "🧹 Cleaning up old containers..."
        BOXES_TO_DELETE=$(echo "$OLD_BOXES" | tr ' ' '\n' | sort -r | tail -n +2)
        for box in $BOXES_TO_DELETE; do
            echo "🗑️ Deleting: '$box'"; distrobox rm -f "$box"
        done
    fi

    # Reload extensions after cleanup (Fedora 41+ standard)
    echo "=> Restarting systemd-sysext service..."
    sudo /usr/bin/systemctl restart systemd-sysext.service
    exit 0
fi

# 3. Pass everything else to the "core" script inside the container
distrobox-enter -n "$CONTAINER_NAME" -- /run/host/usr/bin/sysext-creator-core "$@"
