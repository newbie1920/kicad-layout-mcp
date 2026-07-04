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
LABEL_STUB = 2.54     # wire stub length before a net label (keep labels off pins)
V_TEXT_SPACE = 5.08   # reserved above symbol for ref/value text
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

    margin = 15.0
    block_gap = 6.0
    block_pad = 3.0   # extra margin inside blue rectangle around components


    # Step 1: build each block locally and measure its tight padded bbox.
    local_blocks: dict[str, dict] = {}
    for b in order:
        refs = [c.ref for c in blocks[b]]
        refs = _bfs_order(circuit, refs)
        shelf_x, shelf_y, shelf_h = 0.0, 0.0, 0.0
        placed_local: list[tuple] = []
        max_inner_w = 110.0
        for ref in refs:
            comp = circuit.components[ref]
            sym = get_symbol(comp.part)
            cb = _clearance(circuit, ref)
            w = cb[2] - cb[0]
            h = cb[3] - cb[1]
            if shelf_x > 0 and shelf_x + w > max_inner_w:
                shelf_y += shelf_h + 2.54
                shelf_x = 0.0
                shelf_h = 0.0
            lx = snap(shelf_x - cb[0])
            ly = snap(shelf_y - cb[1])
            placed_local.append((ref, sym, cb, lx, ly))
            shelf_x += w + 2.54
            shelf_h = max(shelf_h, h)
        if not placed_local:
            local_blocks[b] = {"refs": [], "w": 0.0, "h": 0.0, "x1": 0.0, "y1": 0.0}
            continue
        x1 = min(lx + cb[0] for _, _, cb, lx, ly in placed_local) - block_pad
        y1 = min(ly + cb[1] for _, _, cb, lx, ly in placed_local) - block_pad
        x2 = max(lx + cb[2] for _, _, cb, lx, ly in placed_local) + block_pad
        y2 = max(ly + cb[3] for _, _, cb, lx, ly in placed_local) + block_pad
        local_blocks[b] = {
            "refs": placed_local,
            "w": x2 - x1,
            "h": y2 - y1,
            "x1": x1,
            "y1": y1,
        }

    # Step 2: choose the smallest paper size that fits all blocks + reserved title-block corner.
    max_block_w = max((lb["w"] for lb in local_blocks.values()), default=0.0)
    max_block_h = max((lb["h"] for lb in local_blocks.values()), default=0.0)

    title_w = 0.0
    title_h = margin

    def pack_for_size(w, h):
        # Bottom-right title-block corner is reserved. Rows whose bottom is inside the
        # title zone may only use the left zone; rows entirely above may use full width.
        full_w = w - 2 * margin
        left_w = max(50.0, full_w - title_w)
        sorted_blocks = sorted(order, key=lambda b: local_blocks[b]["h"], reverse=True)
        rows: list[list[str]] = []
        row_w: list[float] = []
        row_h: list[float] = []
        row_top_y: list[float] = []
        # Track vertical cursor to decide row zone.
        cursor = h - margin
        for b in sorted_blocks:
            lb = local_blocks[b]
            bw = lb["w"] + block_gap
            placed = False
            # Try existing rows first
            for i, r in enumerate(rows):
                in_title_zone = (row_top_y[i] - row_h[i] < title_h)
                limit = left_w if in_title_zone else full_w
                if row_w[i] + bw <= limit:
                    r.append(b)
                    row_w[i] += bw
                    row_h[i] = max(row_h[i], lb["h"])
                    placed = True
                    break
            if not placed:
                # New row below current cursor
                new_h = lb["h"]
                in_title_zone = (cursor - new_h < title_h)
                limit = left_w if in_title_zone else full_w
                if bw > limit:
                    # cannot fit even in top zone -> fail
                    return rows, [], title_h, False
                rows.append([b])
                row_w.append(bw)
                row_h.append(new_h)
                row_top_y.append(cursor)
                cursor -= new_h + block_gap
        total_h = (h - margin) - (cursor - block_gap) if rows else 0
        fits = (max(row_w, default=0) <= full_w) and (total_h <= h - title_h)
        return rows, row_h, title_h, fits

    paper_options = [("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
    chosen_rows = None
    chosen_row_h = None
    chosen_title_h = None
    for name, pw, ph in paper_options:
        rows, rh, th, fits = pack_for_size(pw, ph)
        if fits:
            layout.paper = name
            layout.sheet_w, layout.sheet_h = pw, ph
            chosen_rows, chosen_row_h, chosen_title_h = rows, rh, th
            break
    if chosen_rows is None:
        # fallback to A0 even if overflow
        layout.paper = "A0"
        layout.sheet_w, layout.sheet_h = 1189, 841
        chosen_rows, chosen_row_h, chosen_title_h, _ = pack_for_size(1189, 841)

    # Step 3: place rows from top down (KiCad y increases upward).
    cursor_y = layout.sheet_h - margin
    for r, h in zip(chosen_rows, chosen_row_h):
        cursor_x = margin
        row_top = cursor_y
        row_bottom = max(chosen_title_h, cursor_y - h)
        for b in r:
            lb = local_blocks[b]
            bx = cursor_x - lb["x1"]
            by = row_top - lb["y1"] - lb["h"]
            for ref, sym, cb, lx, ly in lb["refs"]:
                ps = PlacedSymbol(ref=ref, symbol=sym, block=b, clear=cb)
                ps.x = snap(bx + lx)
                ps.y = snap(by + ly)
                layout.placed[ref] = ps
            # Blue rectangle exactly matches padded local bbox at global origin.
            layout.blocks[b] = (bx + lb["x1"], by + lb["y1"],
                                bx + lb["x1"] + lb["w"], by + lb["y1"] + lb["h"])
            cursor_x += lb["w"] + block_gap
        cursor_y = row_bottom - block_gap

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
