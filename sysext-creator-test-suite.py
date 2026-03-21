#!/usr/bin/python3

# Sysext-Creator Automated Test Suite v3.0
# Environment: Host System (User)

import os
import sys
import subprocess
import varlink
from pathlib import Path

TEST_PKG_NAME = "test-distrobox"
TEST_PKGS = "distrobox"
SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
CONTAINER_NAME = "sysext-builder"

def print_step(msg): print(f"\n\033[1;34m>>> {msg}\033[0m")
def print_success(msg): print(f"\033[1;32m[OK]\033[0m {msg}")
def print_error(msg):
    print(f"\033[1;31m[ERROR]\033[0m {msg}")
    sys.exit(1)

def run_command(cmd):
    try:
        res = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        return res.stdout
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {cmd}\nOutput: {e.stderr}")

def main():
    print_step("Phase 1: Environment Check")
    if not os.path.exists(BUILDER_SCRIPT): print_error(f"Builder script not found at {BUILDER_SCRIPT}")
    if not os.path.exists("/run/sysext-creator.sock"): print_error("Daemon socket not found.")
    print_success("Environment looks good.")

    print_step(f"Phase 2: Building package '{TEST_PKG_NAME}' via Toolbox")
    cmd = f"toolbox run -c {CONTAINER_NAME} python3 {BUILDER_SCRIPT} {TEST_PKG_NAME} {TEST_PKGS}"
    run_command(cmd)

    img_path = Path.home() / f"sysext-builds/{TEST_PKG_NAME}.raw"
    if not img_path.exists(): print_error(f"Builder failed to create image at {img_path}")
    print_success(f"Image created successfully: {img_path}")

    print_step("Phase 3: Deploying via Daemon (Varlink)")
    try:
        with varlink.Client(address=SOCKET_PATH) as client:
            with client.open('io.sysext.creator') as remote:
                # Synchronous call (no _more=True)
                reply = remote.DeploySysext(TEST_PKG_NAME, str(img_path))
                print(f"Daemon Status: {reply['status']}")
    except Exception as e:
        print_error(f"Varlink deployment failed: {e}")
    print_success("Daemon reports successful deployment.")

    print_step("Phase 4: Verifying Deployment")
    try:
        res = subprocess.run("which distrobox", shell=True, capture_output=True, text=True)
        if res.returncode != 0: print_error("Binary 'distrobox' not found in path.")
        print_success("Binary 'distrobox' is available in the system path.")

        with varlink.Client(address=SOCKET_PATH) as client:
            with client.open('io.sysext.creator') as remote:
                res = remote.ListExtensions()
                if not any(ext['name'] == TEST_PKG_NAME for ext in res['extensions']):
                    print_error("Daemon ListExtensions does not show our test package.")
        print_success("Daemon correctly lists the new extension.")
    except Exception as e: print_error(f"Verification failed: {e}")

    print_step("Phase 5: Cleanup and Removal")
    try:
        with varlink.Client(address=SOCKET_PATH) as client:
            with client.open('io.sysext.creator') as remote:
                remote.RemoveSysext(TEST_PKG_NAME)
    except Exception as e: print_error(f"Removal failed: {e}")

    if subprocess.run("which distrobox", shell=True, capture_output=True).returncode == 0:
        print_error("Binary 'distrobox' still exists after removal.")
    print_success("Extension removed successfully.")
    print_step("TEST SUITE COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
