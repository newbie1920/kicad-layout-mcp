"""End-to-end tests: validate, export, parse with kiutils, DRC clean."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kicad_layout_mcp.core.circuit import Circuit, Component
from kicad_layout_mcp.pipeline import generate_project


def _circuit1() -> Circuit:
    c = Circuit(name="led_button", description="LED + resistor + button")
    c.add_component(Component(ref="R1", part="R", value="1k", block="io"))
    c.add_component(Component(ref="D1", part="LED", value="RED", block="io"))
    c.add_component(Component(ref="SW1", part="SW_PUSH", block="io"))
    c.add_component(Component(ref="J1", part="CONN_1x02", block="io"))
    c.connect("VCC", [("J1", "1"), ("R1", "1")])
    c.connect("LED_NET", [("R1", "2"), ("D1", "2")])
    c.connect("SW_NET", [("D1", "1"), ("SW1", "1")])
    c.connect("GND", [("SW1", "2"), ("J1", "2")])
    return c


def _circuit2() -> Circuit:
    c = Circuit(name="esp32_regulator", description="AMS1117 + ESP32 minimal")
    c.add_component(Component(ref="J1", part="CONN_1x02", block="power"))
    c.add_component(Component(ref="C1", part="C", value="10uF", block="power"))
    c.add_component(Component(ref="C2", part="C", value="100nF", block="power"))
    c.add_component(Component(ref="U1", part="AMS1117-3.3", block="power"))
    c.add_component(Component(ref="C3", part="C", value="10uF", block="power"))
    c.add_component(Component(ref="U2", part="ESP32-WROOM-32", block="mcu"))
    c.add_component(Component(ref="R1", part="R", value="10k", block="mcu"))
    c.connect("VIN", [("J1", "1"), ("C1", "1"), ("U1", "3")])
    c.connect("GND", [("J1", "2"), ("C1", "2"), ("C2", "2"), ("U1", "1"), ("C3", "2"), ("U2", "1"), ("U2", "15"), ("U2", "38"), ("U2", "39")])
    c.connect("3V3", [("C2", "1"), ("U1", "2"), ("C3", "1"), ("U2", "2"), ("R1", "1")])
    c.connect("EN", [("R1", "2"), ("U2", "3")])
    return c


def _circuit3() -> Circuit:
    c = Circuit(name="opamp_preamp", description="LM358 audio preamp with connector")
    c.add_component(Component(ref="J1", part="CONN_1x02", block="io"))
    c.add_component(Component(ref="J2", part="CONN_1x02", block="io"))
    c.add_component(Component(ref="U1", part="LM358", block="amp"))
    c.add_component(Component(ref="R1", part="R", value="10k", block="amp"))
    c.add_component(Component(ref="R2", part="R", value="100k", block="amp"))
    c.add_component(Component(ref="R3", part="R", value="10k", block="amp"))
    c.add_component(Component(ref="C1", part="C", value="10uF", block="amp"))
    c.add_component(Component(ref="C2", part="C", value="100nF", block="power"))
    c.connect("VCC", [("J1", "1"), ("C2", "1"), ("U1", "8")])
    c.connect("GND", [("J1", "2"), ("C2", "2"), ("U1", "4"), ("R3", "2"), ("J2", "2")])
    c.connect("IN", [("J2", "1"), ("C1", "1")])
    c.connect("IN_PLUS", [("C1", "2"), ("R3", "1"), ("U1", "3")])
    c.connect("FB", [("U1", "2"), ("R1", "1"), ("R2", "2")])
    c.connect("OUT", [("U1", "1"), ("R1", "2"), ("R2", "1")])
    return c


@pytest.mark.parametrize("builder", [_circuit1, _circuit2, _circuit3])
def test_end_to_end(builder, tmp_path):
    c = builder()
    out = str(tmp_path / c.name)
    report = generate_project(c, out)
    assert report["ok"], f"DRC failed: {report['drc']['errors']}"

    sch_path = report["files"]["schematic"]
    pcb_path = report["files"]["pcb"]

    from kiutils.schematic import Schematic
    from kiutils.board import Board
    sch = Schematic().from_file(sch_path)
    def _ref(sym):
        for prop in sym.properties:
            if prop.key == "Reference":
                return prop.value
        return ""
    real_symbols = [s for s in sch.schematicSymbols if _ref(s) and not _ref(s).startswith("#")]
    assert len(real_symbols) == len(c.components)
    pcb = Board().from_file(pcb_path)
    assert len(pcb.footprints) == len(c.components)

    svg_sch = os.path.join(out, f"{c.name}_schematic.svg")
    svg_pcb = os.path.join(out, f"{c.name}_pcb.svg")
    assert os.path.exists(svg_sch)
    assert os.path.exists(svg_pcb)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
