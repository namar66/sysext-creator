import varlink
import subprocess
import pathlib
import os

# Define system paths
SYSEXT_DIR = pathlib.Path("/var/lib/extensions")
CONFEXT_DIR = pathlib.Path("/var/lib/confexts")

class SysextCreatorImpl:
    def GetHostInfo(self, ctx):
        with open("/etc/os-release") as f:
            lines = dict(line.strip().split("=", 1) for line in f if "=" in line)
        
        return {
            "version_id": lines.get("VERSION_ID", "unknown").strip('"'),
            "architecture": os.uname().machine,
            "kernel": os.uname().release
        }

    def DeploySysext(self, ctx, name, path):
        source = pathlib.Path(path)
        if not source.exists():
            return varlink.error.FileNotFound(path=path)
        
        target = SYSEXT_DIR / name
        try:
            # Atomic move/copy
            target.write_bytes(source.read_bytes())
            subprocess.run(["systemd-sysext", "refresh"], check=True)
            return {"status": "Successfully deployed sysext"}
        except Exception as e:
            return varlink.error.DeploymentError(reason=str(e))

    def DeployConfext(self, ctx, name, path):
        source = pathlib.Path(path)
        if not source.exists():
            return varlink.error.FileNotFound(path=path)
        
        target = CONFEXT_DIR / name
        try:
            target.write_bytes(source.read_bytes())
            subprocess.run(["systemd-confext", "refresh"], check=True)
            return {"status": "Successfully deployed confext"}
        except Exception as e:
            return varlink.error.DeploymentError(reason=str(e))

# Setup service
service = varlink.Service(
    vendor="Sysext-Creator Project",
    product="Deployment Daemon",
    version="3.0.0",
    url="https://github.com/nadmartin/sysext-creator",
    interface_dir=".", # Path to .varlink file
)

# Register the interface
service.register_interface(pathlib.Path("io.sysext.creator.varlink").read_text())

# Start serving (using systemd socket activation via file descriptor 3)
if __name__ == "__main__":
    # In production, systemd passes the socket as FD 3
    # For local testing, we can use a standard unix socket
    with varlink.ThreadingServer("unix:/run/sysext-creator.sock", SysextCreatorImpl()) as server:
        server.serve_forever()
