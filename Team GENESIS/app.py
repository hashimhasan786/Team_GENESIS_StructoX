"""
StructoX — Autonomous Structural Intelligence System
Flask backend wiring all 5 pipeline stages + AI chatbot.
"""

import os
import uuid
import base64
import json
import cv2
import requests

from flask import Flask, request, jsonify, render_template, send_from_directory

from pipeline.stage1_parser   import parse_floor_plan
from pipeline.stage2_geometry import reconstruct_geometry
from pipeline.stage3_model3d  import generate_3d_model
from pipeline.stage4_materials import analyse_materials
from pipeline.stage5_explain  import generate_explanation

app = Flask(__name__)

# ── Anthropic API Key ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = "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"
os.environ.setdefault("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)

# ── Chatbot system prompt ──────────────────────────────────────────────────
CHAT_SYSTEM = """You are the StructoX Assistant — an expert structural engineering AI embedded in the StructoX web application.

StructoX analyses architectural floor plan images through 5 automated pipeline stages:
1. Stage 1 · Parse — Detects walls (horizontal/vertical/diagonal), rooms, openings (doors/windows), and junctions from the uploaded floor plan image using computer vision.
2. Stage 2 · Geometry — Reconstructs the wall graph, classifies walls as load-bearing (LB) or partition, analyses room spans, and identifies structural concerns.
3. Stage 3 · 3D Model — Generates an interactive Three.js 3D model with extruded walls, floor/roof slabs, and columns at load-bearing junctions.
4. Stage 4 · Materials — Recommends ranked building materials for each structural element using a cost-strength tradeoff score (weighted: strength, durability, cost). Provides full cost breakdown in Indian Rupees (INR).
5. Stage 5 · Explain — Generates plain-language AI explanations of the structural analysis, material justifications, and engineering recommendations.

Key concepts:
- Load-bearing walls (LB): structural walls that carry vertical loads — need stronger/costlier materials
- Partition walls (PAR): non-structural dividers — lighter materials acceptable
- Tradeoff score: composite score = (strength x wS) + (durability x wD) - (cost x wC), higher = better
- Structural concerns: issues like long unsupported spans, missing columns, weak junctions
- Common Indian materials: Red Brick, AAC Blocks, RCC, Fly Ash Brick, Hollow Concrete Block
- Cost units: INR/sq.ft for walls/slabs, INR/rmt for beams/columns

You help users understand their floor plan analysis results, explain structural engineering concepts, guide them through the StructoX workflow, and answer questions about materials, costs, and building practices — especially in the Indian construction context.

Be concise, clear, and helpful. Use bullet points for lists. Bold key terms with **asterisks**. Keep responses under 200 words unless a detailed explanation is truly needed. Never make up specific numbers from an analysis you haven't seen."""

UPLOAD_DIR    = os.path.join("static", "uploads")
PROCESSED_DIR = os.path.join("static", "processed")
os.makedirs(UPLOAD_DIR,    exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

ALLOWED = {"png", "jpg", "jpeg", "bmp", "tiff", "webp"}


def _allowed(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    uid  = uuid.uuid4().hex[:10]
    ext  = file.filename.rsplit(".", 1)[1].lower()
    path = os.path.join(UPLOAD_DIR, f"{uid}.{ext}")
    file.save(path)

    results = {}
    stage   = "init"

    try:
        # ── Stage 1: Parse ────────────────────────────────────────────────
        stage = "parsing"
        parsed, annotated_img = parse_floor_plan(path)
        results["stage1"] = parsed

        # Save annotated image
        proc_name = f"{uid}_s1.png"
        proc_path = os.path.join(PROCESSED_DIR, proc_name)
        cv2.imwrite(proc_path, annotated_img)
        _, buf = cv2.imencode(".png", annotated_img)
        b64 = base64.b64encode(buf).decode("utf-8")
        results["annotated_image_b64"] = f"data:image/png;base64,{b64}"
        results["annotated_image_url"] = f"/static/processed/{proc_name}"

        # ── Stage 2: Geometry ─────────────────────────────────────────────
        stage = "geometry"
        geometry = reconstruct_geometry(parsed)
        results["stage2"] = geometry

        # ── Stage 3: 3D Model ─────────────────────────────────────────────
        stage = "3d_model"
        model3d = generate_3d_model(geometry, parsed)
        results["stage3"] = model3d

        # ── Stage 4: Materials ────────────────────────────────────────────
        stage = "materials"
        # Pass classified_walls to geometry for material stage
        geometry["classified_walls"] = geometry.get("classified_walls", [])
        material_analysis = analyse_materials(geometry)
        results["stage4"] = material_analysis

        # ── Stage 5: Explainability ───────────────────────────────────────
        stage = "explainability"
        explanation = generate_explanation(parsed, geometry, material_analysis)
        results["stage5"] = explanation

        results["success"] = True
        results["uid"] = uid

        return jsonify(results)

    except Exception as e:
        return jsonify({
            "error": str(e),
            "stage": stage,
            "success": False,
        }), 500



@app.route("/chat", methods=["POST"])
def chat():
    """
    Proxy endpoint for the StructoX chatbot.
    Expects JSON: { "messages": [...], "api_key": "sk-ant-..." }
    Forwards to Anthropic API server-side, keeping the API key off the browser.
    """
    data = request.get_json(silent=True) or {}

    messages = data.get("messages")
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "messages array is required"}), 400

    # API key: prefer request body, then env var
    api_key = data.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({
            "error": "No API key provided. Set ANTHROPIC_API_KEY env var or pass api_key in request."
        }), 401

    # Validate message format
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") not in ("user", "assistant"):
            return jsonify({"error": "Each message must have role: user|assistant and content string"}), 400

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system":     CHAT_SYSTEM,
                "messages":   messages,
            },
            timeout=30,
        )

        if not resp.ok:
            try:
                err = resp.json()
            except Exception:
                err = {"error": {"message": resp.text}}
            return jsonify({
                "error": err.get("error", {}).get("message", f"Anthropic API error {resp.status_code}")
            }), resp.status_code

        result  = resp.json()
        reply   = "".join(b.get("text", "") for b in result.get("content", []))
        return jsonify({"reply": reply.strip()})

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request to Anthropic API timed out. Please try again."}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Anthropic API. Check your network."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/static/<path:fn>")
def static_files(fn):
    return send_from_directory("static", fn)


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
