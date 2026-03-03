# 💎 Sysext-Creator (v1.1.1)

A professional management tool for system extensions (`systemd-sysext`) on **Fedora Atomic** desktops (Silverblue, Kinoite, Aurora). It allows you to install RPM packages into your immutable system without the overhead of `rpm-ostree` layering.

## ✨ Key Features

* **Bake-on-Site:** Images are built directly on your machine, ensuring 100% compatibility with your specific Fedora version.
* **EROFS Engine:** Uses the modern, high-performance EROFS filesystem for maximum speed and disk space efficiency.
* **Safety First:** Built-in safeguards prevent accidental deletion or corruption of the tool itself during updates.
* **Smart Versioning:** Automatically fixes image naming (avoids `.fc43.fc43` bugs) and detects versions directly from DNF repositories.
* **Clean System:** Installed applications leave no permanent trace in your `/usr` directory.



## 🚀 Quick Start

### 1. Prepare Your System
Clone the repository and set up the necessary permissions:
```bash
git clone https://github.com/namar66/sysext-creator.git
cd sysext-creator
chmod +x *.sh
./sysext-setup.sh
```
Note: You may need to log out and back in for the group changes to take effect.

2. Bootstrap the Tool
Build the initial image that activates the sysext-creator command:

```bash
./build-bundle.sh
sudo mv sysext-creator-v1.1.1-fc*.raw /var/lib/extensions/
sudo systemctl restart systemd-sysext.service
```
3. Usage
Now you can manage packages with ease:

# Install a package
```bash
sysext-creator install htop
```

# Update all extensions (the tool automatically skips itself)
```bash
sysext-creator update
```
# List installed extensions
```bash
sysext-creator list
```
# Remove an extension
```bash
sysext-creator rm htop
```
📂 Project Structure

`sysext-creator.sh` – The host-side wrapper (main entry point).

`sysext-creator-core.sh` – The engine running inside the build container.

`sysext-setup.sh` – Initial host and SELinux configuration.

`build-bundle.sh` – Script to bootstrap the initial tool image.

🗺️ Roadmap (v1.2)
[ ] Remove Distrobox dependency (switching to a pure Podman worker).

[ ] Implement self-upgrade command via GitHub Raw API.

[ ] Automated cleanup of temporary Podman build layers.

⚖️ License
GPLv2 – Created by Martin Naď (2026)
