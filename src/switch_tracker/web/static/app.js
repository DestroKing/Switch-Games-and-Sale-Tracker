"use strict";

/* =============================================================================
   Dashboard behaviour.

   Organised in five sections, in the order the page uses them:

     1. utilities      — formatting and escaping
     2. run control    — starting workers, following their progress
     3. summary        — stats, collector status, price movers
     4. listings       — the table, its filters, and its sorting
     5. boot           — what happens on load

   No framework, and deliberately so: the whole surface is one page, the server
   already renders the shell, and every byte here ships inside a PyInstaller
   bundle. A framework would buy nothing and cost the build step this project
   does not have.
   ========================================================================== */

/* ------------------------------------------------------------- 1. utilities */

const $ = (id) => document.getElementById(id);

const inr = (n) => (n === null || n === undefined ? "—" : "₹" + Math.round(n).toLocaleString("en-IN"));
const num = (n) => Number(n ?? 0).toLocaleString("en-IN");

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** Every fetch goes through here so a backend fault is VISIBLE.
 *  server.ts returned {error} with HTTP 200 and the page dereferenced it,
 *  turning any failure into a JavaScript type error rendered as content. */
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.error || `${response.status} ${response.statusText}`);
  }
  return body;
}

/** Loading placeholders that match the shape of what replaces them.
 *  A spinner would collapse to nothing and shove the page down when data
 *  lands; a skeleton of the right height keeps layout shift at zero. */
const skeleton = (className, count) =>
  `<div class="skel ${className}"></div>`.repeat(count);

/* ----------------------------------------------------------- 2. run control */

const consoleBox = $("console");
const progressPanel = $("progress");
let streaming = false;

/** Live state for one run, reset each time a run starts.
 *  Held here rather than read back out of the DOM: the log is a transcript,
 *  not a data structure, and parsing text you just printed is how a display
 *  drifts out of sync with the thing it displays. */
const run = { total: 0, done: 0, failed: 0, listings: 0, store: "", page: 0 };

function log(text, cls = "") {
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = text;
  consoleBox.appendChild(line);
  consoleBox.scrollTop = consoleBox.scrollHeight;
}

$("consoleToggle").addEventListener("click", (e) => {
  const hidden = consoleBox.classList.toggle("is-hidden");
  e.currentTarget.textContent = hidden ? "Show log" : "Hide log";
  e.currentTarget.setAttribute("aria-expanded", String(!hidden));
});

/** One place decides what "a run is happening" looks like, everywhere.
 *  Previously the only feedback was log text, so the top of the page looked
 *  identical whether the app was idle or eight minutes into a scrape. */
function setRunState(state, label) {
  const badge = $("runStatus");
  badge.className = `status ${state}`;
  badge.textContent = label;
  $("progressState").className = `status ${state}`;
  $("progressState").textContent = label;
}

function paintProgress() {
  const bar = $("progressBar");
  // Indeterminate until at least one store finishes. A store's page count is
  // not known in advance, so before the first completion there is no honest
  // percentage to show -- and a fake one is worse than none.
  if (run.total > 0 && run.done > 0) {
    bar.classList.remove("is-indeterminate");
    const pct = Math.round((run.done / run.total) * 100);
    bar.firstElementChild.style.width = `${pct}%`;
    bar.setAttribute("aria-valuenow", String(pct));
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
  } else {
    bar.classList.add("is-indeterminate");
    bar.removeAttribute("aria-valuenow");
  }

  $("progressCounts").innerHTML = run.total
    ? `${run.done}/${run.total} stores · ${num(run.listings)} listings` +
      (run.failed ? ` · <span class="bad">${run.failed} failed</span>` : "")
    : "";

  $("progressNow").innerHTML = run.store
    ? `<span class="store">${esc(run.store)}</span>` +
      (run.page ? `<span>page ${run.page}</span>` : "") +
      `<span class="muted">${num(run.listings)} listings collected</span>`
    : `<span class="muted">Starting workers…</span>`;
}

function setButtonsDisabled(disabled) {
  // By CLASS, not by looking each control up by id. The previous form named
  // #fixStore explicitly, so every control added afterwards stayed live during
  // a run and handed the user an unexplained 409. A class covers the next one
  // on arrival.
  document.querySelectorAll("[data-action], .js-run-control").forEach((el) => {
    el.disabled = disabled;
  });
  if (!disabled) syncCollectSelected();
}

