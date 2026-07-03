"""Schematic symbol placement.

Strategy (mirrors how a human engineer drafts a readable schematic):
- Components are grouped into functional blocks (declared by the AI).
- Blocks flow left -> right in declared order (signal flow convention).
- Inside a block, components are ordered by connectivity (BFS over the
  net graph) and packed on shelves (rows) using each symbol's *clearance
  box*: body + pins + reserved space for reference/value text and net
  label stubs. Non-overlap of clearance boxes guarantees that no symbol,
  wire stub or text can ever collide.
- Everything is snapped to the 1.27 mm KiCad grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.circuit import Circuit, is_gnd_net, is_power_net
from ..library.parts import GRID, SymbolDef, get_symbol

HALF_GRID = 1.27
CHAR_W = 1.1          # approx label char width at 1.27mm font
LABEL_STUB = 7.62     # wire stub length before a net label (keep labels off pins)
V_TEXT_SPACE = 7.62   # reserved above symbol for ref/value text
BODY_MARGIN = 1.27    # extra air gap around symbol body


def snap(v: float, g: float = HALF_GRID) -> float:
    return round(v / g) * g


@dataclass
class PlacedSymbol:
    ref: str
    symbol: SymbolDef
    x: float = 0.0
    y: float = 0.0
    block: str = "main"
    # clearance box relative to (x, y): x1, y1, x2, y2
    clear: tuple[float, float, float, float] = (0, 0, 0, 0)

    def pin_at(self, number: str) -> tuple[float, float]:
        for p in self.symbol.pins:
            if p.number == number:
                px, py = self.symbol.pin_pos(p)
                return (self.x + px, self.y + py)
        raise ValueError(f"{self.ref}: pin {number} not found")

    def pin_side(self, number: str) -> str:
        for p in self.symbol.pins:
            if p.number == number:
                return p.side
        raise ValueError(f"{self.ref}: pin {number} not found")

    def body_box(self) -> tuple[float, float, float, float]:
        return (self.x - self.symbol.body_w / 2, self.y - self.symbol.body_h / 2,
                self.x + self.symbol.body_w / 2, self.y + self.symbol.body_h / 2)

    def clear_box(self) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = self.clear
        return (self.x + x1, self.y + y1, self.x + x2, self.y + y2)


@dataclass
class SchematicLayout:
    placed: dict[str, PlacedSymbol] = field(default_factory=dict)
    blocks: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    sheet_w: float = 297.0
    sheet_h: float = 210.0


def _net_name_space(circuit: Circuit, ref: str, sides: set[str]) -> float:
    """Extra space needed for net labels / stubs on given pin sides."""
    longest = 0
    sym = get_symbol(circuit.components[ref].part)
    for net, pins in circuit.nets.items():
        for r, pin in pins:
            if r != ref:
                continue
            for p in sym.pins:
                if p.number == str(pin) and p.side in sides:
                    longest = max(longest, len(net))
    if not longest:
        return 1.27
    # stub + label text + small gap
    return LABEL_STUB + longest * CHAR_W + 1.5


def _clearance(circuit: Circuit, ref: str) -> tuple[float, float, float, float]:
    sym = get_symbol(circuit.components[ref].part)
    x1, y1, x2, y2 = sym.bbox()
    # grow body box slightly so wires don't graze the symbol
    x1 -= BODY_MARGIN
    y1 -= BODY_MARGIN
    x2 += BODY_MARGIN
    y2 += BODY_MARGIN
    pin_sides = {p.side for p in sym.pins}
    left_space = _net_name_space(circuit, ref, {"left"}) if "left" in pin_sides else 1.27
    right_space = _net_name_space(circuit, ref, {"right"}) if "right" in pin_sides else 1.27
    top_space = _net_name_space(circuit, ref, {"top"}) if "top" in pin_sides else 1.27
    bot_space = _net_name_space(circuit, ref, {"bottom"}) if "bottom" in pin_sides else 1.27
    # Reference + value text lives above/right of small parts, above ICs.
    ref_len = max(len(ref), len(circuit.components[ref].value)) * CHAR_W + 1.0
    if sym.shape == "box":
        return (x1 - left_space, y1 - top_space - V_TEXT_SPACE,
                x2 + right_space, y2 + bot_space + 1.27)
    # two-lead vertical passive: text goes to the right of the body
    return (x1 - 1.27, y1 - top_space - 1.27, x2 + max(ref_len, right_space) + 1.27,
            y2 + bot_space + 1.27)


def _bfs_order(circuit: Circuit, refs: list[str]) -> list[str]:
    """Order components so that connected ones end up adjacent."""
    adj: dict[str, set[str]] = {r: set() for r in refs}
    for net, pins in circuit.nets.items():
        if is_power_net(net) or is_gnd_net(net):
            continue
        members = [r for r, _ in pins if r in adj]
        for a in members:
            for b in members:
                if a != b:
                    adj[a].add(b)
    # Start from the component with most connections (usually the IC).
    remaining = set(refs)
    order: list[str] = []
    while remaining:
        start = max(remaining, key=lambda r: len(adj[r]))
        queue = [start]
        remaining.discard(start)
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            nxt = sorted(adj[cur] & remaining, key=lambda r: -len(adj[r]))
            for n in nxt:
                remaining.discard(n)
                queue.append(n)
    return order


def place_schematic(circuit: Circuit) -> SchematicLayout:
    layout = SchematicLayout()
    blocks = circuit.blocks()
    order = [b for b in circuit.block_order if b in blocks]
    order += [b for b in blocks if b not in order]

    margin = 20.0
    block_gap = 12.0
    cursor_x = margin
    max_row_h = 0.0
    cursor_y = margin + 8.0   # leave room for block title

    # Estimate a reasonable max block-column height from total content.
    total_h = 0.0
    for b in order:
        for c in blocks[b]:
            cb = _clearance(circuit, c.ref)
            total_h += (cb[3] - cb[1]) + 4.0
    target_col_h = max(80.0, min(180.0, total_h / max(1, len(order)) * 1.2))

    for b in order:
        refs = [c.ref for c in blocks[b]]
        refs = _bfs_order(circuit, refs)

        # Estimate a reasonable block width for this block.
        block_w_est = sum((_clearance(circuit, r)[2] - _clearance(circuit, r)[0]) + 6.0 for r in refs)
        target_block_w = max(90.0, min(280.0, block_w_est))

        # Shelf-pack inside this block.
        shelf_x = cursor_x
        shelf_y = cursor_y
        shelf_h = 0.0
        block_x2 = cursor_x
        block_y2 = cursor_y
        for ref in refs:
            comp = circuit.components[ref]
            sym = get_symbol(comp.part)
            cb = _clearance(circuit, ref)
            w = cb[2] - cb[0]
            h = cb[3] - cb[1]
            if shelf_x > cursor_x and shelf_x + w > cursor_x + target_block_w and shelf_y + shelf_h + h < cursor_y + target_col_h:
                # wrap shelf
                shelf_y += shelf_h + 6.0
                shelf_x = cursor_x
                shelf_h = 0.0
            ps = PlacedSymbol(ref=ref, symbol=sym, block=b, clear=cb)
            ps.x = snap(shelf_x - cb[0])
            ps.y = snap(shelf_y - cb[1])
            layout.placed[ref] = ps
            shelf_x += w + 6.0
            shelf_h = max(shelf_h, h)
            block_x2 = max(block_x2, shelf_x)
            block_y2 = max(block_y2, shelf_y + shelf_h)

        layout.blocks[b] = (cursor_x - 3.0, cursor_y - 8.0, block_x2 + 3.0, block_y2 + 3.0)
        cursor_x = block_x2 + block_gap
        max_row_h = max(max_row_h, block_y2 - cursor_y)

    # Resolve any residual overlaps defensively (should not happen).
    _push_apart(layout)

    # Sheet size: pick smallest standard sheet that fits.
    x2 = max(pb[2] for pb in (p.clear_box() for p in layout.placed.values()))
    y2 = max(pb[3] for pb in (p.clear_box() for p in layout.placed.values()))
    for name, w, h in [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594)]:
        if x2 + margin <= w and y2 + margin <= h:
            layout.sheet_w, layout.sheet_h = w, h
            layout.paper = name
            break
    else:
        layout.paper = "A1"
        layout.sheet_w, layout.sheet_h = 841, 594
    return layout


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _push_apart(layout: SchematicLayout, max_iter: int = 200) -> None:
    """Defensive overlap resolution: nudge symbols right/down until clean."""
    items = list(layout.placed.values())
    for _ in range(max_iter):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if _overlap(a.clear_box(), b.clear_box()):
                    bb = b.clear_box()
                    ab = a.clear_box()
                    dx = ab[2] - bb[0] + HALF_GRID
                    dy = ab[3] - bb[1] + HALF_GRID
                    if dx <= dy:
                        b.x = snap(b.x + dx)
                    else:
                        b.y = snap(b.y + dy)
                    moved = True
        if not moved:
            return
