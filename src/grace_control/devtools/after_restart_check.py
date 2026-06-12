# ############################################################################
# AI_HEADER: after_restart_check
# ROLE: Post-restart consistency checker for the GRACE control plane.
#       Operator/devtool — NOT production runtime. Lives under
#       grace_control.devtools/ and is invoked manually after a supervisor
#       restart (or in CI as a smoke check).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate that after a restart the GRACE control plane is in a
#          consistent state: API reachable, state files readable, optional
#          supervisor socket responds. Optional packet-id probe.
# inputs: api_url, state_root, supervisor_sock, project_root, packet_id,
#         timeout_sec. All optional — fall back to settings, then env.
# returns: AfterRestartReport with component-level passed/failed/skipped
#          results and counters.
# side_effects: HTTP health checks, filesystem reads, optional unix-socket
#               probe. Never mutates anything.
# emitted_logs: after_restart_check_started, after_restart_check_component,
#               after_restart_check_complete.
# error_behavior: Never raises — each component failure is recorded.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ComponentResult
#   - dataclass: AfterRestartReport
#   - function: run_after_restart_check
#   - main:     CLI entrypoint (python -m grace_control.devtools.after_restart_check)
# END_MODULE_MAP

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("after_restart_check")

# Status enum for component results. Skipped is separate from passed
# (TZ §10) so a missing optional supervisor socket is not silently
# counted as a pass.
ComponentStatus = Literal["passed", "failed", "skipped"]


#START_BLOCK_DATACLASSES

@dataclass
class ComponentResult:
    """A single check's outcome.

    `status` is the canonical state:
      - passed: check ran and met its criteria;
      - failed: check ran and did not meet its criteria;
      - skipped: check did not run (typically because an optional
        dependency like supervisor_sock was not configured).
    `passed` is kept as a derived bool for back-compat with anything
    reading the old attribute.
    """
    name: str
    status: ComponentStatus
    detail: str = ""
    duration_ms: float = 0.0
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass
class AfterRestartReport:
    started_at: str = ""
    finished_at: str = ""
    components: list[ComponentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Configuration snapshot — what the checker actually used, useful
    # for debugging "why didn't it check X" without re-running.
    config: dict[str, Any] = field(default_factory=dict)

    # ── counters ──
    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.components if c.status == "passed")

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.components if c.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for c in self.components if c.status == "skipped")

    @property
    def total_count(self) -> int:
        return len(self.components)

    # ── aggregate verdict ──
    # Per TZ §10: skipped does not count as failure. all_passed is true
    # when no non-skipped component failed.
    @property
    def all_passed(self) -> bool:
        return self.failed_count == 0 and self.total_count > 0

    @property
    def summary(self) -> str:
        return (
            f"{self.passed_count} passed, "
            f"{self.failed_count} failed, "
            f"{self.skipped_count} skipped "
            f"(total {self.total_count})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "all_passed": self.all_passed,
            "summary": self.summary,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "total_count": self.total_count,
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "passed": c.passed,
                    "detail": c.detail,
                    "duration_ms": c.duration_ms,
                    "error": c.error,
                }
                for c in self.components
            ],
            "errors": list(self.errors),
            "config": dict(self.config),
        }

#END_BLOCK_DATACLASSES


#START_BLOCK_RESOLUTION

def _resolve_api_url(api_url: str | None) -> str | None:
    """Pick API URL: explicit arg > GRACE_API_URL env > settings.api_url.

    Returns None when no source is available. The API check handles
    None as `api_url_unresolved` (skipped). We deliberately do NOT
    fall back to a hardcoded host:port — the central source of truth
    is settings.api_url (which itself reads from env /
    .grace/config.yaml). Without it the operator must provide one
    explicitly via --api-url or GRACE_API_URL.
    """
    if api_url:
        return api_url
    env = os.environ.get("GRACE_API_URL")
    if env:
        return env
    try:
        from grace_control.config.settings import settings
        return settings.api_url
    except Exception:
        return None


