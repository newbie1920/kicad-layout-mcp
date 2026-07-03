"""Internal DRC: clearance, courtyard overlap, unconnected pads."""
from __future__ import annotations

from ..core.circuit import Circuit
from .placer import PCBLayout
from .router import RouteResult


def run_drc(circuit: Circuit, layout: PCBLayout, route: RouteResult) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    # Courtyard overlap.
    items = list(layout.placed.values())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a = items[i].courtyard_world()
            b = items[j].courtyard_world()
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                errors.append(f"Courtyard overlap: {items[i].ref} and {items[j].ref}")

    # Track too close / through pads.
    for t in route.tracks:
        for p in layout.placed.values():
            for pad in p.fp.pads:
                # pad bbox expanded by clearance + half track width.
                margin = 0.2 + t.width / 2
                px, py = p._rotate(pad.x, pad.y)
                hw, hh = pad.w / 2 + margin, pad.h / 2 + margin
                pad_rect = (px - hw, py - hh, px + hw, py + hh)
                # skip if track starts/ends inside this pad.
                if _in_rect(t.x1, t.y1, pad_rect) or _in_rect(t.x2, t.y2, pad_rect):
                    continue
                if _segment_intersects_rect((t.x1, t.y1), (t.x2, t.y2), pad_rect):
                    errors.append(f"Track on net {t.net} too close to pad {pad.number} of {p.ref}")

    # Unconnected nets.
    for net, pins in circuit.nets.items():
        if len(pins) < 2:
            errors.append(f"Net {net} has only one connection")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _in_rect(x, y, rect):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _segment_intersects_rect(a, b, rect):
    # Liang-Barsky / Cohen-Sutherland simplified: check segment bbox overlap with rect.
    sx, sy = a
    ex, ey = b
    sb = (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))
    if sb[2] < rect[0] or sb[0] > rect[2] or sb[3] < rect[1] or sb[1] > rect[3]:
        return False
    # If either endpoint inside, already handled by caller.
    if _in_rect(sx, sy, rect) or _in_rect(ex, ey, rect):
        return True
    # Check crossing each edge.
    edges = [(rect[0], rect[1], rect[0], rect[3]),
             (rect[2], rect[1], rect[2], rect[3]),
             (rect[0], rect[1], rect[2], rect[1]),
             (rect[0], rect[3], rect[2], rect[3])]
    for e in edges:
        if _segments_cross(a, b, (e[0], e[1]), (e[2], e[3])):
            return True
    return False


def _segments_cross(a, b, c, d):
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)
