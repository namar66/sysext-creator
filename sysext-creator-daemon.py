#!/usr/bin/python3

# Sysext-Creator Daemon v3.0
# Features: Varlink IPC, OverlayFS routing, Metadata, Conflict Guard, Diagnostics

import os
import sys
import subprocess
import varlink
import grp
import logging
import json
from pathlib import Path

# --- Configuration & Paths ---
RUN_DIR = "/run/sysext-creator"
SOCKET_PATH = f"{RUN_DIR}/sysext-creator.sock"
VARLINK_FILE = f"{RUN_DIR}/io.sysext.creator.varlink"

EXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"
CONFEXT_MUTABLE_DIR = "/var/lib/confexts.mutable"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# --- Interface Definition ---
INTERFACE_DEFINITION = """
interface io.sysext.creator

type Extension (
    name: string,
    version: string,
    packages: string
)

method ListExtensions() -> (extensions: []Extension)
method RemoveSysext(name: string) -> ()
method DeploySysext(name: string, path: string, force: bool) -> (status: string, conflicts: []string, progress: int)
method RefreshExtensions() -> (status: string)
method RunDiagnostics() -> (report: []string)

error ExtensionNotFound(name: string)
error PermissionDenied()
error InternalError(message: string)
"""

os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
with open(VARLINK_FILE, "w") as f:
    f.write(INTERFACE_DEFINITION.strip())

service = varlink.Service(
    vendor="Sysext Creator Project",
    product="Sysext Daemon",
    version="5.0",
    interface_dir=RUN_DIR
)

# --- Helper Functions ---
def extract_metadata(image_path):
    version = "unknown"
    packages = "N/A"
    try:
        result = subprocess.run(
            ["systemd-dissect", "--json=short", image_path],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
        release_data = data.get("sysextRelease") or data.get("confextRelease") or []

        release_dict = {}
        for item in release_data:
            if "=" in item:
                key, val = item.split("=", 1)
                release_dict[key] = val.strip('"\'')

        version = release_dict.get("SYSEXT_VERSION_ID", release_dict.get("VERSION_ID", "unknown"))
        packages = release_dict.get("SYSEXT_CREATOR_PKGS", "N/A")
    except Exception as e:
        logging.warning(f"Failed to read metadata from {image_path}: {e}")
    return version, packages

def check_conflicts(image_path):
    conflicts = []
    try:
        res = subprocess.run(["systemd-dissect", "--list", str(image_path)],
                             capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            if line.startswith("etc/") and not line.endswith("/"):
                full_path = "/" + line
                rpm_res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}", "-f", full_path],
                                         capture_output=True, text=True)
                if rpm_res.returncode == 0:
                    owner = rpm_res.stdout.strip()
                    conflicts.append(f"{full_path} (owned by {owner})")
    except Exception as e:
        logging.error(f"Conflict check failed: {e}")
    return conflicts

# --- Interface Logic ---
@service.interface('io.sysext.creator')
class SysextInterfaceLogic:

    def ListExtensions(self):
        ext_dict = {}
        for directory in [EXT_DIR, CONFEXT_DIR]:
            if os.path.exists(directory):
                try:
                    for filename in os.listdir(directory):
                        if filename.endswith(".raw"):
                            name = filename.replace(".confext.raw", "").replace(".raw", "")
                            image_path = os.path.join(directory, filename)
                            version, packages = extract_metadata(image_path)

                            if name not in ext_dict:
                                ext_dict[name] = {"name": name, "version": version, "packages": packages}
                            else:
                                if ext_dict[name]["version"] == "unknown" and version != "unknown":
                                    ext_dict[name]["version"] = version
                                if ext_dict[name]["packages"] == "N/A" and packages != "N/A":
                                    ext_dict[name]["packages"] = packages
                except Exception as e:
                    logging.error(f"Failed to read {directory}: {e}")
        return {"extensions": list(ext_dict.values())}

    def RefreshExtensions(self):
        try:
            os.makedirs(CONFEXT_MUTABLE_DIR, mode=0o755, exist_ok=True)
            subprocess.run(["systemd-sysext", "refresh"], check=True)
            subprocess.run(["systemd-confext", "refresh", "--mutable=auto"], check=True)
            return {"status": "Success"}
        except subprocess.CalledProcessError as e:
            return {"status": f"Error: {e}"}

    def RemoveSysext(self, name):
        targets = [
            os.path.join(EXT_DIR, f"{name}.raw"),
            os.path.join(CONFEXT_DIR, f"{name}.confext.raw")
        ]
        for target in targets:
            if os.path.exists(target):
                os.remove(target)
        self.RefreshExtensions()
        return {}

    def DeploySysext(self, name, path, force=False):
        filename = os.path.basename(path)

        # Pre-flight Check
        if filename.endswith(".confext.raw") and not force:
            conflicts = check_conflicts(path)
            if conflicts:
                logging.warning(f"Deployment blocked due to conflicts.")
                return {"status": "ConflictFound", "conflicts": conflicts, "progress": 0}

        target_dir = CONFEXT_DIR if filename.endswith(".confext.raw") else EXT_DIR
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)

        try:
            subprocess.run(["cp", path, target_path], check=True)
            subprocess.run(["restorecon", "-v", target_path], check=True)
            refresh_res = self.RefreshExtensions()
            if "Error" in refresh_res.get("status", ""):
                return {"status": refresh_res["status"], "conflicts": [], "progress": 0}

            return {"status": "Success", "conflicts": [], "progress": 100}
        except Exception as e:
            return {"status": f"Error: {str(e)}", "conflicts": [], "progress": 0}

    def RunDiagnostics(self):
        report = []
        confext_files = list(Path(CONFEXT_DIR).glob("*.raw"))

        if not confext_files:
            return {"report": ["No configuration extensions found to analyze."]}

        for img in confext_files:
            report.append(f"\n--- Analyzing {img.name} ---")
            try:
                res = subprocess.run(["systemd-dissect", "--list", str(img)],
                                     capture_output=True, text=True, check=True)
                for line in res.stdout.splitlines():
                    if line.startswith("etc/") and not line.endswith("/"):
                        full_path = "/" + line
                        rpm_res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}", "-f", full_path],
                                                 capture_output=True, text=True)
                        if rpm_res.returncode == 0:
                            report.append(f"[FAIL] {full_path} (Overwrites system package: {rpm_res.stdout.strip()})")
                        else:
                            report.append(f"[OK]   {full_path}")
            except Exception as e:
                report.append(f"[ERROR] Could not analyze {img.name}: {e}")

        return {"report": report}

# --- Server Execution ---
class DaemonRequestHandler(varlink.RequestHandler):
    service = service

def run_server():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    with varlink.ThreadingServer(f"unix:{SOCKET_PATH}", DaemonRequestHandler) as server:
        server.service = service
        os.chmod(SOCKET_PATH, 0o660)
        try:
            wheel_info = grp.getgrnam('wheel')
            os.chown(SOCKET_PATH, -1, wheel_info.gr_gid)
        except KeyError:
            pass
        server.serve_forever()

if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit(1)
    run_server()
