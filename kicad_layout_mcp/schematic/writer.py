"""Writes a KiCad 8/9-compatible .kicad_sch file (format 20231120)."""
from __future__ import annotations

import os

from ..core.circuit import Circuit
from ..core.sexpr import Sym, new_uuid, dumps
from ..library.parts import SymbolDef, get_part, get_symbol, resolve_footprint
from .labeler import PlacedText, place_text
from .placer import SchematicLayout
from .router import SchRouting

FONT = ["font", ["size", 1.27, 1.27]]


def _effects(justify: list | None = None, hide: bool = False):
    e = ["effects", list(FONT)]
    if justify:
        e.append(["justify"] + [Sym(j) for j in justify])
    if hide:
        e.append(Sym("hide"))
    return e


def _stroke(width: float = 0.0, stype: str = "default"):
    return ["stroke", ["width", width], ["type", Sym(stype)]]


# ---------------------------------------------------------------------------
# Library symbol S-expressions
# ---------------------------------------------------------------------------

def _lib_symbol(sym: SymbolDef, lib: str = "kmcp"):
    name = f"{lib}:{sym.key}"
    hw, hh = sym.body_w / 2, sym.body_h / 2
    body = ["symbol", f"{sym.key}_0_1",
            ["rectangle", ["start", -hw, hh], ["end", hw, -hh],
             _stroke(0.254), ["fill", ["type", Sym("background")]]]]
    pins = ["symbol", f"{sym.key}_1_1"]
    for p in sym.pins:
        px, py = sym.pin_pos(p)      # model: y down
        ly = -py                     # library: y up
        if p.side == "left":
            angle = 0
        elif p.side == "right":
            angle = 180
        elif p.side == "top":
            angle = 270
        else:
            angle = 90
        et = p.etype if p.etype != "no_connect" else "no_connect"
        pins.append([
            "pin", Sym(et), Sym("line"), ["at", px, ly, angle], ["length", sym.pin_len],
            ["name", p.name, _effects()],
            ["number", p.number, _effects()],
        ])
    out = ["symbol", name]
    if not sym.show_pin_numbers:
        out.append(["pin_numbers", Sym("hide")])
    out.append(["pin_names", ["offset", 0.508 if sym.show_pin_names else 0]]
               if sym.show_pin_names else ["pin_names", ["offset", 0], Sym("hide")])
    out += [
        ["exclude_from_sim", Sym("no")], ["in_bom", Sym("yes")], ["on_board", Sym("yes")],
        ["property", "Reference", sym.ref_prefix, ["at", 0, hh + 1.27, 0], _effects()],
        ["property", "Value", sym.key, ["at", 0, -hh - 1.27, 0], _effects()],
        ["property", "Footprint", "", ["at", 0, 0, 0], _effects(hide=True)],
        ["property", "Datasheet", "~", ["at", 0, 0, 0], _effects(hide=True)],
        ["property", "Description", sym.description, ["at", 0, 0, 0], _effects(hide=True)],
        body, pins,
    ]
    return out


