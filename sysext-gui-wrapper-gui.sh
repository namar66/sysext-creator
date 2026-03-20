#!/bin/bash
set -euo pipefail

check_gui_deps() {
    if rpm -q python3-pyqt6 >/dev/null 2>&1; then
        return 0
    fi

    if ls /var/lib/extensions/python3-pyqt6*.raw >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

if ! check_gui_deps; then
    echo "======================================================================"
    echo "📦 První spuštění GUI: Stahuji a vytvářím rozšíření PyQt6..."
    echo "======================================================================"

    sysext-cli install python3-pyqt6 python3-pyqt6
    sleep 5

    # Závěrečná kontrola
    if ! check_gui_deps; then
        echo "❌ Kritická chyba: Nepodařilo se vytvořit .raw obraz pro PyQt6."
        echo "Zkontrolujte logy nebo to zkuste ručně: sysext-creator install python3-pyqt6"
        read -p "Stiskněte Enter pro ukončení..."
        exit 1
    fi

    echo "✅ Grafické prostředí úspěšně připraveno!"
fi

# Pokud jsme tady, závislosti existují. Předáme řízení přímo Python GUI skriptu.
exec sysext-gui "$@"
