#!/usr/bin/python3

# Sysext-CLI v3.0 - Added update functionality
# Environment: Host System (User)

import sys
import argparse
import subprocess
import os
import varlink
from pathlib import Path

SOCKET = "unix:/run/sysext-creator.sock"
BUILDER_SCRIPT = Path.home() / ".local/bin/sysext-builder"

def get_container_name():
    try:
        res = subprocess.run(["rpm", "-E", "%fedora"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return f"sysext-creator-builder-fc{res.stdout.strip()}"
    except: pass
    return "sysext-creator-builder-fc40"

def deploy_sync(name, path):
    try:
        with varlink.Client(address=SOCKET) as client:
            with client.open('io.sysext.creator') as remote:
                reply = remote.DeploySysext(name, str(path))
                return reply['status'] == 'Success'
    except Exception as e:
        print(f"Varlink error during deploy: {e}")
        return False

def update_all():
    print("Starting update process...")
    try:
        with varlink.Client(address=SOCKET) as client:
            with client.open('io.sysext.creator') as remote:
                res = remote.ListExtensions()
                extensions = res['extensions']
    except Exception as e:
        print(f"Error connecting to daemon: {e}")
        sys.exit(1)

    if not extensions:
        print("No extensions installed. Nothing to update.")
        return

    container = get_container_name()
    build_dir = Path.home() / "sysext-builds"

    success_count = 0
    for ext in extensions:
        name = ext['name']
        pkgs = ext['packages']
        print(f"\nUpdating extension: {name} [{pkgs}]")

        # 1. Build
        cmd = f"toolbox run -c {container} python3 {BUILDER_SCRIPT} {name} {pkgs}"
        print(f"Running build: {cmd}")
        build_res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if build_res.returncode != 0:
            print(f"Build failed for {name}:\n{build_res.stderr}")
            continue

        # 2. Deploy
        p1 = build_dir / f"{name}.raw"
        p2 = build_dir / f"{name}.confext.raw"

        deployed = False
        if p1.exists():
            print(f"Deploying {p1.name}...")
            if deploy_sync(name, p1): deployed = True
        if p2.exists():
            print(f"Deploying {p2.name}...")
            if deploy_sync(name, p2): deployed = True

        if deployed:
            print(f"Successfully updated {name}.")
            success_count += 1
        else:
            print(f"Deployment failed for {name}.")

    print(f"\nUpdate complete. Successfully updated {success_count} out of {len(extensions)} extensions.")

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    rem = sub.add_parser("remove")
    rem.add_argument("name")
    sub.add_parser("update") # New command

    args = parser.parse_args()

    if args.cmd == "update":
        update_all()
        return

    try:
        with varlink.Client(address=SOCKET) as client:
            with client.open('io.sysext.creator') as remote:
                if args.cmd == "list":
                    res = remote.ListExtensions()
                    for e in res['extensions']:
                        print(f"{e['name']}: {e['packages']} (v{e['version']})")
                elif args.cmd == "remove":
                    remote.RemoveSysext(args.name)
                    print(f"Removed {args.name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
