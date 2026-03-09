#!/bin/bash
set -euo pipefail
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"
LOG_FILE="/var/log/sysext-creator.log"
REFRESH_NEEDED=0

shopt -s nullglob
shopt -s dotglob

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') INFO: $1" >> "$LOG_FILE"; }
err() { echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: $1" >> "$LOG_FILE"; }

# A. Version Requests
for req_file in "$STAGING_DIR"/*.version-req; do
    pkg_name=$(basename "$req_file" .version-req)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$req_file"; continue; }

    res_file="$STAGING_DIR/${pkg_name}.version-res"

    # BEZPEČNÉ HLEDÁNÍ (bez příkazu ls, který by mohl skript sestřelit)
    files=("$EXT_DIR"/${pkg_name}-fc*.raw "$EXT_DIR"/${pkg_name}.raw)
    raw_file="${files[0]:-}"

    if [[ -n "$raw_file" && -f "$raw_file" ]]; then
        ext_name=$(basename "$raw_file" .raw)
        systemd-dissect --with "$raw_file" cat "usr/lib/extension-release.d/extension-release.${ext_name}" 2>/dev/null | grep "^SYSEXT_VERSION_ID=" | cut -d'=' -f2 > "$res_file" || touch "$res_file"
    else
        touch "$res_file"
    fi
    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$req_file"
done

# B. /etc Removals
for etc_rm in "$STAGING_DIR"/*.etc.remove; do
    [[ ! -s "$etc_rm" ]] && { rm -f "$etc_rm"; continue; }
    while IFS= read -r f; do [[ "$f" == /etc/* && "$f" != *..* ]] && rm -f "$f"; done < "$etc_rm"
    rm -f "$etc_rm"
done

# C. Deletions
for del_file in "$STAGING_DIR"/*.delete; do
    pkg_name=$(basename "$del_file" .delete)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$del_file"; continue; }

    log "Removing extension: $pkg_name"
    # Smažeme všechny varianty daného rozšíření (s verzí i bez)
    rm -f "$EXT_DIR/${pkg_name}-fc"*.raw "$EXT_DIR/${pkg_name}.raw"
    rm -f "$del_file"
    REFRESH_NEEDED=1
done

# D. New Images (*.raw)
for raw_file in "$STAGING_DIR"/*.raw; do
    [[ ! -s "$raw_file" ]] && { rm -f "$raw_file"; continue; }

    pkg_file=$(basename "$raw_file")
    log "Deploying new extension: $pkg_file"

    if mv "$raw_file" "$EXT_DIR/"; then
        chown root:root "$EXT_DIR/$pkg_file"
        chmod 0644 "$EXT_DIR/$pkg_file"

        if command -v restorecon >/dev/null 2>&1; then
            restorecon "$EXT_DIR/$pkg_file" || err "Failed to restorecon $pkg_file"
        fi
        REFRESH_NEEDED=1
    else
        err "Failed to move $raw_file to $EXT_DIR"
    fi
done

if [[ $REFRESH_NEEDED -eq 1 ]]; then
    log "Refreshing systemd-sysext..."
    systemd-sysext refresh || err "Systemd-sysext refresh failed!"
fi
exit 0
