/* ══════════════════════════════════════════════════════════
   StructoX — main.js
   Handles: navigation, upload, pipeline progress,
   Stage 1–5 rendering, Three.js 3D viewer, voice input
   ══════════════════════════════════════════════════════════ */

"use strict";

// ── Navigation ─────────────────────────────────────────────────────────────
const tabTitles = {
  upload:   "Floor Plan Analyzer",
  parse:    "Stage 1 · Floor Plan Parser",
  geometry: "Stage 2 · Geometry Reconstruction",
  model3d:  "Stage 3 · 3D Structural Model",
  materials:"Stage 4 · Material Analysis",
  explain:  "Stage 5 · AI Explanation",
};

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${tab}`).classList.add("active");
    document.getElementById("topbar-title").textContent = tabTitles[tab] || "StructoX";
    if (tab === "model3d" && window._pendingModel) {
      build3DScene(window._pendingModel);
      window._pendingModel = null;
    }
  });
});

// ── Upload & Pipeline ───────────────────────────────────────────────────────
const fileInput  = document.getElementById("file-input");
const dropZone   = document.getElementById("drop-zone");
const uzInner    = document.getElementById("uz-inner");
const uzPreview  = document.getElementById("uz-preview");
const imgOrig    = document.getElementById("img-orig");
const btnRun     = document.getElementById("btn-run");
const progCard   = document.getElementById("progress-card");
const errBar     = document.getElementById("error-bar");
const errText    = document.getElementById("error-text");

let selectedFile = null;

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) showPreview(fileInput.files[0]);
});

dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", e => {
  e.preventDefault(); dropZone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) showPreview(e.dataTransfer.files[0]);
});

function showPreview(file) {
  selectedFile = file;
  imgOrig.src = URL.createObjectURL(file);
  uzInner.style.display  = "none";
  uzPreview.style.display = "flex";
}

btnRun.addEventListener("click", () => {
  if (selectedFile) runPipeline(selectedFile);
});

// ── Stage progress UI ───────────────────────────────────────────────────────
const STAGES = ["1","2","3","4","5"];

function setStage(n, state) { // state: 'spin' | 'done' | 'error'
  const dot = document.getElementById(`pgd-${n}`);
  const lbl = document.getElementById(`pg-s${n}`);
  const sdot = document.getElementById(`dot-${n}`);
  if (dot) { dot.className = "prog-dot " + state; }
  if (lbl) { lbl.className = "prog-stage " + (state === "done" ? "done" : state === "spin" ? "active" : ""); }
  if (sdot) { sdot.className = "ps-dot " + (state === "done" ? "done" : state === "spin" ? "active" : state === "error" ? "error" : ""); }
}

function resetProgress() {
  STAGES.forEach(n => setStage(n, ""));
  progCard.style.display = "flex";
  errBar.style.display   = "none";
}

async function runPipeline(file) {
  resetProgress();
  // Animate stages
  setStage("1","spin");

  const fd = new FormData();
  fd.append("file", file);

  try {
    const resp = await fetch("/process", { method: "POST", body: fd });
    const data = await resp.json();

    if (!data.success) {
      const s = data.stage || "?";
      const stageNum = {parsing:"1",geometry:"2","3d_model":"3",materials:"4",explainability:"5"}[s] || "1";
      setStage(stageNum, "error");
      errText.textContent = `Stage ${s}: ${data.error}`;
      errBar.style.display = "flex";
      return;
    }

    // Mark all done sequentially for visual effect
    for (let i = 1; i <= 5; i++) {
      setStage(String(i), "done");
      await sleep(120);
    }

    // Hide default materials card after successful pipeline
    const defaultMat = document.getElementById("default-materials-card");
    if (defaultMat) defaultMat.style.display = "none";

    // Render all stages
    renderStage1(data);
    renderStage2(data);
    renderStage3(data);
    renderStage4(data);
    renderStage5(data);

    // Auto-navigate to stage 1
    setTimeout(() => document.querySelector('[data-tab="parse"]').click(), 300);

  } catch(e) {
    setStage("1","error");
    errText.textContent = "Network error: " + e.message;
    errBar.style.display = "flex";
  }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ══ Stage 1 Renderer ═════════════════════════════════════════════════════════
function renderStage1(data) {
  const s1 = data.stage1;
  const el = document.getElementById("parse-content");

  const ws = s1.wall_summary;
  const rooms = s1.rooms || [];
  const openings = s1.openings || [];

  const roomRows = rooms.slice(0,12).map(r => `
    <tr>
      <td style="font-family:var(--mono);color:var(--accent)">R${r.id}</td>
      <td>${r.label}</td>
      <td style="font-family:var(--mono)">${r.bbox.w}×${r.bbox.h}px</td>
      <td style="font-family:var(--mono)">${r.area_px.toLocaleString()}</td>
      <td style="font-family:var(--mono)">${r.aspect_ratio}</td>
    </tr>`).join("");

  el.innerHTML = `
    <div class="parse-grid">
      <div class="card">
        <div class="card-title"><i class="fa-solid fa-image"></i> Annotated Plan</div>
        <div class="parse-image-wrap">
          <img src="${data.annotated_image_b64 || data.annotated_image_url}" alt="Annotated"/>
          <div style="font-size:11px;color:var(--text3);margin-top:6px;font-style:italic">
            Yellow=Horizontal · Orange=Vertical · Green=Diagonal · Blue=Room contours · Cyan=Openings
          </div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="card">
          <div class="card-title"><i class="fa-solid fa-chart-bar"></i> Detection Summary</div>
          <div class="kpi-grid">
            ${kpi(ws.total, "Total Walls", ws.horizontal+"H / "+ws.vertical+"V / "+ws.diagonal+"D", "var(--accent)")}
            ${kpi(s1.room_count, "Rooms", "enclosed regions", "var(--blue)")}
            ${kpi(s1.opening_count, "Openings", "doors & windows", "var(--green)")}
            ${kpi(s1.junction_count, "Junctions", "corners detected", "var(--yellow)")}
          </div>
          <div style="margin-top:8px;padding-top:12px;border-top:1px solid var(--border)">
            <div class="wall-bar"><span class="wb-label">Total wall length</span><span class="wb-val">${ws.total_length_m} m</span></div>
            <div class="wall-bar"><span class="wb-label">Image resolution</span><span class="wb-val">${s1.image_size.w}×${s1.image_size.h}px</span></div>
            <div class="wall-bar"><span class="wb-label">Scale estimate</span><span class="wb-val">${s1.scale.px_per_m} px/m</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title"><i class="fa-solid fa-border-all"></i> Wall Breakdown</div>
          <div class="wall-bar"><span class="wb-label">Horizontal</span><span class="wb-val">${ws.horizontal}</span><span class="wb-type wb-lb" style="background:rgba(0,200,255,.12);color:#0cc">H</span></div>
          <div class="wall-bar"><span class="wb-label">Vertical</span><span class="wb-val">${ws.vertical}</span><span class="wb-type wb-par" style="background:rgba(255,140,50,.12);color:var(--accent2)">V</span></div>
          <div class="wall-bar"><span class="wb-label">Diagonal</span><span class="wb-val">${ws.diagonal}</span><span class="wb-type" style="background:rgba(100,255,150,.1);color:var(--green)">D</span></div>
        </div>
      </div>
    </div>
    ${rooms.length ? `
    <div class="card">
      <div class="card-title"><i class="fa-solid fa-table"></i> Detected Rooms (${rooms.length})</div>
      <div style="overflow-x:auto">
        <table class="cost-table">
          <thead><tr><th>#</th><th>Label</th><th>Dimensions</th><th>Area (px²)</th><th>Aspect</th></tr></thead>
          <tbody>${roomRows}</tbody>
        </table>
      </div>
    </div>` : ""}
  `;
}

// ══ Stage 2 Renderer ═════════════════════════════════════════════════════════
function renderStage2(data) {
  const g = data.stage2;
  const el = document.getElementById("geometry-content");
  const concerns = g.structural_concerns || [];
  const spans = g.room_spans || [];

  const spanRows = spans.map(s => `
    <tr>
      <td style="font-family:var(--mono);color:var(--accent)">R${s.room_id}</td>
      <td>${s.room_label}</td>
      <td style="font-family:var(--mono)">${s.span_x_m}m × ${s.span_y_m}m</td>
      <td style="font-family:var(--mono);font-weight:600">${s.max_span_m}m</td>
      <td>${s.needs_steel ? '<span class="tag tag-red">Steel Required</span>' : s.needs_beam ? '<span class="tag tag-yellow">Beam Needed</span>' : '<span class="tag tag-green">OK</span>'}</td>
    </tr>`).join("");

  el.innerHTML = `
    <div class="geo-grid">
      ${kpiCard("Load-Bearing Walls", g.lb_count, "structural walls", "var(--accent)")}
      ${kpiCard("Partition Walls", g.partition_count, "non-structural", "var(--blue)")}
      ${kpiCard("Graph Nodes", g.node_count, "corners / junctions", "var(--green)")}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="card-title"><i class="fa-solid fa-diagram-project"></i> Wall Classification</div>
        ${(g.classified_walls||[]).slice(0,15).map(w => `
          <div class="wall-bar">
            <span class="wb-label" style="font-family:var(--mono);font-size:11.5px">W${w.id} · ${w.orientation} · ${w.length_m||0}m</span>
            <span class="wb-type ${w.load_bearing ? 'wb-lb' : 'wb-par'}">${w.wall_type === 'load_bearing' ? 'LB' : 'PAR'}</span>
          </div>`).join("")}
        ${(g.classified_walls||[]).length > 15 ? `<div style="font-size:11px;color:var(--text3);margin-top:8px">…and ${g.classified_walls.length - 15} more walls</div>` : ""}
      </div>
      <div class="card">
        <div class="card-title"><i class="fa-solid fa-triangle-exclamation"></i> Structural Concerns</div>
        ${concerns.length ? concerns.map(c => `
          <div class="concern-card">
            <i class="fa-solid fa-circle-exclamation"></i>
            <div>
              <div class="msg" style="font-weight:600;margin-bottom:3px">${c.label}</div>
              <div class="msg">${c.message}</div>
              <span class="concern-sev ${c.severity === 'HIGH' ? 'sev-high' : 'sev-medium'}" style="margin-top:6px;display:inline-block">${c.severity}</span>
            </div>
          </div>`).join("") : `<div style="color:var(--green);font-size:13px;padding:10px 0"><i class="fa-solid fa-circle-check"></i> No critical concerns detected.</div>`}
      </div>
    </div>
    ${spans.length ? `
    <div class="card">
      <div class="card-title"><i class="fa-solid fa-ruler-combined"></i> Room Span Analysis</div>
      <div style="overflow-x:auto">
        <table class="cost-table">
          <thead><tr><th>#</th><th>Room</th><th>Dimensions</th><th>Max Span</th><th>Status</th></tr></thead>
          <tbody>${spanRows}</tbody>
        </table>
      </div>
    </div>` : ""}
  `;
}

// ══ Stage 3 Renderer ═════════════════════════════════════════════════════════
function renderStage3(data) {
  const m = data.stage3;
  const el = document.getElementById("model3d-content");

  el.innerHTML = `
    <div class="card">
      <div class="card-title"><i class="fa-solid fa-cube"></i> Interactive 3D Model</div>
      <div id="three-canvas-wrap"></div>
      <div class="three-legend">
        <div class="tl-item"><div class="tl-swatch" style="background:#c0392b"></div>Load-bearing walls</div>
        <div class="tl-item"><div class="tl-swatch" style="background:#7f8c8d"></div>Partition walls</div>
        <div class="tl-item"><div class="tl-swatch" style="background:#2c3e50"></div>Columns</div>
        <div class="tl-item"><div class="tl-swatch" style="background:#bdc3c7;opacity:.6"></div>Floor slab</div>
        <div class="tl-item"><div class="tl-swatch" style="background:#95a5a6;opacity:.5"></div>Roof slab</div>
      </div>
      <div style="font-size:11.5px;color:var(--text3);margin-top:8px">
        <i class="fa-solid fa-mouse"></i> Left-drag to orbit · Scroll to zoom · Right-drag to pan
      </div>
    </div>
    <div class="model-stats">
      ${kpiCard("3D Objects", m.object_count, "total scene elements", "var(--accent)")}
      ${kpiCard("Wall Meshes", m.wall_count_3d, "LB + partition", "var(--blue)")}
      ${kpiCard("Columns", m.column_count, "at LB junctions", "var(--yellow)")}
      ${kpiCard("Floor Height", "3.0m", "standard extrusion", "var(--green)")}
    </div>
  `;

  // Build scene (may be deferred if tab inactive)
  if (document.getElementById("tab-model3d").classList.contains("active")) {
    build3DScene(m);
  } else {
    window._pendingModel = m;
  }
}

// ── Three.js scene ────────────────────────────────────────────────────────
function build3DScene(modelData) {
  const wrap = document.getElementById("three-canvas-wrap");
  if (!wrap) return;
  wrap.innerHTML = "";

  const W = wrap.clientWidth || 900;
  const H = wrap.clientHeight || 520;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setSize(W, H);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.setClearColor(0x0a0c10);
  wrap.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0a0c10, 40, 120);

  // Lights
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dir = new THREE.DirectionalLight(0xffffff, 0.9);
  dir.position.set(20, 30, 20);
  dir.castShadow = true;
  scene.add(dir);

  const cfg = modelData.scene_config;
  const cam = new THREE.PerspectiveCamera(cfg.camera.fov, W / H, 0.1, 500);
  cam.position.set(...cfg.camera.position);
  cam.lookAt(...cfg.camera.target);

  // Grid
  const grid = new THREE.GridHelper(Math.max(cfg.plan_w_m, cfg.plan_d_m) * 2, 20, 0x1a2030, 0x1a2030);
  scene.add(grid);

  // Build objects
  for (const obj of modelData.objects) {
    const [sx, sy, sz] = obj.size;
    let geo;
    if (obj.type === "column") {
      geo = new THREE.BoxGeometry(sx, sy, sz);
    } else {
      geo = new THREE.BoxGeometry(sx, sy, sz);
    }

    const mat = new THREE.MeshLambertMaterial({
      color: new THREE.Color(obj.color),
      transparent: obj.opacity < 1,
      opacity: obj.opacity,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    if (obj.rotation_y) mesh.rotation.y = obj.rotation_y;
    mesh.receiveShadow = true;
    mesh.castShadow = true;
    scene.add(mesh);
  }

  // Orbit controls (manual — no import needed)
  let isDragging = false, isRightDrag = false;
  let lastX = 0, lastY = 0;
  let theta = Math.PI / 4, phi = Math.PI / 3;
  let radius = Math.max(cfg.plan_w_m, cfg.plan_d_m) * 2;
  const target = new THREE.Vector3(...cfg.camera.target);

  function updateCamera() {
    cam.position.x = target.x + radius * Math.sin(phi) * Math.sin(theta);
    cam.position.y = target.y + radius * Math.cos(phi);
    cam.position.z = target.z + radius * Math.sin(phi) * Math.cos(theta);
    cam.lookAt(target);
  }
  updateCamera();

  renderer.domElement.addEventListener("mousedown", e => {
    isDragging = true;
    isRightDrag = e.button === 2;
    lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("mouseup", () => isDragging = false);
  window.addEventListener("mousemove", e => {
    if (!isDragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    if (isRightDrag) {
      target.x -= dx * 0.02; target.z -= dy * 0.02;
    } else {
      theta -= dx * 0.008;
      phi = Math.max(0.1, Math.min(Math.PI * 0.48, phi - dy * 0.006));
    }
    updateCamera();
  });
  renderer.domElement.addEventListener("wheel", e => {
    radius = Math.max(1, radius + e.deltaY * 0.04);
    updateCamera();
    e.preventDefault();
  }, { passive: false });
  renderer.domElement.addEventListener("contextmenu", e => e.preventDefault());

  // Render loop
  function animate() {
    if (!wrap.isConnected) return;
    requestAnimationFrame(animate);
    renderer.render(scene, cam);
  }
  animate();

  // Resize
  window.addEventListener("resize", () => {
    const nw = wrap.clientWidth, nh = wrap.clientHeight;
    renderer.setSize(nw, nh);
    cam.aspect = nw / nh;
    cam.updateProjectionMatrix();
  });
}

// ══ Stage 4 Renderer ═════════════════════════════════════════════════════════
function renderStage4(data) {
  const s4 = data.stage4;
  const el = document.getElementById("materials-content");
  const recs = s4.recommendations || {};
  const cost = s4.cost_summary || {};

  const icons = {
    load_bearing_wall: "fa-wall-brick",
    partition_wall:    "fa-border-all",
    floor_slab:        "fa-layer-group",
    column:            "fa-lines-leaning",
    roof_slab:         "fa-house-chimney",
    long_span_beam:    "fa-ruler-horizontal",
  };

  let html = "";

  for (const [key, rec] of Object.entries(recs)) {
    const opts = rec.ranked_options || [];
    const wp   = rec.weight_profile || {};
    const maxScore = Math.max(...opts.map(o => o.tradeoff_score), 0.01);

    const optHtml = opts.map((opt, idx) => {
      const pct = Math.max(5, Math.round((opt.tradeoff_score / maxScore) * 100));
      const fillClass = idx === 0 ? "" : (idx === 1 ? "rank2" : "rank3");
      return `
        <div class="mat-option">
          <div class="mat-rank">#${opt.rank} ${idx === 0 ? '— <span style="color:var(--accent)">Selected</span>' : ''}</div>
          <div class="mat-name">${opt.name}</div>
          <div class="mat-score-bar"><div class="mat-score-fill ${fillClass}" style="width:${pct}%"></div></div>
          <div class="mat-meta">
            Score: <span>${opt.tradeoff_score.toFixed(3)}</span><br/>
            Strength: <span>${opt.compressive_mpa} MPa</span><br/>
            Cost: <span>₹${opt.cost_inr_sqft || opt.cost_inr_rmt || "—"}/sqft</span><br/>
            Use: <span>${opt.best_use}</span>
          </div>
        </div>`;
    }).join("");

    html += `
      <div class="mat-element">
        <div class="mat-element-header">
          <div class="mat-el-name">
            <i class="fa-solid ${icons[key] || 'fa-cube'}" style="color:var(--accent)"></i>
            ${rec.element}
            ${rec.count > 0 ? `<span class="tag tag-blue" style="font-size:10px">${rec.count} detected</span>` : ""}
          </div>
          <div style="font-size:11.5px;color:var(--text2)">
            w<sub>S</sub>=${wp.strength} · w<sub>D</sub>=${wp.durability} · w<sub>C</sub>=${wp.cost}
          </div>
        </div>
        <div class="mat-options">${optHtml}</div>
        <div style="padding:12px 18px;font-size:12px;color:var(--text3);border-top:1px solid var(--border);font-style:italic">
          ${wp.rationale || ""}
        </div>
      </div>`;
  }

  // Cost breakdown
  const costRows = (cost.line_items || []).map(item => `
    <tr>
      <td>${item.item}</td>
      <td>${item.material}</td>
      <td style="font-family:var(--mono)">${item.qty}</td>
      <td style="font-family:var(--mono)">₹${item.cost_inr.toLocaleString("en-IN")}</td>
    </tr>`).join("");

  html += `
    <div class="card">
      <div class="card-title"><i class="fa-solid fa-indian-rupee-sign"></i> Estimated Cost Breakdown</div>
      <div style="overflow-x:auto">
        <table class="cost-table">
          <thead><tr><th>Item</th><th>Material</th><th>Quantity</th><th>Cost (₹)</th></tr></thead>
          <tbody>${costRows}</tbody>
        </table>
      </div>
    </div>`;

  el.innerHTML = html;
}

// ══ Stage 5 Renderer ═════════════════════════════════════════════════════════
function renderStage5(data) {
  const s5 = data.stage5;
  const el = document.getElementById("explain-content");
  if (!s5) { el.innerHTML = `<div class="empty-state"><p>Explanation not available</p></div>`; return; }

  const isLLM = s5.source === "claude-api";
  const matList = Array.isArray(s5.material_explanations)
    ? s5.material_explanations.map(m => `<li>${m}</li>`).join("")
    : `<li>${s5.material_explanations || "No data"}</li>`;

  const concList = Array.isArray(s5.structural_concerns)
    ? s5.structural_concerns.map(c => `<li>${c}</li>`).join("")
    : `<li>${s5.structural_concerns || "None"}</li>`;

  el.innerHTML = `
    <div class="card">
      <div class="${isLLM ? 'source-badge llm' : 'source-badge'}">
        <i class="fa-solid ${isLLM ? 'fa-brain' : 'fa-gear'}"></i>
        ${isLLM ? 'Generated by Claude AI (Anthropic)' : 'Rule-based generation'}
      </div>

      <div class="explain-section">
        <h3><i class="fa-solid fa-file-lines"></i> Executive Summary</h3>
        <p>${s5.summary || "—"}</p>
      </div>

      <div class="explain-section">
        <h3><i class="fa-solid fa-cubes"></i> Material Justifications</h3>
        <ul>${matList}</ul>
      </div>

      <div class="explain-section">
        <h3><i class="fa-solid fa-triangle-exclamation"></i> Structural Concerns</h3>
        <ul>${concList}</ul>
      </div>

      <div class="explain-section">
        <h3><i class="fa-solid fa-balance-scale"></i> Cost–Strength Tradeoff Logic</h3>
        <p>${s5.tradeoff_logic || "—"}</p>
      </div>
    </div>
  `;
}

// ── UI helpers ──────────────────────────────────────────────────────────────
function kpi(val, label, sub, color) {
  return `
    <div class="kpi">
      <div class="kpi-label">${label}</div>
      <div class="kpi-val" style="color:${color}">${val}</div>
      <div class="kpi-sub">${sub}</div>
    </div>`;
}

function kpiCard(label, val, sub, color) {
  return `
    <div class="card" style="text-align:center;padding:16px">
      <div class="kpi-label">${label}</div>
      <div class="kpi-val" style="color:${color};font-size:28px">${val}</div>
      <div class="kpi-sub">${sub}</div>
    </div>`;
}

// ══════════════════════════════════════════════════════════════════════════════
//  In-Site Search — Command palette + content search
// ══════════════════════════════════════════════════════════════════════════════
(function () {
  "use strict";

  const searchInput = document.getElementById("search-input");
  const micBtn      = document.getElementById("mic-btn");
  const searchWrap  = searchInput.closest(".search-wrap");

  // ── Build dropdown container ────────────────────────────────────────────
  const dropdown = document.createElement("div");
  dropdown.className = "sx-search-dropdown";
  dropdown.id = "sx-search-dropdown";
  searchWrap.appendChild(dropdown);

  let activeIdx = -1;
  let currentResults = [];

  // ── Static commands (always available) ──────────────────────────────────
  function getStaticCommands() {
    return [
      { cat: "Navigation", icon: "fa-upload",          label: "Go to Upload",              action: () => navTo("upload") },
      { cat: "Navigation", icon: "fa-vector-square",   label: "Go to Stage 1 · Parse",     action: () => navTo("parse") },
      { cat: "Navigation", icon: "fa-diagram-project", label: "Go to Stage 2 · Geometry",  action: () => navTo("geometry") },
      { cat: "Navigation", icon: "fa-cube",            label: "Go to Stage 3 · 3D Model",  action: () => navTo("model3d") },
      { cat: "Navigation", icon: "fa-flask",           label: "Go to Stage 4 · Materials", action: () => navTo("materials") },
      { cat: "Navigation", icon: "fa-brain",           label: "Go to Stage 5 · Explain",   action: () => navTo("explain") },
      { cat: "Action",     icon: "fa-bolt",            label: "Run Pipeline",               action: () => { navTo("upload"); setTimeout(() => { const b = document.getElementById("btn-run"); if (b) b.click(); }, 200); } },
      { cat: "Action",     icon: "fa-folder-open",     label: "Upload a floor plan",        action: () => { navTo("upload"); setTimeout(() => document.getElementById("file-input")?.click(), 200); } },
      { cat: "Action",     icon: "fa-globe",           label: "Translate interface",        action: () => document.getElementById("tr-globe-btn")?.click() },
      { cat: "Action",     icon: "fa-comments",        label: "Open AI Chatbot",            action: () => document.getElementById("chat-fab")?.click() },
      { cat: "Action",     icon: "fa-broom",           label: "Clear chat history",         action: () => document.getElementById("chat-clear-btn")?.click() },
    ];
  }

  // ── Dynamic content entries (from pipeline results) ─────────────────────
  function getDynamicEntries() {
    const entries = [];

    // Scrape Stage 1 — Parse content
    const parseEl = document.getElementById("parse-content");
    if (parseEl && !parseEl.querySelector(".empty-state")) {
      // Wall summary
      parseEl.querySelectorAll(".wall-bar").forEach(bar => {
        const label = bar.querySelector(".wb-label")?.textContent?.trim();
        const val   = bar.querySelector(".wb-val")?.textContent?.trim();
        if (label && val) {
          entries.push({ cat: "Stage 1 · Parse", icon: "fa-border-all", label: `${label}: ${val}`, action: () => navTo("parse") });
        }
      });
      // KPIs
      parseEl.querySelectorAll(".kpi").forEach(k => {
        const lbl = k.querySelector(".kpi-label")?.textContent?.trim();
        const val = k.querySelector(".kpi-val")?.textContent?.trim();
        if (lbl && val) {
          entries.push({ cat: "Stage 1 · Parse", icon: "fa-chart-bar", label: `${lbl}: ${val}`, action: () => navTo("parse") });
        }
      });
      // rooms from table
      parseEl.querySelectorAll(".cost-table tbody tr").forEach(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length >= 2) {
          entries.push({ cat: "Stage 1 · Rooms", icon: "fa-table", label: `Room ${cells[0].textContent.trim()} — ${cells[1].textContent.trim()} (${cells[2]?.textContent?.trim() || ""})`, action: () => navTo("parse") });
        }
      });
    }

    // Scrape Stage 2 — Geometry content
    const geoEl = document.getElementById("geometry-content");
    if (geoEl && !geoEl.querySelector(".empty-state")) {
      geoEl.querySelectorAll(".wall-bar").forEach(bar => {
        const label = bar.querySelector(".wb-label")?.textContent?.trim();
        const type  = bar.querySelector(".wb-type")?.textContent?.trim();
        if (label) {
          entries.push({ cat: "Stage 2 · Geometry", icon: "fa-diagram-project", label: `${label} [${type || ""}]`, action: () => navTo("geometry") });
        }
      });
      // Concerns
      geoEl.querySelectorAll(".concern-card").forEach(card => {
        const msgs = card.querySelectorAll(".msg");
        const title = msgs[0]?.textContent?.trim() || "";
        const desc  = msgs[1]?.textContent?.trim() || "";
        if (title) {
          entries.push({ cat: "Stage 2 · Concerns", icon: "fa-triangle-exclamation", label: `${title} — ${desc}`.substring(0, 100), action: () => navTo("geometry") });
        }
      });
      // Room spans
      geoEl.querySelectorAll(".cost-table tbody tr").forEach(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length >= 3) {
          entries.push({ cat: "Stage 2 · Spans", icon: "fa-ruler-combined", label: `Room ${cells[0].textContent.trim()} — ${cells[1].textContent.trim()} · ${cells[2].textContent.trim()}`, action: () => navTo("geometry") });
        }
      });
      // KPIs
      geoEl.querySelectorAll(".card[style*='text-align:center'] .kpi-val, .card[style*='text-align'] .kpi-val").forEach(v => {
        const card = v.closest(".card");
        const lbl = card?.querySelector(".kpi-label")?.textContent?.trim();
        if (lbl) {
          entries.push({ cat: "Stage 2 · Geometry", icon: "fa-chart-bar", label: `${lbl}: ${v.textContent.trim()}`, action: () => navTo("geometry") });
        }
      });
    }

    // Scrape Stage 4 — Materials content
    const matEl = document.getElementById("materials-content");
    if (matEl && !matEl.querySelector(".empty-state")) {
      matEl.querySelectorAll(".mat-element").forEach(el => {
        const name = el.querySelector(".mat-el-name")?.textContent?.trim();
        if (name) {
          entries.push({ cat: "Stage 4 · Materials", icon: "fa-flask", label: name, action: () => navTo("materials") });
        }
        el.querySelectorAll(".mat-option").forEach(opt => {
          const rank = opt.querySelector(".mat-rank")?.textContent?.trim();
          const mname = opt.querySelector(".mat-name")?.textContent?.trim();
          const meta  = opt.querySelector(".mat-meta")?.textContent?.trim()?.substring(0, 80);
          if (mname) {
            entries.push({ cat: "Stage 4 · Materials", icon: "fa-cubes", label: `${mname} (${rank || ""}) — ${meta || ""}`, action: () => navTo("materials") });
          }
        });
      });
      // cost table
      matEl.querySelectorAll(".cost-table tbody tr").forEach(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length >= 3) {
          entries.push({ cat: "Stage 4 · Cost", icon: "fa-indian-rupee-sign", label: `${cells[0].textContent.trim()} · ${cells[1].textContent.trim()} · ${cells[3]?.textContent?.trim() || ""}`, action: () => navTo("materials") });
        }
      });
    }

    // Scrape Stage 5 — Explain
    const expEl = document.getElementById("explain-content");
    if (expEl && !expEl.querySelector(".empty-state")) {
      expEl.querySelectorAll(".explain-section").forEach(sec => {
        const h3 = sec.querySelector("h3")?.textContent?.trim();
        const body = sec.querySelector("p")?.textContent?.trim() || "";
        const lis  = Array.from(sec.querySelectorAll("li")).map(l => l.textContent.trim()).join("; ");
        const content = (body || lis).substring(0, 120);
        if (h3) {
          entries.push({ cat: "Stage 5 · Explain", icon: "fa-brain", label: `${h3}: ${content}`, action: () => navTo("explain") });
        }
      });
    }

    // Default material recommendations (on upload page)
    const defMat = document.getElementById("default-materials-card");
    if (defMat && defMat.style.display !== "none") {
      defMat.querySelectorAll("tbody tr").forEach(row => {
        const cells = row.querySelectorAll("td");
        if (cells.length >= 3) {
          entries.push({ cat: "Sample Materials", icon: "fa-flask", label: `${cells[0].textContent.trim()} — ${cells[1].textContent.trim()} · ${cells[2].textContent.trim()}`, action: () => navTo("upload") });
        }
      });
    }

    return entries;
  }

  // ── Navigate to a tab ───────────────────────────────────────────────────
  function navTo(tab) {
    const btn = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (btn) btn.click();
  }

  // ── Fuzzy match ─────────────────────────────────────────────────────────
  function fuzzyMatch(query, text) {
    const q = query.toLowerCase();
    const t = text.toLowerCase();
    if (t.includes(q)) return true;
    // word-start matching
    const words = q.split(/\s+/);
    return words.every(w => t.includes(w));
  }

  // ── Highlight matched text ──────────────────────────────────────────────
  function highlight(text, query) {
    if (!query) return escSearch(text);
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const words = escaped.split(/\s+/).filter(Boolean);
    const regex = new RegExp(`(${words.join("|")})`, "gi");
    return escSearch(text).replace(regex, '<mark class="sx-hl">$1</mark>');
  }

  function escSearch(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── Render dropdown ─────────────────────────────────────────────────────
  function renderDropdown(query) {
    const all = [...getStaticCommands(), ...getDynamicEntries()];
    const q = query.trim();

    if (!q) {
      dropdown.classList.remove("open");
      activeIdx = -1;
      currentResults = [];
      return;
    }

    const filtered = all.filter(item => fuzzyMatch(q, item.label) || fuzzyMatch(q, item.cat));
    currentResults = filtered;
    activeIdx = -1;

    if (filtered.length === 0) {
      dropdown.innerHTML = `<div class="sx-sr-empty"><i class="fa-solid fa-magnifying-glass"></i> No results for "${escSearch(q)}"</div>`;
      dropdown.classList.add("open");
      return;
    }

    // Group by category
    const groups = {};
    filtered.forEach(item => {
      if (!groups[item.cat]) groups[item.cat] = [];
      groups[item.cat].push(item);
    });

    let html = "";
    let globalIdx = 0;
    for (const [cat, items] of Object.entries(groups)) {
      html += `<div class="sx-sr-cat">${escSearch(cat)}</div>`;
      for (const item of items) {
        html += `<div class="sx-sr-item" data-idx="${globalIdx}">
          <i class="fa-solid ${item.icon}"></i>
          <span>${highlight(item.label, q)}</span>
        </div>`;
        globalIdx++;
      }
    }

    dropdown.innerHTML = html;
    dropdown.classList.add("open");

    // Click handlers
    dropdown.querySelectorAll(".sx-sr-item").forEach(el => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.dataset.idx);
        if (currentResults[idx]) {
          currentResults[idx].action();
          closeDropdown();
        }
      });
      el.addEventListener("mouseenter", () => {
        activeIdx = parseInt(el.dataset.idx);
        updateActive();
      });
    });
  }

  function updateActive() {
    dropdown.querySelectorAll(".sx-sr-item").forEach(el => {
      el.classList.toggle("active", parseInt(el.dataset.idx) === activeIdx);
    });
    // Scroll active into view
    const activeEl = dropdown.querySelector(".sx-sr-item.active");
    if (activeEl) activeEl.scrollIntoView({ block: "nearest" });
  }

  function closeDropdown() {
    dropdown.classList.remove("open");
    searchInput.value = "";
    searchInput.blur();
    activeIdx = -1;
    currentResults = [];
  }

  // ── Input events ────────────────────────────────────────────────────────
  searchInput.addEventListener("input", () => {
    renderDropdown(searchInput.value);
  });

  searchInput.addEventListener("keydown", (e) => {
    if (!dropdown.classList.contains("open") || currentResults.length === 0) {
      if (e.key === "Escape") { closeDropdown(); e.preventDefault(); }
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, currentResults.length - 1);
      updateActive();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      updateActive();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIdx >= 0 && currentResults[activeIdx]) {
        currentResults[activeIdx].action();
        closeDropdown();
      } else if (currentResults.length > 0) {
        currentResults[0].action();
        closeDropdown();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeDropdown();
    }
  });

  // Close dropdown on outside click
  document.addEventListener("click", (e) => {
    if (!searchWrap.contains(e.target)) closeDropdown();
  });

  // ── Keyboard shortcut: Ctrl+K or / to focus search ──────────────────────
  document.addEventListener("keydown", (e) => {
    // Don't trigger if typing in an input/textarea
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === "/" || (e.ctrlKey && e.key === "k")) {
      e.preventDefault();
      searchInput.focus();
    }
  });

  // ── Voice Input ─────────────────────────────────────────────────────────
  let recognition = null, listening = false;

  micBtn.addEventListener("click", () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert("Voice recognition not supported."); return; }
    if (!recognition) {
      recognition = new SR();
      recognition.lang = "en-IN";
      recognition.interimResults = false;
      recognition.onresult = e => {
        searchInput.value = e.results[0][0].transcript;
        renderDropdown(searchInput.value);
      };
      recognition.onend = () => { listening = false; micBtn.classList.remove("listening"); };
      recognition.onerror = () => { listening = false; micBtn.classList.remove("listening"); };
    }
    if (listening) { recognition.stop(); return; }
    recognition.start();
    listening = true;
    micBtn.classList.add("listening");
  });

})();

// ══ Topbar Language Translator ════════════════════════════════════════════
(function () {
  "use strict";

  const globeBtn   = document.getElementById("tr-globe-btn");
  const globeLabel = document.getElementById("tr-globe-label");
  const dropdown   = document.getElementById("tr-dropdown");
  const trSelect   = document.getElementById("tr-lang-select");
  const trBtn      = document.getElementById("tr-btn");
  const trResetBtn = document.getElementById("tr-reset-btn");
  const trStatus   = document.getElementById("tr-status");

  // ── Toggle dropdown ──────────────────────────────────────────────────
  globeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = dropdown.classList.toggle("open");
    globeBtn.classList.toggle("active", isOpen);
  });

  document.addEventListener("click", (e) => {
    if (!document.getElementById("topbar-translator").contains(e.target)) {
      dropdown.classList.remove("open");
      globeBtn.classList.remove("active");
    }
  });

  // ── Text node collection ─────────────────────────────────────────────
  let originalTexts = null;
  let currentLang   = null;
  let isTranslated  = false;

  function collectTextNodes() {
    const map = new Map();
    const walker = document.createTreeWalker(
      document.querySelector(".main-wrap"),
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const t = node.textContent.trim();
          if (!t || t.length < 2) return NodeFilter.FILTER_REJECT;
          const tag = node.parentElement && node.parentElement.tagName;
          if (["SCRIPT","STYLE","NOSCRIPT"].includes(tag)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );
    let node;
    while ((node = walker.nextNode())) map.set(node, node.textContent);
    return map;
  }

  // ── Google Translate (free endpoint) ────────────────────────────────
  async function googleTranslate(texts, targetLang) {
    const DELIM = " ||| ";
    const joined = texts.join(DELIM);
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=${encodeURIComponent(targetLang)}&dt=t&q=${encodeURIComponent(joined)}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("API error " + resp.status);
    const data = await resp.json();
    return data[0].map(i => i[0]).join("").split(DELIM);
  }

  async function translateNodes(nodes, lang) {
    const BATCH = 40;
    for (let i = 0; i < nodes.length; i += BATCH) {
      const batch  = nodes.slice(i, i + BATCH);
      const texts  = batch.map(n => n.textContent);
      try {
        const results = await googleTranslate(texts, lang);
        batch.forEach((node, idx) => {
          if (results[idx] !== undefined) {
            if (originalTexts && !originalTexts.has(node)) {
              originalTexts.set(node, node.textContent);
            }
            node.textContent = results[idx];
          }
        });
      } catch (e) { console.warn("Batch failed:", e); }
    }
  }

  // ── Translate action ─────────────────────────────────────────────────
  trBtn.addEventListener("click", async () => {
    const lang = trSelect.value;
    if (!lang) {
      trStatus.textContent = "Select a language first.";
      trStatus.className = "tr-status error";
      return;
    }

    originalTexts = collectTextNodes();
    const nodes   = Array.from(originalTexts.keys());

    trBtn.disabled = true;
    trBtn.classList.add("spinning");
    trStatus.className   = "tr-status";
    trStatus.textContent = "Translating…";

    try {
      currentLang  = lang;
      await translateNodes(nodes, lang);
      isTranslated = true;

      const label = trSelect.options[trSelect.selectedIndex].text
                      .replace(/^[^\s]+\s/, "").replace(/\s\(.*\)/, "").trim();
      globeLabel.textContent = lang.toUpperCase().slice(0, 2);
      globeBtn.classList.add("translated");
      globeBtn.classList.remove("active");
      dropdown.classList.remove("open");

      trStatus.textContent = "✓ " + label;
      trStatus.className   = "tr-status success";
      trResetBtn.style.display = "";
    } catch (e) {
      trStatus.textContent = "Error: " + e.message;
      trStatus.className   = "tr-status error";
    } finally {
      trBtn.disabled = false;
      trBtn.classList.remove("spinning");
    }
  });

  // ── Reset ────────────────────────────────────────────────────────────
  trResetBtn.addEventListener("click", () => {
    if (!originalTexts) return;
    originalTexts.forEach((orig, node) => { node.textContent = orig; });
    isTranslated   = false;
    currentLang    = null;
    originalTexts  = null;
    trSelect.value = "";
    globeLabel.textContent = "EN";
    globeBtn.classList.remove("translated");
    trResetBtn.style.display = "none";
    trStatus.textContent = "Reset to English.";
    trStatus.className   = "tr-status";
    setTimeout(() => { trStatus.textContent = ""; }, 1800);
  });

  // ── Re-translate dynamically rendered content ────────────────────────
  const observer = new MutationObserver(() => {
    if (!isTranslated || !currentLang) return;
    setTimeout(() => {
      const walker = document.createTreeWalker(
        document.querySelector(".content-area"),
        NodeFilter.SHOW_TEXT,
        {
          acceptNode(node) {
            const t = node.textContent.trim();
            if (!t || t.length < 2) return NodeFilter.FILTER_REJECT;
            const tag = node.parentElement && node.parentElement.tagName;
            if (["SCRIPT","STYLE","NOSCRIPT"].includes(tag)) return NodeFilter.FILTER_REJECT;
            if (originalTexts && originalTexts.has(node)) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
          }
        }
      );
      const newNodes = [];
      let n;
      while ((n = walker.nextNode())) newNodes.push(n);
      if (newNodes.length > 0) translateNodes(newNodes, currentLang);
    }, 400);
  });
  observer.observe(document.querySelector(".content-area"), {
    childList: true, subtree: true, characterData: false
  });
})();

// ══════════════════════════════════════════════════════════════════════════
//  StructoX Chatbot — Anthropic Claude powered
// ══════════════════════════════════════════════════════════════════════════
(function () {
  "use strict";

  /* ── DOM refs ─────────────────────────────────────────────────────── */
  const fab        = document.getElementById("chat-fab");
  const panel      = document.getElementById("chat-panel");
  const closeBtn   = document.getElementById("chat-close-btn");
  const clearBtn   = document.getElementById("chat-clear-btn");
  const input      = document.getElementById("chat-input");
  const sendBtn    = document.getElementById("chat-send-btn");
  const messages   = document.getElementById("chat-messages");
  const unreadBadge= document.getElementById("chat-unread");

  /* ── State ────────────────────────────────────────────────────────── */
  let isOpen       = false;
  let isWaiting    = false;
  let unreadCount  = 0;
  let history      = [];  // [{role, content}]

  /* ── Toggle panel ─────────────────────────────────────────────────── */
  function openPanel() {
    isOpen = true;
    panel.classList.add("open");
    fab.classList.add("open");
    unreadCount = 0;
    unreadBadge.style.display = "none";
    setTimeout(() => input.focus(), 250);
  }

  function closePanel() {
    isOpen = false;
    panel.classList.remove("open");
    fab.classList.remove("open");
  }

  fab.addEventListener("click", () => isOpen ? closePanel() : openPanel());
  closeBtn.addEventListener("click", closePanel);

  /* ── Clear chat ───────────────────────────────────────────────────── */
  clearBtn.addEventListener("click", () => {
    history = [];
    messages.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon"><i class="fa-solid fa-hard-hat"></i></div>
        <div class="chat-welcome-title">Chat cleared!</div>
        <div class="chat-welcome-sub">Ask me anything about StructoX or your floor plan analysis.</div>
        <div class="chat-chips">
          <button class="chat-chip" data-q="What does Stage 1 Parse do?">Stage 1 explained</button>
          <button class="chat-chip" data-q="What materials are best for load-bearing walls?">Best LB wall materials</button>
          <button class="chat-chip" data-q="How do I interpret structural concerns?">Structural concerns</button>
          <button class="chat-chip" data-q="What is a tradeoff score?">Tradeoff score</button>
        </div>
      </div>`;
    bindChips();
  });

  /* ── Render helpers ───────────────────────────────────────────────── */
  function timestamp() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function appendTimestamp() {
    const ts = document.createElement("div");
    ts.className = "chat-ts";
    ts.textContent = timestamp();
    messages.appendChild(ts);
  }

  function appendUserMsg(text) {
    const el = document.createElement("div");
    el.className = "chat-msg user";
    el.innerHTML = `
      <div class="chat-msg-avatar"><i class="fa-solid fa-user"></i></div>
      <div class="chat-bubble">${escHtml(text)}</div>`;
    messages.appendChild(el);
    scrollBottom();
  }

  function appendTyping() {
    const el = document.createElement("div");
    el.className = "chat-msg bot chat-typing";
    el.id = "chat-typing-indicator";
    el.innerHTML = `
      <div class="chat-msg-avatar"><i class="fa-solid fa-robot"></i></div>
      <div class="chat-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
    messages.appendChild(el);
    scrollBottom();
    return el;
  }

  function removeTyping() {
    const el = document.getElementById("chat-typing-indicator");
    if (el) el.remove();
  }

  function appendBotMsg(text) {
    removeTyping();
    const el = document.createElement("div");
    el.className = "chat-msg bot";
    el.innerHTML = `
      <div class="chat-msg-avatar"><i class="fa-solid fa-robot"></i></div>
      <div class="chat-bubble">${formatMarkdown(text)}</div>`;
    messages.appendChild(el);
    scrollBottom();

    if (!isOpen) {
      unreadCount++;
      unreadBadge.textContent = unreadCount;
      unreadBadge.style.display = "flex";
    }
  }

  function scrollBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function escHtml(s) {
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  /* Simple markdown → HTML: bold, code, line breaks */
  function formatMarkdown(text) {
    return escHtml(text)
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.*?)`/g, "<code>$1</code>")
      .replace(/\n\n/g, "</p><p>")
      .replace(/\n- /g, "</p><p>• ")
      .replace(/\n/g, "<br>");
  }

  /* ── Send message ─────────────────────────────────────────────────── */
  async function sendMessage(text) {
    text = text.trim();
    if (!text || isWaiting) return;

    // Handle /setkey command
    if (text.startsWith("/setkey ")) {
      const newKey = text.replace("/setkey ", "").trim();
      if (newKey) {
        localStorage.setItem("structox_api_key", newKey);
        window.STRUCTOX_API_KEY = newKey;
        input.value = "";
        const welcome = messages.querySelector(".chat-welcome");
        if (welcome) welcome.remove();
        appendBotMsg("✅ **API key saved!** You can now use the chatbot. Try asking me something about your floor plan.");
        appendTimestamp();
      }
      return;
    }

    // Hide welcome if present
    const welcome = messages.querySelector(".chat-welcome");
    if (welcome) welcome.remove();

    appendUserMsg(text);
    appendTimestamp();
    history.push({ role: "user", content: text });

    input.value = "";
    input.style.height = "auto";
    isWaiting = true;
    sendBtn.disabled = true;

    appendTyping();

    try {
      const CHAT_SYSTEM = `You are the StructoX Assistant — an expert structural engineering AI embedded in the StructoX web application.

StructoX analyses architectural floor plan images through 5 automated pipeline stages:
1. Stage 1 · Parse — Detects walls, rooms, openings (doors/windows), and junctions from floor plan images using computer vision.
2. Stage 2 · Geometry — Reconstructs the wall graph, classifies walls as load-bearing (LB) or partition, and identifies structural concerns.
3. Stage 3 · 3D Model — Generates an interactive Three.js 3D model with extruded walls, floor/roof slabs, and columns at load-bearing junctions.
4. Stage 4 · Materials — Recommends ranked building materials with cost breakdown in Indian Rupees (INR).
5. Stage 5 · Explain — Generates plain-language explanations of the structural analysis and engineering recommendations.

Key concepts: Load-bearing walls carry vertical loads (need stronger materials). Partition walls are non-structural. Tradeoff score = (strength × wS) + (durability × wD) - (cost × wC). Common Indian materials: Red Brick, AAC Blocks, RCC, Fly Ash Brick, Hollow Concrete Block. Cost units: INR/sq.ft for walls/slabs, INR/rmt for beams/columns.

Be concise, helpful, use bullet points, bold **key terms**. Keep responses under 200 words unless truly needed.`;

      // Use Anthropic API — requires key. Show friendly setup message if missing.
      const apiKey = (window.STRUCTOX_API_KEY || localStorage.getItem("structox_api_key") || "").trim();

      if (!apiKey) {
        removeTyping();
        appendBotMsg(`🔑 **API Key Required**\n\nThe StructoX chatbot needs an Anthropic API key to work.\n\n**Free option for students:**\n• Go to [console.anthropic.com](https://console.anthropic.com)\n• Sign up with your student email\n• New accounts get **$5 free credits** (enough for hundreds of chats!)\n• Copy your API key and paste it below\n\nTo set your key, type: \`/setkey sk-ant-...\``);
        appendTimestamp();
        isWaiting = false;
        sendBtn.disabled = false;
        input.focus();
        return;
      }

      const fullMessages = [
        { role: "user",      content: CHAT_SYSTEM + "\n\nConfirm you understand your role as StructoX Assistant." },
        { role: "assistant", content: "Understood! I am the StructoX Assistant. I help with structural engineering analysis, floor plan interpretation, and building material recommendations for the Indian construction context. How can I help?" },
        ...history
      ];

      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true"
        },
        body: JSON.stringify({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 600,
          messages: fullMessages
        })
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        if (response.status === 401) {
          localStorage.removeItem("structox_api_key");
          window.STRUCTOX_API_KEY = "";
          throw new Error("Invalid API key. Type `/setkey sk-ant-...` to set a new one.");
        }
        throw new Error((err.error && err.error.message) || `API error ${response.status}`);
      }

      const data  = await response.json();
      const reply = (data.content || []).map(b => b.text || "").join("").trim();

      history.push({ role: "assistant", content: reply });
      appendBotMsg(reply);
      appendTimestamp();

    } catch (err) {
      removeTyping();
      appendBotMsg(`⚠️ **Error:** ${err.message}\n\nIf your API key is wrong or missing, refresh the page and enter a valid Anthropic API key when prompted.`);
    } finally {
      isWaiting    = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  /* ── Input events ─────────────────────────────────────────────────── */
  sendBtn.addEventListener("click", () => sendMessage(input.value));

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input.value);
    }
  });

  // Auto-grow textarea
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 100) + "px";
  });

  /* ── Suggestion chips ─────────────────────────────────────────────── */
  function bindChips() {
    document.querySelectorAll(".chat-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        if (!isOpen) openPanel();
        sendMessage(chip.dataset.q);
      });
    });
  }
  bindChips();

  /* ── Show unread badge after 3s (initial greeting) ─────────────────── */
  setTimeout(() => {
    if (!isOpen) {
      unreadCount = 1;
      unreadBadge.textContent = "1";
      unreadBadge.style.display = "flex";
    }
  }, 3000);

})();
