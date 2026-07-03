"""Intermediate semantic circuit model.

The AI only ever manipulates this model: components, nets, functional
blocks. It never supplies coordinates. All geometry is derived later by
the schematic and PCB engines.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict

POWER_NET_RE = re.compile(r"^(VCC|VDD|VBUS|VBAT|V?\+?\d+V\d*|\+\d+V\d*|3V3|5V|12V|VIN|VOUT|AVCC|AVDD)$", re.I)
GND_NET_RE = re.compile(r"^(GND|AGND|DGND|PGND|VSS|GNDA|EARTH)$", re.I)


def is_power_net(name: str) -> bool:
    return bool(POWER_NET_RE.match(name))


def is_gnd_net(name: str) -> bool:
    return bool(GND_NET_RE.match(name))


@dataclass
class Component:
    ref: str                 # "R1", "U2" ...
    part: str                # library part key, e.g. "R", "ESP32-WROOM-32"
    value: str = ""          # "10k", "100nF" ...
    footprint: str = ""      # footprint key; empty -> part default
    block: str = "main"      # functional block name
    fields: dict = field(default_factory=dict)  # extra fields (MPN, note...)


@dataclass
class Circuit:
    name: str
    description: str = ""
    board_width: float = 0.0   # 0 = auto
    board_height: float = 0.0  # 0 = auto
    layers: int = 2
    components: dict[str, Component] = field(default_factory=dict)
    # nets: net name -> list of [ref, pin_number]
    nets: dict[str, list] = field(default_factory=dict)
    # block order hint (left -> right signal flow); optional
    block_order: list[str] = field(default_factory=list)

    # ---------- mutation ----------

    def add_component(self, comp: Component) -> None:
        if comp.ref in self.components:
            raise ValueError(f"Reference '{comp.ref}' already exists. Use a unique reference designator.")
        if not re.match(r"^[A-Za-z]{1,4}\d+$", comp.ref):
            raise ValueError(
                f"Invalid reference '{comp.ref}'. Use standard designators like R1, C2, U3, J1, D1, Q1, SW1, Y1."
            )
        self.components[comp.ref] = comp
        if comp.block not in self.block_order:
            self.block_order.append(comp.block)

    def remove_component(self, ref: str) -> None:
        if ref not in self.components:
            raise ValueError(f"Component '{ref}' not found.")
        del self.components[ref]
        for net in list(self.nets):
            self.nets[net] = [p for p in self.nets[net] if p[0] != ref]
            if not self.nets[net]:
                del self.nets[net]

    def connect(self, net_name: str, pins: list[tuple[str, str]]) -> None:
        net_name = net_name.strip()
        if not net_name:
            raise ValueError("Net name must not be empty.")
        existing = self.nets.setdefault(net_name, [])
        for ref, pin in pins:
            if ref not in self.components:
                raise ValueError(f"Component '{ref}' not found. Add it with add_component first.")
            # A pin can belong to only one net.
            for other_net, other_pins in self.nets.items():
                if other_net == net_name:
                    continue
                if [ref, str(pin)] in [[p[0], str(p[1])] for p in other_pins]:
                    raise ValueError(
                        f"Pin {pin} of {ref} is already connected to net '{other_net}'. "
                        f"A pin can only be on one net."
                    )
            entry = [ref, str(pin)]
            if entry not in existing:
                existing.append(entry)

    def disconnect(self, net_name: str) -> None:
        if net_name not in self.nets:
            raise ValueError(f"Net '{net_name}' not found.")
        del self.nets[net_name]

    # ---------- queries ----------

    def pin_net(self, ref: str, pin: str) -> str | None:
        for net, pins in self.nets.items():
            if [ref, str(pin)] in [[p[0], str(p[1])] for p in pins]:
                return net
        return None

    def blocks(self) -> dict[str, list[Component]]:
        out: dict[str, list[Component]] = {}
        for c in self.components.values():
            out.setdefault(c.block, []).append(c)
        return out

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Circuit":
        comps = {r: Component(**c) for r, c in d.get("components", {}).items()}
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            board_width=d.get("board_width", 0.0),
            board_height=d.get("board_height", 0.0),
            layers=d.get("layers", 2),
            components=comps,
            nets={k: [list(p) for p in v] for k, v in d.get("nets", {}).items()},
            block_order=d.get("block_order", []),
        )

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Circuit":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
