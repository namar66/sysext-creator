#!/bin/bash

################################################################################
# Sysext-Creator (Refactored Version v1.0 - The "Perfect Storm" Edition)
# Copyright (C) 2026 Martin Naď (namar66)
# License: GNU General Public License v2
################################################################################

set -euo pipefail

# ============================================================================
# CONSTANTS
# ============================================================================

readonly EXT_DIR="/var/lib/extensions"
# 🆕 Systémově čistá cesta pro trackovací soubory (už nešpiníme /var/lib)
readonly STATE_DIR="$HOME/.local/state/sysext-creator"
readonly TRACKER_FILE="${STATE_DIR}/etc_tracker.txt"

readonly REQUIRED_CMDS=("mksquashfs" "cpio" "rpm2cpio" "repoquery")
readonly COMPRESSION_LEVEL=19
readonly BLOCK_SIZE=1048576
readonly SPECIAL_PACKAGES=("vivaldi-stable")

# 🛡️ Ochrana: Seznam balíčků, které nesmí být instalovány
readonly BLACKLIST=("glibc" "systemd" "dnf" "microdnf" "rpm-ostree" "pam" "kernel" "grub2" "dracut" "passwd" "shadow-utils" "sudo" "tar")

# Global variable for cleanup
WORKDIR=""

# ============================================================================
# LOGGING FUNCTIONS (output to stderr)
# ============================================================================

die() {
    local exit_code=${2:-1}
    echo -e "❌ Error: $1" >&2
    cleanup_workdir
    exit "$exit_code"
}

info() { echo "=> $1" >&2; }
status() { echo "📋 $1" >&2; }
success() { echo "✅ $1" >&2; }
warn() { echo "⚠️  $1" >&2; }

cleanup_workdir() {
    if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
        rm -rf "$WORKDIR"
    fi
}

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

