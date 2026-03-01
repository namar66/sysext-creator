#!/bin/bash

################################################################################
# Sysext-Creator (Refactored Version)
# Copyright (C) 2026 Martin Naď (namar66)
# License: GNU General Public License v2
################################################################################

set -euo pipefail

# ============================================================================
# CONSTANTS
# ============================================================================

readonly EXT_DIR="/var/lib/extensions"
readonly TRACKER_FILE="${EXT_DIR}/etc_tracker.txt"
readonly REQUIRED_CMDS=("mksquashfs" "cpio" "rpm2cpio" "repoquery")
readonly COMPRESSION_LEVEL=19
readonly BLOCK_SIZE=1048576
readonly SPECIAL_PACKAGES=("vivaldi-stable")

# Global variable for cleanup
WORKDIR=""

# ============================================================================
# LOGGING FUNCTIONS (output to stderr to avoid capturing in command substitution)
# ============================================================================

die() {
    local exit_code=${2:-1}
    echo "❌ Error: $1" >&2
    cleanup_workdir
    exit "$exit_code"
}

info() {
    echo "=> $1" >&2
}

status() {
    echo "📋 $1" >&2
}

success() {
    echo "✅ $1" >&2
}

warn() {
    echo "⚠️  $1" >&2
}

# Cleanup function for workdir
cleanup_workdir() {
    if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
        rm -rf "$WORKDIR"
    fi
}

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