/** Keep the subset button honest: an empty selection posted to /actions/collect
 *  means "collect everything", which is not what an unticked list looks like. */
function syncCollectSelected() {
  const button = $("collectSelected");
  if (!button) return;
  const chosen = [...document.querySelectorAll(".js-store:checked")];
  button.disabled = chosen.length === 0;
  button.textContent = chosen.length
    ? `Collect selected (${chosen.length})`
    : "Collect selected";
}

/** Subscribe to a run that is already happening in another process.
 *  Closing this tab does not stop it; reopening replays from the cursor. */
function follow(runId, fromSeq = 0) {
  if (streaming) return;
  streaming = true;
  setButtonsDisabled(true);

  Object.assign(run, { total: 0, done: 0, failed: 0, listings: 0, store: "", page: 0 });
  progressPanel.hidden = false;
  setRunState("running", "Running");
  paintProgress();

  const source = new EventSource(`/api/runs/${runId}/events?request_from=${fromSeq}`);

  source.onmessage = () => {};
  source.addEventListener("run_started", (e) => {
    run.total = JSON.parse(e.data).count;
    paintProgress();
    log(`Run ${runId} started — ${run.total} stores`);
  });
  source.addEventListener("store_started", (e) => {
    const d = JSON.parse(e.data);
    run.store = d.store_id;
    run.page = 0;
    paintProgress();
    log(`  ${d.store_id} (${d.detail || ""}) starting…`);
  });
  source.addEventListener("store_progress", (e) => {
    const d = JSON.parse(e.data);
    run.store = d.store_id;
    run.page = d.page;
    paintProgress();
    log(`    ${d.store_id}: page ${d.page} — ${d.count} listings so far`);
  });
  source.addEventListener("store_finished", (e) => {
    const d = JSON.parse(e.data);
    run.done += 1;
    run.listings += d.count || 0;
    if (d.status === "failed" || d.status === "skipped") run.failed += 1;
    paintProgress();
    log(`  ${d.store_id}: ${d.status} — ${d.count} listings${d.detail ? " — " + d.detail : ""}`,
        d.status);
  });
  source.addEventListener("warning", (e) => log(`  ! ${JSON.parse(e.data).detail}`, "partial"));
  source.addEventListener("run_finished", () => {
    log("Run complete.");
    source.close();
    streaming = false;
    // The panel STAYS on screen showing the outcome. The Peak-End rule cuts
    // both ways: a run that vanishes the moment it ends leaves the user with
    // no answer to "did that work?".
    run.store = "";
    setRunState(run.failed ? "partial" : "ok",
                run.failed ? `Finished — ${run.failed} failed` : "Finished");
    $("progressBar").classList.remove("is-indeterminate");
    $("progressBar").firstElementChild.style.width = "100%";
    $("progressNow").innerHTML =
      `<span class="store">Complete</span><span class="muted">` +
      `${run.done} stores · ${num(run.listings)} listings</span>`;
    setButtonsDisabled(false);
    boot();
  });
  source.onerror = () => {
    // EventSource reconnects on its own; the server replays from the cursor,
    // so nothing is lost. Only give up if the run already ended.
    if (source.readyState === EventSource.CLOSED) {
      streaming = false;
      setRunState("idle", "Idle");
      setButtonsDisabled(false);
    }
  };
}

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.action;
    if (button.dataset.confirm && !confirm(button.dataset.confirm)) return;
    // Disable immediately. This is cosmetic only -- the real guard is a
    // unique index in the database, which also catches a refresh or a
    // second tab.
    setButtonsDisabled(true);
    try {
      const result = await api(`/actions/${action}`, { method: "POST" });
      if (result.run_id) {
        consoleBox.innerHTML = "";
        follow(result.run_id);
      } else {
        progressPanel.hidden = false;
        setRunState("ok", "Done");
        $("progressNow").innerHTML = `<span class="store">${esc(action)} finished</span>`;
        log("Done.");
        setButtonsDisabled(false);
        boot();
      }
    } catch (err) {
      progressPanel.hidden = false;
      setRunState("failed", "Failed");
      $("progressNow").innerHTML = `<span class="store">${esc(err.message)}</span>`;
      log(String(err.message), "failed");
      setButtonsDisabled(false);
    }
  });
});

