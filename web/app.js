// PropStory front end — geocode an address, then read ERA5 directly from NSF
// NCAR GDEX (Zarr v2 over OSDF, CORS-open) in the browser, compute a climate
// summary, and render charts/tables. Heavily instrumented so we can SEE where
// time goes (this is the main implementation risk: point reads are slow because
// the GDEX stores are area-chunked, not point-chunked).

import * as zarr from "https://esm.sh/zarrita@0.4.0?bundle";

const GDEX = "https://osdf-data.gdex.ucar.edu/ncar/gdex/d633000/e5.oper.an.sfc.zarr";
const VARS = {            // logical -> {code, varname}
  sd:  { code: "sd",  name: "SD"      },  // snow depth, m water equiv
  t2:  { code: "2t",  name: "VAR_2T"  },  // 2 m temperature, K
  u10: { code: "10u", name: "VAR_10U" },  // 10 m u-wind, m/s
  v10: { code: "10v", name: "VAR_10V" },  // 10 m v-wind, m/s
};
const MM_PER_IN = 25.4, M_TO_IN = 39.37, MS_TO_MPH = 2.23694, SKIABLE_IN = 12;

const $ = (id) => document.getElementById(id);
const logEl = $("log");
function log(msg) { const t = new Date().toISOString().substr(11, 8);
  logEl.textContent += `[${t}] ${msg}\n`; logEl.scrollTop = logEl.scrollHeight;
  console.log(msg); }

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

// CF time decode for "<unit> since YYYY-MM-DD[...]"
function decodeTime(values, units) {
  const m = /(seconds|minutes|hours|days) since (\d{4})-(\d{1,2})-(\d{1,2})/i.exec(units || "");
  if (!m) return values.map((v) => new Date(v)); // fallback
  const mult = { seconds: 1e3, minutes: 6e4, hours: 36e5, days: 864e5 }[m[1].toLowerCase()];
  const base = Date.UTC(+m[2], +m[3] - 1, +m[4]);
  return Array.from(values, (v) => new Date(base + Number(v) * mult));
}

function nearestIndex(arr, target) {
  let best = 0, bd = Infinity;
  for (let i = 0; i < arr.length; i++) { const d = Math.abs(arr[i] - target);
    if (d < bd) { bd = d; best = i; } }
  return best;
}

async function openVar(code) {
  const t0 = performance.now();
  const store = await zarr.withConsolidated(new zarr.FetchStore(`${GDEX}/e5.oper.an.sfc.${code}.zarr`));
  log(`  [${code}] consolidated metadata in ${((performance.now() - t0) / 1000).toFixed(1)}s`);
  return store;
}

