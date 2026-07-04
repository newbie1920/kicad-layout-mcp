"""Embedded parts library: symbols + footprints, fully parametric.

Symbols and footprints are defined as data (not hand-drawn coordinates
from the AI), so all geometry is deterministic and grid-aligned.
Units: mm. Schematic pin grid: 2.54 mm (mandatory in KiCad).
"""
from __future__ import annotations

from dataclasses import dataclass, field

GRID = 2.54


# --------------------------------------------------------------------------
# Symbol model
# --------------------------------------------------------------------------

@dataclass
class SPin:
    number: str
    name: str
    side: str          # left | right | top | bottom
    slot: int          # index along the side, 0-based
    etype: str = "passive"  # passive|input|output|bidirectional|power_in|power_out|no_connect


@dataclass
class SymbolDef:
    key: str
    ref_prefix: str
    body_w: float
    body_h: float
    pins: list[SPin]
    pin_len: float = 2.54
    shape: str = "box"     # box | resistor | capacitor | diode | led (preview styling)
    show_pin_names: bool = True
    show_pin_numbers: bool = True
    description: str = ""

    def pin_pos(self, pin: SPin) -> tuple[float, float]:
        """Connection-point position of a pin, relative to symbol center (mm).

        Y axis: schematic convention (positive = down in file, but we keep
        a math convention here: +y down to match KiCad sch coordinates).
        """
        hw, hh = self.body_w / 2, self.body_h / 2
        if pin.side == "left":
            n = len([p for p in self.pins if p.side == "left"])
            y0 = -((n - 1) * GRID) / 2
            return (-hw - self.pin_len, y0 + pin.slot * GRID)
        if pin.side == "right":
            n = len([p for p in self.pins if p.side == "right"])
            y0 = -((n - 1) * GRID) / 2
            return (hw + self.pin_len, y0 + pin.slot * GRID)
        if pin.side == "top":
            n = len([p for p in self.pins if p.side == "top"])
            x0 = -((n - 1) * GRID) / 2
            return (x0 + pin.slot * GRID, -hh - self.pin_len)
        # bottom
        n = len([p for p in self.pins if p.side == "bottom"])
        x0 = -((n - 1) * GRID) / 2
        return (x0 + pin.slot * GRID, hh + self.pin_len)

    def bbox(self) -> tuple[float, float, float, float]:
        """Bounding box including pins, relative to center: (x1, y1, x2, y2)."""
        x1 = -self.body_w / 2
        y1 = -self.body_h / 2
        x2 = self.body_w / 2
        y2 = self.body_h / 2
        for p in self.pins:
            px, py = self.pin_pos(p)
            x1, y1 = min(x1, px), min(y1, py)
            x2, y2 = max(x2, px), max(y2, py)
        return (x1, y1, x2, y2)


def _two_lead(key: str, prefix: str, shape: str, desc: str) -> SymbolDef:
    """Vertical two-lead passive: pin 1 top, pin 2 bottom."""
    return SymbolDef(
        key=key, ref_prefix=prefix, body_w=2.54, body_h=5.08, shape=shape,
        show_pin_names=False, show_pin_numbers=False, description=desc,
        pins=[
            SPin("1", "~", "top", 0),
            SPin("2", "~", "bottom", 0),
        ],
    )


def _box(key: str, prefix: str, left: list = (), right: list = (), top: list = (),
         bottom: list = (), desc: str = "", min_w: float = 10.16) -> SymbolDef:
    """IC-style box symbol. left/right/top/bottom: list of (number, name, etype)."""
    pins: list[SPin] = []
    for i, (num, name, et) in enumerate(left):
        pins.append(SPin(str(num), name, "left", i, et))
    for i, (num, name, et) in enumerate(right):
        pins.append(SPin(str(num), name, "right", i, et))
    for i, (num, name, et) in enumerate(top):
        pins.append(SPin(str(num), name, "top", i, et))
    for i, (num, name, et) in enumerate(bottom):
        pins.append(SPin(str(num), name, "bottom", i, et))
    n_side = max(len(left), len(right))
    body_h = max(2, n_side + 1) * GRID
    # Width: enough for longest pin names on both sides.
    max_name = max([len(p.name) for p in pins] + [4])
    body_w = max(min_w, round((max_name * 1.3 * 2 + 5.08) / GRID) * GRID)
    if top or bottom:
        body_w = max(body_w, (max(len(top), len(bottom)) + 1) * GRID)
    return SymbolDef(key=key, ref_prefix=prefix, body_w=body_w, body_h=body_h,
                     pins=pins, description=desc)


# --------------------------------------------------------------------------
# Footprint model
# --------------------------------------------------------------------------

@dataclass
class PadDef:
    number: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "roundrect"   # rect | roundrect | circle | oval
    ptype: str = "smd"         # smd | thru_hole
    drill: float = 0.0