document.querySelectorAll(".js-store").forEach((box) => {
  box.addEventListener("change", syncCollectSelected);
});

const collectSelected = $("collectSelected");
if (collectSelected) {
  collectSelected.addEventListener("click", async () => {
    const ids = [...document.querySelectorAll(".js-store:checked")].map((b) => b.value);
    if (!ids.length) return;
    try {
      const result = await api(
        `/actions/collect?only=${encodeURIComponent(ids.join(","))}`,
        { method: "POST" },
      );
      consoleBox.innerHTML = "";
      log(`Collecting ${ids.length} store(s): ${ids.join(", ")}`);
      if (result && result.run_id) follow(result.run_id);
    } catch (err) {
      log(String(err.message), "failed");
    }
  });
}

const fixPicker = $("fixStore");
if (fixPicker) {
  fixPicker.addEventListener("change", async () => {
    const storeId = fixPicker.value;
    if (!storeId) return;
    fixPicker.value = "";
    try {
      await api(`/actions/inspect/${storeId}`, { method: "POST" });
      progressPanel.hidden = false;
      consoleBox.classList.remove("is-hidden");
      $("consoleToggle").textContent = "Hide log";
      $("consoleToggle").setAttribute("aria-expanded", "true");
      log(`Opening ${storeId} in a real browser window. Alt+click the card, then its ` +
          `title, price and link.`);
    } catch (err) {
      log(String(err.message), "failed");
    }
  });
}

/* --------------------------------------------------------------- 3. summary */

/** listing id -> its most recent price movement.
 *  /api/movers already carries l.id, and so does /api/listings, so the two are
 *  joined HERE rather than by widening a backend query. That keeps the API
 *  contract untouched while still letting the table show which rows just
 *  moved -- the single most useful thing a price tracker can say. */
let movementById = new Map();

/** What /api/movers returns at most. Mirrored here only so the UI can say
 *  "60+" instead of "60" when it is clearly truncated. */
const MOVERS_CAP = 60;
/** How many movers to show before the fold. The full set is 60 rows, which
 *  measured 3,176px of a 9,409px page -- a third of the document for a
 *  secondary section, pushing the main listings table far out of sight. */
const MOVERS_PREVIEW = 6;
let moversExpanded = false;
let moversData = [];

/** One figure in the summary strip.
 *  The qualifier goes inside the LABEL, not the value: the strip renders the
 *  number before the label, so a qualifier attached to the value reads as
 *  "60+ since last run PRICE DROPS". */
function statTile(label, value, unit = "") {
  return `<div class="stat"><dd>${esc(value)}</dd>` +
         `<dt>${esc(label)}${unit ? ` <span class="unit">${esc(unit)}</span>` : ""}</dt></div>`;
}

