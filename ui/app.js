/* VehicleGPT Edge UI - vanilla JS, no external libraries, no network beyond localhost */
const $ = (s) => document.querySelector(s);
const EXAMPLES = [
  "Why has my driving range reduced over the last two weeks?",
  "When did fuel efficiency show the largest drop?",
  "Show all ADAS disengagement events from yesterday.",
  "What happened before the battery overheating warning?",
  "Compare energy consumption between city and highway driving.",
  "Show the evidence.",
  "Which trips contributed most to the difference?",
  "Were there any missing sensor readings?",
];

/* tabs */
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("#" + b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "diagnostics") loadDiagnostics();
  if (b.dataset.tab === "timeline") loadTimeline();
  if (b.dataset.tab === "simulator") loadGroundTruth();
}));

async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/* A. overview */
async function loadStatus() {
  try {
    const s = await j("/api/status");
    $("#badge-model").textContent = s.model.enabled ? "model: " + s.model.model_name
                                                    : "model: off (deterministic)";
    $("#badge-sim").style.display = s.simulated ? "" : "none";
    $("#status-cards").innerHTML = [
      ["application status", "running (local API)"],
      ["vehicle", s.vehicle],
      ["data source", s.data_maturity.join(", ") + " — synthetic"],
      ["latest data timestamp", s.latest_data_timestamp || "—"],
      ["history window", `${s.history_days} days · ${s.history_samples.toLocaleString()} samples`],
      ["retention setting", s.retention_days + " days"],
      ["database size", (s.database_bytes / 1e6).toFixed(1) + " MB"],
      ["model status", s.model.enabled ? s.model.model_name : "disabled — model-free mode"],
      ["offline", s.offline ? "yes — no cloud calls" : "no"],
      ["measured on", "this machine (dev PC) — not target hardware"],
    ].map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`)
     .join("");
  } catch (e) { $("#status-cards").textContent = "status error: " + e.message; }
}

/* B. ask */
$("#examples").innerHTML = EXAMPLES.map(e => `<button data-q="${e.replace(/"/g, """)}">${e}</button>`).join("");
document.querySelectorAll("#examples button").forEach(b =>
  b.addEventListener("click", () => { $("#question").value = b.dataset.q; ask(); }));

async function ask() {
  const q = $("#question").value.trim();
  if (!q) return;
  $("#ask-btn").disabled = true;
  try {
    const a = await j("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ question: q }) });
    $("#answer-box").classList.remove("hidden");
    $("#a-category").textContent = a.category;
    $("#a-status").textContent = a.retrieval_status;
    $("#a-status").className = "pill " + (a.retrieval_status === "ok" ? "good" : "warn");
    $("#a-model").textContent = "model: " + (a.model_used || "none");
    $("#a-time").textContent = `${a.time_range.start || "?"} → ${a.time_range.end || "?"}`;
    $("#a-text").textContent = a.direct_answer || "(no answer produced)";
    $("#a-limits").innerHTML = a.limitations.length
      ? "<ul>" + a.limitations.map(l => `<li>${l}</li>`).join("") + "</ul>" : "";
    $("#a-evcount").textContent = a.evidence.length;
    $("#a-evidence tbody").innerHTML = a.evidence.map(e => `<tr>
      <td>${e.evidence_id}</td><td>${e.kind}</td><td>${e.reference}</td>
      <td>${e.value ?? ""}</td><td>${e.unit ?? ""}</td>
      <td>${e.timestamp || ((e.time_start || "") + " → " + (e.time_end || ""))}</td>
      <td>${e.data_maturity}</td><td>${e.produced_by}</td></tr>`).join("");
    $("#a-validation").textContent =
      `status: ${a.validation.status}\nchecks: ${a.validation.checks_run.join(", ")}`
      + (a.validation.issues.length ? "\nissues:\n- " + a.validation.issues.join("\n- ") : "\nno issues");
    if (a.chart && a.chart.points && a.chart.points.length) drawChart(a.chart, "#chart-svg", "#chart");
  } catch (e) { alert("ask failed: " + e.message); }
  finally { $("#ask-btn").disabled = false; }
}
$("#ask-btn").addEventListener("click", ask);
$("#question").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });

function drawChart(chart, svgSel, wrapSel) {
  const svg = $(svgSel), W = 640, H = 220, pad = 30;
  const pts = chart.points, vals = pts.map(p => p.v);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const xy = pts.map((p, i) => [
    pad + i * (W - 2 * pad) / Math.max(1, pts.length - 1),
    H - pad - ((p.v - min) / span) * (H - 2 * pad)]);
  svg.innerHTML =
    `<rect x="0" y="0" width="${W}" height="${H}" fill="#fbfdff"/>` +
    `<text x="${pad}" y="18" font-size="11" fill="#5a6b7b">${chart.signal} (${chart.unit}) — ` +
    `${chart.samples} synthetic samples, bucketed to ${pts.length} points</text>` +
    `<polyline fill="none" stroke="#00a6e0" stroke-width="2" points="${xy.map(p => p.join(",")).join(" ")}"/>` +
    `<text x="${pad}" y="${H - 8}" font-size="10" fill="#5a6b7b">${pts[0].t}</text>` +
    `<text x="${W - pad - 60}" y="${H - 8}" font-size="10" fill="#5a6b7b">${pts[pts.length - 1].t}</text>` +
    `<text x="4" y="${pad + 4}" font-size="10" fill="#5a6b7b">${max.toFixed(1)}</text>` +
    `<text x="4" y="${H - pad}" font-size="10" fill="#5a6b7b">${min.toFixed(1)}</text>`;
  $(wrapSel).classList.remove("hidden");
}

/* C. timeline */
async function loadTimeline() {
  const params = new URLSearchParams();
  if ($("#tl-type").value) params.set("event_type", $("#tl-type").value);
  if ($("#tl-sev").value) params.set("severity", $("#tl-sev").value);
  if ($("#tl-start").value) params.set("start", $("#tl-start").value);
  if ($("#tl-end").value) params.set("end", $("#tl-end").value + " 23:59:59");
  params.set("limit", "300");
  try {
    const d = await j("/api/timeline?" + params);
    $("#tl-type").innerHTML = '<option value="">all event types</option>' +
      d.event_types.map(t => `<option ${t === $("#tl-type").value ? "selected" : ""}>${t}</option>`).join("");
    $("#tl-table tbody").innerHTML = d.events.map(e => `<tr>
      <td>${e.timestamp}</td><td>${e.event_type}</td><td>${e.severity}</td>
      <td>${e.description || ""}</td><td>${e.data_maturity}</td></tr>`).join("");
  } catch (e) { alert("timeline error: " + e.message); }
}
$("#tl-btn").addEventListener("click", loadTimeline);

/* D. analytics */
async function loadSignals() {
  try {
    const d = await j("/api/signals");
    $("#an-signal").innerHTML = d.signals.map(s =>
      `<option value="${s.signal_name}">${s.signal_name} [${s.unit}]</option>`).join("");
    $("#an-signal").value = "range_estimate";
  } catch (e) { /* ignore */ }
}
async function plot() {
  const sig = $("#an-signal").value;
  const end = $("#an-end").value || "2026-10-25";
  const start = $("#an-start").value || "2026-10-11";
  try {
    const d = await j(`/api/series?signal=${sig}&start=${start} 00:00:00&end=${end} 23:59:59`);
    if (!d.points.length) { $("#an-caption").textContent = "no samples in range"; return; }
    drawChart(d, "#an-svg", "#an-chart");
    $("#an-caption").textContent =
      `${d.samples} synthetic samples in range (chart is bucketed, not decimated data)`;
  } catch (e) { alert("series error: " + e.message); }
}
$("#an-btn").addEventListener("click", plot);

/* E. simulator */
async function regen() {
  $("#sim-btn").disabled = true;
  try {
    const d = await j("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: parseInt($("#sim-days").value || "60", 10), reset: true }) });
    $("#sim-out").textContent = "generated " + JSON.stringify(d.generated);
    loadStatus();
  } catch (e) { $("#sim-out").textContent = "error: " + e.message; }
  finally { $("#sim-btn").disabled = false; }
}
$("#sim-btn").addEventListener("click", regen);
async function loadGroundTruth() {
  try {
    const d = await j("/api/timeline?limit=1");
    $("#gt-pre").textContent = "ground truth rows are stored in scenario_ground_truth and read by the test suite.";
    const r = await fetch("/api/diagnostics"); // diagnostics already proves the system state
    void r; void d;
  } catch (e) { $("#gt-pre").textContent = "error: " + e.message; }
}

/* F. diagnostics */
async function loadDiagnostics() {
  try {
    const d = await j("/api/diagnostics");
    $("#diag-cards").innerHTML = [
      ["api", d.api], ["database", d.database], ["model", d.model],
      ["validation failures", d.recent_validation_failures.length],
      ["ingestion errors", d.ingestion_errors],
      ["signal quality", Object.entries(d.signal_quality_counts).map(([k, v]) => `${k}:${v}`).join(" · ")],
    ].map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
    $("#diag-table tbody").innerHTML = d.recent_queries.map(q => `<tr>
      <td>${q.timestamp}</td><td>${q.query_category}</td><td>${q.retrieval_status}</td>
      <td>${q.duration_ms}</td><td>${q.evidence_count}</td><td>${q.model_used}</td>
      <td>${q.validation_status}</td></tr>`).join("");
  } catch (e) { $("#diag-cards").textContent = "error: " + e.message; }
}

loadStatus(); loadSignals();
