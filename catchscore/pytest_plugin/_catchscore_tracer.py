"""Records which lines of the mutated files each test runs. Loaded into the project's own Python, so it
imports nothing outside the standard library (and not pytest: child processes load it too).

Lines run while a module or class body executes are recorded under "" (not tied to one test): a bug
there affects every test that imports the module, so all tests must run for it.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
from inspect import CO_NEWLOCALS

ENV_FILES = "CATCHSCORE_TRACE_FILES"  # JSON {realpath: relative path} of files to watch
ENV_OUT = "CATCHSCORE_TRACE_OUT"      # directory the hit maps are written to
ENV_TEST = "CATCHSCORE_TEST"          # node id of the running test, inherited by child processes


class Tracer:
    def __init__(self, files: dict[str, str], child: bool = False):
        self.files = files
        self.child = child  # a process started by a test: everything it runs counts for that test
        self.known: dict[str, str | None] = {}
        self.current = os.environ.get(ENV_TEST, "") if child else ""
        self.import_depth = 0
        self.hits: dict[str, set[tuple[str, int]]] = {}
        self.cancelled = False

    def _rel(self, filename: str) -> str | None:
        if filename not in self.known:
            self.known[filename] = self.files.get(os.path.realpath(filename))
        return self.known[filename]

    def _global(self, frame, event, arg):
        if self._rel(frame.f_code.co_filename) is None:
            return None
        if not frame.f_code.co_flags & CO_NEWLOCALS:  # a module or class body
            self.import_depth += 1
            return self._body
        return self._local

    def _record(self, frame):
        key = "" if self.import_depth and not self.child else self.current
        self.hits.setdefault(key, set()).add((self.known[frame.f_code.co_filename], frame.f_lineno))

    def _local(self, frame, event, arg):
        if event == "line":
            self._record(frame)
        return self._local

    def _body(self, frame, event, arg):
        if event == "line":
            self._record(frame)
        elif event == "return":
            self.import_depth -= 1
        return self._body

    def start(self):
        threading.settrace(self._global)
        sys.settrace(self._global)

    def stop(self):
        sys.settrace(None)
        threading.settrace(None)

    def write(self, path: str):
        if self.cancelled:
            return
        with open(path, "w") as f:
            json.dump({k: sorted(v) for k, v in self.hits.items()}, f)


_child: Tracer | None = None


def from_env(child: bool = False) -> Tracer | None:
    files = os.environ.get(ENV_FILES)
    return Tracer(json.loads(files), child) if files and os.environ.get(ENV_OUT) else None


def start_child():
    """Called from sitecustomize in every Python process while tracing is on."""
    global _child
    _child = from_env(child=True)
    if _child is None:
        return
    _child.start()
    out = os.path.join(os.environ[ENV_OUT], f"child-{os.getpid()}.json")
    atexit.register(_child.write, out)


def main_process_tracer() -> Tracer | None:
    """The pytest process itself: replace the child tracer sitecustomize started with a per-test one."""
    if _child is not None:
        _child.stop()
        _child.cancelled = True
    tracer = from_env()
    if tracer:
        tracer.start()
    return tracer
