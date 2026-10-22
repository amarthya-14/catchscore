"""Run the test suite against each mutant in a scratch copy of the project, never in the user's tree."""

import ast
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
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


# Python reuses cached bytecode when a source file's size and mtime (whole seconds) look unchanged. A
# mutant like `/ 2` -> `/ 3` keeps the size, and is written within the same second, so the tests would
# silently run the previous code and the bug would wrongly "survive". Never write or read the cache.
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
PLUGIN = Path(__file__).parent / "pytest_plugin"


def _import_roots(work: Path, paths) -> list[str]:
    """Directories (relative to `work`) from which the mutated files are imported: above the topmost
    package of each file, plus `src` if there is one."""
    roots = []
    for p in paths:
        d = (work / p).parent
        while d != work and (d / "__init__.py").exists():
            d = d.parent
        roots.append(os.path.relpath(d, work))
    if (work / "src").is_dir():
        roots.append("src")
    return list(dict.fromkeys(roots))


def _pytest(workdir: Path, cmd: list[str], timeout: float, want_output: bool = False, env=None):
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout, env=env)
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
        # Filled by a traced baseline: which tests run each changed line, and which lines run on import.
        self.tests_on: dict[tuple[str, int], set[str]] | None = None
        self.import_lines: set[tuple[str, int]] = set()
        self.subprocess_lines: set[tuple[str, int]] = set()  # run by a process a test started
        self._spans: dict[str, dict[int, range]] = {}
        self.stats = {"in_memory": 0, "fresh_process": 0, "not_run": 0}  # how each mutant was tested
        self.roots: list[str] = []
        self.max_timeout = max_timeout
        self.tmp = Path(tempfile.mkdtemp(prefix="catchscore-"))
        self.work = self.tmp / repo.name
        shutil.copytree(repo, self.work, ignore=IGNORE, symlinks=True)

    def _env(self, workdir: Path, plugin: bool = False, **extra: str) -> dict[str, str]:
        # The copy's own source roots go first on the path. Otherwise an editable install of the
        # project, which points at the original folder, would import that instead of the mutated copy.
        paths = ([str(PLUGIN)] if plugin else []) + [str(workdir / r) for r in self.roots]
        if ENV.get("PYTHONPATH"):
            paths.append(ENV["PYTHONPATH"])
        return {**ENV, "PYTHONPATH": os.pathsep.join(paths), **extra}

    def baseline(self, paths: list[str] = (), trace: bool = True) -> float:
        """Tests must pass before any bug is injected; returns how long they took.

        `paths` are the files that will be mutated. With `trace`, also records which tests run each of
        their lines, so each mutant only needs the tests that can reach it.
        """
        ok = False
        self.roots = _import_roots(self.work, paths)
        if paths and trace:
            ok, took = self._traced_baseline(paths)
        if not ok:
            self.tests_on = None
            ok, took, output = _pytest(self.work, self.cmd, self.max_timeout, want_output=True, env=self._env(self.work))
        if not ok:
            raise RuntimeError("the test suite fails before any mutation; fix it first (or pass --pytest).\n"
                               "Last lines of pytest's output:\n" + output[-2500:])
        self.timeout = min(self.max_timeout, took * 3 + 5)
        return took

    def _traced_baseline(self, paths: list[str]) -> tuple[bool, float]:
        out = Path(tempfile.mkdtemp(prefix="trace-", dir=self.tmp))
        files = {os.path.realpath(self.work / p): p for p in paths}
        env = self._env(self.work, plugin=True, CATCHSCORE_TRACE_FILES=json.dumps(files), CATCHSCORE_TRACE_OUT=str(out))
        ok, took = _pytest(self.work, self.cmd + ["-p", "catchscore_plugin"], self.max_timeout, env=env)
        if not ok or not (out / "main.json").exists():
            return False, took  # e.g. another tracer (pytest-cov) took over: fall back to running every test
        self._load_trace(out)
        return True, took

    def _load_trace(self, out: Path):
        self.tests_on = {}
        for f in [*out.glob("main.json"), *out.glob("trace.json"), *out.glob("child-*.json")]:
            child = f.name.startswith("child-")
            for test, hits in json.loads(f.read_text()).items():
                for path, line in hits:
                    if child:
                        self.subprocess_lines.add((path, line))
                    if test:
                        self.tests_on.setdefault((path, line), set()).add(test)
                    else:
                        self.import_lines.add((path, line))

    def score(self, mutants: list[Mutant], jobs: int = 1, progress=None) -> list[Result]:
        """Baseline plus every mutant. Where it can, this collects the tests once and runs each mutant
        in a forked child with the mutated functions swapped in memory, so imports are paid once; the
        rest run from disk, one test process each (`run`)."""
        served = self._serve(mutants, jobs, progress)
        if served is None:
            self.baseline(sorted({m.path for m in mutants}))
            results = self.run_many(mutants, jobs, progress)
            self.stats["not_run"] = sum(r.reason == "not run by any test" for r in results)
            self.stats["fresh_process"] = len(results) - self.stats["not_run"]
            return results
        results, rest = served
        self.stats["not_run"] = sum(r.reason == "not run by any test" for r in results.values())
        self.stats["in_memory"] = len(results) - self.stats["not_run"]
        self.stats["fresh_process"] = len(rest)
        if rest:
            done = len(results)
            more = self.run_many(rest, jobs, progress and (lambda i, n: progress(done + i, len(mutants))))
            results.update(zip(map(id, rest), more))
        return [results[id(m)] for m in mutants]

    def _serve(self, mutants, jobs, progress):
        if not hasattr(os, "fork"):
            return None
        out = Path(tempfile.mkdtemp(prefix="serve-", dir=self.tmp))
        files = {os.path.realpath(self.work / p): p for p in {m.path for m in mutants}}
        self.roots = _import_roots(self.work, {m.path for m in mutants})
        env = self._env(self.work, plugin=True, CATCHSCORE_TRACE_FILES=json.dumps(files), CATCHSCORE_TRACE_OUT=str(out),
                        CATCHSCORE_SERVE=str(out), OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
        if sys.platform == "darwin" and not any(k.lower().endswith("_proxy") for k in env):
            # After fork(), macOS's system proxy lookup (urllib, used by httpx/requests) segfaults.
            # With a proxy variable set, Python never asks the system.
            env["no_proxy"] = "*"
        with open(out / "pytest.log", "w") as log:
            proc = subprocess.Popen(self.cmd + ["-p", "catchscore_plugin"], cwd=self.work, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
        try:
            baseline = _wait_for(out / "baseline.json", proc, self.max_timeout * 2)
            if not baseline or not baseline["ok"]:
                return None  # not supported here, or the tests need a fresh process: do it the slow way
            self.timeout = min(self.max_timeout, baseline["seconds"] * 3 + 5)
            self._load_trace(out)
            results, forked, rest = {}, [], []
            for m in mutants:
                tests = self.tests_for(m)
                if tests == []:
                    results[id(m)] = Result(m, False, "not run by any test")
                elif tests is None or any(k in self.subprocess_lines for k in self._lines(m)):
                    rest.append(m)  # needs a fresh import, or a test runs this code in another process
                else:
                    forked.append((m, tests))
            batch = [{"id": i, "path": m.path, "source": m.source, "tests": t} for i, (m, t) in enumerate(forked)]
            tmp = out / "batch.json.tmp"
            tmp.write_text(json.dumps({"timeout": self.timeout, "jobs": max(1, jobs), "mutants": batch}))
            tmp.replace(out / "batch.json")
            done: dict[int, str] = {}
            while True:
                exited = proc.poll() is not None
                if (out / "results.jsonl").exists():
                    for line in (out / "results.jsonl").read_text().splitlines():
                        r = json.loads(line)
                        done[r["id"]] = r["status"]
                if progress:
                    progress(len(results) + len(done), len(mutants))
                if exited:
                    break
                time.sleep(0.05)
            for i, (m, _) in enumerate(forked):
                status = done.get(i, "fallback")  # also covers a server that died part-way
                if status == "fallback":
                    rest.append(m)
                else:
                    results[id(m)] = Result(m, status != "survived", "failed" if status == "killed" else status)
            return results, rest
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def _lines(self, mutant: Mutant) -> list[tuple[str, int]]:
        if mutant.path not in self._spans:
            self._spans[mutant.path] = _statement_spans((self.work / mutant.path).read_text())
        return [(mutant.path, n) for n in self._spans[mutant.path].get(mutant.line, (mutant.line,))]

    def tests_for(self, mutant: Mutant) -> list[str] | None:
        """The tests that run the mutated statement: [] if none does, None if all must run."""
        if self.tests_on is None or self.only is not None:
            return None
        lines = self._lines(mutant)
        if any(key in self.import_lines for key in lines):
            return None
        return sorted(set().union(*(self.tests_on.get(key, ()) for key in lines)))

    def run_many(self, mutants: list[Mutant], jobs: int = 1, progress=None) -> list[Result]:
        """Test every mutant; with jobs > 1, each worker gets its own copy of the project."""
        if jobs <= 1:
            out = []
            for i, m in enumerate(mutants, 1):
                out.append(self.run(m))
                if progress:
                    progress(i, len(mutants))
            return out
        free: queue.Queue[Path] = queue.Queue()
        free.put(self.work)
        for k in range(1, min(jobs, len(mutants))):
            copy = self.tmp / f"{self.work.name}-{k}"
            shutil.copytree(self.work, copy, ignore=IGNORE, symlinks=True)
            free.put(copy)
        done = 0

        def task(m: Mutant) -> Result:
            nonlocal done
            workdir = free.get()
            try:
                return self.run(m, workdir)
            finally:
                free.put(workdir)
                done += 1
                if progress:
                    progress(done, len(mutants))

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            return list(pool.map(task, mutants))

    def run(self, mutant: Mutant, workdir: Path | None = None) -> Result:
        workdir = workdir or self.work
        cmd, env = self._cmd(), self._env(workdir)
        tests = self.tests_for(mutant)
        if tests == []:
            return Result(mutant, False, "not run by any test")
        if tests:
            fd, select = tempfile.mkstemp(suffix=".txt", dir=self.tmp)
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(tests))
            cmd, env = cmd + ["-p", "catchscore_plugin"], self._env(workdir, plugin=True, CATCHSCORE_SELECT=select)
        target = workdir / mutant.path
        original = target.read_text()
        target.write_text(mutant.source)
        try:
            passed, took = _pytest(workdir, cmd, self.timeout, env=env)
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
        ok, _, output = _pytest(self.work, self._cmd(), self.timeout, want_output=True, env=self._env(self.work))
        return ok, output

    def add_file(self, rel: str, text: str):
        (self.work / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.work / rel).write_text(text)

    def remove_file(self, rel: str):
        (self.work / rel).unlink(missing_ok=True)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _wait_for(path: Path, proc: subprocess.Popen, timeout: float):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists():
            return json.loads(path.read_text())
        if proc.poll() is not None:
            return json.loads(path.read_text()) if path.exists() else None
        time.sleep(0.05)
    return None


def _statement_spans(source: str) -> dict[int, range]:
    """Map each line to the lines of the innermost statement on it (for a compound statement, just its
    header, e.g. a multi-line `if` condition). A mutant's tests are those that run any of these lines."""
    spans: dict[int, range] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return spans
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        body = getattr(node, "body", None)
        end = body[0].lineno - 1 if isinstance(body, list) and body and isinstance(body[0], ast.stmt) else node.end_lineno
        span = range(node.lineno, max(node.lineno, end) + 1)
        for n in span:
            if n not in spans or len(span) < len(spans[n]):
                spans[n] = span
    return spans
