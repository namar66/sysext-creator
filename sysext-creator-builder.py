#!/usr/bin/python3

# Sysext-Creator Builder
# Uses rpm-ostree on the host to calculate the exact missing dependencies,
# synchronizes host repositories, downloads them via DNF, and builds EROFS images.

import os
import sys
import shutil
import logging
import argparse
import subprocess
import glob
import stat

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run_cmd(cmd, cwd=None, shell=False):
    """Executes a shell command and raises an exception on failure."""
    try:
        subprocess.run(cmd, cwd=cwd, shell=shell, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
        logging.error(f"Error output: {e.stderr}")
        sys.exit(1)

def force_rmtree(path):
    """Forces removal of a directory tree by fixing read-only permissions first."""
    if os.path.exists(path):
        subprocess.run(["chmod", "-R", "u+w", path], stderr=subprocess.DEVNULL)
        shutil.rmtree(path, ignore_errors=True)

def check_dependencies():
    """Ensures required tools are available inside the container."""
    tools = ["dnf", "rpm2cpio", "cpio", "mkfs.erofs", "rpm", "flatpak-spawn"]
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        logging.info(f"Installing missing tools: {', '.join(missing)}")
        run_cmd(["sudo", "dnf", "install", "-y"] + missing)

def sync_host_repositories():
    """
    Synchronizes DNF repositories and GPG keys from the host OS into the container.
    This ensures the container has access to the exact same packages (e.g., COPRs).
    """
    logging.info("Synchronizing repositories and GPG keys from host OS...")

    # Copy GPG keys
    if os.path.exists("/run/host/etc/pki/rpm-gpg"):
        run_cmd("sudo cp -r /run/host/etc/pki/rpm-gpg/* /etc/pki/rpm-gpg/ 2>/dev/null || true", shell=True)

    # Copy Repo definitions
    if os.path.exists("/run/host/etc/yum.repos.d"):
        run_cmd("sudo cp -r /run/host/etc/yum.repos.d/* /etc/yum.repos.d/ 2>/dev/null || true", shell=True)

def get_fedora_version():
    """Reads the current Fedora version from /etc/os-release."""
    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return line.strip().split("=")[1].strip('"')
    except Exception:
        pass
    return "43"

def calculate_host_dependencies(packages):
    """
    Queries the host OS via flatpak-spawn and rpm-ostree to find exactly
    which packages are missing from the base image.
    """
    logging.info("Calculating missing dependencies against the host OS using rpm-ostree...")
    cmd = ["flatpak-spawn", "--host", "rpm-ostree", "install", "--dry-run"] + packages

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"rpm-ostree failed. Are the package names correct? Error: {e.stderr}")
        sys.exit(1)

    pkg_list = []
    is_parsing = False

    for line in res.stdout.splitlines():
        line = line.strip()

        if line.startswith("Installing ") and "packages:" in line:
            is_parsing = True
            continue

        if (line.startswith("Upgrading ") or line.startswith("Removing ") or
            line.startswith("Downgrading ") or line.startswith("Exiting because")):
            is_parsing = False
            continue

        if is_parsing and line:
            parts = line.split()
            if parts:
                exact_pkg = parts[0]
                pkg_list.append(exact_pkg)

    return pkg_list

