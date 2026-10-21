// Browser port of main.py (Tkinter + SQLite) for Battery Thermal Management.
// The four SQLite tables are kept in localStorage with the same column names.

const TEMP_WARNING = 45.0;
const TEMP_CRITICAL = 50.0;
const TARGET_DELTA_T = 5.0;
const STORE_KEY = "battery_thermal_db_v1";
const TABLES = ["sensor_readings", "cfd_results", "predictions", "maintenance_logs"];

const $ = (sel) => document.querySelector(sel);
const now = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
const rand = (lo, hi, dp) => +(lo + Math.random() * (hi - lo)).toFixed(dp);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- Domain (mirrors the Python classes) ----------

class SensorReading {
  constructor(battery_id, cell_id, temperature, voltage, current, coolant_temperature, flow_rate, timestamp = "") {
    Object.assign(this, { battery_id, cell_id, temperature, voltage, current, coolant_temperature, flow_rate });
    this.timestamp = timestamp || now();
    if (!String(battery_id).trim() || !String(cell_id).trim()) throw new Error("Battery ID and Cell ID are required.");
    for (const f of ["temperature", "voltage", "current", "coolant_temperature", "flow_rate"]) {
      if (!Number.isFinite(this[f])) throw new Error(`${titleCase(f)} must be a number.`);
      if (this[f] < 0) throw new Error(`${titleCase(f)} cannot be negative.`);
    }
  }
  summary() {
    return `${this.battery_id}/${this.cell_id} | ${this.temperature.toFixed(1)} °C | ${this.voltage.toFixed(2)} V | ` +
      `${this.current.toFixed(2)} A | Coolant ${this.coolant_temperature.toFixed(1)} °C | Flow ${this.flow_rate.toFixed(2)} L/min`;
  }
}
const titleCase = (f) => f.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

class CoolingFluid {
  constructor(name, concentration, reynolds, inlet_temp, pressure_drop, heat_transfer, max_temp) {
    Object.assign(this, { name, concentration, reynolds, inlet_temp, pressure_drop, heat_transfer, max_temp });
  }
}
class WaterCase extends CoolingFluid {
  performanceScore() { return this.heat_transfer - this.pressure_drop * 0.15 - this.max_temp * 0.2; }
}
class NanofluidCase extends CoolingFluid {
  performanceScore() { return this.heat_transfer - this.pressure_drop * 0.15 - this.max_temp * 0.2 - this.concentration * 0.1; }
}

const ThermalAnalysis = {
  temperatureDifference: (hot, cold) => Math.abs(hot - cold),
  rankCases: (cases) => [...cases].sort((a, b) => b.score - a.score),
};

function getStatus(t) {
  if (t >= TEMP_CRITICAL) return "CRITICAL";
  if (t > TEMP_WARNING) return "WARNING";
  return "NORMAL";
}

// ---------- Database (localStorage-backed, same schema as SQLite) ----------

class ThermalDatabase {
  constructor() {
    this.data = null;
    try { this.data = JSON.parse(localStorage.getItem(STORE_KEY)); } catch (_) { /* storage unavailable */ }
    if (!this.data || !this.data.tables) this.reset(false);
  }
  reset(save = true) {
    this.data = { seq: {}, tables: {} };
    for (const t of TABLES) { this.data.tables[t] = []; this.data.seq[t] = 0; }
    if (save) this.save();
  }
  save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(this.data)); } catch (_) { /* in-memory only */ } }
  insert(table, row) {
    const id = ++this.data.seq[table];
    this.data.tables[table].push({ id, ...row });
    this.save();
    return id;
  }
  saveReading(r, delta_t, status) {
    this.insert("sensor_readings", {
      battery_id: r.battery_id, cell_id: r.cell_id, timestamp: r.timestamp, temperature: r.temperature,
      voltage: r.voltage, current: r.current, coolant_temperature: r.coolant_temperature, flow_rate: r.flow_rate, delta_t, status,
    });
  }
  savePrediction(model, predicted, observed) {
    this.insert("predictions", {
      timestamp: now(), model_name: model, predicted_temperature: +predicted.toFixed(2),
      observed_temperature: +observed.toFixed(2), error: +Math.abs(predicted - observed).toFixed(2),
    });
  }
  saveCfd(c) {
    this.insert("cfd_results", {
      case_name: c.name, reynolds: c.reynolds ?? null, inlet_temperature: c.inlet, concentration: c.concentration ?? 0,
      pressure_drop: c.pressure, heat_transfer: c.htc, max_temperature: c.max_temp ?? c.outlet, score: +c.score.toFixed(2),
    });
  }
  saveAlert(alert_type, description) {
    this.insert("maintenance_logs", { timestamp: now(), alert_type, description, status: "Open" });
  }
  rows(table) {
    if (!TABLES.includes(table)) throw new Error("Unknown database table.");
    return [...this.data.tables[table]].sort((a, b) => b.id - a.id).slice(0, 300);
  }
  deleteReading(id) {
    const t = this.data.tables.sensor_readings;
    const i = t.findIndex((r) => r.id === id);
    if (i >= 0) { t.splice(i, 1); this.save(); }
  }
}