def _resolve_state_root(state_root: Path | str | None) -> Path:
    """Pick state root: explicit arg > GRACE_STATE_ROOT env > settings.state_root."""
    if state_root:
        return Path(state_root)
    env = os.environ.get("GRACE_STATE_ROOT")
    if env:
        return Path(env)
    try:
        from grace_control.config.settings import settings
        return Path(settings.state_root)
    except Exception:
        return Path(".grace/state")


def _resolve_supervisor_sock(supervisor_sock: Path | str | None) -> Path | None:
    """Pick supervisor socket: explicit arg > GRACE_SUPERVISOR_SOCK env > None."""
    if supervisor_sock:
        return Path(supervisor_sock)
    env = os.environ.get("GRACE_SUPERVISOR_SOCK")
    if env:
        return Path(env)
    return None


def _parse_host_port(api_url: str) -> tuple[str, int]:
    """Best-effort parse of (host, port) from an http://host:port URL."""
    from urllib.parse import urlparse
    parsed = urlparse(api_url)
    host = parsed.hostname or "127.0.0.1"
    try:
        port = parsed.port or 80
    except ValueError:
        port = 80
    return host, port

#END_BLOCK_RESOLUTION


#START_BLOCK_CHECKS

async def _check_api_health(api_url: str | None, timeout_sec: int) -> ComponentResult:
    """Try a real /health endpoint first, fall back to TCP port probe.

    Distinguishes four outcomes (TZ §5.6 + follow-up):
      - api_health_http_ok: /health endpoint returned 2xx;
      - api_health_tcp_only_ok: HTTP failed but TCP socket connected;
      - api_health_failed: nothing reachable;
      - api_url_unresolved: api_url is None (no explicit arg, no env,
        no settings). Reported as status=\"skipped\" so the absence of
        a central source does not silently degrade to a hard failure.
    """
    import time
    start = time.monotonic()
    if not api_url:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="api_health",
            status="skipped",
            detail="api_url_unresolved (no --api-url, no GRACE_API_URL, no settings.api_url)",
            duration_ms=dur,
        )
    host, port = _parse_host_port(api_url)
    health_url = api_url.rstrip("/") + "/health"
    # Try HTTP /health first
    try:
        import urllib.request
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = getattr(resp, "status", 200)
            if 200 <= status < 300:
                dur = (time.monotonic() - start) * 1000
                return ComponentResult(
                    name="api_health",
                    status="passed",
                    detail=f"api_health_http_ok ({health_url} -> {status})",
                    duration_ms=dur,
                )
    except Exception as http_err:
        http_err_str = f"{type(http_err).__name__}: {http_err}"
    else:
        http_err_str = ""

    # Fall back to TCP
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_sec,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="api_health",
            status="passed",
            detail=f"api_health_tcp_only_ok ({host}:{port}); /health failed: {http_err_str}",
            duration_ms=dur,
        )
    except Exception as tcp_err:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="api_health",
            status="failed",
            detail=f"api_health_failed ({host}:{port}); http_err={http_err_str}; tcp_err={tcp_err}",
            duration_ms=dur,
            error=str(tcp_err),
        )


async def _check_state_files(state_root: Path) -> ComponentResult:
    """Walk state_root for *.json, detect stuck RUNNING/CLAIMED states.

    Legacy `.grace_state` is reported as a separate component status
    detail so operators can clean it up, not as a hard failure.

    State values are normalized to UPPER before comparison because real
    PacketState values are lowercase in the system (running, ready,
    failed, merged, etc.). Uppercase RUNNING/CLAIMED here are the
    canonical reference, not assumptions about input casing.
    """
    import time
    start = time.monotonic()
    legacy_note = ""
    if not state_root.exists():
        # Detect legacy `.grace_state` next to the project root as a hint.
        # Walk up from state_root looking for a sibling `.grace_state`.
        # For state_root=".grace/state" the sibling is "<root>/.grace_state".
        # This is informational only — does not fail the check.
        for ancestor in (state_root.parent, state_root.parent.parent):
            if ancestor is None:
                continue
            legacy = ancestor / ".grace_state"
            if legacy.exists() and legacy.is_dir():
                legacy_note = f"; legacy_state_root_detected={legacy}"
                break
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="state_files",
            status="passed",
            detail=f"state root {state_root} does not exist (clean){legacy_note}",
            duration_ms=dur,
        )
    errors: list[str] = []
    json_files = sorted(state_root.rglob("*.json"))
    for f in json_files:
        try:
            data = json.loads(f.read_text())
        except Exception as e:
            errors.append(f"{f.relative_to(state_root)}: unreadable ({e})")
            continue
        state_norm = str(data.get("state", data.get("status", ""))).upper()
        if state_norm in ("RUNNING", "CLAIMED"):
            errors.append(f"{f.relative_to(state_root)}: stuck in {state_norm}")
    dur = (time.monotonic() - start) * 1000
    if errors:
        return ComponentResult(
            name="state_files",
            status="failed",
            detail="; ".join(errors[:5]),
            duration_ms=dur,
            error=f"{len(errors)} state file issue(s)",
        )
    return ComponentResult(
        name="state_files",
        status="passed",
        detail=f"{len(json_files)} state files OK under {state_root}{legacy_note}",
        duration_ms=dur,
    )


