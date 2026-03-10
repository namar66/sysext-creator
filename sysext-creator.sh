#!/bin/bash

################################################################################
# Sysext-Creator Wrapper (v1.6.0 - Universal & Self-Contained SELinux)
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
    echo "=> 🩺 Starting diagnostics of installed images (Sysext Doctor)..."
    local host_ver=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
    local ext_dir="/var/lib/extensions"
    local ext_count=0
    local has_errors=0

    echo "=> Vyžadována práva administrátora pro analýzu obrazů..."
    sudo -v || { echo "❌ Sudo oprávnění bylo zamítnuto." >&2; exit 1; }

    local images=$(find "$ext_dir" -maxdepth 1 -name "*.raw" -type f 2>/dev/null || true)

    if [[ -z "$images" ]]; then
        echo "--------------------------------------------------------"
        echo "📋 No installed images found for diagnostics."
        return 0
    fi

    for img in $images; do
        ext_count=$((ext_count + 1))
        local img_name=$(basename "$img" .raw)

        echo "--------------------------------------------------------"
        echo "🔍 Checking image: $img_name.raw"

        # 1. STRUCTURAL INTEGRITY CHECK
        if ! sudo systemd-dissect --validate "$img" >/dev/null 2>&1; then
            echo "❌ ERROR: Image structure is corrupted or invalid!" >&2
            has_errors=1
            continue
        else
            echo "✅ Image structure and format are valid."
        fi

        # 2. LABEL AND VERSION CHECK
        local release_file="usr/lib/extension-release.d/extension-release.${img_name}"
        local img_ver=""

        if ! sudo systemd-dissect --copy-from "$img" "/$release_file" - >/dev/null 2>&1; then
            echo "❌ ERROR: Missing or incorrectly named release label!" >&2
            echo "   Expected path inside the image: /$release_file" >&2
            has_errors=1
        else
            img_ver=$(sudo systemd-dissect --copy-from "$img" "/$release_file" - 2>/dev/null | grep "^VERSION_ID=" | cut -d'=' -f2 || true)
            if [[ "$img_ver" != "$host_ver" ]]; then
                echo "⚠️  WARNING: Image version ($img_ver) does not match the host ($host_ver)!" >&2
                has_errors=1
            else
                echo "✅ Label and OS version ($img_ver) match."
            fi
        fi

        # 3. BASE SYSTEM CONFLICT CHECK
        echo "🛠️  Scanning for conflicts with the base system (shadowing)..."
        local conflicts=0

        # OPRAVA: Povolíme cesty bez lomítka na začátku (^/?)
        local files_to_check=$(sudo systemd-dissect --list "$img" 2>/dev/null | grep -E '^/?usr/(bin|sbin|lib/systemd)/' || true)

        if [[ -n "$files_to_check" ]]; then
            for file in $files_to_check; do
                # OPRAVA: Přidáme lomítko na začátek, aby RPM databáze soubor poznala
                local abs_file="$file"
                [[ "$abs_file" != /* ]] && abs_file="/$abs_file"

                # Ptáme se hostitelské RPM databáze na absolutní cestu
                if rpm -qf "$abs_file" >/dev/null 2>&1; then
                    # Složky jako /usr/bin ignorujeme, zajímají nás jen skutečné soubory (binárky)
                    if ! test -d "$abs_file"; then
                        echo "   ⚠️  CONFLICT DETECTED: $abs_file (already exists in the base system!)" >&2
                        conflicts=$((conflicts + 1))
                    fi
                fi
            done
        fi

        if [[ $conflicts -eq 0 ]]; then
            echo "✅ No conflicts with the base system found."
        else
            echo "❌ Found a total of $conflicts conflicting file(s)." >&2
            has_errors=1
        fi
    done

    echo "--------------------------------------------------------"
    if [[ $has_errors -eq 0 ]]; then
        echo "✅ Diagnostics completed. All images are in 100% perfect condition!"
    else
        echo "⚠️  Diagnostics completed, but issues were found. Please fix them, or the system extensions might not work properly." >&2
    fi
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
