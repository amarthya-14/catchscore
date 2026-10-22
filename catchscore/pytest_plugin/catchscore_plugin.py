"""pytest plugin, loaded with `-p catchscore_plugin`. Three modes, chosen by environment variables:

- CATCHSCORE_TRACE_FILES/OUT: record which lines of the watched files each test runs.
- CATCHSCORE_SELECT (a file of node ids): run only those tests.
- CATCHSCORE_SERVE (a directory): collect once, then run the baseline and every mutant in forked
  children, so imports and collection are paid once instead of once per mutant. The protocol, all
  through files in that directory:
    plugin writes baseline.json {"ok", "seconds"} (and trace.json, child-*.json from the tracer)
    catchscore writes batch.json {"timeout", "jobs", "mutants": [{"id", "path", "source", "tests"}]}
    plugin appends one line per mutant to results.jsonl {"id", "status"}; status is "killed",
    "survived", "timeout" or "fallback" (could not apply in memory: run it from disk instead)
"""

import json
import os
import signal
import time

import pytest

import _catchscore_swap as swap
import _catchscore_tracer as tr

_tracer = tr.main_process_tracer()
SERVE = os.environ.get("CATCHSCORE_SERVE")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if _tracer:
        _tracer.current = os.environ[tr.ENV_TEST] = item.nodeid
    yield
    if _tracer:
        _tracer.current = os.environ[tr.ENV_TEST] = ""


def pytest_sessionfinish(session):
    if _tracer and not SERVE:
        _tracer.stop()
        _tracer.write(os.path.join(os.environ[tr.ENV_OUT], "main.json"))


def pytest_collection_modifyitems(config, items):
    path = os.environ.get("CATCHSCORE_SELECT")
    if not path:
        return
    with open(path) as f:
        wanted = set(f.read().splitlines())
    keep = [i for i in items if i.nodeid in wanted]
    if not keep:
        return  # never turn "no matching tests" into an empty, failing run: run everything instead
    config.hook.pytest_deselected(items=[i for i in items if i.nodeid not in wanted])
    items[:] = keep


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session):
    if not SERVE or not hasattr(os, "fork") or session.config.option.collectonly:
        return None
    _serve(session.items, SERVE)
    return True


def _run(items, counts=None) -> bool:
    """Run tests like `pytest -x` would; True if any failed. Tallies passed/skipped tests into `counts`."""
    from _pytest.runner import runtestprotocol

    for i, item in enumerate(items):
        if _tracer:
            _tracer.current = os.environ[tr.ENV_TEST] = item.nodeid
        reports = runtestprotocol(item, nextitem=items[i + 1] if i + 1 < len(items) else None, log=False)
        if any(r.failed for r in reports):
            return True
        if counts is not None:
            counts["skipped" if any(r.skipped for r in reports) else "passed"] += 1
    return False


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _serve(items, d):
    try:
        # Create pytest's temp root once, here: children that each made their own would clean up
        # each other's directories (pytest keeps only the newest few).
        items[0].config._tmp_path_factory.getbasetemp()
    except (AttributeError, IndexError):
        pass
    start = time.monotonic()
    pid = os.fork()
    if pid == 0:  # baseline, traced
        code = 98
        try:
            counts = {"passed": 0, "skipped": 0}
            code = 1 if _run(items, counts) else 0
            _write(os.path.join(d, "counts.json"), counts)
            if _tracer:
                _tracer.stop()
                _tracer.write(os.path.join(d, "trace.json"))
        finally:
            os._exit(code)
    if _tracer:
        _tracer.stop()
    os.environ.pop(tr.ENV_FILES, None)  # mutant runs (and processes they start) are not traced
    _, status = os.waitpid(pid, 0)
    ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    counts_path = os.path.join(d, "counts.json")
    counts = json.load(open(counts_path)) if os.path.exists(counts_path) else None
    _write(os.path.join(d, "baseline.json"), {"ok": ok, "seconds": time.monotonic() - start, "tests": counts})
    if not ok:
        return
    batch_path = os.path.join(d, "batch.json")
    while not os.path.exists(batch_path):
        time.sleep(0.02)
    with open(batch_path) as f:
        batch = json.load(f)
    mutants = batch["mutants"]
    by_id = {i.nodeid: i for i in items}
    sources = {}
    for m in mutants:
        m["real"] = os.path.realpath(m["path"])
        if m["real"] not in sources:
            with open(m["real"]) as f:
                sources[m["real"]] = f.read()
    index = swap.index_functions(set(sources))
    results = open(os.path.join(d, "results.jsonl"), "a", buffering=1)
    running = {}  # pid -> (mutant, started)
    queue = list(mutants)
    while queue or running:
        while queue and len(running) < batch["jobs"]:
            m = queue.pop(0)
            pid = os.fork()
            if pid == 0:
                code = 98
                try:
                    if not swap.apply(m["real"], sources[m["real"]], m["source"], index):
                        code = 99
                    else:
                        code = 1 if _run([by_id[t] for t in m["tests"] if t in by_id] or items) else 0
                finally:
                    os._exit(code)
            running[pid] = (m, time.monotonic())
        pid, status = os.waitpid(-1, os.WNOHANG)
        if pid == 0:
            for p, (m, started) in list(running.items()):
                if time.monotonic() - started > batch["timeout"]:
                    os.kill(p, signal.SIGKILL)
                    os.waitpid(p, 0)
                    del running[p]
                    results.write(json.dumps({"id": m["id"], "status": "timeout"}) + "\n")
            time.sleep(0.005)
            continue
        if pid not in running:
            continue
        m, started = running.pop(pid)
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
        # A crash or an error in catchscore's own machinery is not evidence the tests caught the bug.
        verdict = {0: "survived", 1: "killed"}.get(code, "fallback")
        results.write(json.dumps({"id": m["id"], "status": verdict,
                                  "seconds": round(time.monotonic() - started, 2)}) + "\n")
    results.close()
