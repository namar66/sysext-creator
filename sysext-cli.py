#!/usr/bin/python3
import sys, os, argparse, subprocess, varlink, re
from pathlib import Path

SOCKET = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"

def connect():
    return varlink.Client(address=SOCKET).open(INTERFACE)

def cmd_list(args):
    with connect() as remote:
        exts = remote.ListExtensions().get("extensions", [])
        print(f"{'NAME':<20} | {'VERSION':<20}")
        print("-" * 45)
        for e in exts: print(f"{e['name']:<20} | {e['version']:<20}")

def cmd_install(args):
    name = args.name_or_rpm
    if name.endswith(".rpm"):
        res = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", name], capture_output=True, text=True)
        name = res.stdout.strip()
    
    print(f"Building {name}...")
    subprocess.run(["toolbox", "run", "-c", "sysext-builder", "python3", "/usr/local/bin/sysext-creator-builder.py", name] + args.packages, check=True)
    
    with connect() as remote:
        remote.DeploySysext(name, f"/var/tmp/sysext-creator/{name}.raw", args.force)
    print("✅ Active.")

def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)
    subs.add_parser("list")
    ins = subs.add_parser("install")
    ins.add_argument("name_or_rpm")
    ins.add_argument("packages", nargs="*")
    ins.add_argument("--force", action="store_true")
    rem = subs.add_parser("remove")
    rem.add_argument("name")
    
    args = p.parse_args()
    if args.cmd == "list": cmd_list(args)
    elif args.cmd == "install": cmd_install(args)
    elif args.cmd == "remove":
        with connect() as remote: remote.RemoveSysext(args.name)

if __name__ == "__main__": main()
