// PropStory front end.
//
// Fast path (default): fetch a precomputed, point-optimized cell JSON
//   (web/data/<lat>_<lon>.json, GDEX-sourced, built in CI) in ONE request and
//   render instantly.
// Live fallback: if no precompute exists for the cell, read ERA5 straight from
//   GDEX in the browser with zarrita (slow — area-chunked stores). zarrita is
//   imported lazily so the page is responsive and the fast path never depends
//   on a CDN.

const GDEX = "https://osdf-data.gdex.ucar.edu/ncar/gdex/d633000/e5.oper.an.sfc.zarr";
const LIVE_VARS = { sd: "SD", "2t": "VAR_2T", "10u": "VAR_10U", "10v": "VAR_10V" };
const MM_PER_IN = 25.4, MS_TO_MPH = 2.23694, SKIABLE_IN = 12;

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
  const url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" +
    encodeURIComponent(addr);
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  const j = await r.json();
  if (!j.length) throw new Error("address not found");
  return { lat: +j[0].lat, lon: +j[0].lon, name: j[0].display_name };
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

async function liveFromGDEX(loc, years) {
  log("no precompute for this cell → live GDEX read (slow; area-chunked) …");
  const zarr = await import("https://esm.sh/zarrita@0.4.0?bundle");
  const lonE = ((loc.lon % 360) + 360) % 360;
  const open = async (code) =>
    zarr.withConsolidated(new zarr.FetchStore(`${GDEX}/e5.oper.an.sfc.${code}.zarr`));
  const t0 = performance.now();
  const sdStore = await open("sd");
  log(`opened sd metadata in ${((performance.now() - t0) / 1000).toFixed(1)}s`);
  const latArr = (await zarr.get(await zarr.open(sdStore.resolve("latitude"), { kind: "array" }))).data;
  const lonArr = (await zarr.get(await zarr.open(sdStore.resolve("longitude"), { kind: "array" }))).data;
  const ilat = nearest(latArr, loc.lat), ilon = nearest(lonArr, lonE);
  const timeA = await zarr.open(sdStore.resolve("time"), { kind: "array" });
  const tvals = (await zarr.get(timeA)).data;
  const times = decodeTime(tvals, timeA.attrs.units);
  const end = times.length;
  const cutoff = +times[end - 1] - years * 365.25 * 864e5;
  let start = end - 1; while (start > 0 && +times[start] > cutoff) start--;
  log(`reading last ${years}y (${end - start} steps) at cell ${(+latArr[ilat]).toFixed(2)},${(((+lonArr[ilon] + 180) % 360) - 180).toFixed(2)} …`);
  const read = async (st, name) => (await zarr.get(
    await zarr.open(st.resolve(name), { kind: "array" }), [zarr.slice(start, end), ilat, ilon])).data;
  const sd = await read(sdStore, LIVE_VARS.sd); log("  sd done");
  const u = await read(await open("10u"), LIVE_VARS["10u"]); log("  10u done");
  const v = await read(await open("10v"), LIVE_VARS["10v"]); log("  10v done");
  const swe = Array.from(sd, (x) => (x * 1000) / MM_PER_IN);
  const wind = Array.from(u, (uu, i) => Math.hypot(uu, v[i]) * MS_TO_MPH);
  const tw = times.slice(start, end);
  const iPeak = swe.indexOf(Math.max(...swe));
  $("s_snow").innerHTML = `${swe[iPeak].toFixed(1)}<small> peak SWE (in)</small>`;
  $("s_wind").innerHTML = `${(wind.reduce((a, b) => a + b, 0) / wind.length).toFixed(1)}<small> mean wind (mph)</small>`;
  drawChart($("ch_snow"), tw, swe);
  log("live render done.");
}

function nearest(arr, t) { let b = 0, bd = Infinity;
  for (let i = 0; i < arr.length; i++) { const d = Math.abs(arr[i] - t); if (d < bd) { bd = d; b = i; } } return b; }
function decodeTime(values, units) {
  const m = /(seconds|minutes|hours|days) since (\d{4})-(\d{1,2})-(\d{1,2})/i.exec(units || "");
  if (!m) return Array.from(values, (v) => new Date(Number(v)));
  const mult = { seconds: 1e3, minutes: 6e4, hours: 36e5, days: 864e5 }[m[1].toLowerCase()];
  const base = Date.UTC(+m[2], +m[3] - 1, +m[4]);
  return Array.from(values, (v) => new Date(base + Number(v) * mult));
}

async function build() {
  $("go").disabled = true;
  logEl.textContent = "";
  try {
    const addr = $("addr").value.trim();
    const years = Math.max(1, Math.min(85, +$("years").value || 5));
    const params = new URLSearchParams(location.search);
    let loc;
    if (params.has("lat") && params.has("lon")) {
      loc = { lat: +params.get("lat"), lon: +params.get("lon"), name: "(coords from URL)" };
      log(`coords from URL: ${loc.lat}, ${loc.lon}`);
    } else {
      log(`geocoding: ${addr}`); loc = await geocode(addr);
    }
    log(`→ ${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`);
    $("loc").textContent = loc.name;
    map.setView([loc.lat, loc.lon], 13); marker.setLatLng([loc.lat, loc.lon]);

    const key = snapKey(loc.lat, loc.lon);
    log(`grid cell key ${key}; checking precomputed cache …`);
    const cached = await tryCache(key);
    if (cached) {
      log("loaded precomputed cell (fast path).");
      renderSummary(cached);
      log("DONE.");
    } else {
      await liveFromGDEX(loc, years);
      log("DONE.");
    }
  } catch (e) {
    log("ERROR: " + (e && e.message ? e.message : e));
    console.error(e);
  } finally {
    $("go").disabled = false;
  }
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
window.__appReady = true;          // smoke test waits on this before clicking
log("ready. enter an address and click Build.");
