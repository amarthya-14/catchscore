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


def _pytest(workdir: Path, cmd: list[str], timeout: float) -> tuple[bool, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, timeout
    return proc.returncode == 0, time.monotonic() - start


class Runner:
    def __init__(self, repo: Path, pytest_cmd: list[str], max_timeout: float = 120):
        self.repo = repo
        self.cmd = pytest_cmd + ["-x", "-q", "-p", "no:cacheprovider"]
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
            passed, took = _pytest(self.work, self.cmd, self.timeout)
            if took >= self.timeout:
                return Result(mutant, True, "timeout")
            return Result(mutant, not passed, "failed" if not passed else "survived")
        finally:
            target.write_text(original)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