def create_package_manifest(name, rpm_dir, usr_staging, etc_staging):
    """Creates a manifest file containing the exact versions of all included packages."""
    rpm_files = glob.glob(os.path.join(rpm_dir, "*.rpm"))
    if not rpm_files:
        logging.warning("No RPM files found for manifest generation.")
        return

    logging.info("Generating full package manifest...")
    try:
        cmd = ["rpm", "-qp", "--queryformat", "%{NAME} %{VERSION}-%{RELEASE} (%{ARCH})\\n"] + rpm_files
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        manifest_content = "".join(sorted(res.stdout.splitlines(True)))

        if os.path.exists(os.path.join(usr_staging, "usr")):
            manifest_dir = os.path.join(usr_staging, "usr", "lib", "extension-release.d")
            os.makedirs(manifest_dir, exist_ok=True)
            with open(os.path.join(manifest_dir, f"{name}-packages.txt"), "w") as f:
                f.write(manifest_content)

        if os.path.exists(os.path.join(etc_staging, "etc")):
            manifest_dir = os.path.join(etc_staging, "etc", "extension-release.d")
            os.makedirs(manifest_dir, exist_ok=True)
            with open(os.path.join(manifest_dir, f"{name}-packages.txt"), "w") as f:
                f.write(manifest_content)

    except Exception as e:
        logging.error(f"Failed to write package manifest: {e}")

def create_metadata(name, target_dir, prefix, pkgs_str, version_id):
    """Creates the extension-release metadata file for systemd."""
    meta_dir = os.path.join(target_dir, prefix, "lib" if prefix == "usr" else "", "extension-release.d")
    os.makedirs(meta_dir, exist_ok=True)

    with open(os.path.join(meta_dir, f"extension-release.{name}"), "w") as f:
        f.write("ID=fedora\n")
        f.write(f"VERSION_ID={version_id}\n")
        f.write("SYSEXT_LEVEL=1.0\n")
        f.write(f"SYSEXT_CREATOR_PKGS={pkgs_str}\n")

def build_erofs_image(out_file, staging_dir):
    """
    Builds the EROFS image with forced root ownership and correct SELinux labels.
    This prevents system boot hangs caused by user-owned files in system directories.
    """
    cmd = [
        "mkfs.erofs",
        "-zlz4hc",
        "--force-uid=0",  # Vynutí vlastníka root
        "--force-gid=0",  # Vynutí skupinu root
        "-U", "clear"     # Vyčistí UUID pro čistší mount
    ]

    # Zkusíme použít SELinux databázi přímo z hostitele (přes Toolbox /run/host)
    selinux_contexts = "/run/host/etc/selinux/targeted/contexts/files/file_contexts"
    if not os.path.exists(selinux_contexts):
        selinux_contexts = "/etc/selinux/targeted/contexts/files/file_contexts"

    if os.path.exists(selinux_contexts):
        cmd.append(f"--file-contexts={selinux_contexts}")

    cmd.extend([out_file, staging_dir])
    run_cmd(cmd)

def fix_executable_etc(name, usr_staging, etc_staging):
    """
    Detects executable scripts in /etc (which would break due to confext noexec),
    moves them to /usr/libexec, and creates tmpfiles.d symlinks to link them back.
    """
    etc_dir = os.path.join(etc_staging, "etc")
    if not os.path.exists(etc_dir):
        return

    tmpfiles_content = []

    for root, _, files in os.walk(etc_dir):
        for file in files:
            filepath = os.path.join(root, file)

            # Check if it's a regular file and has executable bits set
            if os.path.isfile(filepath) and not os.path.islink(filepath):
                st = os.stat(filepath)
                if st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):

                    # 1. Calculate relative path (e.g., etc/sddm/Xsetup)
                    rel_path = os.path.relpath(filepath, etc_staging)

                    # 2. Define safe target location in /usr (mounted with exec)
                    usr_target = os.path.join(usr_staging, "usr", "libexec", "sysext-creator", rel_path)
                    os.makedirs(os.path.dirname(usr_target), exist_ok=True)

                    # 3. Move the executable file to the /usr layer
                    shutil.move(filepath, usr_target)
                    logging.info(f"Relocated executable config: /{rel_path} -> /usr/libexec/sysext-creator/{rel_path}")

                    # 4. Create tmpfiles.d instruction (L+ means create symlink, overwriting if needed)
                    # Format: L+ /etc/sddm/Xsetup - - - - /usr/libexec/sysext-creator/etc/sddm/Xsetup
                    tmpfiles_content.append(f"L+ /{rel_path} - - - - /usr/libexec/sysext-creator/{rel_path}\n")

    # If we moved anything, write the tmpfiles.d configuration
    if tmpfiles_content:
        tmpfiles_dir = os.path.join(usr_staging, "usr", "lib", "tmpfiles.d")
        os.makedirs(tmpfiles_dir, exist_ok=True)
        conf_path = os.path.join(tmpfiles_dir, f"99-sysext-{name}-exec-fix.conf")

        with open(conf_path, "w") as f:
            f.writelines(tmpfiles_content)
        logging.info(f"Generated tmpfiles.d workaround at {conf_path}")