def _power_lib_symbol(net: str, down: bool, lib: str = "kmcp_power"):
    name = f"{lib}:{net}"
    if down:  # GND family: bars below origin (library y-up: negative)
        gfx = ["symbol", f"{net}_0_1",
               ["polyline", ["pts", ["xy", 0, 0], ["xy", 0, -1.016]], _stroke(0.254), ["fill", ["type", Sym("none")]]],
               ["polyline", ["pts", ["xy", -1.27, -1.016], ["xy", 1.27, -1.016]], _stroke(0.254), ["fill", ["type", Sym("none")]]],
               ["polyline", ["pts", ["xy", -0.762, -1.524], ["xy", 0.762, -1.524]], _stroke(0.254), ["fill", ["type", Sym("none")]]],
               ["polyline", ["pts", ["xy", -0.254, -2.032], ["xy", 0.254, -2.032]], _stroke(0.254), ["fill", ["type", Sym("none")]]]]
        val_at = ["at", 0, -3.556, 0]
    else:     # rail: stem + bar above origin
        gfx = ["symbol", f"{net}_0_1",
               ["polyline", ["pts", ["xy", 0, 0], ["xy", 0, 1.27]], _stroke(0.254), ["fill", ["type", Sym("none")]]],
               ["polyline", ["pts", ["xy", -1.016, 1.27], ["xy", 1.016, 1.27]], _stroke(0.254), ["fill", ["type", Sym("none")]]]]
        val_at = ["at", 0, 2.794, 0]
    pin = ["symbol", f"{net}_1_1",
           ["pin", Sym("power_in"), Sym("line"), ["at", 0, 0, 90 if not down else 270],
            ["length", 0],
            ["name", net, _effects()],
            ["number", "1", _effects()]]]
    return ["symbol", name, ["power"], ["pin_numbers", Sym("hide")],
            ["pin_names", ["offset", 0], Sym("hide")],
            ["exclude_from_sim", Sym("yes")], ["in_bom", Sym("no")], ["on_board", Sym("yes")],
            ["property", "Reference", "#PWR", ["at", 0, 0, 0], _effects(hide=True)],
            ["property", "Value", net, val_at, _effects()],
            ["property", "Footprint", "", ["at", 0, 0, 0], _effects(hide=True)],
            ["property", "Datasheet", "", ["at", 0, 0, 0], _effects(hide=True)],
            ["property", "Description", f"Power symbol {net}", ["at", 0, 0, 0], _effects(hide=True)],
            gfx, pin]


# ---------------------------------------------------------------------------
# Top-level schematic
# ---------------------------------------------------------------------------

