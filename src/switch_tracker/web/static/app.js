"use strict";

const inr = (n) => (n === null || n === undefined ? "—" : "₹" + Math.round(n).toLocaleString("en-IN"));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const $ = (id) => document.getElementById(id);

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

/* ------------------------------------------------------------- actions */

const consoleBox = $("console");
let streaming = false;

function log(text, cls = "") {
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = text;
  consoleBox.appendChild(line);
  consoleBox.scrollTop = consoleBox.scrollHeight;
}

$("consoleToggle").addEventListener("click", () => {
  const hidden = consoleBox.classList.toggle("is-hidden");
  $("consoleToggle").textContent = hidden ? "Show logs" : "Hide logs";
});

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

  let cursor = fromSeq;
  const source = new EventSource(`/api/runs/${runId}/events?request_from=${cursor}`);

  source.onmessage = () => {};
  source.addEventListener("run_started", (e) =>
    log(`Run ${runId} started — ${JSON.parse(e.data).count} stores`));
  source.addEventListener("store_started", (e) => {
    const d = JSON.parse(e.data);
    log(`  ${d.store_id} (${d.detail || ""}) starting…`);
  });
  source.addEventListener("store_progress", (e) => {
    const d = JSON.parse(e.data);
    log(`    ${d.store_id}: page ${d.page} — ${d.count} listings so far`);
  });
  source.addEventListener("store_finished", (e) => {
    const d = JSON.parse(e.data);
    log(`  ${d.store_id}: ${d.status} — ${d.count} listings${d.detail ? " — " + d.detail : ""}`,
        d.status);
  });
  source.addEventListener("warning", (e) => log(`  ! ${JSON.parse(e.data).detail}`, "partial"));
  source.addEventListener("run_finished", () => {
    log("Run complete.");
    source.close();
    streaming = false;
    setButtonsDisabled(false);
    boot();
  });
  source.onerror = () => {
    // EventSource reconnects on its own; the server replays from the cursor,
    // so nothing is lost. Only give up if the run already ended.
    if (source.readyState === EventSource.CLOSED) {
      streaming = false;
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
        log("Done.");
        setButtonsDisabled(false);
        boot();
      }
    } catch (err) {
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
      log(`Opening ${storeId} in a real browser window. Alt+click the card, then its ` +
          `title, price and link.`);
    } catch (err) {
      log(String(err.message), "failed");
    }
  });
}

/* -------------------------------------------------------------- summary */

async function boot() {
  let sum, hp, mv;
  try {
    [sum, hp, mv] = await Promise.all([api("/api/summary"), api("/api/health"), api("/api/movers")]);
  } catch (err) {
    $("lede").innerHTML = `<span class="error">Could not read the database: ${esc(err.message)}</span>`;
    return;
  }

  if (!hp.run) {
    $("lede").textContent = "No collection has run yet. Press “Collect prices” to start one.";
  } else {
    $("stamp").textContent = "last run " +
      new Date(hp.run.started_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    $("lede").textContent =
      `${sum.listings.toLocaleString("en-IN")} listings across ${sum.stores} stores · ` +
      `${sum.points.toLocaleString("en-IN")} price observations · ` +
      `${sum.unmatched.toLocaleString("en-IN")} not yet matched to a canonical title.`;
  }

  $("strip").innerHTML = hp.stores.map((s) => `
    <div class="tile ${esc(s.status)}">
      <div class="n">${s.listings_found}</div>
      <div class="who">${esc(s.name)}</div>
      <div class="why" title="${esc(s.detail || s.status)}">${esc(s.detail || s.status)}</div>
    </div>`).join("") || '<div class="empty">Nothing collected yet.</div>';

  const fxCount = mv.filter((m) => m.fx_suspect).length;
  $("fxnote").innerHTML = fxCount
    ? `<div class="note"><b>${fxCount} of these moved together.</b> Same currency, same ratio,
       same day — that is the rupee moving against the dollar, not the shops changing their
       minds. Flagged rather than counted as price changes.</div>`
    : "";

  $("movers").innerHTML = mv.length ? `
    <table><thead><tr>
      <th>Title</th><th>Store</th><th class="num">Was</th><th class="num">Now</th>
      <th class="num">Change</th>
    </tr></thead><tbody>
    ${mv.map((m) => `<tr>
      <td><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.raw_title)}</a>
        ${m.region !== "IN" ? `<span class="tag">${esc(m.region)}</span>` : ""}
        ${m.fx_suspect ? `<span class="tag fx">FX</span>` : ""}
        ${!m.in_stock ? `<span class="tag oos">out of stock</span>` : ""}</td>
      <td>${esc(m.store)}</td>
      <td class="num">${inr(m.prev_price)}</td>
      <td class="num price">${inr(m.now_price)}</td>
      <td class="num ${m.pct < 0 ? "down" : "up"}">${m.pct > 0 ? "+" : ""}${m.pct.toFixed(1)}%</td>
    </tr>`).join("")}</tbody></table>`
    : `<div class="empty">Nothing to compare yet — price changes appear after a second run.</div>`;

  await loadFacets();
  await search();
}

