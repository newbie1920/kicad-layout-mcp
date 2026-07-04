"""PCB placement with engineering heuristics for industrial controller."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..core.circuit import Circuit, is_gnd_net, is_power_net
from ..library.parts import FootprintDef, get_part, resolve_footprint

PCB_GRID = 0.5
BOARD_MARGIN = 4.0
CONN_MARGIN = 1.0
GAP = 6.0


def snap(v: float) -> float:
    return round(v / PCB_GRID) * PCB_GRID


@dataclass
class PlacedFootprint:
    ref: str
    fp: FootprintDef
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    block: str = "main"
    side: str = "front"

    def _rotate(self, px: float, py: float) -> tuple[float, float]:
        rad = math.radians(self.angle)
        c, s = math.cos(rad), math.sin(rad)
        return (self.x + px * c - py * s, self.y + px * s + py * c)

    def pin_world(self, pin_num: str) -> tuple[float, float]:
        for p in self.fp.pads:
            if p.number == str(pin_num):
                x, y = self._rotate(p.x, p.y)
                return (round(x, 3), round(y, 3))
        raise ValueError(f"{self.ref}: pad {pin_num} not found")

    def bbox(self, margin: float = 0.0) -> tuple[float, float, float, float]:
        cx1, cy1, cx2, cy2 = self.fp.courtyard
        pts = [self._rotate(cx1, cy1), self._rotate(cx1, cy2),
               self._rotate(cx2, cy1), self._rotate(cx2, cy2)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs) - margin, min(ys) - margin,
                max(xs) + margin, max(ys) + margin)

    def courtyard_world(self) -> tuple[float, float, float, float]:
        return self.bbox(0.0)


@dataclass
class PCBLayout:
    placed: dict[str, PlacedFootprint] = field(default_factory=dict)
    board_x1: float = 0.0
    board_y1: float = 0.0
    board_x2: float = 50.0
    board_y2: float = 50.0


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _is_connector(comp) -> bool:
    p = comp.part
    return p.startswith(("CONN", "TERMINAL", "USB", "RJ45", "SIM"))


def _is_passive(comp) -> bool:
    return comp.part in ("R", "C", "C_POL", "L", "LED", "D", "D_SCHOTTKY", "D_ZENER")


def _is_ic(comp) -> bool:
    return get_part(comp.part)["ref_prefix"] in ("U", "Q", "K", "Y")


def _fp_size(fp: FootprintDef) -> tuple[float, float]:
    cx1, cy1, cx2, cy2 = fp.courtyard
    return (cx2 - cx1, cy2 - cy1)


class Shelf:
    """Simple rectangle packer in a zone."""
    def __init__(self, x1: float, y1: float, x2: float, y2: float):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.cursor_x = x1
        self.cursor_y = y1
        self.row_h = 0.0
        self.items: list[PlacedFootprint] = []

    def pack(self, pf: PlacedFootprint, gap: float = GAP) -> bool:
        w, h = _fp_size(pf.fp)
        # try current row
        if self.cursor_x + w + gap > self.x2:
            self.cursor_x = self.x1
            self.cursor_y += self.row_h + gap
            self.row_h = 0.0
        if self.cursor_y + h + gap > self.y2:
            return False
        # center at cursor + half size (courtyard may not be centered)
        cx1, cy1, cx2, cy2 = pf.fp.courtyard
        pf.x = snap(self.cursor_x - cx1)
        pf.y = snap(self.cursor_y - cy1)
        self.items.append(pf)
        self.cursor_x += w + gap
        self.row_h = max(self.row_h, h)
        return True


def _clamp(layout: PCBLayout):
    for pf in layout.placed.values():
        bb = pf.bbox(BOARD_MARGIN)
        dx, dy = 0.0, 0.0
        if bb[0] < layout.board_x1:
            dx = layout.board_x1 - bb[0]
        if bb[2] > layout.board_x2:
            dx = layout.board_x2 - bb[2]
        if bb[1] < layout.board_y1:
            dy = layout.board_y1 - bb[1]
        if bb[3] > layout.board_y2:
            dy = layout.board_y2 - bb[3]
        pf.x += dx
        pf.y += dy


def _place_group(circuit: Circuit, refs: list[str], shelf: Shelf, layout: PCBLayout, angle: float = 0.0):
    for ref in refs:
        comp = circuit.components[ref]
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, angle=angle, block=comp.block)
        if not shelf.pack(pf):
            # fallback center
            cx, cy = (shelf.x1 + shelf.x2) / 2, (shelf.y1 + shelf.y2) / 2
            cx1, cy1, cx2, cy2 = pf.fp.courtyard
            pf.x = snap(cx - (cx1 + cx2) / 2)
            pf.y = snap(cy - (cy1 + cy2) / 2)
        layout.placed[ref] = pf




def _legalize(layout: PCBLayout, circuit: Circuit, max_iter: int = 100):
    refs = list(layout.placed.keys())
    for _ in range(max_iter):
        moved = False
        for i, ra in enumerate(refs):
            pa = layout.placed[ra]
            a = pa.bbox(1.0)
            # board clamp
            dx, dy = 0.0, 0.0
            if a[0] < layout.board_x1:
                dx = layout.board_x1 - a[0]
            if a[2] > layout.board_x2:
                dx = layout.board_x2 - a[2]
            if a[1] < layout.board_y1:
                dy = layout.board_y1 - a[1]
            if a[3] > layout.board_y2:
                dy = layout.board_y2 - a[3]
            if dx or dy:
                pa.x += dx; pa.y += dy; moved = True
                a = pa.bbox(1.0)
            for rb in refs[i+1:]:
                pb = layout.placed[rb]
                b = pb.bbox(1.0)
                if not _overlaps(a, b):
                    continue
                dx = min(a[2], b[2]) - max(a[0], b[0])
                dy = min(a[3], b[3]) - max(a[1], b[1])
                if dx < dy:
                    sep = dx / 2 + 0.5
                    if pa.x < pb.x:
                        pa.x -= sep; pb.x += sep
                    else:
                        pa.x += sep; pb.x -= sep
                else:
                    sep = dy / 2 + 0.5
                    if pa.y < pb.y:
                        pa.y -= sep; pb.y += sep
                    else:
                        pa.y += sep; pb.y -= sep
                pa.x = snap(pa.x); pa.y = snap(pa.y)
                pb.x = snap(pb.x); pb.y = snap(pb.y)
                moved = True
        if not moved:
            break
    _clamp(layout)

def place_pcb(circuit: Circuit) -> PCBLayout:
    bw = max(circuit.board_width, 100.0)
    bh = max(circuit.board_height, 80.0)
    layout = PCBLayout(board_x2=bw, board_y2=bh)
    comps = circuit.components

    def refs(*blocks):
        out = []
        for b in blocks:
            out += [r for r, c in comps.items() if c.block == b]
        return out

    def conn_refs(*blocks):
        return [r for r in refs(*blocks) if _is_connector(comps[r])]

    def other_refs(*blocks):
        return [r for r in refs(*blocks) if not _is_connector(comps[r])]

    # --- 1. Connectors at edges ---
    # left edge: power + DI + AI terminals, pins inward, body flush with left edge
    left_shelf = Shelf(CONN_MARGIN, 10.0, 50.0, bh - 10.0)
    _place_group(circuit, conn_refs("power") + conn_refs("di") + conn_refs("ai"), left_shelf, layout, angle=0)

    # top edge: relay output terminals, body flush with top edge
    top_shelf = Shelf(55.0, bh - 26.0, bw - 55.0, bh - CONN_MARGIN)
    _place_group(circuit, conn_refs("relay"), top_shelf, layout, angle=0)

    # right edge: comm connectors (USB, RJ45, RS485 terminal), body flush with right edge
    right_shelf = Shelf(bw - 50.0, 10.0, bw - CONN_MARGIN, bh - 10.0)
    _place_group(circuit, conn_refs("usb", "eth", "rs485") + conn_refs("cell"), right_shelf, layout, angle=0)

    # --- 2. MCU center ---
    mcu_ref = next((r for r, c in comps.items() if c.block == "mcu" and c.part == "STM32F407"), None)
    if mcu_ref:
        fp = resolve_footprint(comps[mcu_ref].part, comps[mcu_ref].footprint)
        pf = PlacedFootprint(ref=mcu_ref, fp=fp, angle=0, block="mcu")
        cx1, cy1, cx2, cy2 = fp.courtyard
        pf.x = snap(bw / 2 - (cx1 + cx2) / 2)
        pf.y = snap(bh / 2 - (cy1 + cy2) / 2)
        layout.placed[mcu_ref] = pf

    # --- 3. Power section bottom-left ---
    power_shelf = Shelf(55.0, CONN_MARGIN, 140.0, 45.0)
    _place_group(circuit, other_refs("power"), power_shelf, layout)

    # --- 4. Relay drivers above MCU / top-center ---
    relay_shelf = Shelf(55.0, bh - 90.0, bw - 55.0, bh - 28.0)
    _place_group(circuit, other_refs("relay"), relay_shelf, layout)

    # --- 5. Communication ICs right-center ---
    comm_shelf = Shelf(bw - 145.0, 50.0, bw - 55.0, bh - 95.0)
    _place_group(circuit, other_refs("rs485", "eth", "cell"), comm_shelf, layout)

    # --- 6. Analog front-end left-center (away from switching) ---
    analog_shelf = Shelf(55.0, 50.0, 140.0, bh - 95.0)
    _place_group(circuit, other_refs("ai") + other_refs("di"), analog_shelf, layout)

    # --- 7. MCU support around MCU ---
    mcu_support = [r for r in refs("mcu") if r not in layout.placed]
    # place in a ring around MCU using small zones
    mcu_shelf = Shelf(140.0, 50.0, bw - 145.0, bh - 95.0)
    _place_group(circuit, mcu_support, mcu_shelf, layout)

    # --- 8. RTC / battery bottom-right, quiet corner ---
    rtc_shelf = Shelf(bw - 145.0, CONN_MARGIN, bw - 55.0, 45.0)
    _place_group(circuit, refs("rtc"), rtc_shelf, layout)

    # --- 9. Indicators visible near top-right ---
    ind_shelf = Shelf(bw - 100.0, bh - 50.0, bw - 55.0, bh - 28.0)
    _place_group(circuit, refs("ind"), ind_shelf, layout)

    # --- 10. Anything else to center ---
    for ref, comp in comps.items():
        if ref in layout.placed:
            continue
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, angle=0, block=comp.block)
        cx1, cy1, cx2, cy2 = pf.fp.courtyard
        pf.x = snap(bw / 2 - (cx1 + cx2) / 2)
        pf.y = snap(bh / 2 - (cy1 + cy2) / 2)
        layout.placed[ref] = pf

    _clamp(layout)
    _legalize(layout, circuit)
    return layout
