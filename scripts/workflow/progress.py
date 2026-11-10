#!/usr/bin/env python3
"""Best-effort, opt-in progress bridge for image helper scripts.

An Agent-approved preview creates a private preview-runtime.json in the
original discovery session. Without a verified live preview this module does
not write status files or add network traffic. Failures to publish progress
never interfere with image operations. Only fixed stage/state and counters are
published, never filesystem paths, credentials or command output.
"""
from contextlib import contextmanager
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent

def load(name):
    spec = importlib.util.spec_from_file_location("uc_progress_" + name, HERE / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def session_from_plan(plan):
    if not isinstance(plan, dict):
        return None
    discovery = plan.get("discovery")
    return discovery.get("session") if isinstance(discovery, dict) else None

def session_from_build(result):
    if not isinstance(result, dict):
        return None
    return result.get("discovery_session")

def preview_is_live(session):
    if not isinstance(session, (str, Path)) or not str(session):
        return False
    try:
        control = load("preview_control")
        meta = control.read_metadata(session)
        return bool(meta and control.probe(meta, timeout=0.2))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return False

class Tracker:
    def __init__(self, session, stage, total):
        if stage not in ("image-plan", "image-build", "rootfs-build", "first-boot", "verify"):
            raise ValueError("Unsupported image workflow stage")
        if type(total) is not int or not 1 <= total <= 1000000:
            raise ValueError("Invalid workflow total")
        self.session = session
        self.stage = stage
        self.total = total
        self.completed = 0
        self.enabled = preview_is_live(session)
        self.final_state = None
        self._publish("running")

    def _publish(self, state):
        if not self.enabled:
            return
        if not preview_is_live(self.session):
            # Stopping the optional preview disables subsequent auto updates.
            self.enabled = False
            return
        try:
            load("status").update(self.session, self.stage, state,
                                  self.completed, self.total)
        except (OSError, ValueError, RuntimeError, TypeError):
            # Preview is optional, so reporting failure cannot abort a build.
            self.enabled = False

    def advance(self, completed):
        if type(completed) is not int or not self.completed <= completed <= self.total:
            raise ValueError("Invalid or decreasing progress counter")
        self.completed = completed
        if self.final_state is None:
            self._publish("running")

    def blocked(self):
        self.final_state = "blocked"
        self._publish("blocked")

    def failed(self):
        self.final_state = "failed"
        self._publish("failed")

    def complete(self):
        if self.final_state is None:
            self.completed = self.total
            self.final_state = "complete"
            self._publish("complete")

def report_error(session, stage):
    """Override a finished stage if its CLI artifact write subsequently fails."""
    if stage not in ("image-plan", "image-build", "rootfs-build", "first-boot", "verify"):
        raise ValueError("Unsupported image workflow stage")
    if not preview_is_live(session):
        return
    try:
        load("status").update(session, stage, "failed", 0, 1)
    except (OSError, ValueError, RuntimeError, TypeError):
        pass

@contextmanager
def tracking(session, stage, total):
    tracker = Tracker(session, stage, total)
    try:
        yield tracker
    except BaseException:
        if tracker.final_state is None:
            tracker.failed()
        raise
    else:
        tracker.complete()
