#!/usr/bin/python3

# Sysext-Creator Auto-Updater v3.0
# Periodically rebuilds extensions to fetch the latest RPM packages.

import os
import sys
import subprocess
import varlink
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
CONTAINER_NAME = "sysext-builder"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
BUILD_DIR = Path.home() / "sysext-builds"

def update_extensions():
    try:
        client = varlink.Client(address=SOCKET_PATH)
        remote = client.open(INTERFACE)
    except Exception as e:
        logging.error(f"Failed to connect to daemon via Varlink: {e}")
        sys.exit(1)

    try:
        res = remote.ListExtensions()
        extensions = res.get("extensions", [])
    except Exception as e:
        logging.error(f"Failed to fetch extensions from daemon: {e}")
        sys.exit(1)

    if not extensions:
        logging.info("No extensions found. Nothing to update.")
        return

    # Translate host path to toolbox path if needed
    toolbox_script_path = BUILDER_SCRIPT
    if toolbox_script_path.startswith("/usr/"):
        toolbox_script_path = "/run/host" + toolbox_script_path

    for ext in extensions:
        name = ext.get("name")
        packages = ext.get("packages")

        # Skip extensions built before we added the packages metadata feature
        if not packages or packages == "N/A":
            logging.warning(f"Skipping '{name}': No package metadata available.")
            continue

        logging.info(f"Starting update for '{name}' (Packages: {packages})")

        # Step 1: Rebuild inside Toolbox
        build_cmd = ["toolbox", "run", "-c", CONTAINER_NAME, "python3", toolbox_script_path, name] + packages.split()
        try:
            subprocess.run(build_cmd, check=True)
        except subprocess.CalledProcessError:
            logging.error(f"Build failed for '{name}'. Moving to next extension.")
            continue

        # Step 2: Deploy new images via Daemon
        sysext_path = BUILD_DIR / f"{name}.raw"
        confext_path = BUILD_DIR / f"{name}.confext.raw"

        deployed = False
        for path in [sysext_path, confext_path]:
            if path.exists():
                logging.info(f"Deploying updated image: {path.name}")
                try:
                    # Using force=True to ensure unattended updates do not block on warnings
                    remote.DeploySysext(name, str(path), True)
                    deployed = True
                except varlink.error.VarlinkError as e:
                    logging.error(f"Daemon error deploying {path.name}: {e}")

        if deployed:
            logging.info(f"Successfully updated '{name}'.")

    logging.info("Auto-Updater finished successfully.")

if __name__ == "__main__":
    update_extensions()
