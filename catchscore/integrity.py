"""Did the change weaken the tests? Static checks on test-file diffs.

These only raise questions for a human; plenty of test deletions are legitimate (the feature was
removed, the test moved). Each finding carries the evidence so it can be judged in seconds.
"""

import re
from dataclasses import dataclass

from .diff import FileDiff, is_test_file

TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)")
ASSERTISH = re.compile(r"\bassert\b|pytest\.(raises|fail|warns)|self\.assert\w+\(|\.assert_\w+\(|assert_\w+\(|"
                       r"raise\s+AssertionError|self\.fail\(")
HELPER_CHECK = re.compile(r"\b(check|verify|expect|validate)_?\w*\(|snapshot")
# Platform, hardware and optional-dependency skips are routine; an unconditional skip is not.
UNCONDITIONAL_SKIP = re.compile(
    r"@pytest\.mark\.(skip|xfail)\s*(\(\s*(reason\s*=\s*)?[\"'][^\"']*[\"']\s*\))?\s*$|@unittest\.skip\(|pytest\.skip\(")
ASSERT_EQ = re.compile(r"^\s*assert\s+(.+?)\s*==\s*(.+?)\s*$")
TAUTOLOGY = re.compile(r"^\s*assert\s+(True|1|not\s+False)\s*(#.*)?$")
# Assertions that pass for almost any output: "something came back", "it has the right type".
WEAK = re.compile(r"^\s*assert\s+(.+\s+is\s+not\s+None|isinstance\(.+\)|len\(.+\)\s*>=\s*0|.+\s+is\s+not\s+False)\s*(#.*)?$")


@dataclass
class Finding:
    path: str
    kind: str
    detail: str


def _lines(patch: str):
    added = [l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in patch.splitlines() if l.startswith("-") and not l.startswith("---")]
    return added, removed


def _new_tests(added: list[str]) -> dict[str, list[str]]:
    bodies, cur = {}, None
    for line in added:
        m = TEST_DEF.match(line)
        if m:
            cur = m.group(1)
            bodies[cur] = []
        elif cur is not None:
            if line.strip() and not line.startswith((" ", "\t", ")")):
                cur = None
            else:
                bodies[cur].append(line)
    return bodies


def check(files: list[FileDiff]) -> list[Finding]:
    tests = [f for f in files if is_test_file(f.path)]
    findings: list[Finding] = []
    added_anywhere = {m.group(1) for f in tests for l in _lines(f.patch)[0] if (m := TEST_DEF.match(l))}
    for f in tests:
        if f.status == "removed":
            findings.append(Finding(f.path, "test file deleted", f.path))
            continue
        added, removed = _lines(f.patch)
        for name in sorted({m.group(1) for l in removed if (m := TEST_DEF.match(l))} - added_anywhere):
            findings.append(Finding(f.path, "test deleted", name))
        for l in added:
            if UNCONDITIONAL_SKIP.search(l):
                findings.append(Finding(f.path, "test skipped", l.strip()))
            if TAUTOLOGY.match(l):
                findings.append(Finding(f.path, "assertion can never fail", l.strip()))
        old = {m.group(1): m.group(2) for l in removed if (m := ASSERT_EQ.match(l))}
        for l in added:
            m = ASSERT_EQ.match(l)
            if m and m.group(1) in old and old[m.group(1)] != m.group(2):
                findings.append(Finding(f.path, "expected value changed",
                                        f"{m.group(1)}: {old[m.group(1)]} -> {m.group(2)}"))
        for name, body in _new_tests(added).items():
            checks = [l for l in body if ASSERTISH.search(l) or HELPER_CHECK.search(l)]
            if body and not checks:
                findings.append(Finding(f.path, "new test checks nothing", name))
            elif checks and all(WEAK.match(l) for l in checks):
                findings.append(Finding(f.path, "new test only checks that something came back", name))
    # Counted across all test files together, so moving tests between files isn't a loss.
    lost = sum(sum(bool(ASSERTISH.search(l)) for l in _lines(f.patch)[1]) -
               sum(bool(ASSERTISH.search(l)) for l in _lines(f.patch)[0]) for f in tests if f.status != "removed")
    if lost > 0:
        findings.append(Finding("(all test files)", "assertions removed",
                                f"{lost} more assertion line(s) removed than added"))
    return findings
