#!/usr/bin/python3

# Sysext-Builder v3.0 - SELinux Contexts & Advanced Logging
# Environment: Fedora Toolbox

import os
import sys
import shutil
import argparse
import subprocess
import re
import datetime
import logging
from pathlib import Path

LOG_DIR = Path.home() / ".local/state/sysext-creator"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "builder.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def log(msg: str):
    logging.info(msg)

def log_debug(msg: str):
    logging.debug(msg)

def log_error(msg: str):
    logging.error(msg)

def run_cmd(cmd, cwd=None):
    log(f"Executing: {cmd}")
    try:
        result = subprocess.run(cmd, check=True, cwd=cwd, shell=True, capture_output=True, text=True)
        if result.stdout: log_debug(f"Stdout:\n{result.stdout}")
        if result.stderr: log_debug(f"Stderr:\n{result.stderr}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd}\nRC: {e.returncode}\nStdout: {e.stdout}\nStderr: {e.stderr}")
        sys.exit(e.returncode or 1)

def resolve_host_dependencies(packages):
    if not packages: return []
    log("Resolving dependencies against host via rpm-ostree...")
    pkg_str = " ".join(packages)
    cmd = f"flatpak-spawn --host rpm-ostree install --dry-run {pkg_str}"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True, check=True)
        resolved = set()
        for line in result.stdout.splitlines():
            match = re.search(r"^\s+(\S+)", line)
            if match and not any(x in line.lower() for x in ["installing", "added:", "packages:"]):
                full_nvr = match.group(1)
                if '.' in full_nvr:
                    parts = full_nvr.split('.')
                    arch = parts[-1]
                    name_part = re.split(r'-[0-9]', ".".join(parts[:-1]))[0]
                    resolved.add(f"{name_part}.{arch}")
        final_list = list(resolved) if resolved else packages
        log(f"Resolved list: {final_list}")
        return final_list
    except subprocess.CalledProcessError as e:
        log_error(f"Resolution failed, falling back to original list. Stderr:\n{e.stderr}")
        return packages

def get_package_version(name, rpms_dir):
    try:
        cmd = f"rpm -qp --qf '%{{VERSION}}' {rpms_dir}/{name}*.rpm"
        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception as e:
        log_error(f"Version detection failed: {e}")
    return "unknown"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("packages", nargs='+')
    args = parser.parse_args()

    log(f"=== Starting build for {args.name} ===")

    build_dir = Path.home() / "sysext-builds"
    build_dir.mkdir(exist_ok=True)
    temp_root = build_dir / f".tmp_{args.name}"
    if temp_root.exists(): shutil.rmtree(temp_root)
    temp_root.mkdir()

    resolved = resolve_host_dependencies(args.packages)
    rpms_dir = temp_root / "rpms"
    rpms_dir.mkdir()

    log("Downloading RPMs...")
    run_cmd(f"dnf download --destdir={rpms_dir} {' '.join(resolved)}")

    native_version = get_package_version(args.name, rpms_dir)

    rootfs = temp_root / "rootfs"
    rootfs.mkdir()
    log("Extracting RPMs...")
    for rpm in rpms_dir.glob("*.rpm"):
        run_cmd(f"rpm2cpio {rpm} | cpio -idm --quiet", cwd=rootfs)

    v_id = "43"
    meta_content = (
        f"ID=fedora\n"
        f"VERSION_ID={v_id}\n"
        f"SYSEXT_LEVEL=1.0\n"
        f"SYSEXT_VERSION_ID={native_version}\n"
        f"SYSEXT_CREATOR_PACKAGES=\"{' '.join(args.packages)}\"\n"
    )

    # Prepare SELinux contexts
    selinux_opt = ""
    fc_path = Path("/etc/selinux/targeted/contexts/files/file_contexts")
    if fc_path.exists():
        selinux_opt = f"--file-contexts={fc_path}"
        log("SELinux file contexts found and will be applied to the image.")
    else:
        log_error("WARNING: SELinux file_contexts not found! Image may have permission issues.")

    log("Building layers...")

    # ---------------- USR LAYER ----------------
    usr_stage = temp_root / "stage_usr"
    usr_stage.mkdir()

    has_usr = False
    for folder in ["usr", "opt"]:
        if (rootfs / folder).exists():
            shutil.move(str(rootfs / folder), str(usr_stage / folder))
            has_usr = True

    if has_usr:
        rel_dir = usr_stage / "usr/lib/extension-release.d"
        rel_dir.mkdir(parents=True, exist_ok=True)
        with open(rel_dir / f"extension-release.{args.name}", "w") as f:
            f.write(meta_content)

        img_usr = build_dir / f"{args.name}.raw"
        run_cmd(f"mkfs.erofs -zlz4hc {selinux_opt} {img_usr} {usr_stage}")

    # ---------------- ETC LAYER ----------------
    if (rootfs / "etc").exists():
        etc_stage = temp_root / "stage_etc"
        etc_stage.mkdir()
        shutil.move(str(rootfs / "etc"), str(etc_stage / "etc"))

        rel_dir = etc_stage / "etc/extension-release.d"
        rel_dir.mkdir(parents=True, exist_ok=True)
        with open(rel_dir / f"extension-release.{args.name}", "w") as f:
            f.write(meta_content)

        img_etc = build_dir / f"{args.name}.confext.raw"
        run_cmd(f"mkfs.erofs -zlz4hc {selinux_opt} {img_etc} {etc_stage}")

    shutil.rmtree(temp_root)
    log(f"=== Build finished successfully. Version: {native_version} ===")

if __name__ == "__main__":
    main()