async function boot() {
  $("stats").innerHTML = skeleton("skel-tile", 4);
  $("strip").innerHTML = skeleton("skel-tile", 6);

  let sum, hp, mv;
  try {
    [sum, hp, mv] = await Promise.all([api("/api/summary"), api("/api/health"), api("/api/movers")]);
  } catch (err) {
    $("stats").innerHTML = "";
    $("strip").innerHTML =
      `<div class="notice error" role="alert"><div><b>Could not read the database.</b> ` +
      `${esc(err.message)}</div></div>`;
    return;
  }

  movementById = new Map(mv.map((m) => [m.id, m]));

  // "Stores" here counts stores that actually HAVE listings, which is not the
  // same as the number that ran -- a store can run and collect nothing. The
  // collector strip below reports the second number, so this one is labelled
  // to say which it is rather than letting two different numbers
  // sit side by side unexplained.
  const drops = mv.filter((m) => m.pct < 0 && !m.fx_suspect).length;
  // /api/movers caps at 60 rows, so this is a floor, not a total. Labelled
  // "60+" at the cap rather than stating a number that may be short.
  const dropLabel = mv.length >= MOVERS_CAP ? `${num(drops)}+` : num(drops);
  $("stats").innerHTML =
    statTile("Listings", num(sum.listings)) +
    statTile("Stores with data", num(sum.stores)) +
    statTile("Price points", num(sum.points)) +
    statTile("Price drops", dropLabel, "since last run");

  if (!hp.run) {
    $("stamp").textContent = "never collected";
    setRunState("idle", "No data yet");
  } else {
    $("stamp").textContent = "last run " +
      new Date(hp.run.started_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    if (!streaming) setRunState("idle", "Idle");
  }

  const bad = hp.stores.filter((s) => s.status === "failed" || s.status === "skipped").length;
  $("collectorSub").textContent = hp.stores.length
    ? `${hp.stores.length} stores in the last run` + (bad ? ` · ${bad} need attention` : " · all healthy")
    : "";

  // Failing stores FIRST. A dashboard sorted by database order buries the one
  // tile the user needs to act on somewhere in the middle of twenty-four.
  const rank = { failed: 0, skipped: 1, partial: 2, ok: 3 };
  const ordered = [...hp.stores].sort(
    (a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || b.listings_found - a.listings_found);

  // A healthy store is one line: glyph, name, count. Anything else earns a
  // second line carrying the status word and the reason -- which is the only
  // text on this panel anybody actually needs to read.
  $("strip").innerHTML = ordered.map((s) => {
    const healthy = s.status === "ok";
    const why = healthy ? "" :
      `<span class="why" title="${esc(s.detail || s.status)}">${esc(s.status)}` +
      `${s.detail ? " · " + esc(s.detail) : ""}</span>`;
    return `<div class="tile ${esc(s.status)}">
      <span class="status ${esc(s.status)}"><span class="visually-hidden">${esc(s.status)}</span></span>
      <span class="who" title="${esc(s.name)}">${esc(s.name)}</span>
      <span class="n">${num(s.listings_found)}</span>
      ${why}
    </div>`;
  }).join("") ||
    '<div class="empty"><b>Nothing collected yet</b>Press “Collect prices” to fill this in.</div>';

  const fxCount = mv.filter((m) => m.fx_suspect).length;
  $("fxnote").innerHTML = fxCount
    ? `<div class="notice warn"><div><b>${fxCount} of these moved together.</b> Same currency,
       same ratio, same day — that is the rupee moving against the dollar, not the shops changing
       their minds. Flagged rather than counted as price changes.</div></div>`
    : "";

  moversData = mv;
  paintMovers();

  await loadFacets();
  await search();
}

/** The movers table, capped to a preview with an explicit way to see the rest.
 *  Progressive disclosure rather than truncation: the count is always visible,
 *  so nothing is hidden without saying so. */
function paintMovers() {
  const mv = moversData;
  const shown = moversExpanded ? mv : mv.slice(0, MOVERS_PREVIEW);
  $("moversSub").textContent = mv.length
    ? `${mv.length}${mv.length >= MOVERS_CAP ? "+" : ""} changed`
    : "";
  $("movers").innerHTML = mv.length ? `
    <div class="tablewrap"><table>
      <caption class="visually-hidden">Listings whose price changed since the previous run</caption>
      <thead><tr>
        <th class="plain" scope="col">Title</th><th class="plain" scope="col">Store</th>
        <th class="plain num" scope="col">Was</th><th class="plain num" scope="col">Now</th>
        <th class="plain num" scope="col">Change</th>
      </tr></thead><tbody>
      ${shown.map((m) => `<tr class="${m.pct < 0 && !m.fx_suspect ? "is-deal" : ""}">
        <td class="title-cell"><div class="clamp">
          <a class="name" href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.raw_title)}</a><span class="meta">${
            m.region !== "IN" ? `<span class="tag">${esc(m.region)}</span>` : ""}${
            m.fx_suspect ? `<span class="tag fx">FX suspect</span>` : ""}${
            !m.in_stock ? `<span class="tag oos">out of stock</span>` : ""}</span></div></td>
        <td>${esc(m.store)}</td>
        <td class="num dim">${inr(m.prev_price)}</td>
        <td class="num price">${inr(m.now_price)}</td>
        <td class="num"><span class="delta ${m.pct < 0 ? "down" : "up"}">${Math.abs(m.pct).toFixed(1)}%</span></td>
      </tr>`).join("")}</tbody></table>
      ${mv.length > MOVERS_PREVIEW
        ? `<button class="showall" id="moversToggle" type="button" aria-expanded="${moversExpanded}">` +
          (moversExpanded ? "Show fewer" : `Show all ${mv.length} changes`) + `</button>`
        : ""}</div>`
    : `<div class="empty"><b>Nothing to compare yet</b>Price changes appear after a second run.</div>`;

  const toggle = $("moversToggle");
  if (toggle) toggle.addEventListener("click", () => {
    moversExpanded = !moversExpanded;
    paintMovers();
    // Keep the control under the pointer after a collapse, or the page jumps
    // and the user loses their place.
    if (!moversExpanded) $("moversHead").scrollIntoView({ block: "nearest" });
  });
}

