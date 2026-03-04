# use version 1.0 new versions are broken for now
💎 Sysext-Creator (v1.2.0)
A professional management tool for system extensions (systemd-sysext) on Fedora Atomic desktops (Silverblue, Kinoite, Aurora). It allows you to install RPM packages directly into your immutable system without the overhead of rpm-ostree layering or the need for a reboot.

✨ Key Features (v1.2.0)
Pure Podman Architecture: Completely removed Distrobox dependency. Baking now takes place in an isolated, lightweight container managed directly via Podman.

KDE Dolphin Integration: Install downloaded RPM files with a single click using the "Install as System Extension" context menu action.

Self-Upgrade System: The tool can now update itself directly from GitHub using the self-upgrade command.

N+1 Version Readiness: During every build, the tool automatically prepares images for both the current and the next Fedora version, ensuring a seamless transition after a major OS upgrade.

EROFS Engine: Utilizes the high-performance EROFS filesystem for maximum speed and disk space efficiency.

Clean System Philosophy: Extensions exist only as a virtual layer in /usr, leaving no permanent trace in the base OS image.

🚀 Quick Start
Version 1.2.0 introduces a fully automated setup process:

1. Download and Setup
Clone the repository and run the setup script. This will configure the Podman worker and deploy the tool into your system.

```Bash
git clone https://github.com/namar66/sysext-creator.git
cd sysext-creator
chmod +x *.sh
./sysext-setup.sh
```
2. Ready to Go!
The tool is now integrated into your OS. You can safely delete the cloned folder. Start using the sysext-creator command globally in your terminal or use the right-click menu in Dolphin.

🛠️ Usage
Terminal (CLI)

# Install a package from repositories
```Bash
sysext-creator install vivaldi
```
# Update all installed extensions
```Bash
sysext-creator update
```
# Check for available updates without installing
```Bash
sysext-creator update-check
```

# Remove an extension
```Bash
sysext-creator rm htop
```
# Update Sysext-Creator itself
sysext-creator self-upgrade
Graphical Interface (KDE Dolphin)
Locate any .rpm file in Dolphin.

Right-click the file and select "Install as System Extension".

📂 Project Structure
`sysext-creator.sh` – The host-side orchestrator (The Conductor).

`sysext-creator-core.sh` – The build logic running inside the container (The Worker).

`sysext-setup.sh` – Podman container initialization and first-time deployment.

`build-bundle.sh` – Generates system images for the tool itself (The Baker).

`sysext-install.desktop` – KDE Dolphin context menu integration.

🗺️ Roadmap (v1.3)
[ ] KCM Module: Native control panel integrated into KDE System Settings.

[ ] Desktop Notifications: Stay informed about available extension updates via the system tray.

⚖️ License
GPLv2 – Created by Martin Naď (2026)
