"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const safeUrl = (value) => (/^https?:\/\//i.test(String(value ?? "")) ? esc(value) : "#");
  const query = $("marketQuery");
  const platform = $("marketPlatform");
  const catalogue = $("marketCatalogue");
  const detail = $("marketDetail");
  if (!query || !platform || !catalogue || !detail) return;

  async function get(path) {
    const response = await fetch(path);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || body.error || response.statusText);
    return body;
  }

  async function loadOverview() {
    const data = await get("/api/market/overview");
    $("marketStats").innerHTML = [
      ["Physical releases", data.products],
      ["Retailer items", data.retailer_items],
      ["Evidence records", data.evidence_records],
      ["Retailer scans", data.total_scans],
      ["Complete scans", data.complete_scans],
      ["Partial scans", data.partial_scans],
      ["Failed scans", data.failed_scans],
      ["Unknown coverage", data.unknown_scans],
      ["Unresolved listings", data.unresolved_items],
    ].map(([label, value]) =>
      `<div class="market-stat"><b>${Number(value).toLocaleString("en-IN")}</b><span>${esc(label)}</span></div>`
    ).join("");
  }

  async function loadCoverage() {
    const target = $("marketCoverage");
    if (!target) return;
    try {
      const rows = await get("/api/market/scans?limit=40");
      if (!rows.length) {
        target.innerHTML = '<p class="empty">No market scans yet. Run Collect prices to begin retailer discovery.</p>';
        return;
      }
      target.innerHTML = `
        <h3>Recent retailer scan coverage</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>Store</th><th>Scope</th><th>Coverage</th><th>Items observed</th><th>Completed</th><th>Detail</th></tr></thead>
          <tbody>${rows.map((row) => `
            <tr>
              <td>${esc(row.store_name)}</td><td>${esc(row.scope_type)}</td>
              <td><b>${esc(row.coverage_status)}</b></td><td class="num">${Number(row.observed_items).toLocaleString("en-IN")}</td>
              <td>${esc(row.completed_at || row.started_at)}</td>
              <td>${esc(row.detail || row.completion_evidence || "—")}</td>
            </tr>`).join("")}</tbody>
        </table></div>`;
    } catch (error) {
      target.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    }
  }

  async function loadDiscoveries() {
    const target = $("marketDiscoveries");
    if (!target) return;
    try {
      const data = await get("/api/market/discoveries?limit=100");
      if (!data.rows.length) {
        target.innerHTML = '<p class="empty">No unresolved retailer listings. Listings are linked to physical releases only after their edition, region and format can be identified safely.</p>';
        return;
      }
      target.innerHTML = `
        <div class="tablewrap"><table>
          <thead><tr><th>Listing title</th><th>Platform</th><th>Region</th><th>Retailer</th><th>Latest state</th><th>Price</th><th>Last seen</th><th>Source</th></tr></thead>
          <tbody>${data.rows.map((row) => `
            <tr>
              <td>${esc(row.raw_title || row.sku)}</td><td>${esc(row.platform || "UNKNOWN")}</td>
              <td>${esc(row.region || "UNKNOWN")}</td><td>${esc(row.store_name)}</td>
              <td>${esc(row.latest_state || "UNKNOWN")}</td>
              <td class="num">${row.latest_price == null ? "—" : `${esc(row.latest_currency || "")} ${esc(row.latest_price)}`}</td>
              <td>${esc(row.last_seen)}</td>
              <td><a href="${safeUrl(row.url)}" target="_blank" rel="noopener noreferrer">Open listing</a></td>
            </tr>`).join("")}</tbody>
        </table></div><p class="count">${data.total} unresolved retailer listings</p>`;
    } catch (error) {
      target.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    }
  }

  async function loadCatalogue() {
    catalogue.innerHTML = '<p class="empty">Loading physical releases…</p>';
    const params = new URLSearchParams({ q: query.value, platform: platform.value, limit: "200" });
    try {
      const data = await get(`/api/market/catalogue?${params}`);
      if (!data.rows.length) {
        catalogue.innerHTML = '<p class="empty"><b>No catalogue records yet.</b> Add verified physical releases to begin tracking. Existing price-watch listings are not silently promoted into release identities.</p>';
        return;
      }
      catalogue.innerHTML = `
        <div class="tablewrap"><table>
          <thead><tr><th>Physical release</th><th>Platform</th><th>Edition</th><th>Region</th><th>Format</th><th>Retailer items</th><th>Verified independent</th><th>Evidence</th></tr></thead>
          <tbody>${data.rows.map((row) => `
            <tr>
              <td><button type="button" class="market-open" data-id="${row.id}">${esc(row.title)}</button></td>
              <td>${esc(row.platform)}</td><td>${esc(row.edition)}</td><td>${esc(row.region)}</td>
              <td>${esc(row.physical_format)}</td><td class="num">${row.retailer_count}</td>
              <td class="num">${row.verified_independent_count}</td><td class="num">${row.evidence_count}</td>
            </tr>`).join("")}</tbody>
        </table></div><p class="count">${data.total} physical releases</p>`;
    } catch (error) {
      catalogue.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    }
  }

  async function loadDetail(id) {
    try {
      const data = await get(`/api/market/products/${encodeURIComponent(id)}`);
      const p = data.product;
      detail.hidden = false;
      detail.innerHTML = `
        <div class="section-head"><h3>${esc(p.title)}</h3><button type="button" id="marketClose">Close</button></div>
        <p>${esc(p.platform)} · ${esc(p.edition)} · ${esc(p.region)} · ${esc(p.physical_format)}</p>
        <h4>Retailer observations</h4>
        ${data.retailer_items.length ? `<ul>${data.retailer_items.map((item) =>
          `<li><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.store_name)}</a> — ${esc(item.latest_state || "No stock observation")} · ${esc(item.retailer_relationship || "UNVERIFIED")} ${item.latest_price == null ? "" : `· ${esc(item.latest_currency || "")} ${esc(item.latest_price)}`}</li>`
        ).join("")}</ul>` : "<p>No retailer items recorded.</p>"}
        <h4>Evidence</h4>
        ${data.evidence.length ? `<ul>${data.evidence.map((item) =>
          `<li><a href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">${esc(item.source_name || item.evidence_type)}</a> — ${esc(item.verification)} · checked ${esc(item.checked_at)}<p>${esc(item.notes || "")}</p></li>`
        ).join("")}</ul>` : "<p>No publisher, distributor, packaging or reprint evidence recorded.</p>"}
        <p class="muted">Only explicitly verified independent businesses count toward the strict independent-retailer figure. Marketplace and unverified seller relationships are not treated as independent. Availability and out-of-print status are separate assessments. An incomplete scan cannot establish absence.</p>`;
      $("marketClose").addEventListener("click", () => { detail.hidden = true; });
    } catch (error) {
      detail.hidden = false;
      detail.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    }
  }

  catalogue.addEventListener("click", (event) => {
    const button = event.target.closest("[data-id]");
    if (button) loadDetail(button.dataset.id);
  });
  $("marketRefresh").addEventListener("click", () => {
    Promise.all([loadOverview(), loadCoverage(), loadDiscoveries(), loadCatalogue()]).catch((error) => {
      catalogue.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    });
  });
  query.addEventListener("input", () => {
    clearTimeout(query._marketDebounce);
    query._marketDebounce = setTimeout(loadCatalogue, 180);
  });
  platform.addEventListener("change", loadCatalogue);

  Promise.all([loadOverview(), loadCoverage(), loadDiscoveries(), loadCatalogue()]).catch((error) => {
    catalogue.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
  });
})();
