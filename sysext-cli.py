#!/usr/bin/python3

# Sysext-Creator CLI v3.1
# Features: Smart RPM Naming, Varlink Integration

import sys
import os
import argparse
import subprocess
import varlink
import re
from pathlib import Path

SOCKET_ADDRESS = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
BUILD_DIR = Path("/var/tmp/sysext-creator")
CONTAINER_NAME = "sysext-builder"

def connect():
    try:
        client = varlink.Client(address=SOCKET_ADDRESS)
        return client.open(INTERFACE)
    except Exception as e:
        print(f"Error: Daemon not reachable ({e})")
        sys.exit(1)

def cmd_list(args):
    with connect() as remote:
        res = remote.ListExtensions()
        exts = res.get("extensions", [])
        if not exts:
            print("No extensions active.")
            return
        print(f"{'NAME':<20} | {'VERSION':<20}")
        print("-" * 45)
        for e in exts:
            print(f"{e.get('name'):<20} | {e.get('version'):<20}")

def cmd_remove(args):
    with connect() as remote:
        remote.RemoveSysext(args.name)
        print(f"Extension '{args.name}' removed.")

def handle_deploy(remote, name, path, force):
    res = remote.DeploySysext(name, os.path.abspath(path), force)
    if res.get("status") == "ConflictFound":
        print("\n⚠️ Conflicts detected!")
        for c in res.get("conflicts", []): print(f"  - {c}")
        if not force:
            if input("\nForce installation? [y/N]: ").lower() == 'y':
                res = remote.DeploySysext(name, os.path.abspath(path), True)
            else:
                print("Aborted.")
                return None
    return res

def cmd_install(args):
    if args.name_or_rpm.endswith(".rpm") and os.path.exists(args.name_or_rpm):
        abs_path = os.path.abspath(args.name_or_rpm)
        try:
            # Získání jména přímo z RPM
            res = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", abs_path], capture_output=True, text=True, check=True)
            name = res.stdout.strip()
        except:
            name = Path(abs_path).stem.split('-')[0]
        packages = [abs_path] + args.packages
        print(f"📦 Local RPM: Using extension name '{name}'")
    else:
        name = args.name_or_rpm
        packages = args.packages
        if not packages:
            print("Error: Specify packages to install.")
            sys.exit(1)

    print(f"--- Step 1: Toolbox '{CONTAINER_NAME}' ---")
    if subprocess.run(["podman", "container", "exists", CONTAINER_NAME]).returncode != 0:
        subprocess.run(["toolbox", "create", "-c", CONTAINER_NAME], check=True)

    print(f"\n--- Step 2: Building '{name}' ---")
    script = "/run/host" + BUILDER_SCRIPT
    try:
        subprocess.run(["toolbox", "run", "-c", CONTAINER_NAME, "python3", script, name] + packages, check=True)
    except:
        print("Build failed.")
        sys.exit(1)

    print(f"\n--- Step 3: Deploying ---")
    deployed = False
    with connect() as remote:
        for suffix in ["", ".confext"]:
            p = BUILD_DIR / f"{name}{suffix}.raw"
            if p.exists():
                res = handle_deploy(remote, name, str(p), args.force)
                if res and res.get("status") == "Success": deployed = True

    if deployed: print("\n✅ Done!")

def main():
    parser = argparse.ArgumentParser(description="Sysext CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    rem = sub.add_parser("remove")
    rem.add_argument("name")

    ins = sub.add_parser("install")
    ins.add_argument("name_or_rpm")
    ins.add_argument("packages", nargs="*")
    ins.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.command == "list": cmd_list(args)
    elif args.command == "remove": cmd_remove(args)
    elif args.command == "install": cmd_install(args)

if __name__ == "__main__":
    main()
