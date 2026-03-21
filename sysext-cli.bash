#!/usr/bin/env bash

# Bash completion for sysext-cli
# Provides intelligent auto-completion for commands and extension names

_sysext_cli_completions() {
    local cur prev words cword command

    # Standard Bash completion variables
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    command="${COMP_WORDS[1]}"

    local commands="list deploy install remove refresh"

    # 1. Complete the main command (first argument)
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
        return 0
    fi

    # 2. Complete arguments based on the specific subcommand
    case "${command}" in
        remove)
            # Fetch active extensions from the system layer directory
            local exts=""
            if [[ -d "/var/lib/extensions" ]]; then
                # List files, match .raw, exclude .confext.raw, and strip the extension
                exts=$(ls -1 /var/lib/extensions 2>/dev/null | grep -E '\.raw$' | grep -v '\.confext\.raw$' | sed 's/\.raw$//')
            fi
            COMPREPLY=( $(compgen -W "${exts}" -- "${cur}") )
            return 0
            ;;
        deploy|install)
            # Enable default file and directory completion for paths
            compopt -o default 2>/dev/null
            return 0
            ;;
        *)
            # No completion for other commands
            return 0
            ;;
    esac
}

# Register the completion function for sysext-cli
complete -F _sysext_cli_completions sysext-cli
