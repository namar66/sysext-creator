#!/usr/bin/python3
# Sysext-Creator Builder v3.2.4
# Full pipeline: Fedora 45 DNF5 support, bin/sbin merge, opt relocation,
# vendor /etc relocation, SELinux policy compilation (-n), trigger detection,
# local RPM filtering, and EROFS LZ4 compression.
# Smart /etc vendor relocation, SELinux compilation, trigger detection & RPM scriptlet inspection
# Phase 1: Smart vendor relocation for /etc -> /usr, minimal tmpfiles.d fallback
# bin/sbin merge, opt-relocation, systemd unit auto-reload
# Fedora 45 DNF5 & usr-repo relocation support, fast host RPM indexing, clean /etc manifests

import os
import subprocess
import sys
import tempfile
import shutil
import logging
import re
import argparse
import stat

CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

VENDOR_RELOCATIONS = {
    "udev/rules.d": "usr/lib/udev/rules.d",
    "sysctl.d": "usr/lib/sysctl.d",
    "modules-load.d": "usr/lib/modules-load.d",
    "binfmt.d": "usr/lib/binfmt.d",
    "tmpfiles.d": "usr/lib/tmpfiles.d",
    "environment.d": "usr/lib/environment.d",
    "systemd/system": "usr/lib/systemd/system",
    "systemd/user": "usr/lib/systemd/user",
    "security/limits.d": "usr/lib/security/limits.d",
    "pam.d": "usr/lib/pam.d",
    "polkit-1/rules.d": "usr/share/polkit-1/rules.d",
}

def safe_rmtree(path):
    """Recursively removes directory tree handling read-only permissions."""
    def on_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            func(p)
        except Exception:
            pass
    if os.path.exists(path):
        shutil.rmtree(path, onerror=on_error)

def run_cmd(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e.stderr}")
        sys.exit(1)

def get_os_info():
    info = {"ID": "fedora", "VERSION_ID": "any"}
    for candidate in ["/run/host/usr/lib/os-release", "/run/host/etc/os-release"]:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r") as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            info[k] = v.strip('"\'')
                break
            except Exception:
                pass
    return info

