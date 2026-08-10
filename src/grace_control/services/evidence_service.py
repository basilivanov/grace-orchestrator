# ############################################################################
# AI_HEADER: evidence_service
# ROLE: Persist acceptance reports + agent logs under state_root.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Save evidence JSON, acceptance reports, and agent logs to the
#          standard run directory layout.
# inputs: packet_id, run_number, payloads, state_root.
# returns: Path strings.
# side_effects: Writes files under state_root/packets/{id}/runs/R{NN}/.
# emitted_logs: agent_log_saved (when applicable).
# error_behavior: Never raises — failures swallowed, caller receives empty path.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: EvidenceService
# END_MODULE_MAP

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import PacketRun

_log = GraceLogger("evidence_service")


class EvidenceService:
    """Owns the per-run evidence directory layout."""

    def __init__(self, db_factory=None):
        # db_factory is injectable so tests can patch the same get_db that
        # the adapter uses; default to the production singleton.
        if db_factory is None:
            from grace_control.db import get_db as _default_get_db
            self._db = _default_get_db
        else:
            self._db = db_factory

    @staticmethod
    def run_dir(packet_id: str, run_number: int, state_root: Path) -> Path:
        return state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"

    def evidence_path(self, packet_id: str, run_number: int, state_root: Path) -> str:
        return str(self.run_dir(packet_id, run_number, state_root))

    def save_acceptance_report(self, packet_id: str, run_number: int, report, state_root: Path) -> str:
        try:
            ev_dir = self.run_dir(packet_id, run_number, state_root)
            ev_dir.mkdir(parents=True, exist_ok=True)
            path = ev_dir / "acceptance_report.json"
            path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
            return str(path)
        except Exception:
            _log.warn("save_acceptance_report_failed", packet_id=packet_id)
            return ""

    def save_agent_log(self, packet_id: str, run_number: int, result, state_root: Path) -> None:
        try:
            log_dir = self.run_dir(packet_id, run_number, state_root)
            log_dir.mkdir(parents=True, exist_ok=True)
            agent_log = log_dir / "agent_output.log"

            mr = getattr(result, "managed_runner_result", None)
            if isinstance(mr, dict):
                agent = mr.get("agent_result", {})
                if isinstance(agent, dict):
                    for key in ("stdout_path", "stderr_path"):
                        path = agent.get(key, "")
                        if path:
                            p = Path(path)
                            if p.exists():
                                content = p.read_text()
                                with agent_log.open("a") as f:
                                    f.write(f"=== {key} ===\n{content}\n")
                    for key in ("stdout", "stderr"):
                        content = agent.get(key, "")
                        if content:
                            with agent_log.open("a") as f:
                                f.write(f"=== AGENT {key.upper()} ===\n{content}\n")

            if agent_log.exists() and agent_log.stat().st_size > 0:
                _log.info("agent_log_saved", packet_id=packet_id, path=str(agent_log),
                    size=agent_log.stat().st_size)
        except Exception:
            pass

    def update_run_result(
        self,
        *,
        run_id: str,
        status: str,
        legacy_result: dict,
        acceptance_report,
        evidence_verifier_report,
        reviewer_report,
        evidence_path: str,
        duration_ms: int,
        executor_id: str = "",
        commit_sha: str = "",
        model: str = "",
        command_preview: list | None = None,
        prompt: str = "",
        dev_replay: dict | None = None,
        diagnostics: dict | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        base_sha: str | None = None,
        integration_base_sha: str | None = None,
        parallel_execution: dict | None = None,
    ) -> None:
        try:
            with self._db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = status
                    accept_dict = (
                        acceptance_report.to_dict()
                        if acceptance_report
                        else {"error": "acceptance pipeline failed"}
                    )
                    previous_result = existing.result_json if isinstance(existing.result_json, dict) else {}
                    res_json = {
                        "legacy_result": legacy_result,
                        "acceptance_report": accept_dict,
                        "evidence_verifier_report": (
                            evidence_verifier_report.model_dump()
                            if hasattr(evidence_verifier_report, "model_dump")
                            else (evidence_verifier_report if isinstance(evidence_verifier_report, dict) else {})
                        ),
                        "reviewer_report": (
                            reviewer_report.model_dump()
                            if hasattr(reviewer_report, "model_dump")
                            else (reviewer_report if isinstance(reviewer_report, dict) else {})
                        ),
                        "agent_commit_sha": commit_sha,
                    }
                    previous_parallel = previous_result.get("parallel_execution")
                    if isinstance(previous_parallel, dict):
                        res_json["parallel_execution"] = dict(previous_parallel)
                    if isinstance(parallel_execution, dict):
                        res_json["parallel_execution"] = dict(parallel_execution)
                    if dev_replay:
                        res_json["dev_replay"] = dev_replay
                    # TZ §6.6: top-level diagnostics surface for UI/admin
                    # to consume without traversing legacy_result.evidence.
                    if diagnostics:
                        res_json["diagnostics"] = dict(diagnostics)
                    existing.result_json = res_json
                    if base_sha is not None:
                        existing.base_sha = base_sha
                    if integration_base_sha is not None:
                        existing.integration_base_sha = integration_base_sha
                    existing.evidence_path = evidence_path
                    existing.finished_at = datetime.now(timezone.utc)
                    existing.duration_ms = duration_ms
                    existing.executor_id = executor_id
                    if model:
                        existing.model = model
                    if command_preview is not None:
                        existing.command_preview = list(command_preview)
                    if prompt:
                        existing.prompt = prompt
                    if tokens_in is not None:
                        existing.tokens_in = tokens_in
                    if tokens_out is not None:
                        existing.tokens_out = tokens_out
                    if cost_usd is not None:
                        existing.cost_usd = cost_usd
                    self._log_rejection(status, accept_dict)
        except Exception:
            _log.warn("update_run_result_failed", run_id=run_id, status=status)

    @staticmethod
    def _log_rejection(status: str, accept_dict: dict) -> None:
        if status != "accepted" and accept_dict:
            stages = [s.get("name", "?") for s in accept_dict.get("stages", [])]
            _log.info("execution_rejected",
                verdict=accept_dict.get("final_verdict", "?"),
                summary=accept_dict.get("summary", "")[:200],
                stages=stages,
                evidence_issues=accept_dict.get("evidence_issues", []),
                scope_violations=accept_dict.get("scope_violations", []),
            )
