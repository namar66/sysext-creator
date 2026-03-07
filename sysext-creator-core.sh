#!/bin/bash

################################################################################
# Sysext-Creator-Core (v1.4.3 - The Ultimate Edition)
# Běží výhradně uvnitř distrobox kontejneru.
################################################################################

set -euo pipefail

# ============================================================================
# CONSTANTS
# ============================================================================

readonly EXT_DIR="/var/lib/extensions"
readonly STAGING_DIR="/var/tmp/sysext-staging"
readonly STATE_DIR="$HOME/.local/state/sysext-creator"
readonly TRACKER_FILE="${STATE_DIR}/etc_tracker.txt"

readonly REQUIRED_CMDS=("mkfs.erofs" "cpio" "rpm2cpio" "repoquery")
readonly SPECIAL_PACKAGES=("vivaldi-stable")
readonly BLACKLIST=("glibc" "systemd" "dnf" "microdnf" "rpm-ostree" "pam" "kernel" "grub2" "dracut" "passwd" "shadow-utils" "sudo" "tar")

WORKDIR=""

# ============================================================================
# LOGGING & CLEANUP
# ============================================================================

die() { echo -e "❌ Error: $1" >&2; cleanup_workdir; exit "${2:-1}"; }
info() { echo "=> $1" >&2; }
status() { echo "📋 $1" >&2; }
success() { echo "✅ $1" >&2; }
warn() { echo "⚠️  $1" >&2; }