/* -------------------------------------------------------------- 4. listings */

// store and region are SETS. platform and condition stay single-valued -- their
// controls are three-way segments whose first option already means "all".
const BLANK = { q: "", platform: "", condition: "", region: [], store: [],
                inStock: false, sort: "price", dir: "asc", offset: 0 };
const state = { ...BLANK, region: [], store: [] };
let rows = [];
let facets = { stores: [], regions: [] };

const COLS = [
  { key: "title", label: "Title", sortable: true },
  { key: "store", label: "Store", sortable: true },
  { key: null, label: "Native", num: true },
  { key: "price", label: "INR", sortable: true, num: true },
  {
    key: "change",
    label: "Change",
    sortable: true,
    num: true,
    hint: "Movement since the previous run, where known",
  },
];

function queryString() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  for (const k of ["platform", "condition"]) if (state[k]) p.set(k, state[k]);
  // Comma-separated, matching /actions/collect?only=a,b -- one encoding for
  // "a set of ids" across the whole app. A single value produces ?store=x,
  // so old bookmarks keep working.
  for (const k of ["store", "region"]) if (state[k].length) p.set(k, state[k].join(","));
  if (state.inStock) p.set("in_stock", "true");
  p.set("sort", state.sort);
  p.set("dir", state.dir);
  p.set("limit", "100");
  p.set("offset", String(state.offset));
  return p.toString();
}

/** Build one checkbox per value that actually exists in the data. */
function fillBoxes(containerId, key, items) {
  const box = $(containerId);
  box.innerHTML = "";
  for (const item of items) {
    const label = document.createElement("label");
    label.className = "check";
    label.innerHTML =
      `<input type="checkbox" data-filter="${key}" value="${esc(item.value)}">` +
      `<span>${esc(item.label)} <span class="muted">(${item.n})</span></span>`;
    box.appendChild(label);
  }
}

function syncChosen(key) {
  const badge = document.querySelector(`.chosen[data-for="${key}"]`);
  if (badge) badge.textContent = state[key].length ? `(${state[key].length})` : "";
}

/** The active-filter chip row. Every chip removes exactly one condition, so
 *  narrowing a search is never a one-way door the user has to hunt to undo. */
function paintChips() {
  const labelFor = (key, value) => {
    const list = key === "store" ? facets.stores : facets.regions;
    const hit = list.find((x) => (key === "store" ? x.id : x.region) === value);
    return hit ? (key === "store" ? hit.name : hit.region) : value;
  };
  const chips = [];
  const push = (kind, label, value) =>
    chips.push(`<span class="chip"><span>${esc(kind)}</span> <b>${esc(label)}</b>` +
      `<button type="button" data-chip="${esc(kind)}" data-value="${esc(value ?? "")}"` +
      ` aria-label="Remove filter ${esc(kind)} ${esc(label)}">×</button></span>`);

  if (state.q) push("search", state.q);
  if (state.platform) push("console", state.platform === "SWITCH2" ? "Switch 2" : "Switch");
  if (state.condition) push("condition", state.condition === "NEW" ? "New" : "Pre-owned");
  if (state.inStock) push("stock", "In stock only");
  for (const v of state.store) push("store", labelFor("store", v), v);
  for (const v of state.region) push("region", labelFor("region", v), v);

  $("chips").innerHTML = chips.length
    ? chips.join("") + `<button type="button" class="linkish" id="clearAll">Clear all</button>`
    : "";
}

