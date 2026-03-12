# ======================================================================
# B. ZPRACOVÁNÍ POŽADAVKŮ NA MAZÁNÍ (*.delete)
# ======================================================================
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

# SEKCE C (Původní plošná extrakce konfigurace) JE ZRUŠENA A PŘESUNUTA DO SEKCE D.

# ======================================================================
# D. VALIDACE A ATOMICKÁ INSTALACE NOVÝCH OBRAZŮ (*.raw)
# ======================================================================
for raw_file in "$STAGING_DIR"/*.raw; do
    [[ ! -s "$raw_file" ]] && { rm -f "$raw_file"; continue; }

    pkg_file=$(basename "$raw_file")
    ext_name="${pkg_file%.raw}"
    
    # Získáme čisté jméno balíčku (např. z 'distrobox-fc43' udělá 'distrobox')
    base_pkg_name=$(echo "$ext_name" | sed -E 's/-fc[0-9]+$//')

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
        
        # ATOMICKÁ OPRAVA: Jelikož obraz selhal, rovnou smažeme i jeho připravenou konfiguraci!
        rm -f "$STAGING_DIR/${base_pkg_name}.etc.tar.gz"
        rm -f "$STAGING_DIR/${base_pkg_name}.etc.tracker"
        continue
    fi

    log "Validation passed. Deploying extension: $pkg_file"

    if cp "$raw_file" "$EXT_DIR/" && rm -f "$raw_file"; then
        chmod 0644 "$EXT_DIR/$pkg_file"
        if command -v restorecon >/dev/null 2>&1; then
            restorecon "$EXT_DIR/$pkg_file" || err "Failed to restorecon $pkg_file"
        fi

        # --- ATOMICKÁ INSTALACE KONFIGURACE (Teprve nyní, když je obraz bezpečně v systému) ---
        if [[ -s "$STAGING_DIR/${base_pkg_name}.etc.tar.gz" ]]; then
            log "Extracting /etc configuration for: $base_pkg_name"
            tar -xzf "$STAGING_DIR/${base_pkg_name}.etc.tar.gz" -C /etc/ 2>/dev/null || err "Failed to extract config"
            rm -f "$STAGING_DIR/${base_pkg_name}.etc.tar.gz"
        fi

        if [[ -f "$STAGING_DIR/${base_pkg_name}.etc.tracker" ]]; then
            mv "$STAGING_DIR/${base_pkg_name}.etc.tracker" "$TRACKER_DIR/${base_pkg_name}.etc.tracker"
            chmod 0644 "$TRACKER_DIR/${base_pkg_name}.etc.tracker"
        fi
        # --------------------------------------------------------------------------------------

        REFRESH_NEEDED=1
    else
        err "Failed to deploy $pkg_file"
    fi
done
