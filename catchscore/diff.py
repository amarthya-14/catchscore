"""Which lines changed? Parses `git diff` into per-file sets of changed line numbers and raw patches."""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileDiff:
    path: str
    status: str  # "added", "modified" or "removed"
    added_lines: set[int] = field(default_factory=set)  # line numbers in the new file
    patch: str = ""


def is_test_file(path: str) -> bool:
    name = Path(path).name
    parts = Path(path).parts
    return path.endswith(".py") and (
        name.startswith("test_") or name.endswith("_test.py") or "tests" in parts or "test" in parts
    )


def parse(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    new_line = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            cur = None
            continue
        if line.startswith("--- "):
            old_path = line[4:]
            continue
        if line.startswith("+++ "):
            new_path = line[4:]
            if new_path == "/dev/null":
                cur = FileDiff(old_path.removeprefix("a/"), "removed")
            else:
                status = "added" if old_path == "/dev/null" else "modified"
                cur = FileDiff(new_path.removeprefix("b/"), status)
            files.append(cur)
            continue
        if cur is None:
            continue
        m = HUNK.match(line)
        if m:
            new_line = int(m.group(1))
            cur.patch += line + "\n"
            continue
        if line.startswith(("+", "-", " ")) or line == "":
            cur.patch += line + "\n"
        if line.startswith("+"):
            cur.added_lines.add(new_line)
            new_line += 1
        elif line.startswith(" ") or line == "":
            new_line += 1
    return files


def git_diff(repo: Path, base: str | None) -> list[FileDiff]:
    """Changes in the working tree against `base` (default: HEAD, i.e. uncommitted work), untracked files included."""
    # --relative: paths relative to `repo`, so a subdirectory of a monorepo (e.g. backend/) works as the root.
    args = ["git", "-C", str(repo), "diff", "--relative", "--unified=0", "--no-color", base or "HEAD"]
    diff = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    files = parse(diff)
    # `git diff` ignores untracked files, but an agent's new modules and tests often are untracked.
    untracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout.split()
    for path in untracked:
        text = (repo / path).read_text(errors="replace")
        lines = text.splitlines()
        files.append(FileDiff(path, "added", set(range(1, len(lines) + 1)),
                              "".join(f"+{l}\n" for l in lines)))
    return files
