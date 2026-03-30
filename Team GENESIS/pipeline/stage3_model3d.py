"""
Stage 3 — 2D → 3D Model Generation
=====================================
Converts the geometry graph into a Three.js-renderable JSON scene.

Extrusion rules:
  • Floor height: 3.0 m (as per PS specification)
  • Load-bearing walls: width = 0.23 m (230mm brick)
  • Partition walls: width = 0.10 m (100mm AAC)
  • Floor slab: 0.125 m thick at y=0
  • Roof slab: 0.15 m thick at y=3.0
  • Columns: 0.3×0.3 m placed at LB junction nodes

Returns a JSON-serialisable dict for Three.js rendering.
"""

import math


FLOOR_HEIGHT   = 3.0      # metres
LB_THICKNESS   = 0.23     # load-bearing wall width (m)
PAR_THICKNESS  = 0.10     # partition wall width (m)
SLAB_THICK     = 0.125    # floor slab
ROOF_THICK     = 0.15     # roof slab
COL_SIZE       = 0.3      # column cross-section (m)


def _wall_box(x1_px, y1_px, x2_px, y2_px, px_per_m, thickness_m, height_m, is_lb):
    """
    Convert a 2D wall segment to a 3D box (position + size).
    Y axis = up,  X/Z = plan axes.
    px coords → metres.
    """
    x1 = x1_px / px_per_m
    z1 = y1_px / px_per_m   # plan Y → 3D Z
    x2 = x2_px / px_per_m
    z2 = y2_px / px_per_m

    length = math.hypot(x2 - x1, z2 - z1)
    if length < 0.05:
        return None

    cx = (x1 + x2) / 2
    cz = (z1 + z2) / 2
    cy = height_m / 2

    angle = math.atan2(z2 - z1, x2 - x1)   # rotation around Y axis

    return {
        "type": "wall",
        "position": [round(cx, 3), round(cy, 3), round(cz, 3)],
        "size":     [round(length, 3), round(height_m, 3), round(thickness_m, 3)],
        "rotation_y": round(angle, 4),
        "load_bearing": is_lb,
        "color": "#c0392b" if is_lb else "#7f8c8d",
        "opacity": 0.88 if is_lb else 0.72,
    }


def generate_3d_model(geometry: dict, parsed_data: dict) -> dict:
    px_per_m = geometry["scale"]["px_per_m"]
    img_w = geometry["image_size"]["w"]
    img_h = geometry["image_size"]["h"]

    scene_objects = []

    # ── Floor Slab ───────────────────────────────────────────────────────────
    plan_w = img_w / px_per_m
    plan_d = img_h / px_per_m
    scene_objects.append({
        "type": "slab",
        "subtype": "floor",
        "position": [round(plan_w / 2, 2), -SLAB_THICK / 2, round(plan_d / 2, 2)],
        "size":     [round(plan_w, 2), SLAB_THICK, round(plan_d, 2)],
        "rotation_y": 0,
        "color": "#bdc3c7",
        "opacity": 0.9,
    })

    # ── Roof Slab ────────────────────────────────────────────────────────────
    scene_objects.append({
        "type": "slab",
        "subtype": "roof",
        "position": [round(plan_w / 2, 2), FLOOR_HEIGHT + ROOF_THICK / 2, round(plan_d / 2, 2)],
        "size":     [round(plan_w, 2), ROOF_THICK, round(plan_d, 2)],
        "rotation_y": 0,
        "color": "#95a5a6",
        "opacity": 0.45,
    })

    # ── Walls ────────────────────────────────────────────────────────────────
    lb_count = 0
    par_count = 0
    for edge in geometry["edges"]:
        thickness = LB_THICKNESS if edge["load_bearing"] else PAR_THICKNESS
        box = _wall_box(
            edge["x1"], edge["y1"],
            edge["x2"], edge["y2"],
            px_per_m, thickness, FLOOR_HEIGHT, edge["load_bearing"]
        )
        if box:
            box["wall_id"] = edge["wall_id"]
            scene_objects.append(box)
            if edge["load_bearing"]:
                lb_count += 1
            else:
                par_count += 1

    # ── Columns at LB junction nodes ─────────────────────────────────────────
    lb_node_ids = set()
    for e in geometry["edges"]:
        if e["load_bearing"]:
            lb_node_ids.add(e["n1"])
            lb_node_ids.add(e["n2"])

    col_nodes = [n for n in geometry["nodes"] if n["id"] in lb_node_ids and n["type"] in ("T", "X", "L")]
    col_count = 0
    for n in col_nodes:
        cx_m = n["x"] / px_per_m
        cz_m = n["y"] / px_per_m
        scene_objects.append({
            "type": "column",
            "position": [round(cx_m, 3), FLOOR_HEIGHT / 2, round(cz_m, 3)],
            "size":     [COL_SIZE, FLOOR_HEIGHT + ROOF_THICK, COL_SIZE],
            "rotation_y": 0,
            "color": "#2c3e50",
            "opacity": 1.0,
        })
        col_count += 1

    # ── Camera & Scene config ─────────────────────────────────────────────────
    cam_dist = max(plan_w, plan_d) * 1.5
    scene_config = {
        "camera": {
            "position": [plan_w / 2, cam_dist * 0.8, plan_d / 2 + cam_dist],
            "target":   [plan_w / 2, FLOOR_HEIGHT / 2, plan_d / 2],
            "fov": 45,
        },
        "floor_height_m": FLOOR_HEIGHT,
        "plan_w_m": round(plan_w, 2),
        "plan_d_m": round(plan_d, 2),
    }

    model_data = {
        "objects": scene_objects,
        "object_count": len(scene_objects),
        "wall_count_3d": lb_count + par_count,
        "lb_walls_3d": lb_count,
        "partition_walls_3d": par_count,
        "column_count": col_count,
        "scene_config": scene_config,
        "stats": {
            "floor_slabs": 1,
            "roof_slabs": 1,
            "total_objects": len(scene_objects),
        }
    }

    return model_data
