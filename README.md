# Sysext-Creator for Fedora (Kinoite/Silverblue)

Sysext-Creator is a fully automated Bash script for managing additional applications on immutable systems (Fedora Kinoite, Silverblue) using `systemd-sysext` technology. 

The tool combines the dependency resolution logic of the host system (via `rpm-ostree dry-run`) with the flexibility of containers (Distrobox) to create clean, custom-tailored SquashFS images without modifying the base system image.

You can use my original script `sysext-creator.sh` or the refactored version created by GitHub AI `sysext-image-creator-fixed.sh`. Both versions are tested and work perfectly for me. If you find an issue, please let me know!

---

## ⚠️ Important Warnings

* **Early Stages:** THIS SCRIPT IS IN EARLY STAGES. Use at your own risk.
* **Active Extensions:** Do not deactivate systemd extensions if they are being used by critical programs installed within them (Desktop Environments, databases, etc.).
* **System Files Override:** Because `systemd-sysext` uses OverlayFS, installing base system packages (like `dnf` or `glibc`) via this script can override critical host system files. This may lead to system crashes or make your Fedora **unbootable**. Use this tool primarily for standalone applications and standard CLI tools.

### 🚑 How to recover an unbootable system
If you accidentally create a problematic image and your system refuses to boot, you don't need to reinstall your OS. Just follow these steps:
1. Reboot your PC and wait for the **GRUB menu** to appear.
2. Select your default Fedora entry and press **`e`** to edit the boot parameters.
3. Find the line starting with `linux` (or `linuxefi`) and append the following parameter to the very end of that line:
   `systemd.mask=systemd-sysext.service`
4. Press **`Ctrl+X`** or **`F10`** to boot.

Your system will now boot normally with all sysext images temporarily disabled. You can then open your terminal, delete the broken `.raw` file from `/var/lib/extensions/`, and reboot again.

---

## ✨ Features
* **Install (`install`):** Automatically calculates exact dependencies against the host system and downloads only what is strictly necessary.
* **Update (`update`):** Detects installed `.raw` images and updates them in bulk (ideal for background execution via a Systemd Timer).
* **Remove (`rm`):** Safely deletes the image from the disk and immediately applies changes to the running system.
* **Config Extraction:** Automatically moves global configuration files from `/etc` inside the RPM packages directly to the host system during installation.

## ⚙️ Requirements
* **Host System:** Fedora Kinoite, Silverblue, Sericea, or Onyx.
* **Container:** Distrobox container sharing the same Fedora version as the host.
* **Mount Point:** The extensions folder (`/var/lib/extensions`) must be mounted into the container via bind mount (`--volume /var/lib/extensions:/var/lib/extensions:rw`).
* **Container Packages:** `squashfs-tools`, `cpio`, `dnf-utils`.

## 📦 Container Setup (First Time Only)
If you are setting this up on a fresh system, here are the exact commands to create the required Distrobox container and install the necessary tools inside it:

for pre-installation distrobox you can use `single-package-sysext.sh` for create sysext from local downloaded *.rpm  after that install distrobox
with "distrobox-enter -n sysext-box -- sysext-creator install distrobox" and delete "/var/lib/distrobox-1.2.3" folder
```bash
chmod +x single-package-sysext.sh
./single-package-sysext.sh distrobox-1.2.3.rpm
```
* (Note: You can change sysext-box to any container name you prefer, with required parameter "--volume /var/lib/extensions:/var/lib/extensions:rw")
1. Create a Fedora container with the required volume mount
```bash
distrobox create --name sysext-box --image registry.fedoraproject.org/fedora-toolbox:latest --volume /var/lib/extensions:/var/lib/extensions:rw
```

2. Enter the container and install the required packages
```bash
distrobox enter sysext-box -- sudo dnf install -y squashfs-tools cpio dnf-utils
```

🚀 Installation
Move the script to a folder in your host's system path and make it executable:

```bash
mkdir -p ~/.local/bin
mv sysext-creator.sh ~/.local/bin/sysext-creator
chmod +x ~/.local/bin/sysext-creator
```
📖 Usage
The tool is designed to run inside the prepared Distrobox container. For seamless integration with the host, use distrobox-enter.

1. Install a new application:
```Bash
distrobox-enter -n sysext-box -- sysext-creator install mc
```
2. Bulk update all applications:
```Bash
distrobox-enter -n sysext-box -- sysext-creator update
```
3. Remove an application:
```Bash
distrobox-enter -n sysext-box -- sysext-creator rm mc
```
🔄 Automation (Auto-Update)
For maintenance-free operation, we recommend creating a user Systemd Timer (~/.config/systemd/user/) to periodically run sysext-creator update in the background.

📜 License
This project is licensed under the GNU General Public License v2.0 (GPLv2).
