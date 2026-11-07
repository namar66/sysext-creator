#!/usr/bin/python3
# Sysext Creator CLI v3.2
# Safe input escaping, clean /etc symlink cleanup on removal, update command

import os
import sys
import re
import argparse
import subprocess
import shlex

CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")
EXTENSIONS_DIR = "/var/lib/extensions"
MANIFEST_DIR = "/usr/share/sysext/manifests"
BIN_DIR = os.path.expanduser("~/.local/bin")

def validate_name(name):
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
        print(f"❌ Error: Invalid extension name '{name}'. Use only letters, digits, '-', '_' and '.'.")
        sys.exit(1)

def run_pkexec_cmd(cmd_string, action_name):
    """Executes a shell command via pkexec."""
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

def get_human_size(path):
    try:
        size = os.path.getsize(path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    except Exception:
        return "Unknown"

def cmd_list(args):
    """Lists all installed and active extensions."""
    if not os.path.exists(EXTENSIONS_DIR):
        print("No extensions directory found.")
        return

    exts = [f[:-4] for f in os.listdir(EXTENSIONS_DIR) if f.endswith(".raw")]
    if not exts:
        print("No active extensions found.")
        return

    print(f"{'NAME':<22} | {'VERSION':<12} | {'PACKAGES':<10} | {'SIZE':<10} | {'STATUS'}")
    print("-" * 70)

    for name in sorted(exts):
        count = "Unknown"
        version = "unknown"
        manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
        version_path = os.path.join(MANIFEST_DIR, f"{name}.version")
        raw_path = os.path.join(EXTENSIONS_DIR, f"{name}.raw")

        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r') as f:
                    count = str(sum(1 for line in f if line.strip()))
            except Exception:
                pass

        if os.path.exists(version_path):
            try:
                with open(version_path, 'r') as f:
                    version = f.read().strip()
            except Exception:
                pass

        size_str = get_human_size(raw_path)
        print(f"{name:<22} | {version:<12} | {count:<10} | {size_str:<10} | Active")

def cmd_remove(args):
    """Removes an extension and purges its /etc symlinks cleanly."""
    name = args.name
    validate_name(name)

    raw_path = os.path.join(EXTENSIONS_DIR, f"{name}.raw")
    cache_path = os.path.join(CACHE_DIR, f"{name}.raw")
    etc_manifest = os.path.join(MANIFEST_DIR, f"{name}-etc.txt")

    if not os.path.exists(raw_path):
        print(f"❌ Extension '{name}' is not currently active.")
        sys.exit(1)

    print(f"🗑️  Removing extension '{name}'...")

    # Read /etc symlinks while layer is still mounted
    etc_links_to_remove = []
    if os.path.exists(etc_manifest):
        try:
            with open(etc_manifest, 'r') as f:
                etc_links_to_remove = [line.strip() for line in f if line.strip()]
        except Exception:
            pass

    # Build clean shell removal script
    cleanup_cmds = []
    for rel_f in etc_links_to_remove:
        full_etc_link = os.path.join("/etc", rel_f)
        cleanup_cmds.append(f"[ -L {shlex.quote(full_etc_link)} ] && rm -f {shlex.quote(full_etc_link)}")

    cleanup_cmds.append(f"rm -f {shlex.quote(raw_path)} {shlex.quote(cache_path)}")
    cleanup_cmds.append("systemd-sysext refresh")
    cleanup_cmds.append("systemd-tmpfiles --create")

    full_shell_cmd = " && ".join(cleanup_cmds)

    if run_pkexec_cmd(full_shell_cmd, f"remove {name}"):
        print(f"✅ Extension '{name}' successfully removed and cleaned up.")

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
    validate_name(name)
    packages = args.packages

    if not packages:
        packages = [name]

    print(f"🚀 Building extension '{name}' with packages: {', '.join(packages)}")

    builder_script = os.path.join(BIN_DIR, "sysext-creator-builder.py")
    if not os.path.exists(builder_script):
        print(f"❌ Builder script not found at {builder_script}")
        sys.exit(1)

    # Phase 1: Build in Toolbox
    build_cmd = [
        "toolbox", "run", "-c", "sysext-builder",
        "python3", builder_script,
        "--name", name,
        "--packages"
    ] + packages

    try:
        subprocess.run(build_cmd, check=True)
    except subprocess.CalledProcessError:
        print("\n❌ Build phase failed.")
        sys.exit(1)

    # Phase 2: Deploy to Root space
    source_raw = os.path.join(CACHE_DIR, f"{name}.raw")
    dest_raw = os.path.join(EXTENSIONS_DIR, f"{name}.raw")

    if not os.path.exists(source_raw):
        print(f"\n❌ Expected build output not found at {source_raw}")
        sys.exit(1)

    print(f"\n📦 Deploying '{name}' to system...")
    shell_cmd = (
        f"mkdir -p {shlex.quote(EXTENSIONS_DIR)} && "
        f"mv -f {shlex.quote(source_raw)} {shlex.quote(dest_raw)} && "
        f"systemd-sysext refresh && "
        f"systemd-tmpfiles --create"
    )

    if run_pkexec_cmd(shell_cmd, f"deploy {name}"):
        print(f"✅ Extension '{name}' successfully built and activated.")

def cmd_update(args):
    """Rebuilds and refreshes existing extensions."""
    if args.all:
        if not os.path.exists(EXTENSIONS_DIR):
            print("No extensions found to update.")
            return
        targets = [f[:-4] for f in os.listdir(EXTENSIONS_DIR) if f.endswith(".raw")]
    else:
        if not args.name:
            print("❌ Specify an extension name or use --all.")
            sys.exit(1)
        targets = [args.name]

    for name in targets:
        validate_name(name)
        manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
        if not os.path.exists(manifest_path):
            print(f"⚠️  Manifest not found for '{name}' at {manifest_path}. Skipping.")
            continue

        with open(manifest_path, "r") as f:
            packages = [line.strip() for line in f if line.strip()]

        print(f"\n🔄 Updating extension '{name}' ({', '.join(packages)})...")
        args_install = argparse.Namespace(name=name, packages=packages)
        cmd_install(args_install)

def main():
    parser = argparse.ArgumentParser(description="Sysext Creator Pro - CLI Interface")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    subparsers.add_parser("list", help="List active extensions")

    parser_remove = subparsers.add_parser("remove", help="Remove an extension")
    parser_remove.add_argument("name", help="Name of the extension to remove")

    subparsers.add_parser("doctor", help="Run system diagnostics")

    parser_install = subparsers.add_parser("install", help="Build and deploy an extension")
    parser_install.add_argument("name", help="Name of the resulting extension")
    parser_install.add_argument("packages", nargs="*", help="List of DNF packages to include")

    parser_update = subparsers.add_parser("update", help="Update installed extensions")
    parser_update.add_argument("name", nargs="?", help="Extension to update")
    parser_update.add_argument("--all", action="store_true", help="Update all active extensions")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "remove":
        cmd_remove(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "update":
        cmd_update(args)

if __name__ == "__main__":
    main()