const db = new ThermalDatabase();

const latest = () => {
  const row = db.rows("sensor_readings")[0];
  return row ? new SensorReading(row.battery_id, row.cell_id, row.temperature, row.voltage, row.current, row.coolant_temperature, row.flow_rate, row.timestamp) : null;
};

function makeDemoReading(temperature = null, flow = null) {
  const n = db.data.seq.sensor_readings + 1;
  return new SensorReading(
    "BAT-01", `CELL-${String(n).padStart(2, "0")}`,
    temperature ?? rand(30, 48, 1), rand(3.55, 4.15, 2), rand(5, 25, 1), rand(21, 30, 1), flow ?? rand(1, 3.5, 2)
  );
}

function persistReading(r) {
  const delta = ThermalAnalysis.temperatureDifference(r.temperature, r.coolant_temperature);
  db.saveReading(r, +delta.toFixed(2), getStatus(r.temperature));
}

function loadSampleData() {
  if (!db.rows("sensor_readings").length) {
    [[34.2, 2.8], [39.6, 2.2], [46.4, 1.1]].forEach(([t, f]) => persistReading(makeDemoReading(t, f)));
  }
  refreshAll();
}

// ---------- Tabs ----------

const tabButtons = document.querySelectorAll(".tabs button");
function selectTab(name) {
  tabButtons.forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
    if (b.dataset.tab === name) b.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.dataset.panel !== name));
  try { localStorage.setItem("bt_tab", name); } catch (_) {}
  if (name === "monitor") drawTrend();
}
tabButtons.forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));

// ---------- Views ----------

function refreshDashboard() {
  const r = latest();
  if (!r) {
    $("#c-temp").textContent = "-- °C"; $("#c-volt").textContent = "-- V";
    $("#c-curr").textContent = "-- A"; $("#c-flow").textContent = "-- L/min";
    $("#status").dataset.level = "NONE"; $("#status").textContent = "Status: waiting for data";
    $("#latest").textContent = "No reading yet.";
    return;
  }
  const status = getStatus(r.temperature);
  $("#c-temp").textContent = `${r.temperature.toFixed(1)} °C`;
  $("#c-volt").textContent = `${r.voltage.toFixed(2)} V`;
  $("#c-curr").textContent = `${r.current.toFixed(1)} A`;
  $("#c-flow").textContent = `${r.flow_rate.toFixed(2)} L/min`;
  $("#status").dataset.level = status;
  $("#status").textContent = `Status: ${status}  |  ΔT ${Math.abs(r.temperature - r.coolant_temperature).toFixed(1)} °C`;
  $("#latest").textContent = `${r.summary()}\nTimestamp: ${r.timestamp}`;
}

