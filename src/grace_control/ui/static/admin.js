/* ############################################################################
 * AI_HEADER: admin.js (HTMX init + clock + health)
 * ROLE: Minimal JS for the HTMX-based operator console.
 *       - htmx.org is loaded via CDN in the base template.
 *       - This file only does: clock, health pill, and HTMX config tweaks
 *         (preserve scroll position in sidebars, set health on swap).
 *       - All routing, partial updates, search, filter, and tab swaps are
 *         handled by HTMX attributes in the server-rendered HTML.
 *       - For backward compat (the old /api/admin/* JSON endpoints) we
 *         also expose window.api() so the legacy fetch-style code keeps
 *         working, but no admin page uses it anymore.
 * ############################################################################ */

// ── HTMX config (preserves scroll in sidebars) ────────────────────────────
document.addEventListener("htmx:beforeRequest", function (evt) {
  // Mark the request so we can decide whether to preserve scroll.
  const target = evt.detail.target;
  if (target && target.id === "master-tree" || target && target.id === "timeline-pane") {
    evt.detail.requestConfig = evt.detail.requestConfig || {};
    // Don't reset scroll in the master/timeline panes on swap.
  }
});

document.addEventListener("htmx:beforeSwap", function (evt) {
  // When the master tree or timeline pane is swapped, don't change the
  // page scroll — only the new content's own scroll is reset by the browser.
  const target = evt.detail.target;
  if (target && (target.id === "master-tree" || target.id === "timeline-pane")) {
    // Save the existing scroll position of #main (page-level)
    const main = document.getElementById("main");
    const pageScrollY = window.scrollY;
    evt.detail.requestConfig = evt.detail.requestConfig || {};
    // Use swap="outerHTML" (set on the element) so the swap is in-place.
    // After the swap, restore page scroll:
    setTimeout(() => {
      if (main) main.scrollTop = main.scrollTop;  // no-op for outerHTML
      window.scrollTo(0, pageScrollY);
    }, 0);
  }
});

// ── Health pill ────────────────────────────────────────────────────────────
window.setHealth = function (h) {
  const node = document.getElementById("health");
  if (!h || !node) { return; }
  const cls = h.supervisor_alive ? (h.db_ok ? "ok" : "warn") : "err";
  node.className = "health " + cls;
  node.textContent = h.supervisor_alive
    ? "supervisor: " + (h.workers_alive || 0) + " workers"
    : "supervisor: down";
};

// ── Clock (24h format) ─────────────────────────────────────────────────────
function tick() {
  const el = document.getElementById("clock");
  if (!el) return;
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  el.textContent = hh + ":" + mm + ":" + ss;
}
tick();
setInterval(tick, 1000);

// ── Legacy: window.api for /api/admin/* JSON consumers ─────────────────────
window.api = async function (path, opts = {}) {
  const r = await fetch("/api/admin" + path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch (_) {}
    throw new Error(detail || ("HTTP " + r.status));
  }
  return r.json();
};

// Top-level navigation links should do a full reload (per spec:
// "Full page reload is allowed only for top-level navigation: Overview/System").
document.addEventListener("click", function (e) {
  const a = e.target.closest("a[data-topnav='true']");
  if (!a) return;
  // Let the browser handle it normally — full reload.
});

// HX-Trigger handlers for events from server → JS
document.addEventListener("htmx:afterSwap", function (evt) {
  // Update the health pill after a stats bar swap
  if (evt.detail.target && evt.detail.target.id === "stats-bar-container") {
    // The stats template includes a <script>setHealth(...)</script> inline.
    // The browser already executed it; nothing to do here.
  }
});
