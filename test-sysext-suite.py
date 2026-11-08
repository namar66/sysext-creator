#!/usr/bin/python3
# Test Suite for Sysext Creator Pro
# Generates a synthetic RPM with traps, tests build, deployment, triggers, and cleanup

import os
import sys
import shutil
import subprocess
import tempfile
import time
import logging

LOG_FILE = "sysext-test-suite.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(sys.stdout)
    ]
)

BIN_DIR = os.path.expanduser("~/.local/bin")
CLI_PATH = os.path.join(BIN_DIR, "sysext-cli")

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"


class SysextTestSuite:
    def __init__(self):
        cache_base = os.path.expanduser("~/.cache/sysext-creator")
        os.makedirs(cache_base, exist_ok=True)
        self.work_dir = tempfile.mkdtemp(prefix="sysext-test-", dir=cache_base)
        self.rpm_dir = os.path.join(self.work_dir, "rpmbuild")
        self.layer_name = "test-synthetic-layer"
        self.test_results = []
        self.built_rpm = None

    def log_assert(self, condition: bool, description: str):
        if condition:
            logging.info(f"{PASS} {description}")
            self.test_results.append((True, description))
        else:
            logging.error(f"{FAIL} {description}")
            self.test_results.append((False, description))

    def setup_rpm_tree(self):
        logging.info(f"{INFO} Preparing RPM build tree in {self.rpm_dir}...")
        for folder in ["BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"]:
            os.makedirs(os.path.join(self.rpm_dir, folder), exist_ok=True)

    def generate_synthetic_spec(self):
        """Generates a spec file testing vendor paths, tmpfiles, bin/sbin merge, and scriptlets."""
        spec_content = f"""
Name:           sysext-test-synthetic
Version:        1.0.0
Release:        1%{{?dist}}
Summary:        Synthetic RPM for Sysext Creator validation
License:        MIT

%description
Synthetic package containing test traps: raw scriptlets, sbin binaries,
vendor udev rules, and classic /etc application configs.

%install
mkdir -p %{{buildroot}}/usr/bin
mkdir -p %{{buildroot}}/usr/sbin
mkdir -p %{{buildroot}}/etc/udev/rules.d
mkdir -p %{{buildroot}}/etc/synthetic-app
mkdir -p %{{buildroot}}/usr/lib/sysusers.d
mkdir -p %{{buildroot}}/usr/share/applications

# 1. Test standard binary
cat << 'EOF' > %{{buildroot}}/usr/bin/sysext-test-bin
#!/bin/sh
echo "SYSEXT_TEST_BIN_OK"
EOF
chmod 0755 %{{buildroot}}/usr/bin/sysext-test-bin

# 2. Test bin/sbin merge (binary in /usr/sbin)
cat << 'EOF' > %{{buildroot}}/usr/sbin/sysext-test-sbin
#!/bin/sh
echo "SYSEXT_TEST_SBIN_OK"
EOF
chmod 0755 %{{buildroot}}/usr/sbin/sysext-test-sbin

# 3. Test Vendor Relocation (/etc/udev/rules.d -> /usr/lib/udev/rules.d)
cat << 'EOF' > %{{buildroot}}/etc/udev/rules.d/99-sysext-test.rules
# Test rule
SUBSYSTEM=="misc", KERNEL=="sysext_test", MODE="0666"
EOF

# 4. Test Fallback /etc migration (/etc/synthetic-app/test.conf -> tmpfiles.d)
cat << 'EOF' > %{{buildroot}}/etc/synthetic-app/test.conf
[main]
status = functional
EOF

# 5. Test Declarative User (sysusers.d trigger)
cat << 'EOF' > %{{buildroot}}/usr/lib/sysusers.d/sysext-synthetic-user.conf
u sysexttest 9876 "Sysext Test Daemon User" /var/empty /sbin/nologin
EOF

# 6. Test Desktop Entry (XDG menu trigger)
cat << 'EOF' > %{{buildroot}}/usr/share/applications/sysext-synthetic.desktop
[Desktop Entry]
Type=Application
Name=Sysext Test App
Exec=/usr/bin/sysext-test-bin
Categories=Development;
EOF

# 7. TRAP: Scriptlets to prove raw execution is blocked / audited
%pre
echo "RAW_RPM_PRE_EXECUTED" > /tmp/rpm-trap-pre.log

%post
echo "RAW_RPM_POST_EXECUTED" > /tmp/rpm-trap-post.log

%files
/usr/bin/sysext-test-bin
/usr/sbin/sysext-test-sbin
/etc/udev/rules.d/99-sysext-test.rules
/etc/synthetic-app/test.conf
/usr/lib/sysusers.d/sysext-synthetic-user.conf
/usr/share/applications/sysext-synthetic.desktop
"""
        spec_path = os.path.join(self.rpm_dir, "SPECS", "synthetic.spec")
        with open(spec_path, "w") as f:
            f.write(spec_content)
        return spec_path

    def build_rpm(self, spec_path):
        logging.info(f"{INFO} Compiling test RPM inside toolbox...")
        # Ensure rpm-build tool is present
        subprocess.run(["toolbox", "run", "-c", "sysext-builder", "sudo", "dnf", "install", "-y", "rpm-build"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cmd = [
            "toolbox", "run", "-c", "sysext-builder",
            "rpmbuild",
            f"--define=_topdir {self.rpm_dir}",
            "-bb", spec_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logging.error(f"RPM build failed: {res.stderr}")
            sys.exit(1)

        rpms_found = []
        for root, _, files in os.walk(os.path.join(self.rpm_dir, "RPMS")):
            for f in files:
                if f.endswith(".rpm"):
                    rpms_found.append(os.path.join(root, f))

        if not rpms_found:
            logging.error("No RPM binary produced.")
            sys.exit(1)

        self.built_rpm = rpms_found[0]
        logging.info(f"{PASS} Synthetic RPM created: {self.built_rpm}")

    def run_sysext_install(self):
        logging.info(f"\n{INFO} === PHASE 1: Deploying extension via sysext-cli ===")
        # Cleanup any leftover trap files
        for trap in ["/tmp/rpm-trap-pre.log", "/tmp/rpm-trap-post.log"]:
            if os.path.exists(trap):
                os.remove(trap)

        cmd = [sys.executable, CLI_PATH, "install", self.layer_name, self.built_rpm]
        res = subprocess.run(cmd, text=True)
        self.log_assert(res.returncode == 0, "CLI install command completed successfully.")

    def run_deployment_assertions(self):
        logging.info(f"\n{INFO} === PHASE 2: Validating system assertions ===")

        # 1. Raw scriptlets must NOT have run directly on host
        self.log_assert(not os.path.exists("/tmp/rpm-trap-pre.log"),
                        "Security: %pre scriptlet did NOT execute on host.")
        self.log_assert(not os.path.exists("/tmp/rpm-trap-post.log"),
                        "Security: %post scriptlet did NOT execute on host.")

        # 2. Standard binary is reachable and executable
        bin_path = "/usr/bin/sysext-test-bin"
        if os.path.exists(bin_path):
            res = subprocess.run([bin_path], capture_output=True, text=True)
            self.log_assert("SYSEXT_TEST_BIN_OK" in res.stdout,
                            f"Standard binary in {bin_path} is executable.")
        else:
            self.log_assert(False, f"Binary {bin_path} not found in mounted overlay.")

        # 3. Bin/Sbin merge verification (/usr/sbin -> /usr/bin)
        sbin_merged_path = "/usr/bin/sysext-test-sbin"
        self.log_assert(os.path.exists(sbin_merged_path),
                        f"Bin/Sbin Merge: sbin executable successfully relocated to {sbin_merged_path}.")

        # 4. Vendor Relocation (/etc/udev/rules.d moved to /usr/lib/udev/rules.d)
        vendor_udev = "/usr/lib/udev/rules.d/99-sysext-test.rules"
        direct_etc_udev = "/etc/udev/rules.d/99-sysext-test.rules"
        self.log_assert(os.path.exists(vendor_udev),
                        f"Vendor Relocation: udev rules safely located in {vendor_udev}.")
        self.log_assert(not os.path.islink(direct_etc_udev),
                        f"Clean /etc: No symlink created in {direct_etc_udev}.")

        # 5. Fallback /etc migration via tmpfiles.d
        etc_app_conf = "/etc/synthetic-app/test.conf"
        is_symlink = os.path.islink(etc_app_conf)
        self.log_assert(is_symlink,
                        f"Tmpfiles.d Fallback: {etc_app_conf} is a managed symlink.")
        if is_symlink:
            target = os.readlink(etc_app_conf)
            self.log_assert(self.layer_name in target,
                            f"Symlink points to sysext template directory ({target}).")

        # 6. Declarative User Trigger (systemd-sysusers verification)
        try:
            with open("/etc/passwd", "r") as f:
                passwd_content = f.read()
            self.log_assert("sysexttest" in passwd_content,
                            "System Trigger: 'sysexttest' user successfully provisioned via systemd-sysusers.")
        except Exception as e:
            self.log_assert(False, f"Failed to inspect /etc/passwd: {e}")

        # 7. Metadata Manifests verification
        manifest_base = f"/usr/share/sysext/manifests/{self.layer_name}.txt"
        manifest_etc = f"/usr/share/sysext/manifests/{self.layer_name}-etc.txt"
        manifest_triggers = f"/usr/share/sysext/manifests/{self.layer_name}-triggers.txt"

        self.log_assert(os.path.exists(manifest_base), f"Manifest {manifest_base} exists.")
        self.log_assert(os.path.exists(manifest_etc), f"Manifest {manifest_etc} exists.")
        self.log_assert(os.path.exists(manifest_triggers), f"Manifest {manifest_triggers} exists.")

    def run_sysext_removal(self):
        logging.info(f"\n{INFO} === PHASE 3: Removing extension & verifying cleanup ===")
        cmd = [sys.executable, CLI_PATH, "remove", self.layer_name]
        res = subprocess.run(cmd, text=True)
        self.log_assert(res.returncode == 0, "CLI remove command completed successfully.")

        # 1. Layer binaries must be gone
        self.log_assert(not os.path.exists("/usr/bin/sysext-test-bin"),
                        "Cleanup: /usr/bin/sysext-test-bin unmounted.")

        # 2. /etc symlinks must be purged
        etc_app_conf = "/etc/synthetic-app/test.conf"
        self.log_assert(not os.path.exists(etc_app_conf) and not os.path.islink(etc_app_conf),
                        f"Cleanup: Orphan symlink in {etc_app_conf} completely purged.")

        # Clean empty test parent folder in /etc
        etc_dir = "/etc/synthetic-app"
        if os.path.exists(etc_dir) and not os.listdir(etc_dir):
            try:
                os.rmdir(etc_dir)
            except Exception:
                pass

    def cleanup(self):
        logging.info(f"\n{INFO} Cleaning up temporary build artifacts...")
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def run(self):
        logging.info("=" * 65)
        logging.info("  SYSEXT CREATOR AUTOMATED TEST SUITE")
        logging.info("=" * 65)

        try:
            self.setup_rpm_tree()
            spec = self.generate_synthetic_spec()
            self.build_rpm(spec)
            self.run_sysext_install()
            self.run_deployment_assertions()
            self.run_sysext_removal()
        except KeyboardInterrupt:
            logging.warning("\nTest execution interrupted.")
        finally:
            self.cleanup()

        # Final Report
        total = len(self.test_results)
        passed = sum(1 for status, _ in self.test_results if status)
        failed = total - passed

        logging.info("\n" + "=" * 65)
        logging.info(f"  TEST SUMMARY: {passed}/{total} Passed, {failed} Failed")
        logging.info("=" * 65)

        if failed > 0:
            sys.exit(1)


if __name__ == "__main__":
    suite = SysextTestSuite()
    suite.run()
