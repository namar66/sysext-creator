#!/usr/bin/python3

# Sysext-Creator Builder v3.1.1
# Fixes: Automatic /etc migration via tmpfiles.d and Manifest generation for GUI

import os
import subprocess
import sys
import tempfile
import shutil
import logging
import re
import argparse

# ==========================================
# GLOBAL CONFIGURATION
# ==========================================
CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run_cmd(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e.stderr}")
        sys.exit(1)

def get_os_info():
    info = {"ID": "fedora", "VERSION_ID": "any"}
    try:
        path = "/run/host/etc/os-release"
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        info[k] = v.strip('"')
    except: pass
    return info

def get_rpm_version(rpm_path):
    query = "%|EPOCH?{%{EPOCH}:}:{}|%{VERSION}-%{RELEASE}"
    try:
        res = subprocess.run(["rpm", "-qp", f"--qf={query}", rpm_path], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except:
        return "unknown"

def calculate_host_dependencies(packages):
    if not packages: return []
    logging.info("Calculating missing dependencies against host OS...")
    cmd = ["flatpak-spawn", "--host", "rpm-ostree", "install", "--dry-run"] + packages
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

        # Abort immediately if rpm-ostree reports the package is already on the host
        if res.returncode != 0:
            combined_output = res.stderr + "\n" + res.stdout
            if "is already provided by" in combined_output:
                logging.error("Build aborted: One or more requested packages are already installed on the host OS.")
                logging.error(combined_output.strip())
                sys.exit(1)
            else:
                logging.warning(f"rpm-ostree dry-run returned an error: {combined_output.strip()}")

        arch_res = subprocess.run(["uname", "-m"], capture_output=True, text=True, check=True)
        host_arch = arch_res.stdout.strip()

        allowed_archs = ["noarch", host_arch]
        if host_arch == "x86_64": allowed_archs.append("i686")

        added_pkgs = []
        parsing_added = False

        # Dynamically build the regex pattern for allowed architectures
        arch_pattern = "|".join(allowed_archs)
        nevra_re = re.compile(fr'^(.+?)-(([0-9]+:)?([^-]+)-([^-]+))\.({arch_pattern})$')

        # Step 1: Parse the output from rpm-ostree dry-run
        for line in res.stdout.splitlines():
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
                    name_pkg, arch = match.group(1), match.group(6)
                    formatted = f"{name_pkg}.{arch}"
                    if formatted not in added_pkgs: added_pkgs.append(formatted)

        # Step 2: Filter out packages that are already present in the host RPM database (e.g., layered overlays)
        if added_pkgs:
            logging.info("Cross-checking with host RPM database to filter out existing overlays...")
            try:
                rpm_res = subprocess.run(
                    ["rpm", "--root", "/run/host", "-qa", "--qf", "%{NAME}.%{ARCH}\n"],
                    capture_output=True, text=True, check=True
                )
                host_pkgs = set(line.strip() for line in rpm_res.stdout.splitlines() if line.strip())

                filtered_pkgs = [p for p in added_pkgs if p not in host_pkgs]
                ignored_count = len(added_pkgs) - len(filtered_pkgs)

                if ignored_count > 0:
                    logging.info(f"Filtered out {ignored_count} packages already present on the host.")

                added_pkgs = filtered_pkgs
            except Exception as e:
                logging.warning(f"Failed to query host RPM database for filtering: {e}")

        # Final reporting
        if added_pkgs:
            logging.info(f"Found {len(added_pkgs)} packages to download (after filtering).")
        else:
            logging.info("No additional dependencies needed.")

        return added_pkgs
    except Exception as e:
        logging.error(f"Dependency calculation failed: {e}")
        sys.exit(1)

def sync_host_repos():
    """Synchronize repositories and GPG keys from the host to the toolbox."""
    logging.info("Syncing host repositories and GPG keys...")
    host_repos = "/run/host/etc/yum.repos.d"
    host_gpg = "/run/host/etc/pki/rpm-gpg"

    if os.path.exists(host_repos):
        try:
            subprocess.run(f"sudo cp -f {host_repos}/*.repo /etc/yum.repos.d/", shell=True)
        except: pass

    if os.path.exists(host_gpg):
        try:
            subprocess.run(["sudo", "mkdir", "-p", "/etc/pki/rpm-gpg"], check=True)
            subprocess.run(f"sudo cp -rf {host_gpg}/* /etc/pki/rpm-gpg/", shell=True)
            # Import keys into the toolbox RPM database
            for f in os.listdir(host_gpg):
                key_path = os.path.join("/etc/pki/rpm-gpg", f)
                if os.path.isfile(key_path) and not f.startswith("."):
                    subprocess.run(["sudo", "rpm", "--import", key_path], capture_output=True)
        except: pass

def verify_rpms(rpm_paths, is_local=False):
    """Verify GPG signatures of RPM packages. Local packages are checked but don't fail the build if unsigned."""
    if not rpm_paths: return

    label = "local" if is_local else "downloaded"
    logging.info(f"Verifying GPG signatures for {len(rpm_paths)} {label} packages...")

    for rpm in rpm_paths:
        try:
            # rpm -K (or --checksig) verifies the signature
            subprocess.run(["rpm", "-K", rpm], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            if is_local:
                logging.warning(f"Warning: Local package signature verification skipped/failed: {os.path.basename(rpm)}")
            else:
                logging.error(f"Error: GPG Verification FAILED for repo package: {os.path.basename(rpm)}")
                logging.error(f"Details: {e.stderr}")
                sys.exit(1)

    if not is_local:
        logging.info("All repository signatures verified successfully.")

def check_container_dependencies():
    """Ensure erofs-utils and dnf-plugins-core are installed in the toolbox."""
    logging.info("Checking container dependencies...")

    missing = []
    # Check mkfs.erofs (erofs-utils)
    if shutil.which("mkfs.erofs") is None:
        missing.append("erofs-utils")

    # Check dnf download (dnf-plugins-core)
    try:
        subprocess.run(["dnf", "download", "--help"], capture_output=True, check=True)
    except:
        missing.append("dnf-plugins-core")

    if missing:
        logging.warning(f"Missing dependencies in container: {', '.join(missing)}")
        logging.info("Attempting to install missing dependencies...")
        try:
            # Use sudo because toolbox usually requires it for dnf install
            subprocess.run(["sudo", "LANG=C", "dnf", "install", "-y"] + missing, check=True)
            logging.info("Dependencies installed successfully.")
        except Exception as e:
            logging.error(f"Failed to install dependencies: {e}")
            sys.exit(1)
    else:
        logging.info("All container dependencies are present.")

def prune_shadowed_files(staging_root):
    """
    Remove files from staging that are owned by host RPM packages.
    This prevents shadowing core system files while allowing updates
    of files provided by currently active sysexts (which are not in RPM DB).
    """
    logging.info("Fetching list of all files owned by host RPMs (this may take a moment)...")
    try:
        # Get all files owned by all installed packages on the host
        res = subprocess.run(["flatpak-spawn", "--host", "rpm", "-ql", "--all"],
                             capture_output=True, text=True, errors="replace")
        if res.returncode != 0:
            logging.warning("Failed to get host RPM file list. Skipping smart pruning.")
            return

        # Create a set of host-owned files for O(1) lookup
        host_owned_files = set(res.stdout.splitlines())
        logging.info(f"Indexed {len(host_owned_files)} system-owned files.")
    except Exception as e:
        logging.warning(f"Error during host RPM indexing: {e}. Skipping smart pruning.")
        return

    pruned_count = 0
    usr_staging = os.path.join(staging_root, "usr")
    if not os.path.exists(usr_staging):
        return

    for root, dirs, files in os.walk(usr_staging):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, staging_root)
            # Ensure path starts with / for matching
            abs_rel_path = "/" + rel_path

            # CRITICAL: Only prune if the file is explicitly owned by a host RPM
            if abs_rel_path in host_owned_files:
                try:
                    os.remove(full_path)
                    pruned_count += 1
                    logging.debug(f"Pruned shadowed system file: {abs_rel_path}")
                except Exception as e:
                    logging.warning(f"Failed to prune {abs_rel_path}: {e}")

    if pruned_count > 0:
        logging.info(f"Smart Pruning: Removed {pruned_count} files owned by the host OS.")
        # Cleanup empty directories
        for root, dirs, files in os.walk(usr_staging, topdown=False):
            for d in dirs:
                dir_path = os.path.join(root, d)
                if not os.listdir(dir_path):
                    try:
                        os.rmdir(dir_path)
                    except: pass
    else:
        logging.info("No host OS shadowing detected.")

def main():
    # Setup professional argument parsing
    parser = argparse.ArgumentParser(description="Sysext-Creator EROFS Builder")
    parser.add_argument("--name", required=True, help="Name of the resulting system extension")
    parser.add_argument("--packages", nargs='+', required=True, help="List of packages to include in the extension")

    args = parser.parse_args()

    name = args.name
    requested_packages = args.packages

    check_container_dependencies()
    sync_host_repos()

    os.makedirs(CACHE_DIR, exist_ok=True) # <-- Added safety check here

    build_dir = tempfile.mkdtemp(prefix=f"sysext-build-{name}-")
    staging_root = build_dir

    try:
        os.makedirs(staging_root, exist_ok=True)

        local_rpms = [p for p in requested_packages if p.endswith(".rpm") and os.path.isfile(p)]
        repo_packages = [p for p in requested_packages if p not in local_rpms]
        all_pkgs = repo_packages + local_rpms

        if local_rpms:
            verify_rpms(local_rpms, is_local=True)

        missing_deps = calculate_host_dependencies(all_pkgs)
        dnf_dir = os.path.join(build_dir, "dnf-downloads")
        os.makedirs(dnf_dir, exist_ok=True)

        if missing_deps:
            logging.info(f"Downloading {len(missing_deps)} packages to {dnf_dir}...")
            run_cmd(["dnf", "--refresh", "download", "-y", f"--destdir={dnf_dir}"] + missing_deps)
            # Verify GPG signatures of downloaded packages
            downloaded_rpms = [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]
            verify_rpms(downloaded_rpms, is_local=False)

        rpms_to_extract = local_rpms + [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]

        version = "unknown"
        for rpm in rpms_to_extract:
            if os.path.basename(rpm).startswith(name + "-"):
                version = get_rpm_version(rpm)
                break
        if version == "unknown" and rpms_to_extract:
            version = get_rpm_version(rpms_to_extract[0])

        logging.info(f"Detected version: {version}")

        for rpm in rpms_to_extract:
            ps = subprocess.Popen(["rpm2cpio", rpm], stdout=subprocess.PIPE)
            subprocess.run(["cpio", "-idmv"], stdin=ps.stdout, cwd=staging_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ps.wait()

        # --- SMART PRUNING ---
        prune_shadowed_files(staging_root)

        # --- /ETC PROCESSING ---
        etc_src = os.path.join(staging_root, "etc")
        if os.path.exists(etc_src):
            logging.info(f"Found /etc content in {name}. Migrating to tmpfiles.d...")
            etc_template_dir = f"usr/lib/sysext-creator/etc-template/{name}"
            full_template_path = os.path.join(staging_root, etc_template_dir)
            os.makedirs(full_template_path, exist_ok=True)

            tmpfiles_content = []
            # Iterate through all files in /etc
            for root, dirs, files in os.walk(etc_src):
                for f in files:
                    full_f_path = os.path.join(root, f)
                    rel_f_path = os.path.relpath(full_f_path, etc_src)

                    # Path within sysext (where we move the file)
                    target_in_usr = os.path.join(full_template_path, rel_f_path)
                    os.makedirs(os.path.dirname(target_in_usr), exist_ok=True)
                    shutil.move(full_f_path, target_in_usr)

                    # Add line to tmpfiles.d (L+ creates a symlink and overwrites existing)
                    # Format: L+ /etc/path - - - - /usr/lib/sysext-creator/etc-template/name/path
                    tmpfiles_content.append(f"L+ /etc/{rel_f_path} - - - - /{etc_template_dir}/{rel_f_path}")

            # Delete empty /etc in staging root
            shutil.rmtree(etc_src)

            # Write tmpfiles.d configuration
            tmp_dir = os.path.join(staging_root, "usr/lib/tmpfiles.d")
            os.makedirs(tmp_dir, exist_ok=True)
            with open(os.path.join(tmp_dir, f"sysext-creator-{name}.conf"), "w") as f:
                f.write("# Generated by Sysext-Creator\n")
                f.write("\n".join(tmpfiles_content) + "\n")
        # --- END OF /ETC PROCESSING ---

        os_info = get_os_info()
        rel_dir = os.path.join(staging_root, "usr/lib/extension-release.d")
        os.makedirs(rel_dir, exist_ok=True)
        with open(os.path.join(rel_dir, f"extension-release.{name}"), "w") as f:
            f.write(f"ID={os_info.get('ID')}\n")
            f.write(f"VERSION_ID={os_info.get('VERSION_ID')}\n")
            f.write(f"VERSION={version}\n")

        # --- METADATA & MANIFESTS ---
        manifest_dir = os.path.join(staging_root, "usr/share/sysext/manifests")
        os.makedirs(manifest_dir, exist_ok=True)

        # 1. Base requested packages
        with open(os.path.join(manifest_dir, f"{name}.txt"), "w") as f:
            f.write("\n".join(requested_packages) + "\n")

        # 2. Base version info
        with open(os.path.join(manifest_dir, f"{name}.version"), "w") as f:
            f.write(version + "\n")

        # 3. Full dependency list with versions (<name>.<version>)
        logging.info("Extracting version info for full dependency list...")
        deps_list = []
        for rpm in rpms_to_extract:
            try:
                # Queries the RPM file for Name.Version format
                res = subprocess.run(
                    ["rpm", "-qp", "--qf", "%{NAME}.%{VERSION}", rpm],
                    capture_output=True, text=True, check=True
                )
                if res.stdout.strip():
                    deps_list.append(res.stdout.strip())
            except Exception as e:
                logging.warning(f"Failed to extract info from {os.path.basename(rpm)}: {e}")

        # Named specifically to avoid conflicts when merged into /usr
        with open(os.path.join(manifest_dir, f"{name}-deps.txt"), "w") as f:
            f.write("\n".join(sorted(deps_list)) + "\n")

        # --- CLEANUP ---
        # Remove the downloaded RPMs so they don't bloat the final .raw image
        if os.path.exists(dnf_dir):
            shutil.rmtree(dnf_dir)
            logging.info("Cleaned up temporary DNF downloads.")


        # --- EROFS IMAGE CREATION ---
        out_file = os.path.join(CACHE_DIR, f"{name}.raw")
        tmp_out_file = out_file + ".tmp"

        selinux_contexts = "/run/host/etc/selinux/targeted/contexts/files/file_contexts"
        cmd = ["mkfs.erofs", "-x1", "--all-root", "-U", "clear", "-T", "0"]
        if os.path.exists(selinux_contexts):
            cmd.append(f"--file-contexts={selinux_contexts}")
        cmd.extend([tmp_out_file, staging_root])
        run_cmd(cmd)

        # Atomic rename
        os.rename(tmp_out_file, out_file)
        logging.info(f"Build finished successfully: {out_file}")

    finally:
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)

if __name__ == "__main__":
    main()