@dataclass
class FootprintDef:
    key: str
    pads: list[PadDef]
    courtyard: tuple[float, float, float, float]   # x1,y1,x2,y2 around origin
    silk: list = field(default_factory=list)        # [(x1,y1,x2,y2), ...]
    attr: str = "smd"                               # smd | through_hole
    description: str = ""

    def size(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.courtyard
        return (x2 - x1, y2 - y1)


def _chip(key: str, body_l: float, body_w: float, pad_l: float, pad_w: float, pitch: float,
          desc: str) -> FootprintDef:
    """Two-pad chip footprint (0402..1206). Pads left/right of origin."""
    half = pitch / 2
    cy = max(body_l / 2 + pad_l, half + pad_l / 2) + 0.25
    cx = max(body_w, pad_w) / 2 + 0.25
    s = body_w / 2 + 0.15
    e = half - pad_l / 2 - 0.2
    silk = []
    if e > s * 0.2:
        silk = [(-e, -s, e, -s), (-e, s, e, s)]
    return FootprintDef(
        key=key, attr="smd", description=desc,
        pads=[
            PadDef("1", -half, 0, pad_l, pad_w),
            PadDef("2", half, 0, pad_l, pad_w),
        ],
        courtyard=(-cy, -cx, cy, cx),
        silk=silk,
    )


def _dual_row(key: str, n: int, pitch: float, row_sep: float, pad_w: float, pad_h: float,
              body_w: float, body_l: float, attr: str = "smd", drill: float = 0.0,
              desc: str = "") -> FootprintDef:
    """SOIC/DIP-style dual row, pin 1 top-left, CCW numbering."""
    per_side = n // 2
    pads = []
    y0 = -((per_side - 1) * pitch) / 2
    shape = "oval" if attr == "through_hole" else "roundrect"
    ptype = "thru_hole" if attr == "through_hole" else "smd"
    for i in range(per_side):
        pads.append(PadDef(str(i + 1), -row_sep / 2, y0 + i * pitch, pad_w, pad_h,
                           shape="rect" if i == 0 and ptype == "thru_hole" else shape,
                           ptype=ptype, drill=drill))
    for i in range(per_side):
        pads.append(PadDef(str(per_side + i + 1), row_sep / 2, y0 + (per_side - 1 - i) * pitch,
                           pad_w, pad_h, shape=shape, ptype=ptype, drill=drill))
    cx = row_sep / 2 + pad_w / 2 + 0.25
    cy = max(body_l / 2, (per_side - 1) * pitch / 2 + pad_h / 2) + 0.25
    bs = body_w / 2
    bl = body_l / 2
    silk = [(-bs, -bl, bs, -bl), (-bs, bl, bs, bl), (-bs, -bl, -bs, bl), (bs, -bl, bs, bl),
            (-bs - 0.4, y0 - pitch / 2, -bs - 0.4, y0)]  # pin-1 mark
    return FootprintDef(key=key, pads=pads, courtyard=(-cx, -cy, cx, cy), silk=silk,
                        attr=attr, description=desc)


def _quad(key: str, n: int, pitch: float, span: float, pad_w: float, pad_h: float,
          body: float, desc: str = "") -> FootprintDef:
    """LQFP/TQFP quad footprint, pin 1 at left side top, CCW."""
    per_side = n // 4
    pads = []
    c0 = -((per_side - 1) * pitch) / 2
    for i in range(per_side):     # left, top->bottom: 1..per_side
        pads.append(PadDef(str(i + 1), -span / 2, c0 + i * pitch, pad_h, pad_w))
    for i in range(per_side):     # bottom, left->right
        pads.append(PadDef(str(per_side + i + 1), c0 + i * pitch, span / 2, pad_w, pad_h))
    for i in range(per_side):     # right, bottom->top
        pads.append(PadDef(str(2 * per_side + i + 1), span / 2, c0 + (per_side - 1 - i) * pitch, pad_h, pad_w))
    for i in range(per_side):     # top, right->left
        pads.append(PadDef(str(3 * per_side + i + 1), c0 + (per_side - 1 - i) * pitch, -span / 2, pad_w, pad_h))
    c = span / 2 + pad_h / 2 + 0.25
    b = body / 2
    silk = [(-b, -b, b, -b), (-b, b, b, b), (-b, -b, -b, b), (b, -b, b, b)]
    return FootprintDef(key=key, pads=pads, courtyard=(-c, -c, c, c), silk=silk,
                        attr="smd", description=desc)


def _header(key: str, n: int, desc: str) -> FootprintDef:
    pads = []
    y0 = -((n - 1) * 2.54) / 2
    for i in range(n):
        pads.append(PadDef(str(i + 1), 0, y0 + i * 2.54, 1.7, 1.7,
                           shape="rect" if i == 0 else "circle",
                           ptype="thru_hole", drill=1.0))
    c = 1.6
    cy = (n - 1) * 2.54 / 2 + 1.6
    return FootprintDef(key=key, pads=pads, courtyard=(-c, -cy, c, cy),
                        silk=[(-1.27, -cy + 0.3, 1.27, -cy + 0.3), (-1.27, cy - 0.3, 1.27, cy - 0.3),
                              (-1.27, -cy + 0.3, -1.27, cy - 0.3), (1.27, -cy + 0.3, 1.27, cy - 0.3)],
                        attr="through_hole", description=desc)


def _sot23(key: str = "SOT-23", desc: str = "SOT-23 3-pin") -> FootprintDef:
    return FootprintDef(
        key=key, attr="smd", description=desc,
        pads=[
            PadDef("1", -0.95, 1.0, 0.9, 0.8),
            PadDef("2", 0.95, 1.0, 0.9, 0.8),
            PadDef("3", 0.0, -1.0, 0.9, 0.8),
        ],
        courtyard=(-1.75, -1.7, 1.75, 1.7),
        silk=[(-0.75, -0.7, 0.75, -0.7), (-0.75, 0.7, 0.75, 0.7)],
    )


def _sot223(key: str = "SOT-223", desc: str = "SOT-223 (AMS1117 etc.)") -> FootprintDef:
    return FootprintDef(
        key=key, attr="smd", description=desc,
        pads=[
            PadDef("1", -2.3, 3.15, 1.5, 2.0),
            PadDef("2", 0.0, 3.15, 1.5, 2.0),
            PadDef("3", 2.3, 3.15, 1.5, 2.0),
            PadDef("4", 0.0, -3.15, 3.6, 2.0),
        ],
        courtyard=(-3.7, -4.4, 3.7, 4.4),
        silk=[(-1.85, -1.6, 1.85, -1.6), (-1.85, 1.6, 1.85, 1.6),
              (-1.85, -1.6, -1.85, 1.6), (1.85, -1.6, 1.85, 1.6)],
    )


def _to220(key: str = "TO-220-3", desc: str = "TO-220 vertical") -> FootprintDef:
    pads = [PadDef(str(i + 1), -2.54 + i * 2.54, 0, 1.9, 1.9,
                   shape="rect" if i == 0 else "circle", ptype="thru_hole", drill=1.1)
            for i in range(3)]
    return FootprintDef(
        key=key, pads=pads, attr="through_hole", description=desc,
        courtyard=(-5.6, -2.8, 5.6, 3.2),
        silk=[(-5.1, -2.4, 5.1, -2.4), (-5.1, 2.6, 5.1, 2.6),
              (-5.1, -2.4, -5.1, 2.6), (5.1, -2.4, 5.1, 2.6)],
    )


def _esp32_wroom(key: str = "ESP32-WROOM-32") -> FootprintDef:
    """ESP32-WROOM-32 module: 18 x 25.5 mm, 1.27 pitch castellated pads."""
    pads: list[PadDef] = []
    # Left side: pins 1..14, from top (module antenna up). First pin y = -8.26.
    y0 = -8.255
    for i in range(14):
        pads.append(PadDef(str(i + 1), -8.5, y0 + i * 1.27, 2.0, 0.9))
    # Bottom side: pins 15..24, left -> right.
    x0 = -5.715
    for i in range(10):
        pads.append(PadDef(str(15 + i), x0 + i * 1.27, 12.25, 0.9, 2.0))
    # Right side: pins 25..38, bottom -> top.
    for i in range(14):
        pads.append(PadDef(str(25 + i), 8.5, y0 + (13 - i) * 1.27, 2.0, 0.9))
    # Thermal pad.
    pads.append(PadDef("39", 0, 6.0, 5.0, 5.0, shape="rect"))
    b = 9.0
    return FootprintDef(
        key=key, pads=pads, attr="smd",
        courtyard=(-9.9, -13.0, 9.9, 13.6),
        silk=[(-b, -12.75, b, -12.75), (-b, 12.75, b, 12.75),
              (-b, -12.75, -b, 12.75), (b, -12.75, b, 12.75),
              (-b, -6.4, b, -6.4)],  # antenna keep-out line
        description="ESP32-WROOM-32 module, 38 pads + thermal",
    )


def _tact_switch(key: str = "SW_PUSH_6mm") -> FootprintDef:
    pads = [
        PadDef("1", -3.25, -2.25, 2.0, 1.3, ptype="thru_hole", drill=1.0, shape="oval"),
        PadDef("1", 3.25, -2.25, 2.0, 1.3, ptype="thru_hole", drill=1.0, shape="oval"),
        PadDef("2", -3.25, 2.25, 2.0, 1.3, ptype="thru_hole", drill=1.0, shape="oval"),
        PadDef("2", 3.25, 2.25, 2.0, 1.3, ptype="thru_hole", drill=1.0, shape="oval"),
    ]
    return FootprintDef(
        key=key, pads=pads, attr="through_hole",
        courtyard=(-4.6, -3.4, 4.6, 3.4),
        silk=[(-3.0, -3.0, 3.0, -3.0), (-3.0, 3.0, 3.0, 3.0)],
        description="Tactile switch 6x6mm THT",
    )


def _terminal(key: str, n: int) -> FootprintDef:
    pads = []
    x0 = -((n - 1) * 5.0) / 2
    for i in range(n):
        pads.append(PadDef(str(i + 1), x0 + i * 5.0, 0, 2.6, 2.6,
                           shape="rect" if i == 0 else "circle", ptype="thru_hole", drill=1.3))
    cx = (n - 1) * 5.0 / 2 + 3.0
    return FootprintDef(
        key=key, pads=pads, attr="through_hole",
        courtyard=(-cx, -4.4, cx, 4.4),
        silk=[(-cx + 0.4, -4.0, cx - 0.4, -4.0), (-cx + 0.4, 4.0, cx - 0.4, 4.0),
              (-cx + 0.4, -4.0, -cx + 0.4, 4.0), (cx - 0.4, -4.0, cx - 0.4, 4.0)],
        description=f"Screw terminal {n}P, 5.0mm pitch",
    )


def _crystal_3225(key: str = "Crystal_3225") -> FootprintDef:
    pads = [
        PadDef("1", -1.1, 0.85, 1.4, 1.2),
        PadDef("2", 1.1, 0.85, 1.4, 1.2),
        PadDef("3", 1.1, -0.85, 1.4, 1.2),
        PadDef("4", -1.1, -0.85, 1.4, 1.2),
    ]
    return FootprintDef(key=key, pads=pads, attr="smd",
                        courtyard=(-2.1, -1.75, 2.1, 1.75),
                        silk=[(-1.6, -1.35, -0.5, -1.35)],
                        description="Crystal SMD 3.2x2.5mm 4-pad")


def _usb_c(key: str = "USB_C_16P") -> FootprintDef:
    """Simplified USB-C 16-pin receptacle (HRO TYPE-C-31-M-12 style)."""
    names = ["A1", "A4", "B8", "A5", "B7", "A6", "A7", "B5", "A8", "B4", "B1"]
    xs = [-3.2, -2.4, -1.6, -0.8, -0.35, 0.35, 0.8, 1.6, 2.4, 3.2]
    pads: list[PadDef] = []
    # Signal pads (0.5 pitch region simplified to 10 pads used by 2.0 designs)
    sig = [("A1B12", -3.2), ("A4B9", -2.4), ("B8", -1.75), ("A5", -1.25),
           ("B7", -0.75), ("A6", -0.25), ("A7", 0.25), ("B6", 0.75),
           ("A8", 1.25), ("B5", 1.75), ("B4A9", 2.4), ("B1A12", 3.2)]
    for name, x in sig:
        w = 0.6 if len(name) > 3 else 0.3
        pads.append(PadDef(name, x, -4.0, w, 1.1))
    # Shell mounting holes.
    for i, (x, y) in enumerate([(-4.32, -3.6), (4.32, -3.6), (-4.32, 0.65), (4.32, 0.65)]):
        pads.append(PadDef("S1", x, y, 1.0, 1.8, shape="oval", ptype="thru_hole", drill=0.6))
    return FootprintDef(key=key, pads=pads, attr="smd",
                        courtyard=(-5.4, -5.1, 5.4, 4.2),
                        silk=[(-4.7, 3.5, 4.7, 3.5)],
                        description="USB Type-C 16P receptacle (USB2.0 subset), place at board edge")


# --------------------------------------------------------------------------
# Library assembly
# --------------------------------------------------------------------------

P = "passive"
I = "input"
O = "output"
B = "bidirectional"
PI = "power_in"
PO = "power_out"

SYMBOLS: dict[str, SymbolDef] = {}
FOOTPRINTS: dict[str, FootprintDef] = {}
# part key -> (symbol key, default footprint key, description)
PARTS: dict[str, dict] = {}


def _reg(sym: SymbolDef, fp_key: str, alt_fps: list[str] | None = None):
    SYMBOLS[sym.key] = sym
    PARTS[sym.key] = {
        "symbol": sym.key,
        "footprint": fp_key,
        "alt_footprints": alt_fps or [],
        "ref_prefix": sym.ref_prefix,
        "description": sym.description,
        "pins": [{"number": p.number, "name": p.name} for p in sym.pins],
    }


# ---- footprints ----
for k, bl, bw, pl, pw, pt in [
    ("R_0402", 1.0, 0.5, 0.6, 0.6, 1.0), ("R_0603", 1.6, 0.8, 0.9, 0.95, 1.65),
    ("R_0805", 2.0, 1.25, 1.0, 1.45, 1.9), ("R_1206", 3.2, 1.6, 1.1, 1.8, 2.9),
    ("C_0402", 1.0, 0.5, 0.6, 0.6, 1.0), ("C_0603", 1.6, 0.8, 0.9, 0.95, 1.65),
    ("C_0805", 2.0, 1.25, 1.0, 1.45, 1.9), ("C_1206", 3.2, 1.6, 1.1, 1.8, 2.9),
    ("L_0603", 1.6, 0.8, 0.9, 0.95, 1.65), ("L_0805", 2.0, 1.25, 1.0, 1.45, 1.9),
    ("D_0805", 2.0, 1.25, 1.0, 1.45, 1.9), ("LED_0805", 2.0, 1.25, 1.0, 1.45, 1.9),
    ("LED_0603", 1.6, 0.8, 0.9, 0.95, 1.65),
]:
    FOOTPRINTS[k] = _chip(k, bl, bw, pl, pw, pt, f"Chip {k}")

FOOTPRINTS["D_SMA"] = _chip("D_SMA", 4.3, 2.6, 1.5, 1.8, 4.0, "Diode SMA (DO-214AC)")
FOOTPRINTS["CP_Elec_6.3x7.7"] = _chip("CP_Elec_6.3x7.7", 6.6, 6.6, 2.2, 1.6, 5.6,
                                      "Electrolytic SMD 6.3mm")
FOOTPRINTS["SOT-23"] = _sot23()
FOOTPRINTS["SOT-223"] = _sot223()
FOOTPRINTS["TO-220-3"] = _to220()
FOOTPRINTS["SOIC-8"] = _dual_row("SOIC-8", 8, 1.27, 5.4, 1.55, 0.6, 3.9, 4.9, desc="SOIC-8 3.9x4.9mm")
FOOTPRINTS["SOIC-14"] = _dual_row("SOIC-14", 14, 1.27, 5.4, 1.55, 0.6, 3.9, 8.7, desc="SOIC-14")
FOOTPRINTS["DIP-8"] = _dual_row("DIP-8", 8, 2.54, 7.62, 1.6, 1.6, 6.35, 9.6,
                                attr="through_hole", drill=0.8, desc="DIP-8")
FOOTPRINTS["DIP-14"] = _dual_row("DIP-14", 14, 2.54, 7.62, 1.6, 1.6, 6.35, 19.0,
                                 attr="through_hole", drill=0.8, desc="DIP-14")
FOOTPRINTS["TQFP-32"] = _quad("TQFP-32", 32, 0.8, 8.4, 0.55, 1.5, 7.0, "TQFP-32 7x7mm 0.8p")
FOOTPRINTS["LQFP-48"] = _quad("LQFP-48", 48, 0.5, 8.4, 0.3, 1.5, 7.0, "LQFP-48 7x7mm 0.5p")
FOOTPRINTS["ESP32-WROOM-32"] = _esp32_wroom()
FOOTPRINTS["SW_PUSH_6mm"] = _tact_switch()
FOOTPRINTS["Crystal_3225"] = _crystal_3225()
FOOTPRINTS["USB_C_16P"] = _usb_c()
for n in range(2, 11):
    FOOTPRINTS[f"PinHeader_1x{n:02d}"] = _header(f"PinHeader_1x{n:02d}", n,
                                                 f"Pin header 1x{n} 2.54mm THT")
for n in (2, 3, 4):
    FOOTPRINTS[f"Terminal_{n}P"] = _terminal(f"Terminal_{n}P", n)

# RJ45 connector footprint
FOOTPRINTS["RJ45"] = FootprintDef(key="RJ45", pads=[
    PadDef("1", -3.81, -6.35, 1.0, 1.5, shape="rect", ptype="thru_hole", drill=0.6),
    PadDef("2", -1.27, -6.35, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("3", 1.27, -6.35, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("4", 3.81, -6.35, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("5", -3.81, -3.81, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("6", -1.27, -3.81, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("7", 1.27, -3.81, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("8", 3.81, -3.81, 1.0, 1.5, ptype="thru_hole", drill=0.6),
    PadDef("S1", -6.6, 0, 1.5, 2.5, shape="oval", ptype="thru_hole", drill=1.0),
    PadDef("S2", 6.6, 0, 1.5, 2.5, shape="oval", ptype="thru_hole", drill=1.0),
], attr="through_hole", courtyard=(-8, -8, 8, 8), description="RJ45 8P8C with shield")

# Nano SIM holder footprint
FOOTPRINTS["SIM_NANO"] = FootprintDef(key="SIM_NANO", pads=[
    PadDef("C1", -2.54, 3.5, 1.0, 1.0, shape="rect", ptype="thru_hole", drill=0.6),
    PadDef("C2", 0, 3.5, 1.0, 1.0, ptype="thru_hole", drill=0.6),
    PadDef("C3", 2.54, 3.5, 1.0, 1.0, ptype="thru_hole", drill=0.6),
    PadDef("C5", -2.54, -3.5, 1.0, 1.0, ptype="thru_hole", drill=0.6),
    PadDef("C6", 0, -3.5, 1.0, 1.0, ptype="thru_hole", drill=0.6),
    PadDef("C7", 2.54, -3.5, 1.0, 1.0, ptype="thru_hole", drill=0.6),
    PadDef("GND1", -5.5, 0, 1.5, 2.0, shape="oval", ptype="thru_hole", drill=1.0),
    PadDef("GND2", 5.5, 0, 1.5, 2.0, shape="oval", ptype="thru_hole", drill=1.0),
], attr="through_hole", courtyard=(-7, -5.5, 7, 5.5), description="Nano SIM card holder")

# 4G module placeholder (Quectel EC200U-CN style)
FOOTPRINTS["MODULE_4G"] = FootprintDef(key="MODULE_4G", pads=[
    PadDef("1", -11.0, -4.0, 2.0, 1.0, shape="rect"),
    PadDef("2", -11.0, -2.0, 2.0, 1.0),
    PadDef("3", -11.0, 0.0, 2.0, 1.0),
    PadDef("4", -11.0, 2.0, 2.0, 1.0),
    PadDef("5", -11.0, 4.0, 2.0, 1.0),
    PadDef("6", 11.0, -4.0, 2.0, 1.0),
    PadDef("7", 11.0, -2.0, 2.0, 1.0),
    PadDef("8", 11.0, 0.0, 2.0, 1.0),
    PadDef("9", 11.0, 2.0, 2.0, 1.0),
    PadDef("10", 11.0, 4.0, 2.0, 1.0),
], attr="smd", courtyard=(-13, -6, 13, 6), description="4G module placeholder")

# ---- passives ----
_reg(_two_lead("R", "R", "resistor", "Resistor"), "R_0603",
     ["R_0402", "R_0805", "R_1206"])
_reg(_two_lead("C", "C", "capacitor", "Ceramic capacitor"), "C_0603",
     ["C_0402", "C_0805", "C_1206"])
_reg(_two_lead("C_POL", "C", "capacitor_pol", "Polarized capacitor (pin 1 = +)"),
     "CP_Elec_6.3x7.7", ["C_0805", "C_1206"])
_reg(_two_lead("L", "L", "inductor", "Inductor"), "L_0603", ["L_0805"])
_reg(_two_lead("D", "D", "diode", "Diode (pin 1 = K, pin 2 = A)"), "D_SMA", ["D_0805"])
_reg(_two_lead("D_SCHOTTKY", "D", "diode", "Schottky diode (pin 1 = K, pin 2 = A)"),
     "D_SMA", ["D_0805"])
_reg(_two_lead("D_ZENER", "D", "diode", "Zener diode (pin 1 = K, pin 2 = A)"),
     "D_SMA", ["D_0805"])
_reg(_two_lead("LED", "D", "led", "LED (pin 1 = K, pin 2 = A)"), "LED_0805", ["LED_0603"])

# ---- transistors ----
_reg(_box("Q_NPN", "Q", left=[("1", "B", I)], right=[("3", "C", P), ("2", "E", P)],
          desc="NPN BJT SOT-23 (1=B 2=E 3=C, e.g. BC847/MMBT2222)", min_w=7.62),
     "SOT-23")
_reg(_box("Q_PNP", "Q", left=[("1", "B", I)], right=[("3", "C", P), ("2", "E", P)],
          desc="PNP BJT SOT-23 (1=B 2=E 3=C, e.g. BC857)", min_w=7.62),
     "SOT-23")
_reg(_box("Q_NMOS", "Q", left=[("1", "G", I)], right=[("3", "D", P), ("2", "S", P)],
          desc="N-MOSFET SOT-23 (1=G 2=S 3=D, e.g. AO3400)", min_w=7.62),
     "SOT-23")
_reg(_box("Q_PMOS", "Q", left=[("1", "G", I)], right=[("3", "D", P), ("2", "S", P)],
          desc="P-MOSFET SOT-23 (1=G 2=S 3=D, e.g. AO3401)", min_w=7.62),
     "SOT-23")

# ---- regulators / analog ICs ----
_reg(_box("LM2577", "U",
          left=[("1", "VIN", PI), ("4", "GND", PI), ("5", "GND", PI), ("2", "ON/OFF", I)],
          right=[("3", "SW", O), ("6", "FB", I), ("7", "NC", "no_connect")],
          desc="Step-up switching regulator, SOIC-8"),
     "SOIC-8")
_reg(_box("AMS1117-3.3", "U",
          left=[("3", "VIN", PI)], right=[("2", "VOUT", PO)], bottom=[("1", "GND", PI)],
          desc="LDO 3.3V 1A, SOT-223 (with tab=VOUT pad 4)"),
     "SOT-223")
_reg(_box("AMS1117-5.0", "U",
          left=[("3", "VIN", PI)], right=[("2", "VOUT", PO)], bottom=[("1", "GND", PI)],
          desc="LDO 5.0V 1A, SOT-223"),
     "SOT-223")
_reg(_box("LM7805", "U",
          left=[("1", "VIN", PI)], right=[("3", "VOUT", PO)], bottom=[("2", "GND", PI)],
          desc="Linear regulator 5V 1.5A, TO-220"),
     "TO-220-3")
_reg(_box("LM358", "U",
          left=[("3", "IN1+", I), ("2", "IN1-", I), ("5", "IN2+", I), ("6", "IN2-", I)],
          right=[("1", "OUT1", O), ("7", "OUT2", O)],
          top=[("8", "V+", PI)], bottom=[("4", "V-", PI)],
          desc="Dual op-amp, SOIC-8/DIP-8"),
     "SOIC-8", ["DIP-8"])
_reg(_box("NE555", "U",
          left=[("2", "TRIG", I), ("6", "THRES", I), ("4", "~RESET", I), ("5", "CTRL", I)],
          right=[("3", "OUT", O), ("7", "DISCH", O)],
          top=[("8", "VCC", PI)], bottom=[("1", "GND", PI)],
          desc="555 timer, SOIC-8/DIP-8"),
     "SOIC-8", ["DIP-8"])

# ---- MCUs / modules ----
_reg(_box("ESP32-WROOM-32", "U",
          left=[("3", "EN", I), ("4", "IO36/SVP", I), ("5", "IO39/SVN", I),
                ("6", "IO34", I), ("7", "IO35", I), ("8", "IO32", B), ("9", "IO33", B),
                ("10", "IO25", B), ("11", "IO26", B), ("12", "IO27", B),
                ("13", "IO14", B), ("14", "IO12", B), ("16", "IO13", B),
                ("23", "IO15", B)],
          right=[("37", "IO23", B), ("36", "IO22", B), ("35", "TXD0/IO1", O),
                 ("34", "RXD0/IO3", I), ("33", "IO21", B), ("30", "IO18", B),
                 ("31", "IO19", B), ("29", "IO5", B), ("28", "IO17", B),
                 ("27", "IO16", B), ("26", "IO4", B), ("24", "IO2", B),
                 ("25", "IO0", B)],
          top=[("2", "3V3", PI)],
          bottom=[("1", "GND", PI), ("15", "GND", PI), ("38", "GND", PI), ("39", "GND", PI)],
          desc="ESP32-WROOM-32 WiFi/BT module (flash pins 17-22 omitted)"),
     "ESP32-WROOM-32")
_reg(_box("ATMEGA328P-AU", "U",
          left=[("29", "~RESET/PC6", I), ("7", "XTAL1/PB6", I), ("8", "XTAL2/PB7", I),
                ("23", "PC0/A0", B), ("24", "PC1/A1", B), ("25", "PC2/A2", B),
                ("26", "PC3/A3", B), ("27", "PC4/SDA", B), ("28", "PC5/SCL", B),
                ("19", "ADC6", I), ("22", "ADC7", I)],
          right=[("30", "PD0/RXD", B), ("31", "PD1/TXD", B), ("32", "PD2", B),
                 ("1", "PD3", B), ("2", "PD4", B), ("9", "PD5", B), ("10", "PD6", B),
                 ("11", "PD7", B), ("12", "PB0", B), ("13", "PB1", B), ("14", "PB2/~SS", B),
                 ("15", "PB3/MOSI", B), ("16", "PB4/MISO", B), ("17", "PB5/SCK", B)],
          top=[("4", "VCC", PI), ("6", "AVCC", PI), ("18", "AREF", I)],
          bottom=[("3", "GND", PI), ("5", "GND", PI), ("21", "GND", PI)],
          desc="ATmega328P TQFP-32 (Arduino Uno MCU)"),
     "TQFP-32")
_reg(_box("STM32F103C8", "U",
          left=[("7", "NRST", I), ("44", "BOOT0", I), ("5", "PD0/OSC_IN", I),
                ("6", "PD1/OSC_OUT", O),
                ("10", "PA0", B), ("11", "PA1", B), ("12", "PA2", B), ("13", "PA3", B),
                ("14", "PA4", B), ("15", "PA5", B), ("16", "PA6", B), ("17", "PA7", B),
                ("29", "PA8", B), ("30", "PA9/TX", B), ("31", "PA10/RX", B),
                ("32", "PA11/USB_DM", B), ("33", "PA12/USB_DP", B),
                ("34", "PA13/SWDIO", B), ("37", "PA14/SWCLK", B), ("38", "PA15", B)],
          right=[("18", "PB0", B), ("19", "PB1", B), ("20", "PB2/BOOT1", B),
                 ("39", "PB3", B), ("40", "PB4", B), ("41", "PB5", B), ("42", "PB6", B),
                 ("43", "PB7", B), ("45", "PB8", B), ("46", "PB9", B),
                 ("21", "PB10", B), ("22", "PB11", B), ("25", "PB12", B),
                 ("26", "PB13", B), ("27", "PB14", B), ("28", "PB15", B),
                 ("2", "PC13", B), ("3", "PC14", B), ("4", "PC15", B)],
          top=[("1", "VBAT", PI), ("24", "VDD1", PI), ("36", "VDD2", PI),
               ("48", "VDD3", PI), ("9", "VDDA", PI)],
          bottom=[("23", "VSS1", PI), ("35", "VSS2", PI), ("47", "VSS3", PI),
                  ("8", "VSSA", PI)],
          desc="STM32F103C8T6 LQFP-48 (Blue Pill MCU)"),
     "LQFP-48")

# ---- connectors & misc ----
for n in range(2, 11):
    _reg(_box(f"CONN_1x{n:02d}", "J",
              left=[(str(i + 1), f"P{i + 1}", P) for i in range(n)], right=[],
              desc=f"Pin header 1x{n}", min_w=5.08),
         f"PinHeader_1x{n:02d}")
for n in (2, 3, 4):
    _reg(_box(f"TERMINAL_{n}P", "J",
              left=[(str(i + 1), f"P{i + 1}", P) for i in range(n)], right=[],
              desc=f"Screw terminal {n}P", min_w=5.08),
         f"Terminal_{n}P")
_reg(_box("USB_C", "J",
          right=[("A1B12", "GND", PI), ("A4B9", "VBUS", PO),
                 ("A5", "CC1", B), ("B5", "CC2", B),
                 ("A6", "D+", B), ("A7", "D-", B),
                 ("B6", "D+2", B), ("B7", "D-2", B),
                 ("A8", "SBU1", B), ("B8", "SBU2", B),
                 ("B4A9", "VBUS2", PO), ("B1A12", "GND2", PI),
                 ("S1", "SHIELD", P)],
          desc="USB Type-C receptacle (USB 2.0). Place at board edge."),
     "USB_C_16P")
_reg(_box("SW_PUSH", "SW", left=[("1", "1", P)], right=[("2", "2", P)],
          desc="Momentary push button", min_w=7.62),
     "SW_PUSH_6mm")
_reg(_box("CRYSTAL_4P", "Y", left=[("1", "XIN", P)], right=[("3", "XOUT", P)],
          bottom=[("2", "GND", PI), ("4", "GND2", PI)],
          desc="Crystal SMD 3225 4-pad", min_w=7.62),
     "Crystal_3225")
_reg(_two_lead("CRYSTAL", "Y", "crystal", "Crystal 2-pin"), "Crystal_3225")
_reg(_two_lead("BUZZER", "BZ", "buzzer", "Buzzer (pin 1 = +)"), "CP_Elec_6.3x7.7")

# ---- Industrial controller parts ----

# LQFP-100 footprint (100 pins, 0.5mm pitch, 14x14mm body)
_lqfp100_pads = []
for i in range(25):
    _lqfp100_pads.append(PadDef(str(i+1), -8.5, 6.0-i*0.5, 1.5, 0.25))
for i in range(25):
    _lqfp100_pads.append(PadDef(str(i+26), -6.0+i*0.5, 8.5, 0.25, 1.5))
for i in range(25):
    _lqfp100_pads.append(PadDef(str(i+51), 8.5, -6.0+i*0.5, 1.5, 0.25))
for i in range(25):
    _lqfp100_pads.append(PadDef(str(i+76), 6.0-i*0.5, -8.5, 0.25, 1.5))
FOOTPRINTS["LQFP-100"] = FootprintDef(key="LQFP-100", pads=_lqfp100_pads, attr="smd",
    courtyard=(-9.5, -9.5, 9.5, 9.5), description="LQFP-100 14x14mm 0.5mm pitch")

# QFN-24 footprint (24 pins + exposed pad, 4x4mm body)
_qfn24_pads = []
for i in range(6):
    _qfn24_pads.append(PadDef(str(i+1), -2.25, 1.25-i*0.5, 0.28, 0.28))
for i in range(6):
    _qfn24_pads.append(PadDef(str(i+7), -1.25+i*0.5, 2.25, 0.28, 0.28))
for i in range(6):
    _qfn24_pads.append(PadDef(str(i+13), 2.25, -1.25+i*0.5, 0.28, 0.28))
for i in range(6):
    _qfn24_pads.append(PadDef(str(i+19), 1.25-i*0.5, -2.25, 0.28, 0.28))
_qfn24_pads.append(PadDef("25", 0, 0, 1.5, 1.5, shape="rect"))
FOOTPRINTS["QFN-24"] = FootprintDef(key="QFN-24", pads=_qfn24_pads, attr="smd",
    courtyard=(-3, -3, 3, 3), description="QFN-24 4x4mm 0.5mm pitch")

# DIP-4 footprint (optocoupler)
FOOTPRINTS["DIP-4"] = FootprintDef(key="DIP-4", pads=[
    PadDef("1", -3.81, -1.27, 1.5, 1.5, shape="rect", ptype="thru_hole", drill=0.8),
    PadDef("2", -3.81, 1.27, 1.5, 1.5, shape="rect", ptype="thru_hole", drill=0.8),
    PadDef("3", 3.81, 1.27, 1.5, 1.5, shape="rect", ptype="thru_hole", drill=0.8),
    PadDef("4", 3.81, -1.27, 1.5, 1.5, shape="rect", ptype="thru_hole", drill=0.8),
], attr="through_hole", courtyard=(-5, -3, 5, 3), description="DIP-4 optocoupler")

# Relay footprint (5 pins)
FOOTPRINTS["Relay"] = FootprintDef(key="Relay", pads=[
    PadDef("1", -5, -2.5, 2, 2, shape="rect", ptype="thru_hole", drill=1.0),
    PadDef("2", -5, 2.5, 2, 2, shape="rect", ptype="thru_hole", drill=1.0),
    PadDef("3", 5, -5, 2, 2, shape="rect", ptype="thru_hole", drill=1.0),
    PadDef("4", 5, 0, 2, 2, shape="rect", ptype="thru_hole", drill=1.0),
    PadDef("5", 5, 5, 2, 2, shape="rect", ptype="thru_hole", drill=1.0),
], attr="through_hole", courtyard=(-8, -8, 8, 8), description="5-pin relay DPST")


# RJ45 connector (8P8C) - simplified signal set
_reg(_box("RJ45", "J",
    left=[("1","TX+",B),("2","TX-",B),("3","RX+",B),("6","RX-",B)],
    right=[("4","NC1",P),("5","NC2",P),("7","NC3",P),("8","NC4",P),
           ("S1","SHIELD",P),("S2","SHIELD2",P)],
    desc="RJ45 8P8C Ethernet connector"), "RJ45")

# Nano SIM holder
_reg(_box("SIM_NANO", "J",
    left=[("C1","VCC",PI),("C2","RST",I),("C3","CLK",I)],
    right=[("C5","VPP",P),("C6","I/O",B),("C7","GND",PI)],
    desc="Nano SIM card holder"), "SIM_NANO")

# 4G module placeholder
_reg(_box("MODULE_4G", "U",
    left=[("1","VCC",PI),("2","GND",PI),("3","TX",I),("4","RX",O),("5","PWRKEY",I)],
    right=[("6","ANT",P),("7","STATUS",O),("8","NETLIGHT",O),("9","DTR",I),("10","RTS",I)],
    desc="4G LTE module placeholder (e.g. Quectel EC200U)"), "MODULE_4G")

# STM32F407VGT6 LQFP-100
_reg(_box("STM32F407", "U",
    left=[("19","PA0",I),("20","PA1",I),("21","PA2",B),("22","PA3",I),
          ("23","PA4",B),("24","PA5",I),("26","PA7",I),
          ("14","PC1",B),("27","PC4",I),("28","PC5",I),
          ("33","PB11",O),("37","PB12",O),("38","PB13",O),
          ("46","PA9/TX1",O),("47","PA10/RX1",I),
          ("61","PD5/TX2",O),("62","PD6/RX2",I),
          ("48","PA11/USB-",B),("49","PA12/USB+",B),
          ("52","PA13/SWDIO",B),("53","PA14/SWCLK",I),
          ("12","NRST",I)],
    right=[("69","BOOT0",I),("74","PE0",O),("75","PE1",O),("76","PE2",O),
           ("77","PE3",O),("78","PE4",O),("79","PE5",O),
           ("80","PE7",B),("82","PE8",B),("83","PE9",B),("84","PE10",O),
           ("67","PB6/SCL",B),("68","PB7/SDA",B),
           ("54","PA15/NSS",B),("64","PB3/SCK",B),
           ("65","PB4/MISO",B),("66","PB5/MOSI",B)],
    top=[("6","VBAT",PI),("18","VDDA",PI),("36","VDD1",PI),
         ("51","VDD2",PI),("73","VDD3",PI),("94","VDD4",PI)],
    bottom=[("17","VSSA",PI),("35","VSS1",PI),("50","VSS2",PI),
            ("72","VSS3",PI),("93","VSS4",PI),("99","VSS5",PI),
            ("10","OSC_IN",I),("11","OSC_OUT",O)],
    desc="STM32F407VGT6 LQFP-100 ARM Cortex-M4 168MHz"), "LQFP-100")

# LAN8720A Ethernet PHY QFN-24
_reg(_box("LAN8720", "U",
    left=[("1","RXD0",I),("2","RXD1",I),("3","CRS_DV",I),
          ("4","MDC",B),("5","MDIO",B),("6","REFCLK",I)],
    right=[("11","TXD0",O),("12","TXD1",O),("13","TX_EN",O)],
    top=[("24","VDDIO",PI),("23","VDDA",PI)],
    bottom=[("18","GND1",PI),("17","GND2",PI)],
    desc="LAN8720A Ethernet PHY QFN-24"), "QFN-24")

# THVD2450 RS485 transceiver SOIC-8
_reg(_box("THVD2450", "U",
    left=[("1","RO",O),("2","RE",I),("3","DE",I),("4","DI",I)],
    right=[("6","Y",O),("7","Z",O)],
    top=[("5","VCC",PI)], bottom=[("8","GND",PI)],
    desc="THVD2450 RS485 transceiver SOIC-8"), "SOIC-8")

# DS3231 RTC SOIC-8
_reg(_box("DS3231", "U",
    left=[("3","32K",O),("4","SQW",O),("5","SCL",B),("6","SDA",B)],
    right=[],
    top=[("2","VCC",PI)], bottom=[("1","GND",PI)],
    desc="DS3231 RTC SOIC-8"), "SOIC-8")

# 24LC256 EEPROM SOIC-8
_reg(_box("24LC256", "U",
    left=[("1","A0",I),("2","A1",I),("3","A2",I),("4","VSS",PI)],
    right=[("8","VCC",PI),("7","WP",I),("6","SCL",B),("5","SDA",B)],
    desc="24LC256 EEPROM SOIC-8"), "SOIC-8")

# PC817 Optocoupler DIP-4
_reg(_box("PC817", "U",
    left=[("1","A",I),("2","K",P)],
    right=[("4","C",O),("3","E",PI)],
    desc="PC817 optocoupler DIP-4"), "DIP-4")

# Relay 5-pin DPST

_reg(_box("PWR_FLAG", "#FLG",
    left=[],
    right=[("1","",PO)],
    desc="Power flag"), "PWR_FLAG")
FOOTPRINTS["PWR_FLAG"] = FootprintDef(key="PWR_FLAG", pads=[
    PadDef("1", 0, 0, 0.001, 0.001, shape="rect", ptype="smd")
], attr="virtual", courtyard=(-0.1,-0.1,0.1,0.1), description="Power flag")

_reg(_box("Battery", "BT",
    left=[("1","+",PI),("2","-",PI)],
    desc="Coin cell battery holder"), "Battery")
FOOTPRINTS["Battery"] = FootprintDef(key="Battery", pads=[
    PadDef("1", -2.54, 0, 1.5, 1.5, shape="roundrect", ptype="thru_hole", drill=0.8),
    PadDef("2", 2.54, 0, 1.5, 1.5, shape="oval", ptype="thru_hole", drill=0.8),
], attr="through_hole", courtyard=(-5, -3, 5, 3), description="CR1220 battery holder")

_reg(_box("RELAY", "K",
    left=[("1","COIL+","passive"),("2","COIL-","passive")],
    right=[("3","COM","passive"),("4","NO","passive"),("5","NC","passive")],
    desc="5-pin relay DPST"), "Relay")


def get_part(part_key: str) -> dict:
    if part_key not in PARTS:
        close = [k for k in PARTS if part_key.upper() in k or k in part_key.upper()]
        hint = f" Did you mean: {', '.join(close[:5])}?" if close else ""
        raise ValueError(
            f"Unknown part '{part_key}'.{hint} Call list_library to see all available parts."
        )
    return PARTS[part_key]


def get_symbol(part_key: str) -> SymbolDef:
    return SYMBOLS[get_part(part_key)["symbol"]]


def get_footprint(fp_key: str) -> FootprintDef:
    if fp_key not in FOOTPRINTS:
        raise ValueError(f"Unknown footprint '{fp_key}'. Call list_library to see options.")
    return FOOTPRINTS[fp_key]


def resolve_footprint(comp_part: str, comp_fp: str) -> FootprintDef:
    if comp_fp:
        return get_footprint(comp_fp)
    return get_footprint(get_part(comp_part)["footprint"])
