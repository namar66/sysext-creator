#!/bin/bash

################################################################################
# Sysext-Creator Wrapper (v1.6.2 - Universal & Self-Contained SELinux)
################################################################################

set -euo pipefail

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STAGING_DIR="/var/tmp/sysext-staging"

# Chytrá autodetekce jádra (Local vs System-wide)
if ! HOST_CORE_PATH=$(command -v sysext-creator-core 2>/dev/null); then
    echo "❌ Error: sysext-creator-core not found in PATH."
    exit 1
fi

if [[ "$HOST_CORE_PATH" == /usr/* ]]; then
    # Běžíme z RPM balíčku nebo RAW obrazu -> kontejner musí jít přes můstek
    CORE_EXEC="/run/host${HOST_CORE_PATH}"
else
    # Běžíme lokálně (např. ~/.local/bin) -> kontejner sdílí složku přímo
    CORE_EXEC="$HOST_CORE_PATH"
fi

cmd_doctor() {
    echo "=> 🩺 Requesting system diagnostics from daemon..."
    local req_file="/var/tmp/sysext-staging/doctor.req"
    local res_file="/var/tmp/sysext-staging/doctor.res"

    rm -f "$res_file"
    touch "$req_file"

    # Čekáme, dokud démon nezpracuje požadavek (timeout 15 sekund)
    local counter=0
    while [[ ! -f "$res_file" ]]; do
        sleep 0.5
        counter=$((counter + 1))
        if [[ $counter -gt 30 ]]; then
            echo "❌ ERROR: Daemon did not respond in time." >&2
            rm -f "$req_file"
            exit 1
        fi
    done

    # Vypíšeme výsledek a uklidíme
    cat "$res_file"
    rm -f "$res_file"
}

garbage_collect() {
    local old_containers=$(podman ps -a --format '{{.Names}}' | grep '^sysext-box-fc' | grep -v "^${CONTAINER_NAME}$" || true)

    if [[ -n "$old_containers" ]]; then
        echo "🧹 Found legacy containers from previous Fedora versions. Starting cleanup..."
        for old_box in $old_containers; do
            echo "=> Removing old container: $old_box"
            distrobox rm -Y "$old_box" >/dev/null 2>&1 || podman rm -f "$old_box" >/dev/null 2>&1
        done
        echo "✅ Garbage Collection completed."
    fi
}

check_container() {
    local recreate=0

    if ! podman ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "⚠️ Container $CONTAINER_NAME does not exist."
        recreate=1
    else
        local mounts=$(podman inspect "$CONTAINER_NAME" --format '{{.Mounts}}' 2>/dev/null || true)
        if [[ "$mounts" != *"$STAGING_DIR"* ]] || [[ "$mounts" != *"/etc/yum.repos.d"* ]]; then
            echo "⚠️ Container $CONTAINER_NAME is missing required mounts. Rebuilding..."
            distrobox rm -Y "$CONTAINER_NAME" >/dev/null 2>&1 || podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1
            recreate=1
        fi
    fi

    if [[ $recreate -eq 1 ]]; then
        echo "=> Starting build of container $CONTAINER_NAME..."
        distrobox create \
            --name "$CONTAINER_NAME" \
            --image "registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION}" \
            --volume "$STAGING_DIR":"$STAGING_DIR":rw \
            --volume "/etc/yum.repos.d:/etc/yum.repos.d:ro" \
            -Y

        echo "=> Installing required dependencies inside the container..."
        # ZDE PŘIDÁNA INSTALACE selinux-policy-targeted
        distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils selinux-policy-targeted
        echo "✅ Container successfully restored and ready!"
    fi
}

main() {
    [[ $# -lt 1 ]] && { echo "Usage: sysext-creator install|install-local|update|check-update|rm|list|search [package/path]"; exit 1; }

    garbage_collect
    check_container

    local cmd="$1"

    case "$cmd" in
        install)
            local target="$2"
            if [[ -f "$target" && "$target" == *.rpm ]]; then
                local abs_path=$(realpath "$target")
                echo "=> Local package detected, starting offline installation..."
                distrobox enter "$CONTAINER_NAME" -- "$CORE_EXEC" install-local "$abs_path"
            else
                distrobox enter "$CONTAINER_NAME" -- "$CORE_EXEC" install "$target"
            fi
            ;;
        rm|update|check-update|list|search|doctor)
            distrobox enter "$CONTAINER_NAME" -- "$CORE_EXEC" "$@"
            ;;
        *)
            echo "❌ Unknown command: $cmd"
            exit 1
            ;;
    esac
}
COMMAND="$1"

# Odchytíme doctor na hostiteli
if [[ "$COMMAND" == "doctor" ]] || [[ "$COMMAND" == "audit" ]]; then
    cmd_doctor
    exit 0
fi
main "$@"
