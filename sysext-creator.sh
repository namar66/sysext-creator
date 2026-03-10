#!/bin/bash

################################################################################
# Sysext-Creator Wrapper (v2.0.0 - Pure Podman Edition)
################################################################################

set -euo pipefail

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STAGING_DIR="/var/tmp/sysext-staging"

# Chytrá autodetekce jádra
if ! RAW_CORE_PATH=$(command -v sysext-creator-core 2>/dev/null); then
    echo "❌ Error: sysext-creator-core not found in PATH."
    exit 1
fi

# Získáme absolutní cestu (pojistka proti symlinkům)
HOST_CORE_PATH=$(realpath "$RAW_CORE_PATH")

# Jelikož čistý Podman nemá automaticky namapovanou domovskou složku,
# musíme hostitelskou cestu VŽDY hledat přes náš namapovaný root (/run/host)
CORE_EXEC="/run/host${HOST_CORE_PATH}"

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

get_installed_version() {
    local pkg="$1"
    local req_file="$STAGING_DIR/${pkg}.version-req"
    local res_file="$STAGING_DIR/${pkg}.version-res"

    touch "$req_file"
    local timeout=20
    while [[ ! -f "$res_file" && $timeout -gt 0 ]]; do
        sleep 0.2
        ((timeout--))
    done

    if [[ -f "$res_file" ]]; then
        cat "$res_file"
        rm -f "$res_file"
    else
        echo "unknown"
    fi
}

cmd_list() {
    echo "=> Listing installed system extensions:"
    local packages=$(find "/var/lib/extensions" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -r -n1 basename -s .raw | sed 's/-fc[0-9]\+$//' | sort -u | tr -d '\r')

    if [[ -z "$packages" ]]; then
        echo "📋 No packages are installed."
        return 0
    fi

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        local v=$(get_installed_version "$pkg")
        echo " 📦 $pkg (Version: ${v:-unknown})"
    done
}

cmd_remove() {
    local pkg="$1"
    local force_all="${2:-false}"

    if [[ "$pkg" == "sysext-creator" || "$pkg" == "sysext-creator-kinoite" ]]; then
        echo "❌ Error: This tool cannot be removed with the regular rm command."
        echo "   For complete and safe removal, use the setup script with 'uninstall'."
        exit 1
    fi

    local check_exists=$(find "/var/lib/extensions" -maxdepth 1 \( -name "${pkg}-fc*.raw" -o -name "${pkg}.raw" \) 2>/dev/null)
    if [[ -z "$check_exists" ]]; then
        echo "📋 Package '$pkg' is not installed. Nothing to do."
        return 0
    fi

    echo "=> Requesting daemon to remove extension $pkg..."
    touch "$STAGING_DIR/${pkg}.delete"

    local TRACKER_FILE="$HOME/.local/state/sysext-creator/etc_tracker.txt"
    if [[ "$force_all" == "yes" && -f "$TRACKER_FILE" ]]; then
        echo "=> Extracting configuration files list for $pkg from tracker..."
        awk "/^######## $pkg ########/{flag=1; next} /^########/{flag=0} flag" "$TRACKER_FILE" > "$STAGING_DIR/${pkg}.etc.remove"
    fi

    echo "✅ Removal request for package $pkg was sent."
}

garbage_collect() {
    local old_containers=$(podman ps -a --format '{{.Names}}' | grep '^sysext-box-fc' | grep -v "^${CONTAINER_NAME}$" || true)

    if [[ -n "$old_containers" ]]; then
        echo "🧹 Found legacy containers from previous Fedora versions. Starting cleanup..."
        for old_box in $old_containers; do
            echo "=> Removing old container: $old_box"
            podman rm -f "$old_box" >/dev/null 2>&1
        done
        echo "✅ Garbage Collection completed."
    fi
}