async function readPointSeries(store, varname, t0idx, t1idx, ilat, ilon) {
  const arr = await zarr.open(store.resolve(varname), { kind: "array" });
  const t = performance.now();
  const sub = await zarr.get(arr, [zarr.slice(t0idx, t1idx), ilat, ilon]);
  log(`  [${varname}] read ${t1idx - t0idx} steps in ${((performance.now() - t) / 1000).toFixed(1)}s`);
  return sub.data; // 1-D typed array
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
      log(`using coords from URL: ${loc.lat}, ${loc.lon}`);
    } else {
      log(`geocoding: ${addr}`);
      loc = await geocode(addr);
    }
    log(`→ ${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`);
    $("loc").textContent = loc.name;
    map.setView([loc.lat, loc.lon], 13); marker.setLatLng([loc.lat, loc.lon]);
    const lonE = ((loc.lon % 360) + 360) % 360;

    // open snow store, get coords + time once (shared grid across vars)
    log("opening GDEX ERA5 stores …");
    const sdStore = await openVar(VARS.sd.code);
    const latArr = (await zarr.get(await zarr.open(sdStore.resolve("latitude"), { kind: "array" }))).data;
    const lonArr = (await zarr.get(await zarr.open(sdStore.resolve("longitude"), { kind: "array" }))).data;
    const ilat = nearestIndex(latArr, loc.lat), ilon = nearestIndex(lonArr, lonE);
    log(`grid cell: ${(+latArr[ilat]).toFixed(2)}, ${(((+lonArr[ilon] + 180) % 360) - 180).toFixed(2)} (idx ${ilat},${ilon})`);

    const timeA = await zarr.open(sdStore.resolve("time"), { kind: "array" });
    const tvals = (await zarr.get(timeA)).data;
    const times = decodeTime(tvals, timeA.attrs.units);
    const end = times.length;
    const cutoff = +times[end - 1] - years * 365.25 * 864e5;
    let start = end - 1; while (start > 0 && +times[start] > cutoff) start--;
    log(`time: ${times[0].toISOString().slice(0,10)} … ${times[end-1].toISOString().slice(0,10)} (${end} steps); reading last ${years}y = ${end-start} steps`);

    // read each variable's point series for the window
    const sd = await readPointSeries(sdStore, VARS.sd.name, start, end, ilat, ilon);
    const t2store = await openVar(VARS.t2.code);
    const t2 = await readPointSeries(t2store, VARS.t2.name, start, end, ilat, ilon);
    const uStore = await openVar(VARS.u10.code);
    const u = await readPointSeries(uStore, VARS.u10.name, start, end, ilat, ilon);
    const vStore = await openVar(VARS.v10.code);
    const v = await readPointSeries(vStore, VARS.v10.name, start, end, ilat, ilon);

    // compute
    const tw = times.slice(start, end);
    const swe_in = Array.from(sd, (x) => (x * 1000) / MM_PER_IN);
    const wind_mph = Array.from(u, (uu, i) => Math.hypot(uu, v[i]) * MS_TO_MPH);
    const tF = Array.from(t2, (k) => (k - 273.15) * 9 / 5 + 32);

    const peakSWE = Math.max(...swe_in);
    const iPeak = swe_in.indexOf(peakSWE);
    const meanWind = wind_mph.reduce((a, b) => a + b, 0) / wind_mph.length;
    const iWind = wind_mph.indexOf(Math.max(...wind_mph));
    const coldF = Math.min(...tF); const iCold = tF.indexOf(coldF);
    // skiable days/yr: physical depth ≈ SWE*10 (rough, no density here); count days >=12"
    const skiableHrs = swe_in.filter((s) => s * 10 >= SKIABLE_IN).length;
    const skiPerYr = Math.round(skiableHrs / 24 / years);

    $("s_snow").innerHTML = `${peakSWE.toFixed(1)}<small> peak SWE (in)</small>`;
    $("s_ski").innerHTML = `${skiPerYr}<small> skiable days/yr (approx)</small>`;
    $("s_wind").innerHTML = `${meanWind.toFixed(1)}<small> mean wind (mph)</small>`;
    $("s_cold").innerHTML = `${coldF.toFixed(0)}<small> coldest (°F)</small>`;

    drawChart($("ch_snow"), tw, swe_in);
    const fmt = (d) => d.toISOString().slice(0, 16).replace("T", " ") + "Z";
    $("tbl").innerHTML = `<tbody>
      <tr><td>Deepest SWE</td><td class="n">${peakSWE.toFixed(2)} in</td><td>${fmt(tw[iPeak])}</td></tr>
      <tr><td>Windiest hour</td><td class="n">${(wind_mph[iWind]).toFixed(1)} mph</td><td>${fmt(tw[iWind])}</td></tr>
      <tr><td>Coldest hour</td><td class="n">${coldF.toFixed(1)} °F</td><td>${fmt(tw[iCold])}</td></tr>
      <tr><td class="muted">Source</td><td colspan="2" class="muted">GDEX d633000 ERA5 · cell ${(+latArr[ilat]).toFixed(2)},${(((+lonArr[ilon]+180)%360)-180).toFixed(2)}</td></tr>
      </tbody>`;
    log("DONE.");
  } catch (e) {
    log("ERROR: " + (e && e.message ? e.message : e));
    console.error(e);
  } finally {
    $("go").disabled = false;
  }
}

function drawChart(canvas, times, vals) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d"); c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
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
