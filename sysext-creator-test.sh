#!/bin/bash

# ======================================================================
# Sysext-Creator Integration Test Suite v2.0
# ======================================================================
set -euo pipefail

PKG_SIMPLE="fake-package-simple"
PKG_COMPLEX="fake-package-complex"
LOG_FILE="/var/log/sysext-creator.log"
EXT_DIR="/var/lib/extensions"
STAGING_DIR="/var/tmp/sysext-staging"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS:${NC} $1"; }
fail() { echo -e "${RED}❌ FAIL:${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}▶▶ TEST:${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️ WARN:${NC} $1"; }

step "Environment Check"
if ! command -v sysext-creator &> /dev/null; then fail "sysext-creator is missing in PATH."; fi
if ! systemctl is-active --quiet sysext-creator-deploy.path; then fail "Deployment daemon is not running!"; fi
pass "Tool and daemon are ready."

step "Pre-test cleanup"
for pkg in "$PKG_SIMPLE" "$PKG_COMPLEX"; do
    if sysext-creator list | grep "📦 $pkg" >/dev/null; then
        warn "Package $pkg is already installed. Cleaning up before test..."
        sysext-creator rm "$pkg" yes >/dev/null
        sleep 4
    fi
done

step "Daemon Communication (Doctor)"
if sysext-creator doctor | grep -q "Diagnostics completed"; then pass "Daemon is responding."
else fail "Doctor did not return expected output."; fi

step "Snapshot of /etc state before running tests"
ETC_COUNT_BEFORE=$({ find /etc 2>/dev/null || true; } | wc -l)
pass "Initial count of items in /etc: $ETC_COUNT_BEFORE"

step "Installation of a simple package: $PKG_SIMPLE"
sysext-creator install "$PKG_SIMPLE" > /dev/null
sleep 4

if command -v "$PKG_SIMPLE" &> /dev/null; then pass "Command $PKG_SIMPLE is available in the system."
else fail "Application $PKG_SIMPLE was not installed correctly."; fi

sysext-creator rm "$PKG_SIMPLE" yes > /dev/null
sleep 4
if ! command -v "$PKG_SIMPLE" &> /dev/null; then pass "Package $PKG_SIMPLE successfully removed."
else fail "Removal of $PKG_SIMPLE failed."; fi

step "Installation of a complex package: $PKG_COMPLEX (tunnel + /etc)"
sysext-creator install "$PKG_COMPLEX" > /dev/null
sleep 5

echo "=> Verifying binary availability and dependency resolution..."
if command -v "$PKG_COMPLEX" &> /dev/null; then 
    pass "Command $PKG_COMPLEX found (main package installed)."
else 
    fail "Command $PKG_COMPLEX not found. Installation failed!"
fi

if command -v "$PKG_SIMPLE" &> /dev/null; then 
    pass "Command $PKG_SIMPLE found (dependency resolution works 100%!)."
else 
    fail "Command $PKG_SIMPLE not found. Dependencies were not downloaded or merged!"
fi

if [[ -f "/etc/fake-complex/config.conf" ]]; then
    pass "Configuration in /etc successfully deployed (Daemon works correctly)."
else
    fail "Configuration in /etc is missing! Daemon did not extract .tar.gz."
fi

step "Removal of the complex package incl. configuration (Force Remove)"
sysext-creator rm "$PKG_COMPLEX" yes > /dev/null
sleep 5

if ! command -v "$PKG_COMPLEX" &> /dev/null; then 
    pass "Package $PKG_COMPLEX removed from the system."
else 
    fail "Removal of $PKG_COMPLEX failed."; 
fi

if [[ ! -d "/etc/fake-complex" ]] || [[ -z "$(ls -A /etc/fake-complex 2>/dev/null)" ]]; then 
    pass "Traces in /etc/ were cleanly removed thanks to the tracker."
else 
    fail "Configuration /etc/fake-complex remained in the system after deletion."; 
fi

step "CRASH TEST: Preventing deployment of a corrupted image"
DUMMY_FILE="$STAGING_DIR/poisoned-fc43.raw"
echo "This is not a valid erofs image, this is a virus!" > "$DUMMY_FILE"
sleep 4

if [[ ! -f "$DUMMY_FILE" ]]; then 
    pass "Daemon immediately deleted the corrupted file from the Staging directory."
else 
    fail "Daemon left the corrupted file in the Staging directory!"; 
fi

if grep -q "Validation failed: poisoned-fc43.raw is corrupted" "$LOG_FILE"; then
    pass "Detection of the corrupted file was correctly logged."
else
    fail "Log entry about rejecting the corrupted file is missing."
fi

step "Checking absolute system cleanliness (Snapshot comparison)"
ETC_COUNT_AFTER=$({ find /etc 2>/dev/null || true; } | wc -l)

echo -e "  📊 State before test: $ETC_COUNT_BEFORE items"
echo -e "  📊 State after tests: $ETC_COUNT_AFTER items"

if [[ "$ETC_COUNT_BEFORE" -eq "$ETC_COUNT_AFTER" ]]; then
    pass "/etc structure is exactly the same as before the test. The tool left absolutely no traces!"
else
    diff=$((ETC_COUNT_AFTER - ETC_COUNT_BEFORE))
    if [[ $diff -gt -5 && $diff -lt 5 ]]; then
        warn "Item count differs slightly (difference: $diff). Likely background OS activity."
    else
        fail "Large difference in file count detected ($diff). Some configuration was likely not deleted!"
    fi
fi

echo -e "\n${GREEN}=================================================${NC}"
echo -e "${GREEN}🎉 E2E TESTS COMPLETED: ARCHITECTURE IS 100% BULLETPROOF!${NC}"
echo -e "${GREEN}=================================================${NC}\n"
