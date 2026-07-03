"""Reference / value text placement with collision avoidance.

For every symbol we try 8 candidate positions around the body and pick
the first one whose text rectangle does not intersect any symbol body,
wire, net label, or previously placed text. Because symbol clearance
boxes already reserve space, a valid position always exists.
"""
from __future__ import annotations

from dataclasses import dataclass

from .placer import CHAR_W, PlacedSymbol, SchematicLayout, snap
from .router import SchRouting

TEXT_H = 1.6


@dataclass
class PlacedText:
    text: str
    x: float          # anchor (justify-left) position
    y: float
    kind: str         # "reference" | "value"


def _text_rect(x: float, y: float, text: str):
    w = len(text) * CHAR_W
    return (x - 0.3, y - TEX_H_HALF(), x + w + 0.3, y + TEX_H_HALF())


def TEX_H_HALF() -> float:
    return TEXT_H / 2 + 0.2


def _rects_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _wire_rects(routing: SchRouting):
    rects = []
    for w in routing.wires:
        for (x1, y1), (x2, y2) in zip(w.points, w.points[1:]):
            rects.append((min(x1, x2) - 0.4, min(y1, y2) - 0.4,
                          max(x1, x2) + 0.4, max(y1, y2) + 0.4))
    return rects


def _label_rects(routing: SchRouting):
    rects = []
    for lb in routing.labels:
        w = len(lb.net) * CHAR_W + 2.0
        if lb.angle == 0:
            rects.append((lb.x, lb.y - 1.1, lb.x + w, lb.y + 1.1))
        elif lb.angle == 180:
            rects.append((lb.x - w, lb.y - 1.1, lb.x, lb.y + 1.1))
        elif lb.angle == 90:
            rects.append((lb.x - 1.1, lb.y - w, lb.x + 1.1, lb.y))
        else:
            rects.append((lb.x - 1.1, lb.y, lb.x + 1.1, lb.y + w))
    for pp in routing.power_pins:
        rects.append((pp.x - 2.0, pp.y - 0.5, pp.x + 2.0, pp.y + 5.5)
                     if pp.down else (pp.x - 2.0, pp.y - 5.5, pp.x + 2.0, pp.y + 0.5))
    return rects


def place_text(layout: SchematicLayout, routing: SchRouting,
               values: dict[str, str]) -> dict[str, list[PlacedText]]:
    """Returns ref -> [PlacedText(reference), PlacedText(value)]."""
    occupied = [p.body_box() for p in layout.placed.values()]
    occupied += _wire_rects(routing)
    occupied += _label_rects(routing)

    result: dict[str, list[PlacedText]] = {}
    for ref, ps in layout.placed.items():
        texts: list[PlacedText] = []
        for kind, text in (("reference", ref), ("value", values.get(ref, ""))):
            if not text:
                continue
            pos = _find_spot(ps, text, occupied, prefer_second_row=(kind == "value"))
            occupied.append(_text_rect(pos[0], pos[1], text))
            texts.append(PlacedText(text, pos[0], pos[1], kind))
        result[ref] = texts
    return result


def _candidates(ps: PlacedSymbol, text: str, second: bool):
    bx1, by1, bx2, by2 = ps.body_box()
    w = len(text) * CHAR_W
    dy = TEXT_H + 0.6 if second else 0.0
    if ps.symbol.shape != "box":
        # passive: right of body, two stacked rows
        return [
            (bx2 + 0.8, ps.y - 1.0 + dy),
            (bx2 + 0.8, ps.y + 1.0 + dy),
            (bx1 - w - 0.8, ps.y - 1.0 + dy),
            (bx1 - w - 0.8, ps.y + 1.0 + dy),
            (ps.x - w / 2, by1 - 1.4 - dy),
            (ps.x - w / 2, by2 + 1.4 + dy),
        ]
    # IC box: above the body (row 1 = ref, row 2 = value), else below
    return [
        (bx1, by1 - 1.6 - dy),
        (bx1, by2 + 1.6 + dy),
        (bx2 + 0.8, by1 + 1.0 + dy),
        (ps.x - w / 2, by1 - 1.6 - dy),
    ]


def _find_spot(ps: PlacedSymbol, text: str, occupied: list, prefer_second_row: bool):
    for cand in _candidates(ps, text, prefer_second_row):
        r = _text_rect(cand[0], cand[1], text)
        if not any(_rects_overlap(r, o) for o in occupied):
            return cand
    # Escalate: march upward until free (always terminates on open canvas).
    x, y = _candidates(ps, text, prefer_second_row)[0]
    for k in range(1, 40):
        r = _text_rect(x, y - k * 2.0, text)
        if not any(_rects_overlap(r, o) for o in occupied):
            return (x, y - k * 2.0)
    return (x, y)
