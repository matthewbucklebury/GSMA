/* Tower Ownership Explorer — front end (vanilla JS + Chart.js + D3 map) */
"use strict";

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const SERIES = () => [1,2,3,4,5,6,7,8].map(i => css(`--series-${i}`));
const OTHER = () => css("--other");
const TEXT2 = () => css("--text-secondary");
// sequential blue ramp (light->dark) from the reference palette
const SEQ = ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7",
             "#3987e5","#2a78d6","#256abf","#1c5cab","#184f95","#104281","#0d366b"];

const state = { meta: null, at: "", league: null, mnos: null, countries: null,
                mapData: {}, cmp: { kind: "country", items: [] }, colorSlots: new Map() };

const DATA_QUALITY_LEVELS = {
  public_gsma_verified: "Public data, GSMA verified",
  public_trusted: "Public data, trusted but not GSMA verified",
  public_unverified: "Public data, not GSMA verified",
  private_gsma_verified: "Private data, GSMA verified",
  estimated: "Estimated",
};
function qualityTip(r) {
  const q = DATA_QUALITY_LEVELS[r.verification_level || r.data_quality] ||
            DATA_QUALITY_LEVELS.public_unverified;
  const lu = r.last_updated ? ` · updated ${String(r.last_updated).slice(0, 10)}` : "";
  return `Data quality: ${q}${lu}`;
}

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const fmt = n => (n === null || n === undefined || isNaN(n)) ? "—"
  : Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(path) {
  const sep = path.includes("?") ? "&" : "?";
  const r = await fetch(state.at ? `${path}${sep}at=${state.at}` : path);
  return r.json();
}
async function apiRaw(path, opts) { return (await fetch(path, opts)).json(); }

/* Chart-scoped colour maps: colour follows the entity within a chart session;
   entities beyond the 8 slots are folded into "Other" by the callers. */
function makeColorMap() { return new Map(); }
function colorIn(map, name) {
  if (!map.has(name)) {
    const used = new Set(map.values());
    const free = SERIES().find(c => !used.has(c));
    map.set(name, free || OTHER());
  }
  return map.get(name);
}
function pruneColors(map, keep) {
  [...map.keys()].forEach(k => { if (!keep.includes(k)) map.delete(k); });
}
const cmpColors = makeColorMap();

/* ------------------------------------------------ tabs */
$("#tabs").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  $$("#tabs button").forEach(x => x.classList.toggle("active", x === b));
  $$("main > section").forEach(s => s.hidden = s.id !== `tab-${b.dataset.tab}`);
  loadTab(b.dataset.tab);
});
function activeTab() { return $("#tabs button.active").dataset.tab; }

function loadTab(tab, force = false) {
  if (tab === "league" && (force || !state.league)) loadLeague();
  if (tab === "mnos" && (force || !state.mnos)) loadMnos();
  if (tab === "countries" && (force || !state.countries)) loadCountries();
  if (tab === "map") loadMap(force);
  if (tab === "explore") renderCompare();
  if (tab === "entry") loadOverrides();
  if (tab === "about") renderAbout();
}

