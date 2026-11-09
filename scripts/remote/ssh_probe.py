#!/usr/bin/env python3
"""Read-only SSH inventory with OpenSSH.

Requires a named Host alias in ~/.ssh/config; no command argument interpolation.
Never installs keys, bypasses host-key checks, or runs sudo.
"""
import argparse
import json
import re
import subprocess
import sys

HOST_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PROBE = (
    "printf 'OS\\n'; cat /etc/os-release; "
    "printf '\\nKERNEL\\n'; uname -a; "
    "printf '\\nNETWORK\\n'; ip -s link show; "
    "printf '\\nROUTES\\n'; ip route show; "
    "printf '\\nSTORAGE\\n'; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"
)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host_alias", help="SSH config Host alias (not an arbitrary SSH option)")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()
    if not HOST_ALIAS.fullmatch(args.host_alias) or args.host_alias.startswith("-"):
        parser.error("Invalid SSH host alias")
    if not 1 <= args.timeout <= 120:
        parser.error("Timeout must be between 1 and 120 seconds")
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8", "-o", "NumberOfPasswordPrompts=0",
        args.host_alias, PROBE
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"host_alias": args.host_alias, "error": str(exc)}), file=sys.stderr)
        return 2
    if result.returncode:
        print(json.dumps({"host_alias": args.host_alias, "exit": result.returncode, "error": result.stderr[-3000:]}), file=sys.stderr)
        return result.returncode
    # Raw data can contain private IPs/hostnames. Never upload it automatically.
    print(result.stdout)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
