### :warning:Warning
* THIS SCRIPT IS IN EARLY STAGES. Use at your own risk
* Do not deactivate systemd extensions if its being used by critical programs installed in it (Desktop Enviroments, databases, etc).
* ### ⚠️ Important Warning: Overriding System Files
Because `systemd-sysext` uses OverlayFS, installing base system packages (like `dnf` or `glibc`) via this script can override critical host system files. 
This may lead to system crashes or make your Fedora **unbootable**. Use this tool primarily for standalone applications and standard CLI tools.

#### 🚑 How to recover an unbootable system
If you accidentally create a problematic image and your system refuses to boot, you don't need to reinstall your OS. Just follow these steps:
1. Reboot your PC and wait for the **GRUB menu** to appear.
2. Select your default Fedora entry and press **`e`** to edit the boot parameters.
3. Find the line starting with `linux` (or `linuxefi`) and append the following parameter to the very end of that line:
   `systemd.mask=systemd-sysext.service`
4. Press **`Ctrl+X`** or **`F10`** to boot.

Your system will now boot normally with all sysext images temporarily disabled. You can then open your terminal, delete the broken `.raw` file from `/var/lib/extensions/`, and reboot again.


# sysext-creator
Bash script for creating sysext .raw image
# Sysext-Creator pro Fedoru (Kinoite/Silverblue)

Sysext-Creator je plně automatizovaný Bash skript pro správu dodatečných aplikací na immutabilních systémech (Fedora Kinoite, Silverblue) pomocí technologie `systemd-sysext`. 

Nástroj spojuje výpočetní logiku hostitelského systému (přes `rpm-ostree dry-run`) s flexibilitou kontejnerů (Distrobox) pro vytváření čistých, na míru šitých SquashFS obrazů bez nutnosti modifikovat základní obraz systému.

## ✨ Funkce
* **Instalace (`install`):** Automaticky vypočítá přesné závislosti aplikace vůči hostitelskému systému a stáhne pouze to nejnutnější.
* **Aktualizace (`update`):** Detekuje nainstalované `.raw` obrazy a hromadně je aktualizuje (ideální pro spouštění na pozadí přes Systemd Timer).
* **Odinstalace (`rm`):** Bezpečně smaže obraz z disku a okamžitě aplikuje změny do běžícího systému.
* **Extrakce konfigurací:** Automaticky přesouvá globální konfigurační soubory z `/etc` v RPM balíčcích přímo na při instalaci hostitelský systém.
* 
## ⚙️ Požadavky
* **Hostitelský systém:** Fedora Kinoite, Silverblue, Sericea nebo Onyx.
* **Kontejner:** Distrobox kontejner sdílející stejnou verzi Fedory jako hostitel.
* Složka pro rozšíření (`/var/lib/extensions`) připojená do kontejneru přes bind mount (`--volume /var/lib/extensions:/var/lib/extensions:rw`).
* **Balíčky v kontejneru:** `squashfs-tools`, `cpio`, `dnf-utils`

## 🚀 Instalace
Skript přesuňte do složky, kterou máte v systémové cestě, a povolte jeho spouštění:
```bash
mkdir -p ~/.local/bin
mv sysext-creator.sh ~/.local/bin/sysext-creator
chmod +x ~/.local/bin/sysext-creator

*Použití
*Nástroj se spouští uvnitř připraveného Distrobox kontejneru. Pro bezproblémové propojení s hostitelem doporučujeme používat distrobox-enter.

*1. Instalace nové aplikace:
*Bash
distrobox-enter -n nazev_kontejneru -- sysext-creator install mc

*2. Hromadná aktualizace všech aplikací:
*Bash
distrobox-enter -n nazev_kontejneru -- sysext-creator update

*3. Odstranění aplikace:
*Bash
distrobox-enter -n nazev_kontejneru -- sysext-creator rm mc

🔄 Automatizace (Auto-Update)
* Pro plně bezúdržbový chod doporučujeme vytvořit uživatelský Systemd Timer (~/.config/systemd/user/), který bude pravidelně spouštět sysext-creator update na pozadí.

📜 Licence
Tento projekt je licencován pod GNU General Public License v2.0 (GPLv2).
