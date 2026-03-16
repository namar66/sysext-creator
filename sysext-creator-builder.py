#!/usr/bin/python3

# Sysext-Builder v3.1-dev
# Environment: Fedora Toolbox
# Features: Auto-dependency check, Host Repo sync, Host SELinux contexts

import os
import sys
import shutil
import argparse
import subprocess
import re
import logging
from pathlib import Path

# Setup logging
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

def check_and_install_dependencies():
    """
    Check if required build tools are available inside the Toolbox container.
    If they are missing, install them automatically using dnf.
    """
    required_tools = {
        "mkfs.erofs": "erofs-utils",
        "rpm2cpio": "rpm",
        "cpio": "cpio"
    }
    
    missing_packages = set()
    
    # Check for basic binary commands
    for cmd, pkg in required_tools.items():
        if shutil.which(cmd) is None:
            missing_packages.add(pkg)
            
    # Check if 'dnf download' plugin is available (usually in dnf-plugins-core)
    res = subprocess.run(["dnf", "download", "--help"], capture_output=True, text=True)
    if res.returncode != 0:
        missing_packages.add("dnf-plugins-core")

    # Install missing dependencies automatically
    if missing_packages:
        log(f"Missing build tools detected. Installing: {', '.join(missing_packages)}")
        # In Toolbox, 'sudo dnf' works without asking for a password
        install_cmd = f"sudo dnf install -y {' '.join(missing_packages)}"
        run_cmd(install_cmd)
        log("Build dependencies successfully installed.")

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
    
    # 1. Ensure the Toolbox has all necessary tools before we begin
    check_and_install_dependencies()
    
    build_dir = Path.home() / "sysext-builds"
    build_dir.mkdir(exist_ok=True)
    temp_root = build_dir / f".tmp_{args.name}"
    if temp_root.exists(): shutil.rmtree(temp_root)
    temp_root.mkdir()

    resolved = resolve_host_dependencies(args.packages)
    rpms_dir = temp_root / "rpms"
    rpms_dir.mkdir()
    
    # 2. Map DNF to host's repositories if available
    host_repos = Path("/run/host/etc/yum.repos.d")
    repo_args = f"--setopt=reposdir={host_repos}" if host_repos.exists() else ""
    
    log("Downloading RPMs (using host repositories if available)...")
    run_cmd(f"dnf download {repo_args} --destdir={rpms_dir} {' '.join(resolved)}")

    native_version = get_package_version(args.name, rpms_dir)
    
    rootfs = temp_root / "rootfs"
    rootfs.mkdir()
    log("Extracting RPMs...")
    for rpm in rpms_dir.glob("*.rpm"):
        run_cmd(f"rpm2cpio {rpm} | cpio -idm --quiet", cwd=rootfs)

    # 3. Determine correct OS VERSION_ID from host
    try:
        host_os_release = subprocess.run(
            "flatpak-spawn --host grep '^VERSION_ID=' /etc/os-release | cut -d'=' -f2", 
            shell=True, capture_output=True, text=True
        )
        v_id = host_os_release.stdout.strip() or "43"
    except:
        v_id = "43"

    meta_content = (
        f"ID=fedora\n"
        f"VERSION_ID={v_id}\n"
        f"SYSEXT_LEVEL=1.0\n"
        f"SYSEXT_VERSION_ID={native_version}\n"
        f"SYSEXT_CREATOR_PACKAGES=\"{' '.join(args.packages)}\"\n"
    )

    # 4. Prepare SELinux contexts (Prioritize Host OS)
    selinux_opt = ""
    host_fc = Path("/run/host/etc/selinux/targeted/contexts/files/file_contexts")
    container_fc = Path("/etc/selinux/targeted/contexts/files/file_contexts")

    if host_fc.exists():
        selinux_opt = f"--file-contexts={host_fc}"
        log("Using HOST SELinux file contexts.")
    elif container_fc.exists():
        selinux_opt = f"--file-contexts={container_fc}"
        log("Using CONTAINER SELinux file contexts.")

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
