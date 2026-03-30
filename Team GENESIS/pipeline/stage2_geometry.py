"""
Stage 2 — Geometry Reconstruction
===================================
Converts parsed elements into a structural graph:
  • Nodes  = corners / junctions  (with type: L / T / X)
  • Edges  = wall segments (with load-bearing classification)

Wall classification rules:
  1. Outer-boundary walls → load-bearing
  2. Longest continuous horizontal/vertical spines → load-bearing
  3. Short/thin internal segments → partition

Returns geometry_data dict consumed by Stage 3.
"""

import math
from collections import defaultdict


def _dist(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def _endpoint_cluster(walls, tol=12):
    """
    Cluster wall endpoints that are within `tol` pixels of each other
    into shared nodes. Returns node list and updated walls with node ids.
    """
    nodes = []   # list of {"id", "x", "y", "type"}
    node_map = {}   # (snapped_x, snapped_y) → node_id

    def _get_or_create(px, py):
        sx, sy = round(px / tol) * tol, round(py / tol) * tol
        key = (sx, sy)
        if key not in node_map:
            nid = len(nodes)
            nodes.append({"id": nid, "x": int(px), "y": int(py), "type": "corner", "walls": []})
            node_map[key] = nid
        return node_map[key]

    walls_out = []
    for w in walls:
        n1 = _get_or_create(w["x1"], w["y1"])
        n2 = _get_or_create(w["x2"], w["y2"])
        nodes[n1]["walls"].append(w["id"])
        nodes[n2]["walls"].append(w["id"])
        walls_out.append({**w, "node_start": n1, "node_end": n2})

    # Classify node types by degree (number of connected walls)
    for n in nodes:
        deg = len(set(n["walls"]))
        n["type"] = "X" if deg >= 4 else ("T" if deg == 3 else ("L" if deg == 2 else "end"))

    return nodes, walls_out


def _outer_walls(walls, outer_box, margin=20):
    """Mark walls that touch the outer boundary as outer=True."""
    ox, oy = outer_box["x"], outer_box["y"]
    ox2, oy2 = ox + outer_box["w"], oy + outer_box["h"]
    result = []
    for w in walls:
        is_outer = (
            min(w["x1"], w["x2"]) <= ox + margin or
            max(w["x1"], w["x2"]) >= ox2 - margin or
            min(w["y1"], w["y2"]) <= oy + margin or
            max(w["y1"], w["y2"]) >= oy2 - margin
        )
        result.append({**w, "is_outer": is_outer})
    return result


def _find_spines(walls, img_w, img_h, min_span_ratio=0.35):
    """
    Long continuous lines that span ≥ 35% of the plan dimension
    are classified as structural spines.
    """
    spines = set()
    for w in walls:
        span = w["length_px"] / (img_w if w["orientation"] == "horizontal" else img_h)
        if span >= min_span_ratio:
            spines.add(w["id"])
    return spines


def _classify_load_bearing(walls, outer_box, img_w, img_h):
    """
    Rule-based load-bearing classification:
      LB  → outer walls + structural spines + long walls near centre
      PAR → everything else
    """
    spine_ids = _find_spines(walls, img_w, img_h)
    outer = _outer_walls(walls, outer_box)

    result = []
    for w in outer:
        is_spine = w["id"] in spine_ids
        is_lb = w["is_outer"] or is_spine
        # Additional rule: walls longer than 40% of plan width/height are LB
        span_h = w["length_px"] / img_w
        span_v = w["length_px"] / img_h
        if span_h > 0.4 or span_v > 0.4:
            is_lb = True
        result.append({
            **w,
            "load_bearing": is_lb,
            "wall_type": "load_bearing" if is_lb else "partition",
            "is_spine": is_spine,
        })
    return result


def _compute_spans(rooms, px_per_m):
    """For each room, compute clear span in metres (longest dimension)."""
    spans = []
    for r in rooms:
        bw = r["bbox"]["w"] / px_per_m
        bh = r["bbox"]["h"] / px_per_m
        max_span = max(bw, bh)
        spans.append({
            "room_id": r["id"],
            "room_label": r["label"],
            "span_x_m": round(bw, 2),
            "span_y_m": round(bh, 2),
            "max_span_m": round(max_span, 2),
            "needs_beam": max_span > 4.5,
            "needs_steel": max_span > 5.0,
        })
    return spans


def reconstruct_geometry(parsed_data: dict) -> dict:
    walls  = parsed_data["walls"]
    rooms  = parsed_data["rooms"]
    outer  = parsed_data["outer_boundary"]
    img_w  = parsed_data["image_size"]["w"]
    img_h  = parsed_data["image_size"]["h"]
    px_per_m = parsed_data["scale"]["px_per_m"]

    # Build node graph
    nodes, walls_with_nodes = _endpoint_cluster(walls)

    # Classify walls
    classified_walls = _classify_load_bearing(walls_with_nodes, outer, img_w, img_h)

    lb_walls  = [w for w in classified_walls if w["load_bearing"]]
    par_walls = [w for w in classified_walls if not w["load_bearing"]]

    # Compute spans
    spans = _compute_spans(rooms, px_per_m)
    problem_spans = [s for s in spans if s["needs_beam"]]

    # Build edges list for 3D
    edges = []
    for w in classified_walls:
        n1 = next((n for n in nodes if n["id"] == w["node_start"]), None)
        n2 = next((n for n in nodes if n["id"] == w["node_end"]), None)
        if n1 and n2:
            edges.append({
                "wall_id": w["id"],
                "n1": n1["id"],
                "n2": n2["id"],
                "x1": n1["x"], "y1": n1["y"],
                "x2": n2["x"], "y2": n2["y"],
                "length_m": w.get("length_m", 0),
                "orientation": w["orientation"],
                "wall_type": w["wall_type"],
                "load_bearing": w["load_bearing"],
            })

    geometry = {
        "nodes": nodes,
        "node_count": len(nodes),
        "edges": edges,
        "classified_walls": classified_walls,
        "load_bearing_walls": lb_walls,
        "partition_walls": par_walls,
        "lb_count": len(lb_walls),
        "partition_count": len(par_walls),
        "room_spans": spans,
        "structural_concerns": [
            {
                "room_id": s["room_id"],
                "label": s["room_label"],
                "max_span_m": s["max_span_m"],
                "severity": "HIGH" if s["needs_steel"] else "MEDIUM",
                "message": (
                    f"Span of {s['max_span_m']}m exceeds 5m — steel frame or precast beam required."
                    if s["needs_steel"]
                    else f"Span of {s['max_span_m']}m (4.5–5m) — RCC beam strongly recommended."
                )
            }
            for s in problem_spans
        ],
        "outer_boundary": outer,
        "scale": parsed_data["scale"],
        "image_size": parsed_data["image_size"],
    }

    return geometry
