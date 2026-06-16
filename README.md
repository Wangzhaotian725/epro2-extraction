# epro2x — Offline extractor for EasyEDA Pro / JLCEDA Pro `.epro2` files

Parses a `.epro2` project entirely offline (standard library only) and writes a
compact, self-contained `analysis.json` plus convenience CSVs. The JSON is the
single file to send for a PCB layout/routing review — it contains the schematic
netlist, component parameters, PCB placement, routing, vias, copper planes, and
pre-computed analysis metrics (routing distribution, ground partition, and exact
ground-split crossings).

No network access, no EasyEDA install, no third-party packages required for
extraction. `matplotlib` is optional and only used for `--diagrams`.

---

## 1. Requirements

- Python 3.10 or newer (uses `X | Y` type syntax).
- Optional: `matplotlib` (only if you want PNG diagrams).

Check your version:

```bash
python3 --version
```

## 2. Install

No install needed — it's a plain package folder. Just unzip and run from the
project root (the folder that contains the `epro2x/` directory).

Optional, for diagrams:

```bash
pip install matplotlib
```

## 3. 运行

**方式一：批量模式（推荐）**

把一个或多个 `.epro2` 文件放进项目的 `input/` 文件夹，然后在项目根目录运行：

```bash
python3 -m epro2x.extract
```

程序会自动扫描 `input/` 下所有 `.epro2`，逐个解析，并把每个工程的结果写到
`output/<工程名>/`。加 `--diagrams` 可同时生成 PNG 图（需 matplotlib）。

也可以用便捷脚本：

```bash
./run_example.sh
```

**方式二：单文件模式**

```bash
python3 -m epro2x.extract path/to/YourBoard.epro2
# 默认输出到 output/<工程名>/；也可用 -o 指定目录：
python3 -m epro2x.extract path/to/YourBoard.epro2 -o some/dir/
```

**输入 / 输出文件夹**

| 文件夹 | 用途 |
|--------|------|
| `input/` | 放待解析的 `.epro2` 文件（可放多个） |
| `output/<工程名>/` | 每个工程的解析结果 |

每个工程的 `output/<工程名>/` 内包含：

| 文件 | 内容 |
|------|------|
| `analysis.json` | **做评审的文件。** 下列全部内容打包成一个文件。 |
| `components.csv` | 原理图元件 + 值 / 厂商料号 / 封装 |
| `placements.csv` | PCB 元件坐标（mm）、所在面、旋转角 |
| `traces.csv` | 每条走线段（mm），含网络、层、线宽 |
| `vias.csv` | 过孔清单（mm），含网络、孔径/焊盘径 |
| `net_summary.csv` | 各网络走线长度与所用层 |
| `diagrams/*.png` | 布局图、各层走线图、地分割图（仅 `--diagrams`） |

> 可自定义文件夹：`--input-dir`、`--output-dir`。

## 4. Use as a library

```python
from epro2x import Epro2Project
from epro2x import pcb, schematic

proj = Epro2Project.open("YourBoard.epro2")
print(proj.inventory())                       # document counts
placements = pcb.extract_placements(proj.pcb)  # list of dicts (mm)
nets = schematic.extract_net_labels(proj)      # named nets -> placements
```

---

## What gets extracted (and why it matters for review)

**Schematic**
- Component list with `Designator`, `Value`, `Manufacturer Part`, `Footprint`.
- BOM-style summary (counts by prefix, capacitor/resistor value histogram, IC list).
- Named nets (power rails and signals the designer labelled). *Note:* unlabelled
  wires get auto names inside EDA and are reported only where a label exists.

**PCB**
- Board extent (mm), copper layers in use, and layer stackup (materials/thickness).
- Component placements in mm, side (Top/Bottom), and rotation.
- All routed segments (net, layer, width, endpoints, length in mm).
- Vias (position, hole/pad diameter, net).
- Copper pours / planes as polygons (used for ground analysis).

**Pre-computed analysis**
- `routing_metrics`: total routed length, per-layer distribution, trace-width
  histogram, and per-net length/layers.
- `ground_analysis`: detects analog/digital ground nets (AGND/GND), which layers
  each pour covers, and ground-via stitching counts.
- `split_crossings`: exact point-in-polygon test of which signal nets cross the
  digital-ground island boundary — the key signal-integrity risk list.

---

## Notes & limitations

- **Read-only.** This tool never modifies your `.epro2`. The format is a
  proprietary append-only document stream; edits must be made in EasyEDA Pro.
- **Coordinates** are converted to millimetres (EasyEDA stores mil). Y is flipped
  to an upright frame (Y up) so positions read naturally and match the diagrams.
- **Net-to-pin connectivity** is taken from the schematic net labels. Pad-level
  net assignment is not stored in the PCB document itself (pads live in the
  footprint library), so trace `net` names are the reliable source on the PCB.
- **Arcs** in copper pours are approximated by their endpoints — fine for area /
  containment (ground-crossing) analysis, not intended for exact arc geometry.
- Tested against EasyEDA Pro editor version 3.2.x project files.

## Project layout

```
epro2-extractor/
├── README.md
├── run_example.sh           # 便捷运行脚本（默认批量模式）
├── test_extractor.py        # 自检脚本（无第三方依赖）
├── input/                   # ← 把待解析的 .epro2 放这里
├── output/                  # ← 解析结果自动输出到这里（按工程名分子文件夹）
└── epro2x/
    ├── __init__.py
    ├── core.py              # .epro2 解压 + .epru 文档流解析
    ├── geometry.py          # mil->mm、多边形展开、点在多边形内判定
    ├── schematic.py         # 元件、参数、网络标签、BOM
    ├── pcb.py               # 布局、走线、过孔、铺铜、各项指标
    ├── diagrams.py          # 可选的 matplotlib 绘图
    └── extract.py           # 命令行入口（python -m epro2x.extract）
```
