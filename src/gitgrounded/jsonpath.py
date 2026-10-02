import re
from typing import Any

TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+|\*)\]|\[['\"]([^'\"]+)['\"]\]")


def _tokens(path: str) -> list[str | int]:
    path = path.strip()
    if path in ("$", ""):
        return []
    if not path.startswith("$"):
        path = "$." + path
    rest = path[1:]
    out: list[str | int] = []
    pos = 0
    while pos < len(rest):
        m = TOKEN.match(rest, pos)
        if not m:
            raise ValueError(f"unsupported JSONPath: {path}")
        if m.group(1) is not None:
            out.append(m.group(1))
        elif m.group(2) is not None:
            out.append("*" if m.group(2) == "*" else int(m.group(2)))
        else:
            out.append(m.group(3))
        pos = m.end()
    return out


def jsonpath_get_all(data: Any, path: str) -> list[Any]:
    nodes = [data]
    for tok in _tokens(path):
        nxt = []
        for n in nodes:
            if tok == "*":
                if isinstance(n, list):
                    nxt.extend(n)
                elif isinstance(n, dict):
                    nxt.extend(n.values())
            elif isinstance(tok, int):
                if isinstance(n, list) and -len(n) <= tok < len(n):
                    nxt.append(n[tok])
            elif isinstance(n, dict) and tok in n:
                nxt.append(n[tok])
        nodes = nxt
    return nodes


_MISSING = object()


def jsonpath_get(data: Any, path: str, default: Any = None) -> Any:
    vals = jsonpath_get_all(data, path)
    return vals[0] if vals else default


def jsonpath_set(data: Any, path: str, value: Any) -> Any:
    toks = _tokens(path)
    if not toks:
        return value
    node = data
    for tok in toks[:-1]:
        if isinstance(tok, int):
            node = node[tok]
        else:
            node = node.setdefault(tok, {})
    last = toks[-1]
    if isinstance(last, int):
        node[last] = value
    else:
        node[last] = value
    return data
