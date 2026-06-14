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


def _safe_part(value: str, field: str) -> str:
    if not value or "/" in value or "\\" in value or value in {".", ".."} or ".." in Path(value).parts:
        raise ValueError(f"unsafe artifact path component: {field}={value!r}")
    return value


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
        safe = _safe_part(feature_id, "feature_id")
        return self._root / safe

    def packet_dir(self, feature_id: str, packet_id: str) -> Path:
        sf = _safe_part(feature_id, "feature_id")
        sp = _safe_part(packet_id, "packet_id")
        return self._root / sf / "packets" / sp

    def write_text(
        self,
        *,
        trace: RuntimeTraceContext,
        stage: str,
        name: str,
        content: str,
        kind: str,
    ) -> RuntimeArtifactRef:
        feature_id = _safe_part(trace.feature_id or "unknown", "feature_id")
        safe_stage = _safe_part(stage, "stage")
        safe_name = _safe_part(name, "name")
        stage_dir = self.feature_dir(feature_id) / safe_stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / safe_name
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

    def write_packet_text(
        self,
        *,
        trace: RuntimeTraceContext,
        packet_id: str,
        name: str,
        content: str,
        kind: str,
    ) -> RuntimeArtifactRef:
        feature_id = _safe_part(trace.feature_id or "unknown", "feature_id")
        _safe_part(packet_id, "packet_id")
        safe_name = _safe_part(name, "name")
        pkt_dir = self.packet_dir(feature_id, packet_id)
        pkt_dir.mkdir(parents=True, exist_ok=True)
        path = pkt_dir / safe_name
        path.write_text(content, encoding="utf-8")
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        size_bytes = len(content.encode("utf-8"))
        preview = content[:settings.runtime_debug_max_preview_chars] if self._preview_enabled() else None
        rel = path.relative_to(self._root.parent) if path.is_relative_to(self._root.parent) else path
        ref = RuntimeArtifactRef(
            kind=kind,
            path=str(rel),
            sha256=sha256,
            size_bytes=size_bytes,
            preview=preview,
        )
        _log.debug("artifact_written", kind=kind, path=str(path), sha256=sha256[:12], size_bytes=size_bytes)
        return ref

    def write_packet_json(
        self,
        *,
        trace: RuntimeTraceContext,
        packet_id: str,
        name: str,
        payload: Any,
        kind: str,
    ) -> RuntimeArtifactRef:
        content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return self.write_packet_text(
            trace=trace,
            packet_id=packet_id,
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
        feature_id = _safe_part(trace.feature_id or "unknown", "feature_id")
        safe_stage = _safe_part(stage, "stage")
        safe_name = _safe_part(name, "name")
        stage_dir = self.feature_dir(feature_id) / safe_stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / safe_name
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
