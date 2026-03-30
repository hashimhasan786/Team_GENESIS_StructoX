"""
Stage 4 — Material Analysis & Cost–Strength Tradeoff
======================================================
Uses the PS-provided starter material database.
Computes a weighted tradeoff score per structural element type.

Score formula (as required by PS):
    score = w_strength * strength_norm  +  w_durability * durability_norm
            - w_cost    * cost_norm

Weights differ by structural role (justifiable engineering reason):
  Load-bearing:  strength=0.45, durability=0.35, cost=0.20
  Partition:     strength=0.20, durability=0.30, cost=0.50
  Slab/Column:   strength=0.50, durability=0.35, cost=0.15
"""

# ── Starter Material Database (as given in PS) ──────────────────────────────

MATERIAL_DB = [
    {
        "id": "aac",
        "name": "AAC Blocks",
        "cost_level": 1,        # 1=Low, 2=Med-Low, 3=Medium, 4=Med-High, 5=High
        "strength_level": 2,    # 1=Low … 5=Very High
        "durability_level": 4,
        "cost_inr_sqft": 210,
        "best_use": "Partition walls",
        "weight_kg_m3": 600,
        "compressive_mpa": 4,
        "notes": "Lightweight, good thermal insulation, low structural strength",
    },
    {
        "id": "red_brick",
        "name": "Red Brick (IS:1077)",
        "cost_level": 3,
        "strength_level": 4,
        "durability_level": 3,
        "cost_inr_sqft": 280,
        "best_use": "Load-bearing walls",
        "weight_kg_m3": 1900,
        "compressive_mpa": 10,
        "notes": "Traditional LB wall material, moderate durability, proven performance",
    },
    {
        "id": "rcc",
        "name": "RCC (M25)",
        "cost_level": 5,
        "strength_level": 5,
        "durability_level": 5,
        "cost_inr_sqft": 420,
        "best_use": "Columns, slabs, beams",
        "weight_kg_m3": 2400,
        "compressive_mpa": 25,
        "notes": "Best structural performance, highest cost, fire-resistant",
    },
    {
        "id": "steel_frame",
        "name": "Steel Frame",
        "cost_level": 5,
        "strength_level": 5,
        "durability_level": 5,
        "cost_inr_rmt": 980,
        "best_use": "Long spans (>5m), columns",
        "weight_kg_m3": 7850,
        "compressive_mpa": 250,
        "notes": "Required for spans >5m, high cost, excellent strength-to-weight",
    },
    {
        "id": "hollow_block",
        "name": "Hollow Concrete Block",
        "cost_level": 2,
        "strength_level": 2,
        "durability_level": 3,
        "cost_inr_sqft": 190,
        "best_use": "Non-structural walls",
        "weight_kg_m3": 1100,
        "compressive_mpa": 6,
        "notes": "Cost-effective non-structural partitions, moderate durability",
    },
    {
        "id": "fly_ash_brick",
        "name": "Fly Ash Brick",
        "cost_level": 1,
        "strength_level": 3,
        "durability_level": 4,
        "cost_inr_sqft": 165,
        "best_use": "General walling",
        "weight_kg_m3": 1600,
        "compressive_mpa": 7.5,
        "notes": "Eco-friendly, good durability, lower cost than red brick",
    },
    {
        "id": "precast",
        "name": "Precast Concrete Panel",
        "cost_level": 4,
        "strength_level": 4,
        "durability_level": 5,
        "cost_inr_sqft": 390,
        "best_use": "Structural walls, slabs",
        "weight_kg_m3": 2300,
        "compressive_mpa": 35,
        "notes": "Factory precision, faster construction, excellent for structural slabs",
    },
    {
        "id": "rcc_m30",
        "name": "RCC (M30)",
        "cost_level": 5,
        "strength_level": 5,
        "durability_level": 5,
        "cost_inr_sqft": 480,
        "best_use": "Heavy columns, transfer beams",
        "weight_kg_m3": 2400,
        "compressive_mpa": 30,
        "notes": "High-grade concrete for critical structural members",
    },
]

# ── Weight profiles per element category ────────────────────────────────────

