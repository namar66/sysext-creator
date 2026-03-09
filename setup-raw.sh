#!/bin/bash
set -euo pipefail

# ==========================================
# UNINSTALL LOGIKA
# ==========================================
if [[ "${1:-}" == "uninstall" ]]; then
    echo "🧹 Zahajuji kompletní a bezpečné odstranění Sysext-Creator..."

    echo "=> Vypínám služby a časovače..."
    systemctl --user stop sysext-update.timer sysext-update.service 2>/dev/null || true
    systemctl --user disable sysext-update.timer 2>/dev/null || true

    sudo systemctl stop sysext-creator-heal.service 2>/dev/null || true
    sudo systemctl disable sysext-creator-heal.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/sysext-creator-heal.service
    sudo rm -f /usr/local/bin/sysext-creator-healer
    sudo systemctl daemon-reload

    sudo rm -f /etc/systemd/system/sysext-creator-deploy.path
    sudo rm -f /etc/systemd/system/sysext-creator-deploy.service

    echo ""
    read -p "Do you want to remove ALL installed raw images in /var/lib/extensions? (yes/no): " remove_all
    if [[ "$remove_all" == "yes" ]]; then
        echo "=> Odstraňuji VŠECHNY RAW obrazy..."
        sudo rm -f /var/lib/extensions/*.raw
    else
        echo "=> Odstraňuji pouze Sysext-Creator..."
        sudo rm -f /var/lib/extensions/sysext-creator-fc*.raw
        sudo rm -f /var/lib/extensions/sysext-creator.raw 2>/dev/null || true
    fi

    echo "=> Odpojuji systémová rozšíření..."
    sudo systemd-sysext refresh

    echo "--------------------------------------------------------"
    echo "✅ Sysext-Creator byl kompletně odstraněn."
    echo "--------------------------------------------------------"
    exit 0
fi

# ==========================================
# INSTALL LOGIKA
# ==========================================
echo "🚀 Aktivuji Sysext-Creator z RAW obrazu..."

if [ ! -f "/usr/bin/sysext-creator" ]; then
    echo "❌ Chyba: Sysext-Creator není připojen."
    echo "Ujistěte se, že je obraz ve složce /var/lib/extensions a spusťte 'sudo systemd-sysext refresh'."
    exit 1
fi

echo "=> Načítám systemd služby a aktivuji hlídání složky (daemon)..."
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

echo "=> Nastavuji automatické aktualizace..."
systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

echo "=> Obnovuji mezipaměť ikon a zástupců plochy..."
if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
    echo "✅ KDE menu aktualizováno."
fi
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database ~/.local/share/applications || true
fi

echo "=> Kontroluji Distrobox kontejner..."
/usr/bin/sysext-creator list > /dev/null 2>&1 || true

echo "=> Instaluji Auto-Healer (záchranný modul pro přežití upgradu OS)..."

sudo tee /usr/local/bin/sysext-creator-healer > /dev/null << 'EOF'
#!/bin/bash
HOST_VER=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')
RAW_FILE="/var/lib/extensions/sysext-creator-fc${HOST_VER}.raw"

if [ -f "$RAW_FILE" ]; then
    exit 0
fi

echo "🚨 Sysext-Creator pro Fedoru $HOST_VER nenalezen! Spouštím auto-heal..."

# Úklid starých verzí
rm -f /var/lib/extensions/sysext-creator.raw 2>/dev/null || true
find /var/lib/extensions/ -maxdepth 1 -name "sysext-creator-fc*.raw" -not -name "sysext-creator-fc${HOST_VER}.raw" -delete 2>/dev/null || true

PKG="sysext-creator"
if grep -iq "kinoite" /etc/os-release || [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]]; then
    PKG="sysext-creator-kinoite"
fi

podman run --rm --privileged \
    -v /var/lib/extensions:/ext_out \
    "registry.fedoraproject.org/fedora:${HOST_VER}" \
    /bin/bash -c " \
        dnf install -y dnf-plugins-core erofs-utils cpio selinux-policy-targeted && \
        dnf copr enable -y nadmartin/sysext-creator && \
        dnf install -y --downloadonly --downloaddir=/tmp/pkg $PKG && \
        mkdir -p /tmp/rootfs/usr/lib/extension-release.d && \
        echo \"ID=fedora\" > /tmp/rootfs/usr/lib/extension-release.d/extension-release.sysext-creator && \
        echo \"VERSION_ID=\${HOST_VER}\" >> /tmp/rootfs/usr/lib/extension-release.d/extension-release.sysext-creator && \
        rpm2cpio /tmp/pkg/*.rpm | cpio -idmv -D /tmp/rootfs 2>/dev/null && \
        mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 --file-contexts=/etc/selinux/targeted/contexts/files/file_contexts /ext_out/sysext-creator-fc\${HOST_VER}.raw /tmp/rootfs >/dev/null
    "

systemd-sysext refresh
EOF

sudo chmod +x /usr/local/bin/sysext-creator-healer

sudo tee /etc/systemd/system/sysext-creator-heal.service > /dev/null << 'EOF'
[Unit]
Description=Sysext-Creator Auto-Healer (OS Upgrade Survival)
After=network-online.target podman.socket
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sysext-creator-healer
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-heal.service

echo "✅ Auto-Healer je aktivní. Nástroj nyní přežije upgrady systému."
echo "--------------------------------------------------------"
echo "✅ Aktivace dokončena!"
echo "📦 Nyní můžete Sysext-Creator spustit z menu aplikací."
echo "--------------------------------------------------------"