def main():
    parser = argparse.ArgumentParser(description="Sysext EROFS Builder")
    parser.add_argument("name", help="Name of the extension")
    parser.add_argument("packages", nargs="+", help="RPM packages to install")
    args = parser.parse_args()

    name = args.name
    requested_packages = args.packages
    pkgs_str = " ".join(requested_packages)
    fedora_version = get_fedora_version()

    work_dir = "/var/tmp/sysext-builder"
    rpm_dir = os.path.join(work_dir, "rpms")
    extract_dir = os.path.join(work_dir, "extract")
    usr_staging = os.path.join(work_dir, "staging_usr")
    etc_staging = os.path.join(work_dir, "staging_etc")
    output_dir = os.path.expanduser("~/sysext-builds")

    force_rmtree(work_dir)

    for d in [rpm_dir, extract_dir, usr_staging, etc_staging, output_dir]:
        os.makedirs(d, exist_ok=True)

    check_dependencies()

    # NEW: Sync repos and keys right before we do anything network-related
    sync_host_repositories()

    exact_dependencies = calculate_host_dependencies(requested_packages)

    if not exact_dependencies:
        logging.error("No packages to download. They might already be part of the base OS.")
        sys.exit(1)

    logging.info(f"Host requires {len(exact_dependencies)} packages. Downloading...")
    run_cmd(["dnf", "download", "--destdir", rpm_dir] + exact_dependencies)

    logging.info("Verifying GPG signatures...")
    rpm_files = glob.glob(os.path.join(rpm_dir, "*.rpm"))
    run_cmd(["rpmkeys", "--checksig"] + rpm_files)

    logging.info("Extracting packages...")
    for rpm in rpm_files:
        run_cmd(f"rpm2cpio {rpm} | cpio -idmv", cwd=extract_dir, shell=True)

    has_usr = False
    has_etc = False

    if os.path.exists(os.path.join(extract_dir, "usr")):
        shutil.move(os.path.join(extract_dir, "usr"), os.path.join(usr_staging, "usr"))
        create_metadata(name, usr_staging, "usr", pkgs_str, fedora_version)
        has_usr = True

    if os.path.exists(os.path.join(extract_dir, "etc")):
        shutil.move(os.path.join(extract_dir, "etc"), os.path.join(etc_staging, "etc"))
        create_metadata(name, etc_staging, "etc", pkgs_str, fedora_version)
        has_etc = True

        fix_executable_etc(name, usr_staging, etc_staging)
        has_usr = True # Ensure usr image is created since we might have moved files there

    create_package_manifest(name, rpm_dir, usr_staging, etc_staging)

    logging.info("Finalizing EROFS images...")

    if has_usr:
        out_file = os.path.join(output_dir, f"{name}.raw")
        if os.path.exists(out_file): os.remove(out_file)
        build_erofs_image(out_file, usr_staging)
        logging.info(f"Created: {out_file}")

    if has_etc:
        out_file = os.path.join(output_dir, f"{name}.confext.raw")
        if os.path.exists(out_file): os.remove(out_file)
        run_cmd(["mkfs.erofs", "-zlz4hc", out_file, etc_staging])
        logging.info(f"Created: {out_file}")

    force_rmtree(work_dir)
    logging.info(f"Successfully built extension '{name}'")

if __name__ == "__main__":
    main()
