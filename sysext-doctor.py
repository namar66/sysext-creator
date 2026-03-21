#!/usr/bin/python3

# Sysext Doctor v3.1 - Precision Diagnostic
# Checks for /etc Overwrites & RPM Conflicts

import os
import subprocess
import sys
from pathlib import Path

CONFEXT_DIR = "/var/lib/confexts"

def get_rpm_owner(file_path):
    if not os.path.exists(file_path): return None, False
    res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}", "-f", file_path], capture_output=True, text=True)
    if res.returncode == 0: return res.stdout.strip(), True
    return None, True

def check_collisions():
    print("--- Checking for /etc Overwrites & RPM Conflicts ---")
    confext_files = list(Path(CONFEXT_DIR).glob("*.raw"))
    if not confext_files:
        print("No configuration extensions found.")
        return

    for img in confext_files:
        print(f"\n🔍 Analyzing {img.name}...")
        try:
            res = subprocess.run(["systemd-dissect", "--list", str(img)], capture_output=True, text=True, check=True)
            for line in res.stdout.splitlines():
                if line.startswith("etc/") and not line.endswith("/"):
                    full_path = "/" + line
                    owner, exists = get_rpm_owner(full_path)
                    if owner:
                        print(f"[FAIL] {full_path} overwrites system package: {owner}")
                    elif exists:
                        print(f"[WARN] {full_path} exists on host (local file or active extension)")
                    else:
                        print(f"[ OK ] {full_path} (new file)")
        except Exception as e: print(f"Error: {e}")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Please run with sudo.")
        sys.exit(1)
    check_collisions()
