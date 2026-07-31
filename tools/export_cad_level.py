#!/usr/bin/env python3
"""Export the Lake Perris DXF into compact browser-friendly scene data.

The DXF remains the authority. This file only converts its native coordinates
into the Three.js world coordinate system used by the SSBD web level.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import disassemble


CAD_DECK = (41496.73955020502, 15045.14901826808)
WORLD_DECK = (14.5, 42.0)
WORLD_SCALE = 0.02685
WORLD_ROTATION = 3.3297
MIRROR_EAST_WEST = True

GEOMETRY_LAYERS = {
    "SCRIM 6' FENCE",
    "SCRIM 8' FENCE",
    "Fence Line",
    "Bike Rack",
    "Stages",
    "Stage-Main",
    "Tents",
    "Stretch Tents",
    "Food",
    "Vendors",
    "Porta Potties _ Bathroom Trucks",
    "Parking",
    "Park Infrastructure",
    "Fire Exits",
    "Emergency Exits",
    "Traffic",
    "Sponsor Activations",
    "Preparty",
    # Reference-only design layers. The browser uses these outlines to place
    # detailed assets but does not draw the raw CAD polygons over the level.
    "Group Camping",
    "But Area",
    "None",
    "CRASH BARRICADE",
}


def cad_to_world(x: float, y: float) -> list[float]:
    dx, dy = x - CAD_DECK[0], y - CAD_DECK[1]
    c, s = math.cos(WORLD_ROTATION), math.sin(WORLD_ROTATION)
    world_x = WORLD_SCALE * (c * dx - s * dy)
    if MIRROR_EAST_WEST:
        world_x *= -1
    return [
        round(WORLD_DECK[0] + world_x, 4),
        round(WORLD_DECK[1] + WORLD_SCALE * (s * dx + c * dy), 4),
    ]


def cad_angle_to_world(angle: float) -> float:
    dx, dy = math.cos(angle), math.sin(angle)
    c, s = math.cos(WORLD_ROTATION), math.sin(WORLD_ROTATION)
    world_x, world_z = c * dx - s * dy, s * dx + c * dy
    if MIRROR_EAST_WEST:
        world_x *= -1
    return math.atan2(-world_z, world_x)


def clean_text(value: str) -> str:
    value = value.replace("\\P", " / ")
    value = re.sub(r"\\[A-Za-z][^;]*;", "", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def polyline_points(entity) -> list[list[float]]:
    kind = entity.dxftype()
    if kind == "LINE":
        return [
            cad_to_world(entity.dxf.start.x, entity.dxf.start.y),
            cad_to_world(entity.dxf.end.x, entity.dxf.end.y),
        ]
    if kind == "LWPOLYLINE":
        points = [cad_to_world(x, y) for x, y, *_ in entity.get_points()]
        if entity.closed and points and points[0] != points[-1]:
            points.append(points[0])
        return points
    if kind == "POLYLINE":
        points = [cad_to_world(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        if entity.is_closed and points and points[0] != points[-1]:
            points.append(points[0])
        return points
    if kind == "SPLINE":
        try:
            return [cad_to_world(p.x, p.y) for p in entity.flattening(25.0)]
        except Exception:
            return []
    if kind == "CIRCLE":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        return [
            cad_to_world(
                center.x + math.cos(i / 24 * math.tau) * radius,
                center.y + math.sin(i / 24 * math.tau) * radius,
            )
            for i in range(25)
        ]
    return []


def load_dxf(path: Path):
    # The transferred file contains NUL padding in a few numeric records.
    # Sanitizing a temporary copy preserves the source while making it readable.
    raw = path.read_bytes().replace(b"\x00", b"")
    with tempfile.NamedTemporaryFile(suffix=".dxf") as tmp:
        tmp.write(raw)
        tmp.flush()
        return ezdxf.readfile(tmp.name)


def convex_hull(points: list[list[float]]) -> list[list[float]]:
    points = sorted({(p[0], p[1]) for p in points})
    if len(points) <= 1:
        return [list(p) for p in points]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


def oriented_bounds(points: list[list[float]]) -> dict | None:
    hull = convex_hull(points)
    if len(hull) < 2:
        return None
    best = None
    for i, p in enumerate(hull):
        q = hull[(i + 1) % len(hull)]
        dx, dz = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dz)
        if length < 1e-9:
            continue
        ux, uz = dx / length, dz / length
        vx, vz = -uz, ux
        us = [x * ux + z * uz for x, z in hull]
        vs = [x * vx + z * vz for x, z in hull]
        width, depth = max(us) - min(us), max(vs) - min(vs)
        candidate = (width * depth, ux, uz, vx, vz, min(us), max(us), min(vs), max(vs))
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        return None
    _, ux, uz, vx, vz, u0, u1, v0, v1 = best
    # Keep width on the long axis so asset builders have a stable convention.
    width, depth = u1 - u0, v1 - v0
    if depth > width:
        ux, uz, vx, vz = vx, vz, -ux, -uz
        u0, u1, v0, v1 = v0, v1, -u1, -u0
        width, depth = u1 - u0, v1 - v0
    cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    return {
        "point": [round(cu * ux + cv * vx, 4), round(cu * uz + cv * vz, 4)],
        "width": round(width, 4),
        "depth": round(depth, 4),
        "rotation": round(math.atan2(-uz, ux), 5),
    }


def insert_bounds(entity) -> dict | None:
    points: list[list[float]] = []
    min_z, max_z = math.inf, -math.inf
    try:
        primitives = disassemble.to_primitives(
            disassemble.recursive_decompose([entity]),
            max_flattening_distance=10.0,
        )
        vertices = list(disassemble.to_vertices(primitives))
    except Exception:
        return None
    for vertex in vertices:
        min_z = min(min_z, vertex.z)
        max_z = max(max_z, vertex.z)
        points.append(cad_to_world(vertex.x, vertex.y))
    result = oriented_bounds(points)
    if result is not None:
        result["height"] = round(max(0.0, max_z - min_z) * WORLD_SCALE, 4)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dxf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    doc = load_dxf(args.dxf)
    model = doc.modelspace()
    paths: list[dict] = []
    anchors: list[dict] = []
    inserts: list[dict] = []
    skipped = Counter()

    for entity in model:
        layer = entity.dxf.layer
        kind = entity.dxftype()
        if kind in {"TEXT", "MTEXT"}:
            text = clean_text(entity.dxf.text if kind == "TEXT" else entity.text)
            if text:
                point = entity.dxf.insert
                direction = entity.dxf.get("text_direction", None)
                angle = (
                    math.atan2(direction.y, direction.x)
                    if direction is not None
                    else math.radians(float(entity.dxf.rotation or 0))
                )
                anchors.append({
                    "text": text,
                    "layer": layer,
                    "point": cad_to_world(point.x, point.y),
                    "rotation": round(cad_angle_to_world(angle), 5),
                })
            continue
        if kind == "INSERT" and layer in GEOMETRY_LAYERS:
            point = entity.dxf.insert
            item = {
                "name": entity.dxf.name,
                "layer": layer,
                "point": cad_to_world(point.x, point.y),
                "rotation": round(math.radians(float(entity.dxf.rotation or 0)) + WORLD_ROTATION, 5),
                "scale": [
                    round(abs(float(entity.dxf.xscale or 1)) * WORLD_SCALE, 5),
                    round(abs(float(entity.dxf.yscale or 1)) * WORLD_SCALE, 5),
                ],
            }
            bounds = insert_bounds(entity)
            if bounds is not None:
                # Group-70 contains stairs and loose production geometry outside
                # the actual stage deck. Its CAD deck/oriented structural bounds
                # were measured separately; do not let accessories enlarge it.
                if entity.dxf.name == "Group-70":
                    bounds = {
                        "point": [24.2618, 26.5208],
                        "width": 26.8163,
                        "depth": 11.0286,
                        "rotation": 0.86849,
                        "height": 15.9110,
                    }
                # Tent block graphics include guy lines/feet beyond the printed
                # rental size. Preserve their CAD center/rotation, but use the
                # named dimensions for the physical asset.
                tent_size = re.search(r"Event Tent (\d+)x(\d+)", entity.dxf.name)
                if tent_size:
                    a, b = (float(v) * 0.3048 for v in tent_size.groups())
                    bounds["width"], bounds["depth"] = round(max(a, b), 4), round(min(a, b), 4)
                if entity.dxf.name == "Event Tent 40x60 Event 2 (2D)":
                    bounds["width"] = bounds["depth"] = round(40 * 0.3048, 4)
                item["bounds"] = bounds
            inserts.append(item)
            continue
        if layer not in GEOMETRY_LAYERS:
            continue
        points = polyline_points(entity)
        if len(points) >= 2:
            paths.append({"layer": layer, "closed": points[0] == points[-1], "points": points})
        else:
            skipped[(layer, kind)] += 1

    output = {
        "schema": "ssbd-cad-level-v1",
        "source": args.dxf.name,
        "transform": {
            "cadDeck": CAD_DECK,
            "worldDeck": WORLD_DECK,
            "scale": WORLD_SCALE,
            "rotation": WORLD_ROTATION,
            "mirrorEastWest": MIRROR_EAST_WEST,
        },
        "stats": {
            "entities": len(model),
            "paths": len(paths),
            "anchors": len(anchors),
            "inserts": len(inserts),
            "skipped": {f"{a}/{b}": n for (a, b), n in sorted(skipped.items())},
        },
        "paths": paths,
        "anchors": anchors,
        "inserts": inserts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(output["stats"], indent=2))


if __name__ == "__main__":
    main()
