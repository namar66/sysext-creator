#!/usr/bin/python3

# Sysext-Creator Builder v3.1
# Environment: Fedora Toolbox
# Features: GPG Verification, Local RPM support, Host Repo/SELinux sync, Auto-deps

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

def log(msg: str): logging.info(msg)
def log_warn(msg: str): logging.warning(msg)
def log_error(msg: str): logging.error(msg)

def run_cmd(cmd, cwd=None):
    try:
        result = subprocess.run(cmd, check=True, cwd=cwd, shell=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {cmd}\nStderr: {e.stderr}")
        sys.exit(e.returncode or 1)

def check_and_install_dependencies():
    """Ensure all required tools are available inside the container."""
    required = {"mkfs.erofs": "erofs-utils", "rpm2cpio": "rpm", "cpio": "cpio"}
    missing = [pkg for cmd, pkg in required.items() if shutil.which(cmd) is None]
    
    # Check for dnf download plugin
    if subprocess.run(["dnf", "download", "--help"], capture_output=True).returncode != 0:
        missing.append("dnf-plugins-core")

    if missing:
        log(f"Installing missing build tools: {', '.join(missing)}")
        run_cmd(f"sudo dnf install -y {' '.join(missing)}")

def verify_gpg_signatures(rpms_dir: Path):
    """Checks GPG signatures of all downloaded RPMs."""
    log("Verifying GPG signatures...")
    failed = []
    for rpm in rpms_dir.glob("*.rpm"):
        # rpm -K checks signatures and digests
        res = subprocess.run(["rpm", "-K", str(rpm)], capture_output=True, text=True)
        if "OK" not in res.stdout:
            failed.append(rpm.name)
    
    if failed:
        log_error(f"GPG check FAILED for: {', '.join(failed)}")
        log_error("Aborting build. Use --nogpgcheck to bypass if you trust these sources.")
        sys.exit(2)
    log("GPG verification successful.")

def get_package_version(name, rpms_dir):
    try:
        # Get the version of the main package
        cmd = f"rpm -qp --qf '%{{VERSION}}' {rpms_dir}/{name}*.rpm | head -n 1"
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except: return "unknown"

def main():
    parser = argparse.ArgumentParser(description="Sysext Builder v3.1")
    parser.add_argument("name", help="Name of the resulting extension")
    parser.add_argument("packages", nargs='+', help="Package names or local .rpm paths")
    parser.add_argument("--nogpgcheck", action="store_true", help="Skip GPG verification")
    args = parser.parse_args()

    check_and_install_dependencies()

    # Directory setup
    build_dir = Path("/var/tmp/sysext-builds") # Shared build dir
    build_dir.mkdir(parents=True, exist_ok=True)
    temp_root = build_dir / f".tmp_{args.name}"
    if temp_root.exists(): shutil.rmtree(temp_root)
    temp_root.mkdir()
    
    rpms_dir = temp_root / "rpms"
    rpms_dir.mkdir()

    # 1. Distinguish between local RPMs and Repo packages
    local_rpms = [p for p in args.packages if p.endswith('.rpm') and os.path.isfile(p)]
    repo_pkgs = [p for p in args.packages if p not in local_rpms]

    if local_rpms:
        log(f"Handling local RPMs: {local_rpms}")
        for rpm in local_rpms: shutil.copy2(rpm, rpms_dir)

    if repo_pkgs:
        host_repos = Path("/run/host/etc/yum.repos.d")
        repo_args = f"--setopt=reposdir={host_repos}" if host_repos.exists() else ""
        log(f"Downloading from repos: {repo_pkgs}")
        run_cmd(f"dnf download {repo_args} --destdir={rpms_dir} --resolve {' '.join(repo_pkgs)}")

    # 2. Security Check
    if not args.nogpgcheck:
        verify_gpg_signatures(rpms_dir)
    else:
        log_warn("GPG verification skipped by user.")

    # 3. Extraction
    rootfs = temp_root / "rootfs"
    rootfs.mkdir()
    log("Extracting packages...")
    for rpm in rpms_dir.glob("*.rpm"):
        run_cmd(f"rpm2cpio {rpm} | cpio -idm --quiet", cwd=rootfs)

    # 4. Metadata and Versioning
    ver = get_package_version(args.name, rpms_dir)
    # Detect host version
    try:
        v_id = run_cmd("grep '^VERSION_ID=' /run/host/etc/os-release | cut -d'=' -f2").strip().strip('"')
    except: v_id = "41"

    meta = (f"ID=fedora\nVERSION_ID={v_id}\nSYSEXT_LEVEL=1.0\n"
            f"SYSEXT_VERSION_ID={ver}\nSYSEXT_CREATOR_PKGS=\"{' '.join(args.packages)}\"\n")

    # 5. Build Image with Host SELinux context
    selinux_opt = ""
    h_fc = Path("/run/host/etc/selinux/targeted/contexts/files/file_contexts")
    if h_fc.exists():
        selinux_opt = f"--file-contexts={h_fc}"
        log("Using Host SELinux contexts.")

    log("Finalizing EROFS images...")
    output_base = Path.home() / "sysext-builds"
    output_base.mkdir(exist_ok=True)

    # USR Layer
    usr_stage = temp_root / "stage_usr"
    usr_stage.mkdir()
    for d in ["usr", "opt"]:
        if (rootfs / d).exists(): shutil.move(str(rootfs / d), str(usr_stage / d))
    
    if (usr_stage / "usr").exists():
        rel_dir = usr_stage / "usr/lib/extension-release.d"
        rel_dir.mkdir(parents=True, exist_ok=True)
        (rel_dir / f"extension-release.{args.name}").write_text(meta)
        run_cmd(f"mkfs.erofs -zlz4hc {selinux_opt} {output_base}/{args.name}.raw {usr_stage}")

    # ETC Layer (Configuration Extension)
    if (rootfs / "etc").exists():
        etc_stage = temp_root / "stage_etc"
        etc_stage.mkdir()
        shutil.move(str(rootfs / "etc"), str(etc_stage / "etc"))
        rel_dir = etc_stage / "etc/extension-release.d"
        rel_dir.mkdir(parents=True, exist_ok=True)
        (rel_dir / f"extension-release.{args.name}").write_text(meta)
        run_cmd(f"mkfs.erofs -zlz4hc {selinux_opt} {output_base}/{args.name}.confext.raw {etc_stage}")

    shutil.rmtree(temp_root)
    log(f"Successfully built {args.name} version {ver}")

if __name__ == "__main__":
    main()
