"""Run the test suite against each mutant in a scratch copy of the project, never in the user's tree."""

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .mutate import Mutant

IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                                ".mypy_cache", ".catchscore", "*.egg-info")


@dataclass
class Result:
    mutant: Mutant
    killed: bool
    reason: str  # "failed", "timeout" or "survived"


def _pytest(workdir: Path, cmd: list[str], timeout: float, want_output: bool = False):
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return (False, timeout, "timed out") if want_output else (False, timeout)
    took = time.monotonic() - start
    if want_output:
        return proc.returncode == 0, took, proc.stdout[-3000:] + proc.stderr[-1000:]
    return proc.returncode == 0, took


class Runner:
    def __init__(self, repo: Path, pytest_cmd: list[str], max_timeout: float = 120):
        self.repo = repo
        self.cmd = pytest_cmd + ["-x", "-q", "-p", "no:cacheprovider"]
        # Everything up to "pytest" is how to invoke it; the rest selects tests. Verifying a suggested
        # test file swaps the selection for just that file.
        cut = next((i + 1 for i, t in enumerate(pytest_cmd) if t.endswith("pytest")), len(pytest_cmd))
        self.invoke = pytest_cmd[:cut]
        self.only: list[str] | None = None
        self.max_timeout = max_timeout
        self.tmp = Path(tempfile.mkdtemp(prefix="catchscore-"))
        self.work = self.tmp / repo.name
        shutil.copytree(repo, self.work, ignore=IGNORE)

    def baseline(self) -> float:
        """Tests must pass before any bug is injected; returns how long they took."""
        ok, took = _pytest(self.work, self.cmd, self.max_timeout)
        if not ok:
            raise RuntimeError("the test suite fails before any mutation; fix it first (or pass --pytest)")
        self.timeout = min(self.max_timeout, took * 3 + 5)
        return took

    def run(self, mutant: Mutant) -> Result:
        target = self.work / mutant.path
        original = target.read_text()
        target.write_text(mutant.source)
        try:
            passed, took = _pytest(self.work, self._cmd(), self.timeout)
            if took >= self.timeout:
                return Result(mutant, True, "timeout")
            return Result(mutant, not passed, "failed" if not passed else "survived")
        finally:
            target.write_text(original)

    def _cmd(self) -> list[str]:
        if self.only is None:
            return self.cmd
        return self.invoke + self.only + ["-x", "-q", "-p", "no:cacheprovider"]

    def passes(self) -> tuple[bool, str]:
        ok, _, output = _pytest(self.work, self._cmd(), self.timeout, want_output=True)
        return ok, output

    def add_file(self, rel: str, text: str):
        (self.work / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.work / rel).write_text(text)

    def remove_file(self, rel: str):
        (self.work / rel).unlink(missing_ok=True)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
