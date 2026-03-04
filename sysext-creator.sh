#!/bin/bash
set -euo pipefail

# ⚙️ KONFIGURACE
TOOL_VERSION="1.2.0"
GH_USER="namar66"
REPO="sysext-creator"
BRANCH="main"
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-worker-fc${HOST_VERSION}"
WORKSPACE="$HOME/.cache/sysext-creator-workspace"
EXT_DIR="/var/lib/extensions"

# --- OCHRANNÉ FUNKCE ---
is_blacklisted() {
    local pkg="$1"
    case "$pkg" in
        kernel*|systemd*|glibc*|dbus*|pam|dracut*|grub2*|selinux-policy*|sysext-creator*|update)
            return 0 ;;
        *)
            return 1 ;;
    esac
}

# --- PŘÍKAZY ---
cmd_self_upgrade() {
    echo "🌐 Checking for tool updates on GitHub..."
    local raw_url="https://raw.githubusercontent.com/$GH_USER/$REPO/$BRANCH"
    local upgrade_dir="$WORKSPACE/upgrade"

    mkdir -p "$upgrade_dir"

    curl -sSL "$raw_url/sysext-creator.sh" -o "$upgrade_dir/sysext-creator.sh"

    if [[ ! -s "$upgrade_dir/sysext-creator.sh" ]]; then
        echo "❌ Failed to connect to GitHub."
        rm -rf "$upgrade_dir"
        return 1
    fi

    local remote_ver=$(grep -m 1 '^TOOL_VERSION=' "$upgrade_dir/sysext-creator.sh" | cut -d'"' -f2 || true)

    echo "   Installed: ${TOOL_VERSION:-unknown}"
    echo "   Available: ${remote_ver:-unknown}"

    if [[ -n "$remote_ver" && "$TOOL_VERSION" == "$remote_ver" ]]; then
        echo "✅ Sysext-Creator is already up to date."
        rm -rf "$upgrade_dir"
        return 0
    fi

    echo "⬇️ Downloading latest core scripts..."
    curl -sSL "$raw_url/sysext-creator-core.sh" -o "$upgrade_dir/sysext-creator-core.sh"
    curl -sSL "$raw_url/build-bundle.sh" -o "$upgrade_dir/build-bundle.sh"
    curl -sSL "$raw_url/sysext-setup.sh" -o "$upgrade_dir/sysext-setup.sh"
    chmod +x "$upgrade_dir/"*.sh

    if [[ -x "$upgrade_dir/build-bundle.sh" ]]; then
        echo "🔄 Re-bundling the tool as a system extension..."
        "$upgrade_dir/build-bundle.sh"
        sudo systemctl restart systemd-sysext.service
        echo "✨ Self-upgrade to v$remote_ver successful!"
    else
        echo "❌ Failed to download core scripts."
    fi
    rm -rf "$upgrade_dir"
}

cmd_update_check() {
    echo "🔄 Refreshing repository metadata..."
    rpm-ostree refresh-md >/dev/null

    echo "📊 Checking for available updates..."
    local pkgs=$(ls "$EXT_DIR" 2>/dev/null | grep "\.raw$" | sed -E 's/-(v?[0-9]|fc[0-9]).*//' | sort -u)
    local updates_available=0

    echo "--------------------------------------------------------------------------------"
    printf "%-20s | %-25s | %-25s\n" "PACKAGE" "INSTALLED" "AVAILABLE"
    echo "--------------------------------------------------------------------------------"

    for pkg in $pkgs; do
        [[ -z "$pkg" || "$pkg" == sysext-creator* ]] && continue

        local current_file=$(ls "$EXT_DIR" 2>/dev/null | grep "^${pkg}-" | head -n1 || true)
        local current_ver="none"
        if [[ -n "$current_file" ]]; then
            current_ver=$(echo "$current_file" | sed -E "s/^${pkg}-//; s/\.raw$//")
        fi

        local dry_run=$(rpm-ostree install --dry-run "$pkg" 2>/dev/null || true)
        local available_ver="unknown"
        if [[ -n "$dry_run" && "$dry_run" == *"packages:"* ]]; then
            local available_pkg_string=$(echo "$dry_run" | sed -n '/packages:/,$p' | grep -E "^  $pkg-[0-9]" | head -n1 | awk '{print $1}')
            available_ver=$(echo "$available_pkg_string" | sed -E "s/^${pkg}-//; s/\.[^.]+$//")
        fi

        if [[ "$current_ver" != "$available_ver" && "$available_ver" != "unknown" ]]; then
            printf "%-20s | %-25s | %-25s 🆕\n" "$pkg" "$current_ver" "$available_ver"
            updates_available=$((updates_available + 1))
        else
            printf "%-20s | %-25s | %-25s\n" "$pkg" "$current_ver" "$available_ver"
        fi
    done

    echo "--------------------------------------------------------------------------------"
    if [[ $updates_available -gt 0 ]]; then
        echo "💡 $updates_available update(s) available. Run '$0 update' to install."
    else
        echo "✅ All extensions are up to date."
    fi
}

