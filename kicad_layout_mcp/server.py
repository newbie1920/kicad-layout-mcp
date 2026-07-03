"""FastMCP server: AI describes circuits semantically, engine handles geometry."""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .core.circuit import Circuit, Component
from .core.validate import validate
from .library.parts import FOOTPRINTS, PARTS
from .pipeline import generate_project as _generate_project

mcp = FastMCP("kicad-layout-mcp")

# In-memory circuit store, keyed by session file path or name.
_store: dict[str, Circuit] = {}


def _circuit_key(name: str) -> str:
    return name


def _dump(circuit: Circuit) -> dict:
    return circuit.to_dict()


@mcp.tool()
def create_circuit(name: str, description: str = "", board_width_mm: float = 0.0,
                   board_height_mm: float = 0.0, layers: int = 2) -> str:
    """Create a new semantic circuit model. AI supplies only name, blocks, size hint."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Invalid circuit name.")
    circuit = Circuit(name=name, description=description,
                      board_width=board_width_mm, board_height=board_height_mm,
                      layers=layers)
    _store[_circuit_key(name)] = circuit
    return json.dumps({"ok": True, "circuit": name, "components": 0, "nets": 0}, indent=2)


@mcp.tool()
def add_component(circuit_name: str, ref: str, part: str, value: str = "",
                  footprint: str = "", block: str = "main") -> str:
    """Add a component by reference, part type, value, and functional block.
    No coordinates allowed.
    """
    circuit = _store.get(_circuit_key(circuit_name))
    if not circuit:
        raise ValueError(f"Circuit '{circuit_name}' not found. Call create_circuit first.")
    comp = Component(ref=ref, part=part, value=value, footprint=footprint, block=block)
    circuit.add_component(comp)
    return json.dumps({"ok": True, "ref": ref, "block": block, "part": part}, indent=2)


@mcp.tool()
def connect(circuit_name: str, net: str, pins: list[dict]) -> str:
    """Connect a list of (ref, pin) tuples to a net. Supports power nets like VCC/GND."""
    circuit = _store.get(_circuit_key(circuit_name))
    if not circuit:
        raise ValueError(f"Circuit '{circuit_name}' not found.")
    parsed = [(p["ref"], str(p["pin"])) for p in pins]
    circuit.connect(net, parsed)
    return json.dumps({"ok": True, "net": net, "pins": len(parsed)}, indent=2)


@mcp.tool()
def list_library() -> str:
    """List all available embedded symbols/footprints for AI to choose from."""
    parts = []
    for key, info in sorted(PARTS.items()):
        parts.append({
            "part": key,
            "prefix": info["ref_prefix"],
            "default_footprint": info["footprint"],
            "alt_footprints": info["alt_footprints"],
            "pins": info["pins"],
            "description": info["description"],
        })
    fps = [{"footprint": k, "size_mm": [round(v.size()[0], 2), round(v.size()[1], 2)],
            "type": v.attr, "description": v.description}
           for k, v in sorted(FOOTPRINTS.items())]
    return json.dumps({"parts": parts, "footprints": fps}, indent=2)


@mcp.tool()
def validate_circuit(circuit_name: str) -> str:
    """Validate netlist and return actionable errors/warnings for the AI."""
    circuit = _store.get(_circuit_key(circuit_name))
    if not circuit:
        raise ValueError(f"Circuit '{circuit_name}' not found.")
    result = validate(circuit)
    return json.dumps(result, indent=2)


@mcp.tool()
def generate_project(circuit_name: str, output_dir: str) -> str:
    """Run the full pipeline: validate -> schematic -> PCB -> DRC -> export."""
    circuit = _store.get(_circuit_key(circuit_name))
    if not circuit:
        raise ValueError(f"Circuit '{circuit_name}' not found.")
    report = _generate_project(circuit, output_dir)
    return json.dumps(report, indent=2)


@mcp.tool()
def preview(circuit_name: str, output_dir: str, kind: str = "schematic") -> str:
    """Render an SVG preview so the AI/user can inspect the result."""
    from .preview.render import render_schematic, render_pcb
    circuit = _store.get(_circuit_key(circuit_name))
    if not circuit:
        raise ValueError(f"Circuit '{circuit_name}' not found.")
    os.makedirs(output_dir, exist_ok=True)
    if kind == "schematic":
        sch_path = os.path.join(output_dir, f"{circuit_name}.kicad_sch")
        svg_path = os.path.join(output_dir, f"{circuit_name}_schematic.svg")
        if not os.path.exists(sch_path):
            raise ValueError("No schematic found. Run generate_project first.")
        render_schematic(sch_path, svg_path)
    elif kind == "pcb":
        pcb_path = os.path.join(output_dir, f"{circuit_name}.kicad_pcb")
        svg_path = os.path.join(output_dir, f"{circuit_name}_pcb.svg")
        if not os.path.exists(pcb_path):
            raise ValueError("No PCB found. Run generate_project first.")
        render_pcb(pcb_path, svg_path)
    else:
        raise ValueError("kind must be 'schematic' or 'pcb'")
    return json.dumps({"ok": True, "svg": svg_path}, indent=2)


@mcp.tool()
def get_report(circuit_name: str, output_dir: str) -> str:
    """Return BOM, track length, via count, DRC report."""
    path = os.path.join(output_dir, f"{circuit_name}_report.json")
    if not os.path.exists(path):
        raise ValueError("No report found. Run generate_project first.")
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
