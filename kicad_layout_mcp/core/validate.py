"""Netlist validation with AI-friendly, actionable error messages."""
from __future__ import annotations

from .circuit import Circuit, is_gnd_net, is_power_net
from ..library.parts import get_part, get_symbol, resolve_footprint


def validate(circuit: Circuit) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not circuit.components:
        errors.append("Circuit has no components. Add components with add_component.")
        return {"ok": False, "errors": errors, "warnings": warnings}

    # Parts / footprints resolve, pin references valid.
    for ref, comp in circuit.components.items():
        try:
            part = get_part(comp.part)
        except ValueError as e:
            errors.append(f"{ref}: {e}")
            continue
        try:
            resolve_footprint(comp.part, comp.footprint)
        except ValueError as e:
            errors.append(f"{ref}: {e}")
        valid_pins = {p["number"] for p in part["pins"]}
        for net, pins in circuit.nets.items():
            for r, pin in pins:
                if r == ref and str(pin) not in valid_pins:
                    errors.append(
                        f"Net '{net}': {ref} has no pin '{pin}'. Valid pins of {comp.part}: "
                        + ", ".join(sorted(valid_pins, key=_pin_sort))
                    )

    # Nets reference existing components.
    for net, pins in circuit.nets.items():
        for r, pin in pins:
            if r not in circuit.components:
                errors.append(f"Net '{net}' references unknown component '{r}'.")
        if len(pins) < 2:
            warnings.append(
                f"Net '{net}' has only {len(pins)} pin(s) connected — a net needs at least 2 pins."
            )

    # Floating pins.
    connected: set[tuple[str, str]] = set()
    for pins in circuit.nets.values():
        for r, pin in pins:
            connected.add((r, str(pin)))
    for ref, comp in circuit.components.items():
        try:
            sym = get_symbol(comp.part)
        except ValueError:
            continue
        for p in sym.pins:
            if (ref, p.number) not in connected:
                if p.etype == "no_connect":
                    continue
                if p.etype in ("power_in",):
                    errors.append(
                        f"Power pin {p.number} ({p.name}) of {ref} is not connected. "
                        f"Connect it to a power or GND net."
                    )
                else:
                    warnings.append(
                        f"Pin {p.number} ({p.name}) of {ref} is floating (not on any net)."
                    )

    # Sanity: presence of GND / power nets.
    if not any(is_gnd_net(n) for n in circuit.nets):
        warnings.append("No GND net found. Almost all circuits need a GND net.")
    if not any(is_power_net(n) for n in circuit.nets):
        warnings.append("No power net (VCC/3V3/5V/VIN...) found.")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _pin_sort(p: str):
    return (0, int(p)) if p.isdigit() else (1, p)
