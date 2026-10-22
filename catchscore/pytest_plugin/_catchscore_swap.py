"""Put a mutant into an already-imported program by swapping the code of the functions it changes.

Every live function object compiled from the original file is found once (before forking). For a
mutant, the original and mutated modules are compiled and compared code object by code object. If
only function bodies differ, each affected function (and every enclosing function, so closures made
later use the new code) gets the mutated code. Anything else, e.g. a change to a module or class body,
returns False and the caller falls back to running the tests from disk.

Standard library only: this runs inside the project's own Python.
"""

from __future__ import annotations

import ast
import gc
import os
import sys
from inspect import CO_NEWLOCALS
from types import CodeType, FunctionType


def index_functions(paths: set[str]) -> dict[tuple[str, str, int], list[FunctionType]]:
    """(realpath, qualname, first line) -> the live function objects compiled from those files."""
    real: dict[str, str | None] = {}
    index: dict[tuple[str, str, int], list[FunctionType]] = {}
    for obj in gc.get_objects():
        if type(obj) is not FunctionType:
            continue
        code = obj.__code__
        name = code.co_filename
        if name not in real:
            r = os.path.realpath(name)
            real[name] = r if r in paths else None
        if real[name]:
            index.setdefault((real[name], code.co_qualname, code.co_firstlineno), []).append(obj)
    return index


def _walk(code: CodeType, parent: int | None = None, out=None):
    out = [] if out is None else out
    me = len(out)
    out.append((code, parent))
    for c in code.co_consts:
        if isinstance(c, CodeType):
            _walk(c, me, out)
    return out


def _own(code: CodeType):
    consts = tuple((type(c), repr(c)) for c in code.co_consts if not isinstance(c, CodeType))
    return code.co_code, code.co_names, consts


def apply(path: str, original: str, mutated: str, index) -> bool:
    if sys.version_info < (3, 11):  # needs co_qualname
        return False
    try:
        raw = _walk(compile(original, path, "exec", dont_inherit=True))
        norm = _walk(compile(ast.unparse(ast.parse(original)), path, "exec", dont_inherit=True))
        mut = _walk(compile(mutated, path, "exec", dont_inherit=True))
    except SyntaxError:
        return False
    if not len(raw) == len(norm) == len(mut) or any(
            a[0].co_qualname != b[0].co_qualname or a[0].co_qualname != c[0].co_qualname
            for a, b, c in zip(raw, norm, mut)):
        return False
    changed = [i for i in range(len(mut)) if _own(norm[i][0]) != _own(mut[i][0])]
    if not changed:
        return False
    targets = set()
    for i in changed:
        if not mut[i][0].co_flags & CO_NEWLOCALS:  # a module or class body: needs a fresh import
            return False
        j = i
        while j is not None and mut[j][0].co_flags & CO_NEWLOCALS:
            targets.add(j)
            j = mut[j][1]
    swapped = 0
    for j in targets:
        old = raw[j][0]
        for fn in index.get((path, old.co_qualname, old.co_firstlineno), ()):
            fn.__code__ = mut[j][0]
            swapped += 1
    return swapped > 0
