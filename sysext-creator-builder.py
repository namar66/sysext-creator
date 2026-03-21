#!/usr/bin/python3

# Sysext-Creator Builder v4.1
# Features: EROFS, Host-Aware Dependencies, Robust NEVRA Parsing

import os
import sys
import subprocess
import shutil
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run_cmd(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(cmd)}")
        logging.error(f"Error output: {e.stderr}")
        sys.exit(1)

def check_dependencies():
    dependencies = {
        "mkfs.erofs": "erofs-utils",
        "cpio": "cpio",
        "rpm2cpio": "rpm",
        "flatpak-spawn": "flatpak-spawn"
    }
    missing_pkgs = []
    for cmd, pkg in dependencies.items():
        if shutil.which(cmd) is None:
            missing_pkgs.append(pkg)

    if missing_pkgs:
        logging.info(f"Installing missing build tools: {' '.join(missing_pkgs)}")
        run_cmd(["sudo", "dnf", "install", "-y"] + list(set(missing_pkgs)))

def calculate_host_dependencies(packages):
    if not packages:
        return []

    logging.info("Calculating missing dependencies against host OS...")
    cmd = ["flatpak-spawn", "--host", "rpm-ostree", "install", "--dry-run"] + packages

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        output = res.stdout

        if "Already in target" in output or "No packages to install" in output:
            return []

        added_pkgs = []
        parsing_added = False
        # Robustní regex pro NEVRA (včetně volitelné Epochy a architektonické tečky)
        nevra_re = re.compile(r'^(.+?)-(([0-9]+:)?([^-]+)-([^-]+))\.(x86_64|noarch)$')

        for line in output.splitlines():
            if "Exiting because" in line: break
            if any(line.startswith(s) for s in ["Installing ", "Added:", "Upgrading ", "Upgraded:"]):
                parsing_added = True
                continue
            elif any(line.startswith(s) for s in ["Removing ", "Removed:"]):
                parsing_added = False
                continue

            if parsing_added and line.startswith(" "):
                raw_pkg = line.strip().split()[0]
                match = nevra_re.match(raw_pkg)
                if match:
                    name = match.group(1)
                    arch = match.group(6)
                    if arch in ["x86_64", "noarch"] and not ("debuginfo" in name or "debugsource" in name):
                        formatted = f"{name}.{arch}"
                        if formatted not in added_pkgs: added_pkgs.append(formatted)
                else:
                    if not raw_pkg.endswith(".src") and raw_pkg not in added_pkgs:
                        added_pkgs.append(raw_pkg)
        return added_pkgs
    except Exception as e:
        logging.warning(f"Dependency calculation failed: {e}")
        return packages

def build_erofs_image(out_file, staging_dir):
    if os.path.exists(out_file): os.remove(out_file)
    # mkfs.erofs s parametry pro reprodukovatelnost a systemd kompatibilitu
    cmd = ["mkfs.erofs", "-x1", "--all-root", "-U", "clear", "-T", "0", out_file, staging_dir]
    run_cmd(cmd)

def main():
    if len(sys.argv) < 3:
        logging.error("Usage: builder.py <name> <pkg1> [pkg2 ...]")
        sys.exit(1)

    check_dependencies()
    name = sys.argv[1]
    requested_packages = sys.argv[2:]

    output_dir = "/var/tmp/sysext-creator"
    os.makedirs(output_dir, exist_ok=True)

    build_dir = f"/var/tmp/sysext-build-{name}"
    dnf_dir = os.path.join(build_dir, "dnf-downloads")
    usr_staging = os.path.join(build_dir, "usr")

    if os.path.exists(build_dir): shutil.rmtree(build_dir)
    os.makedirs(dnf_dir, exist_ok=True)
    os.makedirs(usr_staging, exist_ok=True)

    local_rpms = []
    repo_packages = []

    for pkg in requested_packages:
        if pkg.endswith(".rpm") and os.path.isfile(pkg):
            if pkg.endswith(".src.rpm"):
                logging.warning(f"Skipping Source RPM: {pkg}")
                continue
            local_rpms.append(pkg)
        else:
            repo_packages.append(pkg)

    local_provided_names = []
    for rpm in local_rpms:
        try:
            out = subprocess.run(["rpm", "-qp", "--queryformat", "%{NAME}.%{ARCH}", rpm], capture_output=True, text=True).stdout.strip()
            if out: local_provided_names.append(out)
        except: pass

    all_pkgs = repo_packages + local_rpms
    missing_deps = calculate_host_dependencies(all_pkgs) if all_pkgs else []
    dnf_dl_list = [pkg for pkg in missing_deps if pkg not in local_provided_names]

    if dnf_dl_list:
        logging.info(f"Downloading {len(dnf_dl_list)} dependencies...")
        run_cmd(["dnf", "download", "-y", f"--destdir={dnf_dir}"] + dnf_dl_list)

    rpms_to_extract = local_rpms
    if os.path.exists(dnf_dir):
        for f in os.listdir(dnf_dir):
            if f.endswith(".rpm"): rpms_to_extract.append(os.path.join(dnf_dir, f))

    if not rpms_to_extract:
        logging.error("No packages to extract.")
        sys.exit(1)

    logging.info("Extracting RPMs...")
    for rpm_path in rpms_to_extract:
        ps = subprocess.Popen(["rpm2cpio", rpm_path], stdout=subprocess.PIPE)
        subprocess.run(["cpio", "-idmv"], stdin=ps.stdout, cwd=usr_staging, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ps.wait()

    # Metadata
    metadata_dir = os.path.join(usr_staging, "share/factory/sysext-metadata")
    os.makedirs(metadata_dir, exist_ok=True)
    metadata_pkgs = repo_packages + [os.path.basename(p) for p in local_rpms]
    with open(os.path.join(metadata_dir, "packages.txt"), "w") as f:
        f.write(" ".join(metadata_pkgs))

    out_file = os.path.join(output_dir, f"{name}.raw")
    build_erofs_image(out_file, usr_staging)
    logging.info(f"Build finished: {out_file}")

if __name__ == "__main__":
    main()
