#!/usr/bin/python3

# Sysext-Creator Test Suite v3.1
# Environment: Host System (User)

import os
import sys
import subprocess
import varlink
from pathlib import Path

TEST_NAME = "test-layer"
TEST_PKGS = ["htop"]
SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"

def main():
    print(">>> Phase 1: Build Test")
    cmd = ["toolbox", "run", "-c", "sysext-builder", "python3", "/run/host"+BUILDER_SCRIPT, TEST_NAME] + TEST_PKGS
    subprocess.run(cmd, check=True)

    img = f"/var/tmp/sysext-creator/{TEST_NAME}.raw"
    if not os.path.exists(img):
        print("Build failed: Image not found.")
        sys.exit(1)
    print("[OK] Build successful.")

    print(">>> Phase 2: Daemon Deployment")
    try:
        with varlink.Client(address=SOCKET_PATH) as client:
            with client.open('io.sysext.creator') as remote:
                res = remote.DeploySysext(TEST_NAME, img, True)
                print(f"Status: {res['status']}")

                print(">>> Phase 3: Verification")
                exts = remote.ListExtensions()['extensions']
                if any(e['name'] == TEST_NAME for e in exts):
                    print("[OK] Extension listed in daemon.")

                print(">>> Phase 4: Removal")
                remote.RemoveSysext(TEST_NAME)
                print("[OK] Extension removed.")
    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
