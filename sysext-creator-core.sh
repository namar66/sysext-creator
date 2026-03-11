#!/bin/bash

################################################################################
# Sysext-Creator-Core (v2.0 - Pure Podman Edition)
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

    if [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]]; then
        if [[ "$package" == "sysext-creator" ]]; then
            if grep -iq "kinoite" /run/host/etc/os-release || [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]]; then
                info "Special package detected: Switching to sysext-creator-kinoite (GUI)"
                package="sysext-creator-kinoite"
            else
                info "Special package detected: Keeping sysext-creator (Core)"
            fi
        fi
    fi

    [[ "$package" =~ ^($(IFS='|'; echo "${BLACKLIST[*]}"))$ ]] && die "Installation of '$package' is blocked (blacklist)."

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

    WORKDIR=$(mktemp -d)
    mkdir -p "$WORKDIR/rpms"

    info "Reading resolved dependencies from host tunnel..."
    local deps="${RESOLVED_DEPS:-}"
    [[ -z "$deps" || "$deps" == " " ]] && deps="$package"

    info "Downloading and extracting RPM packages..."
    dnf download $deps --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$WORKDIR/rpms" >/dev/null
    for rpm in "$WORKDIR/rpms"/*.rpm; do rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null; done

    process_extension "$package" "$host_version" "$available_v" "$mode"
}

cmd_install_local() {
    local rpm_path="$1" host_version="$2"

    # --- KOUZLO 2.0: Autodetekce cesty z hostitele ---
    if [[ ! -f "$rpm_path" && -f "/run/host${rpm_path}" ]]; then
        info "Translating host path to container path..."
        rpm_path="/run/host${rpm_path}"
    fi
    # -------------------------------------------------

    [[ ! -f "$rpm_path" ]] && die "File not found: $rpm_path"

    info "Analyzing local file..."
    local package=$(rpm -qp --queryformat '%{NAME}' "$rpm_path" 2>/dev/null)
    local available_v=$(rpm -qp --queryformat '%{VERSION}-%{RELEASE}' "$rpm_path" 2>/dev/null)

    [[ -z "$package" ]] && die "Cannot read metadata from the local RPM package."

    local installed_v=$(get_installed_version "$package")
    status "Local package: $package | Version: $available_v | Installed: ${installed_v:-no}"
    [[ "$installed_v" == "$available_v" && "$installed_v" != "unknown" ]] && { status "This version is already installed."; return 0; }

    WORKDIR=$(mktemp -d)
    mkdir -p "$WORKDIR/rpms"

    info "Reading resolved dependencies from host tunnel..."
    local deps="${RESOLVED_DEPS:-}"
    deps=$(echo "$deps" | tr ' ' '\n' | grep -v "^${package}$" | tr '\n' ' ' | xargs || true)

    if [[ -n "$deps" ]]; then
        info "Fetching missing dependencies from Fedora repositories: $deps"
        dnf download $deps --refresh --forcearch="$(uname -m)" --exclude="*.i686" --destdir="$WORKDIR/rpms" --skip-unavailable >/dev/null
    else
        info "No additional dependencies from repositories are needed."
    fi

    info "Copying and extracting RPM packages..."
    cp "$rpm_path" "$WORKDIR/rpms/"
    for rpm in "$WORKDIR/rpms"/*.rpm; do rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null; done

    process_extension "$package" "$host_version" "$available_v" "install"
}

process_extension() {
    local package="$1" host_version="$2" available_v="$3" mode="$4"

    local ext_name="${package}-fc${host_version}"

    mkdir -p "$WORKDIR/usr/lib/extension-release.d"
    echo -e "ID=fedora\nVERSION_ID=$host_version\nSYSEXT_VERSION_ID=$available_v" > "$WORKDIR/usr/lib/extension-release.d/extension-release.${ext_name}"

    if [[ "$mode" != "update" ]] && ! [[ " ${SPECIAL_PACKAGES[*]} " =~ " ${package} " ]] && [[ -d "$WORKDIR/etc" ]]; then
        info "Processing configuration files from /etc..."
        tar -czf "$WORKDIR/${package}.etc.tar.gz" -C "$WORKDIR/etc" .
        mv "$WORKDIR/${package}.etc.tar.gz" "$STAGING_DIR/"
        
        # Novinka: Tracker pošleme rovnou do Stagingu k démonovi
        find "$WORKDIR/etc" ! -type d | sed "s|$WORKDIR||" > "$STAGING_DIR/${package}.etc.tracker"
        rm -rf "$WORKDIR/etc"
    fi

    local raw_file="$WORKDIR/${ext_name}.raw"
    mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 --file-contexts=/etc/selinux/targeted/contexts/files/file_contexts "$raw_file" "$WORKDIR" >/dev/null
    mv "$raw_file" "$STAGING_DIR/"

    success "Extension $ext_name was successfully dispatched to daemon for deployment."
    cleanup_workdir
}

cmd_check_update() {
    info "Checking for available updates..."
    local packages="${HOST_PKGS:-}"

    [[ -z "$packages" ]] && { status "No packages are installed."; return 0; }

    local updates_available=0

    echo ""
    printf "%-30s %-25s %-25s\n" "PACKAGE" "INSTALLED" "AVAILABLE"
    echo "--------------------------------------------------------------------------------"

    for pkg in $packages; do
        [[ -z "$pkg" ]] && continue
        sleep 0.5

        local installed_v=$(get_installed_version "$pkg")
        local available_v=$(get_available_version "$pkg")

        [[ -z "$available_v" ]] && available_v="unknown"
        [[ -z "$installed_v" ]] && installed_v="unknown"

        if [[ "$installed_v" != "$available_v" && "$available_v" != "unknown" ]]; then
            printf "%-30s %-25s %-25s\n" "$pkg" "$installed_v" "$available_v"
            updates_available=1
        fi
    done

    echo ""
    if [[ $updates_available -eq 0 ]]; then
        success "All system extensions are up to date."
    else
        info "To install these updates, run: sysext-creator update"
    fi
}

cmd_search() {
    local keyword="${1:-}"
    [[ -z "$keyword" ]] && die "Enter a search term (e.g., sysext-creator search htop)."

    info "Searching for packages matching '$keyword'..."
    local raw_output=$(dnf --quiet search "$keyword" 2>/dev/null || true)

    if [[ -z "$raw_output" ]]; then
        status "No packages found."
        return 0
    fi

    echo ""
    printf "%-35s %s\n" "PACKAGE" "SUMMARY"
    echo "--------------------------------------------------------------------------------"

    echo "$raw_output" | awk '
        /^Odpov/ || /^Matched/ || /^Aktualizace/ || /^Updating/ || /^Repozit/ || /^Repositories/ || /^Posled/ || /^Last/ || /^===/ {next}
        NF < 2 {next}
        {
            name_arch = $1
            sub(/\.(x86_64|noarch|i686|aarch64|src)$/, "", name_arch)
            $1 = ""
            summary = $0
            sub(/^ +/, "", summary)
            printf "%-35s %s\n", name_arch, summary
        }
    ' | sort -u
    echo ""
}

main() {
    [[ $# -lt 1 ]] && { echo "Usage: $0 install|install-local|update-single|check-update|search [package/path]"; exit 1; }
    local h_v=$(validate_environment)
    case "$1" in
        install)       cmd_install "$2" "$h_v" "install" ;;
        install-local) cmd_install_local "$2" "$h_v" ;;
        update-single) cmd_install "$2" "$h_v" "update" ;;
        check-update)  cmd_check_update ;;
        search)        cmd_search "${2:-}" ;;
        *)             die "Unknown command: $1" ;;
    esac
}

main "$@"
