# Sysext Creator (v3.1)

![License](https://img.shields.io/badge/license-GPLv2-blue.svg)
![Platform](https://img.shields.io/badge/platform-Fedora_Atomic-3870b2.svg)
![Experience](https://img.shields.io/badge/user-Linux__admin-black?logo=linux)

# 🚀 Sysext Creator Pro

The Ultimate GUI/CLI Suite for Managing **`systemd-sysext`** and Layered Packages on **Atomic Fedora** (Kinoite/Silverblue/Sericea).

`sysext-creator-pro` provides a safe, seamless, and user-friendly experience for adding layered applications to immutable Fedora systems without compromising the core OS integrity or requiring a full ostree commit. It manages everything from downloading DNF packages to creating highly-compressed EROFS images, handling activation, updates, and removals with an enterprise-grade focus on security and best practices.

* note: Make sure your system is fully up to date.
## 🌟 Key Features

### 🖥️ GUI (Graphical User Interface)
* **Real-time DNF Search:** Blazing fast search and filtering of >60,000 packages directly from the Fedora repos.
* **Transaction Queue:** Add packages to a "shopping cart" before building the final image.
* **Extension Management:** View installed/cached system extensions, their status (Active/Inactive), and detailed package lists (Requested vs. Full Dependencies).
* **Smart Doctor:** Run deep, privileged (polkit) diagnostics to identify `/etc` symlink status, OS overwrites, or cross-extension collisions.
* **System Integration:** Installs to your local `~/.local` directory for full persistence and integration with the application menu (tested on KDE).

### 🛠️ CLI Builder (under the hood)
* **Atomic Operation:** Builds in a clean, throwaway Toolbox container without polluting your host.
* **Smart Pruning:** Automatically prunes shadowed files already present on the host OS to reduce image size (saves ~10% disk space).
* **Dependency Tracking:** Generates detailed `manifest.txt`, `version.txt`, and full dependency trees (`deps.txt`) for auditability.
* **EROFS Compression:** Uses highly efficient `mkfs.erofs` for smaller, faster images.

## 🏗️ Architecture

The suite is built with a strong focus on security and the XDG Base Directory Specification:

1.  **GUI (`sysext-gui-pro`):** A standard Qt6 application. It communicates with the system via `pkexec` only when administrative actions (deployment, removal, diagnostics) are required.
2.  **Builder (`sysext-creator-builder.py`):** Operates entirely within a Toolbox container. It fetches packages, unpacks RPMs, prunes duplicates, and creates the EROFS raw image into your local cache directory.
3.  **Local XDG Compliance:**
    * **Cache:** Built `.raw` images are temporarily stored in `~/.cache/sysext-creator`.
    * **Executables & Desktop:** Installed locally to `~/.local/bin` and `~/.local/share/applications`.

## 📦 Prerequisites

* Fedora Atomic (Kinoite, Silverblue, etc.).
* Toolbox installed.
* Polkit (`pkexec`) capability.
* PyQt6, `erofs-utils`, and `systemd-dissect` on the host.

## 🚀 Installation

Ensure you have your icon named `sysext-creator-icon.png` in the source directory.

```bash
# 1. Clone the repository
git clone https://github.com/namar66/sysext-creator.git
cd sysext-creator

# 2. Grant execution permissions to the scripts and the installer
chmod +x sysext-gui-pro.py sysext-creator-builder.py sysext-doctor.py install.sh

# 3. Run the installer
./install.sh
```

A new "Sysext Creator Pro" entry will appear in your application menu.

## 📜 Uninstallation

We are XDG compliant and leave your core system untouched. To remove the local user installation:

```bash
rm -f ~/.local/bin/{sysext-gui-pro,sysext-creator-builder.py,sysext-doctor.py}
rm -f ~/.local/share/applications/sysext-creator.desktop
rm -f ~/.local/share/icons/hicolor/128x128/apps/sysext-creator.png
rm -rf ~/.cache/sysext-creator
```

---

*This project is built by developers who understand that an immutable OS shouldn't mean a locked-down experience. Manage your layers responsibly.*
