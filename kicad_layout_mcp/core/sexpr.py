"""Minimal S-expression builder for KiCad file formats.

KiCad schematic/board files are S-expressions. We build them as nested
Python lists and serialize with proper quoting and indentation so the
output diffs cleanly and parses in KiCad 8/9.
"""
from __future__ import annotations

import uuid as _uuid


class Sym(str):
    """A bare (unquoted) symbol token, e.g. `yes`, `signal`, `hide`."""
    __slots__ = ()


def new_uuid() -> str:
    return str(_uuid.uuid4())


def _fmt_num(v: float) -> str:
    # KiCad writes up to 6 decimals, trimming trailing zeros.
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _fmt_atom(a) -> str:
    if isinstance(a, Sym):
        return str(a)
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, int):
        return str(a)
    if isinstance(a, float):
        return _fmt_num(a)
    if isinstance(a, str):
        escaped = a.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    raise TypeError(f"Cannot serialize atom of type {type(a)}: {a!r}")


def dumps(expr, indent: int = 0) -> str:
    """Serialize a nested list into KiCad-style S-expression text."""
    if not isinstance(expr, (list, tuple)):
        return _fmt_atom(expr)

    pad = "\t" * indent
    # Short lists with only atoms go on one line.
    if all(not isinstance(e, (list, tuple)) for e in expr):
        inner_parts = []
        for i, e in enumerate(expr):
            if i == 0 and isinstance(e, str) and not isinstance(e, Sym):
                inner_parts.append(e)
            else:
                inner_parts.append(_fmt_atom(e))
        return f"({' '.join(inner_parts)})"

    parts = []
    head_atoms = []
    i = 0
    while i < len(expr) and not isinstance(expr[i], (list, tuple)):
        # Only the first token (KiCad keyword) is unquoted; rest are values.
        token = expr[i]
        if i == 0 and isinstance(token, str) and not isinstance(token, Sym):
            head_atoms.append(token)
        else:
            head_atoms.append(_fmt_atom(token))
        i += 1
    head = " ".join(head_atoms)
    parts.append(f"({head}" if head else "(")
    for e in expr[i:]:
        parts.append("\n" + "\t" * (indent + 1) + dumps(e, indent + 1))
    parts.append("\n" + pad + ")")
    return "".join(parts)


def write_file(path: str, expr) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(expr))
        f.write("\n")
