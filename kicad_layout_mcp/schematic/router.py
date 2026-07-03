"""Schematic connectivity generation.

Professional drafting rules applied automatically:
- Power/GND nets never get long wires: a power symbol is dropped at
  every pin (GND pointing down, rails pointing up).
- Short 2-pin nets inside one block are routed as real Manhattan wires
  with A* collision avoidance against symbol boxes and other wires.
- Everything else gets a short stub + net label (the way pros keep
  large schematics readable). Labels always point away from the body,
  so they can never overlap the symbol.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from ..core.circuit import Circuit, is_gnd_net, is_power_net
from ..library.parts import GRID
from .placer import HALF_GRID, LABEL_STUB, PlacedSymbol, SchematicLayout, snap

MAX_ROUTE_DIST = 60.0


@dataclass
class Wire:
    points: list  # [(x, y), ...] polyline


@dataclass
class PowerPin:
    net: str
    x: float
    y: float
    down: bool          # True for GND family (symbol below), False for rails (above)


@dataclass
class NetLabel:
    net: str
    x: float
    y: float
    angle: int          # 0 = attach left / text right; 180 = attach right / text left
    is_global: bool


@dataclass
class SchRouting:
    wires: list = field(default_factory=list)
    power_pins: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    junctions: list = field(default_factory=list)


def route_schematic(circuit: Circuit, layout: SchematicLayout) -> SchRouting:
    out = SchRouting()
    obstacles = [p.clear_box() for p in layout.placed.values()]
    pin_cells: set = set()
    for ps in layout.placed.values():
        for p in ps.symbol.pins:
            px, py = ps.pin_at(p.number)
            pin_cells.add(_cell(px, py))
            # keep one cell around each pin free of routing
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    pin_cells.add((_cell(px, py)[0] + dx, _cell(px, py)[1] + dy))
    wire_cells: set = set()

    def stub_and_dir(ps: PlacedSymbol, pin: str) -> tuple[tuple, tuple, str]:
        (px, py) = ps.pin_at(pin)
        side = ps.pin_side(pin)
        if side == "left":
            return (px, py), (px - LABEL_STUB, py), side
        if side == "right":
            return (px, py), (px + LABEL_STUB, py), side
        if side == "top":
            return (px, py), (px, py - LABEL_STUB), side
        return (px, py), (px, py + LABEL_STUB), side

    for net, pins in sorted(circuit.nets.items()):
        placed_pins = [(layout.placed[r], str(pin)) for r, pin in pins if r in layout.placed]
        if not placed_pins:
            continue

        # Power nets: short stub + global label (avoids embedded power-symbol lib issues).
        if is_gnd_net(net) or is_power_net(net):
            for ps, pin in placed_pins:
                (px, py), (lx, ly), side = stub_and_dir(ps, pin)
                out.wires.append(Wire([(px, py), (lx, ly)]))
                _mark_wire(wire_cells, [(px, py), (lx, ly)])
                angle = 180 if side == "left" else 0
                if side == "top":
                    angle = 90
                elif side == "bottom":
                    angle = 270
                out.labels.append(NetLabel(net, lx, ly, angle, is_global=True))
            continue

        same_block = len({ps.block for ps, _ in placed_pins}) == 1
        if len(placed_pins) == 2 and same_block:
            (a, pa), (b, pb) = placed_pins
            start = a.pin_at(pa)
            end = b.pin_at(pb)
            dist = abs(start[0] - end[0]) + abs(start[1] - end[1])
            if dist <= MAX_ROUTE_DIST:
                path = _astar(start, end, a.pin_side(pa), b.pin_side(pb),
                              obstacles, wire_cells | pin_cells)
                if path:
                    out.wires.append(Wire(path))
                    _mark_wire(wire_cells, path)
                    continue

        # Fallback: stub + label at each pin.
        is_glob = not same_block
        for ps, pin in placed_pins:
            (px, py), (lx, ly), side = stub_and_dir(ps, pin)
            out.wires.append(Wire([(px, py), (lx, ly)]))
            _mark_wire(wire_cells, [(px, py), (lx, ly)])
            angle = 180 if side in ("left",) else 0
            if side == "top":
                angle = 90
            elif side == "bottom":
                angle = 270
            out.labels.append(NetLabel(net, lx, ly, angle, is_glob))

    return out


# ---------------------------------------------------------------------------
# Manhattan A* on the 1.27mm grid
# ---------------------------------------------------------------------------

def _cell(x: float, y: float) -> tuple[int, int]:
    return (round(x / HALF_GRID), round(y / HALF_GRID))


def _mark_wire(cells: set, pts: list) -> None:
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        c1, c2 = _cell(x1, y1), _cell(x2, y2)
        if c1[0] == c2[0]:
            for gy in range(min(c1[1], c2[1]), max(c1[1], c2[1]) + 1):
                cells.add((c1[0], gy))
        else:
            for gx in range(min(c1[0], c2[0]), max(c1[0], c2[0]) + 1):
                cells.add((gx, c1[1]))


_DIRS = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}


def _astar(start, end, start_side, end_side, obstacles, wire_cells,
           max_nodes: int = 20000):
    s = _cell(*start)
    e = _cell(*end)

    blocked = set(wire_cells)
    blocked.discard(s)
    blocked.discard(e)

    def in_obstacle(c) -> bool:
        x, y = c[0] * HALF_GRID, c[1] * HALF_GRID
        for (x1, y1, x2, y2) in obstacles:
            if x1 - 0.6 < x < x2 + 0.6 and y1 - 0.6 < y < y2 + 0.6:
                return True
        return False

    def h(c) -> float:
        return abs(c[0] - e[0]) + abs(c[1] - e[1])

    sd = _DIRS[start_side]
    ed = _DIRS[end_side]
    first = (s[0] + sd[0], s[1] + sd[1])
    pre_end = (e[0] + ed[0], e[1] + ed[1])

    open_q = [(h(first), 0.0, first, sd, [s, first])]
    seen: dict = {}
    nodes = 0
    while open_q and nodes < max_nodes:
        nodes += 1
        f, g, cur, d, path = heapq.heappop(open_q)
        if cur == pre_end or cur == e:
            full = path if cur == e else path + [e]
            return _simplify([(c[0] * HALF_GRID, c[1] * HALF_GRID) for c in full])
        key = (cur, d)
        if key in seen and seen[key] <= g:
            continue
        seen[key] = g
        for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cur[0] + nd[0], cur[1] + nd[1])
            if nxt != e and nxt != pre_end:
                if nxt in blocked or in_obstacle(nxt):
                    continue
            cost = g + 1 + (2.0 if nd != d else 0.0)   # turn penalty
            heapq.heappush(open_q, (cost + h(nxt), cost, nxt, nd, path + [nxt]))
    return None


def _simplify(pts: list) -> list:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = out[-1], pts[i], pts[i + 1]
        if (x0 == x1 == x2) or (y0 == y1 == y2):
            continue
        out.append(pts[i])
    out.append(pts[-1])
    return out
