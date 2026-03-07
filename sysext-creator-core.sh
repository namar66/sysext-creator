#!/bin/bash

################################################################################
# Sysext-Creator (Refactored Version v1.1.3 - The "Event-Driven" Edition)
# Copyright (C) 2026 Martin Naď (namar66)
# License: GNU General Public License v2
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
# LOGGING FUNCTIONS
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
            die "Missing required command: $cmd\nInstall with: sudo dnf install -y erofs-utils cpio dnf-utils"
        fi
    done

    if ! distrobox-host-exec test -w "$STAGING_DIR"; then
        die "Missing write permissions to $STAGING_DIR.\nPlease ensure the daemon is running properly."
    fi

    local host_version guest_version
    host_version=$(distrobox-host-exec grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')
    guest_version=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')

    if [[ "$host_version" != "$guest_version" ]]; then
        distrobox-host-exec notify-send -u critical -i dialog-warning "Sysext-Creator" "Fedora upgrade detected! Please run: sysext-creator upgrade-box" || true
        die "OS version mismatch: Host ($host_version) != Guest ($guest_version)\nPlease run: sysext-creator upgrade-box"
    fi

    echo "$host_version"
}

check_blacklist() {
    local package="$1"
    for bad_pkg in "${BLACKLIST[@]}"; do
        if [[ "$package" == "$bad_pkg" ]]; then
            die "Installation of package '$package' is blocked for security reasons!"
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

get_installed_version() {
    local package="$1"
    local req_file="$STAGING_DIR/${package}.version-req"
    local res_file="$STAGING_DIR/${package}.version-res"

    if ! distrobox-host-exec test -f "$EXT_DIR/${package}.raw"; then
        echo ""
        return 0
    fi

    distrobox-host-exec sh -c "echo 'req' > \"$req_file\""

    local timeout=20
    while ! distrobox-host-exec test -f "$res_file"; do
        sleep 0.5
        timeout=$((timeout - 1))
        if [[ $timeout -le 0 ]]; then
            echo ""
            return 0
        fi
    done

    local version
    version=$(distrobox-host-exec cat "$res_file" 2>/dev/null | tr -d '\r\n')

    distrobox-host-exec rm -f "$res_file"

    echo "$version"
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
    # 🆕 Fixed to support both "packages:" and "Added:" from newer rpm-ostree
    echo "$raw_output" | sed -n -e '/packages:/,$p' -e '/^Added:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | sort -u | tr '\n' ' '
}

download_packages() {
    local packages="$1"
    local workdir="$2"
    info "Downloading packages from guest environment..."
    if [[ -z "$packages" || "$packages" == " " ]]; then
        die "No packages to download - dependency resolution failed"
    fi

    dnf download $packages --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$workdir/rpms" 2>/dev/null || \
        die "Failed to download packages for: $packages"

    local rpm_count=$(ls -1 "$workdir/rpms"/*.rpm 2>/dev/null | wc -l) || true
    [[ $rpm_count -eq 0 ]] && die "No packages downloaded."
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

    local release_file="$workdir/usr/lib/extension-release.d/extension-release.${package}"

    cat > "$release_file" << EOF
ID=fedora
VERSION_ID=$host_version
SYSEXT_VERSION_ID=$version
EOF
}

handle_etc_files() {
    local workdir="$1"
    local package="$2"
    local mode="$3"

    [[ ! -d "$workdir/etc" ]] && return 0

    if [[ "$mode" == "update" ]]; then
        info "Update mode: Skipping /etc configuration..."
        rm -rf "$workdir/etc"
        return 0
    fi

    if is_special_package "$package"; then
        info "Skipping config for special package: $package"
        rm -rf "$workdir/etc"
        return 0
    fi

    info "Dispatching /etc configuration to the staging area..."
    tar -czf "$workdir/${package}.etc.tar.gz" -C "$workdir/etc" . || die "Failed to archive /etc"

    distrobox-host-exec mv "$workdir/${package}.etc.tar.gz" "$STAGING_DIR/" || die "Failed to move config to staging"

    mkdir -p "$STATE_DIR"
    echo "######## $package ########" >> "$TRACKER_FILE"
    find "$workdir/etc" -type f | sed "s|$workdir||" >> "$TRACKER_FILE"
    info "Configuration files tracked in $TRACKER_FILE"

    rm -rf "$workdir/etc"
}

create_erofs() {
    local workdir="$1"
    local package="$2"

    local output_raw="$WORKDIR/${package}.raw"

    info "Creating EROFS image with lz4hc compression..."
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 "$output_raw" "$workdir" > /dev/null || \
        die "Failed to create EROFS image"
    echo "$output_raw"
}

delete_old_images() {
    local package="$1"
    info "Dispatching image removal request to the staging area ($STAGING_DIR)..."
    distrobox-host-exec sh -c "echo 'delete' > \"$STAGING_DIR/${package}.delete\"" || true
}

install_image() {
    local raw_file="$1"
    info "Dispatching image to the staging area ($STAGING_DIR)..."
    distrobox-host-exec mv "$raw_file" "$STAGING_DIR/" || die "Failed to move image to $STAGING_DIR"
    info "Done! The host daemon will now handle the deployment and systemd-sysext refresh."
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
    installed_version=$(get_installed_version "$package")
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

    # 🆕 Fallback if dependency detection is empty
    if [[ -z "$packages" || "$packages" == " " ]]; then
        warn "Dependency detection empty, falling back to base package."
        packages="$package"
    fi

    download_packages "$packages" "$WORKDIR"
    extract_rpms "$WORKDIR"
    rm -rf "$WORKDIR/rpms"

    create_extension_file "$WORKDIR" "$package" "$available_version" "$host_version"
    handle_etc_files "$WORKDIR" "$package" "$mode"

    local raw_file
    raw_file=$(create_erofs "$WORKDIR" "$package")

    install_image "$raw_file"

    success "$package successfully dispatched to staging daemon"
    cleanup_workdir
}

cmd_update() {
    local host_version="$1"
    info "Finding installed packages..."
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} .raw | sort -u | tr '\n' ' ') || true

    [[ -z "$packages" ]] && { info "No installed packages found"; return 0; }

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        sleep 0.5
        cmd_install "$pkg" "$host_version" "update" || true
    done
    success "Update loop completed"
}

cmd_remove() {
    local package="$1"

    local is_installed=0
    if distrobox-host-exec test -f "$EXT_DIR/${package}.raw"; then
        is_installed=1
    fi
    if [[ -f "$TRACKER_FILE" ]] && grep -q "^######## $package ########$" "$TRACKER_FILE"; then
        is_installed=1
    fi

    if [[ $is_installed -eq 0 ]]; then
        warn "Package '$package' was not found (not installed)."
        return 0
    fi

    info "Removing $package..."

    local config_files=""
    if [[ -f "$TRACKER_FILE" ]]; then
        config_files=$(sed -n "/^######## $package ########$/,/^######## /p" "$TRACKER_FILE" | grep -v "^########" || true)
    fi

    local files_to_remove=()

    if [[ -n "$config_files" ]]; then
        echo -e "\n⚠️ Configuration files found in /etc for package $package:"
        echo "$config_files" | sed 's/^/  /'
        echo ""
        read -p "Do you want to delete these files? [A]ll / [S]elect / [N]one [N]: " choice
        choice=${choice:-N}

        case "${choice^^}" in
            A)
                while read -r line; do
                    [[ -n "$line" ]] && files_to_remove+=("$line")
                done <<< "$config_files"
                ;;
            S)
                while read -r line; do
                    [[ -z "$line" ]] && continue
                    read -p " Delete $line? [y/N]: " del_choice < /dev/tty
                    del_choice=${del_choice:-N}
                    if [[ "${del_choice^^}" == "Y" ]]; then
                        files_to_remove+=("$line")
                    fi
                done <<< "$config_files"
                ;;
            *)
                info "Keeping configuration files on disk."
                ;;
        esac
    fi

    WORKDIR=$(mktemp -d) || die "Failed to create temp directory"

    if [[ ${#files_to_remove[@]} -gt 0 ]]; then
        local removal_file="$WORKDIR/${package}.etc.remove"
        for f in "${files_to_remove[@]}"; do
            echo "$f" >> "$removal_file"
        done
        distrobox-host-exec mv "$removal_file" "$STAGING_DIR/"
        info "Configuration removal request dispatched to daemon."
    fi

    if [[ -f "$TRACKER_FILE" ]]; then
        awk -v p="######## $package ########" '$0 == p { skip=1; next } skip && /^######## / { skip=0 } !skip { print }' "$TRACKER_FILE" > "${TRACKER_FILE}.tmp" && mv "${TRACKER_FILE}.tmp" "$TRACKER_FILE"
    fi

    delete_old_images "$package"

    info "Done! The host daemon will now handle the removal and systemd-sysext refresh."
    success "$package dispatched for removal"
    cleanup_workdir
}

cmd_list() {
    info "List of installed sysext packages:"
    local packages=$(distrobox-host-exec find "$EXT_DIR" -maxdepth 1 -name "*.raw" -type f 2>/dev/null | xargs -I {} basename {} .raw | sort | tr -d '\r') || true

    if [[ -z "$packages" ]]; then
        status "No packages are currently installed."
        return 0
    fi

    for pkg in $packages; do
        [[ -n "$pkg" ]] && distrobox-host-exec sh -c "echo 'req' > \"$STAGING_DIR/${pkg}.version-req\""
    done

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue

        local res_file="$STAGING_DIR/${pkg}.version-res"
        local timeout=30
        local version=""

        while ! distrobox-host-exec test -f "$res_file"; do
            sleep 0.5
            timeout=$((timeout - 1))
            if [[ $timeout -le 0 ]]; then
                break
            fi
        done

        if distrobox-host-exec test -f "$res_file"; then
            version=$(distrobox-host-exec cat "$res_file" 2>/dev/null | tr -d '\r\n')
            distrobox-host-exec rm -f "$res_file"
        fi

        if [[ -n "$version" ]]; then
            echo " 📦 $pkg (Version: $version)"
        else
            echo " 📦 $pkg (Version: unknown)"
        fi
    done
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
  upgrade-box         Rebuild sysext container after an OS upgrade

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