cmd_install() {
    local pkg_input="${1:-}"
    [[ -z "$pkg_input" ]] && return 0

    # Zjistíme čisté jméno balíčku (i z cesty k RPM souboru)
    local pkg_name=$(basename "$pkg_input" | sed 's/\.rpm$//' | cut -d'-' -f1)

    if is_blacklisted "$pkg_name"; then
        echo "⛔ Blocked: Package '$pkg_name' is blacklisted because it conflicts with the core OS."
        return 1
    fi

    echo -e "\n🔍 Checking $pkg_input..."

    local current_file=$(ls "$EXT_DIR" 2>/dev/null | grep "^${pkg_name}-" | head -n1 || true)
    local current_ver="none"
    if [[ -n "$current_file" ]]; then
        current_ver=$(echo "$current_file" | sed -E "s/^${pkg_name}-//; s/\.raw$//")
    fi

    local dry_run=$(rpm-ostree install --dry-run "$pkg_input" 2>/dev/null || true)
    if [[ -z "$dry_run" || ! "$dry_run" == *"packages:"* ]]; then
        echo "❌ Error: Could not resolve $pkg_input via rpm-ostree."
        return 1
    fi

    # Vytáhneme verzi balíčku
    local available_pkg_string=$(echo "$dry_run" | sed -n '/packages:/,$p' | grep -E "^  $pkg_name-[0-9]" | head -n1 | awk '{print $1}')
    local available_ver=$(echo "$available_pkg_string" | sed -E "s/^${pkg_name}-//; s/\.[^.]+$//")

    echo "   Installed: $current_ver"
    echo "   Available: ${available_ver:-unknown}"

    if [[ -n "$available_ver" && "$current_ver" == "$available_ver" ]]; then
        echo "✅ $pkg_name is already up to date."
        return 0
    fi

    local deps=$(echo "$dry_run" | sed -n '/packages:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | tr '\n' ' ')
    [[ -z "$deps" ]] && deps="$pkg_name"

    echo "📦 Waking up worker to bake version $available_ver..."
    # Zde musíme zajistit cestu k jádru Pekaře
    local core_script="sysext-creator-core"
    if [[ -x "$(which $core_script 2>/dev/null)" ]]; then
        cp "$(which $core_script)" "$WORKSPACE/core.sh"
    else
        cp ./sysext-creator-core.sh "$WORKSPACE/core.sh"
    fi
    chmod +x "$WORKSPACE/core.sh"

    local target_raw="${pkg_name}-${available_ver}.raw"
    local output=$(sudo podman exec -w /workspace "$CONTAINER_NAME" ./core.sh bake "$pkg_name" "$HOST_VERSION" "$target_raw" "$deps")
    local status_line=$(echo "$output" | grep "^STATUS:" || true)

    if [[ "$status_line" == *"STATUS:BAKED"* ]]; then
        echo "🚚 Deploying $target_raw..."
        sudo rm -f "$EXT_DIR/${pkg_name}-"*.raw
        sudo mv "$WORKSPACE/$target_raw" "$EXT_DIR/"
        sudo systemctl restart systemd-sysext.service
        echo "✨ $pkg_name updated successfully."
    else
        echo "❌ Build failed. Output:"
        echo "$output"
    fi
}

cmd_update_all() {
    echo "🔄 Refreshing repository metadata..."
    rpm-ostree refresh-md >/dev/null

    echo "🔄 Checking for updates in $EXT_DIR..."
    local pkgs=$(ls "$EXT_DIR" 2>/dev/null | grep "\.raw$" | sed -E 's/-(v?[0-9]|fc[0-9]).*//' | sort -u)

    for p in $pkgs; do
        [[ -z "$p" || "$p" == sysext-creator* ]] && continue
        cmd_install "$p"
    done
}

# --- MAIN ---
case "${1:-}" in
    install)      cmd_install "${2:-}" ;;
    update)       [[ -n "${2:-}" ]] && cmd_install "$2" || cmd_update_all ;;
    update-check) cmd_update_check ;;
    self-upgrade) cmd_self_upgrade ;;
    version|--version|-v)
        echo "💎 Sysext-Creator v${TOOL_VERSION} (Pure Podman Edition)"
        ;;
    rm|remove)
        pkg="${2:-}"
        [[ -z "$pkg" ]] && { echo "Usage: $0 rm <package>"; exit 1; }
        if is_blacklisted "$pkg"; then echo "⛔ Blocked: Cannot remove core system packages."; exit 1; fi
        echo "🗑 Removing $pkg..."
        sudo rm -f "$EXT_DIR/${pkg}-"*.raw && sudo systemctl restart systemd-sysext.service
        echo "✅ $pkg removed."
        ;;
    list)         ls -lh "$EXT_DIR" ;;
    *)
        echo "Usage: $0 {install|update|update-check|rm|list|self-upgrade|version} [package]"
        exit 1
        ;;
esac
