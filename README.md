# Sysext Creator (v3.0)

![License](https://img.shields.io/badge/license-GPLv2-blue.svg)
![Platform](https://img.shields.io/badge/platform-Fedora_Atomic-3870b2.svg)

A robust, atomic-first system extension manager for immutable Linux distributions (Fedora Silverblue, Kinoite, CoreOS). 

Sysext Creator allows you to cleanly overlay RPM packages (and their precise dependencies) onto your read-only root filesystem using `systemd-sysext` and `systemd-confext`.

## ✨ Key Features

* **Host-Aware Dependency Resolution:** Uses `rpm-ostree install --dry-run` to calculate the exact delta of missing packages. It never downloads bloated dependencies your host OS already has.
* **Isolated Build Environment:** Downloads and extracts RPMs safely inside a Toolbox container (`dnf`, `rpm2cpio`), leaving your host OS completely untouched during the build phase.
* **Rootless Operation via IPC:** The backend daemon runs as root, but your user tools (GUI/CLI) communicate with it securely via a **Varlink UNIX socket**. No annoying Polkit password prompts required for daily usage.
* **Smart `noexec` Workaround:** Automatically detects executable scripts in `/etc` (like SDDM setups), relocates them to `/usr/libexec`, and generates `tmpfiles.d` symlinks to bypass `systemd-confext` execution restrictions.
* **SELinux & Permissions Guard:** Enforces `root:root` ownership and injects correct host SELinux contexts during the `mkfs.erofs` image creation to prevent boot hangs.
* **PyQt6 GUI & CLI:** Comes with a full-featured graphical interface and a scriptable command-line tool.
* **Auto-Updater:** A systemd-timer-driven background service that keeps your layered packages up to date.

## 🏗️ Architecture

1.  **Daemon (`sysext-creator-daemon.py`):** The privileged backend. It strictly handles mounting, deploying `.raw` files to `/var/lib/extensions`, and refreshing `systemd-sysext`. Hardened via systemd directives.
2.  **Builder (`sysext-creator-builder.py`):** The isolated engine running inside a Toolbox container.
3.  **Clients (`sysext-creator-gui.py`, `sysext-cli.py`):** Unprivileged frontends for user interaction.

## 🚀 Installation

1. Clone this repository to a temporary directory:
   ```bash
   git clone [https://github.com/YOUR_USERNAME/sysext-creator.git](https://github.com/YOUR_USERNAME/sysext-creator.git)
   cd sysext-creator
   ```
2. Run the automated bootstrap installer:
```Bash
chmod +x install.sh
./install.sh
```
Note: The installer will automatically spin up a Toolbox container, build an initial system extension containing required Python dependencies (python3-varlink, python3-pyqt6), and set up the systemd daemon.
💻 Usage
Graphical Interface
Simply launch Sysext Creator from your desktop application menu.
# Install a new package (e.g., htop)
Note: sysext-cli install <image_name>  <package_name>  <package_>
```Bash
sysext-cli install htop htop
```
# List active extensions
```Bash
sysext-cli list
```
# Remove an extension
```Bash
sysext-cli remove htop
```
🛠️ Diagnostics
If you suspect an extension is conflicting with base system RPMs, use the built-in diagnostic tool (requires sudo):
```Bash
sudo python3 /opt/sysext-creator/sysext-doctor.py
```
📄 License
This project is licensed under the GPLv2 License - see the LICENSE file for details.
