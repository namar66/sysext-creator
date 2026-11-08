# Sysext Creator (v3.2.4)

![License](https://img.shields.io/badge/license-GPLv2-blue.svg)
![Platform](https://img.shields.io/badge/platform-Fedora_Atomic-3870b2.svg)
![Experience](https://img.shields.io/badge/user-Linux__admin-black?logo=linux)

# sysext-creator

`sysext-creator` is a tool for building, deploying, and managing `systemd-sysext` images on Fedora Atomic desktops (Silverblue, Kinoite).

It packages applications and their missing dependencies into compressed EROFS images that layer directly over `/usr` without modifying the underlying ostree deployment.

## Features

- **CLI-First Architecture**: `sysext-cli` handles building, deployment, updates, and removal; the Qt6 GUI (`sysext-gui-pro`) acts as an optional frontend.
- **Isolated Builds**: Downloads and unpacks RPMs inside an unprivileged Toolbox container (`sysext-builder`).
- **Host Dependency Resolution**: Uses `rpm-ostree install --dry-run` against the host system to identify and download only missing dependencies.
- **Smart Pruning**: Removes files from the build tree that already exist in the host's RPM database to prevent shadowing core system libraries.
- **Vendor Configuration Relocation**: Automatically moves standard vendor configurations (`/etc/udev/rules.d`, `/etc/sysctl.d`, `/etc/pam.d`, etc.) to `/usr/lib/` or `/usr/share/`.
- **Stateful `/etc` Handling**: Converts residual `/etc` application configurations into `tmpfiles.d` symlinks and tracks them for clean removal without leaving orphaned links.
- **SELinux Lifecycle**: Compiles package policies inside the container with `semodule -n`, applies file contexts to the EROFS filesystem, and loads/unloads modules into the host kernel upon layer deployment/removal.
- **Declarative System Triggers**: Automatically executes post-deployment tasks (`systemd-sysusers`, `glib-compile-schemas`, `update-mime-database`, `gtk-update-icon-cache`, `systemd-hwdb`).
- **Desktop Integration**: Automatically notifies KDE Plasma (`kbuildsycoca6`) and GNOME (`update-desktop-database`) to refresh application menus after layer state changes.
- **EROFS Compression**: Compresses images using `mkfs.erofs -zlz4`.

## Architecture

The project consists of four primary components:

1. **`sysext-cli.py` (`sysext-cli`)**: Unified backend and CLI interface. Dispatches containerized builds, requests Polkit privileges for deployment (`/var/lib/extensions`), manages manifests, and cleans up `/etc` symlinks and SELinux policies upon removal.
2. **`sysext-creator-builder.py`**: Runs inside the `sysext-builder` Toolbox container. Handles DNF downloads, RPM extraction via `rpm2cpio`, file pruning, vendor relocation, SELinux context labeling, and EROFS image generation.
3. **`sysext-doctor.py`**: Diagnostic utility that checks extension validity, OS version matching (`extension-release`), Fedora 45+ repo paths, and orphaned symlinks in `/etc`.
4. **`sysext-gui-pro.py`**: PyQt6 graphical interface providing repository package search, queue management, and visual status reporting by calling `sysext-cli`.

## Prerequisites

- Fedora Atomic Desktop (Kinoite, Silverblue, etc.)
- `toolbox`
- `python3`
- `erofs-utils` (installed in the toolbox container)
- `python3-pyqt6` (optional, for the GUI)

## Installation

Run `install.sh` to install all scripts, desktop files, and bash completion to your user environment (`~/.local`):

```bash
git clone https://github.com/namar66/sysext-creator.git
cd sysext-creator
chmod +x install.sh
./install.sh
```

Ensure `~/.local/bin` is present in your `$PATH`.

## Usage

### Command Line (`sysext-cli`)

**Build and deploy an extension:**
```bash
sysext-cli install krusader
# or specify multiple packages into a named layer:
sysext-cli install dev-tools git-lfs jq ripgrep
```

**List active extensions:**
```bash
sysext-cli list
```

**Update installed extensions:**
```bash
# Update a specific extension
sysext-cli update krusader

# Update all active extensions
sysext-cli update --all
```

**Remove an extension:**
```bash
sysext-cli remove krusader
```

**Run system diagnostics:**
```bash
sysext-cli doctor
```

### Graphical Interface

Launch **Sysext Creator** from your desktop application launcher or run:

```bash
sysext-gui-pro
```

## Testing

An automated test suite is provided to verify the build pipeline, vendor relocations, `tmpfiles.d` fallback, declarative triggers, and cleanup:

```bash
python3 test-sysext-suite.py
```

## License

GPL-2.0
