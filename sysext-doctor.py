#!/usr/bin/python3
# Sysext Doctor v3.2.4
# System diagnostics for systemd-sysext, F45 repo layouts, and orphan /etc symlinks

import os
import sys
import subprocess
import shutil

EXTENSIONS_DIR = "/var/lib/extensions"
MANIFEST_DIR = "/usr/share/sysext/manifests"
TEMPLATE_DIR = "/usr/lib/sysext-creator/etc-template"
SELINUX_CONTEXTS = "/etc/selinux/targeted/contexts/files/file_contexts"
F45_REPOS_DIR = "/usr/share/dnf5/repos.d"
LEGACY_REPOS_DIR = "/etc/yum.repos.d"

PASS = "[\033[92mPASS\033[0m]"
WARN = "[\033[93mWARN\033[0m]"
FAIL = "[\033[91mFAIL\033[0m]"
INFO = "[\033[94mINFO\033[0m]"


def check_root():
    if os.geteuid() != 0:
        print(f"{FAIL} Sysext doctor requires root privileges. Run with pkexec or sudo.")
        sys.exit(1)


def get_os_release():
    data = {}
    for path in ["/usr/lib/os-release", "/etc/os-release"]:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        data[k] = v.strip('"\'')
            break
    return data


def check_systemd_sysext_status():
    print(f"\n{INFO} Checking systemd-sysext service and status...")
    if shutil.which("systemd-sysext") is None:
        print(f"{FAIL} systemd-sysext binary not found in PATH.")
        return

    res = subprocess.run(["systemd-sysext", "status"], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"{PASS} systemd-sysext is operational.")
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        for line in lines[:5]:
            print(f"      {line}")
    else:
        print(f"{WARN} systemd-sysext status returned code {res.returncode}: {res.stderr.strip()}")


def check_directories():
    print(f"\n{INFO} Checking extension directories and permissions...")
    if not os.path.exists(EXTENSIONS_DIR):
        print(f"{WARN} Extensions directory {EXTENSIONS_DIR} does not exist yet.")
    else:
        exts = [f for f in os.listdir(EXTENSIONS_DIR) if f.endswith(".raw")]
        print(f"{PASS} {EXTENSIONS_DIR} exists (contains {len(exts)} .raw images).")

    if not os.path.exists(MANIFEST_DIR):
        print(f"{WARN} Manifests directory {MANIFEST_DIR} does not exist.")
    else:
        manifests = [f for f in os.listdir(MANIFEST_DIR) if f.endswith(".txt")]
        print(f"{PASS} {MANIFEST_DIR} exists (contains {len(manifests)} manifests).")


def check_toolbox_environment():
    print(f"\n{INFO} Checking Toolbox container environment...")
    toolbox_bin = shutil.which("toolbox")
    if not toolbox_bin:
        print(f"{WARN} 'toolbox' binary not found on host.")
        return

    # Check if sysext-builder container exists
    res = subprocess.run(["toolbox", "list", "-c"], capture_output=True, text=True)
    if "sysext-builder" in res.stdout:
        print(f"{PASS} Container 'sysext-builder' is provisioned.")
    else:
        print(f"{WARN} Container 'sysext-builder' not found in toolbox list.")
        print("      Create it with: toolbox create -c sysext-builder")


def check_f45_repos():
    print(f"\n{INFO} Checking Fedora 45+ repository layouts...")
    os_info = get_os_release()
    version_id = os_info.get("VERSION_ID", "")

    if os.path.exists(F45_REPOS_DIR):
        repos = [f for f in os.listdir(F45_REPOS_DIR) if f.endswith(".repo")]
        print(f"{PASS} Modern DNF5 repo directory found: {F45_REPOS_DIR} ({len(repos)} repo files).")
    else:
        if version_id and version_id >= "45":
            print(f"{WARN} Running Fedora >= 45 but {F45_REPOS_DIR} is missing.")
        else:
            print(f"{INFO} {F45_REPOS_DIR} not present (expected on legacy releases).")

    if os.path.exists(LEGACY_REPOS_DIR):
        repos = [f for f in os.listdir(LEGACY_REPOS_DIR) if f.endswith(".repo")]
        print(f"{INFO} Legacy repo directory: {LEGACY_REPOS_DIR} ({len(repos)} user/custom repo files).")


def check_selinux_contexts():
    print(f"\n{INFO} Checking SELinux context configuration...")
    if os.path.exists(SELINUX_CONTEXTS):
        print(f"{PASS} SELinux file contexts available at {SELINUX_CONTEXTS}.")
    else:
        print(f"{WARN} SELinux file contexts missing at {SELINUX_CONTEXTS}. EROFS images might lack proper labels.")


def check_extension_os_matching():
    print(f"\n{INFO} Validating extension release matching against current OS...")
    os_info = get_os_release()
    current_os_id = os_info.get("ID")
    current_ver_id = os_info.get("VERSION_ID")

    release_d = "/usr/lib/extension-release.d"
    if not os.path.exists(release_d):
        print(f"{INFO} No active extensions mounted in {release_d}.")
        return

    mismatches = 0
    for rel_file in os.listdir(release_d):
        if not rel_file.startswith("extension-release."):
            continue
        ext_name = rel_file.split("extension-release.", 1)[1]
        path = os.path.join(release_d, rel_file)

        ext_id, ext_ver = None, None
        try:
            with open(path, "r") as f:
                for line in f:
                    if line.startswith("ID="):
                        ext_id = line.strip().split("=", 1)[1].strip('"\'')
                    elif line.startswith("VERSION_ID="):
                        ext_ver = line.strip().split("=", 1)[1].strip('"\'')
        except Exception as e:
            print(f"{WARN} Could not read {path}: {e}")
            continue

        if ext_id != current_os_id or (ext_ver != current_ver_id and ext_ver != "any"):
            print(f"{WARN} Extension '{ext_name}' release mismatch: "
                  f"built for {ext_id}={ext_ver}, host is {current_os_id}={current_ver_id}.")
            mismatches += 1

    if mismatches == 0:
        print(f"{PASS} All mounted extensions match host OS release.")


def check_orphan_etc_symlinks():
    print(f"\n{INFO} Scanning for dangling /etc symlinks pointing to sysext templates...")
    orphan_links = []

    for root, dirs, files in os.walk("/etc"):
        for name in files + dirs:
            full_path = os.path.join(root, name)
            if os.path.islink(full_path):
                try:
                    target = os.readlink(full_path)
                    # Detect links pointing to sysext creator template directory
                    if target.startswith("/usr/lib/sysext-creator/etc-template") or target.startswith(TEMPLATE_DIR):
                        # Verify if destination target actually exists
                        if not os.path.exists(full_path):
                            orphan_links.append((full_path, target))
                except OSError:
                    continue

    if orphan_links:
        print(f"{FAIL} Found {len(orphan_links)} orphaned symlink(s) in /etc:")
        for link, target in orphan_links:
            print(f"      - {link} -> {target}")
        print("\n      Clean them up by running:")
        cmd_fix = "rm -f " + " ".join(f"'{l}'" for l, _ in orphan_links)
        print(f"      {cmd_fix}")
    else:
        print(f"{PASS} No orphaned sysext symlinks found in /etc.")


def main():
    check_root()
    print("=" * 60)
    print("  Sysext Creator Doctor v3.2 - Diagnostic Report")
    print("=" * 60)

    check_systemd_sysext_status()
    check_directories()
    check_toolbox_environment()
    check_f45_repos()
    check_selinux_contexts()
    check_extension_os_matching()
    check_orphan_etc_symlinks()

    print("\n" + "=" * 60)
    print("  Diagnostics complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
