# ############################################################################
# AI_HEADER: admin_artifact_read_service — evidence and artifact reads
# ROLE: Owns packet-run evidence DTOs, bounded artifact metadata and safe file
#       reads for the admin facade. Physical paths are accepted only as server
#       resolved evidence roots and relative client paths go through the
#       existing SafeFilesystemService boundary.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build evidence, artifact and packet-run read DTOs for admin APIs.
# inputs: SQLAlchemy Session, packet/run selectors and evidence-relative paths.
# returns: Existing admin dictionaries, binary tuples or None on misses.
# side_effects: Reads bounded local evidence files and ORM result JSON only.
# emitted_logs: SafeFilesystemService emits filesystem read events.
# error_behavior: Missing runs, unsafe paths and unreadable files return None
#                 or an empty DTO according to the existing facade contract.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminArtifactReadService
#     methods:
#       - get_packet_run
#       - get_packet_evidence
#       - get_packet_artifacts
#       - get_artifact_file
#       - get_artifact_preview
# END_MODULE_MAP

from __future__ import annotations

import base64
import mimetypes
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketRun
from grace_control.services.safe_filesystem_service import (
    FilesystemReadError,
    SafeFilesystemService,
)

_log = GraceLogger("admin_artifact_read")


# START_BLOCK_HELPERS
def _classify_artifact(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
        return "image"
    if ext in (".log", ".txt", ".md"):
        return "log"
    if ext == ".json":
        return "json"
    if ext == ".har":
        return "har"
    return "file"


def _build_artifact_tree(
    evidence_dir: Path,
    max_files: int = 2000,
) -> tuple[list[dict[str, Any]], bool]:
    """Build a bounded nested metadata tree without reading file contents."""
    if not evidence_dir.exists():
        return [], False
    nodes: dict[str, dict[str, Any]] = {}

    def _ensure_dir(relative: str) -> dict[str, Any]:
        if relative == "":
            return nodes.setdefault("", {"name": "", "type": "dir", "size": 0, "children": []})
        if relative in nodes:
            return nodes[relative]
        parent_relative = str(Path(relative).parent)
        if parent_relative == ".":
            parent_relative = ""
        parent_node = _ensure_dir(parent_relative)
        node = {"name": Path(relative).name, "type": "dir", "size": 0, "children": []}
        parent_node["children"].append(node)
        nodes[relative] = node
        return node

    file_count = 0
    truncated = False
    for candidate in evidence_dir.rglob("*"):
        if not candidate.is_file():
            continue
        file_count += 1
        if file_count > max_files:
            truncated = True
            break
        relative = candidate.relative_to(evidence_dir)
        relative_string = str(relative)
        parent_relative = str(relative.parent)
        if parent_relative == ".":
            parent_relative = ""
        parent = _ensure_dir(parent_relative)
        node = {
            "name": candidate.name,
            "type": "file",
            "size": candidate.stat().st_size,
            "kind": _classify_artifact(candidate.name),
            "relative_path": relative_string,
            "mtime": candidate.stat().st_mtime,
            "mime": mimetypes.guess_type(candidate.name)[0] or "application/octet-stream",
            "preview_capable": True,
        }
        parent["children"].append(node)
    return (nodes[""]["children"] if "" in nodes else []), truncated


# END_BLOCK_HELPERS


# START_BLOCK_SERVICE
class AdminArtifactReadService:
    """Read-only owner for packet-run evidence and artifact DTOs."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the artifact reader with the facade's canonical run
    #          selector resolver.
    # inputs: run_resolver — callable resolving a packet/run selector.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises during configuration.
    # END_FUNCTION_CONTRACT
    def __init__(self, run_resolver: Callable[..., PacketRun | None]) -> None:
        self._run_resolver = run_resolver

    # START_FUNCTION_CONTRACT
    # name: get_packet_run
    # purpose: Return one run plus persisted result, prompt, command and a
    #          bounded legacy artifact summary.
    # inputs: db, packet_id and run_id selector.
    # returns: Existing packet-run DTO or None when the run is missing.
    # side_effects: Reads run metadata and evidence directory metadata.
    # emitted_logs: None.
    # error_behavior: Unknown selectors return None; inaccessible evidence is
    #                 represented by an empty summary.
    # END_FUNCTION_CONTRACT
    def get_packet_run(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
    ) -> dict[str, Any] | None:
        run = self._run_resolver(db, packet_id, run_id)
        if not run:
            return None
        evidence_path = Path(run.evidence_path) if run.evidence_path else None
        artifacts_summary: dict[str, Any] = {
            "total_files": 0,
            "total_size": 0,
            "files": [],
            "truncated": False,
        }
        if evidence_path and evidence_path.exists():
            files: list[dict[str, Any]] = []
            total = 0
            for index, candidate in enumerate(evidence_path.rglob("*")):
                if candidate.is_file():
                    if index >= 2000:
                        artifacts_summary["truncated"] = True
                        break
                    relative = str(candidate.relative_to(evidence_path))
                    size = candidate.stat().st_size
                    total += size
                    files.append({
                        "name": relative,
                        "type": _classify_artifact(candidate.name),
                        "size": size,
                    })
            artifacts_summary.update({
                "total_files": len(files),
                "total_size": total,
                "files": files,
            })
        return {
            "run": {
                "run_id": run.id,
                "run_number": run.run_number,
                "packet_id": run.packet_id,
                "worker_id": run.worker_id or "",
                "executor_id": run.executor_id or "",
                "model": run.model or "",
                "status": run.status,
                "duration_ms": run.duration_ms or 0,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "evidence_path": run.evidence_path or "",
                "tokens_in": run.tokens_in,
                "tokens_out": run.tokens_out,
                "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "base_sha": run.base_sha,
                "integration_base_sha": run.integration_base_sha,
            },
            "result_json": run.result_json or {},
            "command_preview": list(run.command_preview or []),
            "model": run.model or "",
            "prompt": run.prompt or "",
            "evidence_path": run.evidence_path or "",
            "artifacts_summary": artifacts_summary,
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_evidence
    # purpose: Project the selected run's acceptance report into the stable
    #          T0/T1/T2 evidence DTO.
    # inputs: db, packet_id and optional run selector.
    # returns: Evidence dictionary with verdict, summary and bounded stages.
    # side_effects: Reads persisted run result JSON only.
    # emitted_logs: None.
    # error_behavior: Missing runs return an empty evidence DTO.
    # END_FUNCTION_CONTRACT
    def get_packet_evidence(
        self,
        db: Session,
        packet_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if run_id is None:
            run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet_id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
        else:
            run = self._run_resolver(db, packet_id, run_id)
        if not run:
            return {"verdict": "", "summary": "", "stages": [], "screenshots": []}
        acceptance = (run.result_json or {}).get("acceptance_report", {}) or {}
        stages: list[dict[str, Any]] = []
        for stage in acceptance.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            commands = [
                command
                for command in (stage.get("commands", []) or [])
                if isinstance(command, dict)
            ][:100]
            failed_commands = [
                command
                for command in commands
                if (command.get("exit_code") or 0) != 0 or command.get("timed_out")
            ]
            stages.append({
                "name": stage.get("name", ""),
                "status": stage.get("status", ""),
                "summary": stage.get("summary", ""),
                "blocking_issues": stage.get("blocking_issues", []) or [],
                "commands": commands,
                "failed_commands": failed_commands,
                "commands_summary": {
                    "passed": len(commands) - len(failed_commands),
                    "failed": len(failed_commands),
                    "total": len(commands),
                },
                "exit_codes": [
                    command.get("exit_code")
                    for command in commands
                    if command.get("exit_code") is not None
                ],
                "stdout_tail": str(stage.get("stdout_tail") or stage.get("stdout") or "")[-32768:],
                "stderr_tail": str(stage.get("stderr_tail") or stage.get("stderr") or "")[-32768:],
                "screenshots": list(stage.get("screenshots") or [])[:100],
                "visual": stage.get("visual") if isinstance(stage.get("visual"), dict) else {},
                "browser": stage.get("browser") if isinstance(stage.get("browser"), dict) else {},
            })
        return {
            "verdict": acceptance.get("final_verdict", ""),
            "summary": acceptance.get("summary", ""),
            "stages": stages,
            "screenshots": [],
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_artifacts
    # purpose: Build the bounded nested artifact metadata tree for one run.
    # inputs: db, packet_id and run_id selector.
    # returns: Existing tree/evidence_path/truncated DTO.
    # side_effects: Reads evidence directory metadata without file contents.
    # emitted_logs: None.
    # error_behavior: Missing run/evidence returns an empty tree.
    # END_FUNCTION_CONTRACT
    def get_packet_artifacts(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        run = self._run_resolver(db, packet_id, run_id)
        if not run or not run.evidence_path:
            return {"tree": [], "evidence_path": ""}
        evidence_dir = Path(run.evidence_path)
        tree, truncated = _build_artifact_tree(evidence_dir)
        return {
            "tree": tree,
            "evidence_path": run.evidence_path,
            "truncated": truncated,
        }

    # START_FUNCTION_CONTRACT
    # name: get_artifact_file
    # purpose: Read a complete or tail-bounded artifact through the existing
    #          safe evidence-root filesystem boundary.
    # inputs: db, packet_id, run_id, relative path and optional tail line count.
    # returns: (bytes, mime) tuple or None when unavailable/unsafe.
    # side_effects: Reads a bounded local artifact file.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: SafeFilesystemService errors return None.
    # END_FUNCTION_CONTRACT
    def get_artifact_file(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        path: str,
        tail: int = 0,
    ) -> tuple[bytes, str] | None:
        run = self._run_resolver(db, packet_id, run_id)
        if not run or not run.evidence_path:
            return None
        evidence_dir = Path(run.evidence_path).resolve()
        try:
            reader = SafeFilesystemService(
                {"evidence": evidence_dir},
                max_preview_bytes=1024 * 1024,
                max_tail_lines=10000,
                max_tail_bytes=1024 * 1024,
            )
            payload = (
                reader.tail_file("evidence", path, lines=tail)
                if tail > 0
                else reader.read_file("evidence", path)
            )
        except (FilesystemReadError, OSError, ValueError):
            return None
        content_type = str(payload.get("mime") or "application/octet-stream")
        if payload.get("binary"):
            content = base64.b64decode(payload.get("content_base64") or "")
        else:
            content = str(payload.get("content") or "").encode("utf-8")
        return content, content_type

    # START_FUNCTION_CONTRACT
    # name: get_artifact_preview
    # purpose: Return a bounded JSON-safe preview for one evidence-relative
    #          artifact path, including binary and truncation metadata.
    # inputs: db, packet_id, run_id, relative path and max_bytes.
    # returns: SafeFilesystemService preview DTO without its physical root,
    #          or None when unavailable/unsafe.
    # side_effects: Reads at most the requested bounded artifact prefix.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: Unsafe/missing paths return None.
    # END_FUNCTION_CONTRACT
    def get_artifact_preview(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        path: str,
        max_bytes: int = 512 * 1024,
    ) -> dict[str, Any] | None:
        run = self._run_resolver(db, packet_id, run_id)
        if not run or not run.evidence_path:
            return None
        evidence_dir = Path(run.evidence_path).resolve()
        try:
            reader = SafeFilesystemService(
                {"evidence": evidence_dir},
                max_preview_bytes=min(max(int(max_bytes), 1), 512 * 1024),
                max_tail_lines=10000,
                max_tail_bytes=min(max(int(max_bytes), 1), 512 * 1024),
            )
            payload = reader.read_file("evidence", path, max_bytes=max_bytes)
        except (FilesystemReadError, OSError, ValueError):
            return None
        return {key: value for key, value in payload.items() if key not in {"root"}}


# END_BLOCK_SERVICE


# START_BLOCK_COMPATIBILITY
def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat().replace("+00:00", "Z")


# END_BLOCK_COMPATIBILITY
