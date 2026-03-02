#!/bin/bash

# Zastaví skript při jakékoliv chybě
set -euo pipefail

echo "🚀 Začínáme s instalací prostředí pro Sysext-Creator..."

# Zjištění aktuální verze hostitele
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"

# 1. KROK: Oprávnění a Sudoers (Bezheslový refresh pro timer na pozadí)
echo "=> Nastavuji práva pro aktualizace na pozadí (budete vyzváni k zadání sudo hesla)..."
if ! getent group sysext-admins >/dev/null; then
    sudo groupadd -f sysext-admins
fi
sudo usermod -aG sysext-admins "$USER"

sudo mkdir -p /var/lib/extensions
sudo chown root:sysext-admins /var/lib/extensions
sudo chmod 775 /var/lib/extensions

echo "%sysext-admins ALL=(root) NOPASSWD: /usr/bin/systemd-sysext refresh, /usr/bin/systemd-sysext unmerge" | sudo tee /etc/sudoers.d/sysext-creator > /dev/null
sudo chmod 440 /etc/sudoers.d/sysext-creator

# 2. KROK: Instalace Distroboxu
if ! command -v distrobox &> /dev/null; then
    echo "=> Distrobox nenalezen. Instaluji lokálně do ~/.local/bin..."
    curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sh -s -- --prefix ~/.local
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "=> Distrobox nalezen, pokračuji..."
fi

# 3. KROK: Vytvoření kontejneru pro aktuální systém
echo "=> Vytvářím kontejner '$CONTAINER_NAME' (tohle může chvíli trvat)..."
distrobox create --name "$CONTAINER_NAME" --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} --volume /var/lib/extensions:/var/lib/extensions:rw -Y

echo "=> Instaluji potřebné balíčky uvnitř kontejneru..."
distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y squashfs-tools cpio dnf-utils

# 4. KROK: Instalace hlavního skriptu a chytrého Wrapperu
echo "=> Kopíruji nástroje do ~/.local/bin..."
mkdir -p ~/.local/bin

if [ ! -f "sysext-creator.sh" ]; then
    echo "❌ Chyba: Nemohu najít 'sysext-creator.sh' v aktuální složce!"
    exit 1
fi

cp sysext-creator.sh ~/.local/bin/sysext-creator-core
chmod +x ~/.local/bin/sysext-creator-core

# Vytvoření Wrapperu s logikou pro upgrade a úklid starých kontejnerů
cat << 'EOF' > ~/.local/bin/sysext-creator
#!/bin/bash
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"

# Pokud uživatel zavolá upgrade kontejneru po povýšení systému
if [ "${1:-}" == "upgrade-box" ]; then
    echo "📦 Zjišťuji stav pro Fedoru $HOST_VERSION..."

    if distrobox list | grep -q "$CONTAINER_NAME"; then
        echo "=> Kontejner $CONTAINER_NAME již existuje. Není potřeba zakládat nový."
    else
        echo "=> Vytvářím NOVÝ kontejner $CONTAINER_NAME..."
        distrobox create --name "$CONTAINER_NAME" --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} --volume /var/lib/extensions:/var/lib/extensions:rw -Y
        distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y squashfs-tools cpio dnf-utils
    fi

    echo "🔄 Přebudovávám nainstalované aplikace pro novou verzi systému..."
    distrobox-enter -n "$CONTAINER_NAME" -- sysext-creator-core update
    echo "✅ Přebudování dokončeno!"

# Najde všechny kontejnery, seřadí je podle verze od nejstarší po nejnovější a vyřadí ten aktuální
    OLD_BOXES=$(distrobox list --no-color | grep -o "sysext-box-fc[0-9]*" | grep -v "$CONTAINER_NAME" | sort -u || true)

    if [ -n "$OLD_BOXES" ]; then
        echo "🧹 Spouštím Garbage Collector (Pravidlo N-1)..."

        # Spočítáme, kolik starých kontejnerů tam je
        BOX_COUNT=$(echo "$OLD_BOXES" | wc -w)

        # Necháme si jen ten jeden nejnovější ze starých (např. při F43 si necháme F42)
        # Seřadíme je sestupně a přeskočíme první (ten nejnovější ze starých)
        BOXES_TO_DELETE=$(echo "$OLD_BOXES" | tr ' ' '\n' | sort -r | tail -n +2)

        if [ -n "$BOXES_TO_DELETE" ]; then
             for box in $BOXES_TO_DELETE; do
                 echo "🗑️ Mažu zastaralý kontejner: '$box'"
                 distrobox rm -f "$box"
             done
        else
            echo "=> Žádné zastaralé kontejnery ke smazání (udržuji jeden pro rollback)."
        fi
    fi
    exit 0
fi

# Směrování běžných příkazů do aktuálního kontejneru
distrobox-enter -n "$CONTAINER_NAME" -- sysext-creator-core "$@"
EOF

chmod +x ~/.local/bin/sysext-creator

# 5. KROK: Systemd Timer
echo "=> Nastavuji automatické denní aktualizace na pozadí..."
mkdir -p ~/.config/systemd/user/

cat << 'EOF' > ~/.config/systemd/user/sysext-update.service
[Unit]
Description=Auto-update Sysext-Creator images

[Service]
Type=oneshot
ExecStart=/bin/bash -c "$HOME/.local/bin/sysext-creator update"
EOF

cat << 'EOF' > ~/.config/systemd/user/sysext-update.timer
[Unit]
Description=Daily Auto-update for Sysext-Creator

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

# 6. KROK: Bash completion (Našeptávač)
echo "=> Nastavuji bash completion (našeptávač příkazů)..."
mkdir -p ~/.local/share/bash-completion/completions

cat << 'EOF' > ~/.local/share/bash-completion/completions/sysext-creator
_sysext_creator_completions() {
    local cur prev commands installed_pkgs

    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="install update rm list upgrade-box"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
        return 0
    fi

    if [[ "${prev}" == "rm" ]]; then
        installed_pkgs=$(ls /var/lib/extensions/*.raw 2>/dev/null | xargs -n 1 basename 2>/dev/null | sed -E 's/-[0-9].*//' | sort -u)
        COMPREPLY=( $(compgen -W "${installed_pkgs}" -- "${cur}") )
        return 0
    fi
    COMPREPLY=()
}
complete -F _sysext_creator_completions sysext-creator
EOF

echo "--------------------------------------------------------"
echo "✅ Instalace je kompletní!"
echo "⚠️ DŮLEŽITÉ: Nyní zavřete tento terminál a otevřete nový,"
echo "aby se načetlo vaše členství v nové skupině 'sysext-admins'."
echo "Poté zkuste nainstalovat první balíček: sysext-creator install mc"
echo "--------------------------------------------------------"
