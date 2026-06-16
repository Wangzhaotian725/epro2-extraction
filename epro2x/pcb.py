"""Extract placement, routing, vias, copper pours and derived metrics from the PCB."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .core import Epro2Project, EpruDoc
from .geometry import (
    bbox,
    flatten_path_points,
    mil_to_mm,
    point_in_poly,
    seg_len_mm,
)

# Copper layer ids observed in EasyEDA Pro:
#   1 = Top, 2 = Bottom, plus inner SIGNAL layers (e.g. 15, 16).
# Non-copper layers (silk, mask, paste, doc) are excluded from routing metrics.
COPPER_LAYER_TYPES = {"TOP", "BOTTOM", "INNER", "SIGNAL", "PLANE"}


def layer_map(pcb: EpruDoc) -> dict[int, dict[str, Any]]:
    """layerId -> {name, type, used} for every defined layer."""
    out: dict[int, dict[str, Any]] = {}
    for head, body in pcb.of_type("LAYER"):
        if not isinstance(body, dict):
            continue
        lid = body.get("layerId")
        if lid is None:
            continue
        out[lid] = {
            "name": body.get("layerName"),
            "type": body.get("layerType"),
            "used": bool(body.get("use")),
        }
    return out


def copper_layers(pcb: EpruDoc) -> dict[int, dict[str, Any]]:
    return {
        lid: info
        for lid, info in layer_map(pcb).items()
        if info["type"] in COPPER_LAYER_TYPES and info["used"]
    }


def extract_placements(pcb: EpruDoc) -> list[dict[str, Any]]:
    """Component placements on the PCB (designator, position in mm, side, angle)."""
    pos: dict[str, dict] = {}
    for head, body in pcb.of_type("COMPONENT"):
        if isinstance(body, dict):
            pos[head.get("id")] = body
    attrs: dict[str, dict] = defaultdict(dict)
    for head, body in pcb.of_type("ATTR"):
        if isinstance(body, dict) and body.get("parentId") in pos:
            attrs[body["parentId"]][body.get("key")] = body.get("value")
    out: list[dict[str, Any]] = []
    for cid, b in pos.items():
        a = attrs.get(cid, {})
        des = a.get("Designator", "?")
        out.append(
            {
                "designator": des,
                "x_mm": round(mil_to_mm(b.get("x", 0)), 4),
                "y_mm": round(mil_to_mm(-b.get("y", 0)), 4),  # flip Y to read upright
                "layer_id": b.get("layerId"),
                "side": "Top" if b.get("layerId") == 1 else "Bottom" if b.get("layerId") == 2 else "?",
                "angle": b.get("angle"),
                "footprint": a.get("Footprint"),
            }
        )
    out.sort(key=lambda r: r["designator"])
    return out


def extract_traces(pcb: EpruDoc, coppers: dict[int, dict]) -> list[dict[str, Any]]:
    """Routed copper line segments on copper layers."""
    traces: list[dict[str, Any]] = []
    for head, body in pcb.of_type("LINE"):
        if not isinstance(body, dict):
            continue
        lid = body.get("layerId")
        if lid not in coppers:
            continue
        x1, y1 = body["startX"], body["startY"]
        x2, y2 = body["endX"], body["endY"]
        traces.append(
            {
                "net": body.get("netName"),
                "layer_id": lid,
                "x1_mm": round(mil_to_mm(x1), 4),
                "y1_mm": round(mil_to_mm(-y1), 4),
                "x2_mm": round(mil_to_mm(x2), 4),
                "y2_mm": round(mil_to_mm(-y2), 4),
                "width_mil": body.get("width"),
                "len_mm": round(seg_len_mm(x1, y1, x2, y2), 4),
            }
        )
    return traces


def extract_vias(pcb: EpruDoc) -> list[dict[str, Any]]:
    vias: list[dict[str, Any]] = []
    for head, body in pcb.of_type("VIA"):
        if not isinstance(body, dict):
            continue
        vias.append(
            {
                "net": body.get("netName"),
                "x_mm": round(mil_to_mm(body.get("centerX", 0)), 4),
                "y_mm": round(mil_to_mm(-body.get("centerY", 0)), 4),
                "hole_mm": round(mil_to_mm(body.get("holeDiameter", 0)), 4),
                "pad_mm": round(mil_to_mm(body.get("viaDiameter", 0)), 4),
                "type": body.get("viaType"),
            }
        )
    return vias


def extract_pours(pcb: EpruDoc) -> list[dict[str, Any]]:
    """Copper pours (planes / ground fills) as polygons in mm."""
    pours: list[dict[str, Any]] = []
    for head, body in pcb.of_type("POUR"):
        if not isinstance(body, dict):
            continue
        # flatten_path_points returns Y as stored (negative-down); flip Y so pour
        # polygons share the same upright frame as placements/traces (Y up).
        polys = [
            [(x, -y) for (x, y) in poly]
            for poly in flatten_path_points(body.get("path", []))
        ]
        pours.append(
            {
                "net": body.get("netName"),
                "layer_id": body.get("layerId"),
                "name": body.get("name"),
                "priority": body.get("order"),
                "polygons": polys,
            }
        )
    return pours


def extract_stackup(pcb: EpruDoc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for head, body in pcb.of_type("LAYER_PHYS"):
        if isinstance(body, dict) and body.get("material"):
            out.append(
                {
                    "material": body.get("material"),
                    "thickness_mil": body.get("thickness"),
                    "z": body.get("zIndex"),
                }
            )
    return out


# --------------------------------------------------------------------------
# Derived analysis metrics (the values most useful for optimization review)
# --------------------------------------------------------------------------

def routing_metrics(traces: list[dict], coppers: dict[int, dict]) -> dict[str, Any]:
    per_layer = defaultdict(lambda: {"segments": 0, "len_mm": 0.0})
    per_net = defaultdict(lambda: {"len_mm": 0.0, "segments": 0, "layers": set()})
    widths: dict[float, int] = defaultdict(int)
    for t in traces:
        per_layer[t["layer_id"]]["segments"] += 1
        per_layer[t["layer_id"]]["len_mm"] += t["len_mm"]
        widths[t["width_mil"]] += 1
        if t["net"]:
            n = per_net[t["net"]]
            n["len_mm"] += t["len_mm"]
            n["segments"] += 1
            n["layers"].add(t["layer_id"])
    total = sum(v["len_mm"] for v in per_layer.values())
    layer_summary = {}
    for lid, v in per_layer.items():
        name = coppers.get(lid, {}).get("name", str(lid))
        layer_summary[name] = {
            "segments": v["segments"],
            "len_mm": round(v["len_mm"], 2),
            "pct": round(100 * v["len_mm"] / total, 1) if total else 0,
        }
    net_summary = {
        net: {
            "len_mm": round(v["len_mm"], 2),
            "segments": v["segments"],
            "layers": sorted(v["layers"]),
        }
        for net, v in sorted(per_net.items(), key=lambda x: -x[1]["len_mm"])
    }
    return {
        "total_len_mm": round(total, 2),
        "per_layer": layer_summary,
        "width_histogram_mil": dict(sorted(widths.items())),
        "per_net": net_summary,
    }


def ground_analysis(pours: list[dict], vias: list[dict]) -> dict[str, Any]:
    """Identify analog/digital ground partition and the bridge situation.

    Heuristic: nets whose name contains AGND/analog ground vs GND/digital.
    Reports pour coverage per layer and via stitching counts per ground net.
    """
    ground_nets = sorted({p["net"] for p in pours if p["net"] and "GND" in p["net"].upper()})
    coverage: dict[str, list[int]] = defaultdict(list)
    for p in pours:
        if p["net"] in ground_nets:
            coverage[p["net"]].append(p["layer_id"])
    via_counts: dict[str, int] = defaultdict(int)
    for v in vias:
        if v["net"] in ground_nets:
            via_counts[v["net"]] += 1
    return {
        "ground_nets": ground_nets,
        "pour_layers": {n: sorted(set(coverage[n])) for n in ground_nets},
        "stitching_vias": dict(via_counts),
        "is_split": len(ground_nets) > 1,
    }


def split_crossings(
    traces: list[dict],
    pours: list[dict],
    digital_ground: str = "GND",
    inner_only: bool = False,
) -> dict[str, Any]:
    """Find signal traces that cross the digital-ground island boundary.

    A trace 'crosses' if one endpoint is inside any digital-ground pour polygon
    and the other endpoint is outside all of them. This is an exact
    point-in-polygon test (not a bounding box), evaluated per signal layer.
    """
    # gather digital-ground polygons (optionally only inner plane)
    dg_polys: list[list[tuple[float, float]]] = []
    for p in pours:
        if p["net"] != digital_ground:
            continue
        dg_polys.extend(p["polygons"])
    if not dg_polys:
        return {"digital_ground": digital_ground, "polygons": 0, "crossing_nets": {}}

    def inside(x: float, y: float) -> bool:
        return any(point_in_poly(x, y, poly) for poly in dg_polys)

    crossings: dict[str, int] = defaultdict(int)
    for t in traces:
        net = t["net"]
        if not net or net.startswith("$") or "GND" in (net or "").upper():
            continue
        a = inside(t["x1_mm"], t["y1_mm"])
        b = inside(t["x2_mm"], t["y2_mm"])
        if a != b:
            crossings[net] += 1
    return {
        "digital_ground": digital_ground,
        "polygons": len(dg_polys),
        "crossing_nets": dict(sorted(crossings.items(), key=lambda x: -x[1])),
    }


def board_extent(placements: list[dict], traces: list[dict]) -> dict[str, float]:
    xs: list[float] = []
    ys: list[float] = []
    for p in placements:
        xs.append(p["x_mm"]); ys.append(p["y_mm"])
    for t in traces:
        xs += [t["x1_mm"], t["x2_mm"]]; ys += [t["y1_mm"], t["y2_mm"]]
    if not xs:
        return {}
    return {
        "min_x_mm": round(min(xs), 2), "max_x_mm": round(max(xs), 2),
        "min_y_mm": round(min(ys), 2), "max_y_mm": round(max(ys), 2),
        "width_mm": round(max(xs) - min(xs), 2),
        "height_mm": round(max(ys) - min(ys), 2),
    }
