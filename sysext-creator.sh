#!/bin/bash

################################################################################
# Sysext-Creator Wrapper (v2.0 - Pure Podman Edition)
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

# ======================================================================
# POMOCNÉ FUNKCE NA HOSTITELI (Mimo kontejner)
# ======================================================================
resolve_deps() {
    local target="$1"
    # Voláme rpm-ostree BEZPEČNĚ přímo na hostiteli
    rpm-ostree install --dry-run "$target" 2>/dev/null | sed -n -e '/packages:/,$p' -e '/^Added:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | sort -u | tr '\n' ' ' || true
}

cmd_doctor() {
    echo "=> 🩺 Requesting system diagnostics from daemon..."
    local req_file="/var/tmp/sysext-staging/doctor.req"
    local res_file="/var/tmp/sysext-staging/doctor.res"

    rm -f "$res_file"
    touch "$req_file"

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
    local auto_yes="${2:-}"

    if [[ "$pkg" == "sysext-creator" || "$pkg" == "sysext-creator-kinoite" ]]; then
        echo "❌ Error: This tool cannot be removed with the regular rm command."
        exit 1
    fi

    local check_exists=$(find "/var/lib/extensions" -maxdepth 1 \( -name "${pkg}-fc*.raw" -o -name "${pkg}.raw" \) 2>/dev/null)
    if [[ -z "$check_exists" ]]; then
        echo "📋 Package '$pkg' is not installed. Nothing to do."
        return 0
    fi

    local tracker_file="/var/lib/sysext-creator/trackers/${pkg}.etc.tracker"
    local del_payload=""

    if [[ -f "$tracker_file" ]]; then
        if [[ "$auto_yes" == "yes" || "$auto_yes" == "true" ]]; then
            del_payload="FORCE_ETC_CLEANUP\n"
        else
            echo -e "\n📦 Balíček '$pkg' vytvořil tyto konfigurační soubory:"
            while IFS= read -r f; do
                echo "  📄 $f"
            done < "$tracker_file"
            echo ""

            read -p "Chceš je také trvale smazat? [Y(vše) / N(nic) / S(vybrat ručně)]: " choice
            case "${choice,,}" in
                y|yes)
                    del_payload="FORCE_ETC_CLEANUP\n"
                    ;;
                s|select)
                    del_payload="SELECTED_ETC_CLEANUP\n"
                    echo "=> Vybírání souborů ke smazání:"
                    while IFS= read -r f; do
                        # OPRAVA BASH PASTI: čteme přímo z terminálu, nikoliv z tracker souboru
                        read -p "  🗑️ Smazat $f? [y/N]: " subchoice </dev/tty
                        if [[ "${subchoice,,}" == "y" ]]; then
                            del_payload="${del_payload}${f}\n"
                        fi
                    done < "$tracker_file"
                    ;;
                *)
                    echo "=> Ponechávám konfigurační soubory v systému (/etc/)."
                    ;;
            esac
        fi
    fi

    echo "=> Requesting daemon to remove extension $pkg..."
    echo -e "$del_payload" > "$STAGING_DIR/${pkg}.delete"
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

    if ! podman ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        recreate=1
    else
        local mounts=$(podman inspect "$CONTAINER_NAME" --format '{{.Mounts}}' 2>/dev/null || true)
        if [[ "$mounts" != *"$STAGING_DIR"* ]] || [[ "$mounts" != *"/run/host"* ]]; then
            echo "⚠️ Container $CONTAINER_NAME is missing required mounts. Rebuilding..."
            podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1
            recreate=1
        else
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
            -v /etc/selinux/targeted/contexts/files/file_contexts:/tmp/file_contexts:ro \
            -v "/etc/yum.repos.d:/etc/yum.repos.d:ro" \
            -v "/:/run/host:ro" \
            -v "/run/dbus/system_bus_socket:/run/dbus/system_bus_socket" \
            "registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION}" \
            sleep infinity >/dev/null

        echo "=> Installing required dependencies inside the container..."
        podman exec "$CONTAINER_NAME" dnf install -y erofs-utils cpio dnf-utils
        echo "✅ Container successfully restored and ready!"
    fi
}

# ======================================================================
# HLAVNÍ LOGIKA (Vstupní bod)
# ======================================================================
main() {
    [[ $# -lt 1 ]] && { echo "Usage: sysext-creator install|install-local|update|check-update|rm|list|search|doctor [package/path]"; exit 1; }

    garbage_collect
    check_container

    local cmd="$1"
    local pkgs=$(find "/var/lib/extensions" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -r -n1 basename -s .raw | sed 's/-fc[0-9]\+$//' | sort -u | tr -d '\r' | tr '\n' ' ' || true)

    case "$cmd" in
        install)
            local target="$2"
            echo "=> Resolving dependencies via host system..."
            local deps=$(resolve_deps "$target")

            if [[ -f "$target" && "$target" == *.rpm ]]; then
                local abs_path=$(realpath "$target")
                echo "=> Local package detected, starting offline installation..."
                podman exec -e RESOLVED_DEPS="$deps" -i "$CONTAINER_NAME" "$CORE_EXEC" install-local "$abs_path"
            else
                podman exec -e RESOLVED_DEPS="$deps" -i "$CONTAINER_NAME" "$CORE_EXEC" install "$target"
            fi
            ;;
        update)
            if [[ -z "$pkgs" || "$pkgs" == " " ]]; then
                echo "📋 No packages installed for update."
                exit 0
            fi
            for target in $pkgs; do
                echo "=> Resolving dependencies for $target via host system..."
                local deps=$(resolve_deps "$target")
                podman exec -e RESOLVED_DEPS="$deps" -i "$CONTAINER_NAME" "$CORE_EXEC" update-single "$target"
            done
            ;;
        check-update)
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

# Pokud to není ani jeden z výše uvedených, předáme kontrolu funkci main (kontejneru)
main "$@"
