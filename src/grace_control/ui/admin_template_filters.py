# ############################################################################
# AI_HEADER: admin_template_filters
# ROLE: Custom Jinja2 filters used by admin HTMX partials.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Register custom Jinja2 filters for the admin HTMX templates.
#          Filters encapsulate the search/filter logic that was previously
#          in admin.js. Keeping them server-side means HTMX partials are
#          self-contained.
# inputs: list/dict values from the admin aggregation service.
# returns: filtered lists, booleans, counts.
# side_effects: None.
# emitted_logs: None.
# END_MODULE_CONTRACT

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode


# ── UI display layer ──────────────────────────────────────────────────────
# Maps raw backend states to calm, operator-friendly labels. Backend
# state strings are NOT changed. Only the labels/severity/CSS shown in
# the UI are mapped here. This keeps the raw state available in
# detail-metadata while removing visual noise from navigation/structure.

# severity values:
#   ok       — done / healthy / running
#   muted    — waiting / draft / not started / cancelled
#   attention — needs human review but not final
#   critical — selected failed/rejected/blocking only (one place)
#
# show_pill values:
#   "none"   — do not render any pill in navigation rows
#   "dot"    — render a small colored dot (left-side indicator)
#   "badge"  — render a small text badge (only for the selected detail)

_STATE_MAP: dict[str, dict[str, str]] = {
    # packet states
    "draft":              {"label": "Draft",                "severity": "muted",    "show": "none"},
    "ready":              {"label": "Ready",                "severity": "muted",    "show": "none"},
    "claimed":            {"label": "Running",              "severity": "ok",       "show": "dot"},
    "running":            {"label": "Running",              "severity": "ok",       "show": "dot"},
    "rejected":           {"label": "Reviewer rejected",    "severity": "attention", "show": "badge"},
    "failed":             {"label": "Failed",               "severity": "critical", "show": "badge"},
    "blocked":            {"label": "Blocked",              "severity": "attention", "show": "dot"},
    "blocked_recoverable": {"label": "Blocked",             "severity": "attention", "show": "dot"},
    "blocked_final":      {"label": "Blocked",              "severity": "critical", "show": "badge"},
    "accepted":           {"label": "Done",                 "severity": "ok",       "show": "dot"},
    "merged":             {"label": "Done",                 "severity": "ok",       "show": "dot"},
    "cancelled":          {"label": "Cancelled",            "severity": "muted",    "show": "none"},
    # wave / feature statuses (uppercase from DB)
    "NOT_STARTED":        {"label": "Waiting",              "severity": "muted",    "show": "none"},
    "DEGRADED":           {"label": "Has failed packets",   "severity": "attention", "show": "dot"},
    "COMPLETED":          {"label": "Done",                 "severity": "ok",       "show": "dot"},
    "ACTIVE":             {"label": "Running",              "severity": "ok",       "show": "dot"},
    "DONE":               {"label": "Done",                 "severity": "ok",       "show": "dot"},
    "FAILED":             {"label": "Failed",               "severity": "critical", "show": "badge"},
    "BLOCKED":            {"label": "Blocked",              "severity": "attention", "show": "dot"},
    "BLOCKED_FINAL":      {"label": "Blocked",              "severity": "critical", "show": "badge"},
    "CANCELLED":          {"label": "Cancelled",            "severity": "muted",    "show": "none"},
}


def _state_lookup(state: str | None) -> dict[str, str]:
    if not state:
        return {"label": "—", "severity": "muted", "show": "none"}
    entry = _STATE_MAP.get(state)
    if entry is None:
        # Unknown state — show raw value, treat as muted (not alarming)
        return {"label": str(state), "severity": "muted", "show": "none",
                "raw": str(state)}
    out = dict(entry)
    out["raw"] = str(state)
    return out


def ui_state(state: str | None) -> dict[str, str]:
    """Jinja filter: raw backend state → {label, severity, show, raw}.

    Usage in template:
        {{ packet.state | ui_state }}
    """
    return _state_lookup(state)


def state_label(state: str | None) -> str:
    """Jinja filter: raw state → human label. e.g. 'rejected' → 'Reviewer rejected'."""
    return _state_lookup(state)["label"]


