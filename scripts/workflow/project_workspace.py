#!/usr/bin/env python3
"""Prepare the current ubuntu-customizer project workspace without network access.

The Skill owns this local R0/R1 setup step. This helper does not connect to
devices, install packages, run untrusted commands or change host settings.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

OUTPUTS = "outputs"
VENV = ".venv"


def project_root(root=None):
    """The current working directory is the workspace (not the script folder)."""
    base = Path(root) if root is not None else Path.cwd()
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Project workspace must be an existing real directory")
    base = base.resolve()
    if not (base / "SKILL.md").is_file() or not (base / "scripts" / "workflow").is_dir():
        # Lima/remote runner may execute an absolute script path from a
        # different working directory. Anchor outputs to that script's
        # actual repository, never to the guest's arbitrary home directory.
        if root is not None:
            raise ValueError("Explicit project root is not ubuntu-customizer")
        base = Path(__file__).resolve().parents[2]
        if not (base / "SKILL.md").is_file() or not (base / "scripts" / "workflow").is_dir():
            raise ValueError("No ubuntu-customizer project workspace available")
    return base


def ensure_outputs(root=None):
    base = project_root(root)
    target = base / OUTPUTS
    if target.is_symlink():
        raise ValueError("outputs must not be a symlink")
    if target.exists():
        if not target.is_dir():
            raise ValueError("outputs exists but is not a directory")
    else:
        target.mkdir(mode=0o700)
    # Captured device evidence contains private identifiers.
    target.chmod(0o700)
    return target


def output_path(*parts, root=None):
    """Resolve an output path safely under the project's outputs directory."""
    base = ensure_outputs(root)
    if not parts:
        return base
    for part in parts:
        segment = Path(part)
        if segment.is_absolute() or not segment.parts or ".." in segment.parts:
            raise ValueError("Output path must be relative to outputs")
    result = base.joinpath(*parts)
    candidate = base
    for part in result.relative_to(base).parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError("Output path must not include symlinks")
    try:
        result.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("Output escapes outputs directory") from exc
    return result


def checked_output(value, root=None):
    """Validate a CLI output as a new path inside the current outputs tree."""
    base = ensure_outputs(root)
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root(root) / candidate
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("All Skill output files must be under ./outputs") from exc
    if not relative.parts:
        raise ValueError("Choose a new file or session beneath outputs")
    return output_path(*relative.parts, root=root)



def prepare(root=None, create_venv=True):
    base = project_root(root)
    folder = ensure_outputs(base)
    env = base / VENV
    if env.is_symlink():
        raise ValueError(".venv must not be a symlink")
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not env.exists():
        if create_venv:
            # stdlib venv, with locally bundled ensurepip only (no downloads).
            subprocess.run([sys.executable, "-m", "venv", str(env)],
                           cwd=base, check=True, timeout=180)
    elif not env.is_dir():
        raise ValueError(".venv exists but is not a directory")
    if create_venv and (not (env / "pyvenv.cfg").is_file() or not python.is_file()):
        raise ValueError("Existing .venv is incomplete; manual repair required")
    return {"state": "ready", "workspace": str(base), "venv": str(env),
            "python": str(python), "outputs": str(folder)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="Verify workspace and create private outputs; do not create .venv")
    args = parser.parse_args(argv)
    try:
        result = prepare(create_venv=not args.check_only)
    except (OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