WEIGHT_PROFILES = {
    "load_bearing_wall": {
        "strength":    0.45,
        "durability":  0.35,
        "cost":        0.20,
        "rationale": "LB walls carry floor/roof loads — strength and durability dominate. "
                     "Cost savings on LB walls risk structural failure.",
    },
    "partition_wall": {
        "strength":    0.20,
        "durability":  0.30,
        "cost":        0.50,
        "rationale": "Partition walls are non-structural — cost efficiency is the primary driver. "
                     "Minimum durability ensures longevity without structural demand.",
    },
    "floor_slab": {
        "strength":    0.50,
        "durability":  0.35,
        "cost":        0.15,
        "rationale": "Slabs experience bending and shear — high strength is critical. "
                     "Long service life demands durability over cost.",
    },
    "column": {
        "strength":    0.55,
        "durability":  0.35,
        "cost":        0.10,
        "rationale": "Columns are primary structural members — failure is catastrophic. "
                     "Strength is weighted highest; cost is a secondary consideration.",
    },
    "roof_slab": {
        "strength":    0.40,
        "durability":  0.45,
        "cost":        0.15,
        "rationale": "Roof exposed to weather — durability is paramount. "
                     "Moderate strength sufficient for dead/live roof loads.",
    },
    "long_span_beam": {
        "strength":    0.55,
        "durability":  0.30,
        "cost":        0.15,
        "rationale": "Spans >4.5m require maximum bending strength. "
                     "Steel frame mandatory for spans >5m regardless of cost.",
    },
}

# ── Scoring ──────────────────────────────────────────────────────────────────

def _normalise(val, lo=1, hi=5):
    return (val - lo) / (hi - lo)


def score_material(mat: dict, weights: dict) -> float:
    s = _normalise(mat["strength_level"])
    d = _normalise(mat["durability_level"])
    c = _normalise(mat["cost_level"])
    return round(
        weights["strength"]   * s
        + weights["durability"] * d
        - weights["cost"]       * c,
        4
    )


def recommend_for_element(element_type: str, top_n=3, force_ids=None) -> list:
    """Return top_n ranked materials for a structural element type."""
    weights = WEIGHT_PROFILES[element_type]

    candidates = MATERIAL_DB
    if force_ids:
        candidates = [m for m in MATERIAL_DB if m["id"] in force_ids]

    scored = []
    for mat in candidates:
        sc = score_material(mat, weights)
        scored.append({
            **mat,
            "tradeoff_score": sc,
            "element_type": element_type,
            "weight_profile": weights,
        })

    scored.sort(key=lambda x: x["tradeoff_score"], reverse=True)
    ranked = []
    for rank, m in enumerate(scored[:top_n], 1):
        m["rank"] = rank
        ranked.append(m)
    return ranked


# ── Master analysis ──────────────────────────────────────────────────────────

def analyse_materials(geometry: dict) -> dict:
    """Run full material analysis for all structural element categories."""

    has_long_span = any(
        s["needs_beam"] for s in geometry.get("room_spans", [])
    )
    has_steel_span = any(
        s["needs_steel"] for s in geometry.get("room_spans", [])
    )

    recommendations = {}

    # Load-bearing walls
    lb_ids = ["red_brick", "fly_ash_brick", "precast", "rcc"]
    recommendations["load_bearing_wall"] = {
        "element": "Load-Bearing Walls",
        "count": geometry.get("lb_count", 0),
        "ranked_options": recommend_for_element("load_bearing_wall", top_n=3, force_ids=lb_ids),
        "selected": "red_brick",
        "weight_profile": WEIGHT_PROFILES["load_bearing_wall"],
    }

    # Partition walls
    par_ids = ["aac", "hollow_block", "fly_ash_brick", "red_brick"]
    recommendations["partition_wall"] = {
        "element": "Partition Walls",
        "count": geometry.get("partition_count", 0),
        "ranked_options": recommend_for_element("partition_wall", top_n=3, force_ids=par_ids),
        "selected": "aac",
        "weight_profile": WEIGHT_PROFILES["partition_wall"],
    }

    # Floor slab
    slab_ids = ["rcc", "precast", "rcc_m30"]
    recommendations["floor_slab"] = {
        "element": "Floor Slab",
        "count": 1,
        "ranked_options": recommend_for_element("floor_slab", top_n=3, force_ids=slab_ids),
        "selected": "rcc",
        "weight_profile": WEIGHT_PROFILES["floor_slab"],
    }

    # Columns
    col_ids = ["rcc_m30", "rcc", "steel_frame"]
    recommendations["column"] = {
        "element": "Columns",
        "count": geometry.get("node_count", 0),
        "ranked_options": recommend_for_element("column", top_n=3, force_ids=col_ids),
        "selected": "rcc_m30",
        "weight_profile": WEIGHT_PROFILES["column"],
    }

    # Roof slab
    roof_ids = ["precast", "rcc", "rcc_m30"]
    recommendations["roof_slab"] = {
        "element": "Roof Slab",
        "count": 1,
        "ranked_options": recommend_for_element("roof_slab", top_n=3, force_ids=roof_ids),
        "selected": "precast",
        "weight_profile": WEIGHT_PROFILES["roof_slab"],
    }

    # Long-span beam (conditional)
    if has_long_span:
        span_ids = ["steel_frame", "rcc_m30", "precast"] if has_steel_span else ["rcc_m30", "precast", "rcc"]
        recommendations["long_span_beam"] = {
            "element": "Long-Span Beams",
            "count": sum(1 for s in geometry["room_spans"] if s["needs_beam"]),
            "ranked_options": recommend_for_element("long_span_beam", top_n=3, force_ids=span_ids),
            "selected": "steel_frame" if has_steel_span else "rcc_m30",
            "weight_profile": WEIGHT_PROFILES["long_span_beam"],
        }

    # Cost summary (approximate)
    cost_summary = _cost_summary(recommendations, geometry)

    return {
        "recommendations": recommendations,
        "cost_summary": cost_summary,
        "structural_flags": {
            "has_long_span": has_long_span,
            "has_steel_span": has_steel_span,
        }
    }


