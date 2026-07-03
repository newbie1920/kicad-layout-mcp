"""Render SVG previews of schematic and PCB without requiring KiCad."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read_sexpr(path: str):
    text = open(path, encoding="utf-8").read()
    # Quick balanced parentheses tokenizer.
    tokens = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in "()":
            tokens.append(c)
            i += 1
        elif c in ' \t\n\r':
            i += 1
        elif c == '"':
            j = i + 1
            s = []
            while j < len(text):
                if text[j] == '\\' and j + 1 < len(text):
                    s.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    s.append(text[j])
                    j += 1
            tokens.append('"' + ''.join(s) + '"')
            i = j + 1
        else:
            j = i
            while j < len(text) and text[j] not in '() \t\n\r"':
                j += 1
            tokens.append(text[i:j])
            i = j
    pos = [0]

    def parse():
        assert tokens[pos[0]] == "("
        pos[0] += 1
        node = []
        while pos[0] < len(tokens) and tokens[pos[0]] != ")":
            if tokens[pos[0]] == "(":
                node.append(parse())
            else:
                node.append(tokens[pos[0]])
            pos[0] += 1
        pos[0] += 1
        return node
    return parse()


def _find(node, head: str):
    for child in node:
        if isinstance(child, list) and child and child[0] == head:
            return child
    return None


def _find_all(node, head: str):
    return [child for child in node if isinstance(child, list) and child and child[0] == head]


def _num(token):
    try:
        return float(token)
    except ValueError:
        return 0.0


def _atom(token):
    if isinstance(token, list):
        return " ".join(str(t) for t in token)
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return token


def render_schematic(sch_path: str, out_path: str) -> str:
    root = _read_sexpr(sch_path)
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    svg = ET.Element("svg", xmlns=ns, version="1.1")

    xs, ys = [], []
    # symbols with at
    syms = _find_all(root, "symbol")
    for s in syms:
        at = _find(s, "at")
        if at:
            xs.append(_num(at[1])); ys.append(_num(at[2]))
    # wires
    wires = _find_all(root, "wire")
    for w in wires:
        pts = _find(w, "pts")
        if pts:
            for xy in _find_all(pts, "xy"):
                xs.append(_num(xy[1])); ys.append(_num(xy[2]))
    if not xs:
        xs = [0, 100]
        ys = [0, 100]
    margin = 10
    minx, maxx = min(xs) - margin, max(xs) + margin
    miny, maxy = min(ys) - margin, max(ys) + margin
    w, h = maxx - minx, maxy - miny
    svg.set("viewBox", f"{minx} {miny} {w} {h}")
    svg.set("width", f"{w}mm")
    svg.set("height", f"{h}mm")

    # sheet outline
    rect = ET.SubElement(svg, "rect")
    rect.set("x", str(minx + 5))
    rect.set("y", str(miny + 5))
    rect.set("width", str(w - 10))
    rect.set("height", str(h - 10))
    rect.set("fill", "none")
    rect.set("stroke", "#ccc")
    rect.set("stroke-width", "0.5")

    # wires
    for w in wires:
        pts = _find(w, "pts")
        if not pts:
            continue
        path = []
        for xy in _find_all(pts, "xy"):
            path.append(f"{_num(xy[1])},{_num(xy[2])}")
        if len(path) >= 2:
            el = ET.SubElement(svg, "polyline")
            el.set("points", " ".join(path))
            el.set("fill", "none")
            el.set("stroke", "#0044cc")
            el.set("stroke-width", "0.25")
            el.set("stroke-linecap", "round")
            el.set("stroke-linejoin", "round")

    # symbols as rectangles
    for s in syms:
        at = _find(s, "at")
        if not at:
            continue
        x, y = _num(at[1]), _num(at[2])
        rect = ET.SubElement(svg, "rect")
        rect.set("x", str(x - 2.54))
        rect.set("y", str(y - 2.54))
        rect.set("width", "5.08")
        rect.set("height", "5.08")
        rect.set("fill", "#f8f8f8")
        rect.set("stroke", "#333")
        rect.set("stroke-width", "0.25")
        # ref/value visible properties
        for prop in _find_all(s, "property"):
            if len(prop) > 2 and prop[1] in ("Reference", "Value"):
                eff = _find(prop, "effects")
                if eff and not _find(eff, "hide"):
                    el = ET.SubElement(svg, "text")
                    el.set("x", str(x))
                    el.set("y", str(y - 4))
                    el.set("font-size", "2")
                    el.set("font-family", "sans-serif")
                    el.text = _atom(prop[2])

    # labels
    for lb in _find_all(root, "label") + _find_all(root, "global_label"):
        at = _find(lb, "at")
        if at:
            x, y = _num(at[1]), _num(at[2])
            el = ET.SubElement(svg, "text")
            el.set("x", str(x))
            el.set("y", str(y))
            el.set("font-size", "2")
            el.set("fill", "#cc4400")
            el.text = _atom(lb[1])

    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def render_pcb(pcb_path: str, out_path: str) -> str:
    root = _read_sexpr(pcb_path)
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    svg = ET.Element("svg", xmlns=ns, version="1.1")

    gr = _find(root, "gr_rect")
    if gr:
        start = _find(gr, "start")
        end = _find(gr, "end")
        minx, miny = _num(start[1]), _num(start[2])
        maxx, maxy = _num(end[1]), _num(end[2])
    else:
        minx, miny, maxx, maxy = 0, 0, 50, 50
    margin = 5
    w, h = maxx - minx + 2 * margin, maxy - miny + 2 * margin
    svg.set("viewBox", f"{minx - margin} {miny - margin} {w} {h}")
    svg.set("width", f"{w}mm")
    svg.set("height", f"{h}mm")

    # board edge
    rect = ET.SubElement(svg, "rect")
    rect.set("x", str(minx))
    rect.set("y", str(miny))
    rect.set("width", str(maxx - minx))
    rect.set("height", str(maxy - miny))
    rect.set("fill", "#1a3300")
    rect.set("stroke", "#fff")
    rect.set("stroke-width", "0.25")

    # footprints
    for fp in _find_all(root, "footprint"):
        at = _find(fp, "at")
        if at:
            x, y = _num(at[1]), _num(at[2])
            angle = _num(at[3]) if len(at) > 3 else 0
            for pad in _find_all(fp, "pad"):
                atp = _find(pad, "at")
                sz = _find(pad, "size")
                if atp and sz:
                    px, py = _num(atp[1]), _num(atp[2])
                    pw, ph = _num(sz[1]), _num(sz[2])
                    el = ET.SubElement(svg, "rect")
                    el.set("x", str(x + px - pw / 2))
                    el.set("y", str(y + py - ph / 2))
                    el.set("width", str(pw))
                    el.set("height", str(ph))
                    el.set("fill", "#c98")
                    el.set("stroke", "#fff")
                    el.set("stroke-width", "0.05")
            # ref label
            for prop in _find_all(fp, "property"):
                if len(prop) > 2 and prop[1] == "Reference":
                    el = ET.SubElement(svg, "text")
                    el.set("x", str(x))
                    el.set("y", str(y - 2))
                    el.set("font-size", "1.5")
                    el.set("fill", "#fff")
                    el.text = _atom(prop[2])

    # tracks
    for seg in _find_all(root, "segment"):
        st = _find(seg, "start")
        en = _find(seg, "end")
        if st and en:
            el = ET.SubElement(svg, "line")
            el.set("x1", st[1]); el.set("y1", st[2])
            el.set("x2", en[1]); el.set("y2", en[2])
            el.set("stroke", "#ffcc00")
            el.set("stroke-width", "0.25")

    # vias
    for via in _find_all(root, "via"):
        at = _find(via, "at")
        if at:
            el = ET.SubElement(svg, "circle")
            el.set("cx", at[1]); el.set("cy", at[2])
            el.set("r", "0.4")
            el.set("fill", "#fff")
            el.set("stroke", "#ffcc00")

    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path