cleanup_workdir() { [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR"; }

# ============================================================================
# VALIDATION & VERSIONING
# ============================================================================

validate_environment() {
    for cmd in "${REQUIRED_CMDS[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            die "Missing required command: $cmd\nInstall with: sudo dnf install -y erofs-utils cpio dnf-utils"
        fi
    done

    if ! distrobox-host-exec test -w "$STAGING_DIR"; then
        die "Missing write permissions to $STAGING_DIR. Ensure the host daemon is active."
    fi

    local host_version=$(distrobox-host-exec grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')
    local guest_version=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')

    if [[ "$host_version" != "$guest_version" ]]; then
        distrobox-host-exec notify-send -u critical "Sysext-Creator" "OS upgrade detected! Run: sysext-creator upgrade-box" || true
        die "OS mismatch: Host ($host_version) != Guest ($guest_version)."
    fi
    echo "$host_version"
}

get_installed_version() {
    local package="$1"
    local req_file="$STAGING_DIR/${package}.version-req"
    local res_file="$STAGING_DIR/${package}.version-res"

    if ! distrobox-host-exec test -f "$EXT_DIR/${package}.raw"; then echo ""; return 0; fi

    distrobox-host-exec sh -c "echo 'req' > \"$req_file\""
    local timeout=20
    while ! distrobox-host-exec test -f "$res_file"; do
        sleep 0.5; timeout=$((timeout - 1))
        [[ $timeout -le 0 ]] && { echo ""; return 0; }
    done

    local version=$(distrobox-host-exec cat "$res_file" 2>/dev/null | tr -d '\r\n')
    distrobox-host-exec rm -f "$res_file"
    echo "$version"
}

get_available_version() { dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" "$1" 2>/dev/null || echo ""; }

get_host_packages() {
    local target="$1"
    local raw_output=$(distrobox-host-exec rpm-ostree install --dry-run "$target" 2>/dev/null)
    echo "$raw_output" | sed -n -e '/packages:/,$p' -e '/^Added:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | sort -u | tr '\n' ' '
}

# ============================================================================
# BUILD LOGIC
# ============================================================================

# 1. Standardní instalace z repozitářů Fedory
cmd_install() {
    local package="$1" host_version="$2" mode="${3:-install}"
    [[ "$package" =~ ^($(IFS='|'; echo "${BLACKLIST[*]}"))$ ]] && die "Installation of '$package' is blocked."

    local installed_v=$(get_installed_version "$package")
    local available_v=$(get_available_version "$package")

    status "Package: $package | Available: ${available_v:-unknown} | Installed: ${installed_v:-not installed}"
    [[ "$installed_v" == "$available_v" && -n "$installed_v" ]] && { status "Already up to date"; return 0; }

    WORKDIR=$(mktemp -d)
    mkdir -p "$WORKDIR/rpms"

    info "Resolving dependencies..."
    local deps=$(get_host_packages "$package")
    [[ -z "$deps" || "$deps" == " " ]] && deps="$package"

    info "Downloading and extracting packages..."
    dnf download $deps --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$WORKDIR/rpms" >/dev/null
    for rpm in "$WORKDIR/rpms"/*.rpm; do rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null; done

    process_extension "$package" "$host_version" "$available_v" "$mode"
}

# 2. Instalace lokálního RPM souboru (např. staženého z webu)
cmd_install_local() {
    local rpm_path="$1" host_version="$2"

    [[ ! -f "$rpm_path" ]] && die "Soubor nenalezen: $rpm_path"

    info "Analyzuji lokální soubor..."
    local package=$(rpm -qp --queryformat '%{NAME}' "$rpm_path" 2>/dev/null)
    local available_v=$(rpm -qp --queryformat '%{VERSION}-%{RELEASE}' "$rpm_path" 2>/dev/null)

    [[ -z "$package" ]] && die "Nelze přečíst metadata z lokálního RPM balíčku."

    local installed_v=$(get_installed_version "$package")
    status "Lokální balíček: $package | Verze: $available_v | Nainstalováno: ${installed_v:-ne}"
    [[ "$installed_v" == "$available_v" && -n "$installed_v" ]] && { status "Tato verze už je nainstalovaná."; return 0; }

    WORKDIR=$(mktemp -d)
    mkdir -p "$WORKDIR/rpms"

    info "Zjišťuji závislosti přes hostitelský systém..."
    local deps=$(get_host_packages "$rpm_path")

    # 🆕 FILTR: Vyhodíme samotný balíček ze seznamu, aby ho DNF nehledalo na webu
    deps=$(echo "$deps" | tr ' ' '\n' | grep -v "^${package}$" | tr '\n' ' ' | xargs)

    if [[ -n "$deps" ]]; then
        info "Stahuji chybějící závislosti z repozitářů Fedory: $deps"
        dnf download $deps --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$WORKDIR/rpms" --skip-unavailable >/dev/null
    else
        info "Žádné další závislosti z repozitářů nejsou potřeba."
    fi

    info "Kopíruji a rozbaluji RPM balíčky..."
    cp "$rpm_path" "$WORKDIR/rpms/"
    for rpm in "$WORKDIR/rpms"/*.rpm; do rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null; done

    process_extension "$package" "$host_version" "$available_v" "install"
}

# 3. Společná funkce pro zabalení (aby se neopakoval kód)
process_extension() {
    local package="$1" host_version="$2" available_v="$3" mode="$4"

    mkdir -p "$WORKDIR/usr/lib/extension-release.d"
    echo -e "ID=fedora\nVERSION_ID=$host_version\nSYSEXT_VERSION_ID=$available_v" > "$WORKDIR/usr/lib/extension-release.d/extension-release.${package}"

    if [[ "$mode" != "update" ]] && ! [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]] && [[ -d "$WORKDIR/etc" ]]; then
        info "Dispatching /etc configuration..."
        tar -czf "$WORKDIR/${package}.etc.tar.gz" -C "$WORKDIR/etc" .
        distrobox-host-exec mv "$WORKDIR/${package}.etc.tar.gz" "$STAGING_DIR/"
        mkdir -p "$STATE_DIR"
        echo "######## $package ########" >> "$TRACKER_FILE"
        find "$WORKDIR/etc" -type f | sed "s|$WORKDIR||" >> "$TRACKER_FILE"
        rm -rf "$WORKDIR/etc"
    fi

    local raw_file="$WORKDIR/${package}.raw"
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$raw_file" "$WORKDIR" >/dev/null
    distrobox-host-exec mv "$raw_file" "$STAGING_DIR/"

    success "$package dispatched for deployment"
    cleanup_workdir
}

# ============================================================================
# COMMANDS
# ============================================================================

cmd_list() {
    info "Listing installed sysext packages:"
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} .raw | sort | tr -d '\r')
    [[ -z "$packages" ]] && { status "No packages installed."; return 0; }

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        sleep 0.5
        local v=$(get_installed_version "$pkg")
        echo " 📦 $pkg (Version: ${v:-unknown})"
    done
}

cmd_remove() {
    local pkg="$1"
    ! distrobox-host-exec test -f "$EXT_DIR/${pkg}.raw" && ! grep -q "^######## $pkg ########$" "$TRACKER_FILE" 2>/dev/null && { warn "Not installed."; return 0; }

    info "Removing $pkg..."
    if [[ -f "$TRACKER_FILE" ]]; then
        local files=$(sed -n "/^######## $pkg ########$/,/^######## /p" "$TRACKER_FILE" | grep -v "^########" || true)
        if [[ -n "$files" ]]; then
            echo -e "\n⚠️ Config files found:\n$files"
            read -p "Delete these files? [A]ll / [N]one [N]: " c
            case "${c^^}" in
                A)
                   local rm_f=$(mktemp)
                   echo "$files" > "$rm_f"
                   distrobox-host-exec mv "$rm_f" "$STAGING_DIR/${pkg}.etc.remove"
                   ;;
            esac
        fi
        awk -v p="######## $pkg ########" '$0 == p { s=1; next } s && /^######## / { s=0 } !s { print }' "$TRACKER_FILE" > "${TRACKER_FILE}.tmp" && mv "${TRACKER_FILE}.tmp" "$TRACKER_FILE"
    fi

    distrobox-host-exec sh -c "echo 'delete' > \"$STAGING_DIR/${pkg}.delete\""
    success "$pkg dispatched for removal"
}

cmd_check_update() {
    info "Zjišťuji dostupné aktualizace..."
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} .raw | sort | tr -d '\r')

    [[ -z "$packages" ]] && { status "Žádné balíčky nejsou nainstalovány."; return 0; }

    local updates_available=0

    # Hlavička tabulky po vzoru DNF
    echo ""
    printf "%-30s %-25s %-25s\n" "BALÍČEK" "NAINSTALOVÁNO" "DOSTUPNÉ"
    echo "--------------------------------------------------------------------------------"

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        sleep 0.5 # Jemný throttling pro démona

        local installed_v=$(get_installed_version "$pkg")
        local available_v=$(get_available_version "$pkg")

        [[ -z "$available_v" ]] && available_v="unknown"
        [[ -z "$installed_v" ]] && installed_v="unknown"

        # Pokud se verze liší a zároveň je v repozitáři dostupná nová verze
        if [[ "$installed_v" != "$available_v" && "$available_v" != "unknown" ]]; then
            printf "%-30s %-25s %-25s\n" "$pkg" "$installed_v" "$available_v"
            updates_available=1
        fi
    done

    echo ""
    if [[ $updates_available -eq 0 ]]; then
        success "Všechna systémová rozšíření jsou aktuální."
    else
        info "Pro instalaci těchto aktualizací spusťte: sysext-creator update"
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    [[ $# -lt 1 ]] && { echo "Usage: $0 install|install-local|update|rm|list"; exit 1; }
    local h_v=$(validate_environment)
    case "$1" in
        install)       cmd_install "$2" "$h_v" "install" ;;
        install-local) cmd_install_local "$2" "$h_v" ;;
        update)        for p in $(distrobox-host-exec ls "$EXT_DIR"/*.raw 2>/dev/null | xargs -n1 basename -s .raw); do cmd_install "$p" "$h_v" "update"; done ;;
        check-update)  cmd_check_update ;;
        rm)            cmd_remove "$2" ;;
        list)          cmd_list ;;
        *)             die "Unknown command: $1" ;;
    esac
}

main "$@"
