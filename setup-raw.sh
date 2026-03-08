#!/bin/bash
set -euo pipefail

echo "🚀 Aktivuji Sysext-Creator z RAW obrazu..."

# 1. Zkontrolujeme, jestli je RAW obraz připojený
if [ ! -f "/usr/bin/sysext-creator" ]; then
    echo "❌ Chyba: Sysext-Creator není připojen."
    echo "Ujistěte se, že je sysext-creator.raw ve složce /var/lib/extensions a spusťte 'sudo systemd-sysext refresh'."
    exit 1
fi

# 2. Registrace démona do Systemd
echo "=> Načítám systemd služby a aktivuji hlídání složky (daemon)..."
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator-deploy.path

# 3. Registrace uživatelského timeru pro automatické aktualizace
echo "=> Nastavuji automatické aktualizace..."
systemctl --user daemon-reload
systemctl --user enable --now sysext-update.timer

# 4. Aktualizace grafického rozhraní (KDE/GNOME)
echo "=> Obnovuji mezipaměť ikon a zástupců plochy..."
# Pro KDE Plasma
if command -v kbuildsycoca6 &> /dev/null; then
    kbuildsycoca6 &>/dev/null || true
    echo "✅ KDE menu aktualizováno."
fi

# Obecný update desktop databáze (GNOME atd.)
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database ~/.local/share/applications || true
fi

# 5. Inicializace kontejneru (pokud ještě neexistuje)
echo "=> Kontroluji Distrobox kontejner..."
# Tady jen zavoláme samotný wrapper, který už v sobě má funkci 'check_container'
# Běžící 'sysext-creator list' potichu ověří/vytvoří kontejner, aniž by něco rozbil
/usr/bin/sysext-creator list > /dev/null 2>&1 || true

echo "--------------------------------------------------------"
echo "✅ Aktivace dokončena!"
echo "📦 Nyní můžete Sysext-Creator spustit z menu aplikací."
echo "--------------------------------------------------------"