async function loadFacets() {
  facets = await api("/api/facets");
  fillBoxes("storeBoxes", "store",
            facets.stores.map((s) => ({ value: s.id, label: s.name, n: s.n })));
  fillBoxes("regionBoxes", "region",
            facets.regions.map((r) => ({ value: r.region, label: r.region, n: r.n })));

  // Delegated: the boxes are rebuilt whenever facets reload, so a listener
  // bound to each one would be lost. The container outlives them.
  for (const [containerId, key] of [["storeBoxes", "store"], ["regionBoxes", "region"]]) {
    $(containerId).addEventListener("change", () => {
      state[key] = [...$(containerId).querySelectorAll("input:checked")].map((b) => b.value);
      syncChosen(key);
      rerun();
    });
  }
  syncChosen("store");
  syncChosen("region");
}

function clearFilter(key) {
  const containerId = key === "store" ? "storeBoxes" : "regionBoxes";
  $(containerId).querySelectorAll("input:checked").forEach((b) => { b.checked = false; });
  state[key] = [];
  syncChosen(key);
}

function headerCell(col) {
  const cls = col.num ? " num" : "";
  if (!col.sortable) {
    const hint = col.hint ? ` title="${esc(col.hint)}"` : "";
    return `<th class="plain${cls}" scope="col"${hint}>${esc(col.label)}</th>`;
  }
  const active = state.sort === col.key;
  const dir = state.dir === "asc" ? "ascending" : "descending";
  // A real <button>, so the control is in the tab order and announced as a
  // control. aria-sort lives on the <th>, which is where assistive technology
  // looks for it.
  return `<th class="${cls.trim()}" scope="col"${active ? ` aria-sort="${dir}"` : ""}>
    <button class="sort" type="button" data-sort="${col.key}">
      <span>${esc(col.label)}</span>
      <span class="arrow" aria-hidden="true">${active ? (state.dir === "asc" ? "▲" : "▼") : ""}</span>
    </button></th>`;
}

function deltaCell(row) {
  const moved = movementById.get(row.id);

  // queries.py now returns change_pct for every listing that has
  // a previous observation. Fall back to /api/movers for compatibility.
  const pct = row.change_pct ?? moved?.pct;

  if (pct === null || pct === undefined) {
    return `<td class="num dim">—</td>`;
  }

  const down = pct < 0;

  // /api/movers contains the previous absolute price, so retain the
  // existing tooltip whenever that information is available.
  const title = moved
    ? ` title="was ${inr(moved.prev_price)}"`
    : "";

  return `<td class="num"><span class="delta ${down ? "down" : "up"}"${title}>` +
         `${Math.abs(pct).toFixed(1)}%</span></td>`;
}

async function search(append = false) {
  if (!append) $("list").innerHTML = `<div class="tablewrap">${skeleton("skel-row", 12)}</div>`;

  let data;
  try {
    data = await api("/api/listings?" + queryString());
  } catch (err) {
    $("list").innerHTML =
      `<div class="notice error" role="alert"><div><b>Could not load listings.</b> ` +
      `${esc(err.message)}</div></div>`;
    return;
  }
  rows = append ? rows.concat(data.rows) : data.rows;

  $("count").innerHTML =
    `<b>${num(rows.length)}</b> of <b>${num(data.total)}</b> — sorted in the database, not on this page`;
  paintChips();

  const head = COLS.map(headerCell).join("");

  const body = rows.map((r) => {
    const moved = movementById.get(r.id);
    const isDeal = moved && moved.pct < 0 && !moved.fx_suspect;
    return `<tr class="${isDeal ? "is-deal" : ""}">
      <td class="title-cell"><div class="clamp">
        <a class="name" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.raw_title)}</a><span class="meta">${
          r.platform === "SWITCH2" ? '<span class="tag sw2">Switch 2</span>' : ""}${
          r.region !== "IN" ? `<span class="tag">${esc(r.region)}</span>` : ""}${
          r.condition === "PRE_OWNED" ? '<span class="tag used">pre-owned</span>' : ""}${
          !r.in_stock ? '<span class="tag oos">out of stock</span>' : ""}</span></div></td>
      <td>${esc(r.store)}</td>
      <td class="num dim">${r.native_currency !== "INR"
        ? esc(r.native_currency) + " " + num(r.native_price) : ""}</td>
      <td class="num price">${inr(r.inr_price)}</td>
      ${deltaCell(r)}
    </tr>`;
  }).join("");

  const more = rows.length < data.total
    ? `<button class="more" id="more">Load ${Math.min(100, data.total - rows.length)} more</button>`
    : "";

  $("list").innerHTML = rows.length
    ? `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`
    : `<div class="empty"><b>Nothing matches those filters</b>
       Try clearing one — the chips above show what is currently narrowing the list.</div>`;

  $("list").querySelectorAll("button.sort").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      // Re-query the SERVER. Re-sorting the rows already on screen would sort
      // a subset and present it as the whole answer.
      state.dir = state.sort === key && state.dir === "asc" ? "desc" : "asc";
      state.sort = key;
      state.offset = 0;
      search();
    });
  });
  const moreButton = $("more");
  if (moreButton) moreButton.addEventListener("click", () => {
    state.offset += 100;
    search(true);
  });
}