def state_severity(state: str | None) -> str:
    """Jinja filter: raw state → severity class suffix ('ok' | 'muted' | 'attention' | 'critical')."""
    return _state_lookup(state)["severity"]


def is_attention(state: str | None) -> bool:
    """Jinja filter: True if state is in the attention bucket (failed/rejected/blocked)."""
    return _state_lookup(state)["severity"] in ("attention", "critical")


def raw_state(state: str | None) -> str:
    """Jinja filter: returns the raw backend state unchanged (for debug metadata)."""
    return str(state) if state else "—"


# ── Fallback titles ─────────────────────────────────────────────────────
# When a feature/wave/packet has a too-short or obviously technical title
# ("t", "d", "w1", "p1"), the UI shows "Untitled {kind}" as the main
# label and keeps the original as slug metadata.

# Title kinds (in order: feature, wave, packet)
_TITLE_KIND_LABELS = {
    "feature": "Untitled feature",
    "wave":    "Untitled wave",
    "packet":  "Untitled packet",
}

# Titles that look like obvious placeholders. Lower-cased for comparison.
_PLACEHOLDER_TITLES = frozenset([
    "t", "d", "w1", "w2", "w3", "p1", "p2", "p3",
    "test", "todo", "fix", "fixme", "none", "null", "-",
    "untitled", "n/a", "na",
])


def _is_placeholder_title(title: str | None) -> bool:
    """Heuristic: title is a placeholder if it is:
      - empty / None
      - very short (< 3 chars)
      - all-letters single token in the known placeholder set
      - looks like an identifier (e.g. "w1", "p1", "foo", "bar")
    """
    if not title:
        return True
    t = title.strip()
    if not t:
        return True
    tl = t.lower()
    if tl in _PLACEHOLDER_TITLES:
        return True
    if len(t) < 3:
        return True
    # Single token that looks like an identifier (w1, p1, foo, bar, abc)
    # OR starts with w/p followed by digits (common auto-naming)
    if " " not in t and ("_" not in t) and ("-" not in t):
        # Pure short identifier
        if len(t) <= 4 and t.isalnum():
            # Common auto-named waves/packets: w1, w2, p1, p2
            if (t[0] in ("w", "p") and t[1:].isdigit()) or tl in ("foo", "bar", "baz", "abc", "test"):
                return True
    return False


def display_title(title: str | None, kind: str = "feature") -> dict[str, str]:
    """Jinja filter: returns a dict suitable for rendering titles.

    Usage in template:
        {{ f.title | display_title('feature') }}

    Returns:
      {
        "title":     the human-readable title to show as the main heading,
        "is_placeholder": True if the original title was a placeholder,
        "original":  the original (un-trimmed) title — show as slug/meta
                     when is_placeholder is True.
      }

    When the title is "good" (long, not a placeholder), `title` == original
    and is_placeholder is False.
    """
    fallback = _TITLE_KIND_LABELS.get(kind, "Untitled")
    original = (title or "").strip()
    if _is_placeholder_title(original):
        return {
            "title": fallback,
            "is_placeholder": True,
            "original": original or "",
        }
    return {
        "title": original,
        "is_placeholder": False,
        "original": original,
    }


# ── Time / duration helpers ──────────────────────────────────────────────
# Used by the packet pipeline view, header, and run cards.

def fmt_duration(seconds: float | int | None) -> str:
    """Format a duration in seconds as a short human string.

    Examples:
      5      -> "5s"
      75     -> "1m 15s"
      3725   -> "1h 2m"
      None   -> ""
    """
    if seconds is None:
        return ""
    s = int(seconds)
    if s < 0:
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def fmt_time_short(iso: str | None) -> str:
    """Format an ISO timestamp as HH:MM:SS (24h, server-local portion).

    Returns "" if iso is falsy or unparseable.
    """
    if not iso:
        return ""
    if isinstance(iso, str):
        try:
            # Accept 'Z' suffix and '+00:00'
            s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
            dt = datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return ""
    else:
        dt = iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%H:%M:%S")


