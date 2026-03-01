#!/bin/bash

# Zkontrolujeme, jestli byl zadán argument s cestou k RPM
if [ -z "$1" ]; then
    echo "Použití: $0 <balicek.rpm>"
    exit 1
fi

RPM_FILE=$(realpath "$1")

if [ ! -f "$RPM_FILE" ]; then
    echo "Chyba: Soubor '$RPM_FILE' neexistuje!"
    exit 1
fi

# --- AUTOMATICKÁ DETEKCE METADAT ---
# Vytáhne jméno a verzi (např. krusader-2.9.0)
EXT_NAME=$(rpm -qp --queryformat '%{NAME}-%{VERSION}' "$RPM_FILE")

if [ -z "$EXT_NAME" ]; then
    echo "Chyba: Nepodařilo se načíst metadata z RPM."
    exit 1
fi

EXT_DIR="/var/lib/extensions/"

echo "🛠️  Vytvářím prostředí pro: $EXT_NAME"
mkdir $EXT_NAME
WORKDIR=$EXT_NAME
# 1. Rozbalení obsahu RPM balíčku
echo "📦 Rozbaluji RPM balíček..."
rpm2cpio "$RPM_FILE" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null

# 2. Vytvoření metadatového souboru pro systemd-sysext
echo "📝 Generuji metadata pro systemd-sysext..."

# Cesta musí být usr/lib/extension-release.d/extension-release.$EXT_NAME
mkdir -p $EXT_NAME/usr/lib/extension-release.d
cat <<EOF > $EXT_NAME/usr/lib/extension-release.d/extension-release.$EXT_NAME
ID=fedora
VERSION_ID=$(cat /etc/os-release | grep VERSION_ID= | sed -E "s/VERSION_ID=//")
EOF

# 3. Přesun do systémové složky (vyžaduje sudo)
echo "🚀 Instaluji rozšíření do $EXT_DIR..."

# Přesuneme rozbalenou strukturu 'usr' do cíle
sudo mv "$WORKDIR" "$EXT_DIR/"

# 4. Aktivace rozšíření
echo "🔄 Obnovuji systemd-sysext..."
sudo systemd-sysext refresh

echo "✅ Hotovo! Rozšíření $EXT_NAME je aktivní."
echo "Stav: $(systemd-sysext list | grep $EXT_NAME || echo 'Nenalezeno v seznamu')"
