/* ############################################################################
 * GRACE Admin v3 — Redesigned JS
 * Minimal JS for the HTMX-based operator console.
 * - htmx.org is loaded via CDN in the base template.
 * - This file: clock, health pill, HTMX scroll preservation,
 *   redraw fix (clear detail pane on feature switch), dev replay.
 * ############################################################################ */

// ── HTMX config ────────────────────────────────────────────────────────────

// Preserve scroll positions in sidebars during HTMX swaps
document.addEventListener("htmx:beforeSwap", function (evt) {
  var target = evt.detail.target;
  if (target && (target.id === "master-tree" || target.id === "timeline-pane")) {
    var pageScrollY = window.scrollY;
    setTimeout(function () {
      window.scrollTo(0, pageScrollY);
    }, 0);
  }
});

// After any HTMX swap, update master tree selection state
document.addEventListener("htmx:afterSwap", function (evt) {
  var target = evt.detail.target;

  // Health pill update after stats bar swap
  if (target && target.id === "stats-bar-container") {
    // The stats template includes inline <script>setHealth(...)</script>
    // which the browser already executed.
  }

  // When timeline pane is swapped (feature selection changed),
  // also clear the detail pane if no packet/wave is explicitly selected.
  // This fixes the "stale detail" redraw bug.
  if (target && target.id === "timeline-pane") {
    // Check if the URL has a packet_id or wave_id — if not, clear detail
    var url = new URL(window.location);
    if (!url.searchParams.get("packet_id") && !url.searchParams.get("wave_id")) {
      var detailPane = document.getElementById("detail-pane");
      if (detailPane) {
        // Only clear if it still has old content (not already empty)
        var hasContent = detailPane.querySelector(".pkt-head-bar, .wave-head-bar, .needs-attention, .pipeline-view, .tabs");
        if (hasContent) {
          htmx.ajax("GET", "/admin/_partial/detail?feature_id=" + (url.searchParams.get("feature_id") || ""), "#detail-pane");
        }
      }
    }
  }
});

// ── Health pill ────────────────────────────────────────────────────────────
window.setHealth = function (h) {
  var node = document.getElementById("health");
  if (!h || !node) { return; }
  var cls = h.supervisor_alive ? (h.db_ok ? "ok" : "warn") : "err";
  node.className = "health " + cls;
  node.textContent = h.supervisor_alive
    ? "supervisor: " + (h.workers_alive || 0) + " workers"
    : "supervisor: down";
};

// ── Clock (24h format) ─────────────────────────────────────────────────────
function tick() {
  var el = document.getElementById("clock");
  if (!el) return;
  var d = new Date();
  var hh = String(d.getHours()).padStart(2, "0");
  var mm = String(d.getMinutes()).padStart(2, "0");
  var ss = String(d.getSeconds()).padStart(2, "0");
  el.textContent = hh + ":" + mm + ":" + ss;
}
tick();
setInterval(tick, 1000);

// ── Legacy API ─────────────────────────────────────────────────────────────
window.api = async function (path, opts) {
  opts = opts || {};
  var r = await fetch("/api/admin" + path, {
    headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
    method: opts.method || "GET",
    body: opts.body,
  });
  if (!r.ok) {
    var detail = "";
    try { detail = (await r.json()).detail || ""; } catch (_) {}
    throw new Error(detail || ("HTTP " + r.status));
  }
  return r.json();
};

// ── Top-level nav: full reload ─────────────────────────────────────────────
document.addEventListener("click", function (e) {
  var a = e.target.closest("a[data-topnav='true']");
  if (!a) return;
  // Let the browser handle it — full reload
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
      for (var k = 0; k < allBtns.length; k++) {
        allBtns[k].disabled = false;
      }
      btn.textContent = originalText;
    });
};

function actionLabel(action, stage) {
  if (action === "acceptance") {
    var labels = { t0: "Replay T0", t1: "Replay T1", t2: "Replay T2", full_acceptance: "Full Acceptance" };
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
