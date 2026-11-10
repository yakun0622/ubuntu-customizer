"""Resolve safe NEW output directories across Linux and macOS.

macOS has system-owned aliases such as /var -> /private/var and
/tmp -> /private/tmp. Accept only these exact verified system aliases,
never arbitrary symlinked parents. Return the canonical target so callers,
subprocesses, manifests and tests agree on the same physical directory.
No directory is created here.
"""
from pathlib import Path
import sys

MACOS_SYSTEM_ALIASES = {
    "/var": "/private/var",
    "/tmp": "/private/tmp",
}
FORBIDDEN_ROOTS = ("/dev", "/proc", "/sys")

def canonical_new_directory(path):
    raw = Path(path).expanduser().absolute()
    if ".." in raw.parts:
        raise ValueError("Parent-directory traversal is not allowed")
    if raw.exists() or raw.is_symlink():
        raise ValueError("Output directory must not already exist")
    if any(raw == Path(root) or Path(root) in raw.parents
           for root in FORBIDDEN_ROOTS):
        raise ValueError("Cannot create an output in a pseudo-filesystem")
    for ancestor in (raw.parent, *raw.parent.parents):
        if not ancestor.is_symlink():
            continue
        target = MACOS_SYSTEM_ALIASES.get(str(ancestor))
        if not (sys.platform == "darwin" and target
                and ancestor.resolve() == Path(target)
                and Path(target).is_dir() and not Path(target).is_symlink()):
            raise ValueError("Symlink output ancestors are not allowed")
    if not raw.parent.is_dir():
        raise ValueError("Output parent must already exist")
    canonical_parent = raw.parent.resolve(strict=True)
    canonical = canonical_parent / raw.name
    if canonical.exists() or canonical.is_symlink():
        raise ValueError("Canonical output directory already exists")
    if any(canonical == Path(root) or Path(root) in canonical.parents
           for root in FORBIDDEN_ROOTS):
        raise ValueError("Canonical output points inside a pseudo-filesystem")
    return canonical
