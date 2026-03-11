#!/bin/bash
set -euo pipefail

STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"
TRACKER_DIR="/var/lib/sysext-creator/trackers"
LOG_FILE="/var/log/sysext-creator.log"
REFRESH_NEEDED=0

# Zajistíme, že složka existuje
mkdir -p "$TRACKER_DIR"

shopt -s nullglob
shopt -s dotglob

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') INFO: $1" >> "$LOG_FILE"; }
err() { echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: $1" >> "$LOG_FILE"; }

# ======================================================================
# A. ZPRACOVÁNÍ POŽADAVKŮ NA VERZI
# ======================================================================
for req_file in "$STAGING_DIR"/*.version-req; do
    pkg_name=$(basename "$req_file" .version-req)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$req_file"; continue; }

    res_file="$STAGING_DIR/${pkg_name}.version-res"

    files=("$EXT_DIR"/${pkg_name}-fc*.raw "$EXT_DIR"/${pkg_name}.raw)
    raw_file="${files[0]:-}"

    if [[ -n "$raw_file" && -f "$raw_file" ]]; then
        ext_name=$(basename "$raw_file" .raw)
        ver=$(systemd-dissect --copy-from "$raw_file" "/usr/lib/extension-release.d/extension-release.${ext_name}" - 2>/dev/null | grep "^SYSEXT_VERSION_ID=" | cut -d'=' -f2 | tr -d '"' || true)

        if [[ -n "$ver" ]]; then
            echo "$ver" > "$res_file"
        else
            echo "unknown" > "$res_file"
        fi
    else
        echo "unknown" > "$res_file"
    fi

    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$req_file"
done

# ======================================================================
# B. ZPRACOVÁNÍ TRACKERŮ A MAZÁNÍ OBRAZŮ
# ======================================================================
for tracker in "$STAGING_DIR"/*.etc.tracker; do
    [[ ! -f "$tracker" ]] && continue
    pkg_file=$(basename "$tracker")
    mv "$tracker" "$TRACKER_DIR/$pkg_file"
    chmod 0644 "$TRACKER_DIR/$pkg_file"
done

for del_file in "$STAGING_DIR"/*.delete; do
    pkg_name=$(basename "$del_file" .delete)
    [[ -z "$pkg_name" || "$pkg_name" == "*" ]] && { rm -f "$del_file"; continue; }

    log "Removing extension: $pkg_name"
    rm -f "$EXT_DIR/${pkg_name}-fc"*.raw "$EXT_DIR/${pkg_name}.raw"

    local_tracker="$TRACKER_DIR/${pkg_name}.etc.tracker"

    # Deep cleanup pro /etc
    if grep -q "FORCE_ETC_CLEANUP" "$del_file" 2>/dev/null && [[ -f "$local_tracker" ]]; then
        log "Deep cleaning ALL /etc configuration for $pkg_name..."
        while IFS= read -r f; do
            [[ "$f" == /etc/* && "$f" != *..* ]] && rm -f "$f"
        done < "$local_tracker"
        rm -f "$local_tracker"

        while IFS= read -r d; do
            [[ "$d" == /etc/* ]] && rmdir --ignore-fail-on-non-empty "$d" 2>/dev/null || true
        done < <(sed 's|/[^/]*$||' "$local_tracker" | sort -ru)

    elif grep -q "SELECTED_ETC_CLEANUP" "$del_file" 2>/dev/null; then
        log "Deep cleaning SELECTED /etc configuration for $pkg_name..."
        while IFS= read -r f; do
            [[ "$f" == /etc/* && "$f" != *..* ]] && rm -f "$f"
        done < "$del_file"
        rm -f "$local_tracker"

    else
        # Pokud uživatel zvolil N (nic nemazat), nebo to byl jednoduchý balíček bez trackeru.
        rm -f "$local_tracker"
    fi

    rm -f "$del_file"
    REFRESH_NEEDED=1
done

# ======================================================================
# C. EXTRAKCE KONFIGURACE (/etc)
# ======================================================================
for etc_tar in "$STAGING_DIR"/*.etc.tar.gz; do
    [[ ! -s "$etc_tar" ]] && { rm -f "$etc_tar"; continue; }
    pkg_file=$(basename "$etc_tar")
    log "Extracting /etc configuration from: $pkg_file"
    tar -xzf "$etc_tar" -C /etc/ 2>/dev/null || err "Failed to extract $etc_tar"
    rm -f "$etc_tar"
done

# ======================================================================
# D. INSTALACE NOVÝCH OBRAZŮ (*.raw)
# ======================================================================
for raw_file in "$STAGING_DIR"/*.raw; do
    [[ ! -s "$raw_file" ]] && { rm -f "$raw_file"; continue; }

    pkg_file=$(basename "$raw_file")
    ext_name="${pkg_file%.raw}"
    log "Validating new extension before deployment: $pkg_file"

    validation_failed=0

    if ! systemd-dissect --validate "$raw_file" >/dev/null 2>&1; then
        err "Validation failed: $pkg_file is corrupted or invalid format."
        validation_failed=1
    fi

    if [[ $validation_failed -eq 0 ]]; then
        host_ver=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
        release_path="/usr/lib/extension-release.d/extension-release.${ext_name}"
        img_ver=$(systemd-dissect --copy-from "$raw_file" "$release_path" - 2>/dev/null | grep "^VERSION_ID=" | cut -d'=' -f2 | tr -d '"' || true)

        if [[ "$img_ver" != "$host_ver" ]]; then
            err "Validation failed: $pkg_file OS version mismatch (Image: $img_ver, Host: $host_ver)."
            validation_failed=1
        fi
    fi

    if [[ $validation_failed -eq 0 ]]; then
        files_to_check=$(systemd-dissect --list "$raw_file" 2>/dev/null | grep -E '^/?usr/(bin|sbin|lib/systemd)/' || true)
        for file in $files_to_check; do
            abs_file="$file"
            [[ "$abs_file" != /* ]] && abs_file="/$abs_file"
            if rpm -qf "$abs_file" >/dev/null 2>&1 && ! test -d "$abs_file"; then
                err "Validation failed: $pkg_file conflicts with base system file $abs_file"
                validation_failed=1
                break
            fi
        done
    fi

    if [[ $validation_failed -eq 1 ]]; then
        err "Rejecting $pkg_file due to validation errors. Image was deleted."
        rm -f "$raw_file"
        continue
    fi

    log "Validation passed. Deploying extension: $pkg_file"

    if cp "$raw_file" "$EXT_DIR/" && rm -f "$raw_file"; then
        chmod 0644 "$EXT_DIR/$pkg_file"
        if command -v restorecon >/dev/null 2>&1; then
            restorecon "$EXT_DIR/$pkg_file" || err "Failed to restorecon $pkg_file"
        fi
        REFRESH_NEEDED=1
    else
        err "Failed to deploy $pkg_file"
    fi
done

# ======================================================================
# E. AKTUALIZACE SYSTEMD-SYSEXT
# ======================================================================
if [[ $REFRESH_NEEDED -eq 1 ]]; then
    log "Refreshing systemd-sysext..."
    systemd-sysext refresh >> "$LOG_FILE" 2>&1 || err "systemd-sysext refresh failed"
fi

# ======================================================================
# F. DIAGNOSTIKA (DOCTOR)
# ======================================================================
if [[ -f "$STAGING_DIR/doctor.req" ]]; then
    log "Running Sysext Doctor diagnostics..."
    res_file="$STAGING_DIR/doctor.res"
    host_ver=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
    has_errors=0

    {
        files=("$EXT_DIR"/*.raw)
        if [[ ${#files[@]} -eq 0 || ! -f "${files[0]}" ]]; then
            echo "--------------------------------------------------------"
            echo "📋 No installed images found for diagnostics."
        else
            for img in "${files[@]}"; do
                img_name=$(basename "$img" .raw)
                echo "--------------------------------------------------------"
                echo "🔍 Checking image: $img_name.raw"

                if ! systemd-dissect --validate "$img" >/dev/null 2>&1; then
                    echo "❌ ERROR: Image structure is corrupted or invalid!"
                    has_errors=1
                    continue
                else
                    echo "✅ Image structure and format are valid."
                fi

                release_file="usr/lib/extension-release.d/extension-release.${img_name}"
                if ! systemd-dissect --copy-from "$img" "/$release_file" - >/dev/null 2>&1; then
                    echo "❌ ERROR: Missing or incorrectly named release label!"
                    has_errors=1
                else
                    img_ver=$(systemd-dissect --copy-from "$img" "/$release_file" - 2>/dev/null | grep "^VERSION_ID=" | cut -d'=' -f2 | tr -d '"' || true)
                    if [[ "$img_ver" != "$host_ver" ]]; then
                        echo "⚠️  WARNING: Image version ($img_ver) does not match the host ($host_ver)!"
                        has_errors=1
                    else
                        echo "✅ Label and OS version ($img_ver) match."
                    fi
                fi

                echo "🛠️  Scanning for conflicts with the base system (shadowing)..."
                conflicts=0
                files_to_check=$(systemd-dissect --list "$img" 2>/dev/null | grep -E '^/?usr/(bin|sbin|lib/systemd)/' || true)

                if [[ -n "$files_to_check" ]]; then
                    for file in $files_to_check; do
                        abs_file="$file"
                        [[ "$abs_file" != /* ]] && abs_file="/$abs_file"
                        if rpm -qf "$abs_file" >/dev/null 2>&1; then
                            if ! test -d "$abs_file"; then
                                echo "   ⚠️  CONFLICT DETECTED: $abs_file (already exists in the base system!)"
                                conflicts=$((conflicts + 1))
                            fi
                        fi
                    done
                fi

                if [[ $conflicts -eq 0 ]]; then
                    echo "✅ No conflicts with the base system found."
                else
                    echo "❌ Found a total of $conflicts conflicting file(s)."
                    has_errors=1
                fi
            done
        fi

        echo "--------------------------------------------------------"
        if [[ $has_errors -eq 0 ]]; then
            echo "✅ Diagnostics completed. All images are in 100% perfect condition!"
        else
            echo "⚠️  Diagnostics completed, but issues were found. Please fix them, or the system extensions might not work properly."
        fi
    } > "$res_file" 2>&1

    chmod 0666 "$res_file" 2>/dev/null || true
    rm -f "$STAGING_DIR/doctor.req"
fi

exit 0
