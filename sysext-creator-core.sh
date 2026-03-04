#!/bin/bash
set -euo pipefail
cd /workspace

cmd_bake() {
    local package="$1"
    local host_ver="$2"
    local target_raw="$3"
    local pkg_list="$4"

    echo "🔥 [Worker] Oven is hot. Baking $target_raw..." >&2

    WORKDIR=$(mktemp -d)

    # 🧹 Zaručený úklid při jakémkoliv ukončení
    trap 'rm -rf "$WORKDIR"' EXIT

    local build_dir="$WORKDIR/build_root"
    mkdir -p "$build_dir" "$WORKDIR/rpms"

    # Stahování balíčků.
    # Poznámka: u $pkg_list záměrně nepoužíváme uvozovky pro rozdělení slov.
    # shellcheck disable=SC2086
    if ! dnf download --forcearch=x86_64 $pkg_list --refresh --skip-unavailable --destdir="$WORKDIR/rpms" >/dev/null 2>&1; then
        echo "❌ [Worker] DNF encountered a critical error while downloading." >&2
        exit 1
    fi

    # 🛑 Kontrola, jestli se skutečně stáhl hlavní balíček
    if ! ls "$WORKDIR/rpms/${package}"-*.rpm >/dev/null 2>&1; then
        echo "❌ [Worker] CRITICAL: Main package '$package' was not downloaded!" >&2
        echo "   Check if the required repository is available inside the container." >&2
        exit 1
    fi

    # Extrakce RPM do build složky
    # Používáme nullglob, aby cyklus bezpečně proběhl jen pokud existují soubory
    shopt -s nullglob
    for rpm in "$WORKDIR/rpms"/*.rpm; do
        rpm2cpio "$rpm" | cpio -idm -D "$build_dir" --quiet 2>/dev/null
    done
    shopt -u nullglob

    # Vytvoření povinných metadat pro systemd-sysext
    mkdir -p "$build_dir/usr/lib/extension-release.d"
    echo -e "ID=fedora\nVERSION_ID=$host_ver" > "$build_dir/usr/lib/extension-release.d/extension-release.${package}"

    # Tvorba vysoce komprimovaného EROFS obrazu
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$target_raw" "$build_dir" >/dev/null 2>&1

    # 📡 Signál pro hostitele, že je hotovo
    echo "STATUS:BAKED"
}

case "${1:-}" in
    bake) cmd_bake "${2:-}" "${3:-}" "${4:-}" "${5:-}" ;;
    *) echo "Unknown command" >&2; exit 1 ;;
esac