check_container() {
    local recreate=0

    # Zkontrolujeme, zda kontejner existuje
    if ! podman ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "⚠️ Container $CONTAINER_NAME does not exist."
        recreate=1
    else
        # Kontrola, jestli má kontejner správné mounty (pro nativní Podman)
        local mounts=$(podman inspect "$CONTAINER_NAME" --format '{{.Mounts}}' 2>/dev/null || true)
        if [[ "$mounts" != *"$STAGING_DIR"* ]] || [[ "$mounts" != *"/run/host"* ]]; then
            echo "⚠️ Container $CONTAINER_NAME is missing required mounts. Rebuilding..."
            podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1
            recreate=1
        else
            # Pokud existuje, ale neběží, probudíme ho
            local state=$(podman inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo "false")
            if [[ "$state" != "true" ]]; then
                echo "=> Waking up sleeping container $CONTAINER_NAME..."
                podman start "$CONTAINER_NAME" >/dev/null
            fi
        fi
    fi

    if [[ $recreate -eq 1 ]]; then
        echo "=> Starting build of persistent Podman container $CONTAINER_NAME..."

        podman run -d --name "$CONTAINER_NAME" \
            --privileged \
            -v "$STAGING_DIR":"$STAGING_DIR":rw \
            -v "/var/lib/extensions:/var/lib/extensions:ro" \
            -v "/etc/yum.repos.d:/etc/yum.repos.d:ro" \
            -v "/:/run/host:ro" \
            -v "/run/dbus/system_bus_socket:/run/dbus/system_bus_socket" \
            "registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION}" \
            sleep infinity >/dev/null

        echo "=> Installing required dependencies inside the container..."
        podman exec "$CONTAINER_NAME" dnf install -y erofs-utils cpio dnf-utils selinux-policy-targeted
        echo "✅ Container successfully restored and ready!"
    fi
}

main() {
    [[ $# -lt 1 ]] && { echo "Usage: sysext-creator install|install-local|update|check-update|search [package/path]"; exit 1; }

    garbage_collect
    check_container

    local cmd="$1"

    # 1. Zjistíme seznam na hostiteli (ten umí číst chráněnou složku)
    local pkgs=$(find "/var/lib/extensions" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -r -n1 basename -s .raw | sed 's/-fc[0-9]\+$//' | sort -u | tr -d '\r' | tr '\n' ' ' || true)

    case "$cmd" in
        install)
            local target="$2"
            if [[ -f "$target" && "$target" == *.rpm ]]; then
                local abs_path=$(realpath "$target")
                echo "=> Local package detected, starting offline installation..."
                podman exec -i "$CONTAINER_NAME" "$CORE_EXEC" install-local "$abs_path"
            else
                podman exec -i "$CONTAINER_NAME" "$CORE_EXEC" install "$target"
            fi
            ;;
        update|check-update)
            # 2. TUNEL: Tady pošleme ten náš seznam dovnitř kontejneru
            podman exec -e HOST_PKGS="$pkgs" -i "$CONTAINER_NAME" "$CORE_EXEC" "$@"
            ;;
        search)
            podman exec -i "$CONTAINER_NAME" "$CORE_EXEC" "$@"
            ;;
        *)
            echo "❌ Unknown command: $cmd"
            exit 1
            ;;
    esac
}
#COMMAND="$1"

COMMAND="${1:-}"

# Rychlé odchycení příkazů, které nepotřebují kontejner (OBROVSKÉ zrychlení)
if [[ "$COMMAND" == "doctor" ]] || [[ "$COMMAND" == "audit" ]]; then
    cmd_doctor
    exit 0
elif [[ "$COMMAND" == "list" ]]; then
    cmd_list
    exit 0
elif [[ "$COMMAND" == "rm" ]]; then
    cmd_remove "${2:-}" "${3:-false}"
    exit 0
fi

# Pokud to není ani jeden z výše uvedených, nabootujeme kontejner a pošleme to do něj
main "$@"