function renderTable(table, columns, rows, cell = (c, r) => esc(r[c] ?? "")) {
  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="empty">No records yet</td></tr></tbody>`;
    return;
  }
  table.innerHTML =
    `<thead><tr>${columns.map((c) => `<th>${esc(c.label ?? c)}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((r) => `<tr data-id="${r.id}">${columns.map((c) => cell(c.key ?? c, r)).map((v, i) => `<td${columns[i].wrap ? ' class="wrap"' : ""}>${v}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

const badge = (s) => `<span class="badge badge-${esc(s)}">${esc(s)}</span>`;

function refreshReadingsTable() {
  const cols = [
    { key: "id", label: "ID" }, { key: "timestamp", label: "Time" }, { key: "bc", label: "Battery/Cell" },
    { key: "temperature", label: "Temp °C" }, { key: "voltage", label: "Voltage V" }, { key: "current", label: "Current A" },
    { key: "coolant_temperature", label: "Coolant °C" }, { key: "flow_rate", label: "Flow L/min" },
    { key: "delta_t", label: "ΔT °C" }, { key: "status", label: "Status" },
  ];
  const fmt = { temperature: 1, voltage: 2, current: 1, coolant_temperature: 1, flow_rate: 2, delta_t: 1 };
  renderTable($("#readings-table"), cols, db.rows("sensor_readings"), (k, r) => {
    if (k === "bc") return esc(`${r.battery_id}/${r.cell_id}`);
    if (k === "status") return badge(r.status);
    if (k in fmt) return Number(r[k]).toFixed(fmt[k]);
    return esc(r[k]);
  });
}

let selectedDbId = null;
function refreshDbTable() {
  const table = $("#db-table").value;
  const rows = db.rows(table);
  const cols = rows.length ? Object.keys(rows[0]).map((k) => ({ key: k, label: k, wrap: k === "description" })) : [];
  renderTable($("#db-grid"), cols, rows, (k, r) => (k === "status" && table === "sensor_readings" ? badge(r[k]) : esc(r[k] ?? "")));
  selectedDbId = null;
}

function refreshAlerts() {
  renderTable($("#alerts-table"),
    [{ key: "id", label: "ID" }, { key: "timestamp", label: "Time" }, { key: "alert_type", label: "Type" }, { key: "description", label: "Description", wrap: true }, { key: "status", label: "Status" }],
    db.rows("maintenance_logs"));
}

function refreshAll() {
  refreshDashboard();
  refreshReadingsTable();
  refreshDbTable();
  refreshAlerts();
  drawTrend();
}

// ---------- Monitoring chart (SVG) ----------

function drawTrend() {
  const svg = $("#trend");
  if (!svg || svg.closest(".panel").hidden) return;
  const W = svg.clientWidth || 800, H = svg.clientHeight || 320;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const L = 46, R = W - 18, T = 18, B = H - 34;
  const y = (v) => B - (Math.min(Math.max(v, 0), 60) / 60) * (B - T);
  const css = getComputedStyle(document.documentElement);
  const c = (n) => css.getPropertyValue(n).trim();

  const rows = db.rows("sensor_readings").reverse().slice(-20);
  let html = "";
  for (const v of [0, 15, 30, 45, 60]) {
    html += `<line x1="${L}" x2="${R}" y1="${y(v)}" y2="${y(v)}" stroke="${c("--border")}" stroke-dasharray="3 4"/>`;
    html += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  html += `<text x="8" y="${T - 4}">°C</text>`;
  html += `<line x1="${L}" x2="${R}" y1="${y(TEMP_WARNING)}" y2="${y(TEMP_WARNING)}" stroke="${c("--warn-fg")}" stroke-width="1.5"/>`;
  html += `<line x1="${L}" x2="${R}" y1="${y(TEMP_CRITICAL)}" y2="${y(TEMP_CRITICAL)}" stroke="${c("--crit-fg")}" stroke-width="1.5"/>`;

  if (!rows.length) {
    html += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">Save a reading to display the trend</text>`;
    svg.innerHTML = html;
    $("#monitor-summary").textContent = "No readings available";
    return;
  }

  const x = (i) => L + (rows.length === 1 ? (R - L) / 2 : (i / (rows.length - 1)) * (R - L));
  const pts = rows.map((r, i) => [x(i), y(r.temperature)]);
  if (pts.length > 1) {
    // Catmull-Rom → cubic Bézier for a smooth line (Tk's smooth=True equivalent).
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
    }
    html += `<path d="${d}" fill="none" stroke="${c("--accent")}" stroke-width="2.5" stroke-linecap="round"/>`;
  }
  const dot = { NORMAL: c("--accent"), WARNING: c("--warn-fg"), CRITICAL: c("--crit-fg") };
  rows.forEach((r, i) => {
    html += `<circle cx="${pts[i][0]}" cy="${pts[i][1]}" r="4.5" fill="${dot[r.status] || c("--accent")}" stroke="${c("--panel")}" stroke-width="2" data-i="${i}"/>`;
    html += `<rect x="${pts[i][0] - 12}" y="${T}" width="24" height="${B - T}" fill="transparent" data-i="${i}"/>`;
  });
  svg.innerHTML = html;

  const tip = $("#tip");
  svg.onmousemove = (e) => {
    const i = e.target.dataset?.i;
    if (i === undefined) { tip.hidden = true; return; }
    const r = rows[i], box = svg.getBoundingClientRect();
    tip.innerHTML = `#${r.id} · ${esc(r.cell_id)} · <b>${r.temperature.toFixed(1)} °C</b> · ${r.status}`;
    tip.style.left = `${(pts[i][0] / W) * box.width}px`;
    tip.style.top = `${(pts[i][1] / H) * box.height}px`;
    tip.hidden = false;
  };
  svg.onmouseleave = () => (tip.hidden = true);

  const temps = rows.map((r) => r.temperature);
  $("#monitor-summary").textContent =
    `Readings: ${rows.length}  |  Latest: ${temps.at(-1).toFixed(1)} °C  |  Minimum: ${Math.min(...temps).toFixed(1)} °C  |  Maximum: ${Math.max(...temps).toFixed(1)} °C`;
}
window.addEventListener("resize", () => drawTrend());

// ---------- Actions ----------

function flash(el, text, ok) {
  el.textContent = text;
  el.className = `msg ${ok ? "ok" : "err"}`;
}

$("#btn-sample").onclick = loadSampleData;
$("#btn-refresh").onclick = refreshDashboard;
$("#btn-summary").onclick = () => {
  const rows = db.rows("sensor_readings"), out = $("#summary");
  out.hidden = false;
  if (!rows.length) { out.textContent = "No readings saved."; return; }
  const t = rows.map((r) => r.temperature);
  out.textContent = `Records: ${rows.length}\nAverage: ${(t.reduce((a, b) => a + b, 0) / t.length).toFixed(2)} °C\nMaximum: ${Math.max(...t).toFixed(2)} °C\nMinimum: ${Math.min(...t).toFixed(2)} °C`;
};

$("#sensor-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target), n = (k) => (f.get(k) === "" ? NaN : Number(f.get(k)));
  try {
    const r = new SensorReading(String(f.get("battery_id")).trim(), String(f.get("cell_id")).trim(),
      n("temperature"), n("voltage"), n("current"), n("coolant_temperature"), n("flow_rate"));
    if (r.temperature > 150) throw new Error("Temperature exceeds the demo input limit.");
    if (r.voltage <= 0) throw new Error("Voltage must be greater than zero.");
    persistReading(r);
    refreshAll();
    flash($("#sensor-msg"), "Reading saved successfully.", true);
  } catch (err) {
    flash($("#sensor-msg"), `Invalid input: ${err.message}`, false);
  }
};

$("#btn-random").onclick = () => {
  persistReading(makeDemoReading());
  refreshAll();
  flash($("#sensor-msg"), "Test reading inserted.", true);
};

document.querySelectorAll("[data-test]").forEach((b) => (b.onclick = () => {
  const [t, f] = b.dataset.test.split(",").map(Number);
  persistReading(makeDemoReading(t, f));
  refreshAll();
}));

$("#btn-cooling").onclick = () => {
  const cases = [
    { name: "Configuration A", flow: 1.0, inlet: 25.0, outlet: 42.0, pressure: 18.0, htc: 420.0 },
    { name: "Configuration B", flow: 2.0, inlet: 25.0, outlet: 37.0, pressure: 24.0, htc: 510.0 },
    { name: "Configuration C", flow: 3.0, inlet: 24.0, outlet: 35.5, pressure: 37.0, htc: 560.0 },
  ];
  for (const c of cases) {
    c.delta_t = ThermalAnalysis.temperatureDifference(c.outlet, c.inlet);
    c.score = c.htc - c.pressure * 2 - c.delta_t * 3;
  }
  const ranked = ThermalAnalysis.rankCases(cases);
  ranked.forEach((c) => db.saveCfd(c));
  renderRanking($("#cooling-out"), "Synthetic example data — not CFD measurements", ranked, (c) => [
    ["Flow", `${c.flow} L/min`], ["Inlet → outlet", `${c.inlet} → ${c.outlet} °C`], ["Temperature difference", `${c.delta_t.toFixed(1)} °C`],
    ["Pressure drop", c.pressure], ["Heat-transfer coeff.", c.htc], ["Demonstration score", c.score.toFixed(2)],
  ]);
  refreshDbTable();
};

$("#btn-fluids").onclick = () => {
  const fluids = [
    new WaterCase("Water", 0, 1800, 25, 20, 430, 43),
    new NanofluidCase("Al2O3/Water 0.5%", 0.5, 2100, 25, 25, 520, 39),
    new NanofluidCase("Al2O3/Water 1.0%", 1.0, 2300, 25, 34, 560, 37),
  ];
  const cases = fluids.map((fl) => ({
    name: fl.name, concentration: fl.concentration, reynolds: fl.reynolds, inlet: fl.inlet_temp,
    pressure: fl.pressure_drop, htc: fl.heat_transfer, max_temp: fl.max_temp, score: fl.performanceScore(),
  }));
  const ranked = cases.filter((c) => c.pressure <= 35).sort((a, b) => b.score - a.score);
  ranked.forEach((c) => db.saveCfd(c));
  renderRanking($("#fluids-out"), "Synthetic example data — not experimental results", ranked, (c) => [
    ["Concentration", `${c.concentration}%`], ["Reynolds number", c.reynolds], ["Inlet temperature", `${c.inlet} °C`],
    ["Pressure drop", c.pressure], ["Heat-transfer coeff.", c.htc], ["Maximum temperature", `${c.max_temp} °C`],
    ["Performance score", c.score.toFixed(2)],
  ]);
  refreshDbTable();
};

function renderRanking(el, banner, ranked, fields) {
  const max = Math.max(...ranked.map((c) => c.score));
  el.innerHTML = `<div class="banner">${esc(banner)}</div>` + ranked.map((c, i) => `
    <div class="rank">
      <div class="rank-n">${i + 1}</div>
      <div>
        <h4>${esc(c.name)}</h4>
        <div class="kv">${fields(c).map(([k, v]) => `<div><span>${esc(k)}:</span> <b>${esc(v)}</b></div>`).join("")}</div>
        <div class="score-bar"><i style="width:${Math.max(4, (c.score / max) * 100)}%"></i></div>
      </div>
    </div>`).join("");
}

$("#pred-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target), v = {};
  const out = $("#pred-out");
  try {
    for (const k of ["temp", "current", "coolant", "flow"]) {
      v[k] = f.get(k) === "" ? NaN : Number(f.get(k));
      if (!Number.isFinite(v[k])) throw new Error("All inputs must be numbers.");
    }
    if (Object.values(v).some((x) => x < 0)) throw new Error("Inputs cannot be negative.");
    const predicted = v.temp + Math.max(0, v.current - 10) * 0.08 + Math.max(0, 2 - v.flow) * 1.4 + Math.max(0, v.coolant - 25) * 0.15;
    const risk = getStatus(predicted);
    out.innerHTML = `<strong>Model: rule-based demonstration</strong><br><br>Estimated temperature: <strong>${predicted.toFixed(2)} °C</strong><br>Risk category: ${badge(risk)}<br><br><span class="note">This is not a trained or validated AI model.</span>`;
    const l = latest();
    db.savePrediction("Rule-Based Demonstration", predicted, l ? l.temperature : predicted);
    refreshDbTable();
  } catch (err) {
    out.innerHTML = `<span class="msg err">Invalid input: ${esc(err.message)}</span>`;
  }
};

$("#twin-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target), out = $("#twin-out");
  const p = f.get("pred") === "" ? NaN : Number(f.get("pred"));
  const o = f.get("obs") === "" ? NaN : Number(f.get("obs"));
  if (!Number.isFinite(p) || !Number.isFinite(o)) { out.innerHTML = `<span class="msg err">Invalid input: temperatures must be numbers.</span>`; return; }
  if (p < 0 || o < 0) { out.innerHTML = `<span class="msg err">Invalid input: temperatures cannot be negative.</span>`; return; }
  db.savePrediction("Digital Twin Demonstration", p, o);
  out.innerHTML = `Predicted: <strong>${p.toFixed(2)} °C</strong><br>Observed: <strong>${o.toFixed(2)} °C</strong><br>Absolute error: <strong>${Math.abs(p - o).toFixed(2)} °C</strong>`;
  refreshDbTable();
};

$("#btn-recommend").onclick = () => {
  const r = latest(), out = $("#recommend-out");
  if (!r) { out.textContent = "No data: enter a sensor reading first."; return; }
  const status = getStatus(r.temperature);
  let kind, description;
  if (status === "CRITICAL") {
    kind = "High Temperature";
    description = "Critical demonstration threshold crossed. Inspect the cooling system and follow approved safety procedures.";
  } else if (status === "WARNING") {
    kind = "Temperature Warning";
    description = "Temperature exceeds the demonstration threshold. Review coolant flow and recent readings.";
  } else if (r.flow_rate < 1.5) {
    kind = "Low Coolant Flow";
    description = "Flow is below the demonstration threshold. Inspect the flow sensor and cooling path.";
  } else if (Math.abs(r.temperature - r.coolant_temperature) >= TARGET_DELTA_T) {
    kind = "Thermal Gradient";
    description = "Review the battery-to-coolant temperature difference and compare cell temperatures.";
  } else {
    kind = "Normal Monitoring";
    description = "No configured demonstration rule was triggered. Continue monitoring.";
  }
  db.saveAlert(kind, description);
  out.textContent = `Alert type: ${kind}\nStatus: ${status}\nRecommendation: ${description}\n\nEducational demonstration rules only.`;
  refreshAlerts();
  refreshDbTable();
};

$("#db-table").onchange = refreshDbTable;
$("#btn-load").onclick = refreshDbTable;
$("#db-grid").onclick = (e) => {
  const tr = e.target.closest("tbody tr[data-id]");
  if (!tr) return;
  document.querySelectorAll("#db-grid tr.sel").forEach((x) => x.classList.remove("sel"));
  tr.classList.add("sel");
  selectedDbId = Number(tr.dataset.id);
};
$("#btn-delete").onclick = () => {
  const msg = $("#db-msg");
  if ($("#db-table").value !== "sensor_readings") return flash(msg, "Select the sensor_readings table first.", false);
  if (!selectedDbId) return flash(msg, "Select a reading first.", false);
  if (!confirm(`Delete reading #${selectedDbId}?`)) return;
  db.deleteReading(selectedDbId);
  refreshAll();
  flash(msg, "Reading deleted.", true);
};
$("#btn-reset").onclick = () => {
  if (!confirm("Clear all four tables and reload the sample data?")) return;
  db.reset();
  loadSampleData();
  flash($("#db-msg"), "Database reset.", true);
};

$("#btn-csv").onclick = () => {
  const rows = db.rows("sensor_readings");
  if (!rows.length) return alert("No readings to export.");
  const cols = Object.keys(rows[0]);
  const q = (v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => q(r[c])).join(","))].join("\n");
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "sensor_readings.csv",
  });
  a.click();
  URL.revokeObjectURL(a.href);
};

// ---------- Boot ----------

loadSampleData();
let startTab = "overview";
try { startTab = localStorage.getItem("bt_tab") || "overview"; } catch (_) {}
selectTab(document.querySelector(`[data-panel="${startTab}"]`) ? startTab : "overview");
