#!/usr/bin/python3

# Sysext Doctor v3.2 - Precision Diagnostic (GUI Ready)
# Checks for /etc Overwrites & RPM Conflicts

import os
import subprocess
import sys
from pathlib import Path

# Force unbuffered output so the GUI terminal updates instantly
sys.stdout.reconfigure(line_buffering=True)

SYSEXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"

def get_rpm_owner(file_path):
    if not os.path.exists(file_path): return None, False

    cmd = ["rpm", "-q", "--qf", "%{NAME}", "-f", file_path]
    # If invoked inside Toolbox, force it to check the host's RPM database
    if os.path.exists("/run/.toolboxenv"):
        cmd = ["flatpak-spawn", "--host"] + cmd

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0: return res.stdout.strip(), True
    return None, True

def check_sysext_status():
    print("\n--- Checking systemd-sysext status ---")
    res = subprocess.run(["systemd-sysext", "status"], capture_output=True, text=True)
    if res.returncode == 0:
        print("[ OK ] systemd-sysext is active and healthy")
    else:
        print(f"[FAIL] systemd-sysext status check failed: {res.stderr or 'Unknown error'}")

def check_collisions():
    check_sysext_status()
    print("\n--- Checking for /usr & /etc Overwrites & RPM Conflicts ---")

    images = list(Path(SYSEXT_DIR).glob("*.raw")) + list(Path(CONFEXT_DIR).glob("*.raw"))
    if not images:
        print("No extensions found in /var/lib/extensions or /var/lib/confexts.")
        return

    global_file_map = {}

    for img in images:
        print(f"\n🔍 Analyzing {img.name}...")
        try:
            dissect_check = subprocess.run(["which", "systemd-dissect"], capture_output=True)
            if dissect_check.returncode != 0:
                print(f"[WARN] systemd-dissect not found, skipping deep analysis of {img.name}")
                continue

            res = subprocess.run(["systemd-dissect", "--list", str(img)], capture_output=True, text=True, check=True)
            for line in res.stdout.splitlines():
                if (line.startswith("usr/") or line.startswith("etc/")) and not line.endswith("/"):
                    full_path = "/" + line

                    if full_path not in global_file_map:
                        global_file_map[full_path] = []
                    global_file_map[full_path].append(img.name)

                    owner, exists = get_rpm_owner(full_path)
                    if owner:
                        print(f"[FAIL] {full_path} overwrites system package: {owner}")
                    elif exists:
                        print(f"[WARN] {full_path} exists on host (local file or active extension)")
                    else:
                        print(f"[ OK ] {full_path} (new file)")
        except Exception as e: print(f"Error: {e}")

    print("\n--- Checking for /etc Symlinks (tmpfiles.d) ---")
    tmpfiles_dir = "/usr/lib/tmpfiles.d"
    if os.path.exists(tmpfiles_dir):
        for f in os.listdir(tmpfiles_dir):
            if f.startswith("sysext-creator-") and f.endswith(".conf"):
                print(f"Checking {f}...")
                with open(os.path.join(tmpfiles_dir, f), "r") as cf:
                    for line in cf:
                        if line.startswith("L+ "):
                            parts = line.split()
                            if len(parts) >= 6:
                                link = parts[1]
                                target = parts[5]
                                if os.path.islink(link):
                                    actual_target = os.readlink(link)
                                    if actual_target == target:
                                        print(f"[ OK ] {link} -> {target}")
                                    else:
                                        print(f"[FAIL] {link} points to {actual_target}, expected {target}")
                                else:
                                    print(f"[FAIL] {link} is not a symlink (missing or regular file)")

    print("\n--- Checking for Cross-Extension Collisions ---")
    cross_collisions = {k: v for k, v in global_file_map.items() if len(v) > 1}
    if cross_collisions:
        for path, exts in cross_collisions.items():
            print(f"[FAIL] Collision: {path} is provided by multiple extensions: {', '.join(exts)}")
    else:
        print("[ OK ] No cross-extension collisions detected.\n")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Doctor must be run as root (or via pkexec) to access raw image contents.")
        sys.exit(1)
    check_collisions()