async def _check_packet_operations(state_root: Path,
                                    packet_id: str | None) -> ComponentResult:
    """Optional probe for a specific packet. Skipped if no packet_id given."""
    import time
    start = time.monotonic()
    if not packet_id:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="packet_operations",
            status="skipped",
            detail="no packet_id provided",
            duration_ms=dur,
        )
    state_file = state_root / f"{packet_id}.json"
    if not state_file.exists():
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="packet_operations",
            status="skipped",
            detail=f"packet {packet_id} has no state file under {state_root}",
            duration_ms=dur,
        )
    try:
        data = json.loads(state_file.read_text())
    except Exception as e:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="packet_operations",
            status="failed",
            detail=f"cannot read packet state file: {state_file.relative_to(state_root) if state_root in state_file.parents else state_file.name}",
            duration_ms=dur,
            error=str(e),
        )
    state_norm = str(data.get("state", data.get("status", "unknown"))).upper()
    dur = (time.monotonic() - start) * 1000
    if state_norm in ("FAILED", "REJECTED", "MERGED", "CANCELLED"):
        return ComponentResult(
            name="packet_operations",
            status="passed",
            detail=f"packet {packet_id} terminal ({state_norm})",
            duration_ms=dur,
        )
    return ComponentResult(
        name="packet_operations",
        status="passed",
        detail=f"packet {packet_id} state={state_norm}",
        duration_ms=dur,
    )


async def _check_worker_health(supervisor_sock: Path | None,
                                timeout_sec: int) -> ComponentResult:
    """Probe GRACE supervisor unix socket. Skipped if not configured."""
    import time
    start = time.monotonic()
    if supervisor_sock is None:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="worker_health",
            status="skipped",
            detail="no supervisor_sock configured (set --supervisor-sock or GRACE_SUPERVISOR_SOCK)",
            duration_ms=dur,
        )
    if not supervisor_sock.exists():
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="worker_health",
            status="failed",
            detail=f"supervisor socket not found: {supervisor_sock}",
            duration_ms=dur,
            error="socket missing",
        )
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(supervisor_sock)),
            timeout=timeout_sec,
        )
    except Exception as e:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="worker_health",
            status="failed",
            detail=f"cannot connect to supervisor socket: {supervisor_sock}",
            duration_ms=dur,
            error=str(e),
        )
    try:
        writer.write(json.dumps({"action": "status"}).encode() + b"\n")
        await writer.drain()
        resp = await asyncio.wait_for(reader.readline(), timeout=timeout_sec)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        data = json.loads(resp.decode())
        workers = data.get("workers", [])
        alive = [w for w in workers if w.get("alive")]
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="worker_health",
            status="passed",
            detail=f"{len(alive)}/{len(workers)} workers alive",
            duration_ms=dur,
        )
    except Exception as e:
        dur = (time.monotonic() - start) * 1000
        return ComponentResult(
            name="worker_health",
            status="failed",
            detail=f"worker status query failed",
            duration_ms=dur,
            error=str(e),
        )

#END_BLOCK_CHECKS


#START_BLOCK_RUNNER