def _cost_summary(recs, geometry):
    px_per_m = geometry["scale"]["px_per_m"]
    img_w = geometry["image_size"]["w"] / px_per_m
    img_h = geometry["image_size"]["h"] / px_per_m
    floor_area_sqm = img_w * img_h

    SQFT_PER_SQM = 10.764
    floor_sqft = floor_area_sqm * SQFT_PER_SQM

    items = []
    def _get_mat(mat_id):
        return next((m for m in MATERIAL_DB if m["id"] == mat_id), None)

    # Floor slab
    mat = _get_mat(recs["floor_slab"]["selected"])
    if mat:
        cost = mat.get("cost_inr_sqft", 420) * floor_sqft
        items.append({"item": "Floor Slab", "material": mat["name"],
                      "qty": f"{floor_sqft:.0f} sqft", "cost_inr": round(cost)})

    # Roof slab
    mat = _get_mat(recs["roof_slab"]["selected"])
    if mat:
        cost = mat.get("cost_inr_sqft", 390) * floor_sqft
        items.append({"item": "Roof Slab", "material": mat["name"],
                      "qty": f"{floor_sqft:.0f} sqft", "cost_inr": round(cost)})

    # LB walls - rough estimate: perimeter * 3m height / 9 sqft per unit
    lb_mat = _get_mat(recs["load_bearing_wall"]["selected"])
    if lb_mat:
        total_lb_px = sum(w["length_px"] for w in geometry.get("classified_walls", []) if w.get("load_bearing"))
        lb_m = total_lb_px / px_per_m
        lb_sqft = lb_m * 3 * SQFT_PER_SQM
        cost = lb_mat.get("cost_inr_sqft", 280) * lb_sqft
        items.append({"item": "Load-Bearing Walls", "material": lb_mat["name"],
                      "qty": f"{lb_sqft:.0f} sqft", "cost_inr": round(cost)})

    # Partition walls
    par_mat = _get_mat(recs["partition_wall"]["selected"])
    if par_mat:
        total_par_px = sum(w["length_px"] for w in geometry.get("classified_walls", []) if not w.get("load_bearing"))
        par_m = total_par_px / px_per_m
        par_sqft = par_m * 3 * SQFT_PER_SQM
        cost = par_mat.get("cost_inr_sqft", 210) * par_sqft
        items.append({"item": "Partition Walls", "material": par_mat["name"],
                      "qty": f"{par_sqft:.0f} sqft", "cost_inr": round(cost)})

    total = sum(i["cost_inr"] for i in items)
    items.append({"item": "TOTAL (Structure)", "material": "—",
                  "qty": "—", "cost_inr": round(total)})

    return {"line_items": items, "total_inr": round(total)}
