#!/bin/bash
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STAGING_DIR="/var/tmp/sysext-staging"

# Function to verify if the container has the required volume mounted
check_container_mounts() {
    # Check if container exists
    if ! distrobox list | grep -q "$CONTAINER_NAME"; then
        return 1
    fi

    # Inspect container mounts to find our staging directory
    local mount_exists
    mount_exists=$(podman inspect "$CONTAINER_NAME" --format '{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' | grep "$STAGING_DIR" || true)

    if [[ -z "$mount_exists" ]]; then
        echo "⚠️ Warning: Container '$CONTAINER_NAME' is missing the required mount: $STAGING_DIR"
        return 1
    fi

    return 0
}

# Logic to ensure the container is ready and correctly configured
if [ "${1:-}" == "upgrade-box" ] || ! check_container_mounts; then
    echo "📦 Ensuring container '$CONTAINER_NAME' is ready with correct mounts..."

    # If container exists but is invalid or upgrade is requested, remove it
    if distrobox list | grep -q "$CONTAINER_NAME"; then
        echo "=> Re-creating container to fix mounts or perform upgrade..."
        distrobox rm -f "$CONTAINER_NAME"
    fi

    echo "=> Creating container '$CONTAINER_NAME' with volume '$STAGING_DIR'..."
    distrobox create --name "$CONTAINER_NAME" \
        --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} \
        --volume "$STAGING_DIR":"$STAGING_DIR":rw -Y

    echo "=> Installing required tools inside the container..."
    distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils

    # If this was an upgrade-box command, trigger the update and cleanup
    if [ "${1:-}" == "upgrade-box" ]; then
        echo "🔄 Rebuilding installed applications for the new OS version..."
        distrobox-enter -n "$CONTAINER_NAME" -- sysext-creator-core update
        echo "✅ Rebuild complete!"

        # Garbage Collector (N-1 rule)
        OLD_BOXES=$(distrobox list --no-color | grep -o "sysext-box-fc[0-9]*" | grep -v "$CONTAINER_NAME" | sort -u || true)
        if [ -n "$OLD_BOXES" ]; then
            echo "🧹 Running Garbage Collector..."
            BOXES_TO_DELETE=$(echo "$OLD_BOXES" | tr ' ' '\n' | sort -r | tail -n +2)
            if [ -n "$BOXES_TO_DELETE" ]; then
                 for box in $BOXES_TO_DELETE; do
                     echo "🗑️ Deleting obsolete container: '$box'"
                     distrobox rm -f "$box"
                 done
            fi
        fi
        exit 0
    fi
fi

# Route standard commands to the current validated container
distrobox-enter -n "$CONTAINER_NAME" -- sysext-creator-core "$@"
