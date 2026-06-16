"""Shared helpers: unit conversion and geometry."""

from __future__ import annotations

import math

# EasyEDA Pro stores PCB coordinates in mil (1 mil = 0.0254 mm).
# Verified against this project: a 24.0158-"unit" via = 0.61 mm pad => 1 unit = 1 mil.
MIL_TO_MM = 0.0254


def mil_to_mm(v: float) -> float:
    return v * MIL_TO_MM


def seg_len_mm(x1: float, y1: float, x2: float, y2: float) -> float:
    """Length of a segment given in mil, returned in mm."""
    return math.hypot(x2 - x1, y2 - y1) * MIL_TO_MM


def flatten_path_points(path: list) -> list[list[tuple[float, float]]]:
    """Convert an EasyEDA pour/region/fill `path` into polygons of (x, y) in mm.

    A path is a list of sub-paths. Each sub-path is a flat list mixing numbers
    (coordinate pairs, in mil) and string tokens ("L", "ARC", "R", ...). We keep
    the vertex coordinates and drop the drawing-command tokens; arcs are
    approximated by their endpoints (sufficient for area / containment work).
    """
    polys: list[list[tuple[float, float]]] = []
    for sub in path:
        if not isinstance(sub, list):
            continue
        pts: list[tuple[float, float]] = []
        i = 0
        while i < len(sub):
            tok = sub[i]
            if isinstance(tok, str):
                # "ARC" is followed by an angle then a point; "R" denotes a rect.
                # We simply skip the token and let the following numbers be read
                # as the next coordinate pair.
                i += 1
                continue
            # numeric coordinate pair
            if i + 1 < len(sub) and not isinstance(sub[i + 1], str):
                pts.append((mil_to_mm(sub[i]), mil_to_mm(sub[i + 1])))
                i += 2
            else:
                i += 1
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside
