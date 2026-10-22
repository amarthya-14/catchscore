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
