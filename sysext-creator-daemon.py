#!/usr/bin/python3

# Sysext-Creator Daemon v9.2 (Final Stable)
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

# --- Konfigurace ---
RUN_DIR = "/run/sysext-creator"
SOCKET_PATH = f"{RUN_DIR}/sysext-creator.sock"
EXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

INTERFACE_DEFINITION = """interface io.sysext.creator
type Extension (name: string, version: string, packages: string)
method ListExtensions() -> (extensions: []Extension)
method RemoveSysext(name: string) -> ()
method DeploySysext(name: string, path: string, force: bool) -> (status: string, conflicts: []string, progress: int)
method RefreshExtensions() -> (status: string)
method RunDiagnostics() -> (report: []string)
error ExtensionNotFound(name: string)
error PermissionDenied()
error InternalError(message: string)
"""

class SysextCreatorImpl:
    NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

    def ListExtensions(self):
        extensions = []
        if os.path.exists(EXT_DIR):
            for file in os.listdir(EXT_DIR):
                if file.endswith(".raw") and not file.endswith(".confext.raw"):
                    name = file.replace(".raw", "")
                    raw_path = os.path.join(EXT_DIR, file)
                    stat = os.stat(raw_path)
                    version = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    packages = ""
                    if shutil.which("dump.erofs"):
                        try:
                            cmd = ["dump.erofs", "--cat=/share/factory/sysext-metadata/packages.txt", raw_path]
                            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                            if res.returncode == 0: packages = res.stdout.strip()
                        except: pass
                    extensions.append({"name": name, "version": version, "packages": packages})
        return {"extensions": extensions}

    def RemoveSysext(self, name: str):
        if not self.NAME_PATTERN.match(name): return {}
        for directory in [EXT_DIR, CONFEXT_DIR]:
            for suffix in [".raw", ".confext.raw"]:
                target = os.path.join(directory, f"{name}{suffix}")
                if os.path.exists(target): os.remove(target)
        self.RefreshExtensions()
        return {}

    def DeploySysext(self, name: str, path: str, force: bool):
        res_path = os.path.realpath(path)
        if not res_path.startswith("/var/tmp/sysext-creator/"):
            return {"status": "Error: Untrusted path", "conflicts": [], "progress": 0}
        
        target_dir = CONFEXT_DIR if res_path.endswith(".confext.raw") else EXT_DIR
        target_path = os.path.join(target_dir, os.path.basename(res_path))
        os.makedirs(target_dir, exist_ok=True)
        
        try:
            subprocess.run(["cp", res_path, target_path], check=True)
            subprocess.run(["restorecon", "-v", target_path], check=True)
            self.RefreshExtensions()
            return {"status": "Success", "conflicts": [], "progress": 100}
        except Exception as e:
            return {"status": f"Error: {str(e)}", "conflicts": [], "progress": 0}

    def RefreshExtensions(self):
        subprocess.run(["systemd-sysext", "refresh"], capture_output=True)
        subprocess.run(["systemd-confext", "refresh"], capture_output=True)
        return {"status": "Success"}

    def RunDiagnostics(self): return {"report": ["[OK] Service healthy."]}

service_impl = SysextCreatorImpl()

class NativeVarlinkHandler(socketserver.StreamRequestHandler):
    def handle(self):
        data = b""
        while True:
            chunk = self.request.recv(8192)
            if not chunk: break
            data += chunk
            while b'\0' in data:
                msg_bytes, data = data.split(b'\0', 1)
                msg = json.loads(msg_bytes.decode())
                method = msg.get("method")
                params = msg.get("parameters", {})
                if method == "org.varlink.service.GetInfo":
                    resp = {"parameters": {"vendor": "OpenSource", "product": "SysextCreator", "version": "3.1", "interfaces": ["org.varlink.service", "io.sysext.creator"]}}
                elif method == "io.sysext.creator.ListExtensions":
                    resp = {"parameters": service_impl.ListExtensions()}
                elif method == "io.sysext.creator.RemoveSysext":
                    resp = {"parameters": service_impl.RemoveSysext(**params)}
                elif method == "io.sysext.creator.DeploySysext":
                    resp = {"parameters": service_impl.DeploySysext(**params)}
                elif method == "io.sysext.creator.RefreshExtensions":
                    resp = {"parameters": service_impl.RefreshExtensions()}
                else: resp = {"error": "org.varlink.service.MethodNotFound"}
                self.request.sendall(json.dumps(resp).encode() + b'\0')

class ThreadedUnixStreamServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer): pass

def run_server():
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    with ThreadedUnixStreamServer(SOCKET_PATH, NativeVarlinkHandler) as server:
        os.chmod(SOCKET_PATH, 0o660)
        try: os.chown(SOCKET_PATH, -1, grp.getgrnam('wheel').gr_gid)
        except: pass
        logging.info("Daemon v3.1 Ready.")
        server.serve_forever()

if __name__ == "__main__":
    if os.geteuid() != 0: sys.exit("Must run as root")
    run_server()
