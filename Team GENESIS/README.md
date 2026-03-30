# StructoX — Autonomous Structural Intelligence System
### PS 2 · AI/ML Track · Hackathon Submission

> "Build an AI system that reads a floor plan, builds it in 3D, and tells you exactly what to construct it with — and why."

---

## Project Structure

```
structox/
├── app.py                         ← Flask server (routes all 5 stages)
├── requirements.txt
├── pipeline/
│   ├── __init__.py
│   ├── stage1_parser.py           ← Stage 1: Floor Plan Parsing (OpenCV)
│   ├── stage2_geometry.py         ← Stage 2: Geometry Reconstruction (wall graph)
│   ├── stage3_model3d.py          ← Stage 3: 2D→3D extrusion (Three.js JSON)
│   ├── stage4_materials.py        ← Stage 4: Material Analysis & Tradeoff
│   └── stage5_explain.py          ← Stage 5: LLM Explainability (Anthropic API)
├── templates/
│   └── index.html                 ← Single-page app (all 5 stage panels)
└── static/
    ├── css/style.css
    ├── js/main.js                 ← Three.js renderer + stage renderers
    ├── uploads/                   ← Original images (auto-created)
    └── processed/                 ← Annotated images (auto-created)
```

---

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python app.py

# 3. Open browser
http://127.0.0.1:5000
```

---

## Mandatory Pipeline — All 5 Stages Implemented

### Stage 1 — Floor Plan Parsing (`stage1_parser.py`)
- **Wall detection**: Canny edges → Probabilistic Hough Transform, snapped to grid
- **Room detection**: Wall dilation → contour extraction → area/aspect classification
- **Opening detection**: Short line segment gaps → door/window candidates
- **Junction classification**: Harris Corner → L / T / X node types
- **Output**: Annotated image (colour-coded) + full JSON geometry

### Stage 2 — Geometry Reconstruction (`stage2_geometry.py`)
- **Wall graph**: Nodes (corners/junctions) + edges (wall segments)
- **Load-bearing classification**:
  - Outer boundary walls → LB
  - Structural spines (≥35% plan span) → LB
  - Walls >40% width/height → LB
  - All others → Partition
- **Span analysis**: Per-room clear span in metres, beam/steel need flags
- **Structural concerns**: Flagged with severity (HIGH/MEDIUM)

### Stage 3 — 3D Model Generation (`stage3_model3d.py`)
- Extrudes walls to 3m floor height
- LB walls: 230mm thick · Partition: 100mm thick
- Floor slab: 125mm · Roof slab: 150mm (transparent)
- Columns: 300×300mm at all LB junction nodes
- Output: Three.js JSON scene → interactive browser renderer (orbit, zoom, pan)

### Stage 4 — Material Analysis (`stage4_materials.py`)
- **Starter DB**: All 7 PS-specified materials + RCC M30
- **Tradeoff formula**:
  ```
  score = w_strength × S_norm + w_durability × D_norm − w_cost × C_norm
  ```
- **Weight profiles differ by element role** (engineering justification in rationale field):
  - Load-bearing: S=0.45, D=0.35, C=0.20
  - Partition:    S=0.20, D=0.30, C=0.50
  - Slab/Roof:    S=0.40–0.50, D=0.35–0.45, C=0.15
  - Column:       S=0.55, D=0.35, C=0.10
- **2–3 ranked options per element** with score bars
- **Full cost breakdown** table (INR)

### Stage 5 — Explainability (`stage5_explain.py`)
- Calls **Anthropic Claude API** (`claude-sonnet-4-20250514`) with structured prompt
- Prompt cites: span measurements, MPa values, cost levels, weight formula
- Returns 4 sections: Summary · Material Justifications · Structural Concerns · Tradeoff Logic
- **Falls back** to rule-based text generation if API unavailable (no crash)

---

## Hidden Trap Mitigations

| Trap | Mitigation |
|---|---|
| Non-90° layouts | Grid snapping with configurable tolerance; diagonal walls preserved |
| T/L junction confusion | Harris Corner + node degree analysis (deg=2→L, 3→T, 4→X) |
| 3D coordinate gaps | Endpoint clustering within `tol` px before Three.js export |
| Load-bearing classification | Multi-rule: outer + spine + span ratio heuristics |
| Naive cost formula | Weights are per-element-role and justified in rationale field |
| Shallow explainability | LLM prompt explicitly cites MPa, span metres, formula weights |

---

## Scoring Targets

| Criterion | Addressed by |
|---|---|
| Floor Plan Parsing (20) | Stage 1: walls, rooms, openings, junctions |
| 2D → 3D Model (25) | Stage 3: Three.js scene, all rooms, correct extrusion |
| Material Analysis (25) | Stage 4: weighted formula, 3 options per element, rationale |
| Explainability (20) | Stage 5: LLM summaries with cited evidence |
| System Integration (10) | End-to-end Flask pipeline, progress UI, error handling |

---

## Architecture Diagram

```
┌──────────────┐     POST /process      ┌──────────────────────────────────────────┐
│  Browser UI  │ ─────────────────────► │              Flask app.py                │
│  (Three.js)  │ ◄───────────────────── │                                          │
└──────────────┘     JSON response      │  ┌──────────┐  ┌──────────┐             │
                                        │  │ Stage 1  │─►│ Stage 2  │             │
                                        │  │  Parser  │  │ Geometry │             │
                                        │  └──────────┘  └────┬─────┘             │
                                        │                      ▼                   │
                                        │               ┌──────────┐               │
                                        │               │ Stage 3  │               │
                                        │               │  3D JSON │               │
                                        │               └────┬─────┘               │
                                        │                    ▼                     │
                                        │  ┌──────────┐  ┌──────────┐             │
                                        │  │ Stage 5  │◄─│ Stage 4  │             │
                                        │  │   LLM    │  │Materials │             │
                                        │  └──────────┘  └──────────┘             │
                                        └──────────────────────────────────────────┘
```
