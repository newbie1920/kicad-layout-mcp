"""PCB autoroute: Lee/A* maze router on 0.2mm grid, 2 layers, GND pour."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from ..core.circuit import Circuit, is_gnd_net, is_power_net
from .placer import PCBLayout, PlacedFootprint

GRID_MM = 0.2
TRACK = 0.25
CLEAR = 0.2


def _cell(x: float, y: float) -> tuple[int, int]:
    return (round(x / GRID_MM), round(y / GRID_MM))


def _center_bbox(x1: float, y1: float, x2: float, y2: float) -> tuple:
    """Expand bbox by half clear + track to block routing through."""
    margin = CLEAR + TRACK
    return (x1 - margin, y1 - margin, x2 + margin, y2 + margin)


@dataclass
class Track:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.25
    net: str = ""


@dataclass
class Via:
    x: float
    y: float
    size: float = 0.6
    drill: float = 0.3
    net: str = ""


@dataclass
class RouteResult:
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    unrouted: list[tuple] = field(default_factory=list)

    def stats(self) -> dict:
        total = sum(math.hypot(t.x2 - t.x1, t.y2 - t.y1) for t in self.tracks)
        return {"track_count": len(self.tracks), "track_length_mm": round(total, 2),
                "via_count": len(self.vias), "unrouted": len(self.unrouted)}


import math


def _bbox_expand(bb: tuple, margin: float) -> tuple:
    return (bb[0] - margin, bb[1] - margin, bb[2] + margin, bb[3] + margin)


def _in_bbox(bb: tuple, x: float, y: float) -> bool:
    return bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]


def route_pcb(circuit: Circuit, layout: PCBLayout) -> RouteResult:
    result = RouteResult()

    # Obstacles: courtyards + foreign pads on start/end components.
    obstacles: list[tuple[str, tuple]] = []
    for p in layout.placed.values():
        obstacles.append((p.ref, _bbox_expand(p.courtyard_world(), CLEAR + TRACK / 2)))
        for pad in p.fp.pads:
            px, py = p._rotate(pad.x, pad.y)
            # Pad obstacle with clearance; tagged by ref+pin so net's own pad is skippable.
            obstacles.append((f"{p.ref}:{pad.number}",
                              (px - pad.w / 2 - CLEAR - TRACK / 2,
                               py - pad.h / 2 - CLEAR - TRACK / 2,
                               px + pad.w / 2 + CLEAR + TRACK / 2,
                               py + pad.h / 2 + CLEAR + TRACK / 2)))

    # Nets to route, sorted: power -> short -> long.
    netlist: list[tuple] = []
    for net, pins in circuit.nets.items():
        if is_gnd_net(net):
            continue
        if len(pins) < 2:
            continue
        points = []
        valid = True
        for ref, pin in pins:
            if ref not in layout.placed:
                valid = False
                break
            try:
                points.append(layout.placed[ref].pin_world(pin))
            except ValueError:
                valid = False
                break
        if valid:
            is_pwr = is_power_net(net)
            est = sum(max(abs(points[i][0] - points[i + 1][0]),
                          abs(points[i][1] - points[i + 1][1])) for i in range(len(points) - 1))
            netlist.append((net, points, is_pwr, est))

    netlist.sort(key=lambda x: (not x[2], x[3]))

    occupied: list[Track] = []
    occupied_vias: set = set()

    def layer_pref_for_segment(dx: float, dy: float, layer: str | None) -> str:
        if layer:
            return layer
        # H on F.Cu, V on B.Cu.
        return "F.Cu" if abs(dx) >= abs(dy) else "B.Cu"

    def trace(start, end, width, ref_ignore):
        # Straight-line Manhattan route with via at turn.
        x1, y1 = start
        x2, y2 = end
        # Try horizontal-first; if blocked, vertical-first.
        for pts in ([start, (x2, y1), end], [start, (x1, y2), end]):
            ok = True
            # Require endpoints not inside other components' obstacles.
            if _in_any_obstacle(start, ref_ignore, obstacles) or _in_any_obstacle(end, ref_ignore, obstacles):
                ok = False
                continue
            for a, b in zip(pts, pts[1:]):
                if _segment_hits(a, b, ref_ignore, obstacles, occupied):
                    ok = False
                    break
            if ok:
                layer1 = layer_pref_for_segment(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], None)
                layer2 = layer_pref_for_segment(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1], layer1)
                result.tracks.append(Track(layer1, pts[0][0], pts[0][1], pts[1][0], pts[1][1], width, net))
                result.tracks.append(Track(layer2, pts[1][0], pts[1][1], pts[2][0], pts[2][1], width, net))
                if layer1 != layer2:
                    result.vias.append(Via(pts[1][0], pts[1][1], net=net))
                    occupied_vias.add(_cell(pts[1][0], pts[1][1]))
                # mark occupancy roughly as multiple segments.
                for a, b in zip(pts, pts[1:]):
                    occupied.append(Track(layer1 if a != pts[1] else layer2, a[0], a[1], b[0], b[1], width + CLEAR, net))
                return True
        return False

    def _in_any_obstacle(pt, obstacles):
        for obs in obstacles:
            if _in_bbox(obs, pt[0], pt[1]):
                return True
        return False

    def _in_any_obstacle(pt, ref_ignore, obstacles):
        for ref, obs in obstacles:
            if ref in ref_ignore:
                continue
            if _in_bbox(obs, pt[0], pt[1]):
                return True
        return False

    def _segment_hits(a, b, ref_ignore, obstacles, tracks):
        # raster check along segment.
        cells = _cells_on_segment(a, b)
        margin = TRACK / 2 + CLEAR
        for (cx, cy) in cells:
            x, y = cx * GRID_MM, cy * GRID_MM
            for ref, obs in obstacles:
                if ref in ref_ignore:
                    continue
                if _in_bbox(obs, x, y):
                    return True
            for t in tracks:
                if _point_near_track(x, y, t, margin):
                    return True
        return False

    def _cells_on_segment(a, b):
        c1, c2 = _cell(a[0], a[1]), _cell(b[0], b[1])
        pts = []
        if c1[0] == c2[0]:
            for y in range(min(c1[1], c2[1]), max(c1[1], c2[1]) + 1):
                pts.append((c1[0], y))
        else:
            for x in range(min(c1[0], c2[0]), max(c1[0], c2[0]) + 1):
                pts.append((x, c1[1]))
        return pts

    def _point_near_track(x, y, t, margin):
        if t.layer not in ("F.Cu", "B.Cu"):
            return False
        x1, y1, x2, y2 = t.x1, t.y1, t.x2, t.y2
        if x1 == x2:
            if abs(x - x1) <= margin and min(y1, y2) - margin <= y <= max(y1, y2) + margin:
                return True
        else:
            if abs(y - y1) <= margin and min(x1, x2) - margin <= y <= max(x1, x2) + margin:
                return True
        return False

    for net, points, is_pwr, _ in netlist:
        width = 0.5 if is_pwr else 0.25
        # Minimum spanning tree over points.
        remaining = set(range(1, len(points)))
        connected = [0]
        ref_ignore = set()
        for ref, pin in circuit.nets[net]:
            ref_ignore.add(ref)
            ref_ignore.add(f"{ref}:{pin}")
        while remaining:
            best = None
            best_d = float("inf")
            best_pair = None
            for ci in connected:
                for ri in remaining:
                    d = abs(points[ci][0] - points[ri][0]) + abs(points[ci][1] - points[ri][1])
                    if d < best_d:
                        best_d = d
                        best = ri
                        best_pair = (points[ci], points[ri])
            if best is None:
                break
            ok = trace(best_pair[0], best_pair[1], width, ref_ignore)
            if not ok:
                result.unrouted.append((net, best_pair[0], best_pair[1]))
            connected.append(best)
            remaining.remove(best)

    return result