function rerun() { state.offset = 0; search(); }

function resetAll() {
  Object.assign(state, BLANK, { region: [], store: [] });
  $("q").value = "";
  $("stock").checked = false;
  clearFilter("store");
  clearFilter("region");
  for (const g of ["platform", "condition"]) {
    $(g).querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(i === 0)));
  }
  search();
}

/* Removing one chip un-sets exactly the condition it names. */
$("chips").addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  if (button.id === "clearAll") return resetAll();

  const { chip, value } = button.dataset;
  if (chip === "search") { state.q = ""; $("q").value = ""; }
  if (chip === "stock") { state.inStock = false; $("stock").checked = false; }
  for (const [kind, group] of [["console", "platform"], ["condition", "condition"]]) {
    if (chip === kind) {
      state[group] = "";
      $(group).querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(i === 0)));
    }
  }
  for (const key of ["store", "region"]) {
    if (chip !== key) continue;
    state[key] = state[key].filter((v) => v !== value);
    const containerId = key === "store" ? "storeBoxes" : "regionBoxes";
    $(containerId).querySelectorAll("input").forEach((b) => {
      if (b.value === value) b.checked = false;
    });
    syncChosen(key);
  }
  rerun();
});

let debounce;
$("q").addEventListener("input", (e) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => { state.q = e.target.value.trim(); rerun(); }, 250);
});
for (const group of ["platform", "condition"]) {
  $(group).addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    $(group).querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === button)));
    state[group] = button.dataset.v;
    rerun();
  });
}
document.querySelectorAll("[data-clear]").forEach((button) => {
  button.addEventListener("click", () => { clearFilter(button.dataset.clear); rerun(); });
});
$("stock").addEventListener("change", (e) => { state.inStock = e.target.checked; rerun(); });
$("reset").addEventListener("click", resetAll);

/* A filter popover should close when focus leaves it, the way every other
   menu on the platform does (Jakob's Law). <details> gives us everything
   except this one behaviour. */
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.filter-group[open]").forEach((d) => {
    if (!d.contains(e.target)) d.open = false;
  });
});
/* "/" jumps to search, the convention every search-bearing app on the web
   shares (Jakob's Law). Ignored while typing, or the key could never be typed
   INTO a field. */
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "SELECT" || el.isContentEditable)) return;
  e.preventDefault();
  $("q").focus();
  $("q").select();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  // Escape in the search box clears it, which is what a search field does
  // everywhere else -- and it is the fastest way out of a filtered view.
  if (document.activeElement === $("q") && $("q").value) {
    $("q").value = "";
    state.q = "";
    rerun();
    return;
  }
  document.querySelectorAll("details.filter-group[open]").forEach((d) => {
    d.open = false;
    d.querySelector("summary").focus();
  });
});

/* ------------------------------------------------------------------ 5. boot */

// A run may already be going -- started on launch, or by a tab that has since
// been closed. Reattach to it rather than pretending nothing is happening.
if (ACTIVE_RUN) follow(ACTIVE_RUN);
boot();
