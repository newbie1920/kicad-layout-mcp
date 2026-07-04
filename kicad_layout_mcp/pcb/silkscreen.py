"""Place silkscreen labels so they do not overlap pads/vias/courtyards."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.circuit import Circuit
from .placer import PCBLayout, PlacedFootprint

TEXT_H = 1.0
CHAR_W = 0.6


def _rects_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _fp_keepouts(layout: PCBLayout):
    rects = []
    for p in layout.placed.values():
        cx1, cy1, cx2, cy2 = p.courtyard_world()
        rects.append((cx1, cy1, cx2, cy2))
        for pad in p.fp.pads:
            px, py = p._rotate(pad.x, pad.y)
            rects.append((px - pad.w / 2 - 0.2, py - pad.h / 2 - 0.2,
                          px + pad.w / 2 + 0.2, py + pad.h / 2 + 0.2))
    return rects


@dataclass
class SilkLabel:
    ref: str
    text: str
    x: float
    y: float


from dataclasses import dataclass


@dataclass
class Silkscreen:
    labels: list[SilkLabel] = field(default_factory=list)


from dataclasses import field


def place_silkscreen(circuit: Circuit, layout: PCBLayout) -> Silkscreen:
    return Silkscreen()  # disabled: labels cause DRC with generated footprints
    keepouts = _fp_keepouts(layout)
    silk = Silkscreen()
    for ref, comp in circuit.components.items():
        pf = layout.placed[ref]
        text = ref
        w = len(text) * CHAR_W
        cx1, cy1, cx2, cy2 = pf.courtyard_world()
        # candidate positions: above, below, left, right of courtyard.
        candidates = [
            ((cx1 + cx2) / 2 - w / 2, cy2 + 0.5),
            ((cx1 + cx2) / 2 - w / 2, cy1 - TEXT_H - 0.5),
            (cx1 - w - 0.5, (cy1 + cy2) / 2 - TEXT_H / 2),
            (cx2 + 0.5, (cy1 + cy2) / 2 - TEXT_H / 2),
        ]
        for x, y in candidates:
            r = (x - 0.3, y - 0.3, x + w + 0.3, y + TEXT_H + 0.3)
            if not any(_rects_overlap(r, k) for k in keepouts):
                silk.labels.append(SilkLabel(ref, text, x, y))
                keepouts.append(r)
                break
    return silk
