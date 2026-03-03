#!/bin/bash

################################################################################
# Sysext-Creator (Version v1.1 - Stable "Raw" Edition)
# Copyright (C) 2026 Martin Naď (namar66)
# License: GNU General Public License v2
################################################################################

readonly SYSEXT_CREATOR_VERSION="1.1"

set -euo pipefail

# ============================================================================
# CONSTANTS
# ============================================================================

readonly EXT_DIR="/var/lib/extensions"
readonly STATE_DIR="$HOME/.local/state/sysext-creator"
readonly TRACKER_FILE="${STATE_DIR}/etc_tracker.txt"

readonly REQUIRED_CMDS=("mkfs.erofs" "cpio" "rpm2cpio" "repoquery")
readonly SPECIAL_PACKAGES=("vivaldi-stable")
readonly BLACKLIST=("glibc" "systemd" "dnf" "microdnf" "rpm-ostree" "pam" "kernel" "grub2" "dracut" "passwd" "shadow-utils" "sudo" "tar")

WORKDIR=""

# ============================================================================
# LOGGING & CLEANUP
# ============================================================================

die() {
    echo -e "❌ Error: $1" >&2
    cleanup_workdir
    exit "${2:-1}"
}

info() { echo "=> $1" >&2; }
status() { echo "📋 $1" >&2; }
success() { echo "✅ $1" >&2; }
warn() { echo "⚠️  $1" >&2; }

