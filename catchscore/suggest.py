"""Ask Claude for tests that would catch the surviving bugs, then keep only tests that prove it.

A suggested test file is accepted only if it passes on the real code; it is then scored by how many
surviving bugs it now catches. Nothing the model writes is trusted until the tests have run.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .run import Result, Runner

PROMPT = """You are improving a Python test suite. Below is a module and a list of small bugs ("mutants")
that the current tests do NOT catch. Write NEW pytest tests that pass on the code exactly as it is now,
and that would fail if any one of these bugs were introduced.

Rules:
- Test behaviour through the module's public functions; do not modify or repeat existing tests.
- Target the boundaries and branches the bugs touch (e.g. a `>` that could become `>=` needs a test at the boundary).
- Use realistic inputs only. If a bug could only be caught with contrived objects (e.g. a str subclass that
  is falsy, a mock that behaves unlike the real thing), don't test it; list it in a final comment as
  "probably harmless" with one line on why.
- Import the module as `{import_name}`. Use only pytest and the standard library.
- Reply with one ```python code block and nothing else.

### {path}
```python
{source}
```

### Existing tests
```python
{tests}
```

### Bugs the current tests miss
{survivors}
"""

CODE_BLOCK = re.compile(r"```(?:python)?\n(.*?)```", re.S)


@dataclass
class Suggestion:
    path: str            # where the test file was written in the user's repo
    code: str
    caught: list[Result]  # survivors this file now kills
    still_missed: list[Result]
    rejected: str = ""   # why the file was not accepted ("" if accepted)


def _ask_claude(prompt: str, model: str | None, timeout: float) -> str:
    if not shutil.which("claude"):
        raise RuntimeError("--suggest needs the Claude Code CLI (`claude`) on PATH")
    cmd = ["claude", "-p", "--tools", "", "--no-session-persistence", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def suggest(repo: Path, runner: Runner, survivors: list[Result], test_paths: list[str],
            model: str | None = None, timeout: float = 300) -> Suggestion | None:
    by_module: dict[str, list[Result]] = {}
    for r in survivors:
        by_module.setdefault(r.mutant.path, []).append(r)
    # One module per call keeps the prompt focused; start with the module that has the most survivors.
    path, results = max(by_module.items(), key=lambda kv: len(kv[1]))
    source = (repo / path).read_text()
    lines = source.splitlines()
    tests = "\n\n".join(f"# {t}\n{(repo / t).read_text()}" for t in test_paths if (repo / t).exists()) or "(none)"
    prompt = PROMPT.format(
        path=path, source=source, tests=tests,
        import_name=path.removesuffix(".py").replace("/", "."),
        survivors="\n".join(f"- line {r.mutant.line}: `{lines[r.mutant.line - 1].strip()}`  bug: {r.mutant.description}"
                            for r in results))
    reply = _ask_claude(prompt, model, timeout)
    m = CODE_BLOCK.search(reply)
    code = m.group(1) if m else reply
    rel = f"tests/test_catchscore_{Path(path).stem}.py"
    out_dir = repo / ".catchscore"
    out_dir.mkdir(exist_ok=True)
    if not m:
        return _reject(out_dir, rel, code, results, "the reply contained no Python code block")
    runner.add_file(rel, code)
    runner.only = [rel]
    try:
        ok, output = runner.passes()
        if not ok:
            # Wrong about the current behaviour (or broken): never keep it, but show why.
            return _reject(out_dir, rel, code, results, "the suggested tests fail on the current code:\n" + output)
        rerun = [runner.run(r.mutant) for r in results]
    finally:
        runner.only = None
        runner.remove_file(rel)
    caught = [r for r in rerun if r.killed]
    if not caught:
        return _reject(out_dir, rel, code, results, "the suggested tests pass but catch none of the bugs")
    out = out_dir / Path(rel).name
    out.write_text(code)
    return Suggestion(str(out.relative_to(repo)), code, caught, [r for r in rerun if not r.killed])


def _reject(out_dir: Path, rel: str, code: str, results: list[Result], reason: str) -> Suggestion:
    out = out_dir / ("rejected_" + Path(rel).name)
    out.write_text(code)
    (out_dir / "rejected_reason.txt").write_text(reason)
    return Suggestion(str(out.relative_to(out_dir.parent)), code, [], results, reason)
