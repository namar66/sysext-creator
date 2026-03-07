#!/bin/bash

################################################################################
# Sysext-Creator Wrapper (v1.4.3 - GC & Self-Healing Edition)
################################################################################

set -euo pipefail

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STAGING_DIR="/var/tmp/sysext-staging"

# 🆕 GARBAGE COLLECTION: Smaže staré verze kontejnerů po upgradu OS
garbage_collect() {
    # Najde všechny kontejnery začínající na sysext-box-fc, kromě toho aktuálního
    local old_containers=$(podman ps -a --format '{{.Names}}' | grep '^sysext-box-fc' | grep -v "^${CONTAINER_NAME}$" || true)

    if [[ -n "$old_containers" ]]; then
        echo "🧹 Nalezena stará prostředí z předchozích verzí Fedory. Zahajuji úklid..."
        for old_box in $old_containers; do
            echo "=> Odstraňuji starý kontejner: $old_box"
            distrobox rm -Y "$old_box" >/dev/null 2>&1 || podman rm -f "$old_box" >/dev/null 2>&1
        done
        echo "✅ Garbage Collection dokončena."
    fi
}

# 🆕 KONTROLA MOUNTŮ A EXISTENCE: Sestaví nebo opraví kontejner
check_container() {
    local recreate=0

    if ! podman ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "⚠️ Kontejner $CONTAINER_NAME neexistuje."
        recreate=1
    else
        # Zkontroluje, zda jsou oba klíčové adresáře skutečně namapované uvnitř
        local mounts=$(podman inspect "$CONTAINER_NAME" --format '{{.Mounts}}' 2>/dev/null || true)
        if [[ "$mounts" != *"$STAGING_DIR"* ]] || [[ "$mounts" != *"/etc/yum.repos.d"* ]]; then
            echo "⚠️ Kontejner $CONTAINER_NAME má chybějící mounty (pravděpodobně byl vytvořen ručně). Bude přebudován."
            distrobox rm -Y "$CONTAINER_NAME" >/dev/null 2>&1 || podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1
            recreate=1
        fi
    fi

    # Pokud kontejner chybí nebo měl špatné mounty, vytvoříme ho znovu správně
    if [[ $recreate -eq 1 ]]; then
        echo "=> Zahajuji sestavení kontejneru $CONTAINER_NAME..."
        distrobox create \
            --name "$CONTAINER_NAME" \
            --image "registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION}" \
            --volume "$STAGING_DIR":"$STAGING_DIR":rw \
            --volume "/etc/yum.repos.d:/etc/yum.repos.d:ro" \
            -Y

        echo "=> Instaluji nezbytné závislosti uvnitř kontejneru..."
        distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils
        echo "✅ Kontejner úspěšně obnoven a připraven!"
    fi
}

main() {
    [[ $# -lt 1 ]] && { echo "Použití: sysext-creator install|update|rm|list [balíček/cesta]"; exit 1; }

    # 1. Uklidíme staré verze (např. po upgardu OS)
    garbage_collect

    # 2. Ověříme integritu aktuálního kontejneru
    check_container

    local cmd="$1"

    case "$cmd" in
        install)
            local target="$2"
            if [[ -f "$target" && "$target" == *.rpm ]]; then
                local abs_path=$(realpath "$target")
                echo "=> Detekován lokální balíček, spouštím offline instalaci..."
                distrobox enter "$CONTAINER_NAME" -- sysext-creator-core install-local "$abs_path"
            else
                distrobox enter "$CONTAINER_NAME" -- sysext-creator-core install "$target"
            fi
            ;;
        update|check-update|rm|list)
            distrobox enter "$CONTAINER_NAME" -- sysext-creator-core "$@"
            ;;
        *)
            echo "❌ Neznámý příkaz: $cmd"
            exit 1
            ;;
    esac
}

main "$@"
