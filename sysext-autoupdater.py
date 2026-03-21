#!/usr/bin/python3

# Sysext-Creator Auto-Updater v1.2
# Periodically rebuilds extensions via safe Drop-Zone.

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
BUILD_DIR = Path("/var/tmp/sysext-creator")

def update_extensions():
    try:
        client = varlink.Client(address=SOCKET_PATH)
        remote = client.open(INTERFACE)
    except Exception as e:
        logging.error(f"Failed to connect to daemon: {e}")
        sys.exit(1)

    try:
        res = remote.ListExtensions()
        extensions = res.get("extensions", [])
    except Exception as e:
        logging.error(f"Failed to fetch extensions: {e}")
        sys.exit(1)

    if not extensions:
        logging.info("No extensions found to update.")
        return

    # Cesta uvnitř Toolboxu k hostitelskému skriptu
    toolbox_script_path = "/run/host" + BUILDER_SCRIPT

    for ext in extensions:
        name = ext.get("name")
        packages = ext.get("packages", "")

        if not packages or packages == "N/A" or "missing" in packages:
            logging.warning(f"Skipping '{name}': No metadata.")
            continue

        logging.info(f"Updating '{name}'...")

        build_args = ["run", "-c", CONTAINER_NAME, "python3", toolbox_script_path, name] + packages.split()
        try:
            subprocess.run(["toolbox"] + build_args, check=True)

            # Nasazení po úspěšném buildu
            for suffix in ["", ".confext"]:
                path = BUILD_DIR / f"{name}{suffix}.raw"
                if path.exists():
                    remote.DeploySysext(name, str(path), True)
            logging.info(f"Successfully updated '{name}'.")
        except Exception as e:
            logging.error(f"Update failed for '{name}': {e}")

if __name__ == "__main__":
    update_extensions()
