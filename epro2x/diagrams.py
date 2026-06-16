"""Optional PNG diagram rendering (requires matplotlib).

Generates:
    layout.png            component placement (Top/Bottom)
    route_<layer>.png     routed copper per copper layer
    grounds.png           AGND/GND pour partition with stitching vias

Kept separate from extraction so the core extractor has zero dependencies.
"""

from __future__ import annotations

import os

from .core import Epro2Project
from . import pcb as pcbx


def _net_color(net: str | None) -> str:
    if not net:
        return "#999999"
    u = net.upper()
    if u == "AGND":
        return "#1f77b4"
    if u == "GND":
        return "#d62728"
    if "_AN" in u:
        return "#2ca02c"
    if "DIG" in u:
        return "#9467bd"
    return "#888888"


def render_all(project: Epro2Project, outdir: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    os.makedirs(outdir, exist_ok=True)
    pcb = project.pcb
    coppers = pcbx.copper_layers(pcb)
    placements = pcbx.extract_placements(pcb)
    traces = pcbx.extract_traces(pcb, coppers)
    vias = pcbx.extract_vias(pcb)
    pours = pcbx.extract_pours(pcb)

    # ---- layout ----
    fig, ax = plt.subplots(figsize=(9, 11))
    for p in placements:
        if p["x_mm"] is None:
            continue
        pre = "".join(c for c in p["designator"] if c.isalpha())
        color = {"U": "#d62728", "C": "#1f77b4", "R": "#2ca02c"}.get(pre, "#ff7f0e")
        marker = "s" if p["side"] == "Top" else "^"
        ax.plot(p["x_mm"], p["y_mm"], marker, color=color, ms=4, alpha=0.8)
        if pre in ("U", "P"):
            ax.annotate(p["designator"], (p["x_mm"], p["y_mm"]), fontsize=5, ha="center")
    ax.set_title("Component Layout (square=Top, triangle=Bottom)")
    ax.set_aspect("equal"); ax.set_xlabel("mm"); ax.set_ylabel("mm"); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "layout.png"), dpi=130); plt.close(fig)

    # ---- per-layer routing ----
    for lid, info in coppers.items():
        fig, ax = plt.subplots(figsize=(8.5, 10.5))
        segs = [t for t in traces if t["layer_id"] == lid]
        for t in segs:
            ax.plot([t["x1_mm"], t["x2_mm"]], [t["y1_mm"], t["y2_mm"]],
                    "-", color=_net_color(t["net"]),
                    lw=max(0.4, (t["width_mil"] or 10) * 0.02), alpha=0.8, solid_capstyle="round")
        for v in vias:
            ax.plot(v["x_mm"], v["y_mm"], ".", color="k", ms=1.5, alpha=0.4)
        ax.set_title(f"{info['name']} ({len(segs)} segments)")
        ax.set_aspect("equal"); ax.set_xlabel("mm"); ax.set_ylabel("mm"); ax.grid(alpha=0.15)
        safe = str(info["name"]).replace(" ", "_").replace("/", "_")
        fig.tight_layout(); fig.savefig(os.path.join(outdir, f"route_{safe}.png"), dpi=130); plt.close(fig)

    # ---- ground partition ----
    grounds = pcbx.ground_analysis(pours, vias)
    if grounds["is_split"]:
        fig, ax = plt.subplots(figsize=(8.5, 10.5))
        order = sorted(grounds["ground_nets"], key=lambda n: 0 if n.upper() == "AGND" else 1)
        for net in order:
            color = "#9ec5ee" if net.upper() == "AGND" else "#f3b3a4"
            for p in pours:
                if p["net"] == net:
                    for poly in p["polygons"]:
                        ax.add_patch(Polygon(poly, closed=True, facecolor=color, edgecolor="none", alpha=0.55))
        for v in vias:
            if v["net"] and "GND" in v["net"].upper():
                c = "#08306b" if v["net"].upper() == "AGND" else "#7f0000"
                ax.plot(v["x_mm"], v["y_mm"], ".", color=c, ms=2)
        ax.set_title("Ground partition: AGND (blue) vs GND (red)")
        ax.set_aspect("equal"); ax.set_xlabel("mm"); ax.set_ylabel("mm"); ax.grid(alpha=0.15)
        fig.tight_layout(); fig.savefig(os.path.join(outdir, "grounds.png"), dpi=130); plt.close(fig)
