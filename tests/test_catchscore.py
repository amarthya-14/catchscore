import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from catchscore import integrity
from catchscore.diff import FileDiff, is_test_file, parse
from catchscore.mutate import mutants_for

ROOT = Path(__file__).resolve().parents[1]

DIFF = """\
diff --git a/shop.py b/shop.py
--- a/shop.py
+++ b/shop.py
@@ -3,0 +4,3 @@ def subtotal(prices):
+def discount(total):
+    return total * 0.1
+
diff --git a/old_test.py b/old_test.py
--- a/tests/test_old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def test_old():
-    assert True
"""


def test_parse_records_added_line_numbers_and_removed_files():
    files = {f.path: f for f in parse(DIFF)}
    assert files["shop.py"].status == "modified"
    assert files["shop.py"].added_lines == {4, 5, 6}
    assert files["tests/test_old.py"].status == "removed"


@pytest.mark.parametrize("path, expected", [
    ("tests/test_shop.py", True), ("shop_test.py", True), ("src/shop.py", False), ("docs/test.md", False),
])
def test_is_test_file(path, expected):
    assert is_test_file(path) is expected


SOURCE = """\
def price(total, vip):
    if total > 100 and vip:
        return total - 10
    return total
"""


def test_mutants_only_touch_changed_lines():
    assert {m.line for m in mutants_for("p.py", SOURCE, {3})} == {3}
    assert mutants_for("p.py", SOURCE, set()) == []


def test_each_mutant_changes_exactly_one_thing_and_still_parses():
    mutants = mutants_for("p.py", SOURCE, {2})
    descriptions = {m.description for m in mutants}
    assert {"`>` -> `>=`", "`and` -> `or`", "`100` -> `101`", "`if` condition negated"} <= descriptions
    for m in mutants:
        ast.parse(m.source)
        assert m.source != ast.unparse(ast.parse(SOURCE))


def test_mutated_code_actually_behaves_differently():
    (boundary,) = [m for m in mutants_for("p.py", SOURCE, {2}) if m.description == "`>` -> `>=`"]
    original, mutated = {}, {}
    exec(SOURCE, original)
    exec(boundary.source, mutated)
    assert original["price"](100, True) == 100
    assert mutated["price"](100, True) == 90


def test_syntax_errors_produce_no_mutants():
    assert mutants_for("broken.py", "def (:", {1}) == []


def _test_diff(patch, status="modified"):
    return [FileDiff("tests/test_x.py", status, set(), patch)]


def test_integrity_flags_deleted_and_hollow_tests():
    patch = (
        "-def test_limit():\n"
        "-    assert limit(5) == 5\n"
        "+def test_runs():\n"
        "+    limit(5)\n"
        "+def test_returns_something():\n"
        "+    assert limit(5) is not None\n"
    )
    kinds = {(f.kind, f.detail) for f in integrity.check(_test_diff(patch))}
    assert ("test deleted", "test_limit") in kinds
    assert ("new test checks nothing", "test_runs") in kinds
    assert ("new test only checks that something came back", "test_returns_something") in kinds


def test_integrity_ignores_moved_tests_and_platform_skips():
    files = [
        FileDiff("tests/test_a.py", "modified", set(), "-def test_moved():\n-    assert f() == 1\n"),
        FileDiff("tests/test_b.py", "modified", set(),
                 "+@pytest.mark.skipif(sys.platform == 'win32', reason='posix only')\n"
                 "+def test_moved():\n+    assert f() == 1\n"),
    ]
    assert integrity.check(files) == []


def test_integrity_flags_changed_expectations_and_unconditional_skips():
    patch = "-    assert total(cart) == 30\n+    assert total(cart) == 35\n+@pytest.mark.skip\n"
    kinds = {f.kind for f in integrity.check(_test_diff(patch))}
    assert kinds == {"expected value changed", "test skipped"}


def test_end_to_end_on_the_demo_project(tmp_path):
    subprocess.run(["bash", str(ROOT / "examples" / "make_demo.sh"), str(tmp_path / "shop")],
                   check=True, capture_output=True)
    out = subprocess.run([sys.executable, "-m", "catchscore.cli", "--json", "--repo", str(tmp_path / "shop")],
                         check=True, capture_output=True, text=True).stdout
    report = json.loads(out)
    assert report["injected"] == 16
    assert report["caught"] == 2
    assert any(s["mutation"] == "`>` -> `>=`" for s in report["survivors"])
    assert {f["detail"] for f in report["integrity"]} == {"test_discount_runs", "test_discount_returns_a_number"}


