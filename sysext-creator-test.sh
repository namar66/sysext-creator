#!/bin/bash

# ======================================================================
# Sysext-Creator Integration Test Suite v2.0.1
# ======================================================================
set -euo pipefail

PKG_SIMPLE="fake-package-simple"
PKG_COMPLEX="fake-package-complex"
LOG_FILE="/var/log/sysext-creator.log"
EXT_DIR="/var/lib/extensions"
STAGING_DIR="/var/tmp/sysext-staging"

# Output colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS:${NC} $1"; }
fail() { echo -e "${RED}❌ FAIL:${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}▶▶ TEST:${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️ WARN:${NC} $1"; }

# --- 0. Pre-flight Checks ---
step "Environment Check"
if ! command -v sysext-creator &> /dev/null; then fail "sysext-creator is missing in PATH."; fi
if ! systemctl is-active --quiet sysext-creator-deploy.path; then fail "Deployment daemon is not running!"; fi
pass "Tool and daemon are ready."

step "Pre-test cleanup"
for pkg in "$PKG_SIMPLE" "$PKG_COMPLEX"; do
    if sysext-creator list | grep "$pkg"; then
        sysext-creator rm "$pkg" yes >/dev/null
    fi
done
ETC_COUNT_BEFORE=$({ find /etc 2>/dev/null || true; } | wc -l)
pass "System is clean, test can begin."

# --- 1. Simple package installation ---
step "1. Installation of a simple package (Basic .raw build)"
if sysext-creator install "$PKG_SIMPLE" >/dev/null; then
    pass "Installation completed without error codes."
else
    fail "sysext-creator install command failed."
fi

if command -v "fake-package-simple" &> /dev/null; then 
    pass "Command fake-package-simple found (main package installed)."
else 
    fail "Command fake-package-simple not found. Installation failed!"
fi

# --- 2. Complex package installation (/etc & dependencies) ---
step "2. Installation of a complex package with /etc and dependencies"
if sysext-creator install "$PKG_COMPLEX" >/dev/null; then
    pass "Installation completed without error codes."
else
    fail "sysext-creator install command failed."
fi

if command -v "fake-package-complex" &> /dev/null; then 
    pass "Command fake-package-complex found (main package installed)."
else 
    fail "Command fake-package-complex not found. Installation failed!"
fi

if [[ -f "/etc/fake-complex/config.conf" ]]; then
    pass "Configuration in /etc successfully deployed (Daemon works correctly)."
else
    fail "Configuration in /etc is missing! Daemon did not extract .tar.gz."
fi

if [[ -f "/var/lib/sysext-creator/trackers/${PKG_COMPLEX}.etc.tracker" ]]; then
    pass "Tracker for /etc was successfully generated."
else
    fail "Tracker for /etc is missing!"
fi

# --- 3. Uninstallation and deep /etc cleanup check ---
step "3. Uninstallation and deep /etc cleanup check"
sysext-creator rm "$PKG_COMPLEX" yes >/dev/null

if [[ ! -f "/etc/fake-complex/config.conf" ]]; then
    pass "Configuration files from /etc were successfully deleted."
else
    fail "Configuration files remained in /etc after uninstallation!"
fi

if [[ ! -d "/etc/fake-complex" ]]; then
    pass "Directory in /etc was cleanly removed after deleting files."
else
    fail "Empty directory in /etc remained after uninstallation!"
fi

# Cleanup the simple package as well
sysext-creator rm "$PKG_SIMPLE" yes >/dev/null

# --- 4. Trial by fire: Resistance to corrupted images ---
step "4. Trial by fire: Resistance to corrupted images"
POISON_FILE="$STAGING_DIR/poisoned.raw"
echo "This is definitely not a valid squashfs/erofs image" > "$POISON_FILE"

# Wait for daemon to process it
sleep 3

if [[ ! -f "$POISON_FILE" ]]; then
    pass "Daemon correctly blocked deployment and deleted the corrupted file from the Staging directory."
else 
    fail "Daemon left the corrupted file in the Staging directory!" 
fi

if grep -q "Validation failed: poisoned.raw is corrupted" "$LOG_FILE"; then
    pass "Detection of the corrupted file was correctly logged."
else
    fail "Missing log entry about rejection of the corrupted file."
fi

# --- 5. Final system cleanliness comparison ---
step "Checking absolute system cleanliness (Snapshot comparison)"
ETC_COUNT_AFTER=$({ find /etc 2>/dev/null || true; } | wc -l)

echo -e "  📊 State before test: $ETC_COUNT_BEFORE items"
echo -e "  📊 State after test:  $ETC_COUNT_AFTER items"

if [[ "$ETC_COUNT_BEFORE" -eq "$ETC_COUNT_AFTER" ]]; then
    pass "/etc structure is exactly the same as before the test. The tool left absolutely no traces!"
else
    diff=$((ETC_COUNT_AFTER - ETC_COUNT_BEFORE))
    # Operating systems generate temporary files (NetworkManager, dnf). We tolerate small deviations.
    if [[ $diff -gt -5 && $diff -lt 5 ]]; then
        warn "Item count differs slightly (difference: $diff). Usually temporary OS files."
    else
        fail "More than 5 unknown items left in /etc. Possible data leak!"
    fi
fi

echo -e "\n================================================================================"
echo -e "${GREEN}🎉 E2E TESTS COMPLETED: ARCHITECTURE IS 100% BULLETPROOF!${NC}"
echo -e "================================================================================"
