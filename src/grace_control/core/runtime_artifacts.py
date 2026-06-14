# ############################################################################
# AI_HEADER: runtime_artifacts
# ROLE: RuntimeArtifactRef, RuntimeArtifactStore — persist artifacts with sha256/size
# ############################################################################

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from grace_control.config.settings import settings
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_artifact_store")

_DEFAULT_ARTIFACTS_ROOT = ".grace/runs"


class RuntimeArtifactRef(BaseModel):
    kind: str
    path: str
    sha256: str
    size_bytes: int
    preview: str | None = None


class RuntimeArtifactStore:

    def __init__(self, root: Path | None = None):
        self._root = root or Path(
            settings.runtime_artifacts_root if hasattr(settings, "runtime_artifacts_root") else _DEFAULT_ARTIFACTS_ROOT
        )

    def feature_dir(self, feature_id: str) -> Path:
        return self._root / feature_id

    def packet_dir(self, feature_id: str, packet_id: str) -> Path:
        return self._root / feature_id / "packets" / packet_id

    def write_text(
        self,
        *,
        trace: RuntimeTraceContext,
        stage: str,
        name: str,
        content: str,
        kind: str,
    ) -> RuntimeArtifactRef:
        feature_id = trace.feature_id or "unknown"
        stage_dir = self.feature_dir(feature_id) / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / name
        path.write_text(content, encoding="utf-8")
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        size_bytes = len(content.encode("utf-8"))
        preview = content[:settings.runtime_debug_max_preview_chars] if self._preview_enabled() else None
        ref = RuntimeArtifactRef(
            kind=kind,
            path=str(path.relative_to(self._root.parent) if path.is_relative_to(self._root.parent) else path),
            sha256=sha256,
            size_bytes=size_bytes,
            preview=preview,
        )
        _log.debug("artifact_written", kind=kind, path=str(path), sha256=sha256[:12], size_bytes=size_bytes)
        return ref

    def write_json(
        self,
        *,
        trace: RuntimeTraceContext,
        stage: str,
        name: str,
        payload: Any,
        kind: str,
    ) -> RuntimeArtifactRef:
        content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return self.write_text(
            trace=trace,
            stage=stage,
            name=name,
            content=content,
            kind=kind,
        )

    def append_jsonl(
        self,
        *,
        trace: RuntimeTraceContext,
        stage: str,
        name: str,
        payload: dict,
        kind: str = "events",
    ) -> RuntimeArtifactRef:
        feature_id = trace.feature_id or "unknown"
        stage_dir = self.feature_dir(feature_id) / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / name
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with open(str(path), "a", encoding="utf-8") as f:
            f.write(line)
        existing = path.read_text(encoding="utf-8")
        sha256 = hashlib.sha256(existing.encode("utf-8")).hexdigest()
        size_bytes = len(existing.encode("utf-8"))
        preview = existing[:settings.runtime_debug_max_preview_chars] if self._preview_enabled() else None
        ref = RuntimeArtifactRef(
            kind=kind,
            path=str(path.relative_to(self._root.parent) if path.is_relative_to(self._root.parent) else path),
            sha256=sha256,
            size_bytes=size_bytes,
            preview=preview,
        )
        return ref

    def _preview_enabled(self) -> bool:
        return getattr(settings, "runtime_debug_payload_capture_enabled", True)