def fmt_duration_ms(ms: int | float | None) -> str:
    """Format milliseconds as a short duration string."""
    if ms is None:
        return ""
    return fmt_duration(ms / 1000.0)


def fmt_size(num_bytes: int | float | None) -> str:
    """Format a byte count as a human-readable string (B/KB/MB/GB/TB/PB).

    TZ_RETENTION_POLICY.md Phase 2. Examples:
        0       -> "0 B"
        512     -> "512 B"
        1024    -> "1.0 KB"
        1572864 -> "1.5 MB"
        2 GB    -> "2.0 GB"
        None    -> "0 B"
    """
    if num_bytes is None:
        return "0 B"
    n = float(num_bytes)
    if n == 0:
        return "0 B"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 1024:
        return f"{sign}{int(n) if n == int(n) else n} B"
    original = n
    for unit, divisor in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)):
        n = original / divisor
        if n < 1024:
            return f"{sign}{n:.1f} {unit}"
    n = original / 1024**5
    return f"{sign}{n:.1f} PB"


def safe_str(v: Any, fallback: str = "—") -> str:
    """Render a value as a string with a fallback for None/empty."""
    if v is None or v == "":
        return fallback
    return str(v)


def sum_packet_count(waves: list[dict[str, Any]] | None) -> int:
    """Sum packet counts across all waves in a feature."""
    if not waves:
        return 0
    n = 0
    for w in waves:
        n += len(w.get("packets") or [])
    return n


def matches_search(packet: dict[str, Any], query: str) -> bool:
    """Case-insensitive match against title, slug, id, and state."""
    if not query:
        return True
    ql = query.lower()
    for field in ("title", "slug", "id", "state"):
        v = packet.get(field)
        if v and ql in str(v).lower():
            return True
    return False


def filter_by_state(
    packets: list[dict[str, Any]] | None, state_filter: str
) -> list[dict[str, Any]]:
    """Filter packets by state category (all/failed/running/blocked/attention)."""
    if not packets:
        return []
    if not state_filter or state_filter == "all":
        return packets
    if state_filter == "failed":
        return [p for p in packets if p.get("state") in ("rejected", "failed")]
    if state_filter == "running":
        return [p for p in packets if p.get("state") == "running"]
    if state_filter == "blocked":
        return [p for p in packets if p.get("state") in (
            "blocked", "blocked_recoverable", "blocked_final",
        )]
    if state_filter == "attention":
        return [p for p in packets if p.get("state") in (
            "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
        )]
    return packets


def state_count(packets: list[dict[str, Any]] | None) -> dict[str, int]:
    """Return counts grouped by operator-facing categories."""
    packets = packets or []
    out = {"all": len(packets), "failed": 0, "running": 0,
           "blocked": 0, "attention": 0, "done": 0}
    for p in packets:
        s = p.get("state")
        if s in ("rejected", "failed"):
            out["failed"] += 1
            out["attention"] += 1
        elif s == "running":
            out["running"] += 1
        elif s in ("blocked", "blocked_recoverable", "blocked_final"):
            out["blocked"] += 1
            out["attention"] += 1
        elif s in ("accepted", "merged"):
            out["done"] += 1
    return out


