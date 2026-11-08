#!/usr/bin/env bash

# Bash completion for sysext-cli v3.2.4
# Supports subcommands (list, remove, doctor, install, update), active layer discovery, and flags

_sysext_cli_completions() {
    local cur prev command
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    command="${COMP_WORDS[1]}"

    local commands="list remove doctor install update"

    # 1. Doplňování hlavního subpříkazu
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
        return 0
    fi

    # Pomocná funkce pro vyčtení aktivních .raw vrstev (vynechává .confext)
    _get_active_sysexts() {
        if [[ -d "/var/lib/extensions" ]]; then
            find /var/lib/extensions -maxdepth 1 -name "*.raw" ! -name "*.confext.raw" -printf "%f\n" 2>/dev/null | sed 's/\.raw$//'
        fi
    }

    # 2. Kontextové doplňování argumentů podle subpříkazu
    case "${command}" in
        remove)
            if [[ ${COMP_CWORD} -eq 2 ]]; then
                local exts=$(_get_active_sysexts)
                COMPREPLY=( $(compgen -W "${exts}" -- "${cur}") )
            fi
            return 0
            ;;

        update)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--all -h --help" -- "${cur}") )
                return 0
            fi

            if [[ ${COMP_CWORD} -eq 2 ]]; then
                local exts=$(_get_active_sysexts)
                COMPREPLY=( $(compgen -W "${exts} --all" -- "${cur}") )
            fi
            return 0
            ;;

        install)
            # U dalších argumentů povolíme standardní doplňování cest (pro lokální .rpm soubory)
            if [[ ${COMP_CWORD} -ge 3 ]]; then
                compopt -o default 2>/dev/null
            fi
            return 0
            ;;

        doctor|list)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-h --help" -- "${cur}") )
            fi
            return 0
            ;;

        *)
            return 0
            ;;
    esac
}

# Registrace pro symlink i přímé spuštění .py skriptu
complete -F _sysext_cli_completions sysext-cli
complete -F _sysext_cli_completions sysext-cli.py
