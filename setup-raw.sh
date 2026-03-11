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

echo "=> Kontroluji Distrobox kontejner..."
/usr/bin/sysext-creator list > /dev/null 2>&1 || true

echo "=> Instaluji Auto-Healer (záchranný modul pro přežití upgradu OS)..."

sudo tee /usr/local/bin/sysext-creator-healer > /dev/null << 'EOF'
#!/bin/bash
HOST_VER=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2 | tr -d '"')

# Seznam balíčků
PKG="sysext-creator"
if grep -iq "kinoite" /etc/os-release || [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]]; then
    PKG="sysext-creator-kinoite sysext-creator iio-sensor-proxy python-pyqt6-rpm-macros python3-pyqt6 python3-pyqt6-base python3-pyqt6-sip qt6-qtremoteobjects qt6-qtsensors qt6-qttools-libs-designer qt6-qttools-libs-help"
fi

podman run --rm --privileged \
    -v /var/lib/extensions:/ext_out \
    "registry.fedoraproject.org/fedora:${HOST_VER}" \
    /bin/bash -x -c "
        mkdir -p /tmp/pkg /tmp/rootfs/usr/lib/extension-release.d && \
        dnf install -y erofs-utils cpio selinux-policy-targeted --setopt=install_weak_deps=False && \
        dnf copr enable -y nadmartin/sysext-creator && \
        dnf download --destdir=/tmp/pkg $PKG distrobox && \
        echo 'ID=fedora' > /tmp/rootfs/usr/lib/extension-release.d/extension-release.sysext-creator-fc${HOST_VER} && \
        echo 'VERSION_ID=${HOST_VER}' >> /tmp/rootfs/usr/lib/extension-release.d/extension-release.sysext-creator-fc${HOST_VER} && \
        cd /tmp/rootfs && \
        for f in /tmp/pkg/*.rpm; do
            rpm2cpio \$f | cpio -idmv
        done && \
        mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 \
            --file-contexts=/etc/selinux/targeted/contexts/files/file_contexts \
            /ext_out/sysext-creator-fc${HOST_VER}.raw /tmp/rootfs
    "
systemd-sysext refresh

EOF

sudo chmod +x /usr/local/bin/sysext-creator-healer

sudo tee /etc/systemd/system/sysext-creator-heal.service > /dev/null << 'EOF'
[Unit]
Description=Sysext-Creator Auto-Healer (Background)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sysext-creator-healer
EOF
sudo tee /etc/systemd/system/sysext-creator-heal.timer > /dev/null << 'EOF'
[Unit]
Description=Spouští Healer 2 minuty po startu systému

[Timer]
# Počká 2 minuty po naběhnutí systému
OnBootSec=2min
Unit=sysext-creator-heal.service

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-heal.service

sudo tee /etc/yum.repos.d/_copr_nadmartin-sysext-creator.repo > /dev/null << 'EOF'
[copr:copr.fedorainfracloud.org:nadmartin:sysext-creator]
name=Copr repo for sysext-creator owned by nadmartin
baseurl=https://download.copr.fedorainfracloud.org/results/nadmartin/sysext-creator/fedora-$releasever-$basearch/
type=rpm-md
skip_if_unavailable=True
gpgcheck=1
gpgkey=https://download.copr.fedorainfracloud.org/results/nadmartin/sysext-creator/pubkey.gpg
repo_gpgcheck=0
enabled=1
enabled_metadata=1
exclude=*.src*
EOF
if [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* ]] || pgrep -x plasmashell > /dev/null; then
    echo "=> KDE environment detected. Installing dependencies for GUI python3-pyqt6 as a sysext image..."
    sysext-creator install python3-pyqt6

    if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
    echo "✅ KDE menu aktualizováno."
    fi
fi
echo "✅ Auto-Healer je aktivní. Nástroj nyní přežije upgrady systému."
echo "--------------------------------------------------------"
echo "✅ Aktivace dokončena!"
echo "📦 Nyní můžete Sysext-Creator spustit z menu aplikací."
echo "⏳ Spouštím automatickou diagnostiku a zkoušku ohněm (E2E Test)..."
echo "Během testu se na pozadí vytvoří a zase smažou zkušební balíčky."

# Spuštění samotného testu
test-sysext-creator

echo -e "\nPokud testy prošly zeleně, systém je připraven k použití."
echo "--------------------------------------------------------"
echo -e "\n================================================================================"
echo "✅ Instalace Sysext-Creator (v2.0) byla úspěšně dokončena!"
echo "================================================================================"
