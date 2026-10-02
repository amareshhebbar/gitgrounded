import ast
import operator
from typing import Any

from gitgrounded.errors import ConfigError

_CMP = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class _Missing:
    def __repr__(self) -> str:
        return "missing"


MISSING = _Missing()


def _eval(node: ast.AST, ns: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, ns)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ("true", "True"):
            return True
        if node.id in ("false", "False"):
            return False
        return ns.get(node.id, MISSING)
    if isinstance(node, ast.Attribute):
        base = _eval(node.value, ns)
        if isinstance(base, dict):
            return base.get(node.attr, MISSING)
        return MISSING
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, ns)
        if isinstance(node.op, ast.USub):
            return MISSING if v is MISSING or v is None else -v
        if isinstance(node.op, ast.Not):
            return not v if v is not MISSING else MISSING
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left, ns), _eval(node.right, ns)
        if a in (MISSING, None) or b in (MISSING, None):
            return MISSING
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, ns) for v in node.values]
        vals = [False if v is MISSING else bool(v) for v in vals]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ns)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, ns)
            if left in (MISSING, None) or right in (MISSING, None):
                return False
            if type(op) not in _CMP or not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    raise ConfigError(f"unsupported gate expression element: {ast.dump(node)[:80]}")


def evaluate_gate(expr: str, ns: dict[str, Any]) -> bool:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ConfigError(f"invalid gate expression '{expr}': {e}") from e
    result = _eval(tree, ns)
    return False if result is MISSING else bool(result)


def decide(fail_if: list[str], warn_if: list[str], ns: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    trace = []
    verdict = "PASS"
    for expr in fail_if:
        hit = evaluate_gate(expr, ns)
        trace.append({"level": "fail", "expr": expr, "triggered": hit})
        if hit:
            verdict = "FAIL"
    for expr in warn_if:
        hit = evaluate_gate(expr, ns)
        trace.append({"level": "warn", "expr": expr, "triggered": hit})
        if hit and verdict == "PASS":
            verdict = "WARN"
    return verdict, trace
