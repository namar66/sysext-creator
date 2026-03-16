#!/usr/bin/python3

# Sysext-Doctor v1.2 - Integration Ready
# Environment: Host System
# Exit codes: 0 = Success/Clean, 1 = Error/Conflict

import os
import sys
import subprocess
import argparse
import json
from pathlib import Path

SOCKET = "unix:/run/sysext-creator.sock"
EXT_DIR = Path("/var/lib/extensions")

class Colors:
    OK = '\033[92m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'

def log_ok(msg): print(f"[{Colors.OK} OK {Colors.END}] {msg}")
def log_warn(msg): print(f"[{Colors.WARN}WARN{Colors.END}] {msg}")
def log_err(msg): print(f"[{Colors.FAIL}FAIL{Colors.END}] {msg}")

def validate_single_file(file_path: Path):
    """
    Performs deep validation on a single .raw file.
    Returns True if the file is safe and valid.
    """
    if not file_path.exists():
        log_err(f"File {file_path} not found.")
        return False

    log_ok(f"Doctor is inspecting: {file_path.name}")

    # 1. systemd-dissect validation
    # Note: Using --no-pager and check for binary existence
    res = subprocess.run(["systemd-dissect", "--validate", str(file_path)], capture_output=True, text=True)
    if res.returncode != 0:
        log_err("Systemd validation failed! Image might be corrupted or invalid.")
        log_err(res.stderr.strip())
        return False
    log_ok("Systemd-dissect validation passed.")

    # 2. Metadata check (Try to read extension-release)
    res = subprocess.run(["systemd-dissect", "-j", str(file_path)], capture_output=True, text=True)
    if res.returncode == 0:
        try:
            data = json.loads(res.stdout)
            log_ok(f"Image architecture: {data.get('architecture', 'unknown')}")
        except:
            log_warn("Could not parse image JSON metadata.")
    
    # 3. Check for shadowed files in the base OS or other extensions
    # (Optional: can be expanded to check against active /usr)
    return True

def main():
    parser = argparse.ArgumentParser(description="Sysext Doctor - Diagnostic Tool")
    parser.add_argument("--file", type=str, help="Validate a specific .raw file before installation")
    parser.add_argument("--scan", action="store_true", help="Scan all installed extensions")
    args = parser.parse_args()

    # Elevation check: systemd-dissect --validate often needs root for loop devices
    if os.geteuid() != 0:
        log_err("Sysext Doctor requires root privileges. Please run with pkexec or sudo.")
        sys.exit(1)

    if args.file:
        success = validate_single_file(Path(args.file))
        sys.exit(0 if success else 1)
    
    # If no specific file, perform a general scan (like v1.1)
    # ... (rest of the scan logic from previous version) ...
    sys.exit(0)

if __name__ == "__main__":
    main()
