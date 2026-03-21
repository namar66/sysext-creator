#!/usr/bin/python3

# Sysext-Creator CLI v2.1
# Features: Smart Install, Builder Integration, Varlink IPC, Conflict Resolution

import sys
import os
import argparse
import subprocess
import varlink
from pathlib import Path

SOCKET_ADDRESS = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"

# We expect the builder to be in the same directory or accessible via system path
BUILDER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sysext-creator-builder.py")
BUILD_DIR = Path.home() / "sysext-builds"
CONTAINER_NAME = "sysext-builder"

def connect():
    """Establish connection to the daemon via Varlink."""
    try:
        client = varlink.Client(address=SOCKET_ADDRESS)
        return client.open(INTERFACE)
    except Exception as e:
        print(f"Error connecting to daemon: {e}")
        print("Make sure sysext-creator-daemon.service is running.")
        sys.exit(1)

def cmd_list(args):
    try:
        with connect() as remote:
            result = remote.ListExtensions()
            extensions = result.get("extensions", [])

            if not extensions:
                print("No extensions reported by the daemon.")
                return

            print(f"{'NAME':<20} | {'VERSION':<15} | PACKAGES")
            print("-" * 65)
            for ext in extensions:
                name = ext.get("name", "unknown")
                version = ext.get("version", "unknown")
                pkgs = ext.get("packages", "")
                print(f"{name:<20} | {version:<15} | {pkgs}")
    except varlink.error.VarlinkError as e:
        print(f"Daemon error: {e}")

def cmd_refresh(args):
    print("Triggering system extensions refresh...")
    try:
        with connect() as remote:
            result = remote.RefreshExtensions()
            print(f"Status: {result.get('status')}")
    except varlink.error.VarlinkError as e:
        print(f"Daemon error: {e}")

def handle_deployment_response(remote, result, name, path, is_forced):
    """Helper to handle interactive conflict resolution."""
    if result.get("status") == "ConflictFound":
        print(f"\n\033[1;31m⚠️ WARNING: Conflicts found in {os.path.basename(path)}\033[0m")
        for c in result.get("conflicts", []):
            print(f"  - {c}")

        if is_forced:
            print("\nForce flag active. Proceeding anyway...")
            return remote.DeploySysext(name, str(path), True)

        confirm = input("\nDo you want to FORCE the installation? [y/N]: ")
        if confirm.lower() == 'y':
            return remote.DeploySysext(name, str(path), True)
        else:
            print("Deployment aborted for this layer.")
            return None
    return result

def cmd_deploy(args):
    """Deploys an already existing .raw file."""
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        print(f"Error: File '{path}' does not exist.")
        sys.exit(1)

    name = os.path.basename(path).replace(".confext.raw", "").replace(".raw", "")
    print(f"Deploying extension '{name}' from {path}...")

    try:
        with connect() as remote:
            # FIX: Added the missing 'force' boolean parameter
            result = remote.DeploySysext(name, str(path), args.force)
            result = handle_deployment_response(remote, result, name, str(path), args.force)

            if result:
                print(f"Status: {result.get('status')}")
                if result.get("progress") == 100:
                    print(f"Deployment of {os.path.basename(path)} successful!")
    except varlink.error.VarlinkError as e:
        print(f"Daemon error: {e}")

def cmd_install(args):
    """The 'Smart Install' - prepares a dedicated Toolbox, builds, and deploys."""
    name = args.name
    packages = args.packages

    print(f"--- Step 1: Preparing Toolbox container '{CONTAINER_NAME}' ---")

    container_exists = subprocess.run(
        ["podman", "container", "exists", CONTAINER_NAME]
    ).returncode == 0

    if not container_exists:
        print(f"Container '{CONTAINER_NAME}' not found. Creating it now (this may take a minute)...")
        try:
            subprocess.run(["toolbox", "create", "-c", CONTAINER_NAME], check=True)
            print(f"Container '{CONTAINER_NAME}' created successfully.")
        except subprocess.CalledProcessError:
            print(f"Error: Failed to create Toolbox container '{CONTAINER_NAME}'.")
            sys.exit(1)
    else:
        print(f"Container '{CONTAINER_NAME}' is ready.")

    print(f"\n--- Step 2: Building extension '{name}' inside '{CONTAINER_NAME}' ---")
    if not os.path.exists(BUILDER_SCRIPT):
        print(f"Error: Builder script not found at {BUILDER_SCRIPT}")
        sys.exit(1)

    toolbox_script_path = BUILDER_SCRIPT
    if toolbox_script_path.startswith("/usr/"):
        toolbox_script_path = "/run/host" + toolbox_script_path

    build_cmd = ["toolbox", "run", "-c", CONTAINER_NAME, "python3", toolbox_script_path, name] + packages
    try:
        subprocess.run(build_cmd, check=True)
    except subprocess.CalledProcessError:
        print("\nError: Build failed in Toolbox. Aborting installation.")
        sys.exit(1)

    print(f"\n--- Step 3: Deploying extension '{name}' via Daemon ---")

    sysext_path = BUILD_DIR / f"{name}.raw"
    confext_path = BUILD_DIR / f"{name}.confext.raw"

    deployed_any = False

    with connect() as remote:
        for path in [sysext_path, confext_path]:
            if path.exists():
                print(f"Pushing {path.name} to daemon...")
                try:
                    # FIX: Added the missing 'force' boolean parameter
                    result = remote.DeploySysext(name, str(path), args.force)
                    result = handle_deployment_response(remote, result, name, str(path), args.force)

                    if result:
                        print(f"Daemon response: {result.get('status')}")
                        deployed_any = True
                except varlink.error.VarlinkError as e:
                    print(f"Daemon error during deployment of {path.name}: {e}")

    if not deployed_any:
        print(f"\nError: No generated .raw files were successfully deployed for '{name}'.")
        sys.exit(1)

    print("\n✅ Installation complete! The extension is now active.")

def cmd_remove(args):
    print(f"Removing extension '{args.name}'...")
    try:
        with connect() as remote:
            remote.RemoveSysext(args.name)
            print("Removal request sent. Daemon is refreshing the system.")
    except varlink.error.VarlinkError as e:
        print(f"Daemon error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Sysext Creator CLI - Manage Atomic System Extensions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: list
    parser_list = subparsers.add_parser("list", help="List available extensions")

    # Command: refresh
    parser_refresh = subparsers.add_parser("refresh", help="Force systemd-sysext/confext refresh")

    # Command: deploy
    parser_deploy = subparsers.add_parser("deploy", help="Deploy an already built .raw image")
    parser_deploy.add_argument("file", help="Path to the .raw image")
    parser_deploy.add_argument("--force", action="store_true", help="Bypass conflict checks")

    # Command: install
    parser_install = subparsers.add_parser("install", help="Build and immediately deploy a new extension")
    parser_install.add_argument("name", help="Name of the new extension (e.g., htop)")
    parser_install.add_argument("packages", nargs="+", help="List of RPM packages to include")
    parser_install.add_argument("--force", action="store_true", help="Bypass conflict checks")

    # Command: remove
    parser_remove = subparsers.add_parser("remove", help="Remove an extension from the system")
    parser_remove.add_argument("name", help="Name of the extension to remove (e.g., htop)")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "deploy":
        cmd_deploy(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "remove":
        cmd_remove(args)

if __name__ == "__main__":
    main()
