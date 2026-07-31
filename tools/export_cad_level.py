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
                anchors.append({
                    "text": text,
                    "layer": layer,
                    "point": cad_to_world(point.x, point.y),
                    "rotation": round(math.radians(float(entity.dxf.rotation or 0)), 5),
                })
            continue
        if kind == "INSERT" and layer in GEOMETRY_LAYERS:
            point = entity.dxf.insert
            inserts.append({
                "name": entity.dxf.name,
                "layer": layer,
                "point": cad_to_world(point.x, point.y),
                "rotation": round(math.radians(float(entity.dxf.rotation or 0)) + WORLD_ROTATION, 5),
                "scale": [
                    round(abs(float(entity.dxf.xscale or 1)) * WORLD_SCALE, 5),
                    round(abs(float(entity.dxf.yscale or 1)) * WORLD_SCALE, 5),
                ],
            })
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
