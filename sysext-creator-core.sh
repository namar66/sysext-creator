#!/bin/bash

################################################################################
# Sysext-Creator-Core (v2.0.1 - Pure Podman Edition)
# Runs exclusively inside the persistent podman container.
################################################################################

set -euo pipefail

readonly EXT_DIR="/var/lib/extensions"
readonly STAGING_DIR="/var/tmp/sysext-staging"

readonly REQUIRED_CMDS=("mkfs.erofs" "cpio" "rpm2cpio" "repoquery")
readonly SPECIAL_PACKAGES=("sysext-creator")
readonly BLACKLIST=("glibc" "systemd" "dnf" "microdnf" "rpm-ostree" "pam" "kernel" "grub2" "dracut" "passwd" "shadow-utils" "sudo" "tar")

WORKDIR=""

die() { echo -e "❌ Error: $1" >&2; cleanup_workdir; exit "${2:-1}"; }
info() { echo "=> $1" >&2; }
status() { echo "📋 $1" >&2; }
success() { echo "✅ $1" >&2; }
warn() { echo "⚠️  $1" >&2; }

cleanup_workdir() { [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR"; }

validate_environment() {
    for cmd in "${REQUIRED_CMDS[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            die "Missing required command: $cmd\nInstall with: dnf install -y erofs-utils cpio dnf-utils"
        fi
    done

    if [[ ! -w "$STAGING_DIR" ]]; then
        die "Missing write permissions to $STAGING_DIR. Ensure the host daemon is active."
    fi

    local host_version=$(grep VERSION_ID= /run/host/etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')
    local guest_version=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '\r\n"')

    if [[ "$host_version" != "$guest_version" ]]; then
        warn "OS upgrade detected! Run: sysext-creator upgrade-box"
        die "OS mismatch: Host ($host_version) != Container ($guest_version)."
    fi
    echo "$host_version"
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

get_available_version() { dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" "$1" 2>/dev/null || echo ""; }

cmd_install() {
    local package="$1" host_version="$2" mode="${3:-install}"

    local installed_v=$(get_installed_version "$package")
    local available_v=$(get_available_version "$package")

    status "Package: $package | Available: ${available_v:-unknown} | Installed: ${installed_v:-none}"

    if [[ -z "$available_v" ]]; then
        if [[ "$mode" == "update" ]]; then
            status "Package $package is not in DNF repositories (local). Skipping update..."
            sleep 1
            return 0
        else
            die "Package '$package' was not found in Fedora repositories."
        fi
    fi

    [[ "$installed_v" == "$available_v" && "$installed_v" != "unknown" ]] && { status "Package is already up to date."; return 0; }

    info "Reading resolved dependencies from host tunnel..."
    local deps="${RESOLVED_DEPS:-}"

    if [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]]; then
        if [[ "$package" == "sysext-creator" ]]; then
            if grep -iq "kinoite" /run/host/etc/os-release || [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]]; then
                info "Special package detected: Adding GUI subpackage for KDE (kinoite)"
                deps="sysext-creator sysext-creator-kinoite"
            else
                info "Special package detected: Keeping sysext-creator (Core only)"
                deps="sysext-creator"
            fi
        fi
    fi

    [[ -z "$deps" || "$deps" == " " ]] && deps="$package"

    # FIX 1: Convert string to array to prevent shell injection via word splitting
    read -ra DEPS_ARRAY <<< "$deps"

    # FIX 2: Deep Blacklist Check (Check all resolved dependencies, not just the parent)
    for dep in "${DEPS_ARRAY[@]}"; do
        for b in "${BLACKLIST[@]}"; do
            # Strict match or match with version dash (e.g. systemd or systemd-255)
            if [[ "$dep" == "$b" || "$dep" =~ ^${b}- ]]; then
                die "Security block: Dependency '$dep' contains blacklisted core system component '$b'. Aborting to prevent Kernel Panic."
            fi
        done
    done

    WORKDIR=$(mktemp -d)
    mkdir -p "$WORKDIR/rpms"

    info "Downloading and extracting RPM packages..."
    dnf clean expire-cache >/dev/null 2>&1 || true

    local retries=3
    local dl_success=0
    for ((i=1; i<=retries; i++)); do
        # FIX 1.5: Pass the array securely to DNF to prevent command execution
        if dnf download "${DEPS_ARRAY[@]}" --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$WORKDIR/rpms"; then
            dl_success=1
            break
        else
            warn "Download failed (attempt $i/$retries). Retrying in 2 seconds..."
            sleep 2
        fi
    done

    if [[ $dl_success -eq 0 ]]; then
        die "Failed to download packages after $retries attempts. Check your network or repository."
    fi

    for rpm in "$WORKDIR/rpms"/*.rpm; do rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null || true; done
    
    info "Resolving base system conflicts (Smart Pruning)..."
    local map_file="$STAGING_DIR/host_usr_files.txt"

    if [[ -f "$map_file" ]]; then
        find "$WORKDIR/usr" \( -type f -o -type l \) 2>/dev/null | while read -r filepath; do
            relative_path="${filepath#$WORKDIR}"
            if grep -F -x -q "$relative_path" "$map_file"; then
                rm -f "$filepath"
            fi
        done
    fi

    process_extension "$package" "$host_version" "$available_v" "$mode"
}

cmd_install_local() {
    local rpm_path="$1" host_version="$2"

    if [[ ! -f "$rpm_path" && -f "/run/host${rpm_path}" ]]; then
        info "Translating host path to container path..."
        rpm_path="/run/host${rpm_path}"
    fi

    [[ ! -f "$rpm_path" ]] && die "File not found: $rpm_path"

    info "Analyzing local file..."
    local package=$(rpm -qp --queryformat '%{NAME}' "$rpm_path" 2>/dev/null)
    local available_v=$(rpm -qp --queryformat '%{VERSION}-%{RELEASE}' "$rpm_path" 2>/dev/null)

    [[ -z "$package" ]] && die "Cannot read metadata from the local RPM package."

    local installed_v=$(get_installed_version "$package")
    status "Local package: $package | Version: $available_v | Installed: ${installed_v:-no}"
    [[ "$installed_v" == "$available_v" && "$
