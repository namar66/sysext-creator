#!/usr/bin/env python3

# Sysext-Creator Daemon v3.0 - Synchronous Fix
# Environment: Host System (Root)

import os
import shutil
import subprocess
import sys
import re
from pathlib import Path
from threading import Lock
import varlink

# --- CONFIG ---
SOCKET_PATH = "/run/sysext-creator.sock"
EXT_DIR = Path("/var/lib/extensions")
CONFEXT_DIR = Path("/var/lib/confexts")
LOCK = Lock()

INTERFACE_NAME = "io.sysext.creator"
INTERFACE_DIR = "/run/sysext-creator-interfaces"
INTERFACE_FILE = os.path.join(INTERFACE_DIR, f"{INTERFACE_NAME}.varlink")

INTERFACE_CONTENT = f'''
interface {INTERFACE_NAME}
type Extension (name: string, packages: string, version: string)
method GetHostInfo() -> (version_id: string, architecture: string, kernel: string)
method ListExtensions() -> (extensions: []Extension)
method DeploySysext(name: string, path: string) -> (progress: int, status: string)
method RemoveSysext(name: string) -> ()
'''

def log(msg):
    print(f"[DAEMON] {msg}", flush=True)

os.makedirs(INTERFACE_DIR, exist_ok=True)
with open(INTERFACE_FILE, "w") as f:
    f.write(INTERFACE_CONTENT)

sysext_service = varlink.Service(
    vendor='Nadmartin',
    product='Sysext Creator',
    version='13.3',
    interface_dir=INTERFACE_DIR
)

def extract_metadata_from_raw(path):
    pkgs, ver = "unknown", "unknown"
    try:
        res = subprocess.run(f"strings {path} | grep SYSEXT_", shell=True, capture_output=True, text=True)
        for line in res.stdout.splitlines():
            if "SYSEXT_CREATOR_PACKAGES=" in line: pkgs = line.split("=", 1)[1].strip('"')
            if "SYSEXT_VERSION_ID=" in line: ver = line.split("=", 1)[1].strip('"')
    except: pass
    return pkgs, ver

def extract_metadata_from_mounts(name):
    for p_base in ["/usr/lib", "/etc"]:
        p = Path(p_base) / f"extension-release.d/extension-release.{name}"
        if p.exists():
            try:
                with open(p, "r") as f:
                    content = f.read()
                    pkgs = re.search(r'SYSEXT_CREATOR_PACKAGES=(.*)', content)
                    ver = re.search(r'SYSEXT_VERSION_ID=(.*)', content)
                    return (pkgs.group(1).strip('"\n ') if pkgs else "unknown",
                            ver.group(1).strip('"\n ') if ver else "unknown")
            except: pass
    return None, "unknown"

@sysext_service.interface(INTERFACE_FILE)
class SysextCreatorImpl:
    def GetHostInfo(self, **kwargs):
        import platform
        return {"version_id": "43", "architecture": platform.machine(), "kernel": platform.release()}

    def DeploySysext(self, name, path, **kwargs):
        # We no longer yield. We do the work safely and return the final result.
        with LOCK:
            log(f"Deploying: {name} from {path}")
            is_conf = path.endswith(".confext.raw")
            target = (CONFEXT_DIR if is_conf else EXT_DIR) / os.path.basename(path)

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                os.chmod(target, 0o644)

                cmd = ["systemd-confext" if is_conf else "systemd-sysext", "refresh"]
                log(f"Running: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True)

                if res.returncode != 0:
                    log(f"Refresh failed: {res.stderr}")
                    if target.exists(): target.unlink()
                    raise Exception(res.stderr.strip())

                log(f"Successfully deployed {name}")
                return {"progress": 100, "status": "Success"}

            except Exception as e:
                log(f"Deployment error: {e}")
                raise Exception(str(e))

    def ListExtensions(self, **kwargs):
        results = []
        found_names = set()
        for d in [EXT_DIR, CONFEXT_DIR]:
            if d.exists():
                for f in d.glob("*.raw"):
                    name = f.name.replace(".confext.raw", "").replace(".raw", "")
                    if name in found_names: continue

                    pkgs, ver = extract_metadata_from_mounts(name)
                    if pkgs is None:
                        pkgs, ver = extract_metadata_from_raw(f)

                    results.append({"name": name, "packages": pkgs or "unknown", "version": ver})
                    found_names.add(name)
        return {"extensions": sorted(results, key=lambda x: x['name'])}

    def RemoveSysext(self, name, **kwargs):
        with LOCK:
            log(f"Removing extension: {name}")
            for d in [EXT_DIR, CONFEXT_DIR]:
                for f in d.glob(f"{name}*.raw"):
                    f.unlink()
            subprocess.run(["systemd-sysext", "refresh"], check=False)
            subprocess.run(["systemd-confext", "refresh"], check=False)
            return {}

class SysextRequestHandler(varlink.RequestHandler):
    service = sysext_service

def main():
    log("Starting sysext-creator daemon v13.3")
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    with varlink.ThreadingServer(f"unix:{SOCKET_PATH}", SysextRequestHandler) as server:
        os.chmod(SOCKET_PATH, 0o666)
        log(f"✅ Daemon active on {SOCKET_PATH}")
        server.serve_forever()

if __name__ == "__main__":
    main()
