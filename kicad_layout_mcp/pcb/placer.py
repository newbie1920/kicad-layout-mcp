"""PCB placement: keep functional blocks together, connectors at board edge."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..core.circuit import Circuit, is_gnd_net, is_power_net
from ..library.parts import FootprintDef, GRID, get_part, get_symbol, resolve_footprint

# PCB grid in mm.
PCB_GRID = 0.5
PCB_MARGIN = 2.0


def snap_pcb(v: float) -> float:
    return round(v / PCB_GRID) * PCB_GRID


@dataclass
class PlacedFootprint:
    ref: str
    fp: FootprintDef
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0  # 0/90/180/270
    block: str = "main"
    side: str = "front"  # front | back

    def pin_world(self, pin_num: str) -> tuple[float, float]:
        for p in self.fp.pads:
            if p.number == str(pin_num):
                return self._rotate(p.x, p.y)
        raise ValueError(f"{self.ref}: pad {pin_num} not found")

    def _rotate(self, px: float, py: float) -> tuple[float, float]:
        rad = math.radians(self.angle)
        c, s = math.cos(rad), math.sin(rad)
        return (round(self.x + px * c - py * s, 3),
                round(self.y + px * s + py * c, 3))

    def courtyard_world(self) -> tuple[float, float, float, float]:
        cx1, cy1, cx2, cy2 = self.fp.courtyard
        pts = [self._rotate(cx1, cy1), self._rotate(cx1, cy2),
               self._rotate(cx2, cy1), self._rotate(cx2, cy2)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class PCBLayout:
    placed: dict[str, PlacedFootprint] = field(default_factory=dict)
    board_x1: float = 0.0
    board_y1: float = 0.0
    board_x2: float = 50.0
    board_y2: float = 50.0


def _fp_area(fp: FootprintDef) -> float:
    return fp.size()[0] * fp.size()[1]


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _courtyard_overlap(p1: PlacedFootprint, p2: PlacedFootprint) -> float:
    a = p1.courtyard_world()
    b = p2.courtyard_world()
    if not _overlaps(a, b):
        return 0.0
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy


def _hpwl(circuit: Circuit, layout: PCBLayout) -> float:
    total = 0.0
    for net, pins in circuit.nets.items():
        if is_gnd_net(net) or len(pins) < 2:
            continue
        xs = []
        ys = []
        for ref, pin in pins:
            if ref not in layout.placed:
                continue
            x, y = layout.placed[ref].pin_world(pin)
            xs.append(x)
            ys.append(y)
        if xs:
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def _decoupling_penalty(circuit: Circuit, layout: PCBLayout) -> float:
    pen = 0.0
    for ref, comp in circuit.components.items():
        if comp.part not in ("C",):
            continue
        # Find IC on same VCC/GND net.
        ic_ref = None
        for net, pins in circuit.nets.items():
            if not (is_power_net(net) or is_gnd_net(net)):
                continue
            refs = [r for r, _ in pins]
            if ref in refs:
                ic_ref = next((r for r in refs if r != ref and
                               get_part(circuit.components[r].part)["ref_prefix"] == "U"), None)
                if ic_ref:
                    break
        if ic_ref and ic_ref in layout.placed:
            x1, y1 = layout.placed[ref].x, layout.placed[ref].y
            x2, y2 = layout.placed[ic_ref].x, layout.placed[ic_ref].y
            dist = abs(x1 - x2) + abs(y1 - y2)
            if dist > 10.0:
                pen += (dist - 10.0) * 5.0
    return pen


def _score(circuit: Circuit, layout: PCBLayout) -> float:
    overlap = 0.0
    items = list(layout.placed.values())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            overlap += _courtyard_overlap(items[i], items[j]) * 1000.0
    return _hpwl(circuit, layout) + overlap + _decoupling_penalty(circuit, layout)


def _random_move(layout: PCBLayout, ref: str, rng: random.Random) -> tuple[float, float, float]:
    p = layout.placed[ref]
    old = (p.x, p.y, p.angle)
    p.x = snap_pcb(rng.uniform(layout.board_x1 + PCB_MARGIN, layout.board_x2 - PCB_MARGIN))
    p.y = snap_pcb(rng.uniform(layout.board_y1 + PCB_MARGIN, layout.board_y2 - PCB_MARGIN))
    if rng.random() < 0.3:
        p.angle = rng.choice([0, 90, 180, 270])
    return old


def _initial_guess(circuit: Circuit) -> PCBLayout:
    layout = PCBLayout()
    blocks = circuit.blocks()
    order = [b for b in circuit.block_order if b in blocks] + [b for b in blocks if b not in circuit.block_order]

    # Auto board size.
    total_area = sum(_fp_area(resolve_footprint(c.part, c.footprint)) for c in circuit.components.values())
    target_area = total_area * 6.0
    side = snap_pcb(math.sqrt(target_area) + 2 * PCB_MARGIN)
    bw, bh = circuit.board_width, circuit.board_height
    if bw <= 0:
        bw = side
    if bh <= 0:
        bh = side
    layout.board_x2 = snap_pcb(bw)
    layout.board_y2 = snap_pcb(bh)

    # Seed connectors at left/right edges.
    left_x = layout.board_x1 + PCB_MARGIN
    right_x = layout.board_x2 - PCB_MARGIN
    y_cursor = layout.board_y1 + PCB_MARGIN
    placed = []
    for ref, comp in circuit.components.items():
        fp = resolve_footprint(comp.part, comp.footprint)
        pf = PlacedFootprint(ref=ref, fp=fp, block=comp.block)
        # rough seed: connectors near edge, others random.
        if comp.part.startswith("CONN") or comp.part.startswith("TERMINAL") or comp.part.startswith("USB"):
            pf.x = left_x if "INPUT" in comp.block.upper() else right_x
            pf.y = snap_pcb(y_cursor)
            y_cursor += fp.size()[1] + 2.0
        else:
            pf.x = snap_pcb((layout.board_x1 + layout.board_x2) / 2 + rng_seed.uniform(-10, 10))
            pf.y = snap_pcb((layout.board_y1 + layout.board_y2) / 2 + rng_seed.uniform(-10, 10))
        placed.append(pf)
        layout.placed[ref] = pf

    # Move connectors inside board bounds if needed.
    for pf in layout.placed.values():
        cx1, cy1, cx2, cy2 = pf.courtyard_world()
        if cx1 < layout.board_x1:
            pf.x += layout.board_x1 - cx1
        if cy1 < layout.board_y1:
            pf.y += layout.board_y1 - cy1
        if cx2 > layout.board_x2:
            pf.x -= cx2 - layout.board_x2
        if cy2 > layout.board_y2:
            pf.y -= cy2 - layout.board_y2
    return layout


rng_seed = random.Random(42)


def _simulated_annealing(circuit: Circuit, layout: PCBLayout, iterations: int = 600) -> PCBLayout:
    rng = random.Random(42)
    best = {ref: (p.x, p.y, p.angle) for ref, p in layout.placed.items()}
    best_score = _score(circuit, layout)
    current_score = best_score
    T0 = best_score * 0.05 if best_score > 0 else 10.0
    for i in range(iterations):
        T = T0 * (1 - i / iterations)
        ref = rng.choice(list(layout.placed.keys()))
        old = _random_move(layout, ref, rng)
        s = _score(circuit, layout)
        delta = s - current_score
        if delta < 0 or rng.random() < math.exp(-delta / (T + 1e-9)):
            current_score = s
            if s < best_score:
                best_score = s
                best = {ref: (p.x, p.y, p.angle) for ref, p in layout.placed.items()}
        else:
            p = layout.placed[ref]
            p.x, p.y, p.angle = old
    for ref, state in best.items():
        layout.placed[ref].x, layout.placed[ref].y, layout.placed[ref].angle = state
    return layout


def place_pcb(circuit: Circuit) -> PCBLayout:
    layout = _initial_guess(circuit)
    return _simulated_annealing(circuit, layout)
