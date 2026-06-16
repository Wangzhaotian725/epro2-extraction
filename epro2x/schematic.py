"""Extract components, parameters, and the netlist from schematic pages."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .core import Epro2Project, EpruDoc

# Component attribute keys we care about (others are ignored to keep output small).
KEEP_ATTRS = [
    "Designator", "Name", "Device", "Value", "Manufacturer Part",
    "Supplier Part", "Description", "Footprint", "Add into BOM",
]


def _component_attrs(page: EpruDoc) -> dict[str, dict[str, Any]]:
    """Map each component's parentId -> {attr_key: value} for placed components."""
    comp_ids: set[str] = set()
    for head, body in page.of_type("COMPONENT"):
        cid = head.get("id")
        if cid:
            comp_ids.add(cid)
    attrs: dict[str, dict[str, Any]] = defaultdict(dict)
    for head, body in page.of_type("ATTR"):
        if not isinstance(body, dict):
            continue
        pid = body.get("parentId")
        if pid in comp_ids:
            k = body.get("key")
            v = body.get("value")
            if k is not None:
                attrs[pid][k] = v
    return attrs


def extract_components(project: Epro2Project) -> list[dict[str, Any]]:
    """Return a list of schematic components with their key attributes."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in project.sch_pages:
        attrs = _component_attrs(page)
        for pid, a in attrs.items():
            des = a.get("Designator")
            if not des or des.startswith("UNIQUE"):
                continue
            if des in seen:
                continue
            seen.add(des)
            rec = {"designator": des, "page_uuid": page.uuid}
            for k in KEEP_ATTRS:
                if k in a and a[k] not in (None, ""):
                    rec[k.lower().replace(" ", "_")] = a[k]
            rec["prefix"] = "".join(c for c in des if c.isalpha())
            out.append(rec)
    out.sort(key=lambda r: (r["prefix"], r["designator"]))
    return out


def extract_net_labels(project: Epro2Project) -> dict[str, list[dict]]:
    """Collect explicit net-label placements (ATTR key == 'NET' and
    'Global Net Name') per net name.

    These are the *named* nets a designer assigned (power rails and signals
    like Q1, CSA_OUT_1). Unnamed wires get auto names ($-prefixed) inside EDA
    and are not labelled here.
    """
    nets: dict[str, list[dict]] = defaultdict(list)
    for page in project.sch_pages:
        for head, body in page.of_type("ATTR"):
            if not isinstance(body, dict):
                continue
            key = body.get("key")
            if key in ("NET", "Global Net Name"):
                name = body.get("value")
                if name:
                    nets[name].append(
                        {
                            "page_uuid": page.uuid,
                            "x": body.get("x"),
                            "y": body.get("y"),
                            "source": key,
                        }
                    )
    return dict(nets)


def summarize_bom(components: list[dict]) -> dict[str, Any]:
    """Group components by value/part for a quick BOM-style summary."""
    by_prefix: dict[str, int] = defaultdict(int)
    cap_values: dict[str, int] = defaultdict(int)
    res_values: dict[str, int] = defaultdict(int)
    ics: list[dict] = []
    for c in components:
        by_prefix[c["prefix"]] += 1
        if c["prefix"] == "C":
            cap_values[c.get("value", "?")] += 1
        elif c["prefix"] == "R":
            res_values[c.get("value", "?")] += 1
        elif c["prefix"] == "U":
            ics.append(
                {
                    "designator": c["designator"],
                    "part": c.get("manufacturer_part") or c.get("supplier_part") or "",
                }
            )
    return {
        "by_prefix": dict(sorted(by_prefix.items(), key=lambda x: -x[1])),
        "capacitor_values": dict(sorted(cap_values.items(), key=lambda x: -x[1])),
        "resistor_values": dict(sorted(res_values.items(), key=lambda x: -x[1])),
        "ics": ics,
    }
