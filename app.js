/* Spotify Rights Center — progressive enhancement only.
 * Pages are server-rendered; this handles the register-asset modal, the
 * bulk-select helper, and a confirm step on destructive bulk actions. */

(() => {
  "use strict";

  // --- Modal (open/close) --------------------------------------------------
  function closeModals() {
    document.querySelectorAll(".modal-wrap:not([hidden])").forEach((m) => { m.hidden = true; });
  }
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open]");
    if (opener) { const m = document.getElementById(opener.dataset.open); if (m) m.hidden = false; return; }
    if (e.target.closest("[data-close]")) closeModals();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });

  // --- Bulk select helper --------------------------------------------------
  const selectAll = document.getElementById("selectall");
  const bulkbar = document.getElementById("bulkbar");
  const bulkCount = document.getElementById("bulk-count");
  const rowChecks = () => Array.from(document.querySelectorAll(".row-check"));

  function syncBulk() {
    if (!bulkbar) return;
    const checked = rowChecks().filter((c) => c.checked).length;
    bulkbar.hidden = checked === 0;
    if (bulkCount) bulkCount.textContent = `${checked} selected`;
    if (selectAll) {
      const all = rowChecks();
      selectAll.checked = all.length > 0 && checked === all.length;
      selectAll.indeterminate = checked > 0 && checked < all.length;
    }
  }
  if (selectAll) selectAll.addEventListener("change", () => {
    rowChecks().forEach((c) => { c.checked = selectAll.checked; });
    syncBulk();
  });
  document.addEventListener("change", (e) => { if (e.target.classList.contains("row-check")) syncBulk(); });
  syncBulk();

  // --- Backlog burndown chart ---------------------------------------------
  // The SVG renders server-side and is fully readable without JS; this adds a
  // hover tooltip with exact weekly figures and lets the legend toggle series.
  document.querySelectorAll("[data-chart]").forEach((chart) => {
    const svg = chart.querySelector("svg");
    const tip = chart.querySelector(".bd-tip");
    const pts = Array.from(chart.querySelectorAll(".bd-pt"));
    const vbWidth = svg.viewBox.baseVal.width || 1;

    const swatch = (s) => `<i class="swatch swatch--${s}"></i>`;
    function activate(g) {
      const d = g.dataset;
      tip.innerHTML =
        `<span class="bd-tip__wk">${d.week}</span>` +
        `<span class="bd-tip__row">${swatch("backlog")}Open backlog<b>${d.backlog}</b></span>` +
        `<span class="bd-tip__row">${swatch("detected")}Detected<b>${d.detected}</b></span>` +
        `<span class="bd-tip__row">${swatch("resolved")}Resolved<b>${d.resolved}</b></span>`;
      const rect = svg.getBoundingClientRect();
      tip.style.left = `${(parseFloat(d.x) / vbWidth) * rect.width}px`;
      tip.hidden = false;
      pts.forEach((p) => p.classList.toggle("is-active", p === g));
    }
    function clear() {
      tip.hidden = true;
      pts.forEach((p) => p.classList.remove("is-active"));
    }
    pts.forEach((g) => {
      g.addEventListener("mouseenter", () => activate(g));
      g.addEventListener("mousemove", () => activate(g));
    });
    chart.addEventListener("mouseleave", clear);

    const section = chart.closest(".chart");
    if (section) section.querySelectorAll("[data-series]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const on = btn.getAttribute("aria-pressed") !== "true";
        btn.setAttribute("aria-pressed", String(on));
        svg.querySelectorAll(`[data-series-g="${btn.dataset.series}"]`)
          .forEach((el) => el.classList.toggle("is-hidden", !on));
      });
    });
  });

  // --- Confirm on destructive actions -------------------------------------
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-confirm]");
    if (!btn) return;
    if (btn.name === "action" && !rowChecks().some((c) => c.checked)) {
      e.preventDefault();
      return;
    }
    if (!window.confirm(btn.dataset.confirm)) e.preventDefault();
  });
})();
