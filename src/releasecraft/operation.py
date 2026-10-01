"""Cooperative cancellation and measured, transient progress (never plan identity)."""
from __future__ import annotations
from pathlib import Path
import threading
import time


class Cancelled(Exception):
    """No public candidate was committed before cancellation."""


class Operation:
    def __init__(self, callback=None, cancelled=None, state_directory=None):
        self.callback = callback
        self.cancelled = cancelled or threading.Event()
        self.state_directory = Path(state_directory) if state_directory else None
        self.started = time.monotonic()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def emit(self, phase, **measured):
        self.check()
        if self.callback:
            self.callback({"phase": phase, "elapsed_seconds": time.monotonic() - self.started, **measured})
        self.check()


def signal(operation, phase, **measured):
    if operation is not None:
        operation.emit(phase, **measured)
