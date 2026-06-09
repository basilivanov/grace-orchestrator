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

// ── Dev Replay ─────────────────────────────────────────────────────────────
window.replayStage = function (btn) {
  var runId = btn.getAttribute("data-run-id");
  var action = btn.getAttribute("data-action");
  var stage = btn.getAttribute("data-stage");
  var resultEl = document.getElementById("replay-result");
  var allBtns = document.querySelectorAll(".dev-replay-btn[data-run-id='" + runId + "']");
  var originalText = btn.textContent;

  // Disable all buttons for this run, show loading
  for (var i = 0; i < allBtns.length; i++) {
    allBtns[i].disabled = true;
  }
  btn.textContent = originalText + " …";

  var url, body;
  if (action === "acceptance") {
    url = "/api/dev/runs/" + encodeURIComponent(runId) + "/replay-acceptance";
    body = JSON.stringify({ stage: stage });
  } else if (action === "verifier") {
    url = "/api/dev/runs/" + encodeURIComponent(runId) + "/rerun-verifier";
    body = "{}";
  } else if (action === "reviewer") {
    url = "/api/dev/runs/" + encodeURIComponent(runId) + "/rerun-reviewer";
    body = "{}";
  } else {
    return;
  }

  var startTime = Date.now();

  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body,
  })
    .then(function (r) {
      if (!r.ok) {
        return r.json().then(function (err) {
          throw err;
        }).catch(function (parseErr) {
          // If JSON parse fails, throw a generic error
          throw { detail: "HTTP " + r.status };
        });
      }
      return r.json();
    })
    .then(function (json) {
      var d = json.data || json;
      var elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      var cls = d.status === "passed" ? "dev-replay-ok" : "dev-replay-fail";
      var summary = d.summary || "no summary";
      var meta = d.replay_dir
        ? '<div class="dev-replay-meta-line muted small">artifacts: <span class="mono">' + d.replay_dir + "</span></div>"
        : "";
      var issues = "";
      if (d.blocking_issues && d.blocking_issues.length > 0) {
        issues = '<div class="dev-replay-issues"><strong>Blocking issues:</strong><ul>';
        for (var j = 0; j < d.blocking_issues.length; j++) {
          issues += "<li>" + escapeHtml(d.blocking_issues[j]) + "</li>";
        }
        issues += "</ul></div>";
      }
      resultEl.innerHTML =
        '<div class="dev-replay-entry ' + cls + '">' +
          "<strong>" + actionLabel(action, stage) + "</strong> " +
          "<span class='dev-replay-status'>" + (d.status || "done") + "</span> " +
          "<span class='muted small'>(" + elapsed + "s)</span>" +
          "<div class='dev-replay-summary'>" + escapeHtml(summary) + "</div>" +
          issues +
          meta +
        "</div>";
      // Append to history
      appendReplayHistory(runId, action, stage, d.status || (d.verdict || "done"), summary, elapsed);
    })
    .catch(function (err) {
      var detail = (err.detail && err.detail.message) || (err.detail && err.detail.error) || err.message || "Request failed";
      var patchPath = (err.detail && err.detail.patch_path) || "";
      var html =
        '<div class="dev-replay-entry dev-replay-fail">' +
          "<strong>" + actionLabel(action, stage) + "</strong> " +
          "<span class='dev-replay-status'>failed</span>" +
          "<div class='dev-replay-summary text-err'>" + escapeHtml(detail) + "</div>";
      if (patchPath) {
        html += '<div class="dev-replay-meta-line muted small">patch: <span class="mono">' + escapeHtml(patchPath) + "</span></div>";
      }
      html += "</div>";
      resultEl.innerHTML = html;
      appendReplayHistory(runId, action, stage, "error", detail, "—");
    })
    .finally(function () {
      // Re-enable buttons
      for (var k = 0; k < allBtns.length; k++) {
        allBtns[k].disabled = false;
      }
      btn.textContent = originalText;
    });
};

function actionLabel(action, stage) {
  if (action === "acceptance") {
    var labels = { t0: "Replay T0", t1: "Replay T1", t2: "Replay T2", full_acceptance: "Replay Full Acceptance" };
    return labels[stage] || "Replay " + stage;
  }
  if (action === "verifier") return "Replay Verifier";
  if (action === "reviewer") return "Replay Reviewer";
  return action;
}

function appendReplayHistory(runId, action, stage, status, summary, elapsed) {
  var container = document.getElementById("replay-history");
  if (!container) return;
  var time = new Date().toLocaleTimeString();
  var label = actionLabel(action, stage);
  var cls = (status === "passed" || status === "done" || status === "pass") ? "dev-replay-ok" : "dev-replay-fail";
  var entry = document.createElement("div");
  entry.className = "dev-replay-history-entry " + cls;
  entry.innerHTML =
    "<span class='muted small'>" + time + "</span> " +
    "<strong>" + escapeHtml(label) + "</strong>: " +
    "<span class='dev-replay-status'>" + escapeHtml(status) + "</span>" +
    "<span class='muted small'> (" + elapsed + "s)</span>" +
    "<div class='dev-replay-history-summary muted small'>" + escapeHtml(summary) + "</div>";
  container.appendChild(entry);
  // Keep last 20 entries
  while (container.children.length > 20) {
    container.removeChild(container.firstChild);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  var div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
