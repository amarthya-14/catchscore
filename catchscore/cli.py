"""catchscore: would your tests catch a bug in what just changed?

    catchscore                 # uncommitted changes vs HEAD
    catchscore --base main     # everything on this branch
    catchscore --json          # machine-readable, for CI and agent hooks
"""

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

from . import integrity
from .diff import git_diff, is_test_file
from .mutate import mutants_for
from .run import Runner


def main(argv=None):
    p = argparse.ArgumentParser(prog="catchscore", description=__doc__.splitlines()[0])
    p.add_argument("--base", help="git ref to diff against (default: HEAD, i.e. uncommitted changes)")
    p.add_argument("--repo", default=".", help="project root (default: current directory)")
    p.add_argument("--pytest", default=f"{sys.executable} -m pytest",
                   help="command that runs the tests (default: this Python's pytest)")
    p.add_argument("--max-mutants", type=int, default=60, help="cap per run, to bound the time (default: 60)")
    p.add_argument("--min-score", type=float, help="exit 1 if the catch score is below this percentage")
    p.add_argument("--json", action="store_true", help="print a JSON report")
    args = p.parse_args(argv)

    repo = Path(args.repo).resolve()
    files = git_diff(repo, args.base)
    findings = integrity.check(files)

    mutants = []
    for f in files:
        if f.status == "removed" or not f.path.endswith(".py") or is_test_file(f.path):
            continue
        source = (repo / f.path).read_text()
        mutants += mutants_for(f.path, source, f.added_lines)
    mutants = mutants[: args.max_mutants]

    results = []
    if mutants:
        runner = Runner(repo, shlex.split(args.pytest))
        try:
            runner.baseline()
            for i, m in enumerate(mutants, 1):
                if not args.json and sys.stderr.isatty():
                    print(f"\r  testing injected bug {i}/{len(mutants)}...", end="", file=sys.stderr, flush=True)
                results.append(runner.run(m))
        finally:
            runner.close()
        if not args.json and sys.stderr.isatty():
            print("\r" + " " * 50 + "\r", end="", file=sys.stderr)

    results.sort(key=lambda r: (r.mutant.path, r.mutant.line))
    caught = sum(r.killed for r in results)
    score = 100 * caught / len(results) if results else None
    if args.json:
        print(json.dumps({
            "score": score, "caught": caught, "injected": len(results),
            "survivors": [{"path": r.mutant.path, "line": r.mutant.line, "mutation": r.mutant.description}
                          for r in results if not r.killed],
            "integrity": [asdict(f) for f in findings],
        }, indent=2))
    else:
        print(render(results, findings, score))
    if args.min_score is not None and score is not None and score < args.min_score:
        sys.exit(1)


def render(results, findings, score) -> str:
    out = ["catchscore: would your tests catch a bug in what just changed?", ""]
    if not results:
        out.append("No changed Python source lines to test.")
    else:
        caught = sum(r.killed for r in results)
        out.append(f"Injected {len(results)} small bugs into the changed lines. Tests caught {caught} ({score:.0f}%).")
        survivors = [r for r in results if not r.killed]
        if survivors:
            out += ["", "Your tests would NOT notice these bugs:"]
            out += [f"  {r.mutant.path}:{r.mutant.line}  {r.mutant.description}" for r in survivors]
    if findings:
        out += ["", "Test changes worth a second look:"]
        out += [f"  {f.path}: {f.kind}: {f.detail}" for f in findings]
    return "\n".join(out)


if __name__ == "__main__":
    main()