/* ------------------------------------------------ header: meta, period, search */
async function init() {
  state.meta = await apiRaw("/api/meta");
  const sel = $("#global-at");
  state.meta.periods.slice().reverse().forEach(p => {
    const o = document.createElement("option");
    o.value = p; o.textContent = p.replace("Q", " Q");
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => {
    state.at = sel.value;
    state.league = state.mnos = state.countries = null;
    state.mapData = {};
    loadTab(activeTab(), true);
  });
  const years = $("#e-year");
  for (let y = 2026; y >= 2012; y--) {
    const o = document.createElement("option"); o.value = y; o.textContent = y;
    years.appendChild(o);
  }
  wireSearch($("#global-search"), $("#global-search-results"), item => {
    if (item.kind === "company") openCompany(item.id); else openCountry(item.id);
  });
  wireSearch($("#cmp-search"), $("#cmp-search-results"), item => {
    if (state.cmp.items.length >= 8 || state.cmp.items.some(i => i.id === item.id)) return;
    state.cmp.items.push(item);
    renderCompare();
  }, () => $("#cmp-kind").value);
  loadLeague();
  applyHash();   // support #company/<id> and #country/<id> deep links
}

function wireSearch(input, box, onPick, kindFilter) {
  let t;
  input.addEventListener("input", () => {
    clearTimeout(t);
    const q = input.value.trim();
    if (q.length < 2) { box.style.display = "none"; return; }
    t = setTimeout(async () => {
      const r = await apiRaw(`/api/search?q=${encodeURIComponent(q)}`);
      let items = [
        ...r.companies.map(c => ({ kind: "company", id: c.id, label: c.name, sub: c.type })),
        ...r.countries.map(c => ({ kind: "country", id: c.id, label: c.name, sub: c.region })),
      ];
      if (kindFilter) items = items.filter(it => it.kind === kindFilter());
      box.innerHTML = items.length ? items.map((it, i) =>
        `<div data-i="${i}"><b>${esc(it.label)}</b> <span class="muted small">${esc(it.sub || "")} · ${it.kind}</span></div>`
      ).join("") : `<div class="muted">no matches</div>`;
      box.style.display = "block";
      box.onclick = e => {
        const d = e.target.closest("[data-i]"); if (!d) return;
        box.style.display = "none"; input.value = "";
        onPick(items[+d.dataset.i]);
      };
    }, 180);
  });
  document.addEventListener("click", e => {
    if (!box.contains(e.target) && e.target !== input) box.style.display = "none";
  });
}

/* ------------------------------------------------ sortable tables */
function renderTable(el, cols, rows, onRow) {
  const sortKey = el.dataset.sortKey, sortDir = +(el.dataset.sortDir || -1);
  if (sortKey) {
    const c = cols.find(c => c.key === sortKey);
    rows = rows.slice().sort((a, b) => {
      const va = c.sortVal ? c.sortVal(a) : a[sortKey], vb = c.sortVal ? c.sortVal(b) : b[sortKey];
      if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "number" ? va - vb : String(va).localeCompare(String(vb))) * sortDir;
    });
  }
  el.innerHTML =
    `<thead><tr>${cols.map(c =>
      `<th class="${c.num ? "num" : ""}" data-key="${c.key}">${c.label}${sortKey===c.key?(sortDir>0?" ↑":" ↓"):""}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((r, i) =>
      `<tr class="${onRow ? "click" : ""}" data-i="${i}">${cols.map(c =>
        `<td class="${c.num ? "num" : ""}">${c.render(r)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  el.querySelector("thead").onclick = e => {
    const th = e.target.closest("th"); if (!th) return;
    const k = th.dataset.key;
    el.dataset.sortDir = (el.dataset.sortKey === k) ? -(+el.dataset.sortDir || -1) : -1;
    el.dataset.sortKey = k;
    renderTable(el, cols, rows, onRow);
  };
  if (onRow) el.querySelector("tbody").onclick = e => {
    const a = e.target.closest("a.link"); if (a) return;
    const tr = e.target.closest("tr[data-i]"); if (tr) onRow(rows[+tr.dataset.i]);
  };
}

/* ------------------------------------------------ league tab */
async function loadLeague() {
  state.league = (await api("/api/league")).league;
  const models = [...new Set(state.league.map(l => (l.business_model || "").trim()).filter(Boolean))].sort();
  $("#league-model").innerHTML = `<option value="">All</option>` +
    models.map(m => `<option>${esc(m)}</option>`).join("");
  const totTowers = state.league.reduce((s, l) => s + (l.towers || 0), 0);
  $("#league-stats").innerHTML = [
    [fmt(state.league.length), "towercos & infracos tracked"],
    [fmt(totTowers), "towers in league table"],
    [fmt(state.meta.counts.countries), "countries"],
    [fmt(state.meta.counts.observations), "observations"],
  ].map(([v, k]) => `<div class="stat-tile"><div class="v">${v}</div><div class="k">${k}</div></div>`).join("");
  renderLeague();
}
function renderLeague() {
  const f = $("#league-filter").value.toLowerCase();
  const model = $("#league-model").value;
  const fc = $("#league-country").value.toLowerCase().trim();
  let rows = state.league.filter(l =>
    (!f || (l.company + " " + (l.owners || "") + " " + l.footprint.join(" ")).toLowerCase().includes(f)) &&
    (!model || (l.business_model || "").trim() === model) &&
    (!fc || l.footprint.some(c => c.toLowerCase().includes(fc))));
  $("#league-count").textContent = `${rows.length} companies`;
  renderTable($("#league-table"), [
    { key: "rank", label: "Rank", num: true, render: r => fmt(r.rank) },
    { key: "company", label: "Company", render: r =>
        `<a class="link" title="${esc(qualityTip(r))}" onclick="openCompany(${r.company_id})">${esc(r.company)}</a>` },
    { key: "business_model", label: "Model", render: r => r.business_model ?
        `<span class="pill">${esc(r.business_model.trim())}</span>` : "" },
    { key: "towers", label: "Towers", num: true, render: r => `<b>${fmt(r.towers)}</b>` },
    { key: "towers_sum", label: "Guide country sum", num: true, render: r =>
        r.towers_sum ? `${fmt(r.towers_sum)} <span class="muted small">(${r.guide_countries})</span>` : "<span class='muted'>—</span>" },
    { key: "country_count", label: "Countries", num: true, render: r => fmt(r.country_count) },
    { key: "footprint", label: "Footprint", sortVal: r => r.footprint.length, render: r =>
        `<span class="small muted">${esc(r.footprint.slice(0, 6).join(", "))}${r.footprint.length > 6 ? ` +${r.footprint.length - 6}` : ""}</span>` },
    { key: "known_tenants", label: "Known tenants", sortVal: r => r.known_tenants.length, render: r =>
        r.known_tenants.length
          ? `<span class="small muted" title="${esc(r.known_tenants.join(", "))}">${esc(r.known_tenants.slice(0, 4).join(", "))}${r.known_tenants.length > 4 ? ` +${r.known_tenants.length - 4}` : ""}</span>`
          : "<span class='muted'>—</span>" },
    { key: "as_of", label: "Last updated", sortVal: r => (r.as_of_year || 0) * 10 + (r.as_of_quarter || 0),
      render: r => r.as_of === "unknown" ? `<span class="pill unknown">unknown</span>` : esc(r.as_of) },
    { key: "_edit", label: "", render: r =>
        `<button class="btn secondary small" onclick="event.stopPropagation();openTowercoForm(${r.company_id}, '${esc(r.company).replace(/'/g, "&#39;")}')">Edit</button>` },
  ], rows, r => openCompany(r.company_id));
}
["league-filter", "league-model", "league-country"].forEach(id =>
  $("#" + id).addEventListener("input", renderLeague));

/* ------------------------------------------------ MNOs tab */
async function loadMnos() {
  state.mnos = (await api("/api/mnos")).mnos;
  renderMnos();
}
function renderMnos() {
  const f = $("#mno-filter").value.toLowerCase();
  const ownersOnly = $("#mno-owners-only").checked;
  let rows = state.mnos.filter(m =>
    (!f || m.company.toLowerCase().includes(f)) &&
    (!ownersOnly || m.towers_owned > 0));
  $("#mno-count").textContent = `${rows.length} operators (ranked by footprint)`;
  renderTable($("#mno-table"), [
    { key: "company", label: "Operator", render: r =>
        `<a class="link" onclick="openCompany(${r.company_id})">${esc(r.company)}</a> <span class="pill ${r.type}">${r.type}</span>` },
    { key: "footprint", label: "Footprint", num: true, sortVal: r => r.footprint.length,
      render: r => fmt(r.footprint.length) },
    { key: "marketlist", label: "Markets", sortVal: r => r.footprint.length, render: r =>
        `<span class="small muted">${esc(r.footprint.slice(0, 7).map(m => m.country).join(", "))}${r.footprint.length > 7 ? ` +${r.footprint.length - 7}` : ""}</span>` },
    { key: "towers_owned", label: "Towers owned (guides)", num: true,
      render: r => r.towers_owned ? `<b>${fmt(r.towers_owned)}</b>` : "<span class='muted'>0</span>" },
    { key: "owns_in", label: "Owns towers in", sortVal: r => Object.keys(r.owns_in).length, render: r =>
        `<span class="small muted">${esc(Object.keys(r.owns_in).slice(0, 6).join(", "))}</span>` },
    { key: "towercos", label: "Towercos", sortVal: r => r.towercos.length,
      render: r => `<span class="small muted">${esc(r.towercos.slice(0, 5).join(", "))}${r.towercos.length > 5 ? " +" + (r.towercos.length - 5) : ""}</span>` },
    { key: "_edit", label: "", render: r =>
        `<button class="btn secondary small" onclick="event.stopPropagation();openMnoForm(${r.company_id}, '${esc(r.company).replace(/'/g, "&#39;")}')">Edit</button>` },
  ], rows, r => openCompany(r.company_id));
}
["mno-filter", "mno-owners-only"].forEach(id => $("#" + id).addEventListener("input", renderMnos));

/* ------------------------------------------------ countries tab */
async function loadCountries() {
  state.countries = (await api("/api/countries")).countries;
  const regions = [...new Set(state.countries.map(c => c.region).filter(Boolean))].sort();
  $("#country-region").innerHTML = `<option value="">All</option>` +
    regions.map(r => `<option>${esc(r)}</option>`).join("");
  renderCountries();
}
function renderCountries() {
  const f = $("#country-filter").value.toLowerCase();
  const reg = $("#country-region").value;
  let rows = state.countries.filter(c =>
    (!f || c.name.toLowerCase().includes(f)) && (!reg || c.region === reg) &&
    (c.region || c.owners_count > 0 || c.mnos_active > 0 || f));
  $("#country-count").textContent = `${rows.length} countries (A-Z)`;
  const listCell = (arr, n, label) => arr.length
    ? `<span class="small muted" title="${esc(arr.map(label).join(", "))}">${esc(arr.slice(0, n).map(label).join(", "))}${arr.length > n ? ` +${arr.length - n}` : ""}</span>`
    : "<span class='muted'>—</span>";
  renderTable($("#country-table"), [
    { key: "name", label: "Country", render: r => `<a class="link" onclick="openCountry(${r.id})">${esc(r.name)}</a>` },
    { key: "region", label: "Region", render: r => `<span class="pill">${esc(r.region || "Other")}</span>` },
    { key: "total_towers", label: "Total towers", num: true,
      render: r => `<b>${fmt(r.total_towers)}</b>` },
    { key: "towerco_share", label: "Towerco share", num: true,
      render: r => r.towerco_share !== null ? r.towerco_share + "%" : "—" },
    { key: "towercos_active", label: "Towercos", num: true, render: r => fmt(r.towercos_active) },
    { key: "mnos_active", label: "MNOs", num: true, render: r => fmt(r.mnos_active) },
    { key: "top_owner", label: "Largest owner", sortVal: r => r.top_owner ? -r.top_owner.towers : 0,
      render: r => r.top_owner ? `${esc(r.top_owner.company)} <span class="muted small">(${fmt(r.top_owner.towers)})</span>` : "—" },
    { key: "towerco_list", label: "Towercos active", sortVal: r => r.towercos.length,
      render: r => listCell(r.towercos, 4, t => t.company) },
    { key: "mno_list", label: "MNOs active", sortVal: r => r.mnos.length,
      render: r => listCell(r.mnos, 4, m => m.company) },
    { key: "_edit", label: "", render: r =>
        `<button class="btn secondary small" onclick="event.stopPropagation();openCountryForm(${r.id}, '${esc(r.name).replace(/'/g, "&#39;")}')">Edit</button>` },
  ], rows, r => openCountry(r.id));
}
["country-filter", "country-region"].forEach(id => $("#" + id).addEventListener("input", renderCountries));

/* ------------------------------------------------ map tab */
let world = null;
const MAP_ALIASES = {  // dataset name -> world-atlas name
  "United States": "United States of America", "DRC": "Dem. Rep. Congo",
  "Congo Brazzaville": "Congo", "Czech Republic": "Czechia",
  "Bosnia & Herzegovina": "Bosnia and Herz.", "Dominican Republic": "Dominican Rep.",
  "South Sudan": "S. Sudan", "Equatorial Guinea": "Eq. Guinea",
  "Central African Republic": "Central African Rep.", "Guinea-Bissau": "Guinea-Bissau",
  "Côte d'Ivoire": "Côte d'Ivoire", "North Macedonia": "Macedonia",
};
async function loadMap(force) {
  const metric = $("#map-metric").value;
  if (!world) world = await (await fetch("vendor/world-110m.json")).json();
  if (force) state.mapData = {};
  if (!state.mapData[metric]) state.mapData[metric] = (await api(`/api/map?metric=${metric}`)).rows;
  drawMap(metric, state.mapData[metric]);
}
$("#map-metric").addEventListener("change", () => loadMap(false));
$("#map-regional").addEventListener("change", () => loadMap(false));

function drawMap(metric, rows) {
  const svg = d3.select("#map-svg");
  svg.selectAll("*").remove();
  const countries = topojson.feature(world, world.objects.countries).features;
  const byName = {};
  rows.forEach(r => { byName[MAP_ALIASES[r.name] || r.name] = r; });
  const regional = $("#map-regional").checked;
  // quantile position within either the whole world or the country's region,
  // so each region's spread stays readable despite global outliers
  const pools = {};
  rows.forEach(r => {
    if (r.value == null) return;
    const key = regional ? (r.region || "Other") : "_all";
    (pools[key] = pools[key] || []).push(r.value);
  });
  Object.values(pools).forEach(a => a.sort((x, y) => x - y));
  const vals = rows.map(r => r.value).filter(v => v != null).sort((a, b) => a - b);
  const scale = (v, region) => {
    const pool = pools[regional ? (region || "Other") : "_all"] || [];
    if (v == null || !pool.length) return null;
    const q = d3.bisectLeft(pool, v) / Math.max(pool.length - 1, 1);
    return SEQ[Math.min(SEQ.length - 1, Math.floor(q * (SEQ.length - 1)))];
  };
  const proj = d3.geoNaturalEarth1().fitSize([960, 500], { type: "Sphere" });
  const path = d3.geoPath(proj);
  const tip = $("#map-tip");
  svg.append("path").attr("d", path({ type: "Sphere" }))
    .attr("fill", "none").attr("stroke", css("--border"));
  svg.selectAll("path.country").data(countries).join("path")
    .attr("class", "country").attr("d", path)
    .attr("fill", d => { const r = byName[d.properties.name]; return r ? scale(r.value, r.region) : css("--surface-1"); })
    .attr("stroke", css("--border")).attr("stroke-width", 0.5)
    .style("cursor", d => byName[d.properties.name] ? "pointer" : "default")
    .on("mousemove", (e, d) => {
      const r = byName[d.properties.name];
      tip.style.display = "block";
      tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY + 10) + "px";
      tip.innerHTML = `<b>${esc(d.properties.name)}</b><br>` + (r
        ? `${$("#map-metric").selectedOptions[0].text}: <b>${fmt(r.value)}</b>` +
          (r.as_of ? `<br><span class="muted small">as of ${esc(r.as_of)} · ${esc(r.region)}</span>` : "")
        : `<span class="muted">no data extracted</span>`);
    })
    .on("mouseleave", () => { tip.style.display = "none"; })
    .on("click", async (e, d) => {
      const r = byName[d.properties.name];
      if (!r) return;
      const s = await apiRaw(`/api/search?q=${encodeURIComponent(r.name)}`);
      const hit = s.countries.find(c => c.name === r.name);
      if (hit) openCountry(hit.id);
    });
  // legend: min -> max with 5 sample swatches
  const leg = $("#map-legend");
  if (vals.length) {
    leg.innerHTML = `<span>${fmt(vals[0])}</span>` +
      [0, 3, 6, 9, 12].map(i => `<span class="sw" style="background:${SEQ[i]}"></span>`).join("") +
      `<span>${fmt(vals[vals.length - 1])}</span>`;
  } else leg.innerHTML = "";
}

/* ------------------------------------------------ explore & compare */
const CMP_VIEWS = {
  country: [["ownership", "Ownership breakdown (stacked)"], ["total_towers", "Total towers"],
            ["towerco_share", "Towerco share %"]],
  company: [["holdings", "Towers by country (stacked)"], ["league", "Total tower count (league)"]],
};
$("#cmp-kind").addEventListener("change", () => {
  state.cmp.kind = $("#cmp-kind").value;
  state.cmp.items = [];
  renderCompare();
});
$("#cmp-view").addEventListener("change", renderCompare);
$("#cmp-table-view").addEventListener("change", renderCompare);

let cmpChart = null;
async function renderCompare() {
  const kind = state.cmp.kind;
  const viewSel = $("#cmp-view");
  const wanted = CMP_VIEWS[kind].map(v => v[0]);
  if (!wanted.includes(viewSel.value)) {
    viewSel.innerHTML = CMP_VIEWS[kind].map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
  }
  $("#cmp-chips").innerHTML = state.cmp.items.map((it, i) =>
    `<span class="chip">${esc(it.label)} <b data-i="${i}">×</b></span>`).join("");
  $("#cmp-chips").onclick = e => {
    if (e.target.dataset.i !== undefined) {
      state.cmp.items.splice(+e.target.dataset.i, 1); renderCompare();
    }
  };
  const canvas = $("#cmp-canvas"), tableDiv = $("#cmp-table");
  if (cmpChart) { cmpChart.destroy(); cmpChart = null; }
  tableDiv.innerHTML = "";
  if (!state.cmp.items.length) { $("#cmp-title").textContent = "Pick entities to compare"; return; }
  const ids = state.cmp.items.map(i => i.id).join(",");
  const data = await api(`/api/compare?kind=${kind}&ids=${ids}`);
  const view = viewSel.value;
  const showTable = $("#cmp-table-view").checked;
  canvas.style.display = showTable ? "none" : "";
  let cfg = null, tableHTML = "", title = "", src = "TowerXchange guides + League Table";

  if (kind === "country" && view === "ownership") {
    title = "Site ownership by owner (latest per country)";
    const topOwners = new Map();
    data.items.forEach(c => c.owners.forEach(o => topOwners.set(o.company, (topOwners.get(o.company) || 0) + o.v)));
    const owners = [...topOwners.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(e => e[0]);
    pruneColors(cmpColors, owners);
    const datasets = owners.map(o => ({
      label: o, backgroundColor: colorIn(cmpColors, o), borderColor: css("--surface-2"), borderWidth: 1,
      borderRadius: 3,
      data: data.items.map(c => (c.owners.find(x => x.company === o) || {}).v || 0),
    }));
    datasets.push({ label: "Other owners", backgroundColor: OTHER(), borderColor: css("--surface-2"),
      borderWidth: 1, borderRadius: 3,
      data: data.items.map(c => c.owners.filter(x => !owners.includes(x.company)).reduce((s, x) => s + x.v, 0)) });
    cfg = stackedBarCfg(data.items.map(c => c.name), datasets);
    tableHTML = ownershipTable(data.items);
  } else if (kind === "country") {
    const metricName = CMP_VIEWS.country.find(v => v[0] === view)[1];
    title = metricName + " by country";
    const val = c => view === "towerco_share"
      ? towercoShare(c)
      : c.owners.reduce((s, o) => s + (o.v || 0), 0);   // total = sum of tracked owners
    cfg = simpleBarCfg(data.items.map(c => c.name), data.items.map(val), metricName);
    tableHTML = `<table class="data"><tr><th>Country</th><th class="num">${metricName}</th></tr>` +
      data.items.map(c => `<tr><td>${esc(c.name)}</td><td class="num">${fmt(val(c))}</td></tr>`).join("") + "</table>";
  } else if (view === "holdings") {
    title = "Towers by country (latest, from guides)";
    const allC = new Map();
    data.items.forEach(co => co.holdings.forEach(h => allC.set(h.country, (allC.get(h.country) || 0) + h.v)));
    const countries = [...allC.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(e => e[0]);
    pruneColors(cmpColors, countries);
    const datasets = countries.map(c => ({
      label: c, backgroundColor: colorIn(cmpColors, c), borderColor: css("--surface-2"), borderWidth: 1, borderRadius: 3,
      data: data.items.map(co => (co.holdings.find(h => h.country === c) || {}).v || 0),
    }));
    datasets.push({ label: "Other countries", backgroundColor: OTHER(), borderColor: css("--surface-2"),
      borderWidth: 1, borderRadius: 3,
      data: data.items.map(co => co.holdings.filter(h => !countries.includes(h.country)).reduce((s, h) => s + h.v, 0)) });
    cfg = stackedBarCfg(data.items.map(c => c.name), datasets);
    tableHTML = `<table class="data"><tr><th>Company</th><th>Country</th><th class="num">Towers</th></tr>` +
      data.items.flatMap(co => co.holdings.map(h =>
        `<tr><td>${esc(co.name)}</td><td>${esc(h.country)}</td><td class="num">${fmt(h.v)}</td></tr>`)).join("") + "</table>";
  } else {
    title = "Global tower count (league table)";
    cfg = simpleBarCfg(data.items.map(c => c.name), data.items.map(c => c.league_towers), "Towers");
    tableHTML = `<table class="data"><tr><th>Company</th><th class="num">Rank</th><th class="num">Towers</th></tr>` +
      data.items.map(c => `<tr><td>${esc(c.name)}</td><td class="num">${fmt(c.league_rank)}</td><td class="num">${fmt(c.league_towers)}</td></tr>`).join("") + "</table>";
  }
  $("#cmp-title").textContent = title;
  $("#cmp-src").textContent = "Source: " + src + (state.at ? ` · viewed as of ${state.at}` : " · latest data");
  if (showTable) tableDiv.innerHTML = tableHTML;
  else cmpChart = new Chart(canvas, cfg);
}
function towercoShare(c) {
  const tot = c.owners.reduce((s, o) => s + (o.v || 0), 0);
  const tc = c.owners.filter(o => ["towerco", "jv-infraco"].includes(o.type)).reduce((s, o) => s + (o.v || 0), 0);
  return tot ? +(100 * tc / tot).toFixed(1) : null;
}
function ownershipTable(items) {
  return `<table class="data"><tr><th>Country</th><th>Owner</th><th>Type</th><th class="num">Towers</th></tr>` +
    items.flatMap(c => c.owners.map(o =>
      `<tr><td>${esc(c.name)}</td><td>${esc(o.company)}</td><td><span class="pill ${o.type}">${o.type}</span></td><td class="num">${fmt(o.v)}</td></tr>`)).join("") + "</table>";
}
function chartBase() {
  return { color: TEXT2(), font: { family: "inherit" } };
}
function stackedBarCfg(labels, datasets) {
  return { type: "bar",
    data: { labels, datasets },
    options: { responsive: true, plugins: { legend: { position: "bottom", labels: { color: TEXT2(), boxWidth: 14 } },
      tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmt(ctx.parsed.y)}` } } },
      scales: { x: { stacked: true, ticks: { color: TEXT2() }, grid: { display: false } },
                y: { stacked: true, ticks: { color: TEXT2(), callback: v => fmt(v) }, grid: { color: css("--border") } } } } };
}
function simpleBarCfg(labels, values, name) {
  return { type: "bar",
    data: { labels, datasets: [{ label: name, data: values, backgroundColor: SERIES()[0],
      borderRadius: 4, maxBarThickness: 60 }] },
    options: { responsive: true, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: ctx => `${name}: ${fmt(ctx.parsed.y)}` } } },
      scales: { x: { ticks: { color: TEXT2() }, grid: { display: false } },
                y: { ticks: { color: TEXT2(), callback: v => fmt(v) }, grid: { color: css("--border") } } } } };
}

/* ------------------------------------------------ drawer: entity detail */
let drawerChart = null;
function closeDrawer() {
  $("#drawer").classList.remove("open");
  if (drawerChart) { drawerChart.destroy(); drawerChart = null; }
  if (location.hash) history.replaceState(null, "", location.pathname);
}
window.closeDrawer = closeDrawer;

async function openCountry(id, fromHash) {
  if (!fromHash) history.replaceState(null, "", `#country/${id}`);
  const d = await api(`/api/country/${id}`);
  const c = d.country;
  const holdings = d.observations.filter(o => o.metric === "towers");
  // latest per company+segment
  const latest = latestBy(holdings, o => `${o.company}|${o.segment}`);
  latest.sort((a, b) => (b.value || 0) - (a.value || 0));
  const total = latest.reduce((s, o) => s + (o.value || 0), 0);
  const tcTotal = latest.filter(o => ["towerco", "jv-infraco"].includes(o.company_type))
                        .reduce((s, o) => s + (o.value || 0), 0);
  const body = $("#drawer-body");
  body.innerHTML = `
    <h2>${esc(c.name)} <span class="pill">${esc(c.region || "Other")}</span>
      <button class="btn secondary small" onclick="openCountryForm(${c.id}, '${esc(c.name).replace(/'/g, "&#39;")}')">Edit data</button></h2>
    <div class="stat-row">
      ${tile(fmt(total), "Total towers (tracked owners)")}
      ${tile(total ? (100 * tcTotal / total).toFixed(1) + "%" : "—", "towerco-owned share")}
      ${tile(fmt(latest.length), "owners tracked")}
      ${tile(fmt(d.mnos.length), "MNOs active")}
    </div>
    <div class="chart-box"><h3>Ownership (latest)</h3><canvas id="drawer-canvas" height="210"></canvas>
      <div class="src">TowerXchange guide pie extraction · confidence flags shown in table</div></div>
    <h3>Owners</h3>
    <table class="data">${ownerRows(latest)}</table>
    <h3>MNOs active in market</h3>
    <div class="chips">${d.mnos.map(m => `<span class="chip"><a class="link" onclick="openCompany(${m.company_id})">${esc(m.company)}</a></span>`).join("") || "<span class='muted'>none recorded</span>"}</div>
    <h3>League-table companies with this market in footprint</h3>
    <div class="chips">${d.league_footprint.map(m => `<span class="chip"><a class="link" onclick="openCompany(${m.company_id})">${esc(m.company)}</a></span>`).join("") || "<span class='muted'>none</span>"}</div>
    <h3>All observations (history)</h3>
    <div style="overflow-x:auto">${historyTable(d.observations)}</div>`;
  $("#drawer").classList.add("open");
  const top = latest.filter(o => o.value).slice(0, 8);
  const other = latest.filter(o => o.value).slice(8).reduce((s, o) => s + o.value, 0);
  if (drawerChart) drawerChart.destroy();
  drawerChart = new Chart($("#drawer-canvas"), {
    type: "doughnut",
    data: { labels: [...top.map(o => o.company + (o.segment !== "all" ? ` (${o.segment})` : "")), ...(other ? ["Other"] : [])],
      datasets: [{ data: [...top.map(o => o.value), ...(other ? [other] : [])],
        backgroundColor: (() => { const m = makeColorMap(); return [...top.map(o => colorIn(m, o.company)), ...(other ? [OTHER()] : [])]; })(),
        borderColor: css("--surface-2"), borderWidth: 2 }] },
    options: { plugins: { legend: { position: "right", labels: { color: TEXT2(), boxWidth: 12 } },
      tooltip: { callbacks: { label: ctx => `${ctx.label}: ${fmt(ctx.parsed)} towers` } } } } });
}
window.openCountry = openCountry;

async function openCompany(id, fromHash) {
  if (!fromHash) history.replaceState(null, "", `#company/${id}`);
  const d = await api(`/api/company/${id}`);
  const c = d.company;
  const holdings = d.observations.filter(o => o.metric === "towers" && o.country);
  const latest = latestBy(holdings, o => `${o.country}|${o.segment}`);
  latest.sort((a, b) => (b.value || 0) - (a.value || 0));
  const league = d.league[0];
  const body = $("#drawer-body");
  const isTowerco = ["towerco", "jv-infraco"].includes(c.type);
  const editBtn = isTowerco
    ? `<button class="btn secondary small" onclick="openTowercoForm(${c.id}, '${esc(c.name).replace(/'/g, "&#39;")}')">Edit data</button>`
    : (c.type === "mno"
       ? `<button class="btn secondary small" onclick="openMnoForm(${c.id}, '${esc(c.name).replace(/'/g, "&#39;")}')">Edit data</button>` : "");
  body.innerHTML = `
    <h2>${esc(c.name)} <span class="pill ${c.type}" title="${esc(qualityTip(c))}">${esc(c.type)}</span> ${editBtn}</h2>
    ${c.owners ? `<div class="muted small">Owners: ${esc(c.owners)}</div>` : ""}
    <div class="muted small">${esc(qualityTip(c))}</div>
    <div class="stat-row">
      ${league ? tile("#" + league.rank, "league rank") : ""}
      ${league ? tile(fmt(league.towers), "Total towers (league)", league) : ""}
      ${tile(fmt(latest.reduce((s, o) => s + (o.value || 0), 0)), "towers in guides (sum)")}
      ${tile(fmt(new Set(latest.map(o => o.country)).size), "countries with counts")}
    </div>
    ${latest.length ? `<div class="chart-box"><h3>Holdings by country (latest)</h3>
      <canvas id="drawer-canvas" height="${Math.max(120, latest.length * 22)}"></canvas></div>` : ""}
    ${latest.length ? `<h3>Holdings</h3><table class="data">${countryRows(latest)}</table>` : ""}
    ${d.footprint.length ? `<h3>Footprint</h3><div class="small muted">${esc(d.footprint.join(", "))}</div>` : ""}
    ${d.mno_markets.length ? `<h3>Active as MNO in</h3><div class="small muted">${esc(d.mno_markets.join(", "))}</div>` : ""}
    ${d.anchor_tenants.length ? `<h3>Known tenants</h3><div class="chips">${d.anchor_tenants.map(t =>
        t.tenant_company_id ? `<span class="chip"><a class="link" onclick="openCompany(${t.tenant_company_id})">${esc(t.tenant_name)}</a></span>`
                            : `<span class="chip">${esc(t.tenant_name)}</span>`).join("")}</div>` : ""}
    ${d.anchor_tenant_of.length ? `<h3>Towercos (leases from)</h3><div class="chips">${d.anchor_tenant_of.map(t =>
        `<span class="chip"><a class="link" onclick="openCompany(${t.company_id})">${esc(t.company)}</a></span>`).join("")}</div>` : ""}
    <h3>All observations (history)</h3>
    <div style="overflow-x:auto">${historyTable(d.observations, true)}</div>`;
  $("#drawer").classList.add("open");
  if (drawerChart) { drawerChart.destroy(); drawerChart = null; }
  if (latest.length) {
    drawerChart = new Chart($("#drawer-canvas"), {
      type: "bar",
      data: { labels: latest.map(o => o.country + (o.segment !== "all" ? ` (${o.segment})` : "")),
        datasets: [{ data: latest.map(o => o.value), backgroundColor: SERIES()[0], borderRadius: 4 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${fmt(ctx.parsed.x)} towers` } } },
        scales: { x: { ticks: { color: TEXT2(), callback: v => fmt(v) }, grid: { color: css("--border") } },
                  y: { ticks: { color: TEXT2(), autoSkip: false }, grid: { display: false } } } } });
  }
}
window.openCompany = openCompany;

function latestBy(rows, keyFn) {
  const seen = new Map();
  const rank = o => [(o.as_of_year ? 1 : 0), o.as_of_year || 0, o.as_of_quarter || 0, o.is_override, o.id];
  rows.forEach(o => {
    const k = keyFn(o), prev = seen.get(k);
    if (!prev || rank(o) > rank(prev)) seen.set(k, o);  // lexicographic array compare
  });
  return [...seen.values()];
}
function tile(v, k, obs) {
  const asof = obs && obs.as_of ? `<span class="muted"> · ${esc(obs.as_of)}</span>` : "";
  return `<div class="stat-tile"><div class="v">${v ?? "—"}</div><div class="k">${k}${asof}</div></div>`;
}
function confPill(o) {
  let pills = "";
  if (o.confidence && o.confidence !== "reported") pills += ` <span class="pill ${o.confidence}">${o.confidence}</span>`;
  if (o.is_override) pills += ` <span class="pill override">override</span>`;
  if (o.verification_level && o.verification_level !== "public_unverified")
    pills += ` <span class="pill" title="${esc(DATA_QUALITY_LEVELS[o.verification_level] || "")}">${esc(o.verification_level.replace(/_/g, " "))}</span>`;
  return pills;
}
function ownerRows(rows) {
  return `<tr><th>Owner</th><th>Type</th><th>Segment</th><th class="num">Towers</th><th>As of</th></tr>` +
    rows.map(o => `<tr><td>${o.company_id ? `<a class="link" onclick="openCompany(${o.company_id})">${esc(o.company)}</a>` : esc(o.company)}${confPill(o)}</td>
      <td><span class="pill ${o.company_type}">${esc(o.company_type || "")}</span></td>
      <td>${o.segment === "all" ? "" : esc(o.segment)}</td>
      <td class="num"><b>${fmt(o.value)}</b></td><td class="small muted">${esc(o.as_of)}</td></tr>`).join("");
}
function countryRows(rows) {
  return `<tr><th>Country</th><th>Segment</th><th class="num">Towers</th><th>As of</th><th>Source</th></tr>` +
    rows.map(o => `<tr><td>${esc(o.country)}${confPill(o)}</td><td>${o.segment === "all" ? "" : esc(o.segment)}</td>
      <td class="num"><b>${fmt(o.value)}</b></td><td class="small muted">${esc(o.as_of)}</td>
      <td class="small muted">${esc(o.source || "")}</td></tr>`).join("");
}
function historyTable(obs, withCountry) {
  return `<table class="data"><tr>${withCountry ? "<th>Country</th>" : "<th>Company</th>"}<th>Metric</th><th>Seg</th><th class="num">Value</th><th>As of</th><th>Conf.</th><th>Source</th><th>Note</th></tr>` +
    obs.map(o => `<tr><td>${esc(withCountry ? (o.country || "Total") : (o.company || "—"))}</td>
      <td>${esc(o.metric)}</td><td>${o.segment === "all" ? "" : esc(o.segment)}</td>
      <td class="num">${o.value !== null ? fmt(o.value) : esc(o.value_text || "")}</td>
      <td>${o.as_of === "unknown" ? `<span class="pill unknown">unknown</span>` : esc(o.as_of)}</td>
      <td>${esc(o.confidence)}${o.is_override ? ` <span class="pill override">override</span>` : ""}</td>
      <td class="small muted">${esc(o.source || "")}</td><td class="small muted">${esc(o.note || "")}</td></tr>`).join("") +
    "</table>";
}

/* ------------------------------------------------ data entry */
async function loadOverrides() {
  // datalists
  if (!state.countries) state.countries = (await api("/api/countries")).countries;
  $("#dl-countries").innerHTML = state.countries.map(c => `<option value="${esc(c.name)}">`).join("");
  const league = state.league || (await api("/api/league")).league;
  state.league = league;
  $("#dl-companies").innerHTML = league.slice(0, 400).map(l => `<option value="${esc(l.company)}">`).join("");
  const d = await apiRaw("/api/observations?overrides=1");
  const el = $("#override-table");
  if (!d.observations.length) { el.innerHTML = "<tr><td class='muted'>No manual entries yet.</td></tr>"; return; }
  el.innerHTML = `<tr><th>When</th><th>Company</th><th>Country</th><th>Metric</th><th>Seg</th><th class="num">Value</th><th>As of</th><th>Conf.</th><th>Source</th><th></th></tr>` +
    d.observations.map(o => `<tr>
      <td class="small muted">${esc((o.created_at || "").slice(0, 16))}</td>
      <td>${esc(o.company || "—")}</td><td>${esc(o.country || "—")}</td>
      <td>${esc(o.metric)}</td><td>${o.segment === "all" ? "" : esc(o.segment)}</td>
      <td class="num">${o.value !== null ? fmt(o.value) : esc(o.value_text || "")}</td>
      <td>${esc(o.as_of)}</td><td>${esc(o.confidence)}</td>
      <td class="small muted">${esc(o.source || "")}</td>
      <td><button class="btn danger small" data-del="${o.id}">remove</button></td></tr>`).join("");
  el.onclick = async e => {
    const b = e.target.closest("[data-del]"); if (!b) return;
    await apiRaw(`/api/observations/${b.dataset.del}/delete`, { method: "POST" });
    loadOverrides();
  };
}
$("#entry-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#entry-msg");
  const body = {
    metric: $("#e-metric").value, country: $("#e-country").value.trim() || null,
    company: $("#e-company").value.trim() || null,
    company_type: $("#e-ctype").value || null,
    segment: $("#e-segment").value, value: $("#e-value").value.trim() || null,
    as_of_year: $("#e-year").value, as_of_quarter: $("#e-quarter").value,
    confidence: $("#e-confidence").value, source: $("#e-source").value.trim() || null,
    note: $("#e-note").value.trim() || null,
  };
  const r = await apiRaw("/api/observations", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.error) { msg.className = "err"; msg.textContent = "✗ " + r.error; return; }
  msg.className = "ok"; msg.textContent = "✓ saved";
  $("#e-value").value = ""; $("#e-note").value = "";
  state.league = state.mnos = state.countries = null; state.mapData = {};
  loadOverrides();
});

/* ------------------------------------------------ entity entry forms */
function verificationSelect() {
  return `<select class="ef-verification">` +
    Object.entries(DATA_QUALITY_LEVELS).map(([k, v]) =>
      `<option value="${k}"${k === "public_unverified" ? " selected" : ""}>${esc(v)}</option>`).join("") +
    `</select>`;
}
function asOfSelects() {
  let years = `<option value="">unknown</option>`;
  for (let y = 2026; y >= 2012; y--) years += `<option>${y}</option>`;
  return `<label>As-of year<select class="ef-year">${years}</select></label>
    <label>As-of quarter<select class="ef-quarter"><option value="">—</option>
      <option>1</option><option>2</option><option>3</option><option>4</option></select></label>`;
}
function entityPicker(cls, options, selectedId) {
  return `<select class="${cls}">` + options.map(o =>
    `<option value="${o.id}"${o.id === selectedId ? " selected" : ""}>${esc(o.name)}</option>`
  ).join("") + `</select>`;
}
function rowsEditor(id, addLabel, rowHTML) {
  return `<div class="entry-rows" id="${id}">${rowHTML}</div>
    <button type="button" class="btn secondary small" onclick="addRow('${id}')">${addLabel}</button>`;
}
window.addRow = function (id) {
  const box = $("#" + id);
  const row = box.firstElementChild.cloneNode(true);
  row.querySelectorAll("input").forEach(i => i.value = "");
  box.appendChild(row);
};
document.addEventListener("click", e => {
  if (e.target.classList.contains("rm")) {
    const row = e.target.closest(".entry-row");
    if (row && row.parentElement.children.length > 1) row.remove();
  }
});
function closeEntityForm() { $("#entity-modal").hidden = true; }
window.closeEntityForm = closeEntityForm;

async function ensureLists() {
  if (!state.countries) state.countries = (await api("/api/countries")).countries;
  if (!state.league) state.league = (await api("/api/league")).league;
  if (!state.mnos) state.mnos = (await api("/api/mnos")).mnos;
}

function countryDatalist() {
  return `<datalist id="ef-dl-countries">` +
    state.countries.map(c => `<option value="${esc(c.name)}">`).join("") + `</datalist>`;
}

function formShell(title, entityRow, sectionsHTML, submitLabel) {
  return `<h2>${title}</h2>
    ${entityRow}
    ${sectionsHTML}
    <div class="modal-grid">
      ${asOfSelects()}
      <label>Data quality${verificationSelect()}</label>
      <label>Note<input type="text" class="ef-note"></label>
    </div>
    <button class="btn" id="ef-submit">${submitLabel}</button>
    <button class="btn secondary" type="button" onclick="closeEntityForm()">Cancel</button>
    <span id="ef-msg" style="margin-left:10px"></span>
    ${countryDatalist()}`;
}

function readCommon(body) {
  const box = $("#entity-form-body");
  return Object.assign(body, {
    as_of_year: box.querySelector(".ef-year").value || null,
    as_of_quarter: box.querySelector(".ef-quarter").value || null,
    verification_level: box.querySelector(".ef-verification").value,
    note: box.querySelector(".ef-note").value.trim() || null,
  });
}

async function postEntity(path, body, refresh) {
  const msg = $("#ef-msg");
  msg.textContent = "saving…";
  const r = await apiRaw(path, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.error) { msg.textContent = "✗ " + r.error; msg.style.color = css("--serious"); return; }
  msg.textContent = "✓ saved"; msg.style.color = css("--good");
  state.league = state.mnos = state.countries = null; state.mapData = {};
  setTimeout(() => { closeEntityForm(); refresh && refresh(); }, 600);
}

async function openCountryForm(id, name) {
  await ensureLists();
  const modal = $("#entity-modal"), box = $("#entity-form-body");
  const picker = `<label class="small muted">Country ${entityPicker("ef-entity",
    state.countries.filter(c => c.region || c.owners_count).map(c => ({ id: c.id, name: c.name })), id)}</label>`;
  const row = `<div class="entry-row">
      <input type="text" class="ef-company" placeholder="Company" list="dl-companies">
      <select class="ef-type"><option value="towerco">towerco</option><option value="mno">MNO</option>
        <option value="jv-infraco">JV infraco</option><option value="broadcaster">broadcaster</option>
        <option value="unknown">unknown</option></select>
      <input type="text" class="ef-towers" placeholder="Towers">
      <button type="button" class="rm">×</button></div>`;
  box.innerHTML = formShell(`Country data${name ? " — " + esc(name) : ""}`, picker,
    `<h3 class="small muted" style="margin:14px 0 4px">Who owns how many sites</h3>` +
    rowsEditor("ef-ownership", "+ add owner", row), "Save country data");
  modal.hidden = false;
  $("#ef-submit").onclick = () => {
    const cid = box.querySelector(".ef-entity").value;
    const ownership = [...box.querySelectorAll("#ef-ownership .entry-row")].map(r => ({
      company: r.querySelector(".ef-company").value.trim(),
      type: r.querySelector(".ef-type").value,
      towers: r.querySelector(".ef-towers").value.trim(),
    })).filter(o => o.company);
    if (!ownership.length) { $("#ef-msg").textContent = "add at least one owner"; return; }
    postEntity(`/api/country/${cid}/observations`, readCommon({ ownership }),
      () => { loadTab(activeTab(), true); });
  };
}
window.openCountryForm = openCountryForm;

async function openMnoForm(id, name) {
  await ensureLists();
  const modal = $("#entity-modal"), box = $("#entity-form-body");
  const picker = `<label class="small muted">MNO ${entityPicker("ef-entity",
    state.mnos.map(m => ({ id: m.company_id, name: m.company })), id)}</label>`;
  const marketRow = `<div class="entry-row">
      <input type="text" class="ef-country" placeholder="Country" list="ef-dl-countries">
      <input type="text" class="ef-towers" placeholder="Towers owned (optional)">
      <button type="button" class="rm">×</button></div>`;
  const towercoRow = `<div class="entry-row">
      <input type="text" class="ef-towerco" placeholder="Towerco" list="dl-companies">
      <button type="button" class="rm">×</button></div>`;
  box.innerHTML = formShell(`MNO data${name ? " — " + esc(name) : ""}`, picker,
    `<h3 class="small muted" style="margin:14px 0 4px">Footprint — markets active in (towers owned optional)</h3>` +
    rowsEditor("ef-markets", "+ add market", marketRow) +
    `<h3 class="small muted" style="margin:14px 0 4px">Towercos it leases from</h3>` +
    rowsEditor("ef-towercos", "+ add towerco", towercoRow), "Save MNO data");
  modal.hidden = false;
  $("#ef-submit").onclick = () => {
    const mid = box.querySelector(".ef-entity").value;
    const markets = [...box.querySelectorAll("#ef-markets .entry-row")].map(r => ({
      country: r.querySelector(".ef-country").value.trim(),
      towers_owned: r.querySelector(".ef-towers").value.trim(),
    })).filter(m => m.country);
    const towercos = [...box.querySelectorAll("#ef-towercos .entry-row")]
      .map(r => r.querySelector(".ef-towerco").value.trim()).filter(Boolean);
    if (!markets.length && !towercos.length) { $("#ef-msg").textContent = "add at least one market or towerco"; return; }
    postEntity(`/api/mno/${mid}/observations`, readCommon({ markets, towercos }),
      () => { loadTab(activeTab(), true); });
  };
}
window.openMnoForm = openMnoForm;

async function openTowercoForm(id, name) {
  await ensureLists();
  const modal = $("#entity-modal"), box = $("#entity-form-body");
  const picker = `<label class="small muted">Towerco ${entityPicker("ef-entity",
    state.league.map(l => ({ id: l.company_id, name: l.company })), id)}</label>`;
  const marketRow = `<div class="entry-row">
      <input type="text" class="ef-country" placeholder="Country" list="ef-dl-countries">
      <input type="text" class="ef-towers" placeholder="Towers">
      <button type="button" class="rm">×</button></div>`;
  const tenantRow = `<div class="entry-row">
      <input type="text" class="ef-tenant" placeholder="Tenant (MNO)">
      <button type="button" class="rm">×</button></div>`;
  box.innerHTML = formShell(`Towerco data${name ? " — " + esc(name) : ""}`, picker,
    `<h3 class="small muted" style="margin:14px 0 4px">Markets — towers per country</h3>` +
    rowsEditor("ef-markets", "+ add market", marketRow) +
    `<h3 class="small muted" style="margin:14px 0 4px">Known tenants</h3>` +
    rowsEditor("ef-tenants", "+ add tenant", tenantRow), "Save towerco data");
  modal.hidden = false;
  $("#ef-submit").onclick = () => {
    const tid = box.querySelector(".ef-entity").value;
    const markets = [...box.querySelectorAll("#ef-markets .entry-row")].map(r => ({
      country: r.querySelector(".ef-country").value.trim(),
      towers: r.querySelector(".ef-towers").value.trim(),
    })).filter(m => m.country);
    const tenants = [...box.querySelectorAll("#ef-tenants .entry-row")]
      .map(r => r.querySelector(".ef-tenant").value.trim()).filter(Boolean);
    if (!markets.length && !tenants.length) { $("#ef-msg").textContent = "add at least one market or tenant"; return; }
    postEntity(`/api/towerco/${tid}/observations`, readCommon({ markets, tenants }),
      () => { loadTab(activeTab(), true); });
  };
}
window.openTowercoForm = openTowercoForm;

/* ------------------------------------------------ hash routing (deep links) */
function applyHash() {
  let m = location.hash.match(/^#company\/(\d+)/);
  if (m) { openCompany(+m[1], true); return; }
  m = location.hash.match(/^#country\/(\d+)/);
  if (m) { openCountry(+m[1], true); return; }
  closeDrawer();
}
window.addEventListener("hashchange", applyHash);

/* ------------------------------------------------ about */
function renderAbout() {
  const m = state.meta;
  $("#about-content").innerHTML = `
    <h2>About this data</h2>
    <p>This explorer consolidates mobile-infrastructure asset tracking from two sources:</p>
    <ul>
      <li><b>League Table.xlsx</b> — ${fmt(m.counts.companies)} companies’ global tower counts,
        ownership, business model and geographic footprint. Each row carries its own
        “last updated” quarter tag (e.g. Q3 2024); where missing it is shown as
        <span class="pill unknown">unknown</span>.</li>
      <li><b>TowerXchange regional guides</b> (MENA ${m ? esc(aboutPub("MENA")) : ""},
        LATAM ${esc(aboutPub("LATAM"))}, Europe ${esc(aboutPub("Europe"))},
        Asia ${esc(aboutPub("Asia"))}, Africa ${esc(aboutPub("Africa"))}) — country-by-country
        estimated tower counts by owner, extracted from the per-country pie charts by matching
        legend swatch colours to slices and value labels to slice angles, then cross-checked
        against each slice’s angular fraction and the stated country total.</li>
    </ul>
    <h3>Extraction quality &amp; caveats</h3>
    <ul>
      <li>Charts with numbered legends (Austria, Germany, Russia, Turkey), two-ring charts
        (Denmark), duplicated legend colours (Norway) and sub-degree sliver fans (Colombia,
        Mexico) were resolved manually from wedge-edge geometry and narrative anchors; these
        corrections live in <code>data/overrides_curated.json</code> with reasons.</li>
      <li>Several source pies are <i>not drawn to scale</i> (e.g. Costa Rica, Côte d’Ivoire,
        Senegal, Cameroon, Romania); printed values were kept because they sum to the stated
        country totals. Such rows carry a note.</li>
      <li>Values inferred as residuals (slice with no printed number) or approximate
        (“+1,000”) are tagged <span class="pill inferred">inferred</span> /
        <span class="pill approx">approx</span>.</li>
      <li><b>Gaps are expected:</b> tower counts are incomplete and there is no guarantee any
        count is exhaustive. Some markets have stats but no ownership pie (e.g. Bahrain,
        Lebanon, UAE, Malawi, Namibia, Niger, Rwanda); several countries are absent entirely.
        MNO market-share pies (Mongolia, South Korea) record share %, not towers.</li>
      <li>The league table and the guides are different vintages, so a company’s global count
        can differ from the sum of its per-country counts — the league view shows both.</li>
    </ul>
    <h3>Time, data quality &amp; overrides</h3>
    <p>Every fact is an <i>observation</i> tagged with year+quarter (or unknown), source,
    confidence and a <b>data quality level</b> (${Object.values(DATA_QUALITY_LEVELS).join("; ")}).
    Extracted data starts at “Public data, not GSMA verified”. The “View as of” selector replays
    the dataset at earlier periods; new data entered on the Data entry page (single points or
    per-country / per-MNO / per-towerco bulk forms) is stored alongside, never replacing, the
    extracted history. Country totals are the sum of tracked owners — the separate
    guide-stated totals and SIM statistics were retired in v2.</p>
    <p class="muted small">Database: <code>data/gsma.db</code> (SQLite) —
      ${fmt(m.counts.observations)} observations, ${fmt(m.counts.countries)} countries,
      ${fmt(m.counts.overrides)} manual overrides. Rebuild with
      <code>python3 data/build_dataset.py && python3 data/build_db.py</code>.</p>`;
}
function aboutPub(r) {
  return { MENA: "Q1 2025", LATAM: "Q2 2025", Europe: "Q2 2025", Asia: "Q4 2024", Africa: "Q2 2025" }[r];
}

init();