/* -------------------------------------------------------------- listings */

// store and region are SETS. platform and condition stay single-valued -- their
// controls are three-way segments whose first option already means "all".
const state = { q: "", platform: "", condition: "", region: [], store: [],
                inStock: false, sort: "price", dir: "asc", offset: 0 };
let rows = [];

const COLS = [
  { key: "title", label: "Title", sortable: true },
  { key: "store", label: "Store", sortable: true },
  { key: null, label: "Native", num: true },
  { key: "price", label: "INR", sortable: true, num: true },
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
      ` ${esc(item.label)} <span class="muted">(${item.n})</span>`;
    box.appendChild(label);
  }
}

function syncChosen(key) {
  const chosen = state[key];
  const badge = document.querySelector(`.chosen[data-for="${key}"]`);
  if (badge) badge.textContent = chosen.length ? `(${chosen.length} selected)` : "";
}

async function loadFacets() {
  const f = await api("/api/facets");
  fillBoxes("storeBoxes", "store",
            f.stores.map((s) => ({ value: s.id, label: s.name, n: s.n })));
  fillBoxes("regionBoxes", "region",
            f.regions.map((r) => ({ value: r.region, label: r.region, n: r.n })));

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

async function search(append = false) {
  const data = await api("/api/listings?" + queryString());
  rows = append ? rows.concat(data.rows) : data.rows;

  $("count").textContent =
    `${rows.length.toLocaleString("en-IN")} of ${data.total.toLocaleString("en-IN")} listings` +
    ` — sorted in the database, not on this page`;

  const head = COLS.map((c) => c.sortable
    ? `<th class="sortable${c.num ? " num" : ""}" data-sort="${c.key}"
         aria-sort="${state.sort === c.key ? (state.dir === "asc" ? "ascending" : "descending") : "none"}">
         ${c.label}${state.sort === c.key ? (state.dir === "asc" ? " ↑" : " ↓") : ""}</th>`
    : `<th class="${c.num ? "num" : ""}">${c.label}</th>`).join("");

  const body = rows.map((r) => `<tr>
    <td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.raw_title)}</a>
      ${r.platform === "SWITCH2" ? '<span class="tag">SW2</span>' : ""}
      ${r.region !== "IN" ? `<span class="tag">${esc(r.region)}</span>` : ""}
      ${r.condition === "PRE_OWNED" ? '<span class="tag">pre-owned</span>' : ""}
      ${!r.in_stock ? '<span class="tag oos">out of stock</span>' : ""}</td>
    <td>${esc(r.store)}</td>
    <td class="num">${r.native_currency !== "INR"
      ? esc(r.native_currency) + " " + r.native_price : ""}</td>
    <td class="num price">${inr(r.inr_price)}</td>
  </tr>`).join("");

  const more = rows.length < data.total
    ? `<button class="more" id="more">Load ${Math.min(100, data.total - rows.length)} more</button>`
    : "";

  $("list").innerHTML = rows.length
    ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${more}`
    : '<div class="empty">Nothing matches those filters.</div>';

  $("list").querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
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
$("reset").addEventListener("click", () => {
  Object.assign(state, { q: "", platform: "", condition: "", region: [], store: [],
                         inStock: false, sort: "price", dir: "asc", offset: 0 });
  $("q").value = ""; $("stock").checked = false;
  clearFilter("store");
  clearFilter("region");
  for (const g of ["platform", "condition"]) {
    $(g).querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(i === 0)));
  }
  search();
});

// A run may already be going -- started on launch, or by a tab that has since
// been closed. Reattach to it rather than pretending nothing is happening.
if (ACTIVE_RUN) follow(ACTIVE_RUN);
boot();