async def run_after_restart_check(
    *,
    project_root: Path | str | None = None,
    api_url: str | None = None,
    state_root: Path | str | None = None,
    supervisor_sock: Path | str | None = None,
    packet_id: str | None = None,
    timeout_sec: int = 10,
) -> AfterRestartReport:
    """Run all post-restart consistency checks. Never raises.

    Each check is wrapped in a try/except so a single failure cannot
    abort the rest. The report records passed/failed/skipped per
    component plus aggregate counters and verdict.
    """
    api_url_resolved = _resolve_api_url(api_url)
    state_root_resolved = _resolve_state_root(state_root)
    supervisor_sock_resolved = _resolve_supervisor_sock(supervisor_sock)
    # project_root is informational; only used to anchor legacy .grace_state hint
    # inside the state_files check.
    report = AfterRestartReport(
        started_at=datetime.now(timezone.utc).isoformat() + "Z",
        config={
            "api_url": api_url_resolved,
            "state_root": str(state_root_resolved),
            "supervisor_sock": (
                str(supervisor_sock_resolved) if supervisor_sock_resolved else None
            ),
            "packet_id": packet_id,
            "timeout_sec": timeout_sec,
            "project_root": str(project_root) if project_root else None,
        },
    )
    _log.info("after_restart_check_started",
              api_url=api_url_resolved,
              state_root=str(state_root_resolved),
              supervisor_sock=str(supervisor_sock_resolved) if supervisor_sock_resolved else None,
              packet_id=packet_id)

    async def _safe(name: str, coro) -> None:
        try:
            result = await coro
            report.components.append(result)
            _log.info("after_restart_check_component",
                      component=name,
                      status=result.status,
                      detail=result.detail[:200])
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            report.components.append(
                ComponentResult(name=name, status="failed",
                                detail=err[:200], error=err[:500])
            )
            report.errors.append(f"{name}: {err}")
            _log.warn("after_restart_check_component",
                      component=name, status="failed", error=err[:200])

    await _safe("api_health", _check_api_health(api_url_resolved, timeout_sec))
    await _safe("state_files", _check_state_files(state_root_resolved))
    await _safe("packet_operations", _check_packet_operations(state_root_resolved, packet_id))
    await _safe("worker_health", _check_worker_health(supervisor_sock_resolved, timeout_sec))

    report.finished_at = datetime.now(timezone.utc).isoformat() + "Z"
    _log.info("after_restart_check_complete",
              summary=report.summary, all_passed=report.all_passed)
    return report

#END_BLOCK_RUNNER


#START_BLOCK_CLI

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grace-after-restart-check",
        description=(
            "Post-restart consistency check for the GRACE control plane. "
            "Returns 0 on all-passed (or all-skipped), 1 on any failure."
        ),
    )
    p.add_argument("--api-url", default=None,
                    help="API URL (default: GRACE_API_URL or settings.api_url)")
    p.add_argument("--state-root", default=None,
                    help="State root directory (default: GRACE_STATE_ROOT or settings.state_root)")
    p.add_argument("--supervisor-sock", default=None,
                    help="Supervisor unix socket (default: GRACE_SUPERVISOR_SOCK; "
                         "if absent the worker_health check is skipped)")
    p.add_argument("--packet-id", default=None,
                    help="Optional packet id to probe (skipped if absent)")
    p.add_argument("--timeout", type=int, default=10,
                    help="Per-check timeout in seconds (default 10)")
    p.add_argument("--project-root", default=None,
                    help="Project root for legacy .grace_state hint (informational)")
    p.add_argument("--json", action="store_true",
                    help="Print full report as JSON instead of human summary")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = asyncio.run(run_after_restart_check(
        project_root=args.project_root,
        api_url=args.api_url,
        state_root=args.state_root,
        supervisor_sock=args.supervisor_sock,
        packet_id=args.packet_id,
        timeout_sec=args.timeout,
    ))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        # Compact human output
        status_marker = "OK" if report.all_passed else "FAIL"
        print(f"[{status_marker}] {report.summary}")
        for c in report.components:
            mark = {
                "passed": "+",
                "failed": "!",
                "skipped": "-",
            }.get(c.status, "?")
            print(f"  {mark} {c.name}: {c.detail}")
    return 0 if report.all_passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

#END_BLOCK_CLI