validate_environment() {
    for cmd in "${REQUIRED_CMDS[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            die "Missing required command: $cmd\nInstall with: sudo dnf install -y squashfs-tools cpio dnf-utils"
        fi
    done

    if ! distrobox-host-exec test -w "$EXT_DIR"; then
        die "Missing write permissions to $EXT_DIR.\nPlease ensure you are in the 'sysext-admins' group and have run setup.sh."
    fi

    # 🆕 Vyčištění zbytků zalomení řádků pomocí 'tr'
    local host_version guest_version
    host_version=$(distrobox-host-exec grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')
    guest_version=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')

    if [[ "$host_version" != "$guest_version" ]]; then
        distrobox-host-exec notify-send -u critical -i dialog-warning "Sysext-Creator" "Detekován upgrade Fedory ($guest_version -> $host_version)! Otevřete terminál a zadejte: sysext-creator upgrade-box" || true
        die "OS version mismatch: Host ($host_version) != Guest ($guest_version)\nPlease run: sysext-creator upgrade-box"
    fi

    echo "$host_version"
}

check_blacklist() {
    local package="$1"
    for bad_pkg in "${BLACKLIST[@]}"; do
        if [[ "$package" == "$bad_pkg" ]]; then
            die "Instalace balíčku '$package' je bezpečnostně zablokována!\nTento balíček by mohl poškodit hostitelský systém."
        fi
    done
}

# ============================================================================
# HELPER FUNCTIONS - PACKAGE INFORMATION
# ============================================================================

is_special_package() {
    local package="$1"
    for special in "${SPECIAL_PACKAGES[@]}"; do
        [[ "$package" == "$special" ]] && return 0
    done
    return 1
}

get_raw_pattern() {
    local package="$1"
    local host_version="$2"
    if is_special_package "$package"; then
        echo "${package}-*.raw"
    else
        echo "${package}-*.fc${host_version}.raw"
    fi
}

extract_version() {
    local raw_file="$1"
    local package="$2"
    basename "$raw_file" | sed "s|${package}-||" | sed 's|\.raw$||'
}

get_installed_version() {
    local package="$1"
    local host_version="$2"
    local pattern=$(get_raw_pattern "$package" "$host_version")
    local raw_file=$(distrobox-host-exec find "$EXT_DIR" -name "$pattern" 2>/dev/null | head -1) || true
    if [[ -z "$raw_file" ]]; then echo ""; else extract_version "$raw_file" "$package"; fi
}

get_available_version() {
    local package="$1"
    dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" "$package" 2>/dev/null || echo ""
}

# ============================================================================
# DEPENDENCY & DOWNLOAD FUNCTIONS
# ============================================================================

get_host_packages() {
    local package="$1"
    local raw_output=$(distrobox-host-exec rpm-ostree install --dry-run "$package" 2>/dev/null)
    echo "$raw_output" | sed -n '/packages:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | tr '\n' ' '
}

download_packages() {
    local packages="$1"
    local workdir="$2"
    info "Downloading packages from guest environment..."
    if [[ -z "$packages" || "$packages" == " " ]]; then
        die "No packages to download - dependency resolution failed"
    fi
    dnf download $packages --refresh --forcearch=x86_64 --destdir="$workdir/rpms" 2>/dev/null || \
        die "Failed to download packages for: $packages"
    local rpm_count=$(ls -1 "$workdir/rpms"/*.rpm 2>/dev/null | wc -l) || true
    [[ $rpm_count -eq 0 ]] && die "No packages downloaded - check package names: $packages"
    status "Downloaded $rpm_count RPM packages"
}

# ============================================================================
# PACKAGE PROCESSING FUNCTIONS
# ============================================================================

extract_rpms() {
    local workdir="$1"
    info "Extracting RPM packages..."
    for rpm in "$workdir/rpms"/*.rpm; do
        [[ -f "$rpm" ]] || continue
        rpm2cpio "$rpm" | cpio -idm -D "$workdir" --quiet 2>/dev/null || true
    done
}

create_extension_file() {
    local workdir="$1"
    local package="$2"
    local version="$3"
    local host_version="$4"
    mkdir -p "$workdir/usr/lib/extension-release.d"
    local release_file="$workdir/usr/lib/extension-release.d/extension-release.${package}-${version}"
    cat > "$release_file" << EOF
ID=fedora
VERSION_ID=$host_version
EOF
}

handle_etc_files() {
    local workdir="$1"
    local package="$2"
    local mode="$3"

    [[ ! -d "$workdir/etc" ]] && return 0

    # 🆕 Tichý mód: Pokud jde o update, /etc přeskočíme, aby to nechtělo heslo!
    if [[ "$mode" == "update" ]]; then
        info "Update mode: Skipping /etc configuration to prevent sudo prompts..."
        rm -rf "$workdir/etc"
        return 0
    fi

    if is_special_package "$package"; then
        info "Skipping config for special package: $package"
        rm -rf "$workdir/etc"
        return 0
    fi

    info "Copying /etc configuration to host... (May ask for sudo password)"
    tar -czf "$workdir/etc-config.tar.gz" -C "$workdir/etc" . || die "Failed to archive /etc"
    distrobox-host-exec sudo tar -xzf "$workdir/etc-config.tar.gz" -C /etc/ --skip-old-files || true

    # Zápis do logu
    mkdir -p "$STATE_DIR"
    echo "######## $package ########" >> "$TRACKER_FILE"
    find "$workdir/etc" -type f | sed "s|$workdir||" >> "$TRACKER_FILE"
    info "Configuration files tracked in $TRACKER_FILE"

    rm -rf "$workdir/etc"
}

create_squashfs() {
    local workdir="$1"
    local package="$2"
    local version="$3"
    # 🆕 Obraz se vytváří přímo ve $WORKDIR, aby si ho skript nesmazal!
    local output_raw="$WORKDIR/${package}-${version}.raw"

    info "Creating SquashFS image with zstd compression..."
    mksquashfs "$workdir" "$output_raw" -all-root -noappend -comp zstd -Xcompression-level "$COMPRESSION_LEVEL" -b "$BLOCK_SIZE" > /dev/null || \
        die "Failed to create SquashFS image"
    echo "$output_raw"
}

delete_old_images() {
    local package="$1"
    info "Removing old images for $package..."
    # 🆕 Univerzální smazání všech starých verzí pro tento balíček
    if is_special_package "$package"; then
        distrobox-host-exec rm -f "$EXT_DIR"/${package}-*.raw 2>/dev/null || true
    else
        distrobox-host-exec rm -f "$EXT_DIR"/${package}-[0-9]*.raw 2>/dev/null || true
    fi
}

install_image() {
    local raw_file="$1"
    info "Installing new image..."
    # Skupina sysext-admins umožňuje mv bez sudo!
    distrobox-host-exec mv "$raw_file" "$EXT_DIR/" || die "Failed to move image to $EXT_DIR"
    info "Refreshing system extensions..."
    # 🆕 Absolutní cesta k systemd-sysext pro funkční Sudoers!
    distrobox-host-exec sudo /usr/bin/systemd-sysext refresh || die "Failed to refresh sysext"
}

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

cmd_install() {
    local package="$1"
    local host_version="$2"
    local mode="${3:-install}"

    check_blacklist "$package"

    local installed_version available_version
    installed_version=$(get_installed_version "$package" "$host_version")
    available_version=$(get_available_version "$package")

    status "Package: $package"
    status "Available: ${available_version:-unknown}"
    status "Installed: ${installed_version:-not installed}"

    if [[ "$installed_version" == "$available_version" && -n "$installed_version" ]]; then
        status "$package is already up to date"
        return 0
    fi

    WORKDIR=$(mktemp -d) || die "Failed to create temp directory"
    mkdir -p "$WORKDIR/rpms"

    info "Querying HOST system for package dependencies..."
    local packages
    packages=$(get_host_packages "$package")

    download_packages "$packages" "$WORKDIR"
    extract_rpms "$WORKDIR"
    rm -rf "$WORKDIR/rpms"

    create_extension_file "$WORKDIR" "$package" "$available_version" "$host_version"

    # Předání módu (install/update) pro zpracování /etc
    handle_etc_files "$WORKDIR" "$package" "$mode"

    local raw_file
    raw_file=$(create_squashfs "$WORKDIR" "$package" "$available_version")

    # Smažeme staré verze napříč všemi Fedorami
    delete_old_images "$package"

    install_image "$raw_file"
    success "$package installed successfully"
    cleanup_workdir
}

cmd_update() {
    local host_version="$1"
    info "Finding installed packages..."
    # Inteligentní extrakce jmen všech instalovaných balíčků
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} .raw | sed -E 's/-[0-9].*//' | sort -u | tr '\n' ' ') || true

    [[ -z "$packages" ]] && { info "No installed packages found"; return 0; }

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        # 🆕 Zavolá instalaci v tichém UPDATE módu
        cmd_install "$pkg" "$host_version" "update" || true
    done
    success "Update completed"
}

cmd_remove() {
    local package="$1"
    info "Removing $package..."
    delete_old_images "$package"

    warn "Configuration files in /etc may remain:"
    # 1. Vypsání souborů (sort -u zajistí, že i kdyby tam byly duplikáty, vypíšou se jen jednou)
    sed -n "/######## $package ########/,/########/p" "$TRACKER_FILE" 2>/dev/null | grep -v "########" | sort -u || true

    # 2. Úklid Trackeru (Smaže blok pro tuto aplikaci ze souboru, aby nerostl)
    if [[ -f "$TRACKER_FILE" ]]; then
        awk -v p="######## $package ########" '$0 == p { skip=1; next } skip && /^######## / { skip=0 } !skip { print }' "$TRACKER_FILE" > "${TRACKER_FILE}.tmp" && mv "${TRACKER_FILE}.tmp" "$TRACKER_FILE"
    fi

    info "Refreshing system extensions..."
    distrobox-host-exec sudo /usr/bin/systemd-sysext refresh || die "Failed to refresh sysext"
    success "$package removed successfully"
}

cmd_list() {
    info "Seznam nainstalovaných sysext aplikací:"
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} 2>/dev/null | sort) || true

    if [[ -z "$packages" ]]; then
        status "Žádné aplikace nejsou aktuálně nainstalovány."
    else
        echo "$packages" | sed 's/^/ 📦 /'
    fi
}

# ============================================================================
# USAGE & MAIN
# ============================================================================

show_usage() {
    cat << EOF
Usage: $0 <command> [package_name]

Commands:
  install <package>   Install or update a specific package
  update              Update all installed packages (silent mode)
  rm <package>        Remove a package
  list                List all installed sysext packages

Examples:
  $0 install htop
  $0 update
  $0 rm htop
  $0 list
EOF
}

main() {
    [[ $# -lt 1 ]] && { show_usage; exit 1; }

    local host_version
    host_version=$(validate_environment)

    case "$1" in
        install)
            [[ -z "${2:-}" ]] && die "Package name required"
            cmd_install "$2" "$host_version" "install"
            ;;
        update)
            cmd_update "$host_version"
            ;;
        rm)
            [[ -z "${2:-}" ]] && die "Package name required"
            cmd_remove "$2"
            ;;
        list)
            cmd_list
            ;;
        *)
            die "Unknown command: $1"
            ;;
    esac
}

main "$@"
=======
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
