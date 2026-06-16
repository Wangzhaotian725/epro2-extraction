"""Command-line extractor: `.epro2` -> structured JSON + CSV bundle.

Default (batch) mode — scans the project's `input/` folder and writes each
project's results to `output/<project-name>/`:

    python -m epro2x.extract
    python -m epro2x.extract --diagrams        # also draw PNGs (needs matplotlib)

Single-file mode — process one specific file to a chosen folder:

    python -m epro2x.extract path/to/Board.epro2 -o some/dir/

Per-project outputs:
    analysis.json        one bundle with everything below (the file to send for review)
    components.csv        schematic components + parameters
    placements.csv        PCB component positions (mm)
    traces.csv           routed segments (mm)
    vias.csv             via list (mm)
    net_summary.csv      per-net routed length / layers
    diagrams/*.png       (only with --diagrams)

`analysis.json` is self-contained; the CSVs are conveniences for spreadsheets.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

# Project root = the folder that contains this `epro2x/` package.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT_DIR = os.path.join(_ROOT, "input")
DEFAULT_OUTPUT_DIR = os.path.join(_ROOT, "output")

from . import __version__
from .core import Epro2Project
from . import pcb as pcbx
from . import schematic as schx


def _write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def build_analysis(project: Epro2Project) -> dict:
    pcb = project.pcb
    if pcb is None:
        raise SystemExit("ERROR: no PCB document found in project.")

    coppers = pcbx.copper_layers(pcb)
    placements = pcbx.extract_placements(pcb)
    traces = pcbx.extract_traces(pcb, coppers)
    vias = pcbx.extract_vias(pcb)
    pours = pcbx.extract_pours(pcb)
    stackup = pcbx.extract_stackup(pcb)

    components = schx.extract_components(project)
    net_labels = schx.extract_net_labels(project)
    bom = schx.summarize_bom(components)

    routing = pcbx.routing_metrics(traces, coppers)
    grounds = pcbx.ground_analysis(pours, vias)
    extent = pcbx.board_extent(placements, traces)

    # crossing analysis only meaningful when a split exists
    crossings = {}
    if grounds["is_split"]:
        # pick the digital ground = the GND net that is NOT the analog one
        digital = next((n for n in grounds["ground_nets"] if n.upper() == "GND"), None)
        if digital is None:
            # fall back: the ground net with the smaller pour bbox is the island
            digital = grounds["ground_nets"][0]
        crossings = pcbx.split_crossings(traces, pours, digital_ground=digital)

    return {
        "extractor_version": __version__,
        "project_meta": project.meta,
        "document_inventory": project.inventory(),
        "board": {
            "extent": extent,
            "copper_layers": {str(k): v for k, v in coppers.items()},
            "stackup": stackup,
        },
        "schematic": {
            "component_count": len(components),
            "bom_summary": bom,
            "components": components,
            "named_nets": sorted(net_labels.keys()),
            "net_label_placements": net_labels,
        },
        "pcb": {
            "placement_count": len(placements),
            "trace_segment_count": len(traces),
            "via_count": len(vias),
            "pour_count": len(pours),
            "placements": placements,
            # full traces/vias can be large; included for completeness
            "traces": traces,
            "vias": vias,
            "pours": [
                {k: v for k, v in p.items() if k != "polygons"}
                | {"polygon_count": len(p["polygons"])}
                for p in pours
            ],
        },
        "analysis": {
            "routing_metrics": routing,
            "ground_analysis": grounds,
            "split_crossings": crossings,
        },
    }


def write_outputs(analysis: dict, project: Epro2Project, outdir: str, diagrams: bool) -> None:
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(outdir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    comps = analysis["schematic"]["components"]
    _write_csv(
        os.path.join(outdir, "components.csv"), comps,
        ["designator", "prefix", "value", "manufacturer_part", "device", "footprint"],
    )
    _write_csv(
        os.path.join(outdir, "placements.csv"), analysis["pcb"]["placements"],
        ["designator", "x_mm", "y_mm", "side", "angle", "footprint"],
    )
    _write_csv(
        os.path.join(outdir, "traces.csv"), analysis["pcb"]["traces"],
        ["net", "layer_id", "x1_mm", "y1_mm", "x2_mm", "y2_mm", "width_mil", "len_mm"],
    )
    _write_csv(
        os.path.join(outdir, "vias.csv"), analysis["pcb"]["vias"],
        ["net", "x_mm", "y_mm", "hole_mm", "pad_mm", "type"],
    )
    net_rows = [
        {"net": n, **v} for n, v in analysis["analysis"]["routing_metrics"]["per_net"].items()
    ]
    _write_csv(
        os.path.join(outdir, "net_summary.csv"), net_rows,
        ["net", "len_mm", "segments", "layers"],
    )

    if diagrams:
        try:
            from .diagrams import render_all
        except Exception as e:  # pragma: no cover
            print(f"(diagrams skipped: {e})", file=sys.stderr)
            return
        render_all(project, os.path.join(outdir, "diagrams"))


def _print_summary(analysis: dict, outdir: str) -> None:
    b = analysis["board"]["extent"]
    print(f"  工程名称: {analysis['project_meta'].get('title', '?')}")
    print(f"  文档清单: {analysis['document_inventory']}")
    if b:
        print(f"  板尺寸: {b.get('width_mm')} x {b.get('height_mm')} mm")
    print(f"  原理图元件数: {analysis['schematic']['component_count']}")
    print(f"  布局元件: {analysis['pcb']['placement_count']}  "
          f"走线段: {analysis['pcb']['trace_segment_count']}  "
          f"过孔: {analysis['pcb']['via_count']}")
    g = analysis["analysis"]["ground_analysis"]
    print(f"  地网络: {g['ground_nets']}  是否分割={g['is_split']}")
    xc = analysis["analysis"]["split_crossings"].get("crossing_nets", {})
    if xc:
        print(f"  跨越地分割缝的网络: {xc}")
    print(f"  -> 已写出: {os.path.join(outdir, 'analysis.json')} (含 CSV)")


def process_one(epro2_path: str, outdir: str, diagrams: bool, quiet: bool) -> dict:
    """Parse a single .epro2 and write its outputs into `outdir`."""
    project = Epro2Project.open(epro2_path)
    analysis = build_analysis(project)
    write_outputs(analysis, project, outdir, diagrams)
    if not quiet:
        _print_summary(analysis, outdir)
    return analysis


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="从 EasyEDA Pro / 嘉立创EDA专业版 .epro2 文件中提取原理图与PCB数据。"
    )
    ap.add_argument(
        "epro2", nargs="?", default=None,
        help="（可选）指定单个 .epro2 文件；不填则批量处理 input/ 文件夹下所有 .epro2",
    )
    ap.add_argument(
        "-o", "--outdir", default=None,
        help="输出目录。单文件模式默认 output/<工程名>/；批量模式忽略此项",
    )
    ap.add_argument(
        "--input-dir", default=DEFAULT_INPUT_DIR,
        help=f"批量模式的输入文件夹（默认: {DEFAULT_INPUT_DIR}）",
    )
    ap.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"批量模式的输出根文件夹（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    ap.add_argument("--diagrams", action="store_true", help="同时渲染 PNG 图（需要 matplotlib）")
    ap.add_argument("--quiet", action="store_true", help="不打印汇总信息")
    args = ap.parse_args(argv)

    # ---- 单文件模式 ----
    if args.epro2:
        name = os.path.splitext(os.path.basename(args.epro2))[0]
        outdir = args.outdir or os.path.join(args.output_dir, name)
        if not args.quiet:
            print(f"[单文件模式] 解析: {args.epro2}")
        process_one(args.epro2, outdir, args.diagrams, args.quiet)
        return 0

    # ---- 批量模式：扫描 input/ ----
    os.makedirs(args.input_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.input_dir, "*.epro2")))
    if not files:
        print(f"未在输入文件夹中找到任何 .epro2 文件：{args.input_dir}")
        print("请把待解析的 .epro2 文件放进该文件夹后重新运行。")
        return 1

    print(f"[批量模式] 在 {args.input_dir} 中找到 {len(files)} 个 .epro2 文件\n")
    ok = 0
    for i, f in enumerate(files, 1):
        name = os.path.splitext(os.path.basename(f))[0]
        outdir = os.path.join(args.output_dir, name)
        print(f"[{i}/{len(files)}] 解析: {os.path.basename(f)}")
        try:
            process_one(f, outdir, args.diagrams, args.quiet)
            ok += 1
        except Exception as e:  # 单个文件失败不影响其余文件
            print(f"  !! 解析失败: {e}")
        print()
    print(f"完成：成功 {ok}/{len(files)}。结果在: {args.output_dir}/<工程名>/")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
