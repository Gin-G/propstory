// PropStory front end.
//
// Fast path (default): fetch a precomputed, point-optimized cell JSON
//   (web/data/<lat>_<lon>.json, GDEX-sourced, built in CI) in ONE request and
//   render instantly.
// On-demand path: if no precompute exists for the cell, GDEX cannot be read
//   from the browser (it serves no CORS headers — a cross-origin fetch fails
//   with "Failed to fetch", confirmed via a CI browser probe). So instead we
//   open a pre-filled GitHub issue carrying the geocoded coordinates; an
//   `on: issues` workflow reads GDEX server-side, commits the cell JSON, and
//   Pages redeploys. The cell is then on the fast path (~2-3 min later).

const REPO = "Gin-G/propstory";   // where cell-request issues are filed

const $ = (id) => document.getElementById(id);
const logEl = $("log");
function log(msg) {
  const t = new Date().toISOString().substr(11, 8);
  if (logEl) { logEl.textContent += `[${t}] ${msg}\n`; logEl.scrollTop = logEl.scrollHeight; }
  console.log(msg);
}

let map, marker;
function initMap(lat = 40.06, lon = -106.39) {
  map = L.map("map").setView([lat, lon], 12);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri World Imagery", maxZoom: 19 }).addTo(map);
  marker = L.marker([lat, lon]).addTo(map);
}

async function geocode(addr) {
  // 1) Open-Meteo geocoding: CORS-friendly and reliable from browsers. It's
  //    city-level, which is plenty for the 0.25° ERA5 grid. Try the full string,
  //    then progressively simpler "town, region" / "town" forms.
  const parts = addr.split(",").map((s) => s.trim()).filter(Boolean);
  const tries = [addr];
  if (parts.length > 1) { tries.push(parts.slice(1).join(", ")); tries.push(parts[parts.length - 2] || parts[0]); }
  for (const q of tries) {
    try {
      const r = await fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name=" +
        encodeURIComponent(q));
      if (r.ok) {
        const j = await r.json();
        if (j.results && j.results.length) {
          const g = j.results[0];
          return { lat: g.latitude, lon: g.longitude,
                   name: [g.name, g.admin1, g.country_code].filter(Boolean).join(", ") };
        }
      }
    } catch (e) { /* try next form / provider */ }
  }
  // 2) Nominatim fallback (handles full street addresses)
  try {
    const r = await fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" +
      encodeURIComponent(addr), { headers: { Accept: "application/json" } });
    const j = await r.json();
    if (j.length) return { lat: +j[0].lat, lon: +j[0].lon, name: j[0].display_name };
  } catch (e) { /* fall through */ }
  throw new Error("could not geocode that address — try a town/city name");
}

function snapKey(lat, lon) {
  let la = Math.round(lat / 0.25) * 0.25;
  let lo = Math.round(lon / 0.25) * 0.25;
  if (lo > 180) lo -= 360;
  return `${la.toFixed(2)}_${lo.toFixed(2)}`;
}

function f1(x) { return (x === null || x === undefined || Number.isNaN(x)) ? "–" : (+x).toFixed(1); }

function renderSummary(d) {
  $("s_snow").innerHTML = `${f1(d.means.peak_swe_in)}<small> peak SWE (in)</small>`;
  $("s_ski").innerHTML = `${Math.round(d.means.skiable_days)}<small> skiable days/yr</small>`;
  $("s_wind").innerHTML = `${f1(d.means.mean_wind_mph)}<small> mean wind (mph)</small>`;
  $("s_cold").innerHTML = `${Math.round(d.records.coldest.value_f)}<small> coldest (°F)</small>`;
  const r = d.records;
  $("tbl").innerHTML = `<tbody>
    <tr><td>Deepest SWE</td><td class="n">${r.deepest_swe.value_in} in</td><td>${r.deepest_swe.when}</td></tr>
    <tr><td>Windiest day</td><td class="n">${r.windiest_day.value_mph} mph</td><td>${r.windiest_day.when}</td></tr>
    <tr><td>Coldest</td><td class="n">${r.coldest.value_f} °F</td><td>${d.records.coldest.when}</td></tr>
    <tr><td>Warmest</td><td class="n">${d.records.warmest.value_f} °F</td><td>${d.records.warmest.when}</td></tr>
    <tr><td class="muted">Source</td><td colspan="2" class="muted">${d.dataset} · cell ${d.grid_cell.lat},${d.grid_cell.lon}</td></tr>
    </tbody>`;
  const dates = d.daily.t.map((s) => new Date(s + "T00:00:00Z"));
  drawChart($("ch_snow"), dates, d.daily.swe_in);

  // monthly snow-depth climatology (water-year order Oct..Sep)
  const clim = d.monthly_climatology && d.monthly_climatology.depth_in;
  if (clim) {
    const order = [9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8]; // Oct..Sep (0-indexed months)
    const labels = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"];
    drawBars($("ch_month"), labels, order.map((m) => clim[m] ?? 0), 12);
  }
  // year-by-year table
  if (d.by_year && d.by_year.length) {
    const rows = d.by_year.map((y) =>
      `<tr><td>${y.wy}</td><td class="n">${y.peak_swe_in}</td><td class="n">${y.skiable_days}</td>` +
      `<td class="n">${y.snow_days}</td><td class="n">${y.coldest_f}</td></tr>`).join("");
    $("tbl_year").innerHTML =
      `<thead><tr><th>WY</th><th class="n">peak SWE</th><th class="n">ski days</th>` +
      `<th class="n">snow days</th><th class="n">coldest °F</th></tr></thead><tbody>${rows}</tbody>`;
  }
}