GOOD_TESTS = '''```python
import pytest
import shop


def test_save10_above_and_at_boundary():
    assert shop.discount(200, "SAVE10") == pytest.approx(20)
    assert shop.discount(100, "SAVE10") == 0
    assert shop.discount(101, "SAVE10") == pytest.approx(10.1)


def test_half_is_capped():
    assert shop.discount(30, "HALF") == pytest.approx(15)
    assert shop.discount(60, "HALF") == 25
    assert shop.discount(50, "HALF") == 25


def test_unknown_code():
    assert shop.discount(10, "BOGUS") == 0
```'''

WRONG_TESTS = '```python\nimport shop\n\n\ndef test_wrong():\n    assert shop.discount(200, "SAVE10") == 999\n```'


@pytest.mark.parametrize("reply, accepted", [(GOOD_TESTS, True), (WRONG_TESTS, False)])
def test_suggestions_are_kept_only_if_they_pass_and_catch_bugs(tmp_path, monkeypatch, reply, accepted):
    from catchscore import suggest as suggest_module
    from catchscore.diff import git_diff
    from catchscore.run import Runner

    repo = tmp_path / "shop"
    subprocess.run(["bash", str(ROOT / "examples" / "make_demo.sh"), str(repo)], check=True, capture_output=True)
    monkeypatch.setattr(suggest_module, "_ask_claude", lambda *a, **k: reply)
    files = git_diff(repo, None)
    mutants = [m for f in files if f.path == "shop.py" for m in mutants_for(f.path, (repo / f.path).read_text(), f.added_lines)]
    # An explicit test path in the command: the suggested file must still be the one that gets verified.
    runner = Runner(repo, [sys.executable, "-m", "pytest", "tests/test_shop.py"])
    try:
        runner.baseline()
        survivors = [r for r in (runner.run(m) for m in mutants) if not r.killed]
        result = suggest_module.suggest(repo, runner, survivors, ["tests/test_shop.py"])
    finally:
        runner.close()
    if accepted:
        assert not result.rejected and len(result.caught) == len(survivors)
        assert (repo / result.path).exists()
    else:
        assert result.rejected.startswith("the suggested tests fail on the current code")
        assert (repo / ".catchscore" / "rejected_reason.txt").exists()


def test_parallel_jobs_give_the_same_results(tmp_path):
    subprocess.run(["bash", str(ROOT / "examples" / "make_demo.sh"), str(tmp_path / "shop")],
                   check=True, capture_output=True)
    reports = [json.loads(subprocess.run(
        [sys.executable, "-m", "catchscore.cli", "--json", "--jobs", jobs, "--repo", str(tmp_path / "shop")],
        check=True, capture_output=True, text=True).stdout) for jobs in ("1", "4")]
    assert reports[0]["survivors"] == reports[1]["survivors"]