def write_schematic(circuit: Circuit, layout: SchematicLayout, routing: SchRouting,
                    path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    root_uuid = new_uuid()
    project = circuit.name

    # lib_symbols: every distinct part + every power net used.
    used_parts: dict[str, SymbolDef] = {}
    for comp in circuit.components.values():
        sym = get_symbol(comp.part)
        used_parts[sym.key] = sym
    lib_symbols = ["lib_symbols"] + [_lib_symbol(s) for s in used_parts.values()]
    power_nets: dict[str, bool] = {}
    for pp in routing.power_pins:
        power_nets[pp.net] = pp.down
    lib_symbols += [_power_lib_symbol(n, d) for n, d in sorted(power_nets.items())]

    doc = ["kicad_sch",
           ["version", 20231120],
           ["generator", "kicad_layout_mcp"],
           ["generator_version", "9.99"],
           ["uuid", root_uuid],
           ["paper", getattr(layout, "paper", "A3")],
           lib_symbols]

    # Text placement for reference/value.
    values = {r: c.value or c.part for r, c in circuit.components.items()}
    texts = place_text(layout, routing, values)

    # Component instances.
    for ref, ps in layout.placed.items():
        comp = circuit.components[ref]
        sym = ps.symbol
        fp = resolve_footprint(comp.part, comp.footprint)
        props = []
        placed_texts = {t.kind: t for t in texts.get(ref, [])}
        for kind, value in (("Reference", ref), ("Value", values[ref])):
            t = placed_texts.get(kind.lower())
            if t:
                props.append(["property", kind, value, ["at", t.x, t.y, 0],
                              _effects(justify=["left"])])
            else:
                props.append(["property", kind, value, ["at", ps.x, ps.y, 0],
                              _effects(hide=True)])
        props.append(["property", "Footprint", f"kmcp:{fp.key}", ["at", ps.x, ps.y, 0],
                      _effects(hide=True)])
        props.append(["property", "Datasheet", "~", ["at", ps.x, ps.y, 0],
                      _effects(hide=True)])
        props.append(["property", "Description", get_part(comp.part)["description"],
                      ["at", ps.x, ps.y, 0], _effects(hide=True)])

        inst = ["symbol",
                ["lib_id", f"kmcp:{sym.key}"],
                ["at", ps.x, ps.y, 0],
                ["unit", 1],
                ["exclude_from_sim", Sym("no")], ["in_bom", Sym("yes")],
                ["on_board", Sym("yes")], ["dnp", Sym("no")],
                ["uuid", new_uuid()]]
        inst += props
        for p in sym.pins:
            inst.append(["pin", p.number, ["uuid", new_uuid()]])
        inst.append(["instances",
                     ["project", project,
                      ["path", f"/{root_uuid}", ["reference", ref], ["unit", 1]]]])
        doc.append(inst)

    # Power symbol instances.
    pwr_idx = 0
    for pp in routing.power_pins:
        pwr_idx += 1
        ref = f"#PWR{pwr_idx:04d}"
        doc.append(["symbol",
                    ["lib_id", f"kmcp_power:{pp.net}"],
                    ["at", pp.x, pp.y, 0],
                    ["unit", 1],
                    ["exclude_from_sim", Sym("no")], ["in_bom", Sym("no")],
                    ["on_board", Sym("yes")], ["dnp", Sym("no")],
                    ["uuid", new_uuid()],
                    ["property", "Reference", ref, ["at", pp.x, pp.y, 0], _effects(hide=True)],
                    ["property", "Value", pp.net,
                     ["at", pp.x, pp.y + (3.556 if pp.down else -2.794), 0], _effects()],
                    ["property", "Footprint", "", ["at", pp.x, pp.y, 0], _effects(hide=True)],
                    ["property", "Datasheet", "", ["at", pp.x, pp.y, 0], _effects(hide=True)],
                    ["property", "Description", "", ["at", pp.x, pp.y, 0], _effects(hide=True)],
                    ["pin", "1", ["uuid", new_uuid()]],
                    ["instances",
                     ["project", project,
                      ["path", f"/{root_uuid}", ["reference", ref], ["unit", 1]]]]])

    # Wires.
    for w in routing.wires:
        for (x1, y1), (x2, y2) in zip(w.points, w.points[1:]):
            if (x1, y1) == (x2, y2):
                continue
            doc.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]],
                        _stroke(0.0, "default"), ["uuid", new_uuid()]])

    # Net labels.
    for lb in routing.labels:
        if lb.is_global:
            doc.append(["global_label", lb.net, ["shape", Sym("bidirectional")],
                        ["at", lb.x, lb.y, lb.angle],
                        ["fields_autoplaced", Sym("yes")],
                        _effects(justify=["left"] if lb.angle in (0, 90) else ["right"]),
                        ["uuid", new_uuid()],
                        ["property", "Intersheetrefs", "${INTERSHEET_REFS}",
                         ["at", lb.x, lb.y, 0], _effects(hide=True)]])
        else:
            doc.append(["label", lb.net, ["at", lb.x, lb.y, lb.angle],
                        ["fields_autoplaced", Sym("yes")],
                        _effects(justify=["left", "bottom"] if lb.angle in (0, 90)
                                 else ["right", "bottom"]),
                        ["uuid", new_uuid()]])

    # No-connect markers on floating pins (keeps ERC clean).
    connected: set[tuple[str, str]] = set()
    for pins in circuit.nets.values():
        for r, pin in pins:
            connected.add((r, str(pin)))
    for ref, ps in layout.placed.items():
        for p in ps.symbol.pins:
            if (ref, p.number) not in connected:
                px, py = ps.pin_at(p.number)
                doc.append(["no_connect", ["at", px, py], ["uuid", new_uuid()]])

    # Block outline annotations.
    for bname, (x1, y1, x2, y2) in layout.blocks.items():
        doc.append(["rectangle", ["start", x1, y1], ["end", x2, y2],
                    _stroke(0.127, "dash"), ["fill", ["type", Sym("none")]],
                    ["uuid", new_uuid()]])
        doc.append(["text", bname.upper(), ["exclude_from_sim", Sym("no")],
                    ["at", x1 + 1.5, y1 + 3.0, 0],
                    ["effects", ["font", ["size", 2.0, 2.0], Sym("bold")], ["justify", Sym("left")]],
                    ["uuid", new_uuid()]])

    doc.append(["sheet_instances", ["path", "/", ["page", "1"]]])

    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(doc))
        f.write("\n")
