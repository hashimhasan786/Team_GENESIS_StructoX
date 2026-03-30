"""
Stage 5 — Explainability Engine
=================================
Generates plain-language explanations using the Anthropic Claude API.
Falls back to rule-based text generation if the API call fails.

Explanations cite:
  • Specific element properties (span, load type)
  • Material properties (compressive MPa, cost level)
  • Structural concerns from geometry analysis
  • Cost–strength tradeoff logic
"""

import json
import urllib.request
import urllib.error


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_API_KEY = "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"


def _call_claude(prompt: str, system: str = None) -> str:
    """Call Anthropic API via stdlib urllib (no external deps)."""
    payload = {
        "model": MODEL,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": ANTHROPIC_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            for block in body.get("content", []):
                if block.get("type") == "text":
                    return block["text"].strip()
    except Exception:
        pass
    return None


def _fallback_explanation(parsed, geometry, materials) -> dict:
    """Rule-based explanation when API is unavailable."""
    walls = parsed.get("wall_summary", {})
    rooms = parsed.get("rooms", [])
    concerns = geometry.get("structural_concerns", [])
    recs = materials.get("recommendations", {})

    room_labels = ", ".join(r["label"] for r in rooms[:5]) + ("..." if len(rooms) > 5 else "")

    # Material summaries
    mat_lines = []
    for key, rec in recs.items():
        top = rec["ranked_options"][0] if rec["ranked_options"] else None
        if top:
            profile = rec["weight_profile"]
            mat_lines.append(
                f"**{rec['element']}** → {top['name']} (score: {top['tradeoff_score']:.2f}). "
                f"Chosen because: strength weight={profile['strength']}, "
                f"durability weight={profile['durability']}, cost weight={profile['cost']}. "
                f"{profile['rationale']}"
            )

    concern_lines = [
        f"⚠ Room {c['label']}: {c['message']} [{c['severity']}]"
        for c in concerns
    ] or ["No critical structural concerns detected."]

    return {
        "summary": (
            f"The floor plan contains {walls.get('total', 0)} wall segments "
            f"({walls.get('horizontal', 0)} horizontal, {walls.get('vertical', 0)} vertical, "
            f"{walls.get('diagonal', 0)} diagonal), totalling approximately "
            f"{walls.get('total_length_m', 0)} metres. "
            f"{parsed.get('room_count', 0)} enclosed rooms were identified: {room_labels}."
        ),
        "material_explanations": mat_lines,
        "structural_concerns": concern_lines,
        "tradeoff_logic": (
            "Material selection uses a weighted formula: "
            "score = w_strength×S + w_durability×D − w_cost×C, "
            "where weights are tuned per element role. "
            "Load-bearing elements prioritise strength (0.45) and durability (0.35); "
            "partition walls prioritise cost savings (0.50) since they carry no structural load."
        ),
        "source": "rule-based fallback"
    }


def generate_explanation(parsed_data: dict, geometry: dict, materials: dict) -> dict:
    """Generate structured plain-language explanations (LLM or fallback)."""

    # Build a concise summary for the LLM
    walls  = parsed_data.get("wall_summary", {})
    rooms  = parsed_data.get("rooms", [])
    conc   = geometry.get("structural_concerns", [])
    recs   = materials.get("recommendations", {})
    flags  = materials.get("structural_flags", {})
    cost   = materials.get("cost_summary", {})

    room_summary = "; ".join(
        f"R{r['id']}={r['label']} (span {geometry['room_spans'][i]['max_span_m']}m)"
        for i, r in enumerate(rooms[:8])
        if i < len(geometry.get("room_spans", []))
    )

    mat_summary = "\n".join(
        f"- {rec['element']}: Top choice = {rec['ranked_options'][0]['name'] if rec['ranked_options'] else 'N/A'} "
        f"(tradeoff score {rec['ranked_options'][0]['tradeoff_score']:.3f} if rec['ranked_options'] else '')"
        for rec in recs.values()
    ) if recs else "No recommendations generated."

    concern_text = "\n".join(
        f"- {c['label']}: {c['message']} ({c['severity']})"
        for c in conc
    ) or "None."

    prompt = f"""You are a structural engineering AI analyst. Based on the floor plan analysis below, write clear, specific, evidence-backed explanations for a non-expert client.

FLOOR PLAN ANALYSIS:
- Walls: {walls.get('total')} total ({walls.get('horizontal')} horizontal, {walls.get('vertical')} vertical, {walls.get('diagonal')} diagonal), ~{walls.get('total_length_m')}m total
- Rooms detected: {parsed_data.get('room_count')} — {room_summary}
- Load-bearing walls: {geometry.get('lb_count')}, Partition walls: {geometry.get('partition_count')}
- Long spans present: {flags.get('has_long_span')}, Steel spans (>5m): {flags.get('has_steel_span')}
- Estimated total structure cost: ₹{cost.get('total_inr', 0):,}

MATERIAL RECOMMENDATIONS:
{mat_summary}

STRUCTURAL CONCERNS:
{concern_text}

WEIGHT FORMULA USED:
score = w_strength × S_norm + w_durability × D_norm − w_cost × C_norm
Load-bearing: w_s=0.45, w_d=0.35, w_c=0.20
Partition: w_s=0.20, w_d=0.30, w_c=0.50

Write 4 sections as JSON with these exact keys:
1. "summary": 3-4 sentence overview of what was found in the plan
2. "material_explanations": list of strings, one per material category, citing MPa/cost data and WHY the formula ranks it first
3. "structural_concerns": list of strings describing any span or load-path issues with specific measurements
4. "tradeoff_logic": 2-3 sentences explaining why the weight ratios differ between structural and non-structural elements

Return ONLY valid JSON, no markdown fences."""

    system = "You are a structural engineering AI. Return only valid JSON. Never use markdown code fences."

    raw = _call_claude(prompt, system)

    if raw:
        # Strip markdown if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            result = json.loads(raw.strip())
            result["source"] = "claude-api"
            return result
        except json.JSONDecodeError:
            pass

    return _fallback_explanation(parsed_data, geometry, materials)
