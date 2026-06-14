from __future__ import annotations

import os
import pwd
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from grace_control.core.runtime_artifacts import RuntimeArtifactStore
from grace_control.core.runtime_trace import RuntimeTraceContext


class AgentRuntimeFailureCode:
    AGENT_ENV_BAD_USER = "AGENT_ENV_BAD_USER"
    AGENT_ENV_BAD_HOME = "AGENT_ENV_BAD_HOME"
    AGENT_ENV_BAD_CWD = "AGENT_ENV_BAD_CWD"
    AGENT_ENV_BAD_GIT_ROOT = "AGENT_ENV_BAD_GIT_ROOT"
    AGENT_ENV_MISSING_AUTH = "AGENT_ENV_MISSING_AUTH"
    AGENT_ENV_MISSING_CONFIG = "AGENT_ENV_MISSING_CONFIG"
    AGENT_MODEL_UNAVAILABLE = "AGENT_MODEL_UNAVAILABLE"
    AGENT_WORKTREE_INVALID = "AGENT_WORKTREE_INVALID"
    AGENT_WORKTREE_DIRTY_BEFORE_RUN = "AGENT_WORKTREE_DIRTY_BEFORE_RUN"
    AGENT_SCOPE_PARENT_NOT_CREATABLE = "AGENT_SCOPE_PARENT_NOT_CREATABLE"
    AGENT_ARTIFACT_DIR_NOT_WRITABLE = "AGENT_ARTIFACT_DIR_NOT_WRITABLE"
    AGENT_RUNTIME_CONTRACT_INVALID = "AGENT_RUNTIME_CONTRACT_INVALID"
    AGENT_SCOPE_PATH_INVALID = "AGENT_SCOPE_PATH_INVALID"
    AGENT_FROZEN_SCOPE_OVERLAP = "AGENT_FROZEN_SCOPE_OVERLAP"
    AGENT_TARGET_REPO_NOT_FOUND = "AGENT_TARGET_REPO_NOT_FOUND"
    AGENT_ORCHESTRATOR_REPO_NOT_FOUND = "AGENT_ORCHESTRATOR_REPO_NOT_FOUND"
    AGENT_NO_EVENT_OUTPUT = "AGENT_NO_EVENT_OUTPUT"
    AGENT_OUTPUT_PARSE_FAILED = "AGENT_OUTPUT_PARSE_FAILED"
    AGENT_PROCESS_CRASHED = "AGENT_PROCESS_CRASHED"
    AGENT_COMMAND_TIMEOUT = "AGENT_COMMAND_TIMEOUT"
    AGENT_PERMISSION_BLOCKED = "AGENT_PERMISSION_BLOCKED"
    AGENT_OPENCODE_SERVER_NOT_RUNNING = "AGENT_OPENCODE_SERVER_NOT_RUNNING"
    AGENT_OPENCODE_SERVER_UNHEALTHY = "AGENT_OPENCODE_SERVER_UNHEALTHY"
    AGENT_OPENCODE_SERVER_START_FAILED = "AGENT_OPENCODE_SERVER_START_FAILED"
    AGENT_OPENCODE_SERVER_TIMEOUT = "AGENT_OPENCODE_SERVER_TIMEOUT"
    AGENT_OPENCODE_ATTACH_FAILED = "AGENT_OPENCODE_ATTACH_FAILED"
    AGENT_CHANGED_OUT_OF_SCOPE = "AGENT_CHANGED_OUT_OF_SCOPE"
    AGENT_TOUCHED_FROZEN_SCOPE = "AGENT_TOUCHED_FROZEN_SCOPE"
    AGENT_SCOPE_ENFORCEMENT_FAILED = "AGENT_SCOPE_ENFORCEMENT_FAILED"
    AGENT_DIFF_INSPECTION_FAILED = "AGENT_DIFF_INSPECTION_FAILED"
    AGENT_NO_CHANGES_PRODUCED = "AGENT_NO_CHANGES_PRODUCED"


class AgentRuntimeContract(BaseModel):
    runtime_run_id: str
    feature_id: str | None = None
    wave_id: str | None = None
    packet_id: str
    role: str
    adapter: str = "opencode"
    target_repo_root: str
    orchestrator_repo_root: str
    worktree_root: str
    cwd: str
    linux_user: str | None = None
    home: str | None = None
    shell: str = "/bin/sh"
    executor_id: str | None = None
    agent_name: str | None = None
    provider: str | None = None
    model: str | None = None
    packet_scope: list[str] = []
    frozen_scope: list[str] = []
    acceptance_profile: str | None = None
    runtime_artifacts_dir: str
    events_jsonl_path: str | None = None
    timeout_seconds: int = 1800
    created_at: datetime | None = None


class AgentRuntimeContractBuilder:

    @staticmethod
    def build(
        packet_data: dict[str, Any],
        executor: dict[str, Any],
        run_id: str,
        trace: RuntimeTraceContext,
        project_root: Path,
        target_repo_root: str,
        worktree_path: Path,
        settings: Any,
    ) -> AgentRuntimeContract:
        spec = packet_data.get("spec_json") or {}
        if isinstance(spec, str):
            spec = {}

        try:
            linux_user = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            linux_user = None

        home = os.environ.get("HOME", None)

        cwd = str(worktree_path)
        artifacts_dir = str(
            RuntimeArtifactStore().packet_dir(
                packet_data.get("feature_id", "") or "",
                packet_data.get("id", ""),
            )
        )

        return AgentRuntimeContract(
            runtime_run_id=run_id,
            feature_id=packet_data.get("feature_id", ""),
            wave_id=packet_data.get("wave_id", ""),
            packet_id=packet_data.get("id", ""),
            role=executor.get("role", "coder"),
            adapter=executor.get("adapter", "opencode"),
            target_repo_root=target_repo_root or str(project_root),
            orchestrator_repo_root=str(project_root),
            worktree_root=str(worktree_path),
            cwd=cwd,
            linux_user=linux_user,
            home=home,
            shell=os.environ.get("SHELL", "/bin/sh"),
            executor_id=executor.get("executor_id", ""),
            agent_name=executor.get("agent_name", ""),
            provider=executor.get("provider", ""),
            model=executor.get("model", ""),
            packet_scope=spec.get("scope", []) if isinstance(spec, dict) else [],
            frozen_scope=executor.get("frozen_scope", []),
            acceptance_profile=packet_data.get("acceptance_profile", ""),
            runtime_artifacts_dir=artifacts_dir,
            events_jsonl_path=None,
            timeout_seconds=getattr(settings, "agent_timeout_seconds", 1800),
            created_at=datetime.now(timezone.utc),
        )
