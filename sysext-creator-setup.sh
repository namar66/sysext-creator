#!/bin/bash
set -euo pipefail

# ==========================================
# UNINSTALL LOGIKA
# ==========================================
if [[ "${1:-}" == "uninstall" ]]; then
    echo "🧹 Zahajuji kompletní odstranění lokální instalace Sysext-Creator..."

    echo "=> Vypínám a odstraňuji systemd služby..."
    sudo systemctl stop sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo systemctl disable sysext-creator-deploy.path sysext-creator-deploy.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.path
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.service
    sudo systemctl daemon-reload

    echo "=> Odstraňuji hostitelského démona..."
    sudo rm -f /usr/local/bin/sysext-creator-deploy.sh

    echo "=> Odstraňuji uživatelské binárky a GUI..."
    rm -f "$HOME/.local/bin/sysext-creator"
    rm -f "$HOME/.local/bin/sysext-creator-core"
    rm -f "$HOME/.local/bin/sysext-gui"

    echo "=> Odstraňuji integraci do plochy, menu a doplňování terminálu..."
    rm -f "$HOME/.local/share/applications/sysext-creator.desktop"
    rm -f "$HOME/.local/share/icons/hicolor/512x512/apps/sysext-creator-icon.png"
    rm -f "$HOME/.local/share/kservices5/ServiceMenus/sysext-creator-install.desktop"
    rm -f "$HOME/.local/share/bash-completion/completions/sysext-creator"
    rm -f "$HOME/.local/bin/sysext-creator-test"
    if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
    echo "✅ KDE menu aktualizováno."
    fi
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi

    echo ""
    read -p "Do you want to remove ALL installed raw images in /var/lib/extensions? (yes/no): " remove_all
    if [[ "$remove_all" == "yes" ]]; then
        echo "=> Odstraňuji VŠECHNY RAW obrazy..."
        sudo rm -f /var/lib/extensions/*.raw
    else
        echo "=> Ponechávám uživatelské obrazy, odstraňuji pouze případný samotný Sysext-Creator obraz..."
        sudo rm -f /var/lib/extensions/sysext-creator-fc*.raw
        sudo rm -f /var/lib/extensions/sysext-creator.raw 2>/dev/null || true
    fi

    echo "=> Odpojuji systémová rozšíření..."
    sudo systemd-sysext refresh

    echo "--------------------------------------------------------"
    echo "✅ Lokální instalace Sysext-Creator byla kompletně odstraněna."
    echo "--------------------------------------------------------"
    exit 0
fi

# ==========================================
# INSTALL LOGIKA
# ==========================================
echo "🚀 Starting Sysext-Creator environment setup (v1.5.0)..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
STAGING_DIR="/var/tmp/sysext-staging"
EXT_DIR="/var/lib/extensions"

if [ ! -d "$EXT_DIR" ]; then
    echo "⚙️ Creating missing extensions directory: $EXT_DIR"
    sudo systemctl enable --now systemd-sysext.service
    sudo mkdir -p "$EXT_DIR"
    sudo chmod 0755 "$EXT_DIR"
fi

echo "=> Installing deployment daemon (requires sudo)..."
if [[ ! -f "$SCRIPT_DIR/sysext-creator-deploy.sh" ]]; then
    echo "❌ Error: sysext-creator-deploy.sh not found in $SCRIPT_DIR!"
    exit 1
fi

sudo cp "$SCRIPT_DIR/sysext-creator-deploy.sh" /usr/local/bin/sysext-creator-deploy.sh
sudo chown root:root /usr/local/bin/sysext-creator-deploy.sh
sudo chmod +x /usr/local/bin/sysext-creator-deploy.sh

sudo tee /etc/systemd/system/sysext-creator-deploy.service > /dev/null << 'EOF'
[Unit]
Description=Deploy staged systemd-sysext images
After=systemd-sysext.service
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sysext-creator-deploy.sh
EOF

sudo tee /etc/systemd/system/sysext-creator-deploy.path > /dev/null << 'EOF'
[Unit]
Description=Monitor sysext staging directory

[Path]
PathChanged=/var/tmp/sysext-staging
MakeDirectory=yes
DirectoryMode=0777

[Install]
WantedBy=multi-user.target
EOF

# --- ZDE JE OCHRANA PROTI SELINUX CHYBĚ ---
echo "=> Opravuji SELinux kontexty pro systemd služby..."
if command -v restorecon &> /dev/null; then
    sudo restorecon -v /etc/systemd/system/sysext-creator-deploy.service
    sudo restorecon -v /etc/systemd/system/sysext-creator-deploy.path
    sudo restorecon -v /usr/local/bin/sysext-creator-deploy.sh
fi
# ------------------------------------------

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

echo "=> Setting up user binaries in ~/.local/bin..."
mkdir -p "$HOME/.local/bin"
cp "$SCRIPT_DIR/sysext-creator-core.sh" "$HOME/.local/bin/sysext-creator-core"
cp "$SCRIPT_DIR/sysext-creator.sh" "$HOME/.local/bin/sysext-creator"
chmod +x "$HOME/.local/bin/sysext-creator-core" "$HOME/.local/bin/sysext-creator"

echo "=> Checking installed podman..."
if ! command -v podman &> /dev/null; then
    echo "❌ Error: Podman is required. Run on a atomic version of Fedora."
    exit 1
fi

if [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]] || pgrep -x plasmashell > /dev/null; then
    echo "=> Prostředí KDE detekováno. Přidávám kontextové menu do Dolphinu..."
    SERVICE_DIR="$HOME/.local/share/kio/servicemenus/"
    mkdir -p "$SERVICE_DIR"

    cat << 'EOF' > "$SERVICE_DIR/sysext-creator-install.desktop"
[Desktop Entry]
Type=Service
MimeType=application/x-rpm;
Actions=installExtension;
X-KDE-Priority=TopLevel

[Desktop Action installExtension]
Name=Instalovat jako Systémové Rozšíření (Sysext)
Icon=sysext-creator-icon
Exec=sysext-creator install-local "%u"
EOF

    echo "✅ Akce pro .rpm soubory úspěšně přidána."
    sysext-creator install python3-pyqt6
    echo "=> Setting up GUI application..."
    cp "$SCRIPT_DIR/sysext-gui" "$HOME/.local/bin/"
    chmod +x "$HOME/.local/bin/sysext-gui"

    echo "=> Installing desktop entry and icon..."
    mkdir -p "$HOME/.local/share/applications"
    mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
    cp "$SCRIPT_DIR/sysext-creator-icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/"
    cp "$SCRIPT_DIR/sysext-creator.desktop" "$HOME/.local/share/applications/"
    if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
    echo "✅ KDE menu aktualizováno."
    fi
    if command -v update-desktop-database &> /dev/null; then
     update-desktop-database "$HOME/.local/share/applications" || true
   fi
else
    echo "=> Prostředí KDE nebylo detekováno (běžíte pravděpodobně na GNOME/Silverblue). Instaluji pouze CLI verzi."
fi

echo "=> Konfiguruji automatické doplňování pro Bash..."
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
mkdir -p "$COMPLETION_DIR"

if [[ -f "$SCRIPT_DIR/bash-completion" ]]; then
    cp "$SCRIPT_DIR/bash-completion" "$COMPLETION_DIR/sysext-creator"
    source "$COMPLETION_DIR/sysext-creator" 2>/dev/null || true
else
    echo "⚠️ Upozornění: Soubor bash-completion v repozitáři chybí."
fi
# ---------- NOVÁ ČÁST PRO TESTY ----------
echo "=> Kopíruji nástroj pro integrační testy..."
cp "$SCRIPT_DIR/sysext-creator-test" "$HOME/.local/bin/"
chmod +x "$HOME/.local/bin/sysext-creator-test"

echo -e "\n================================================================================"
echo "✅ Instalace Sysext-Creator (v2.0) byla úspěšně dokončena!"
echo "================================================================================"
echo "⏳ Spouštím automatickou diagnostiku a zkoušku ohněm (E2E Test)..."
echo "Během testu se na pozadí vytvoří a zase smažou zkušební balíčky."

# Spuštění samotného testu
sysext-creator-test

echo -e "\nPokud testy prošly zeleně, systém je připraven k použití."
#echo "Pro nápovědu napiš: sysext-creator --help"
echo "--------------------------------------------------------"
echo "✅ Lokální instalace dokončena!"
