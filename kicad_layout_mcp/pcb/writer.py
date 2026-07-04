"""Writes KiCad 10-compatible .kicad_pcb file (format 20250513)."""
from __future__ import annotations

from ..core.circuit import Circuit, is_gnd_net
from ..core.sexpr import Sym, dumps, new_uuid
from ..library.parts import get_part, resolve_footprint
from .placer import PCBLayout
from .router import RouteResult
from .silkscreen import SilkLabel, place_silkscreen


def _layer_table():
    return ["layers",
            [0, "F.Cu", Sym("signal")],
            [2, "B.Cu", Sym("signal")],
            [5, "F.SilkS", Sym("user"), "F.Silkscreen"],
            [7, "B.SilkS", Sym("user"), "B.Silkscreen"],
            [1, "F.Mask", Sym("user")],
            [3, "B.Mask", Sym("user")],
            [13, "F.Paste", Sym("user")],
            [15, "B.Paste", Sym("user")],
            [25, "Edge.Cuts", Sym("user")],
            [27, "Margin", Sym("user")],
            [31, "F.CrtYd", Sym("user"), "F.Courtyard"],
            [29, "B.CrtYd", Sym("user"), "B.Courtyard"],
            [35, "F.Fab", Sym("user")],
            [33, "B.Fab", Sym("user")],
            [17, "Dwgs.User", Sym("user"), "User.Drawings"],
            [19, "Cmts.User", Sym("user"), "User.Comments"],
            [21, "Eco1.User", Sym("user"), "User.Eco1"],
            [23, "Eco2.User", Sym("user"), "User.Eco2"],
           ]


def _stackup():
    return ["stackup",
            ["layer", "F.SilkS", ["type", "Top Silk Screen"]],
            ["layer", "F.Paste", ["type", "Top Solder Paste"]],
            ["layer", "F.Mask", ["type", "Top Solder Mask"], ["thickness", 0.01]],
            ["layer", "F.Cu", ["type", Sym("copper")], ["thickness", 0.035]],
            ["layer", "dielectric", ["type", Sym("core")], ["thickness", 1.51]],
            ["layer", "B.Cu", ["type", Sym("copper")], ["thickness", 0.035]],
            ["layer", "B.Mask", ["type", "Bottom Solder Mask"], ["thickness", 0.01]],
            ["layer", "B.Paste", ["type", "Bottom Solder Paste"]],
            ["layer", "B.SilkS", ["type", "Bottom Silk Screen"]],
           ]


def _footprint(pf, ref, value, circuit, net_ids):
    fp = pf.fp
    layer = "F.Cu" if pf.side == "front" else "B.Cu"
    out = [
        "footprint", f"kmcp:{fp.key}",
        ["layer", Sym(layer)],
        ["uuid", new_uuid()],
        ["at", pf.x, pf.y, pf.angle],
        ["descr", fp.description],
        ["property", "Reference", ref, ["at", 0, 0, 0],
         ["layer", Sym("F.Fab")], ["effects", ["font", ["size", 1, 1], ["thickness", 0.15]]]],
        ["property", "Value", value, ["at", 0, 0, 0],
         ["layer", Sym("F.Fab")], ["effects", ["font", ["size", 1, 1], ["thickness", 0.15]]]],
    ]
    pin_net_info = {}
    for net, pins in circuit.nets.items():
        nid = net_ids.get(net)
        if nid is None:
            continue
        for r, pin in pins:
            if r == ref and str(pin) in {p.number for p in fp.pads}:
                pin_net_info[str(pin)] = (nid, net)
    for pad in fp.pads:
        pad_node = ["pad", pad.number, Sym("smd" if pad.ptype == "smd" else "thru_hole"),
                    Sym(pad.shape), ["at", pad.x, pad.y], ["size", pad.w, pad.h],
                    ["layers", Sym("F.Cu"), Sym("F.Mask"), Sym("F.Paste")],
                    ["uuid", new_uuid()]]
        if pad.drill > 0:
            pad_node.append(["drill", pad.drill])
        net_info = pin_net_info.get(pad.number)
        if net_info is not None:
            nid, name = net_info
            pad_node.append(["net", nid, name])
        out.append(pad_node)
    cx1, cy1, cx2, cy2 = fp.courtyard
    out.append(["fp_rect", ["start", cx1, cy1], ["end", cx2, cy2],
                ["layer", Sym("F.CrtYd")], ["width", 0.05], ["fill", Sym("none")], ["uuid", new_uuid()]])
    # disable footprint silk lines to avoid DRC with generated pad shapes
    for (x1, y1, x2, y2) in fp.silk:
        out.append(["fp_line", ["start", x1, y1], ["end", x2, y2],
                    ["layer", Sym("F.Fab")], ["width", 0.12], ["uuid", new_uuid()]])
    return out


def _segment(t, net_id=0):
    layer = {"F.Cu": "F.Cu", "B.Cu": "B.Cu"}.get(t.layer, "F.Cu")
    return ["segment", ["start", t.x1, t.y1], ["end", t.x2, t.y2],
            ["width", t.width], ["layer", Sym(layer)], ["net", net_id], ["uuid", new_uuid()]]


def _via(v, net_id=0):
    return ["via", ["at", v.x, v.y], ["size", v.size], ["drill", v.drill],
            ["layers", Sym("F.Cu"), Sym("B.Cu")], ["net", net_id], ["uuid", new_uuid()]]


def write_pcb(circuit, layout, route, path):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    silk = place_silkscreen(circuit, layout)

    nets = [""]
    net_ids = {"": 0}
    for net, pins in circuit.nets.items():
        if is_gnd_net(net):
            continue
        if len(pins) >= 2:
            nets.append(net)
            net_ids[net] = len(nets) - 1

    doc = ["kicad_pcb",
           ["version", 20250513],
           ["generator", "kicad_layout_mcp"],
           ["generator_version", "9.99"],
           ["general", ["thickness", 1.6], ["legacy_teardrops", Sym("no")]],
           ["paper", "A4"],
           _layer_table(),
           ["setup",
            ["pad_to_mask_clearance", 0], ["solder_mask_min_width", 0.1],
            _stackup(),
            ["pcbplotparams", ["layerselection", "0x00010fc_ffffffff"], ["plot_on_all_layers_selection", "0x0000000_00000000"]]],
           *([["net", i, n] for i, n in enumerate(nets)])]

    doc.append(["gr_rect", ["start", layout.board_x1, layout.board_y1],
                ["end", layout.board_x2, layout.board_y2],
                ["stroke", ["width", 0.05], ["type", Sym("default")]],
                ["fill", Sym("none")], ["layer", Sym("Edge.Cuts")], ["uuid", new_uuid()]])

    for ref, pf in layout.placed.items():
        doc.append(_footprint(pf, ref, circuit.components[ref].value or circuit.components[ref].part, circuit, net_ids))

    for sl in silk.labels:
        doc.append(["gr_text", sl.text,
                    ["at", sl.x, sl.y, 0],
                    ["layer", Sym("F.SilkS")],
                    ["effects", ["font", ["size", 1, 1], ["thickness", 0.15]]],
                    ["uuid", new_uuid()]])

    for t in route.tracks:
        doc.append(_segment(t, net_ids.get(t.net, 0)))
    for v in route.vias:
        doc.append(_via(v, net_ids.get(v.net, 0)))

    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(doc))
        f.write("\n")