def get_rpm_version(rpm_path):
    query = "%|EPOCH?{%{EPOCH}:}:{}|%{VERSION}-%{RELEASE}"
    try:
        res = subprocess.run(["rpm", "-qp", f"--qf={query}", rpm_path], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"

def inspect_rpm_scripts(rpm_paths):
    """Scans RPM scriptlets for unhandled imperative operations."""
    warnings_found = 0
    patterns = [
        (re.compile(r'\buseradd\b'), "Creates users imperatively (handled via sysusers.d if available)"),
        (re.compile(r'\bgroupadd\b'), "Creates groups imperatively (handled via sysusers.d if available)"),
        (re.compile(r'\bcrontab\b'), "Modifies crontab directly"),
        (re.compile(r'/etc/rc\.d'), "Uses legacy SysV init paths"),
    ]

    for rpm in rpm_paths:
        try:
            res = subprocess.run(["rpm", "-qp", "--scripts", rpm], capture_output=True, text=True, check=True)
            if not res.stdout.strip():
                continue
            for pattern, desc in patterns:
                if pattern.search(res.stdout):
                    logging.warning(f"Scriptlet notice [{os.path.basename(rpm)}]: {desc}")
                    warnings_found += 1
        except Exception:
            pass

    if warnings_found == 0:
        logging.info("RPM scriptlets inspection: clean / declarative.")

def calculate_host_dependencies(packages):
    if not packages:
        return []
    logging.info("Calculating missing dependencies against host OS...")
    cmd = ["flatpak-spawn", "--host", "env", "LC_ALL=C", "rpm-ostree", "install", "--dry-run"] + packages
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

        if res.returncode != 0:
            combined_output = res.stderr + "\n" + res.stdout
            if "is already provided by" in combined_output:
                logging.error("Build aborted: One or more requested packages are already installed on host OS.")
                logging.error(combined_output.strip())
                sys.exit(1)
            else:
                logging.warning(f"rpm-ostree dry-run returned non-zero code: {combined_output.strip()}")

        arch_res = subprocess.run(["uname", "-m"], capture_output=True, text=True, check=True)
        host_arch = arch_res.stdout.strip()

        allowed_archs = ["noarch", host_arch]
        if host_arch == "x86_64":
            allowed_archs.append("i686")

        added_pkgs = []
        parsing_added = False
        arch_pattern = "|".join(allowed_archs)
        nevra_re = re.compile(fr'^(.+?)-(([0-9]+:)?([^-]+)-([^-]+))\.({arch_pattern})$')

        for line in res.stdout.splitlines():
            line_s = line.strip()
            if any(line.startswith(s) for s in ["Installing", "Added:", "Upgrading", "Upgraded:"]):
                parsing_added = True
                continue
            elif any(line.startswith(s) for s in ["Removing", "Removed:"]):
                parsing_added = False
                continue

            if parsing_added and line.startswith(" "):
                raw_pkg = line_s.split()[0]
                match = nevra_re.match(raw_pkg)
                if match:
                    name_pkg, arch = match.group(1), match.group(6)
                    formatted = f"{name_pkg}.{arch}"
                    if formatted not in added_pkgs:
                        added_pkgs.append(formatted)

        if added_pkgs:
            logging.info("Cross-checking with host RPM database to filter out existing packages...")
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
                logging.warning(f"Failed to query host RPM database: {e}")

        logging.info(f"Identified {len(added_pkgs)} packages required for extension.")
        return added_pkgs
    except Exception as e:
        logging.error(f"Dependency calculation failed: {e}")
        sys.exit(1)

def sync_host_repos():
    """Synchronizes repository files and GPG keys from host supporting F45+ relocated paths."""
    logging.info("Syncing host repositories and GPG keys...")
    host_repo_dirs = [
        "/run/host/usr/share/dnf5/repos.d",
        "/run/host/etc/yum.repos.d",
        "/run/host/etc/dnf/repos.d",
    ]

    subprocess.run(["sudo", "mkdir", "-p", "/etc/yum.repos.d"], check=False)
    for rdir in host_repo_dirs:
        if os.path.isdir(rdir):
            for f in os.listdir(rdir):
                if f.endswith(".repo"):
                    src = os.path.join(rdir, f)
                    try:
                        subprocess.run(["sudo", "cp", "-f", src, "/etc/yum.repos.d/"], check=True)
                    except Exception as e:
                        logging.warning(f"Could not copy repo file {src}: {e}")

    host_gpg_dirs = [
        "/run/host/usr/share/pki/rpm-gpg",
        "/run/host/etc/pki/rpm-gpg",
    ]

    subprocess.run(["sudo", "mkdir", "-p", "/etc/pki/rpm-gpg", "/usr/share/pki/rpm-gpg"], check=False)
    for gdir in host_gpg_dirs:
        if os.path.isdir(gdir):
            for f in os.listdir(gdir):
                src = os.path.join(gdir, f)
                if os.path.isfile(src) and not f.startswith("."):
                    try:
                        subprocess.run(["sudo", "cp", "-f", src, "/etc/pki/rpm-gpg/"], check=False)
                        subprocess.run(["sudo", "cp", "-f", src, "/usr/share/pki/rpm-gpg/"], check=False)
                        subprocess.run(["sudo", "rpm", "--import", src], capture_output=True, check=False)
                    except Exception as e:
                        logging.warning(f"Could not import GPG key {src}: {e}")

def verify_rpms(rpm_paths, is_local=False):
    if not rpm_paths:
        return
    label = "local" if is_local else "downloaded"
    logging.info(f"Verifying GPG signatures for {len(rpm_paths)} {label} packages...")

    for rpm in rpm_paths:
        try:
            subprocess.run(["rpm", "-K", rpm], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            if is_local:
                logging.warning(f"Local package signature verification skipped/failed: {os.path.basename(rpm)}")
            else:
                logging.error(f"GPG Verification FAILED for repo package: {os.path.basename(rpm)}")
                logging.error(f"Details: {e.stderr}")
                sys.exit(1)

    if not is_local:
        logging.info("All repository package signatures verified.")

def check_container_dependencies():
    logging.info("Checking container build tools...")
    missing = []
    if shutil.which("mkfs.erofs") is None:
        missing.append("erofs-utils")
    if shutil.which("semodule") is None:
        missing.append("policycoreutils")

    try:
        subprocess.run(["dnf", "download", "--help"], capture_output=True, check=True)
    except Exception:
        missing.append("dnf5-plugins" if shutil.which("dnf5") else "dnf-plugins-core")

    if missing:
        logging.info(f"Installing missing container dependencies: {', '.join(missing)}")
        try:
            subprocess.run(["sudo", "LANG=C", "dnf", "install", "-y"] + missing, check=True)
        except Exception as e:
            logging.error(f"Failed to install dependencies: {e}")
            sys.exit(1)

def prune_shadowed_files(staging_root):
    logging.info("Indexing host RPM files via host root...")
    try:
        res = subprocess.run(
            ["rpm", "--root", "/run/host", "-ql", "-a"],
            capture_output=True, text=True, errors="replace", check=True
        )
        host_owned_files = set(res.stdout.splitlines())
        logging.info(f"Indexed {len(host_owned_files)} host-owned files.")
    except Exception as e:
        logging.warning(f"Error during host RPM indexing: {e}. Skipping smart pruning.")
        return

    pruned_count = 0
    staging_target = os.path.join(staging_root, "usr")
    if not os.path.exists(staging_target):
        return

    for root, dirs, files in os.walk(staging_target, topdown=False):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, staging_root)
            abs_rel_path = "/" + rel_path

            if abs_rel_path in host_owned_files:
                try:
                    os.remove(full_path)
                    pruned_count += 1
                except Exception as e:
                    logging.warning(f"Failed to prune {abs_rel_path}: {e}")

        for d in list(dirs):
            dir_path = os.path.join(root, d)
            if os.path.islink(dir_path):
                rel_path = os.path.relpath(dir_path, staging_root)
                abs_rel_path = "/" + rel_path
                if abs_rel_path in host_owned_files:
                    try:
                        os.remove(dir_path)
                        pruned_count += 1
                    except Exception:
                        pass
            elif not os.listdir(dir_path):
                try:
                    os.rmdir(dir_path)
                except Exception:
                    pass

    if pruned_count > 0:
        logging.info(f"Smart Pruning: Removed {pruned_count} files owned by host OS.")
    else:
        logging.info("No host OS shadowing detected.")

def clean_empty_directories(path):
    for root, dirs, files in os.walk(path, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            if not os.path.islink(dir_path) and not os.listdir(dir_path):
                try:
                    os.rmdir(dir_path)
                except Exception:
                    pass

def detect_and_save_triggers(staging_root, manifest_dir, name):
    """Detects required system cache/daemon triggers and writes manifest."""
    triggers = []

    if os.path.exists(os.path.join(staging_root, "usr/lib/sysusers.d")):
        triggers.append("sysusers")

    if os.path.exists(os.path.join(staging_root, "usr/share/glib-2.0/schemas")):
        triggers.append("glib-schemas")

    if os.path.exists(os.path.join(staging_root, "usr/share/mime/packages")):
        triggers.append("mime")

    icons_dir = os.path.join(staging_root, "usr/share/icons")
    if os.path.exists(icons_dir):
        for theme in os.listdir(icons_dir):
            if os.path.isdir(os.path.join(icons_dir, theme)) and theme != "hicolor":
                triggers.append(f"icon-cache:{theme}")
        triggers.append("icon-cache:hicolor")

    if os.path.exists(os.path.join(staging_root, "usr/lib/udev/hwdb.d")):
        triggers.append("hwdb")

    if triggers:
        logging.info(f"Detected post-deployment triggers: {', '.join(triggers)}")
        with open(os.path.join(manifest_dir, f"{name}-triggers.txt"), "w") as f:
            f.write("\n".join(triggers) + "\n")

def main():
    parser = argparse.ArgumentParser(description="Sysext-Creator EROFS Builder")
    parser.add_argument("--name", required=True, help="Name of the resulting system extension")
    parser.add_argument("--packages", nargs='+', required=True, help="List of packages to include")

    args = parser.parse_args()
    name = args.name
    requested_packages = args.packages

    check_container_dependencies()
    sync_host_repos()

    os.makedirs(CACHE_DIR, exist_ok=True)

    build_dir = tempfile.mkdtemp(prefix=f"sysext-build-{name}-")
    staging_root = os.path.join(build_dir, "rootfs")
    dnf_dir = os.path.join(build_dir, "dnf-downloads")

    try:
        os.makedirs(staging_root, exist_ok=True)
        os.makedirs(dnf_dir, exist_ok=True)

        local_rpms = [os.path.abspath(p) for p in requested_packages if p.endswith(".rpm") and os.path.isfile(p)]
        repo_packages = [p for p in requested_packages if p not in local_rpms]
        all_pkgs = repo_packages + local_rpms

        local_pkg_names = set()
        for rpm in local_rpms:
            try:
                res = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", rpm], capture_output=True, text=True, check=True)
                if res.stdout.strip():
                    local_pkg_names.add(res.stdout.strip())
            except Exception:
                pass

        if local_rpms:
            verify_rpms(local_rpms, is_local=True)

        missing_deps = calculate_host_dependencies(all_pkgs)

        if local_pkg_names and missing_deps:
            filtered_deps = []
            for dep in missing_deps:
                dep_name = dep.split(".")[0]
                if dep_name in local_pkg_names:
                    logging.info(f"Skipping repository download for local RPM: {dep}")
                else:
                    filtered_deps.append(dep)
            missing_deps = filtered_deps

        if missing_deps:
            logging.info(f"Downloading {len(missing_deps)} packages to {dnf_dir}...")
            run_cmd(["dnf", "--refresh", "download", f"--destdir={dnf_dir}"] + missing_deps)
            downloaded_rpms = [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]
            verify_rpms(downloaded_rpms, is_local=False)

        rpms_to_extract = local_rpms + [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]

        inspect_rpm_scripts(rpms_to_extract)

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

        # 1. Fedora Bin/Sbin Merge
        usr_sbin = os.path.join(staging_root, "usr", "sbin")
        usr_bin = os.path.join(staging_root, "usr", "bin")
        if os.path.exists(usr_sbin) and not os.path.islink(usr_sbin):
            logging.info("Merging /usr/sbin into /usr/bin (Fedora 42+ compatibility)...")
            os.makedirs(usr_bin, exist_ok=True)
            for item in os.listdir(usr_sbin):
                s_item = os.path.join(usr_sbin, item)
                d_item = os.path.join(usr_bin, item)
                if not os.path.exists(d_item):
                    shutil.move(s_item, d_item)
                else:
                    if os.path.isdir(s_item):
                        shutil.copytree(s_item, d_item, dirs_exist_ok=True)
                        safe_rmtree(s_item)
                    else:
                        shutil.move(s_item, d_item)
            safe_rmtree(usr_sbin)

        # 2. Relocate /opt to /usr/lib/opt
        opt_src = os.path.join(staging_root, "opt")
        if os.path.exists(opt_src):
            logging.info("Migrating /opt payload to /usr/lib/opt...")
            target_opt = os.path.join(staging_root, "usr", "lib", "opt")
            os.makedirs(target_opt, exist_ok=True)
            for item in os.listdir(opt_src):
                s_item = os.path.join(opt_src, item)
                d_item = os.path.join(target_opt, item)
                shutil.move(s_item, d_item)
            safe_rmtree(opt_src)

        # 3. Discard /var
        var_src = os.path.join(staging_root, "var")
        if os.path.exists(var_src):
            logging.warning("Discarding payload in /var (/var is not supported by systemd-sysext).")
            safe_rmtree(var_src)

        # 4. Smart Vendor Relocation from /etc to /usr
        etc_src = os.path.join(staging_root, "etc")
        if os.path.exists(etc_src):
            for etc_rel, usr_rel in VENDOR_RELOCATIONS.items():
                src_dir = os.path.join(etc_src, etc_rel)
                if os.path.exists(src_dir):
                    dest_dir = os.path.join(staging_root, usr_rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    logging.info(f"Vendor Relocation: Moving /etc/{etc_rel} -> /{usr_rel}...")
                    for item in os.listdir(src_dir):
                        s = os.path.join(src_dir, item)
                        d = os.path.join(dest_dir, item)
                        if os.path.isdir(s):
                            shutil.copytree(s, d, dirs_exist_ok=True)
                            safe_rmtree(s)
                        else:
                            shutil.move(s, d)
                    safe_rmtree(src_dir)
            clean_empty_directories(etc_src)

        # 5. Fallback migration via tmpfiles.d
        migrated_etc_files = []
        if os.path.exists(etc_src) and os.listdir(etc_src):
            logging.info(f"Migrating non-relocatable /etc files to tmpfiles.d for {name}...")
            etc_template_dir = f"usr/lib/sysext-creator/etc-template/{name}"
            full_template_path = os.path.join(staging_root, etc_template_dir)
            os.makedirs(full_template_path, exist_ok=True)

            tmpfiles_content = []
            for root, dirs, files in os.walk(etc_src):
                for f in files:
                    full_f_path = os.path.join(root, f)
                    rel_f_path = os.path.relpath(full_f_path, etc_src)
                    target_in_usr = os.path.join(full_template_path, rel_f_path)
                    os.makedirs(os.path.dirname(target_in_usr), exist_ok=True)
                    shutil.move(full_f_path, target_in_usr)

                    tmpfiles_content.append(f"L+ /etc/{rel_f_path} - - - - /{etc_template_dir}/{rel_f_path}")
                    migrated_etc_files.append(rel_f_path)

            safe_rmtree(etc_src)

            tmp_dir = os.path.join(staging_root, "usr/lib/tmpfiles.d")
            os.makedirs(tmp_dir, exist_ok=True)
            with open(os.path.join(tmp_dir, f"sysext-creator-{name}.conf"), "w") as f:
                f.write("# Generated by Sysext-Creator (Fallback application config)\n")
                f.write("\n".join(tmpfiles_content) + "\n")
        elif os.path.exists(etc_src):
            safe_rmtree(etc_src)

        # 6. Smart Pruning against host RPMs
        prune_shadowed_files(staging_root)

        # 7. SELinux processing
        selinux_modules = []
        selinux_dirs = [
            os.path.join(staging_root, "usr/share/selinux/packages"),
            os.path.join(staging_root, "usr/share/selinux/targeted")
        ]
        for sdir in selinux_dirs:
            if os.path.exists(sdir):
                for f in os.listdir(sdir):
                    if f.endswith((".pp", ".pp.bz2", ".cil")):
                        selinux_modules.append(os.path.join(sdir, f))

        active_file_contexts = "/run/host/etc/selinux/targeted/contexts/files/file_contexts"

        if selinux_modules:
            logging.info(f"Detected {len(selinux_modules)} SELinux policy module(s). Compiling in container...")
            try:
                cmd_se = ["sudo", "semodule", "-n", "-i"] + selinux_modules
                subprocess.run(cmd_se, check=True, capture_output=True)

                container_fc = "/etc/selinux/targeted/contexts/files/file_contexts"
                if os.path.exists(container_fc):
                    active_file_contexts = container_fc
                    logging.info("Container file_contexts updated with new policy labels.")
            except Exception as e:
                logging.warning(f"Could not compile SELinux policy inside container: {e}")

        # 8. Check systemd units
        systemd_units_dir = os.path.join(staging_root, "usr", "lib", "systemd", "system")
        has_systemd_units = False
        if os.path.exists(systemd_units_dir):
            for f in os.listdir(systemd_units_dir):
                if f.endswith((".service", ".socket", ".timer", ".target", ".path")):
                    has_systemd_units = True
                    break

        # 9. extension-release metadata
        os_info = get_os_info()
        rel_dir = os.path.join(staging_root, "usr/lib/extension-release.d")
        os.makedirs(rel_dir, exist_ok=True)
        with open(os.path.join(rel_dir, f"extension-release.{name}"), "w") as f:
            f.write(f"ID={os_info.get('ID')}\n")
            f.write(f"VERSION_ID={os_info.get('VERSION_ID')}\n")
            f.write(f"VERSION={version}\n")
            if has_systemd_units:
                f.write("EXTENSION_RELOAD_MANAGER=1\n")
                logging.info("Detected systemd units: added EXTENSION_RELOAD_MANAGER=1 to release metadata.")

        # 10. Generate manifests and triggers
        manifest_dir = os.path.join(staging_root, "usr/share/sysext/manifests")
        os.makedirs(manifest_dir, exist_ok=True)

        with open(os.path.join(manifest_dir, f"{name}.txt"), "w") as f:
            f.write("\n".join(requested_packages) + "\n")

        with open(os.path.join(manifest_dir, f"{name}.version"), "w") as f:
            f.write(version + "\n")

        if migrated_etc_files:
            with open(os.path.join(manifest_dir, f"{name}-etc.txt"), "w") as f:
                f.write("\n".join(migrated_etc_files) + "\n")

        if selinux_modules:
            rel_modules = [os.path.relpath(m, staging_root) for m in selinux_modules]
            with open(os.path.join(manifest_dir, f"{name}-selinux.txt"), "w") as f:
                f.write("\n".join(rel_modules) + "\n")

        detect_and_save_triggers(staging_root, manifest_dir, name)

        deps_list = []
        for rpm in rpms_to_extract:
            try:
                res = subprocess.run(
                    ["rpm", "-qp", "--qf", "%{NAME}.%{VERSION}", rpm],
                    capture_output=True, text=True, check=True
                )
                if res.stdout.strip():
                    deps_list.append(res.stdout.strip())
            except Exception:
                pass

        with open(os.path.join(manifest_dir, f"{name}-deps.txt"), "w") as f:
            f.write("\n".join(sorted(deps_list)) + "\n")

        # 11. Build EROFS image with LZ4 compression
        out_file = os.path.join(CACHE_DIR, f"{name}.raw")
        tmp_out_file = out_file + ".tmp"

        cmd = [
            "mkfs.erofs",
            "-zlz4",
            "-x1",
            "--all-root",
            "-U", "clear",
            "-T", "0"
        ]
        if os.path.exists(active_file_contexts):
            cmd.append(f"--file-contexts={active_file_contexts}")
        cmd.extend([tmp_out_file, staging_root])
        run_cmd(cmd)

        os.rename(tmp_out_file, out_file)
        logging.info(f"Build finished successfully: {out_file}")

    finally:
        safe_rmtree(build_dir)

if __name__ == "__main__":
    main()