def sum_packets(features: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Flatten all features → waves → packets into a single list."""
    out: list[dict[str, Any]] = []
    if not features:
        return out
    for f in features:
        for w in (f.get("waves") or []):
            for p in (w.get("packets") or []):
                out.append(p)
    return out


def status_class(s: str) -> str:
    """Map status string to CSS class (ok/err/warn)."""
    if not s:
        return "warn"
    s = s.upper()
    if s in ("COMPLETED", "DONE", "ACTIVE", "RUNNING", "ACCEPTED", "MERGED"):
        return "ok"
    if s in ("DEGRADED", "FAILED", "REJECTED", "BLOCKED", "BLOCKED_FINAL", "CANCELLED"):
        return "err"
    return "warn"


def state_machine_class(s: str) -> str:
    """Map state-machine step state to CSS class."""
    if not s:
        return ""
    return s  # values are already 'done'/'current'/'failed'/'blocked'/'pending'


def _decide_next_action(decision: dict[str, Any] | None,
                        recommendation: str | None) -> tuple[str | None, str]:
    """Internal: returns (text, css_class)."""
    if not decision:
        return None, ""
    if recommendation == "retry":
        return ("Safe to retry — same coder/wave. Click the packet to inspect.",
                "retry")
    if recommendation == "manual":
        return ("Max attempts reached — manual intervention required. "
                "Check stderr tail and reasoning.",
                "manual")
    state = (decision.get("state") or "").lower()
    if state.startswith("blocked"):
        return ("Blocked — review the recovery reason and decide whether to "
                "retry or skip.", "manual")
    if state == "rejected":
        return ("Rejected — fix the underlying failure and retry, or mark as "
                "skipped.", "manual")
    return None, ""


def next_action_text(args: tuple | list) -> str | None:
    """Jinja filter: (decision, recommendation) → text. Used as
    `blocking_decision, packet.recommendation | next_action_text`."""
    if not isinstance(args, (tuple, list)) or len(args) < 1:
        return None
    decision = args[0]
    rec = args[1] if len(args) > 1 else None
    text, _ = _decide_next_action(decision, rec)
    return text


def next_action_class(args: tuple | list) -> str:
    """Jinja filter: (decision, recommendation) → CSS class."""
    if not isinstance(args, (tuple, list)) or len(args) < 1:
        return ""
    decision = args[0]
    rec = args[1] if len(args) > 1 else None
    _, cls = _decide_next_action(decision, rec)
    return cls


def shell_url(
    feature_id: Any = None,
    packet_id: Any = None,
    wave_id: Any = None,
    tab: str = "timeline",
    search: str = "",
    filter: str = "all",
    expanded_features: Any = None,
    expanded_waves: Any = None,
) -> str:
    """Build the operator console shell URL from current state.

    Used for hx-push-url so the address bar always points to /admin?…
    (not /admin/_partial/…). Refreshing the URL restores the same view.

    `expanded_features`/`expanded_waves` may be set/list/str (comma-joined).
    `wave_id` is only included when a wave is explicitly selected (e.g.
    user clicked a wave card). When a packet is also selected, packet_id
    takes precedence in the detail pane.
    """
    params: list[tuple[str, str]] = []
    if feature_id:
        params.append(("feature_id", str(feature_id)))
    if wave_id and not packet_id:
        params.append(("wave_id", str(wave_id)))
    if packet_id:
        params.append(("packet_id", str(packet_id)))
    if tab and tab != "timeline":
        params.append(("tab", tab))
    if search:
        params.append(("search", search))
    if filter and filter != "all":
        params.append(("filter", filter))

    def _join(v: Any) -> str:
        if v is None or v == "":
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, (set, frozenset, list, tuple)):
            return ",".join(str(x) for x in v if x)
        return str(v)

    ef = _join(expanded_features)
    ew = _join(expanded_waves)
    if ef:
        params.append(("expanded_features", ef))
    if ew:
        params.append(("expanded_waves", ew))
    if not params:
        return "/admin"
    return "/admin?" + urlencode(params)


def register(env: Any) -> None:
    env.filters["sum_packet_count"] = sum_packet_count
    env.filters["sum_packets"] = sum_packets
    env.filters["matches_search"] = matches_search
    env.filters["filter_by_state"] = filter_by_state
    env.filters["state_count"] = state_count
    env.filters["status_class"] = status_class
    env.filters["state_machine_class"] = state_machine_class
    env.filters["next_action_text"] = next_action_text
    env.filters["next_action_class"] = next_action_class
    env.filters["ui_state"] = ui_state
    env.filters["state_label"] = state_label
    env.filters["state_severity"] = state_severity
    env.filters["is_attention"] = is_attention
    env.filters["raw_state"] = raw_state
    env.filters["fmt_duration"] = fmt_duration
    env.filters["fmt_duration_ms"] = fmt_duration_ms
    env.filters["fmt_size"] = fmt_size
    env.filters["fmt_time_short"] = fmt_time_short
    env.filters["safe_str"] = safe_str
    env.filters["display_title"] = display_title
    env.globals["shell_url"] = shell_url
