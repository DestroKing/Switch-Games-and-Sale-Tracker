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
      ["Complete scans", data.complete_scans],
      ["Unverified scans", data.unverified_scans],
    ].map(([label, value]) =>
      `<div class="market-stat"><b>${Number(value).toLocaleString("en-IN")}</b><span>${esc(label)}</span></div>`
    ).join("");
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
    Promise.all([loadOverview(), loadCatalogue()]).catch((error) => {
      catalogue.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    });
  });
  query.addEventListener("input", () => {
    clearTimeout(query._marketDebounce);
    query._marketDebounce = setTimeout(loadCatalogue, 180);
  });
  platform.addEventListener("change", loadCatalogue);

  Promise.all([loadOverview(), loadCatalogue()]).catch((error) => {
    catalogue.innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
  });
})();
