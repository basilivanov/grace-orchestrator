# ############################################################################
# AI_HEADER: artifact_manifest
# ROLE: Generate and validate artifacts-manifest.json for frontend acceptance.
#       TZ_FRONTEND_ACCEPTANCE P3 — single source of truth for browser artifacts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Produce a standardized manifest of all frontend artifacts per run.
#          Used by evidence checker, admin UI, and trace service.
# inputs: run_dir (Path), packet_id (str), run_id (str), stage_info (dict).
# returns: Path to manifest, or None.
# side_effects: Writes artifacts-manifest.json to run_dir/browser/.
# emitted_logs: manifest_written, manifest_validation_failed.
# error_behavior: Returns None on write failure; validation returns error list.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: write_artifact_manifest
#   - function: validate_artifact_manifest
#   - function: build_manifest_entry
# END_MODULE_MAP

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("artifact_manifest")

_MANIFEST_FILENAME = "artifacts-manifest.json"


@dataclass
class ManifestEntry:
    """Single artifact entry in the manifest."""
    kind: str = ""           # screenshot, trace, console_log, network_log, visual_diff, a11y_report, dom_snapshot
    path: str = ""           # relative path from browser_dir
    size: int = 0
    viewport: str = ""
    stage: str = ""
    status: str = "unknown"  # pass, fail, unknown
    metadata: dict = field(default_factory=dict)  # diff_pct, max_diff_pct, critical_count, violations_count


def write_artifact_manifest(
    run_dir: Path,
    *,
    packet_id: str,
    run_id: str,
    entries_in: list[ManifestEntry] | None = None,
) -> Path | None:
    """Write artifacts-manifest.json to run_dir/browser/.

    Collects all artifacts under run_dir/browser/ and builds a manifest.
    Merges with provided entries (from stage results).
    """
    browser_dir = run_dir / "browser"
    if not browser_dir.exists():
        return None

    entries: list[ManifestEntry] = list(entries_in or [])

    # Auto-discover artifacts
    for vp_dir in sorted(browser_dir.iterdir()):
        if not vp_dir.is_dir():
            continue
        vp = vp_dir.name
        for f in sorted(vp_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(browser_dir))
            kind = _classify_artifact(f)
            if kind == "unknown" and f.name == _MANIFEST_FILENAME:
                continue
            entries.append(ManifestEntry(
                kind=kind, path=rel, size=f.stat().st_size,
                viewport=vp, stage=_infer_stage(rel),
                metadata=_extract_metadata(f, kind),
            ))

    manifest = {
        "packet_id": packet_id,
        "run_id": run_id,
        "generated_at": time.time(),
        "total_artifacts": len(entries),
        "entries": [_entry_to_dict(e) for e in entries],
    }

    manifest_path = browser_dir / _MANIFEST_FILENAME
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2))
        _log.info("manifest_written", path=str(manifest_path), entries=len(entries))
        return manifest_path
    except Exception as e:
        _log.error("manifest_write_failed", error=str(e)[:200])
        return None


def validate_artifact_manifest(run_dir: Path) -> list[str]:
    """Check manifest entries correspond to real files. Returns errors."""
    manifest_path = run_dir / "browser" / _MANIFEST_FILENAME
    if not manifest_path.exists():
        return ["artifacts-manifest.json not found"]
    try:
        data = json.loads(manifest_path.read_text())
        errors: list[str] = []
        browser_dir = Path(data.get("browser_dir", str(run_dir / "browser")))
        for entry in data.get("entries", []):
            path = browser_dir / entry["path"]
            if not path.exists():
                errors.append(f"orphan manifest entry: {entry['path']}")
            elif path.stat().st_size != entry.get("size", -1):
                errors.append(f"size mismatch: {entry['path']}")
        missing_files = _find_missing_artifacts(browser_dir, data.get("entries", []))
        errors.extend(missing_files)
        return errors
    except Exception as e:
        return [f"manifest validation error: {str(e)[:200]}"]


# ── helpers ──────────────────────────────────────────────────────────────

def _classify_artifact(f: Path) -> str:
    name = f.name.lower()
    if name.endswith(".png") and "diff" not in name:
        return "screenshot"
    if "trace" in name and name.endswith(".zip"):
        return "trace"
    if "console" in name and (name.endswith(".log") or name.endswith(".txt")):
        return "console_log"
    if "network" in name and (name.endswith(".har") or name.endswith(".json")):
        return "network_log"
    if "diff" in name and name.endswith(".png"):
        return "visual_diff"
    if "diff-report" in name and name.endswith(".json"):
        return "visual_diff"
    if "a11y" in name and name.endswith(".json"):
        return "a11y_report"
    if name.endswith(".html") or "dom" in name or "snapshot" in name:
        return "dom_snapshot"
    return "unknown"


def _infer_stage(rel_path: str) -> str:
    if "a11y" in rel_path.lower():
        return "T2_BROWSER_A11Y"
    if "visual" in rel_path.lower() or "diff" in rel_path.lower():
        return "T3_VISUAL_REGRESSION"
    return "T2_BROWSER_E2E"


def _entry_to_dict(e: ManifestEntry) -> dict:
    d = {"kind": e.kind, "path": e.path, "size": e.size,
         "viewport": e.viewport, "stage": e.stage, "status": e.status}
    if e.metadata:
        d["metadata"] = e.metadata
    return d


def _find_missing_artifacts(browser_dir: Path, entries: list[dict]) -> list[str]:
    manifest_paths = {e["path"] for e in entries}
    missing = []
    for f in browser_dir.rglob("*"):
        if not f.is_file() or f.name == _MANIFEST_FILENAME:
            continue
        rel = str(f.relative_to(browser_dir))
        if rel not in manifest_paths:
            missing.append(f"file not in manifest: {rel}")
    return missing


def _extract_metadata(f: Path, kind: str) -> dict:
    """Parse report files for metadata included in manifest."""
    if kind in ("visual_diff",) and f.name.endswith(".json"):
        try:
            data = json.loads(f.read_text())
            return {"diff_pct": data.get("diff_pct", 0), "max_diff_pct": data.get("max_diff_pct", 0.001)}
        except Exception:
            pass
    if kind == "a11y_report":
        try:
            data = json.loads(f.read_text())
            return {
                "violations_count": data.get("violations_count", 0),
                "critical_count": data.get("critical_count", 0),
                "passed": data.get("passed", False),
            }
        except Exception:
            pass
    return {}
