#!/usr/bin/env python3
"""Explicitly opt-in local preview lifecycle for the ubuntu-customizer Skill.

Starts, checks or stops only the local, read-only status HTTP server.
Never operates on a remote device and never starts without a user-approved
Agent request. Runtime metadata remains under the private session directory.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
PREVIEW = HERE / "preview.py"
RUNTIME = "preview-runtime.json"
MAX_RECORD = 4096

def private_session(session):
    p = Path(session).expanduser()
    if p.is_symlink() or not p.is_dir():
        raise ValueError("A real, existing session directory is required")
    return p.resolve()

def metadata_path(session):
    return private_session(session) / RUNTIME

def read_metadata(session):
    path = metadata_path(session)
    if path.is_symlink():
        raise ValueError("Unsafe preview runtime symlink")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_RECORD:
        raise ValueError("Invalid preview runtime file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported preview runtime metadata")
    if not isinstance(data.get("port"), int) or not 1024 <= data["port"] <= 65535:
        raise ValueError("Invalid preview port")
    if not isinstance(data.get("pid"), int) or data["pid"] <= 0:
        raise ValueError("Invalid preview PID")
    if not isinstance(data.get("instance_id"), str) or len(data["instance_id"]) != 32:
        raise ValueError("Invalid preview identity")
    if data.get("session") != str(private_session(session)):
        raise ValueError("Preview belongs to a different session")
    return data

def choose_port(requested):
    if requested is not None and requested != 0:
        if not 1024 <= requested <= 65535:
            raise ValueError("Port must be 1024–65535, or 0 for automatic")
        return requested
    # The final child bind confirms availability; a race can be safely retried.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    if port < 1024:
        raise RuntimeError("Unable to select an unprivileged localhost port")
    return port

def probe(metadata, timeout=0.5):
    url = f"http://127.0.0.1:{metadata['port']}/api/identity"
    try:
        req = Request(url, headers={"Host": f"127.0.0.1:{metadata['port']}"})
        with urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read(512))
    except (OSError, ValueError, TimeoutError):
        return False
    return (data.get("instance_id") == metadata["instance_id"]
            and type(data.get("pid")) is int
            and data.get("pid") == metadata["pid"])

def status(session):
    data = read_metadata(session)
    if data is None:
        return {"state": "not_started"}
    running = probe(data)
    return {"state": "running" if running else "stale",
            "url": f"http://127.0.0.1:{data['port']}/" if running else None}

def start(session, port=0):
    folder = private_session(session)
    path = metadata_path(folder)
    if path.exists() or path.is_symlink():
        raise ValueError("A preview record already exists. Use status/stop or clear-stale first.")
    port = choose_port(port)
    identity = secrets.token_hex(16)
    args = [sys.executable, str(PREVIEW), str(folder), "--port", str(port),
            "--instance-id", identity]
    # The process is local only. It is started exclusively by this explicit
    # command after the Agent has obtained user approval.
    with open(os.devnull, "wb") as sink:
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                 stdout=sink, stderr=sink, start_new_session=True,
                                 close_fds=True)
    data = {
        "schema_version": 1, "session": str(folder), "instance_id": identity,
        "port": port, "pid": child.pid,
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        for _ in range(40):
            if child.poll() is not None:
                raise RuntimeError("Preview server exited before becoming ready")
            if probe(data, timeout=0.2):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Local preview failed its readiness check")
        # Exclusive creation prevents a second manager from overwriting
        # another preview record. On failure, terminate our own child.
        with path.open("x", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
            f.write("\n")
        path.chmod(0o600)
    except Exception:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        raise
    return {"state": "running", "url": f"http://127.0.0.1:{port}/"}

def stop(session):
    data = read_metadata(session)
    if data is None:
        return {"state": "not_started"}
    if not probe(data):
        raise ValueError("Preview identity not verified. Use clear-stale to remove a stale record without signaling a PID.")
    # The endpoint must confirm a matching random instance ID AND PID before
    # SIGTERM is sent. No HTTP command endpoint is exposed by the preview.
    os.kill(data["pid"], signal.SIGTERM)
    for _ in range(30):
        if not probe(data, timeout=0.15):
            path = metadata_path(session)
            if not path.is_symlink():
                path.unlink(missing_ok=True)
            return {"state": "stopped"}
        time.sleep(0.1)
    raise RuntimeError("Stop signal sent, but the preview is still responding")

def clear_stale(session):
    data = read_metadata(session)
    if data is None:
        return {"state": "not_started"}
    if probe(data):
        raise ValueError("Refusing to clear metadata while the preview is running; use stop")
    path = metadata_path(session)
    if path.is_symlink():
        raise ValueError("Refusing runtime symlink")
    path.unlink()
    return {"state": "stale_record_cleared"}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("start", "status", "stop", "clear-stale"):
        sp = commands.add_parser(name)
        sp.add_argument("session")
        if name == "start":
            sp.add_argument("--port", type=int, default=0,
                            help="local port (0 chooses an available port)")
            sp.add_argument("--approved", action="store_true",
                            help="Agent confirms the user explicitly opted into preview")
    args = p.parse_args(argv)
    try:
        if args.command == "start":
            if not args.approved:
                raise ValueError("Preview is opt-in. Start requires --approved after explicit user consent.")
            result = start(args.session, args.port)
        elif args.command == "status":
            result = status(args.session)
        elif args.command == "stop":
            result = stop(args.session)
        else:
            result = clear_stale(args.session)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
