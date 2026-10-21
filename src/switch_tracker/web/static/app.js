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

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** An href that can only ever be a web link. esc() makes a value safe INSIDE
 *  an attribute, but not as a URL: "javascript:alert(1)" escapes to itself
 *  and runs when clicked, on this page's origin. Store URLs come from the
 *  stores' own data, and rows saved before collect.py started refusing other
 *  schemes are still in the database, so the check lives here too. */
const safeHref = (url) => (/^https?:\/\//i.test(String(url ?? "")) ? esc(url) : "#");

/** Every fetch goes through here so a backend fault is VISIBLE.
 *  An {error} body with HTTP 200 would be dereferenced as data, turning any
 *  failure into a JavaScript type error rendered as content. */
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
  if (!disabled) {
    syncCollectSelected();
    syncFixOpen();  // re-enabled wholesale above; only live with a store picked
  }
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
const fixOpen = $("fixOpen");

/** Open is live only with a store picked. Choosing used to ACT on `change`,
 *  and a <select> fires change on every arrow key, so browsing the list with
 *  the keyboard opened a browser window per keypress. */
function syncFixOpen() {
  // Both are absent when no store is fixable (the template renders neither).
  if (fixOpen && fixPicker) fixOpen.disabled = !fixPicker.value;
}

if (fixPicker && fixOpen) {
  fixPicker.addEventListener("change", syncFixOpen);
  fixOpen.addEventListener("click", async () => {
    const storeId = fixPicker.value;
    if (!storeId) return;
    fixPicker.value = "";
    syncFixOpen();
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

/** How many movers to show before the fold; Show all reveals the full result set. */
const MOVERS_PREVIEW = 6;
let moversExpanded = false;
let moversData = [];
let moversStore = "";


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
  const dropLabel = num(drops);
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
  paintMoverStoreFilter();
  paintMovers();

  loadSchedule();  // not awaited: an OS query, and nothing below depends on it
  // Watchlist before the table: the table's ☆ buttons are painted from it.
  await Promise.all([loadWatch(), loadFacets()]);
  await search();
}


/** One line under the Collector heading: whether prices are collected daily
 *  without anyone pressing a button, and when next. Read-only on purpose --
 *  setting the schedule up is a command, not something a web page may do. */
async function loadSchedule() {
  const note = $("scheduleNote");
  let s;
  try {
    s = await api("/api/schedule");
  } catch {
    note.textContent = "";
    return;
  }
  if (!s.supported) {
    note.textContent = "";
  } else if (s.registered) {
    note.innerHTML = `<span class="status ok">Collects daily on its own</span>` +
      (s.next_run ? `<span class="muted"> · next ${esc(s.next_run)}</span>` : "") +
      (s.last_run && !/never|N\/A/i.test(s.last_run) ? `<span class="muted"> · last ${esc(s.last_run)}</span>` : "");
  } else {
    note.innerHTML = `<span class="status idle">Not collecting automatically</span>` +
      `<span class="muted"> · to collect every day, run <code>START.bat schedule --at 07:30</code></span>`;
  }
}

function paintMoverStoreFilter() {
  const select = $("moversStore");
  const previous = moversStore;

  const stores = [...new Set(
    moversData.map((m) => m.store).filter(Boolean)
  )].sort((a, b) => a.localeCompare(b));

  select.innerHTML =
    '<option value="">All stores</option>' +
    stores.map((store) =>
      `<option value="${esc(store)}">${esc(store)}</option>`
    ).join("");

  // Keep the selection if that store still has movements.
  // Otherwise, return to All stores.
  moversStore = stores.includes(previous) ? previous : "";
  select.value = moversStore;
}


/** The movers table, capped to a preview with an explicit way to see the rest.
 *  Progressive disclosure rather than truncation: the count is always visible,
 *  so nothing is hidden without saying so. */
function paintMovers() {
  const mv = moversStore
    ? moversData.filter((m) => m.store === moversStore)
    : moversData;

  const shown = moversExpanded
    ? mv
    : mv.slice(0, MOVERS_PREVIEW);
  $("moversSub").textContent = mv.length
    ? `${mv.length} changed`
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
          <a class="name" href="${safeHref(m.url)}" target="_blank" rel="noopener">${esc(m.raw_title)}</a><span class="meta">${
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

$("moversStore").addEventListener("change", (event) => {
  moversStore = event.target.value;
  moversExpanded = false;
  paintMovers();
});


/* -------------------------------------------------------------- 4. listings */

// store and region are SETS. platform and condition stay single-valued -- their
// controls are three-way segments whose first option already means "all".
const BLANK = { q: "", platform: "", condition: "", region: [], store: [],
                inStock: false, sort: "price", dir: "asc", offset: 0 };
// `view` lives outside BLANK: "Reset all" clears filters, not which view you chose.
const state = { ...BLANK, region: [], store: [], view: "games" };
let rows = [];
let facets = { stores: [], regions: [] };

/** The expand column. Its header is named for screen readers only: a visible
 *  "Details" label over a column of ▸ glyphs is noise. */
const EXPAND_COL = { key: null, label: "Details", hideLabel: true };

/** One row per game -- the cheapest copy you can actually buy, and where. */
const GAME_COLS = [
  EXPAND_COL,
  { key: "title", label: "Game", sortable: true },
  { key: "price", label: "Best price", sortable: true, num: true,
    hint: "Cheapest in-stock offer; an out-of-stock price only when nothing is in stock" },
  { key: null, label: "Where" },
  { key: "offers", label: "Offers", sortable: true, num: true, hint: "Listings across every store" },
  { key: null, label: "Watch", hideLabel: true },
];

const COLS = [
  EXPAND_COL,
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

const colsFor = (view) => (view === "games" ? GAME_COLS : COLS);

/** The filters alone, without sort or paging. Shared by the main table and by
 *  a game's expanded offers, so expanding a row lists exactly the offers its
 *  "Offers" count was computed from. */
function filterParams() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  for (const k of ["platform", "condition"]) if (state[k]) p.set(k, state[k]);
  // Comma-separated, matching /actions/collect?only=a,b -- one encoding for
  // "a set of ids" across the whole app. A single value produces ?store=x,
  // so old bookmarks keep working.
  for (const k of ["store", "region"]) if (state[k].length) p.set(k, state[k].join(","));
  if (state.inStock) p.set("in_stock", "true");
  return p;
}

/** What the address bar carries: the filters, plus sort and view when they
 *  are not the defaults. Never offset/limit -- a bookmark is a question, not
 *  a scroll position. */
function pageParams() {
  const p = filterParams();
  if (state.sort !== BLANK.sort || state.dir !== BLANK.dir) {
    p.set("sort", state.sort);
    p.set("dir", state.dir);
  }
  if (state.view !== "games") p.set("view", state.view);
  return p;
}

/** The reverse, once at load: location.search into `state` and the controls.
 *  Anything not offered by a control is ignored; unknown stores/regions are
 *  dropped by loadFacets once it knows what exists. */
function readUrl() {
  const p = new URLSearchParams(location.search);
  const pick = (id, value) =>
    [...$(id).querySelectorAll("button")].find((b) => b.dataset.v === value);
  for (const id of ["view", "platform", "condition"]) {
    const chosen = pick(id, p.get(id) ?? (id === "view" ? state.view : ""));
    if (!chosen) continue;
    state[id] = chosen.dataset.v;
    $(id).querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === chosen)));
  }
  state.q = (p.get("q") ?? "").trim();
  $("q").value = state.q;
  state.inStock = p.get("in_stock") === "true";
  $("stock").checked = state.inStock;
  for (const key of ["store", "region"]) {
    state[key] = (p.get(key) ?? "").split(",").filter(Boolean);
  }
  if (colsFor(state.view).some((c) => c.sortable && c.key === p.get("sort"))) state.sort = p.get("sort");
  if (p.get("dir") === "asc" || p.get("dir") === "desc") state.dir = p.get("dir");
}

function queryString() {
  const p = filterParams();
  p.set("sort", state.sort);
  p.set("dir", state.dir);
  p.set("limit", "100");
  p.set("offset", String(state.offset));
  return p.toString();
}

/** Build one checkbox per value that actually exists in the data. */
function fillBoxes(containerId, key, items) {
  const box = $(containerId);
  // Counts refresh while the popover is open, right after a tick. Put focus
  // back on that box, or a keyboard user is dropped onto <body> mid-list.
  const focused = box.contains(document.activeElement) ? document.activeElement.value : null;
  box.innerHTML = "";
  for (const item of items) {
    const label = document.createElement("label");
    label.className = "check";
    label.innerHTML =
      `<input type="checkbox" data-filter="${key}" value="${esc(item.value)}">` +
      `<span>${esc(item.label)} <span class="muted">(${item.n})</span></span>`;
    box.appendChild(label);
  }
  if (focused !== null) box.querySelector(`input[value="${CSS.escape(focused)}"]`)?.focus();
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

/** The filters the facet counts on screen were computed under; search()
 *  refetches when they differ. facetSeq is searchSeq's guard, for facets. */
let facetsKey = null;
let facetSeq = 0;

async function loadFacets() {
  const seq = ++facetSeq;
  facetsKey = filterParams().toString();
  const data = await api("/api/facets?" + facetsKey);
  if (seq !== facetSeq) return;
  facets = data;
  // A value from a hand-edited or stale URL that is not in the data is dropped,
  // not kept as a filter that can only ever match nothing.
  state.store = state.store.filter((v) => facets.stores.some((s) => s.id === v));
  state.region = state.region.filter((v) => facets.regions.some((r) => r.region === v));
  fillBoxes("storeBoxes", "store",
            facets.stores.map((s) => ({ value: s.id, label: s.name, n: s.n })));
  fillBoxes("regionBoxes", "region",
            facets.regions.map((r) => ({ value: r.region, label: r.region, n: r.n })));
  // Rebuilt boxes start unticked; re-tick the active filters so a reload after
  // a collection does not show "Store (2)" over an empty list of ticks.
  for (const [containerId, key] of [["storeBoxes", "store"], ["regionBoxes", "region"]]) {
    $(containerId).querySelectorAll("input").forEach((b) => { b.checked = state[key].includes(b.value); });
  }
  syncChosen("store");
  syncChosen("region");
}

// Delegated, and bound ONCE at load. The boxes are rebuilt whenever facets
// reload, so a listener on each box would be lost -- and binding these inside
// loadFacets(), which boot() reruns after every collection, stacked one more
// listener per run: after N runs one tick fired N searches.
for (const [containerId, key] of [["storeBoxes", "store"], ["regionBoxes", "region"]]) {
  $(containerId).addEventListener("change", () => {
    state[key] = [...$(containerId).querySelectorAll("input:checked")].map((b) => b.value);
    syncChosen(key);
    rerun();
  });
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
    const label = col.hideLabel
      ? `<span class="visually-hidden">${esc(col.label)}</span>`
      : esc(col.label);
    return `<th class="plain${cls}" scope="col"${hint}>${label}</th>`;
  }
  const active = state.sort === col.key;
  const dir = state.dir === "asc" ? "ascending" : "descending";
  // A real <button>, so the control is in the tab order and announced as a
  // control. aria-sort lives on the <th>, which is where assistive technology
  // looks for it.
  return `<th class="${cls.trim()}" scope="col"${active ? ` aria-sort="${dir}"` : ""}>
    <button class="sort" type="button" data-sort="${col.key}"${col.hint ? ` title="${esc(col.hint)}"` : ""}>
      <span>${esc(col.label)}</span>
      <span class="arrow" aria-hidden="true">${active ? (state.dir === "asc" ? "▲" : "▼") : ""}</span>
    </button></th>`;
}

function deltaCell(row) {
  const moved = movementById.get(row.id);

  // queries.py now returns change_pct for every listing that has
  // a previous observation. Fall back to /api/movers for compatibility.
  const pct = row.change_pct ?? moved?.pct;

  if (pct === null || pct === undefined || pct === 0) {
    return `<td class="num dim">—</td>`;
  }

  const down = pct < 0;

  // /api/movers contains the previous absolute price, so retain the
  // existing tooltip whenever that information is available.
  const title = moved
    ? ` title="was ${inr(moved.prev_price)}"`
    : "";

  return `<td class="num"><span class="delta ${down ? "down" : "up"}"${title}>` +
         `${Math.abs(pct) < 0.05 ? "<0.1" : Math.abs(pct).toFixed(1)}%</span></td>`;
}

const tags = (r) =>
  (r.platform === "SWITCH2" ? '<span class="tag sw2">Switch 2</span>' : "") +
  (r.region && r.region !== "IN" ? `<span class="tag">${esc(r.region)}</span>` : "") +
  (r.condition === "PRE_OWNED" ? '<span class="tag used">pre-owned</span>' : "") +
  (r.in_stock === false || r.in_stock === 0 ? '<span class="tag oos">out of stock</span>' : "");

/** The ▸ control that opens a detail row under its own row. A real button with
 *  aria-expanded, so the state is announced and Enter/Space work for free. */
const expander = (kind, attrs, label) =>
  `<td class="expand-cell"><button class="expand" type="button" aria-expanded="false" ` +
  `data-kind="${kind}" ${attrs} aria-label="${esc(label)}"></button></td>`;

function listingRowHtml(r) {
  const moved = movementById.get(r.id);
  const isDeal = moved && moved.pct < 0 && !moved.fx_suspect;
  return `<tr class="${isDeal ? "is-deal" : ""}">
      ${expander("history", `data-id="${r.id}"`, `Price history for ${r.raw_title} at ${r.store}`)}
      <td class="title-cell"><div class="clamp">
        <a class="name" href="${safeHref(r.url)}" target="_blank" rel="noopener">${esc(r.raw_title)}</a><span class="meta">${
          tags(r)}</span></div></td>
      <td>${esc(r.store)}</td>
      <td class="num dim">${r.native_currency !== "INR"
        ? esc(r.native_currency) + " " + num(r.native_price) : ""}</td>
      <td class="num price">${inr(r.inr_price)}</td>
      ${deltaCell(r)}
    </tr>`;
}

/** "3 stores" when every offer is a different shop -- the common case -- and
 *  "4 offers · 3 stores" only when one shop lists it twice (new + pre-owned). */
const offersLabel = (g) => {
  const stores = `${num(g.stores)} ${g.stores === 1 ? "store" : "stores"}`;
  return g.offers === g.stores ? stores : `${num(g.offers)} offers<span class="dim"> · ${stores}</span>`;
};

/** The price cell of a Games or Watchlist row: the best price, then its
 *  history -- "lowest ever" when it IS the all-time low (only with 2+ runs of
 *  history; see queries.games), otherwise the low it has been, if lower. That
 *  answers "is this a good price?" without opening the chart. */
function priceCell(best, lowest, atLowest) {
  const note = atLowest
    ? '<span class="tag low">lowest ever</span>'
    : lowest !== null && lowest !== undefined && best !== null && lowest < best
      ? `<span class="lowest">lowest ${inr(lowest)}</span>`
      : "";
  return `<td class="num price">${inr(best)}${note ? `<span class="price-note">${note}</span>` : ""}</td>`;
}

function gameRowHtml(g) {
  const watching = watchedKeys().has(watchKey(g.game, g.platform));
  const best = { platform: g.platform, region: g.best_region, condition: g.best_condition,
                 in_stock: g.best_in_stock };
  return `<tr>
      ${expander("offers", `data-game="${esc(g.game)}" data-platform="${esc(g.platform)}"`,
                 `Every offer for ${g.title}`)}
      <td class="title-cell"><div class="clamp">
        <span class="name">${esc(g.title)}</span><span class="meta">${
          g.platform === "SWITCH2" ? '<span class="tag sw2">Switch 2</span>' : ""}</span></div></td>
      ${priceCell(g.best_price, g.lowest_ever, g.at_lowest)}
      <td><a href="${safeHref(g.best_url)}" target="_blank" rel="noopener">${esc(g.best_store)}</a>` +
      `<span class="meta">${tags({ ...best, platform: "" })}</span></td>
      <td class="num">${offersLabel(g)}</td>
      <td>${watchButton(g.game, g.platform, watching)}</td>
    </tr>`;
}

/** "312 games", or "Showing 100 of 312 games" only while there is more to load.
 *  Sorting by Change narrows the list to real movers (queries.py), which reads
 *  like rows vanishing unless the line says why the total dropped. */
function countLine(shown, total, games) {
  const noun = games ? (total === 1 ? "game" : "games") : (total === 1 ? "listing" : "listings");
  const base = shown < total
    ? `Showing <b>${num(shown)}</b> of <b>${num(total)}</b> ${noun}`
    : `<b>${num(total)}</b> ${noun}`;
  return !games && state.sort === "change"
    ? `${base} that moved more than 1% since the previous run`
    : base;
}

/** Bumped by every search(). A reply whose number is no longer current is
 *  dropped: without this, a "Load more" for Games that answered AFTER a switch
 *  to Every listing appended game rows into the listings table, and any two
 *  quick filter changes could paint the older answer last. */
let searchSeq = 0;

async function search(append = false) {
  const seq = ++searchSeq;
  if (!append) {
    $("list").innerHTML = `<div class="tablewrap">${skeleton("skel-row", 12)}</div>`;
    // Every filter, sort and view change ends here, so this one line keeps the
    // address bar bookmarkable. Replace, not push: back leaves the page rather
    // than stepping through every tick.
    const url = pageParams().toString();
    history.replaceState(null, "", location.pathname + (url ? "?" + url : ""));
    if (filterParams().toString() !== facetsKey) loadFacets().catch(() => { facetsKey = null; });
  }

  const games = state.view === "games";
  let data;
  try {
    data = await api(`/api/${games ? "games" : "listings"}?` + queryString());
    if (seq !== searchSeq) return;
  } catch (err) {
    if (seq !== searchSeq) return;
    $("list").innerHTML =
      `<div class="notice error" role="alert"><div><b>Could not load ${games ? "games" : "listings"}.</b> ` +
      `${esc(err.message)}</div></div>`;
    return;
  }
  rows = append ? rows.concat(data.rows) : data.rows;

  // Named exactly as its toggle button, so the heading confirms the choice.
  $("listingsHead").textContent = games ? "Games" : "Every listing";
  $("count").innerHTML = countLine(rows.length, data.total, games);
  paintChips();

  const head = colsFor(state.view).map(headerCell).join("");
  const rowHtml = games ? gameRowHtml : listingRowHtml;

  // Appending paints ONLY the new rows, into the <tbody> that is already on
  // screen. Reassigning innerHTML rebuilds every row including the ones you
  // were reading, and the browser has no anchor left to hold, so the viewport
  // snaps to the top -- which made "Load 100 more" cost you the scroll back.
  const tbody = append ? $("list").querySelector("tbody") : null;
  const first = tbody ? rows.length - data.rows.length : 0;
  // Sorted by price, games you can buy come first in both directions, so the
  // out-of-stock tail restarts the price order. Say so with ONE separator,
  // placed by the first such row's index across everything loaded so far --
  // so a "Load more" page can never add a second one.
  // Priced rows only: unpriced games (no exchange rate yet) sort last of all,
  // in stock or not, so they never start the out-of-stock block.
  const oosAt = games && state.sort === "price"
    ? rows.findIndex((r) => r.best_price !== null && !r.best_in_stock) : -1;
  const body = rows.slice(first).map((r, i) =>
    (first + i === oosAt
      // A td, not a th: every th is position:sticky in app.css. Not
      // tr.detail either: collapsing the row above would delete it.
      ? `<tr class="oos-sep"><td colspan="${colsFor(state.view).length}" class="muted">` +
        `<b>Out of stock everywhere</b> — sorted by price again below</td></tr>`
      : "") + rowHtml(r)).join("");

  const more = rows.length < data.total
    ? `<button class="more" id="more">Load ${Math.min(100, data.total - rows.length)} more</button>`
    : "";

  if (tbody) {
    // Read focus BEFORE the old button is removed: someone who reached it by
    // keyboard must not be dropped onto <body>. preventScroll, because
    // restoring focus would otherwise scroll past the rows just loaded.
    const refocus = document.activeElement && document.activeElement.id === "more";
    tbody.insertAdjacentHTML("beforeend", body);
    const stale = $("more");
    if (stale) stale.remove();
    if (more) $("list").insertAdjacentHTML("beforeend", more);
    if (refocus && $("more")) $("more").focus({ preventScroll: true });
  } else {
    $("list").innerHTML = rows.length
      ? `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`
      : `<div class="empty"><b>Nothing matches those filters</b>
         Try clearing one — the chips above show what is currently narrowing the list.</div>`;

    // Bound on a full paint only. On append these buttons keep the DOM nodes
    // they already have, so binding again would fire one sort click twice.
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
  }

  // Always rebound: this button is recreated on every paint, appended or not.
  const moreButton = $("more");
  if (moreButton) moreButton.addEventListener("click", () => {
    state.offset += 100;
    search(true);
  });
}

/* ---------------------------------------------------- detail rows (▸) */

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** A price line drawn from the series, no chart library: one <polyline>.
 *  Time-scaled on x, so a three-week gap LOOKS like a gap rather than being
 *  squeezed between two adjacent daily points. */
function sparkline(points) {
  const W = 280, H = 48, P = 4;
  const t = points.map((p) => Date.parse(p.captured_at));
  const v = points.map((p) => p.inr_price);
  const [t0, t1] = [Math.min(...t), Math.max(...t)];
  const [lo, hi] = [Math.min(...v), Math.max(...v)];
  const x = (i) => P + ((t[i] - t0) / (t1 - t0 || 1)) * (W - 2 * P);
  const y = (i) => H - P - ((v[i] - lo) / (hi - lo || 1)) * (H - 2 * P);
  const line = points.map((_, i) => `${x(i).toFixed(1)},${y(i).toFixed(1)}`).join(" ");
  const last = points.length - 1;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">` +
    `<polyline points="${line}"/><circle cx="${x(last)}" cy="${y(last)}" r="2.5"/></svg>`;
}

/** The chart is decoration; THIS sentence is the content, and it is what a
 *  screen reader gets. Lowest-ever is the number a buyer actually wants. */
function historyHtml(series) {
  const points = series.filter((p) => p.inr_price !== null);
  if (!points.length) return `<p class="muted">No rupee price recorded yet.</p>`;
  const last = points[points.length - 1];
  if (points.length === 1) {
    return `<p class="muted">One price so far: <b>${inr(last.inr_price)}</b> on ${fmtDate(last.captured_at)}.
      A line appears after the next collection.</p>`;
  }
  const low = points.reduce((a, b) => (b.inr_price < a.inr_price ? b : a));
  const high = points.reduce((a, b) => (b.inr_price > a.inr_price ? b : a));
  return `<div class="history">${sparkline(points)}<p>
      Now <b>${inr(last.inr_price)}</b> · lowest <b>${inr(low.inr_price)}</b> (${fmtDate(low.captured_at)})
      · highest ${inr(high.inr_price)} · ${num(points.length)} prices since ${fmtDate(points[0].captured_at)}
    </p></div>`;
}

async function offersHtml(game, platform) {
  const p = filterParams();
  p.set("game", game);
  p.set("platform", platform);
  p.set("sort", "price");
  p.set("dir", "asc");
  p.set("limit", "100");
  const data = await api("/api/listings?" + p.toString());
  if (!data.rows.length) return `<p class="muted">No offers match the current filters.</p>`;
  return `<table class="offers"><caption class="visually-hidden">Every offer for this game</caption>
    <thead><tr>${COLS.map((c) => headerCell({ ...c, sortable: false })).join("")}</tr></thead>
    <tbody>${data.rows.map(listingRowHtml).join("")}</tbody></table>`;
}

/* One delegated handler for every ▸ on the page, nested ones included.
   Bound once to a container that outlives every repaint -- per-button
   listeners would be lost on each paint and doubled on each append. */
$("list").addEventListener("click", async (e) => {
  const button = e.target.closest("button.expand");
  if (!button) return;
  const row = button.closest("tr");
  const open = button.getAttribute("aria-expanded") === "true";
  if (open) {
    row.nextElementSibling?.classList.contains("detail") && row.nextElementSibling.remove();
    button.setAttribute("aria-expanded", "false");
    return;
  }
  button.setAttribute("aria-expanded", "true");
  const span = row.children.length;
  row.insertAdjacentHTML("afterend",
    `<tr class="detail"><td colspan="${span}"><p class="muted">Loading…</p></td></tr>`);
  const cell = row.nextElementSibling.firstElementChild;
  try {
    cell.innerHTML = button.dataset.kind === "history"
      ? historyHtml(await api(`/api/history?id=${encodeURIComponent(button.dataset.id)}`))
      : await offersHtml(button.dataset.game, button.dataset.platform);
  } catch (err) {
    cell.innerHTML = `<p class="bad">Could not load: ${esc(err.message)}</p>`;
  }
});

/* ------------------------------------------------------------ watchlist */

let watched = [];
const watchKey = (game, platform) => `${platform}|${game}`;
// Also the key the server resolved it to (best.game): a watch saved before an
// alias or a matcher change keeps its old key, and its ☆ must still light up.
const watchedKeys = () => new Set(watched.flatMap((w) =>
  [watchKey(w.game, w.platform), watchKey(w.best?.game ?? w.game, w.platform)]));

const watchButton = (game, platform, on) =>
  `<button class="watch quiet" type="button" aria-pressed="${on}" data-game="${esc(game)}" ` +
  `data-platform="${esc(platform)}">${on ? "★ Watching" : "☆ Watch"}</button>`;

async function loadWatch() {
  try {
    watched = await api("/api/watchlist");
  } catch (err) {
    $("watch").innerHTML = `<div class="notice error" role="alert"><div><b>Could not read the watchlist.</b> ` +
      `${esc(err.message)}</div></div>`;
    return;
  }
  paintWatch();
}

function paintWatch() {
  const hits = watched.filter((w) => w.hit);
  // The tab title carries the count, so a hit is visible from another tab.
  document.title = (hits.length ? `(${hits.length}) ` : "") + "Switch cartridge prices";
  $("watchSub").textContent = watched.length
    ? `${watched.length} watched` + (hits.length ? ` · ${hits.length} at or below target` : "")
    : "";
  // Notifying is an extra; painting the panel is the feature. localStorage
  // throws in some privacy modes, and that must never leave the panel blank.
  try { notifyNewHits(hits); } catch { /* the panel below still shows every hit */ }

  // Every save repaints this table, and a save fires on BLUR -- i.e. exactly
  // when Tab has just moved focus to the next control in it. Remember which
  // control that was and put focus back, or a keyboard user lands on <body>.
  const active = document.activeElement;
  // data-cond too: the Any/New pair share classes and game, so without it the
  // refocus would land on "Any" after pressing "New".
  const refocus = active && $("watch").contains(active) && active.dataset.game
    ? `.${[...active.classList].join(".")}[data-game="${CSS.escape(active.dataset.game)}"]` +
      `[data-platform="${CSS.escape(active.dataset.platform)}"]` +
      (active.dataset.cond ? `[data-cond="${CSS.escape(active.dataset.cond)}"]` : "")
    : null;

  if (!watched.length) {
    $("watch").innerHTML = `<div class="empty compact"><b>Nothing watched yet</b>
      Press ☆ Watch on a game below, then set the price you would pay.</div>`;
    return;
  }
  $("watch").innerHTML = `<div class="tablewrap"><table>
    <caption class="visually-hidden">Watched games, best current offer and your target</caption>
    <thead><tr><th class="plain" scope="col">Game</th><th class="plain num" scope="col">Best now</th>
      <th class="plain" scope="col">Where</th>
      <th class="plain" scope="col" title="Which copies count against your target">Copies</th>
      <th class="plain num" scope="col">Your target</th>
      <th class="plain" scope="col"><span class="visually-hidden">Remove</span></th></tr></thead>
    <tbody>${watched.map((w) => {
      const b = w.best;
      const title = b ? b.title : w.game;
      return `<tr class="${w.hit ? "is-deal" : ""}">
        <td class="title-cell"><div class="clamp"><span class="name">${esc(title)}</span><span class="meta">${
          w.platform === "SWITCH2" ? '<span class="tag sw2">Switch 2</span>' : ""}${
          w.hit ? '<span class="status ok">at target</span>' : ""}</span></div></td>
        ${b ? priceCell(b.best_price, b.lowest_ever, b.at_lowest) : '<td class="num price">—</td>'}
        <td>${b ? `<a href="${safeHref(b.best_url)}" target="_blank" rel="noopener">${esc(b.best_store)}</a>` +
              `<span class="meta">${tags({ region: b.best_region, condition: b.best_condition,
                                           in_stock: b.best_in_stock })}</span>`
            : '<span class="muted">No offers right now</span>'}</td>
        <td>${conditionToggle(w, title)}</td>
        <td class="num"><input class="target" type="number" inputmode="numeric" min="1" step="1"
             value="${w.target ?? ""}" placeholder="₹ any" data-game="${esc(w.game)}"
             data-platform="${esc(w.platform)}" aria-label="Target price for ${esc(title)}"></td>
        <td><button class="quiet unwatch" type="button" data-game="${esc(w.game)}"
             data-platform="${esc(w.platform)}" aria-label="Stop watching ${esc(title)}">Remove</button></td>
      </tr>`;
    }).join("")}</tbody></table></div>`;
  if (refocus) $("watch").querySelector(refocus)?.focus({ preventScroll: true });
}

/** Any / New only, per watched game: whether a pre-owned copy can satisfy the
 *  target. The same segmented control as the toolbar's console and condition
 *  filters, so it reads as a choice of two rather than a button. */
function conditionToggle(w, title) {
  const button = (value, label) =>
    `<button type="button" class="cond" data-cond="${value}" data-game="${esc(w.game)}" ` +
    `data-platform="${esc(w.platform)}" aria-pressed="${w.condition === value}">${label}</button>`;
  return `<div class="seg mini" role="group" aria-label="Copies that count for ${esc(title)}">` +
    button("ANY", "Any") + button("NEW", "New only") + `</div>`;
}

/** A field left ``undefined`` is not sent, and the server then KEEPS it. So
 *  the target box (no condition) and the Any/New toggle (no target) never
 *  overwrite each other -- not even when one's request is still in flight
 *  while the other's is sent. ``null`` target is sent: it means "no target". */
async function saveWatch(game, platform, target, condition) {
  const body = { game, platform };
  if (target !== undefined) body.target = target;
  if (condition) body.condition = condition;
  watched = await api("/api/watchlist", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  paintWatch();
}

async function dropWatch(game, platform) {
  // Remember the entry first: unwatching used to throw a typed-in target away
  // with no way back, one mis-click on ★ from losing it for good.
  // An exact watch first: with both an old-key watch that resolves to this
  // game and a direct one on it, ★ must remove the direct one.
  const previous = watched.find((w) => w.game === game && w.platform === platform)
    ?? watched.find((w) => w.best?.game === game && w.platform === platform);
  // Delete by the STORED key: a ☆ in the table carries the game's current key.
  game = previous?.game ?? game;
  watched = await api(`/api/watchlist?${new URLSearchParams({ game, platform })}`, { method: "DELETE" });
  paintWatch();
  if (!previous) return;
  const name = previous.best?.title || game;
  watchNote(`Stopped watching ${esc(name)}. <button type="button" class="linkish" id="undoWatch">Undo</button>`,
            12000);
  // "Remove" deletes the very button that had focus, which drops a keyboard
  // user onto <body>. Undo is the natural next stop, so land there instead.
  // (Unwatching via ☆ in the table keeps its button, so focus is left alone.)
  if (!document.activeElement || document.activeElement === document.body) $("undoWatch").focus();
  $("undoWatch").addEventListener("click", async () => {
    watchNote("");
    try {
      // The condition explicitly: the entry was deleted, so the server has no
      // setting left to keep, and "New only" would quietly come back as Any.
      await saveWatch(game, platform, previous.target ?? null, previous.condition);
      syncWatchButtons();
      watchNote(`<span class="status ok">Watching ${esc(name)} again</span>`);
    } catch (err) {
      watchNote(`<span class="status failed">Could not undo: ${esc(err.message)}</span>`);
    }
  });
}

let watchNoteTimer;
/** One short-lived message beside the watchlist heading. Replaces any earlier
 *  one, so a quick second action never leaves a stale "Undo" pointing at the
 *  wrong game. ``html`` must already be escaped. */
function watchNote(html, ms = 4000) {
  clearTimeout(watchNoteTimer);
  $("watchNote").innerHTML = html;
  if (html) watchNoteTimer = setTimeout(() => { $("watchNote").innerHTML = ""; }, ms);
}

/** Re-label every ☆ for one game wherever it appears, without repainting the
 *  table -- a repaint would collapse whatever rows the user had opened. */
function syncWatchButtons() {
  const keys = watchedKeys();
  document.querySelectorAll("button.watch").forEach((b) => {
    const on = keys.has(watchKey(b.dataset.game, b.dataset.platform));
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "★ Watching" : "☆ Watch";
  });
}

$("list").addEventListener("click", async (e) => {
  const button = e.target.closest("button.watch");
  if (!button) return;
  const { game, platform } = button.dataset;
  // Asked here, on a click, because browsers only grant it from a user gesture.
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  try {
    if (button.getAttribute("aria-pressed") === "true") await dropWatch(game, platform);
    else await saveWatch(game, platform, null);
  } catch (err) {
    alert(`Could not update the watchlist: ${err.message}`);
  }
  syncWatchButtons();
});

$("watch").addEventListener("change", async (e) => {
  const input = e.target.closest("input.target");
  if (!input) return;
  // A number field reports "" for text it cannot parse ("4,500", "4k"), which
  // would read below as "no target" and silently WIPE the saved one.
  if (input.validity.badInput) {
    input.setCustomValidity("Enter the price as a plain number, e.g. 4500");
    input.reportValidity();
    return;
  }
  const value = input.value.trim() === "" ? null : Number(input.value);
  if (value !== null && !(value > 0)) { input.setCustomValidity("Enter a price above zero"); input.reportValidity(); return; }
  input.setCustomValidity("");
  try {
    await saveWatch(input.dataset.game, input.dataset.platform, value);
    // It saves on blur with no button, so say so -- otherwise nothing on
    // screen tells the user the number they typed was kept.
    watchNote(`<span class="status ok">${value === null ? "Target cleared" : `Target ${inr(value)} saved`}</span>`);
  } catch (err) {
    input.setCustomValidity(err.message);
    input.reportValidity();
  }
});

$("watch").addEventListener("click", async (e) => {
  const button = e.target.closest("button.cond");
  if (!button || button.getAttribute("aria-pressed") === "true") return;
  const { game, platform, cond } = button.dataset;
  // No target sent: the server keeps whatever it has. Sending the target from
  // `watched` raced an unsaved edit -- type a price, click "New only", and the
  // toggle's request could land second and put the OLD price back.
  try {
    await saveWatch(game, platform, undefined, cond);
    watchNote(`<span class="status ok">${cond === "NEW" ? "Counting new copies only" : "Counting any copy"}</span>`);
  } catch (err) {
    watchNote(`<span class="status failed">Could not change it: ${esc(err.message)}</span>`);
  }
});

$("watch").addEventListener("click", async (e) => {
  const button = e.target.closest("button.unwatch");
  if (!button) return;
  try {
    await dropWatch(button.dataset.game, button.dataset.platform);
  } catch (err) {
    alert(`Could not update the watchlist: ${err.message}`);
  }
  syncWatchButtons();
});

/** A desktop notification for each NEWLY hit target, if the user allowed it.
 *  "Newly" is remembered across reloads, or every page load would re-announce
 *  the same hit until it stopped being one. */
function notifyNewHits(hits) {
  const seen = new Set(JSON.parse(localStorage.getItem("notifiedHits") || "[]"));
  const now = hits.map((w) => watchKey(w.game, w.platform));
  if ("Notification" in window && Notification.permission === "granted") {
    for (const w of hits) {
      if (seen.has(watchKey(w.game, w.platform))) continue;
      new Notification(`${w.best.title}: ${inr(w.best.best_price)}`,
        { body: `At or below your ${inr(w.target)} target, at ${w.best.best_store}.` });
    }
  }
  // Only CURRENT hits are kept, so a game that drops back under target later
  // is announced again rather than silenced forever.
  localStorage.setItem("notifiedHits", JSON.stringify(now));
}

/* ---------------------------------------------------------- view switch */

$("view").addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button || button.dataset.v === state.view) return;
  $("view").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
  state.view = button.dataset.v;
  // A sort the other view has no column for would silently fall back on the
  // server and leave a stale arrow here; reset it visibly instead.
  if (!colsFor(state.view).some((c) => c.sortable && c.key === state.sort)) {
    state.sort = "price";
    state.dir = "asc";
  }
  rerun();
});

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
readUrl();
boot();
