#!/usr/bin/python3

# Sysext-Creator Daemon v3.1
# Environment: Host System (Runs as Root)
# Features: Varlink IPC, Group 'wheel' access, systemd-sysext integration

import os
import sys
import subprocess
import varlink
import grp
import logging

# Define the Varlink interface
INTERFACE_DEFINITION = """
interface io.sysext.creator

method ListExtensions() -> (extensions: [] (name: str, version: str, packages: str))
method RemoveSysext(name: str) -> ()
method DeploySysext(name: str, path: str) -> (status: str, progress: int)
method RefreshExtensions() -> (status: str)

error ExtensionNotFound(name: str)
error PermissionDenied()
error InternalError(message: str)
"""

SOCKET_PATH = "/run/sysext-creator.sock"
EXT_DIR = "/var/lib/extensions"

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.info
log_err = logging.error

class SysextRequestHandler:
    """Logic for handling Varlink requests from CLI and GUI."""

    def ListExtensions(self, _metadata=None):
        log("Request: ListExtensions")
        extensions = []
        try:
            # Use systemd-sysext to get current status in JSON
            res = subprocess.run(["systemd-sysext", "list", "--json=pretty"], 
                                 capture_output=True, text=True, check=True)
            # In a real scenario, you'd parse this JSON. 
            # For now, we return a placeholder or parsed data.
            # Example parsing would go here.
        except Exception as e:
            log_err(f"Failed to list extensions: {e}")
        return {"extensions": extensions}

    def RefreshExtensions(self, _metadata=None):
        """Triggers systemd-sysext refresh to mount/unmount layers."""
        log("Request: RefreshExtensions")
        try:
            subprocess.run(["systemd-sysext", "refresh"], check=True)
            return {"status": "Success"}
        except subprocess.CalledProcessError as e:
            log_err(f"Refresh failed: {e}")
            return {"status": f"Error: {e.stderr}"}

    def RemoveSysext(self, name, _metadata=None):
        """Deletes .raw images and refreshes the system."""
        log(f"Request: RemoveSysext(name={name})")
        # Check both possible filenames (standard and confext)
        targets = [
            os.path.join(EXT_DIR, f"{name}.raw"),
            os.path.join(EXT_DIR, f"{name}.confext.raw")
        ]
        
        removed_any = False
        for target in targets:
            if os.path.exists(target):
                os.remove(target)
                log(f"Removed file: {target}")
                removed_any = True
        
        if removed_any:
            subprocess.run(["systemd-sysext", "refresh"])
        return {}

    def DeploySysext(self, name, path, _metadata=None):
        """Copies a built .raw image to the system extensions directory."""
        log(f"Request: DeploySysext(name={name}, path={path})")
        if not os.path.exists(path):
            return {"status": "Error: Source file not found", "progress": 0}

        target_path = os.path.join(EXT_DIR, os.path.basename(path))
        
        try:
            # Copy file to protected system directory
            subprocess.run(["cp", path, target_path], check=True)
            
            # Apply correct SELinux context
            subprocess.run(["restorecon", "-v", target_path], check=True)
            
            # Activate immediately
            subprocess.run(["systemd-sysext", "refresh"], check=True)
            
            log(f"Deployment successful: {target_path}")
            return {"status": "Success", "progress": 100}
        except Exception as e:
            log_err(f"Deployment failed: {e}")
            return {"status": f"Error: {str(e)}", "progress": 0}

def run_server():
    """Initializes and starts the Varlink server with proper permissions."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    # Initialize Varlink service
    service = varlink.Service(
        vendor="Sysext Creator Project",
        product="Sysext Daemon",
        version="3.1",
        interface=INTERFACE_DEFINITION
    )

    # Create the server
    with varlink.ThreadingServer(f"unix:{SOCKET_PATH}", SysextRequestHandler) as server:
        log(f"Daemon listening on {SOCKET_PATH}")
        
        # --- SECURITY SETUP ---
        # 1. Set permissions to 0o660 (rw-rw----)
        os.chmod(SOCKET_PATH, 0o660)
        
        # 2. Change group to 'wheel' so admin users can talk to the daemon
        try:
            wheel_info = grp.getgrnam('wheel')
            os.chown(SOCKET_PATH, -1, wheel_info.gr_gid)
            log("🔒 Socket security: Access granted to root and group 'wheel'.")
        except KeyError:
            log_err("⚠️ Group 'wheel' not found. Socket restricted to root only.")
            os.chmod(SOCKET_PATH, 0o600)

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log("Daemon shutting down.")
            if os.path.exists(SOCKET_PATH):
                os.remove(SOCKET_PATH)

if __name__ == "__main__":
    # Ensure running as root
    if os.geteuid() != 0:
        print("Error: Sysext Daemon must run as root.")
        sys.exit(1)
    run_server()
