# 📦 Sysext-Creator: The Atomic App Store

**Sysext-Creator** is a native, container-backed package manager and GUI App Store designed specifically for **Fedora Atomic Desktops** (Kinoite, Silverblue, Sericea, etc.). 

It allows you to install, update, and remove standard RPM packages as **Systemd System Extensions (`systemd-sysext`)** without layering them via `rpm-ostree` and without requiring system reboots.

## ✨ Key Features

* **Zero Host Contamination:** Packages are downloaded, resolved, and packed into EROFS `.raw` images entirely inside a throwaway Distrobox container.
* **Rootless GUI Experience:** The PyQt6 graphical interface runs as a standard user. Privilege escalation is handled securely via a `systemd.path` daemon.
* **Native KDE Dolphin Integration:** Right-click any downloaded `.rpm` file and select *"Install as System Extension"*.
* **SELinux Ready:** Images are built with native host SELinux file contexts, ensuring 100% compatibility with Fedora's security policies.
* **Auto-Updates:** Includes a background systemd user timer that keeps all your extensions up to date with desktop notifications.
* **Bilingual:** GUI automatically adapts to English or Czech based on your system locale.

## 🏗️ How It Works

1. **Frontend (`sysext-gui` / CLI):** Runs as a standard user.
2. **Backend Container:** A Fedora distrobox spins up, downloads RPMs, and packs them into a compressed EROFS `.raw` image. 
3. **Deployment Daemon:** A privileged root daemon detects the new file, moves it to `/var/lib/extensions`, and triggers a `systemd-sysext refresh`.

## 🚀 Quick Installation (Standalone RAW)

Sysext-Creator is distributed as a system extension itself!

1. Download the latest `sysext-creator.raw` from the Releases page.
2. Move it to the extensions directory:
```bash
   sudo mkdir -p /var/lib/extensions
   sudo cp sysext-creator.raw /var/lib/extensions/
   sudo systemd-sysext refresh
 ```
3.Run the bootstrap setup (available directly from the image):

```Bash
sysext-creator-setup
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
# Stop services
```Bash
systemctl --user stop sysext-update.timer sysext-update.service
sudo systemctl disable --now sysext-creator-deploy.path
```
# Remove the extension
```Bash
./sysext-creator-setup.sh uninstall
sudo systemd-sysext refresh
```
* 🤝 License
* GPLv2
