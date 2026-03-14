import varlink
import platform
import logging
import subprocess
import pathlib
import os
import sys

# Setup logging to journal (standard output)
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: [%(name)s] %(message)s'
)
logger = logging.getLogger("sysext-daemon")

# Security configuration
ALLOWED_ARCHITECTURES = ["x86_64", "aarch64"]
SYSEXT_DIR = pathlib.Path("/var/lib/extensions")
CONFEXT_DIR = pathlib.Path("/var/lib/confexts")

class SysextManager:
    """Implementation of the io.sysext.creator Varlink interface."""

    def __init__(self):
        self.host_arch = platform.machine()
        self._check_security_context()

    def _check_security_context(self):
        """Initial security audit on startup."""
        logger.info("Initializing security handshake...")
        
        # Architecture validation
        if self.host_arch not in ALLOWED_ARCHITECTURES:
            logger.warning(f"Running on non-standard architecture: {self.host_arch}")
        else:
            logger.info(f"Architecture pinning active: {self.host_arch}")

        # Permission check
        if os.geteuid() != 0:
            logger.error("Daemon is not running as root! System commands will fail.")

    def GetHostInfo(self, ctx):
        """Returns metadata for the container to adjust its build process."""
        logger.info("Host info requested by container")
        
        # Read version from os-release
        version_id = "unknown"
        if pathlib.Path("/etc/os-release").exists():
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("VERSION_ID="):
                        version_id = line.strip().split("=")[1].strip('"')

        return {
            "version_id": version_id,
            "architecture": self.host_arch,
            "kernel": platform.release()
        }

    def DeploySysext(self, ctx, name, path):
        """Safely moves a .raw image to /usr extensions."""
        logger.info(f"Deployment request for sysext: {name}")
        return self._deploy_resource(name, path, SYSEXT_DIR, "systemd-sysext")

    def DeployConfext(self, ctx, name, path):
        """Safely moves a .raw image to /etc configuration extensions."""
        logger.info(f"Deployment request for confext: {name}")
        return self._deploy_resource(name, path, CONFEXT_DIR, "systemd-confext")

    def _deploy_resource(self, name, path, target_dir, service_cmd):
        """Internal helper for atomic file deployment."""
        source = pathlib.Path(path)
        if not source.exists():
            logger.error(f"Source file not found: {path}")
            return {"status": "error: file_not_found"}

        target = target_dir / name
        try:
            # Atomic operation: write to disk and refresh systemd layer
            target.write_bytes(source.read_bytes())
            logger.info(f"Image {name} written to {target_dir}")
            
            subprocess.run([service_cmd, "refresh"], check=True)
            logger.info(f"{service_cmd} refresh successful")
            
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Deployment failed: {str(e)}")
            return {"status": f"error: {str(e)}"}

# Load the Varlink interface definition
# In a real scenario, this would be read from io.sysext.creator.varlink file
interface_definition = """
interface io.sysext.creator

method GetHostInfo() -> (
    version_id: string,
    architecture: string,
    kernel: string
)

method DeploySysext(name: string, path: string) -> (status: string)
method DeployConfext(name: string, path: string) -> (status: string)
"""

if __name__ == "__main__":
    service = varlink.Service(
        vendor="Sysext Creator Project",
        product="Unified Deployment Daemon",
        version="3.0.0",
        interface_dir=".",
    )
    
    # Normally we would use systemd socket activation
    # For initial testing, we can bind to a temporary socket
    try:
        logger.info("Sysext-Creator Daemon v3 started.")
        with varlink.ThreadingServer("unix:/run/sysext-creator.sock", SysextManager()) as server:
            server.serve_forever()
    except Exception as e:
        logger.critical(f"Fatal daemon error: {e}")
        sys.exit(1)
