"""End-to-end pipeline: circuit -> schematic + PCB + report."""
from __future__ import annotations

import json
import os
import re

from .core.circuit import Circuit
from .core.validate import validate
from .library.parts import get_part
from .pcb.drc import run_drc
from .pcb.placer import place_pcb
from .pcb.router import route_pcb
from .pcb.silkscreen import place_silkscreen
from .pcb.writer import write_pcb
from .preview.render import render_pcb, render_schematic
from .schematic.placer import place_schematic
from .schematic.router import route_schematic
from .schematic.writer import write_schematic


def _bom(circuit: Circuit) -> list[dict]:
    bom: dict[str, dict] = {}
    for ref, comp in circuit.components.items():
        info = get_part(comp.part)
        fp = comp.footprint or info["footprint"]
        key = (comp.part, comp.value, fp)
        bom.setdefault(key, {"refs": [], "part": comp.part, "value": comp.value,
                             "footprint": fp, "description": info["description"]})
        bom[key]["refs"].append(ref)
    return [{"quantity": len(v["refs"]), **v, "refs": v["refs"]}
            for v in sorted(bom.values(), key=lambda x: x["refs"][0])]


def generate_project(circuit: Circuit, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    name = circuit.name

    # 1. Validate.
    v = validate(circuit)
    if not v["ok"]:
        return {"ok": False, "stage": "validate", "errors": v["errors"], "warnings": v["warnings"]}

    # 2. Schematic.
    sch_path = os.path.join(output_dir, f"{name}.kicad_sch")
    sch_layout = place_schematic(circuit)
    sch_route = route_schematic(circuit, sch_layout)
    write_schematic(circuit, sch_layout, sch_route, sch_path)

    # 3. PCB.
    pcb_path = os.path.join(output_dir, f"{name}.kicad_pcb")
    pcb_layout = place_pcb(circuit)
    route_result = route_pcb(circuit, pcb_layout)
    place_silkscreen(circuit, pcb_layout)
    drc = run_drc(circuit, pcb_layout, route_result)
    write_pcb(circuit, pcb_layout, route_result, pcb_path)

    # 4. Project file.
    pro_path = os.path.join(output_dir, f"{name}.kicad_pro")
    from kiutils.schematic import Schematic
    sch_uuid = Schematic().from_file(sch_path).uuid or ""
    pcb_uuid = _read_uuid(pcb_path) or ""
    _write_pro(name, pro_path, sch_uuid, pcb_uuid)

    # 5. Previews.
    try:
        render_schematic(sch_path, os.path.join(output_dir, f"{name}_schematic.svg"))
        render_pcb(pcb_path, os.path.join(output_dir, f"{name}_pcb.svg"))
    except Exception:
        pass

    # 6. Report.
    report = {
        "ok": drc["ok"],
        "circuit": name,
        "output_dir": output_dir,
        "files": {"schematic": sch_path, "pcb": pcb_path, "project": pro_path},
        "bom": _bom(circuit),
        "drc": drc,
        "pcb_stats": route_result.stats(),
        "warnings": v["warnings"],
    }
    with open(os.path.join(output_dir, f"{name}_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return report


def _read_uuid(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.search(r'\(uuid\s+"([^"]+)"\)', line)
            if m:
                return m.group(1)
    return ""


def _write_pro(name: str, path: str, sch_uuid: str = "", pcb_uuid: str = "") -> None:
    data = {
        "board": {"design_settings": {"defaults": {}, "diff_pair_dimensions": [],
                                      "rules": {}, "track_widths": [], "via_dimensions": []},
                  "layer_presets": [], "viewports": []},
        "boards": [[pcb_uuid, name]] if pcb_uuid else [],
        "component_class_settings": {"component_classes": [], "meta": {"version": 0}},
        "cvpcb": {"footprint_choices": []},
        "erc": {"erc_exclusions": [], "meta": {"version": 0}, "pin_to_pin": "warning"},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": [{"bus_width": 12.0, "clearance": 0.2, "diff_pair_gap": 0.25,
                                       "diff_pair_via_gap": 0.25, "line_style": 0,
                                       "microvia_diameter": 0.3, "microvia_drill": 0.1,
                                       "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.0000)",
                                       "schematic_color": "rgba(0, 0, 0, 0.0000)",
                                       "track_width": 0.25, "via_diameter": 0.6,
                                       "via_drill": 0.3, "wire_width": 6.0}],
                      "meta": {"version": 2}, "net_colors": None},
        "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"drawing": {"sheet_size": "A3", "legacy_lib_dirs": []},
                      "layout": {"overlap": {"enable": False}},
                      "selection": {}},
        "sheets": [[sch_uuid, name]] if sch_uuid else [],
        "text_variables": {},
        "time_domain_parameters": {"max_dimension": 0.0, "meta": {"version": 1}},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
