#!/usr/bin/python3

# Sysext-Builder v12.5
# Environment: Fedora Toolbox

import os
import sys
import shutil
import argparse
import subprocess
import re
import datetime
from pathlib import Path

def run_cmd(cmd, cwd=None):
    try:
        subprocess.run(cmd, check=True, cwd=cwd, shell=True)
    except subprocess.CalledProcessError:
        print(f"Error: Command failed: {cmd}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("packages", nargs='+')
    args = parser.parse_args()

    build_dir = Path.home() / "sysext-builds"
    build_dir.mkdir(exist_ok=True)
    temp_root = build_dir / f".tmp_{args.name}"
    if temp_root.exists(): shutil.rmtree(temp_root)
    temp_root.mkdir()

    # Download and Extract
    rpms_dir = temp_root / "rpms"
    rpms_dir.mkdir()
    print(f"Downloading packages: {args.packages}")
    run_cmd(f"dnf download --destdir={rpms_dir} {' '.join(args.packages)}")

    rootfs = temp_root / "rootfs"
    rootfs.mkdir()
    for rpm in rpms_dir.glob("*.rpm"):
        run_cmd(f"rpm2cpio {rpm} | cpio -idm --quiet", cwd=rootfs)

    # Metadata
    v_id = "43" # Targeted for your Fedora version
    sysext_version = datetime.datetime.now().strftime("%Y%m%d")
    meta_content = (
        f"ID=fedora\n"
        f"VERSION_ID={v_id}\n"
        f"SYSEXT_VERSION_ID={sysext_version}\n"
        f"SYSEXT_CREATOR_PACKAGES=\"{' '.join(args.packages)}\"\n"
    )

    # Build /usr and /opt layer
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
        run_cmd(f"mkfs.erofs -zlz4hc {build_dir / args.name}.raw {usr_stage}")

    # Build /etc layer (confext)
    if (rootfs / "etc").exists():
        etc_stage = temp_root / "stage_etc"
        etc_stage.mkdir()
        shutil.move(str(rootfs / "etc"), str(etc_stage / "etc"))
        rel_dir = etc_stage / "etc/extension-release.d"
        rel_dir.mkdir(parents=True, exist_ok=True)
        # Naming inside remains clean (without .confext)
        with open(rel_dir / f"extension-release.{args.name}", "w") as f:
            f.write(meta_content)
        run_cmd(f"mkfs.erofs -zlz4hc {build_dir / args.name}.confext.raw {etc_stage}")

    shutil.rmtree(temp_root)
    print("Build finished.")

if __name__ == "__main__":
    main()
