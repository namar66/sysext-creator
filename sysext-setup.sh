#!/bin/bash
set -euo pipefail

HOST_VERSION=$(grep VERSION_ID= /etc/os-release | cut -d'=' -f2)
CONTAINER_NAME="sysext-box-fc${HOST_VERSION}"
STATE_DIR="$HOME/.local/state/sysext-creator"
SENTINEL_FILE="${STATE_DIR}/presetup_done"

echo "🔧 Configuring the host system..."

# 1. Permissions and Groups
! getent group sysext-admins >/dev/null && sudo groupadd -f sysext-admins
sudo usermod -aG sysext-admins "$USER"

# Create directories including .d for future symlinks
sudo mkdir -p /var/lib/extensions /var/lib/extensions.d /run/extensions
sudo chown root:sysext-admins /var/lib/extensions /var/lib/extensions.d
sudo chmod 775 /var/lib/extensions /var/lib/extensions.d

# Apply SELinux contexts (Fedora standard)
sudo restorecon -RFv /var/lib/extensions /var/lib/extensions.d /run/extensions

# Set up Sudoers for systemd-sysext service
echo "%sysext-admins ALL=(root) NOPASSWD: /usr/bin/systemctl restart systemd-sysext.service, /usr/bin/systemctl stop systemd-sysext.service" | sudo tee /etc/sudoers.d/sysext-creator > /dev/null
sudo chmod 440 /etc/sudoers.d/sysext-creator

# 2. Create the working container
if ! distrobox list | grep -q "$CONTAINER_NAME"; then
    echo "📦 Creating container $CONTAINER_NAME..."
    distrobox create --name "$CONTAINER_NAME" --image registry.fedoraproject.org/fedora-toolbox:${HOST_VERSION} --volume /var/lib/extensions:/var/lib/extensions:rw --volume /var/lib/extensions.d:/var/lib/extensions.d:rw -Y
    distrobox enter "$CONTAINER_NAME" -- sudo dnf install -y erofs-utils cpio dnf-utils
fi

# 3. Final verification
if sudo -n /usr/bin/systemctl restart systemd-sysext.service &>/dev/null; then
    mkdir -p "$STATE_DIR"
    touch "$SENTINEL_FILE"
    echo "✅ Setup successful. Everything is ready to use!"
else
    echo "⚠️  Setup completed, but Sudo privileges are not fully active yet."
    echo "⚠️  IMPORTANT: Please Log out and Log in again to apply group changes."
fi
