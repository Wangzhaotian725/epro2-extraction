"""Sanity self-test for the epro2x extractor.

Usage:
    python3 test_extractor.py path/to/YourBoard.epro2

Runs the full extraction in-memory and checks that the basic structures are
populated and internally consistent. Exits non-zero on failure. Requires no
third-party packages.
"""

from __future__ import annotations

import os
import sys

from epro2x import Epro2Project
from epro2x import pcb as pcbx
from epro2x import schematic as schx
from epro2x.extract import build_analysis


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        path = argv[1]
    else:
        # 不带参数时，自动取 input/ 下的第一个 .epro2
        import glob
        root = os.path.dirname(os.path.abspath(__file__))
        found = sorted(glob.glob(os.path.join(root, "input", "*.epro2")))
        if not found:
            print("用法: python3 test_extractor.py YourBoard.epro2")
            print("（或把一个 .epro2 放进 input/ 后直接运行本脚本）")
            return 2
        # 优先选体积较大的（通常含原理图，测试覆盖更全）
        path = max(found, key=lambda p: os.path.getsize(p))
        print(f"[自动选取] {path}\n")

    proj = Epro2Project.open(path)
    inv = proj.inventory()
    assert proj.pcb is not None, "no PCB document found"
    print(f"[ok] opened project: {inv}")

    placements = pcbx.extract_placements(proj.pcb)
    coppers = pcbx.copper_layers(proj.pcb)
    traces = pcbx.extract_traces(proj.pcb, coppers)
    vias = pcbx.extract_vias(proj.pcb)
    pours = pcbx.extract_pours(proj.pcb)
    assert placements, "no placements extracted"
    assert coppers, "no copper layers detected"
    print(f"[ok] placements={len(placements)} coppers={list(coppers)} "
          f"traces={len(traces)} vias={len(vias)} pours={len(pours)}")

    # geometry sanity: every trace length non-negative, coords finite
    assert all(t["len_mm"] >= 0 for t in traces), "negative trace length"

    comps = schx.extract_components(proj)
    if comps:
        print(f"[ok] schematic components={len(comps)}")
    else:
        print("[skip] 该工程不含原理图（仅 PCB），跳过原理图元件检查")

    analysis = build_analysis(proj)
    g = analysis["analysis"]["ground_analysis"]
    print(f"[ok] ground nets={g['ground_nets']} split={g['is_split']}")
    if g["is_split"]:
        xc = analysis["analysis"]["split_crossings"]["crossing_nets"]
        print(f"[ok] split-crossing nets={xc}")

    rm = analysis["analysis"]["routing_metrics"]
    print(f"[ok] total routed length={rm['total_len_mm']} mm "
          f"across {list(rm['per_layer'])}")

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