def test_same_size_mutants_are_not_hidden_by_python_bytecode_cache(tmp_path):
    """`/ 2` -> `* 2` keeps the file size and is written within the same second as the baseline run.
    If Python reused its cached bytecode, the old code would run and these bugs would wrongly survive."""
    repo = tmp_path / "calc"
    (repo / "tests").mkdir(parents=True)
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q"], check=True)
    (repo / "calc.py").write_text("def f(x):\n    return 4\n")
    (repo / "tests" / "test_calc.py").write_text("from calc import f\n\n\ndef test_f():\n    assert f(4) == 4\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    # Mutants run in this order: two harmless ones (`+`->`-`, `*`->`/`), then two real ones (1->2, 0->1),
    # all the same size. A stale cache would run a harmless mutant's code for a real one, hiding it.
    (repo / "calc.py").write_text("def f(x):\n    return x * 1 + 0\n")
    report = json.loads(subprocess.run([sys.executable, "-m", "catchscore.cli", "--json", "--repo", str(repo)],
                                       check=True, capture_output=True, text=True).stdout)
    assert report["injected"] == 5 and report["caught"] == 3, report["survivors"]
    assert {s["mutation"] for s in report["survivors"]} == {"`+` -> `-`", "`*` -> `/`"}


def _project(tmp_path, before: dict[str, str], after: dict[str, str]) -> Path:
    """A git repo with `before` committed and `after` written on top, uncommitted."""
    repo = tmp_path / "proj"
    git = ["git", "-C", str(repo)]
    for files in (before, after):
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        if files is before:
            subprocess.run(git + ["init", "-q"], check=True)
            subprocess.run(git + ["add", "-A"], check=True)
            subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    return repo


def _score(repo, *flags):
    out = subprocess.run([sys.executable, "-m", "catchscore.cli", "--json", "--repo", str(repo), *flags],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_fast_path_matches_a_fresh_process_per_bug(tmp_path):
    repo = tmp_path / "shop"
    subprocess.run(["bash", str(ROOT / "examples" / "make_demo.sh"), str(repo)], check=True, capture_output=True)
    fast, slow = _score(repo), _score(repo, "--no-select")
    assert [(s["line"], s["mutation"]) for s in fast["survivors"]] == [(s["line"], s["mutation"]) for s in slow["survivors"]]
    if hasattr(__import__("os"), "fork"):
        assert fast["how_tested"]["in_memory"] > 0
    # discount() returns before its last line for every input the agent's tests use
    assert {(s["line"], s["reason"]) for s in fast["survivors"] if s["reason"] == "not run by any test"} == {
        (16, "not run by any test")}


BEFORE = {"tests/test_calc.py": "def test_nothing():\n    pass\n", "calc.py": "\n"}


def test_bugs_in_code_a_test_runs_in_another_process_are_still_caught(tmp_path):
    # Swapping code in memory can't reach a subprocess, so these bugs must be run from disk. The test
    # also imports calc, so an in-memory swap would find the function and wrongly look like it worked.
    after = {
        "calc.py": "import sys\n\n\ndef double(x):\n    return x * 2\n\n\nif __name__ == '__main__':\n"
                   "    print(double(int(sys.argv[1])))\n",
        "tests/test_calc.py": "import subprocess, sys\n\nimport calc\n\n\ndef test_cli():\n"
                              "    assert calc.double is not None\n"
                              "    out = subprocess.run([sys.executable, 'calc.py', '4'], capture_output=True, text=True)\n"
                              "    assert out.stdout.strip() == '8'\n",
    }
    report = _score(_project(tmp_path, BEFORE, after))
    assert not [s for s in report["survivors"] if s["line"] == 5], report


def test_bugs_in_code_run_at_import_time_are_still_caught(tmp_path):
    # RATE is computed once on import; changing rate() in memory afterwards would change nothing.
    after = {
        "calc.py": "def rate():\n    return 3\n\n\nRATE = rate()\n\n\ndef charge(x):\n    return x * RATE\n",
        "tests/test_calc.py": "from calc import charge\n\n\ndef test_charge():\n    assert charge(2) == 6\n",
    }
    report = _score(_project(tmp_path, BEFORE, after))
    assert report["caught"] == report["injected"], report["survivors"]


def test_closures_made_during_a_test_get_the_bug(tmp_path):
    # over_ten exists before the fork, so swapping only check() would "work" but miss the closure the
    # test creates itself: make() must get the new code too.
    after = {
        "calc.py": "def make(limit):\n    def check(x):\n        return x > limit\n    return check\n\n\n"
                   "over_ten = make(10)\n",
        "tests/test_calc.py": "from calc import make\n\n\ndef test_make():\n"
                              "    assert make(1)(2) and not make(1)(1)\n",
    }
    report = _score(_project(tmp_path, BEFORE, after))
    # Only `make(10)` -> `make(11)` survives, correctly: no test uses over_ten.
    assert [s["line"] for s in report["survivors"]] == [7], report["survivors"]


def test_swap_replaces_function_code_and_refuses_module_level_changes():
    sys.path.insert(0, str(ROOT / "catchscore" / "pytest_plugin"))
    import _catchscore_swap as swap

    src = "def f(x):\n    return x + 1\n\nK = 1\n"
    ns = {}
    path = "/virtual/calc.py"
    exec(compile(src, path, "exec"), ns)
    index = {(path, "f", 1): [ns["f"]]}
    assert swap.apply(path, src, "def f(x):\n    return x - 1\nK = 1\n", index)
    assert ns["f"](1) == 0
    assert not swap.apply(path, src, "def f(x):\n    return x + 1\nK = 2\n", index)
