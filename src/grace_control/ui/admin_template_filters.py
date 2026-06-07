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

from typing import Any


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
           "blocked": 0, "attention": 0}
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
