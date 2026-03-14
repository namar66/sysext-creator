# 📦 Sysext-Creator (v2.0) still under development

**Advanced system extension manager for atomic Fedora systems (Kinoite & Silverblue).**

Sysext-Creator is a tool that allows you to install classic RPM packages and graphical applications using `systemd-sysext` technology. Instead of slow package layering via `rpm-ostree` which requires reboots, Sysext-Creator smartly wraps applications into fully isolated `.raw` images using **Podman**. 

Your base system remains 100% clean, untouched, and lightning fast.

---

## ✨ Key Features

* 🐳 **Pure Podman Architecture:** Everything runs securely in an isolated container in the background. No Distrobox required, and no polluting the host system.
* 🪄 **Auto-Healer:** Atomic systems suffer from old extensions breaking after a major OS upgrade (e.g., from Fedora 40 to 41). Sysext-Creator solves this! After a major update, it wakes up in the background, detects the new OS version specifically for the new host system.
* 🖥️ **Full-featured GUI (Kinoite):** A beautiful, native, and secure Qt6 graphical interface (no need to enter a password via `pkexec`).
* 🧩 **Local RPM Installation:** Downloaded an `.rpm` package from the internet? The tool smartly translates the path and installs it along with all necessary dependencies.

---

## 🚀 Installation
## Setup systemd-sysext
1. create extensions dir
```Bash
sudo install -d -m 0755 -o 0 -g 0 "/var/lib/extensions"
sudo restorecon -RFv "/var/lib/extensions"
```
2. activate systemd-sysext.service
```Bash
sudo systemctl enable systemd-sysext.service
```
## 🚀 Quick Installation (Standalone RAW)
Sysext-Creator is distributed as a system extension itself!

1. Download the latest `sysext-creator.raw` from the Releases page.
2. Move it to the extensions directory:
*(note be sure you have enabled systemd-sysext and properly created /var/lib/extensions)
```bash
   sudo cp sysext-creator.raw /var/lib/extensions/
   sudo systemctl restart systemd-sysext.service
 ```
3.Run the bootstrap setup (available directly from the image):

```Bash
sysext-creator-setup
sysext-creator update
```
## 🚀 Quick Installation (Standalone in $Home)
```Bash
git clone https://github.com/namar66/sysext-creator.git
cd sysext-creator
chmod +x *.sh
./sysext-creator-setup.sh
```
💻 CLI Usage

# Search for packages
```Bash
sysext-creator search <keyword>
```
# Install a package
```Bash
sysext-creator install <package_name>
```
* local downloaded rpm package
```Bash
sysext-creator install <_path_package_rpm>
```
# Update all extensions
```Bash
sysext-creator update
```
# Remove an extension
```Bash
sysext-creator rm <package_name>
```
# check installed sysext images
```Bash
sysext-creator doctor
```
🧹 Uninstallation
# Uninstall (Standalone RAW)
```Bash
sysext-creator-setup uninstall
```
# Uninstall (Standalone in $Home)
```Bash
./sysext-creator-setup.sh uninstall
```
* 🤝 License
* GPLv2
