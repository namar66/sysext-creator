* 📦 Sysext-Creator (Resilient Edition)Sysext-Creator is a high-performance, event-driven tool for Fedora Atomic (Silverblue, Kinoite, Sway Atomic). It allows you to install traditional RPM packages as dynamic system extensions (systemd-sysext) with a 100% rootless daily workflow.
* 🌟 Key Features
* ⚡ Zero-Sudo Workflow: After initial setup, manage your apps without ever typing a password.
* 📡 Asynchronous IPC: Uses a request-reply model between a rootless Distrobox and a host daemon.
* 🛡️ Self-Healing Container: Automatically detects missing mount points or OS version mismatches and repairs the environment.
* 🗜️ EROFS Compression: Uses high-performance lz4hc compression for minimal disk footprint and maximum speed.
* 🧹 Smart Cleanup: Interactive /etc configuration management and an "N-1" garbage collector for old containers.
* 🏗️ Architecture: How it Works Sysext-Creator uses a Staging Area at /var/tmp/sysext-staging to facilitate communication between two distinct layers:
* The Client (sysext-creator-core): Runs inside a rootless Distrobox. It downloads RPMs, extracts them, and creates an EROFS image.
* The Watcher (systemd-deploy.path):* A native host unit that monitors the staging area for new files.
* The Daemon (sysext-creator-deploy.sh): Triggered by the watcher, this script runs with host privileges to deploy the image and refresh system extensions.
* 🚀 Installation
* requires distrobox installed check `https://distrobox.it`
* Clone the repository:
```Bash
git clone https://github.com/yourusername/sysext-creator.git
```
```Bash
cd sysext-creator
chmod +x *.sh
```
* Run the setup script:
```Bash
./sysext-creator-setup.sh
```
* (Note: This is the only step that requires sudo to install the system daemon.)
* Restart your terminal to enable bash completion.
* 🛠️ Usage
* Install an Application Fetches the package and its dependencies from the host's Fedora repositories.
* `sysext-creator install htop`
* List Installed Packages Queries the host daemon for accurate versioning of active extensions.
* `sysext-creator list`
* Remove an Application Unmounts the image and interactively asks to clean up configuration files in /etc.
* `sysext-creator rm htop`
* Update images
* `sysext-creator updates`
* OS Upgrade (Major Version)After a major Fedora upgrade (e.g., F43 to F44), rebuild your extensions for the new base.
* `sysext-creator upgrade-box`
* 📝 Configuration & SafetyBlacklist: Critical system packages like glibc, kernel, and shadow-utils are blocked from installation to ensure system stability.
* Throttling: The list command includes a 0.5s throttle to prevent saturating the Systemd event loop, ensuring reliable communication with the host daemon.
* 📜 LicenseThis project is licensed under the GNU General Public License v2.