function drawBars(canvas, labels, vals, thresh) {
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d"); c.scale(dpr, dpr); c.clearRect(0, 0, w, h);
  const max = Math.max(0.1, thresh || 0, ...vals), pad = 24, n = vals.length;
  const bw = (w - pad) / n * 0.7;
  c.fillStyle = "#9fb0c0"; c.font = "10px system-ui";
  c.fillText(max.toFixed(0), 2, 12);
  for (let i = 0; i < n; i++) {
    const x = pad + (i + 0.15) * (w - pad) / n;
    const bh = (vals[i] / max) * (h - 2 * pad);
    c.fillStyle = "#5b9bd5"; c.fillRect(x, h - pad - bh, bw, bh);
    c.fillStyle = "#9fb0c0"; c.fillText(labels[i], x - 2, h - pad + 11);
  }
  if (thresh) {
    const y = h - pad - (thresh / max) * (h - 2 * pad);
    c.strokeStyle = "#c0392b"; c.setLineDash([4, 3]); c.beginPath();
    c.moveTo(pad, y); c.lineTo(w, y); c.stroke(); c.setLineDash([]);
  }
}

async function tryCache(key) {
  try {
    const r = await fetch(`./data/${key}.json`, { cache: "no-cache" });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// Build a pre-filled GitHub issue URL that the cell-request workflow consumes.
// The body carries machine-readable lat/lon lines the workflow parses.
function requestCellUrl(loc, key) {
  const title = `[cell-request] ${key}`;
  const body =
    "PropStory cell request (auto-generated — do not edit the lines below).\n\n" +
    `address: ${loc.name || "(from coordinates)"}\n` +
    `lat: ${loc.lat}\n` +
    `lon: ${loc.lon}\n` +
    `grid: ${key}\n\n` +
    "The PropStory bot will read GDEX, build this cell, and close this issue " +
    "when done (~2-3 min). Then reload PropStory and search this address again.";
  return `https://github.com/${REPO}/issues/new` +
    `?title=${encodeURIComponent(title)}` +
    `&body=${encodeURIComponent(body)}` +
    "&labels=cell-request";
}

let chipLoc = null;        // set when a precomputed-location chip is clicked
let pendingLive = null;    // {loc, years} awaiting explicit "Load live" click
let timerId = null;

function startTimer(label) {
  const t0 = performance.now();
  $("go").disabled = true; $("go_live").disabled = true;
  timerId = setInterval(() => {
    $("go").textContent = `${label} ${((performance.now() - t0) / 1000).toFixed(0)}s`;
  }, 250);
}
function stopTimer() {
  if (timerId) { clearInterval(timerId); timerId = null; }
  $("go").textContent = "Build propstory"; $("go").disabled = false; $("go_live").disabled = false;
}

function setMarker(loc) {
  $("loc").textContent = loc.name || "";
  map.setView([loc.lat, loc.lon], 13); marker.setLatLng([loc.lat, loc.lon]);
}

async function build() {
  logEl.textContent = "";
  $("go_live").style.display = "none"; pendingLive = null;
  startTimer("Building…");
  try {
    const years = Math.max(1, Math.min(85, +$("years").value || 5));
    let loc;
    const params = new URLSearchParams(location.search);
    if (chipLoc) { loc = chipLoc; chipLoc = null; log(`location: ${loc.name}`); }
    else if (params.has("lat") && params.has("lon")) {
      loc = { lat: +params.get("lat"), lon: +params.get("lon"), name: "(coords from URL)" };
      log(`coords from URL: ${loc.lat}, ${loc.lon}`);
    } else {
      log(`geocoding: ${$("addr").value.trim()}`); loc = await geocode($("addr").value.trim());
    }
    log(`→ ${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`);
    setMarker(loc);

    const key = snapKey(loc.lat, loc.lon);
    log(`grid cell ${key}; checking precomputed cache …`);
    const cached = await tryCache(key);
    if (cached) {
      log("loaded precomputed cell (fast path).");
      renderSummary(cached);
      log("DONE.");
    } else {
      log(`no precomputed cell for ${key} yet.`);
      pendingLive = { loc, key };
      $("go_live").style.display = "block";
      log("GDEX serves no browser CORS, so this cell is built server-side from GDEX.");
      log("click “Request this location” to open a GitHub issue that builds it");
      log("(~2-3 min), then reload PropStory and search again.");
    }
  } catch (e) {
    log("ERROR: " + (e && e.message ? e.message : e));
    console.error(e);
  } finally {
    stopTimer();
  }
}

function loadLive() {
  if (!pendingLive) return;
  const { loc, key } = pendingLive;
  const url = requestCellUrl(loc, key);
  window.open(url, "_blank", "noopener");
  log(`opened a GitHub issue to build cell ${key}.`);
  log("the bot reads GDEX, commits the cell, and Pages redeploys (~2-3 min).");
  log("reload this page and search again once the issue is closed.");
}

async function loadAvailable() {
  try {
    const r = await fetch("./data/index.json", { cache: "no-cache" });
    if (!r.ok) return;
    const idx = await r.json();
    const keys = Object.keys(idx);
    if (!keys.length) return;
    const el = $("avail");
    el.innerHTML = "<b>Instant (precomputed) cells:</b> ";
    for (const k of keys) {
      const c = idx[k];
      const b = document.createElement("button");
      b.textContent = `${c.grid_lat}, ${c.grid_lon}`;
      b.style.cssText = "margin:4px 4px 0 0;padding:4px 8px;font-size:12px;background:#24455f;color:#cfe3f5";
      b.onclick = () => { chipLoc = { lat: c.grid_lat, lon: c.grid_lon, name: `precomputed cell ${k}` }; build(); };
      el.appendChild(b);
    }
    // auto-load the first precomputed cell so data shows immediately (no click,
    // no geocoding). Skipped when coords are supplied via URL (e.g. smoke test).
    const params = new URLSearchParams(location.search);
    if (!params.has("lat") && !params.has("lon")) {
      const c = idx[keys[0]];
      chipLoc = { lat: c.grid_lat, lon: c.grid_lon, name: `precomputed cell ${keys[0]}` };
      build();
    }
  } catch { /* index optional */ }
}

function drawChart(canvas, times, vals) {
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d"); c.scale(dpr, dpr); c.clearRect(0, 0, w, h);
  const max = Math.max(0.1, ...vals), pad = 24;
  c.strokeStyle = "#34465a"; c.beginPath(); c.moveTo(pad, h - pad); c.lineTo(w, h - pad); c.stroke();
  c.fillStyle = "#9fb0c0"; c.font = "10px system-ui";
  c.fillText(max.toFixed(1) + " in", 2, 12); c.fillText("0", 2, h - pad);
  c.fillStyle = "rgba(79,157,222,.55)"; c.strokeStyle = "#4f9dde"; c.beginPath();
  for (let i = 0; i < vals.length; i++) {
    const x = pad + (i / (vals.length - 1)) * (w - pad);
    const y = h - pad - (vals[i] / max) * (h - 2 * pad);
    i ? c.lineTo(x, y) : c.moveTo(x, y);
  }
  c.lineTo(w, h - pad); c.lineTo(pad, h - pad); c.closePath(); c.fill();
}

initMap();
$("go").addEventListener("click", build);
$("go_live").addEventListener("click", loadLive);
loadAvailable();
window.__appReady = true;          // smoke test waits on this before clicking
log("ready. enter an address and click Build.");
