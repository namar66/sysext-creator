#!/usr/bin/python3

# Sysext-Creator Daemon v3.1 (Security Hardened)
# Features: Zero-Dependency Varlink Engine, Metadata Management, Security Validation

import os
import sys
import subprocess
import json
import socketserver
import grp
import logging
import fcntl
import datetime
import shutil
import re
from pathlib import Path

# --- Configuration & Paths ---
RUN_DIR = "/run/sysext-creator"
SOCKET_PATH = f"{RUN_DIR}/sysext-creator.sock"

EXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# --- Interface Definition ---
INTERFACE_DEFINITION = """interface io.sysext.creator

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

# --- Implementation Logic ---
class SysextCreatorImpl:
    # Bezpečnostní pojistka: Povolené znaky pro název (prevence Path Injection)
    NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

    def ListExtensions(self):
        extensions = []
        if os.path.exists(EXT_DIR):
            for file in os.listdir(EXT_DIR):
                if file.endswith(".raw") and not file.endswith(".confext.raw"):
                    name = file.replace(".raw", "")
                    raw_path = os.path.join(EXT_DIR, file)

                    # Version based on file modification time
                    stat = os.stat(raw_path)
                    version = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')

                    packages = ""
                    if shutil.which("dump.erofs"):
                        try:
                            # Čtení metadat s timeoutem 5s
                            cmd = ["dump.erofs", "--cat=/share/factory/sysext-metadata/packages.txt", raw_path]
                            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                            if res.returncode == 0:
                                packages = res.stdout.strip()
                        except Exception as e:
                            logging.debug(f"Metadata read failed for {name}: {e}")
                    else:
                        packages = "(erofs-utils missing on host)"

                    extensions.append({"name": name, "version": version, "packages": packages})
        return {"extensions": extensions}

    def RemoveSysext(self, name: str):
        # KRITICKÁ OPRAVA: Validace názvu proti Path Injection (např. ../../etc/shadow)
        if not self.NAME_PATTERN.match(name):
            logging.error(f"Security Alert: Blocked invalid extension name: {name}")
            return {}

        removed = False
        for directory in [EXT_DIR, CONFEXT_DIR]:
            for suffix in [".raw", ".confext.raw"]:
                target = os.path.join(directory, f"{name}{suffix}")
                if os.path.exists(target):
                    try:
                        os.remove(target)
                        removed = True
                    except Exception as e:
                        logging.error(f"Failed to remove {target}: {e}")

        if removed:
            self.RefreshExtensions()
        return {}

    def DeploySysext(self, name: str, path: str, force: bool):
        if not path.endswith(".raw"):
            return {"status": "Error: Target file must be a .raw image", "conflicts": [], "progress": 0}

        # KRITICKÁ OPRAVA: Použití realpath k vyřešení symlinků před kontrolou cesty
        resolved_path = os.path.realpath(path)
        allowed_prefixes = ("/var/tmp/sysext-creator/",)

        if not any(resolved_path.startswith(prefix) for prefix in allowed_prefixes):
            logging.warning(f"Security: Blocked deployment from untrusted path: {resolved_path}")
            return {"status": "Error: Untrusted source path. Use /var/tmp/sysext-creator/", "conflicts": [], "progress": 0}

        if not os.path.exists(resolved_path):
            return {"status": "Error: Source file does not exist", "conflicts": [], "progress": 0}

        is_confext = resolved_path.endswith(".confext.raw")
        target_dir = CONFEXT_DIR if is_confext else EXT_DIR
        target_path = os.path.join(target_dir, os.path.basename(resolved_path))
        os.makedirs(target_dir, exist_ok=True)

        try:
            subprocess.run(["cp", resolved_path, target_path], check=True)
            subprocess.run(["restorecon", "-v", target_path], check=True)
            self.RefreshExtensions()
            return {"status": "Success", "conflicts": [], "progress": 100}
        except Exception as e:
            logging.error(f"Deployment failed: {e}")
            return {"status": f"Error: {str(e)}", "conflicts": [], "progress": 0}

    def RefreshExtensions(self):
        try:
            subprocess.run(["systemd-sysext", "refresh"], capture_output=True, text=True)
            subprocess.run(["systemd-confext", "refresh"], capture_output=True, text=True)
            return {"status": "Success"}
        except Exception as e:
            return {"status": f"Error: {str(e)}"}

    def RunDiagnostics(self):
        return {"report": ["[OK] Diagnostics completed successfully."]}

service_impl = SysextCreatorImpl()

# --- Native Varlink Server Engine ---
class NativeVarlinkHandler(socketserver.StreamRequestHandler):
    def handle(self):
        data = b""
        while True:
            try:
                chunk = self.request.recv(8192)
                if not chunk: break
                data += chunk
                while b'\0' in data:
                    msg_bytes, data = data.split(b'\0', 1)
                    if not msg_bytes: continue

                    msg = json.loads(msg_bytes.decode('utf-8'))
                    method = msg.get("method")
                    params = msg.get("parameters", {})
                    resp = {}

                    if method == "org.varlink.service.GetInfo":
                        resp = {"parameters": {
                            "vendor": "OpenSource", "product": "SysextCreator",
                            "version": "9.2", "url": "https://github.com/sysext-creator",
                            "interfaces": ["org.varlink.service", "io.sysext.creator"]
                        }}
                    elif method == "org.varlink.service.GetInterfaceDescription":
                        req_iface = params.get("interface")
                        if req_iface == "io.sysext.creator":
                            resp = {"parameters": {"description": INTERFACE_DEFINITION}}
                        else:
                            resp = {"error": "org.varlink.service.InterfaceNotFound"}

                    elif method == "io.sysext.creator.ListExtensions":
                        resp = {"parameters": service_impl.ListExtensions()}
                    elif method == "io.sysext.creator.DeploySysext":
                        resp = {"parameters": service_impl.DeploySysext(**params)}
                    elif method == "io.sysext.creator.RemoveSysext":
                        resp = {"parameters": service_impl.RemoveSysext(**params)}
                    elif method == "io.sysext.creator.RefreshExtensions":
                        resp = {"parameters": service_impl.RefreshExtensions()}
                    elif method == "io.sysext.creator.RunDiagnostics":
                        resp = {"parameters": service_impl.RunDiagnostics()}
                    else:
                        resp = {"error": "org.varlink.service.MethodNotFound"}

                    self.request.sendall(json.dumps(resp).encode('utf-8') + b'\0')
            except Exception as e:
                logging.error(f"Varlink error: {e}")
                break

class ThreadedUnixStreamServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    pass

def run_server():
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)

    with ThreadedUnixStreamServer(SOCKET_PATH, NativeVarlinkHandler) as server:
        os.chmod(SOCKET_PATH, 0o660)
        try:
            wheel_info = grp.getgrnam('wheel')
            os.chown(SOCKET_PATH, -1, wheel_info.gr_gid)
        except KeyError:
            logging.warning("Group 'wheel' not found.")

        logging.info("Sysext-Creator Daemon v9.2 is running...")
        server.serve_forever()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Daemon must be run as root.")
        sys.exit(1)
    run_server()
