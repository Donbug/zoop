"""Cooperative admission control between the container controller and one collection path.

A path calls `boundary()` only where its durable state is saved and no request is in flight. The call returns
True once the path must stop admitting work; while the controller holds the path paused it does not return. The
default control never stops and never pauses, so every CLI keeps its existing behaviour.
"""
from __future__ import annotations

import json
import os
import select


class Control:
    def __init__(self, *, stopping=False):
        self._stopping = stopping

    def request_stop(self):
        self._stopping = True

    def boundary(self) -> bool:
        return self._stopping


class _NoControl(Control):
    def request_stop(self):
        raise RuntimeError("the default control cannot be stopped")


NO_CONTROL = _NoControl()


class PipeControl(Control):
    """Line protocol on the worker's stdin: `PAUSE <nonce>`, `RESUME`, `STOP`; acknowledgements go to `events_fd`.

    A PAUSE is acknowledged at the next boundary, then the worker blocks until RESUME or STOP. EOF on the command
    pipe (the controller died) is a STOP.
    """

    def __init__(self, commands_fd: int, events_fd: int, *, stopping=False):
        super().__init__(stopping=stopping)
        self._commands, self._events = commands_fd, events_fd
        self._buffer = b""
        self._pause = None
        self._resumed = False

    def emit(self, event: dict) -> None:
        os.write(self._events, (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode())

    def _read(self, timeout: float | None) -> None:
        if self._stopping and self._pause is None:
            return
        ready, _, _ = select.select([self._commands], [], [], timeout)
        if not ready:
            return
        chunk = os.read(self._commands, 4096)
        if not chunk:
            self._stopping = True
            return
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            word, _, argument = line.decode().partition(" ")
            if word == "STOP":
                self._stopping = True
            elif word == "PAUSE":
                self._pause, self._resumed = argument, False
            elif word == "RESUME":
                self._resumed = True

    def boundary(self) -> bool:
        self._read(0)
        if self._pause is not None and not self._stopping:
            self.emit({"event": "paused", "nonce": self._pause})
            while not self._resumed and not self._stopping:
                self._read(1.0)
            self._pause = None
        return self._stopping