cleanup_workdir() {
    [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR"
}

# ============================================================================
# VERSION TRACKING (The Bugfix Core)
# ============================================================================

get_available_version() {
    local package="$1"
    # Added arch filtering and tail to ensure a single, clean version string
    local ver
    ver=$(dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" --forcearch=x86_64 "$package" 2>/dev/null | tail -n 1 | tr -d '\r\n')
    echo "$ver"
}

extract_version() {
    local raw_file="$1"
    local package="$2"
    # Anchored regex to prevent substring matching bugs
    basename "$raw_file" | sed "s|^${package}-||" | sed 's|\.raw$||'
}

get_installed_version() {
    local package="$1"
    local host_version="$2"

    # Check for both standard and special naming patterns
    local pattern="${package}-*.fc${host_version}.raw"
    [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]] && pattern="${package}-*.raw"

    local raw_file
    raw_file=$(find "$EXT_DIR" -maxdepth 1 -name "$pattern" 2>/dev/null | head -1) || true

    if [[ -z "$raw_file" ]]; then
        echo ""
    else
        extract_version "$raw_file" "$package"
    fi
}

# ============================================================================
# ENVIRONMENT VALIDATION
# ============================================================================

validate_environment() {
    for cmd in "${REQUIRED_CMDS[@]}"; do
        command -v "$cmd" &>/dev/null || die "Missing: $cmd. Run: sudo dnf install -y erofs-utils cpio dnf-utils"
    done

    [[ -w "$EXT_DIR" ]] || die "No write access to $EXT_DIR. Run setup.sh first."

    local host_ver guest_ver
    host_ver=$(distrobox-host-exec grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')
    guest_ver=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')

    if [[ "$host_ver" != "$guest_ver" ]]; then
        distrobox-host-exec notify-send -u critical "Sysext-Creator" "Upgrade detected! Run: sysext-creator upgrade-box" || true
        die "OS mismatch: Host($host_ver) != Guest($guest_ver). Run: sysext-creator upgrade-box"
    fi
    echo "$host_ver"
}

# ============================================================================
# CORE LOGIC
# ============================================================================

handle_etc_files() {
    local build_dir="$1" package="$2" mode="$3"
    [[ ! -d "$build_dir/etc" ]] && return 0
    [[ "$mode" == "update" ]] || [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]] && { rm -rf "$build_dir/etc"; return 0; }

    info "Copying /etc to host (requires sudo)..."
    local cache_dir="$HOME/.cache/sysext-creator"
    mkdir -p "$cache_dir"
    local tarball="$cache_dir/tmp_etc_${package}.tar.gz"

    tar -czf "$tarball" -C "$build_dir/etc" .
    distrobox-host-exec sudo tar -xzf "$tarball" -C /etc/ --skip-old-files || true
    rm -f "$tarball"

    echo "######## $package ########" >> "$TRACKER_FILE"
    find "$build_dir/etc" -type f | sed "s|$build_dir||" >> "$TRACKER_FILE"
    rm -rf "$build_dir/etc"
}

cmd_install() {
    local package="$1"
    local host_version="$2"
    local mode="${3:-install}"

    # 🛡️ SAFEGUARD: Block manipulation of sysext-creator itself
    # This tool is managed via build-bundle.sh or self-upgrade (v1.2+)
    if [[ "$package" == "sysext-creator" ]]; then
        warn "Direct installation or update of 'sysext-creator' is blocked."
        echo "Please use './build-bundle.sh' for manual builds."
        return 1
    fi

    # Check against security blacklist
    for b in "${BLACKLIST[@]}"; do
        [[ "$package" == "$b" ]] && die "Package $package is blacklisted for security reasons."
    done

    # Fetch version information
    local installed_ver available_ver
    installed_ver=$(get_installed_version "$package" "$host_version")
    available_ver=$(get_available_version "$package")

    # Handle DNF availability/network issues
    if [[ -z "$available_ver" ]]; then
        warn "Could not fetch version for $package from repositories."
        if [[ -n "$installed_ver" ]]; then
            status "Internet connection issue? Keeping currently installed: $installed_ver"
            return 0
        fi
        die "Package $package not found. Check your internet connection or package name."
    fi

    status "Package: $package"
    status "Installed: ${installed_ver:-None}"
    status "Available: $available_ver"

    # Up-to-date check
    if [[ "$installed_ver" == "$available_ver" ]]; then
        success "$package is already up to date ($installed_ver)."
        return 0
    fi

    # 🏗️ Build process starts here
    WORKDIR=$(mktemp -d)
    local build_dir="$WORKDIR/build_root"
    mkdir -p "$build_dir" "$WORKDIR/rpms"

    # Resolve dependencies by asking the host system
    info "Resolving host dependencies via rpm-ostree..."
    local pkgs
    pkgs=$(distrobox-host-exec rpm-ostree install --dry-run "$package" 2>/dev/null | \
           sed -n '/packages:/,$p' | grep -E '^  [a-zA-Z0-9]' | \
           awk '{print $1}' | sed -E 's/-[0-9].*//' | tr '\n' ' ')

    info "Downloading and extracting packages..."
    dnf download $pkgs --refresh --destdir="$WORKDIR/rpms" >/dev/null
    for rpm in "$WORKDIR/rpms"/*.rpm; do
        rpm2cpio "$rpm" | cpio -idm -D "$build_dir" --quiet 2>/dev/null
    done

    # 🏷️ SMART NAMING: Fix the double .fcXX extension bug
    local img_name="${package}-${available_ver}"
    if [[ ! " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]]; then
        # Only append .fcXX if it's not already part of the DNF version string
        if [[ ! "$img_name" == *".fc${host_version}"* ]]; then
            img_name="${img_name}.fc${host_version}"
        fi
    fi

    # Create systemd-sysext metadata
    mkdir -p "$build_dir/usr/lib/extension-release.d"
    echo -e "ID=fedora\nVERSION_ID=$host_version" > "$build_dir/usr/lib/extension-release.d/extension-release.${img_name}"

    # Handle /etc configuration files
    handle_etc_files "$build_dir" "$package" "$mode"

    # Bake the high-performance EROFS image
    info "Baking EROFS image..."
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$WORKDIR/${img_name}.raw" "$build_dir" >/dev/null

    # 📦 Finalizing Installation
    info "Installing new image to $EXT_DIR..."

    # Remove all older versions of this specific package to avoid conflicts
    rm -f "$EXT_DIR/${package}-"*.raw

    # Move the new image into place
    cp "$WORKDIR/${img_name}.raw" "$EXT_DIR/"

    # Refresh system extensions on the host
    info "Restarting systemd-sysext service..."
    distrobox-host-exec sudo /usr/bin/systemctl restart systemd-sysext.service

    success "Successfully installed $package ($available_ver)."
    cleanup_workdir
}

# ============================================================================
# OTHER COMMANDS
# ============================================================================

cmd_update() {
    local host_ver="$1"
    info "Checking for updates for installed extensions..."

    # 🆕 Opravený regex: s/-(v?[0-9]).*//  (zvládne htop-3.0 i sysext-creator-v1.1)
    local pkgs
    pkgs=$(find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f | xargs -I {} basename {} .raw | sed -E 's/-(v?[0-9]).*//' | sort -u)

    local count=0
    for p in $pkgs; do
        [[ -z "$p" ]] && continue

        # 🛡️ Pojistka s hvězdičkou pro větší bezpečnost
        if [[ "$p" == sysext-creator* ]]; then
            info "Skipping sysext-creator (self-upgrade handled separately)."
            continue
        fi

        cmd_install "$p" "$host_ver" "update"
        count=$((count + 1))
    done

    if [[ $count -eq 0 ]]; then
        status "No external packages found to update."
    else
        success "Update process finished for $count packages."
    fi
}

cmd_remove() {
    local pkg="$1"

    # 🛡️ BEZPEČNOSTNÍ POJISTKA: Okamžité ukončení při pokusu o smazání sebe sama
    if [[ "$pkg" == "sysext-creator" ]]; then
        warn "Self-removal via command is blocked."
        echo "Please manually remove the .raw file from $EXT_DIR if you wish to uninstall."
        return 1  # ⬅️ KLÍČOVÁ ZMĚNA: Funkce skončí tady a nepokračuje dál
    fi

    info "Removing $pkg..."

    # Skutečné smazání souborů
    rm -f "$EXT_DIR/${pkg}-"*.raw

    # Úklid trackeru
    if [[ -f "$TRACKER_FILE" ]]; then
        awk -v p="######## $pkg ########" '$0 == p { skip=1; next } skip && /^######## / { skip=0 } !skip { print }' "$TRACKER_FILE" > "${TRACKER_FILE}.tmp" && mv "${TRACKER_FILE}.tmp" "$TRACKER_FILE"
    fi

    distrobox-host-exec sudo /usr/bin/systemctl restart systemd-sysext.service
    success "$pkg removed successfully."
}

cmd_list() {
    local pkgs=$(find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f | xargs -I {} basename {} | sort)
    [[ -z "$pkgs" ]] && { status "No packages installed."; return 0; }
    echo "$pkgs" | sed 's/^/ 📦 /'
}

main() {
    [[ $# -lt 1 ]] && { echo "Usage: sysext-creator install|update|rm|list [package]"; exit 1; }
    local host_ver=$(validate_environment)
    case "$1" in
        install) [[ -z "${2:-}" ]] && die "Package name required"; cmd_install "$2" "$host_ver" ;;
        update)  cmd_update "$host_ver" ;;
        rm)      [[ -z "${2:-}" ]] && die "Package name required"; cmd_remove "$2" ;;
        list)    cmd_list ;;
        *)       die "Unknown command: $1" ;;
    esac
}

main "$@"
