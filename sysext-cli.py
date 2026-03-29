#!/usr/bin/python3
#version v3.1

import os
import sys
import argparse
import subprocess

# ==========================================
# GLOBAL CONFIGURATION
# ==========================================
CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")
EXTENSIONS_DIR = "/var/lib/extensions"
MANIFEST_DIR = "/usr/share/sysext/manifests"
BIN_DIR = os.path.expanduser("~/.local/bin")

def run_pkexec_cmd(cmd_string, action_name):
    """Executes a shell command via pkexec and handles the output."""
    print(f"\n[Polkit] Requesting root privileges to {action_name}...")
    cmd = ["pkexec", "sh", "-c", cmd_string]
    try:
        res = subprocess.run(cmd)
        if res.returncode in (126, 127):
            print("❌ Action aborted: Authentication rejected.")
            sys.exit(1)
        elif res.returncode != 0:
            print(f"❌ Action failed with exit code {res.returncode}.")
            sys.exit(1)
        return True
    except Exception as e:
        print(f"❌ Execution error: {e}")
        sys.exit(1)

def cmd_list(args):
    """Lists all installed and active extensions."""
    if not os.path.exists(EXTENSIONS_DIR):
        print("No extensions directory found.")
        return

    exts = [f[:-4] for f in os.listdir(EXTENSIONS_DIR) if f.endswith(".raw")]
    if not exts:
        print("No active extensions found.")
        return

    print(f"{'NAME':<25} | {'PACKAGES':<10} | {'STATUS'}")
    print("-" * 60)

    for name in exts:
        count = "Unknown"
        manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                count = str(sum(1 for line in f if line.strip()))
        print(f"{name:<25} | {count:<10} | Active")

def cmd_remove(args):
    """Removes an extension from the system."""
    name = args.name
    raw_path = os.path.join(EXTENSIONS_DIR, f"{name}.raw")
    cache_path = os.path.join(CACHE_DIR, f"{name}.raw")

    if not os.path.exists(raw_path):
        print(f"❌ Extension '{name}' is not currently active.")
        sys.exit(1)

    print(f"🗑️  Removing extension '{name}'...")
    shell_cmd = f"rm -f {raw_path} {cache_path} && systemd-sysext refresh ; sleep 2 ; systemd-tmpfiles --create"

    if run_pkexec_cmd(shell_cmd, f"remove {name}"):
        print(f"✅ Extension '{name}' successfully removed.")

def cmd_doctor(args):
    """Runs the system diagnostics script."""
    doctor_script = os.path.join(BIN_DIR, "sysext-doctor.py")
    if not os.path.exists(doctor_script):
        print(f"❌ Doctor script not found at {doctor_script}")
        sys.exit(1)

    print("🩺 Starting System Diagnostics...")
    subprocess.run(["pkexec", "python3", doctor_script])

def cmd_install(args):
    """Builds and deploys a new extension."""
    name = args.name
    packages = args.packages

    if not packages:
        # If no packages provided, assume the name is the package
        packages = [name]

    print(f"🚀 Building extension '{name}' with packages: {', '.join(packages)}")

    builder_script = os.path.join(BIN_DIR, "sysext-creator-builder.py")
    if not os.path.exists(builder_script):
        print(f"❌ Builder script not found at {builder_script}")
        sys.exit(1)

    # Phase 1: Build in Toolbox (User space)
    build_cmd = [
        "toolbox", "run", "-c", "sysext-builder",
        "python3", builder_script,
        "--name", name,
        "--packages"
    ] + packages

    try:
        subprocess.run(build_cmd, check=True)
    except subprocess.CalledProcessError:
        print("\n❌ Build phase failed. See output above.")
        sys.exit(1)

    # Phase 2: Deploy (Root space)
    source_raw = os.path.join(CACHE_DIR, f"{name}.raw")
    dest_raw = os.path.join(EXTENSIONS_DIR, f"{name}.raw")

    if not os.path.exists(source_raw):
        print(f"\n❌ Expected build output not found at {source_raw}")
        sys.exit(1)

    print(f"\n📦 Deploying '{name}' to system...")
    shell_cmd = f"mkdir -p {EXTENSIONS_DIR} && mv -f {source_raw} {dest_raw} && systemd-sysext refresh && sleep 2 && systemd-tmpfiles --create"

    if run_pkexec_cmd(shell_cmd, f"deploy {name}"):
        print(f"✅ Extension '{name}' successfully built and activated.")

def main():
    parser = argparse.ArgumentParser(description="Sysext Creator Pro - CLI Interface")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # List command
    subparsers.add_parser("list", help="List active extensions")

    # Remove command
    parser_remove = subparsers.add_parser("remove", help="Remove an extension")
    parser_remove.add_argument("name", help="Name of the extension to remove")

    # Doctor command
    subparsers.add_parser("doctor", help="Run system diagnostics")

    # Install command
    parser_install = subparsers.add_parser("install", help="Build and deploy an extension")
    parser_install.add_argument("name", help="Name of the resulting extension")
    parser_install.add_argument("packages", nargs="*", help="List of DNF packages to include")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "remove":
        cmd_remove(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "install":
        cmd_install(args)

if __name__ == "__main__":
    main()
