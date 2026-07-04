"""PCB placement with engineering heuristics for industrial controller."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.circuit import Circuit
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


def _set_edge_pos(pf: PlacedFootprint, edge: str, board: tuple):
    """Align rotated bbox to a board edge."""
    bx1, by1, bx2, by2 = board
    # compute bbox with current x,y
    bb = pf.bbox(0.0)
    if edge == "left":
        pf.x += (bx1 + CONN_MARGIN) - bb[0]
    elif edge == "right":
        pf.x += (bx2 - CONN_MARGIN) - bb[2]
    elif edge == "top":
        pf.y += (by2 - CONN_MARGIN) - bb[3]
    elif edge == "bottom":
        pf.y += (by1 + CONN_MARGIN) - bb[1]


def _place_edge_stack(circuit: Circuit, refs: list[str], layout: PCBLayout,
                      edge: str, start: float, stop: float, axis: str):
    """Stack connectors along an edge. axis='x' means horizontal stack (top/bottom edges)."""
    cursor = start
    for ref in refs:
        comp = circuit.components[ref]
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, angle=0, block=comp.block)
        # initial temporary position
        pf.x = 0.0
        pf.y = 0.0
        # choose angle per edge
        if edge in ("left", "right"):
            pf.angle = 90
        # stack coordinate
        if axis == "x":
            pf.x = cursor
        else:
            pf.y = cursor
        _set_edge_pos(pf, edge, (layout.board_x1, layout.board_y1, layout.board_x2, layout.board_y2))
        layout.placed[ref] = pf
        # advance cursor by bbox extent on axis + gap
        bb = pf.bbox(GAP)
        cursor = bb[3] if axis == "y" else bb[2]
        if cursor > stop:
            cursor = start  # overflow, will overlap but keep within edge


def _place_group(circuit: Circuit, refs: list[str], layout: PCBLayout,
                 x1: float, y1: float, x2: float, y2: float):
    cursor_x = x1
    cursor_y = y1
    row_h = 0.0
    for ref in refs:
        comp = circuit.components[ref]
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, angle=0, block=comp.block)
        cx1, cy1, cx2, cy2 = pf.fp.courtyard
        w, h = cx2 - cx1, cy2 - cy1
        if cursor_x + w + GAP > x2:
            cursor_x = x1
            cursor_y += row_h + GAP
            row_h = 0.0
        if cursor_y + h + GAP > y2:
            # fallback: dump at center of zone
            cursor_x = (x1 + x2) / 2 - w / 2
            cursor_y = (y1 + y2) / 2 - h / 2
        pf.x = snap(cursor_x - cx1)
        pf.y = snap(cursor_y - cy1)
        layout.placed[ref] = pf
        cursor_x += w + GAP
        row_h = max(row_h, h)


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


def _legalize(layout: PCBLayout, max_iter: int = 100):
    refs = list(layout.placed.keys())
    for _ in range(max_iter):
        moved = False
        for i, ra in enumerate(refs):
            pa = layout.placed[ra]
            a = pa.bbox(2.0)
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
                a = pa.bbox(2.0)
            for rb in refs[i + 1:]:
                pb = layout.placed[rb]
                b = pb.bbox(2.0)
                if not _overlaps(a, b):
                    continue
                dx = min(a[2], b[2]) - max(a[0], b[0])
                dy = min(a[3], b[3]) - max(a[1], b[1])
                sep = dx / 2 + 0.5 if dx < dy else dy / 2 + 0.5
                if dx < dy:
                    if pa.x < pb.x:
                        pa.x -= sep; pb.x += sep
                    else:
                        pa.x += sep; pb.x -= sep
                else:
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


def _auto_board_size(layout: PCBLayout, margin: float = BOARD_MARGIN):
    if not layout.placed:
        return
    xs, ys = [], []
    for pf in layout.placed.values():
        bb = pf.bbox(margin)
        xs += [bb[0], bb[2]]
        ys += [bb[1], bb[3]]
    layout.board_x2 = snap(max(xs))
    layout.board_y2 = snap(max(ys))


def place_pcb(circuit: Circuit) -> PCBLayout:
    # initial board large; auto size later
    bw = 240.0
    bh = 180.0
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

    # --- Connectors at edges, flush and oriented outward ---
    # left: power + DI + AI terminals, rotated 90, wire entry left
    left_refs = conn_refs("power") + conn_refs("di") + conn_refs("ai")
    _place_edge_stack(circuit, left_refs, layout, "left", 10.0, bh - 10.0, axis="y")

    # top: relay terminals, wire entry up
    top_refs = conn_refs("relay")
    _place_edge_stack(circuit, top_refs, layout, "top", 55.0, bw - 55.0, axis="x")

    # right: RJ45, RS485 terminal, SIM, wire entry right
    right_refs = conn_refs("eth", "rs485") + conn_refs("cell")
    _place_edge_stack(circuit, right_refs, layout, "right", 10.0, bh - 10.0, axis="y")
    # bottom: USB connector, opening down
    usb_refs = conn_refs("usb")
    _place_edge_stack(circuit, usb_refs, layout, "bottom", 55.0, bw - 55.0, axis="x")

    # MCU center
    mcu_ref = next((r for r, c in comps.items() if c.block == "mcu" and c.part == "STM32F407"), None)
    if mcu_ref:
        fp = resolve_footprint(comps[mcu_ref].part, comps[mcu_ref].footprint)
        pf = PlacedFootprint(ref=mcu_ref, fp=fp, angle=0, block="mcu")
        cx1, cy1, cx2, cy2 = fp.courtyard
        pf.x = snap(bw / 2 - (cx1 + cx2) / 2)
        pf.y = snap(bh / 2 - (cy1 + cy2) / 2)
        layout.placed[mcu_ref] = pf

    # Power IC + passives bottom-left
    _place_group(circuit, other_refs("power"), layout, 55.0, BOARD_MARGIN, 140.0, 45.0)

    # Relay drivers top-center
    _place_group(circuit, other_refs("relay"), layout, 55.0, bh - 90.0, bw - 55.0, bh - 28.0)

    # Comm ICs right-center
    _place_group(circuit, other_refs("rs485", "eth", "cell"), layout, bw - 145.0, 50.0, bw - 55.0, bh - 95.0)

    # Analog front-end left-center
    _place_group(circuit, other_refs("ai") + other_refs("di"), layout, 55.0, 50.0, 140.0, bh - 95.0)

    # MCU support around MCU
    mcu_support = [r for r in refs("mcu") if r not in layout.placed]
    _place_group(circuit, mcu_support, layout, 140.0, 50.0, bw - 145.0, bh - 95.0)

    # RTC bottom-right
    _place_group(circuit, refs("rtc"), layout, bw - 145.0, BOARD_MARGIN, bw - 55.0, 45.0)

    # Indicators top-right
    _place_group(circuit, refs("ind"), layout, bw - 100.0, bh - 50.0, bw - 55.0, bh - 28.0)

    # leftovers
    for ref, comp in comps.items():
        if ref in layout.placed:
            continue
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, angle=0, block=comp.block)
        cx1, cy1, cx2, cy2 = pf.fp.courtyard
        pf.x = snap(bw / 2 - (cx1 + cx2) / 2)
        pf.y = snap(bh / 2 - (cy1 + cy2) / 2)
        layout.placed[ref] = pf

    _auto_board_size(layout, BOARD_MARGIN)
    _clamp(layout)
    _legalize(layout)
    return layout
