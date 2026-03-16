#!/usr/bin/python3
import sys

# Simulace barev a logiky Doctora
class Colors:
    OK = '\033[92m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'

def test_scenario(name, mock_dissect_rc, mock_varlink_ok):
    print(f"\n=== Testing Scenario: {name} ===")
    
    # 1. Test "Systemd-dissect" logic
    if mock_dissect_rc == 0:
        print(f"[{Colors.OK} OK {Colors.END}] Systemd-dissect validation passed.")
    else:
        print(f"[{Colors.FAIL}FAIL{Colors.END}] Systemd validation failed! Image corrupted.")

    # 2. Test "Varlink" logic
    if mock_varlink_ok:
        print(f"[{Colors.OK} OK {Colors.END}] Varlink IPC communication successful.")
    else:
        print(f"[{Colors.FAIL}FAIL{Colors.END}] Daemon socket missing or access denied.")

    # Determine final result
    success = (mock_dissect_rc == 0 and mock_varlink_ok)
    if success:
        print(f"{Colors.OK}RESULT: Extension is SAFE to install.{Colors.END}")
        return 0
    else:
        print(f"{Colors.FAIL}RESULT: Installation ABORTED.{Colors.END}")
        return 1

# --- RUN QUICK TESTS ---
print("Running Sysext Doctor Logic Test Suite...")

# Test 1: Vše je v pořádku (např. po buildu)
rc1 = test_scenario("Healthy Extension", mock_dissect_rc=0, mock_varlink_ok=True)

# Test 2: Poškozený soubor (např. stažený z netu)
rc2 = test_scenario("Corrupted Image", mock_dissect_rc=1, mock_varlink_ok=True)

# Test 3: Vypnutý démon
rc3 = test_scenario("Dead Daemon", mock_dissect_rc=0, mock_varlink_ok=False)

print("\n" + "="*30)
print(f"Final Test Summary: RC {rc1}, {rc2}, {rc3}")
if rc1 == 0 and rc2 == 1 and rc3 == 1:
    print("Doctor logic verified: Success and Failure states are correctly handled.")
