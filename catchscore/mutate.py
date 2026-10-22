"""Small, well-known bugs ("mutants") injected one at a time into the lines that changed.

Each mutant is a copy of the module with exactly one operator flipped. If the tests still pass with
the bug in place, that bug "survived": nothing in the test suite checks that behaviour.
"""

import ast
import copy
from dataclasses import dataclass

COMPARE_SWAPS = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
BINOP_SWAPS = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div, ast.Mod: ast.Mult,
}
BOOLOP_SWAPS = {ast.And: ast.Or, ast.Or: ast.And}
SYMBOL = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
    ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in",
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%",
    ast.And: "and", ast.Or: "or",
}


@dataclass
class Mutant:
    path: str
    line: int
    description: str
    source: str  # the whole mutated module


def _candidates(tree: ast.AST, lines: set[int]):
    """Yield (node_index, line, description) for every mutable spot on a changed line."""
    for i, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", None)
        if line not in lines:
            continue
        if isinstance(node, ast.Compare):
            for j, op in enumerate(node.ops):
                if type(op) in COMPARE_SWAPS:
                    yield i, j, line, f"`{SYMBOL[type(op)]}` -> `{SYMBOL[COMPARE_SWAPS[type(op)]]}`"
        elif isinstance(node, (ast.BinOp, ast.AugAssign)) and type(node.op) in BINOP_SWAPS:
            yield i, 0, line, f"`{SYMBOL[type(node.op)]}` -> `{SYMBOL[BINOP_SWAPS[type(node.op)]]}`"
        elif isinstance(node, ast.BoolOp):
            yield i, 0, line, f"`{SYMBOL[type(node.op)]}` -> `{SYMBOL[BOOLOP_SWAPS[type(node.op)]]}`"
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            yield i, 0, line, "removed `not`"
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float) and not isinstance(node.value, bool):
            yield i, 0, line, f"`{node.value!r}` -> `{node.value + 1!r}`"
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            yield i, 0, line, f"`{node.value}` -> `{not node.value}`"
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            yield i, 0, line, "return value replaced with `None`"
        elif isinstance(node, (ast.If, ast.While)):
            yield i, 0, line, f"`{type(node).__name__.lower()}` condition negated"


class _Apply(ast.NodeTransformer):
    def __init__(self, index: int, sub: int):
        self.index, self.sub, self.seen = index, sub, -1

    def visit(self, node):
        self.seen += 1
        if self.seen != self.index:
            return super().visit(node)
        if isinstance(node, ast.Compare):
            node.ops[self.sub] = COMPARE_SWAPS[type(node.ops[self.sub])]()
        elif isinstance(node, (ast.BinOp, ast.AugAssign)):
            node.op = BINOP_SWAPS[type(node.op)]()
        elif isinstance(node, ast.BoolOp):
            node.op = BOOLOP_SWAPS[type(node.op)]()
        elif isinstance(node, ast.UnaryOp):
            return node.operand
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            node.value = not node.value
        elif isinstance(node, ast.Constant):
            node.value = node.value + 1
        elif isinstance(node, ast.Return):
            node.value = ast.Constant(None)
        elif isinstance(node, (ast.If, ast.While)):
            node.test = ast.UnaryOp(ast.Not(), node.test)
        return node


def mutants_for(path: str, source: str, changed_lines: set[int]) -> list[Mutant]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    # ast.walk order and NodeTransformer.visit order differ, so map walk indices to visit order.
    walk_order = list(ast.walk(tree))
    visit_index = {id(n): i for i, n in enumerate(_visit_order(tree))}
    out = []
    for i, sub, line, desc in _candidates(tree, changed_lines):
        mutated = _Apply(visit_index[id(walk_order[i])], sub).visit(copy.deepcopy(tree))
        ast.fix_missing_locations(mutated)
        out.append(Mutant(path, line, desc, ast.unparse(mutated)))
    return out


def _visit_order(tree):
    order = []

    class _Collect(ast.NodeVisitor):
        def visit(self, node):
            order.append(node)
            super().visit(node)

    _Collect().visit(tree)
    return order
