#!/bin/bash
#
# Sysext-Creator
# Copyright (C) 2026 Martin Naď (nebo Přezdívka)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
if (( $# < 1 )); then
	echo "Usage: $0 install <name of package >  <for updates just 'update''>" >&2
	exit 1
fi

privileged="sudo"

EXT_DIR="/var/lib/extensions"
# Rychlý test, jestli s takto nastavenými právy dokážeme zapisovat do cílové složky
# Zeptáme se rovnou hostitele, jestli máme do složky právo zápisu

if distrobox-host-exec test -w "$EXT_DIR" ; then
    echo "=> Máme právo zápisu do $EXT_DIR!"
    privileged2=""
else
    echo "=> Nemáme právo zápisu do $EXT_DIR, použijeme sudo."
    privileged2="sudo "
fi

# Ochrana: Jsou nainstalované všechny potřebné nástroje?
REQUIRED_CMDS="mksquashfs cpio rpm2cpio repoquery"

for cmd in $REQUIRED_CMDS; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "❌ Kritická chyba: V kontejneru chybí nástroj '$cmd'!" >&2
        echo "=> Spusť v kontejneru následující příkaz pro instalaci závislostí:" >&2
        echo "   sudo dnf install -y squashfs-tools cpio dnf-utils" >&2
        exit 1
    fi
done


Host_system=$(distrobox-host-exec cat /etc/os-release | grep VERSION_ID= | sed -E "s/VERSION_ID=//")
guest_system=$(cat /etc/os-release | grep VERSION_ID= | sed -E "s/VERSION_ID=//")
if [ "$Host_system" != "$guest_system" ] ; then
echo "Not match HOST and GUEST, run same version of Fedora inside distrobox"
exit 1
fi

input1="$1"

# Ochrana: Je složka skutečně namountovaná z hostitele?
if ! mountpoint -q "$EXT_DIR"; then
    echo "❌ Kritická chyba: Složka $EXT_DIR není připojena jako svazek!" >&2
    echo "=> Ujisti se, že jsi kontejner spustil s parametrem:" >&2
    echo "   --volume /var/lib/extensions:/var/lib/extensions:rw" >&2
    exit 1
fi

if [ "$input1" == "install" ] ; then
if [ -z "$2" ]; then
        echo "Chyba: K příkazu 'install' musíš zadat jméno balíčku!" >&2
        exit 1
fi
Apps="$2"
fi

if  [ "$input1" == "update" ] ; then
Apps=$(distrobox-host-exec ls "$EXT_DIR" |grep .raw | sed -E 's/-[0-9].*//' | tr '\n' ' ')
echo "Hledám aktualizace pro: $Apps"
fi

if [ "$input1" == "rm" ] ; then
    if [ -z "$2" ]; then
        echo "❌ Chyba: K příkazu 'rm' musíš zadat jméno balíčku!" >&2
        exit 1
    fi
    Apps="$2"
    echo "=> Odstraňuji obraz aplikace $Apps..."
    $privileged2 rm -f "$EXT_DIR/${Apps}-"*.raw

    echo "=> Aktualizuji systémové cesty..."
    # Znovu načteme sysext, aby aplikace okamžitě zmizela z běžícího systému
    distrobox-host-exec $privileged systemd-sysext refresh

    echo "✅ Hotovo: $Apps byl úspěšně odstraněn ze systému."
    exit 0  # Správný ukončovací kód pro úspěch!
fi


for tarball in $Apps;do
unset RAW_OUT
unset onserver
unset downloaded
RAW_OUT=$(distrobox-host-exec rpm-ostree install --dry-run "$tarball" 2>/dev/null)
#onserver=$(echo "$RAW_OUT" | sed -n '/packages:/,$p' | grep "$tarball"  | awk -F "-*.x86_64" '{print $1}' | awk -F "-*.noarch" '{print $1}' | awk -F"$tarball-" '{print $NF}' | head -n1 | cut -c3-)
onserver=$(dnf repoquery --latest-limit=1 --queryformat "%{version}-%{release}" "$tarball" 2>/dev/null)
if [ "$tarball" == "vivaldi-stable" ]; then
downloaded="$(find $EXT_DIR/$tarball-*.raw | awk -F'-*.raw' '{print $1}' | awk -F"$tarball-" '{print $NF}')"
else
downloaded="$(find $EXT_DIR/$tarball-*.fc$Host_system.raw | awk -F'-*.raw' '{print $1}' | awk -F"$tarball-" '{print $NF}')"
fi
echo "dostupnost aktualizace pro $tarball"
echo "dostupná verze: $onserver"
echo "nainstalovaná veze: $downloaded"
  if [ "$downloaded" != "$onserver" ] ; then
  echo "=> Vytvářím dočasné pracovní prostředí..."
  WORKDIR=$(mktemp -d)
  trap 'rm -rf "$WORKDIR"' EXIT
  mkdir -p "$WORKDIR/usr/lib/extension-release.d"
  mkdir -p "$WORKDIR/rpms"

PACKAGES=$(echo "$RAW_OUT" | sed -n '/packages:/,$p' | grep -E '^  [a-zA-Z0-9]' | awk '{print $1}' | sed -E 's/-[0-9].*//' | tr '\n' ' ')
dnf download $PACKAGES --refresh --forcearch=x86_64 --destdir="$WORKDIR/rpms" 2>/dev/null

# ---- ZÁCHRANNÁ BRZDA PROTI PRÁZDNÉMU OBRAZU ----
# Spočítáme, kolik .rpm souborů se skutečně stáhlo
#rm -rf "$WORKDIR/rpms/" #test
RPM_COUNT=$(ls -1 "$WORKDIR/rpms/"*.rpm 2>/dev/null | wc -l)

if [ "$RPM_COUNT" -eq 0 ]; then
    echo "❌ Chyba: Nepodařilo se stáhnout balíčky pro '$tarball'!"
    echo "=> Přeskakuji a jdu na další aplikaci..."
    rm -rf "$WORKDIR"  # Musíme po sobě uklidit ten mktemp!
    continue           # Skočíme na další průběh cyklu for
fi


echo "=> Rozbaluji RPM balíčky..."
for rpm in "$WORKDIR/rpms/"*.rpm; do
    rpm2cpio "$rpm" | cpio -idm -D "$WORKDIR" --quiet 2>/dev/null
done
rm -rf "${WORKDIR:?}/rpms"
RELEASE_FILE="$WORKDIR/usr/lib/extension-release.d/extension-release.${tarball}-${onserver}"
cat <<EOF > "$RELEASE_FILE"
ID=fedora
VERSION_ID=$Host_system
EOF
# 5.5 Extrakt konfigurací pro hostitele
if [ -d "$WORKDIR/etc" ]; then
 if [ "$input1" == "install" ] ; then
    if [ "$tarball" == "vivaldi-stable" ]; then
    echo "nepotřebné /etc pro $tarball mažu"
    else
    echo "=> Balíček obsahuje globální konfigurace v /etc. Kopíruji na hostitele..."
    # Zabalíme obsah etc a přes distrobox-host-exec ho rozbalíme v hostitelském /etc
    tar -czf "$WORKDIR/etc-config.tar.gz" -C "$WORKDIR/etc" .
    distrobox-host-exec sudo tar -xzf "$WORKDIR/etc-config.tar.gz" -C /etc/ --skip-old-files
    echo "=> Konfigurace úspěšně zkopírovány do /etc/ na hostiteli."
    fi
    rm -rf "${WORKDIR:?}/etc"
 fi
fi
echo "=> Vytvářím raw obraz (SquashFS + zstd komprese)..."

OUTPUT_RAW="${tarball}-${onserver}.raw"
mksquashfs "$WORKDIR" "$OUTPUT_RAW" -all-root -noappend -comp zstd -Xcompression-level 19 -b 1048576 > /dev/null

if [ -n "$(ls "$EXT_DIR/${tarball}-"*.raw 2>/dev/null)" ]; then
    echo "mažu staré .raw"
    distrobox-host-exec $privileged systemd-sysext unmerge
    if [ "$tarball" == "vivaldi-stable" ]; then
    distrobox-host-exec $privileged2 rm -f "$EXT_DIR/${tarball}-"*.raw
    else
    distrobox-host-exec $privileged2 rm -f "$EXT_DIR/${tarball}-"*.fc$Host_system.raw
    fi
fi
echo "nahravam novou verzi"
distrobox-host-exec $privileged2 mv "$OUTPUT_RAW" "$EXT_DIR/"
distrobox-host-exec $privileged systemd-sysext refresh
rm -rf "$WORKDIR"

else
  printf "$tarball is already installed and updated\n"
fi

done