validate_environment() {
    # Check required commands
    for cmd in "${REQUIRED_CMDS[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            die "Missing required command: $cmd\nInstall with: sudo dnf install -y squashfs-tools cpio dnf-utils"
        fi
    done
    
    # Check mounted directory
    if ! mountpoint -q "$EXT_DIR"; then
        die "Extensions directory not mounted: $EXT_DIR\nMount with: --volume $EXT_DIR:$EXT_DIR:rw"
    fi
    
    # Check OS versions match
    local host_version guest_version
    host_version=$(distrobox-host-exec grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
    guest_version=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
    
    if [[ "$host_version" != "$guest_version" ]]; then
        die "OS version mismatch: Host ($host_version) != Guest ($guest_version)"
    fi
    
    echo "$host_version"
}

# Determine privilege escalation for file operations (move, delete)
get_file_privilege_prefix() {
    if distrobox-host-exec test -w "$EXT_DIR"; then
        echo ""
    else
        echo "sudo "
    fi
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
    local pattern
    pattern=$(get_raw_pattern "$package" "$host_version")
    
    local raw_file
    raw_file=$(find "$EXT_DIR" -name "$pattern" 2>/dev/null | head -1) || true
    
    if [[ -z "$raw_file" ]]; then
        echo ""
    else
        extract_version "$raw_file" "$package"
    fi
}

get_available_version() {
    local package="$1"
    dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" "$package" 2>/dev/null || echo ""
}

# ============================================================================
# DEPENDENCY & DOWNLOAD FUNCTIONS (HOST -> GUEST)
# ============================================================================

# CRITICAL: Get dependencies from HOST using rpm-ostree
# This ensures correct dependencies for the host system
# NOTE: This function outputs ONLY the package list to stdout
get_host_packages() {
    local package="$1"
    
    local raw_output
    raw_output=$(distrobox-host-exec rpm-ostree install --dry-run "$package" 2>/dev/null)
    
    # Extract package names from HOST's dependency list - EXACT same logic as original script
    echo "$raw_output" | sed -n '/packages:/,$p' | \
        grep -E '^  [a-zA-Z0-9]' | \
        awk '{print $1}' | \
        sed -E 's/-[0-9].*//' | \
        tr '\n' ' '
}

# Download packages from GUEST repos
download_packages() {
    local packages="$1"
    local workdir="$2"
    
    info "Downloading packages from guest environment..."
    
    # Verify we have packages to download
    if [[ -z "$packages" || "$packages" == " " ]]; then
        die "No packages to download - dependency resolution failed"
    fi
    
    dnf download $packages --refresh --forcearch=x86_64 --destdir="$workdir/rpms" 2>/dev/null || \
        die "Failed to download packages for: $packages"
    
    local rpm_count
    rpm_count=$(ls -1 "$workdir/rpms"/*.rpm 2>/dev/null | wc -l) || true
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
    
    local release_file="$workdir/usr/lib/extension-release.d/extension-release.${package}-${version}"
    cat > "$release_file" << EOF
ID=fedora
VERSION_ID=$host_version
EOF
}

handle_etc_files() {
    local workdir="$1"
    local package="$2"
    local action="$3"
    
    [[ ! -d "$workdir/etc" ]] && return 0
    [[ "$action" != "install" ]] && { rm -rf "$workdir/etc"; return 0; }
    
    if is_special_package "$package"; then
        info "Skipping config for special package: $package"
        rm -rf "$workdir/etc"
        return 0
    fi
    
    info "Copying /etc configuration to host..."
    tar -czf "$workdir/etc-config.tar.gz" -C "$workdir/etc" . || die "Failed to archive /etc"
    distrobox-host-exec sudo tar -xzf "$workdir/etc-config.tar.gz" -C /etc/ --skip-old-files || true
    
    echo "######## $package ########" >> "$TRACKER_FILE"
    find "$workdir/etc" -type f | sed "s|$workdir||" >> "$TRACKER_FILE"
    
    info "Configuration files tracked in $TRACKER_FILE"
    rm -rf "$workdir/etc"
}

create_squashfs() {
    local workdir="$1"
    local package="$2"
    local version="$3"
    
    local output_raw="${package}-${version}.raw"
    
    info "Creating SquashFS image with zstd compression..."
    mksquashfs "$workdir" "$output_raw" \
        -all-root -noappend -comp zstd \
        -Xcompression-level "$COMPRESSION_LEVEL" \
        -b "$BLOCK_SIZE" > /dev/null || \
        die "Failed to create SquashFS image"
    
    # Output ONLY the filename to stdout (no newlines, no info messages)
    echo "$output_raw"
}

delete_old_images() {
    local package="$1"
    local host_version="$2"
    local file_privilege_prefix="$3"
    
    local pattern
    pattern=$(get_raw_pattern "$package" "$host_version")
    
    info "Removing old images..."
    distrobox-host-exec ${file_privilege_prefix}rm -f "$EXT_DIR"/$pattern
}

install_image() {
    local raw_file="$1"
    local file_privilege_prefix="$2"
    
    info "Installing new image..."
    distrobox-host-exec ${file_privilege_prefix}mv "$raw_file" "$EXT_DIR/" || die "Failed to move image to $EXT_DIR"
    
    info "Refreshing system extensions..."
    distrobox-host-exec sudo systemd-sysext refresh || die "Failed to refresh sysext"
}

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

cmd_install() {
    local package="$1"
    local host_version="$2"
    local file_privilege_prefix="$3"
    
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
    
    mkdir -p "$WORKDIR/usr/lib/extension-release.d" "$WORKDIR/rpms"
    
    # Get packages from HOST, download from GUEST
    info "Querying HOST system for package dependencies..."
    local packages
    packages=$(get_host_packages "$package")
    
    download_packages "$packages" "$WORKDIR"
    
    extract_rpms "$WORKDIR"
    rm -rf "$WORKDIR/rpms"
    
    create_extension_file "$WORKDIR" "$package" "$available_version" "$host_version"
    handle_etc_files "$WORKDIR" "$package" "install"
    
    local raw_file
    raw_file=$(create_squashfs "$WORKDIR" "$package" "$available_version")
    
    # Replace old images
    if [[ -n "$(find "$EXT_DIR" -name "$(get_raw_pattern "$package" "$host_version")" 2>/dev/null)" ]]; then
        distrobox-host-exec sudo systemd-sysext unmerge || true
        delete_old_images "$package" "$host_version" "$file_privilege_prefix"
    fi
    
    install_image "$raw_file" "$file_privilege_prefix"
    success "$package installed successfully"
    
    cleanup_workdir
}

cmd_update() {
    local host_version="$1"
    local file_privilege_prefix="$2"
    
    info "Finding installed packages..."
    
    local packages
    packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | \
        xargs -I {} basename {} .raw | sed 's/-[^-]*$//' | sort -u | tr '\n' ' ') || true
    
    [[ -z "$packages" ]] && { info "No installed packages found"; return 0; }
    
    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        cmd_install "$pkg" "$host_version" "$file_privilege_prefix" || true
    done
    
    success "Update completed"
}

cmd_remove() {
    local package="$1"
    local host_version="$2"
    local file_privilege_prefix="$3"
    
    info "Removing $package..."
    delete_old_images "$package" "$host_version" "$file_privilege_prefix"
    
    warn "Configuration files in /etc may remain:"
    sed -n "/######## $package ########/,/########/p" "$TRACKER_FILE" 2>/dev/null | grep -v "########" || true
    
    info "Refreshing system extensions..."
    distrobox-host-exec sudo systemd-sysext refresh || die "Failed to refresh sysext"
    
    success "$package removed successfully"
}

# ============================================================================
# USAGE & MAIN
# ============================================================================

show_usage() {
    cat << EOF
Usage: $0 <command> [package_name]

Commands:
  install <package>   Install or update a specific package
  update              Update all installed packages
  rm <package>        Remove a package

Examples:
  $0 install htop
  $0 update
  $0 rm htop
EOF
}

main() {
    [[ $# -lt 1 ]] && { show_usage; exit 1; }
    
    local host_version file_privilege_prefix
    host_version=$(validate_environment)
    file_privilege_prefix=$(get_file_privilege_prefix)
    
    case "$1" in
        install)
            [[ -z "${2:-}" ]] && die "Package name required"
            cmd_install "$2" "$host_version" "$file_privilege_prefix"
            ;;
        update)
            cmd_update "$host_version" "$file_privilege_prefix"
            ;;
        rm)
            [[ -z "${2:-}" ]] && die "Package name required"
            cmd_remove "$2" "$host_version" "$file_privilege_prefix"
            ;;
        *)
            die "Unknown command: $1"
            ;;
    esac
}

main "$@"
