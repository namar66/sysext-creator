#!/usr/bin/python3

import os
import subprocess
import sys
from pathlib import Path

# ANSI barvičky
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

CONFEXT_DIR = "/var/lib/confexts"

def print_status(message, status):
    status_map = {
        "PASS": (GREEN, " OK "),
        "FAIL": (RED, "FAIL"),
        "WARN": (YELLOW, "WARN")
    }
    color, text = status_map.get(status, (RESET, "INFO"))
    print(f"[{color}{text}{RESET}] {message}")

def get_rpm_owner(file_path):
    """
    Vrátí jméno balíčku, pokud soubor existuje a je vlastněn RPM.
    Vrátí (None, True), pokud soubor existuje, ale není v RPM (local/merged).
    Vrátí (None, False), pokud soubor vůbec neexistuje.
    """
    if not os.path.exists(file_path):
        return None, False

    # -q: query, --qf: format (jen jméno), -f: file
    res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}", "-f", file_path], capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout.strip(), True

    return None, True

def check_collisions():
    print(f"\n{BOLD}--- Checking for /etc Overwrites & RPM Conflicts ---{RESET}")
    confext_files = list(Path(CONFEXT_DIR).glob("*.raw"))

    if not confext_files:
        print("No configuration extensions found.")
        return

    etc_inventory = {}

    for img in confext_files:
        print(f"\n🔍 Analyzing {BOLD}{img.name}{RESET}...")
        try:
            res = subprocess.run(["systemd-dissect", "--list", str(img)], capture_output=True, text=True, check=True)

            for line in res.stdout.splitlines():
                if line.startswith("etc/") and not line.endswith("/"):
                    full_path = "/" + line
                    owner, exists = get_rpm_owner(full_path)

                    if owner:
                        # SKUTEČNÝ KONFLIKT: Soubor patří systému (RPM)
                        print_status(f"CRITICAL: {full_path} overwrites system package {BOLD}{owner}{RESET}", "FAIL")
                    elif exists:
                        # VAROVÁNÍ: Soubor v systému je, ale RPM o něm neví (může to být už aktivní confext!)
                        print_status(f"NOTICE: {full_path} is currently present on host (Active extension or local file)", "WARN")
                    else:
                        # ČISTÝ STAV: Soubor v systému neexistuje, extension ho vytvoří
                        print_status(f"NEW FILE: {full_path} (clean install)", "PASS")

                    # Detekce kolizí mezi obrazy navzájem
                    if full_path in etc_inventory:
                        etc_inventory[full_path].append(img.name)
                        print_status(f"COLLISION: {full_path} exists in multiple images: {etc_inventory[full_path]}", "FAIL")
                    else:
                        etc_inventory[full_path] = [img.name]

        except Exception as e:
            print_status(f"Analysis error: {e}", "FAIL")

def main():
    if os.geteuid() != 0:
        print(f"{RED}Error: Spusť mě pod sudo.{RESET}")
        sys.exit(1)

    print(f"{BOLD}Sysext Doctor v1.6 - Precision Diagnostic{RESET}")
    print(f"{YELLOW}Note: If extensions are already merged, their files will appear as 'NOTICE'.{RESET}")
    check_collisions()
    print(f"\n{BOLD}--- Diagnostic Complete ---{RESET}")

if __name__ == "__main__":
    main()
