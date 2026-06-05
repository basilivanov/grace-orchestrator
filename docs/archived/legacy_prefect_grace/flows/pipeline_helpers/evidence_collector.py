# ############################################################################
# AI_HEADER: pipeline_helpers.evidence_collector
# ROLE: Read-only evidence and commit candidate collection helpers.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Collect commit/evidence path candidates from existing feature pipeline payloads without mutating state.
# inputs: Feature, packet, verification, review, wave, and verifier-run dictionaries.
# returns: Normalized candidate file and evidence path lists, or enriched verifier result dictionaries.
# side_effects: Reads state and filesystem metadata; does not write state or files.
# emitted_logs: None.
# error_behavior: Tolerates missing files and malformed optional payloads by returning empty candidates.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: normalize_commit_marker
#   - function: find_commit_marker
#   - function: collect_candidate_commit_files
#   - function: normalize_evidence_path
#   - function: append_evidence_path
#   - function: enrich_verifier_evidence_paths
# END_MODULE_MAP

from __future__ import annotations

import glob
from pathlib import Path
import re

from prefect_grace.tasks.state_store import find_record, load_state

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COMMIT_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_PATH_TOKEN_RE = re.compile(
    r"(?P<path>(?:\.{1,2}/|/)?[A-Za-z0-9_.@+~=-]+(?:/[A-Za-z0-9_.@+~=\-*\[\]{}]+)+"
    r"|[A-Za-z0-9_.@+~=-]+\.(?:py|tsx|ts|js|jsx|md|xml|yaml|yml|json|toml|css|scss|html|png|jpg|jpeg|webp|zip|log|txt|svg|lock))"
)
_COMMIT_MARKER_KEYS = {
    "commit_hash",
    "commit_sha",
    "git_commit",
    "git_commit_hash",
    "git_sha",
    "commit_marker",
    "committed_hash",
}
_CANDIDATE_LIST_KEYS = {
    "allowed_write_scope",
    "artifact_files",
    "artifact_paths",
    "artifacts",
    "candidate_commit_files",
    "changed_files",
    "created_files",
    "deleted_files",
    "evidence_paths",
    "file_paths",
    "files_changed",
    "modified_files",
    "output_files",
    "touched_files",
    "write_scope",
}
_CANDIDATE_PATH_KEYS = {
    "architect_handoff_path",
    "architect_manifest_path",
    "brief_path",
    "development_plan_slice_path",
    "execution_packet_path",
    "knowledge_graph_slice_path",
    "packet_path",
    "requirements_slice_path",
    "review_path",
    "verification_matrix_slice_path",
    "verification_path",
    "wave_plan_path",
}
_VERIFIER_RUN_ARTIFACT_KEYS = ("last_message_path", "stdout_path", "stderr_path")
_COMMON_OBSERVABILITY_EVIDENCE = (
    "logs/feed.jsonl",
    "logs/report.jsonl",
    "test-results/grace-report.json",
)
_MAX_ENRICHED_EVIDENCE_PATHS = 80


# START_FUNCTION_CONTRACT
# name: normalize_commit_marker
# purpose: Extract a stable commit marker string from booleans, strings, sequences, or nested dictionaries.
# inputs:
#   value: Raw commit marker candidate.
# returns: Commit marker string, or empty string when absent.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def normalize_commit_marker(value: object) -> str:
    if isinstance(value, bool):
        return "commit_marker" if value else ""
    if isinstance(value, (list, tuple)):
        for item in value:
            marker = normalize_commit_marker(item)
            if marker:
                return marker
        return ""
    if isinstance(value, dict):
        marker = find_commit_marker(value)
        return marker
    text = " ".join(str(value or "").strip().split())
    if not text or text.lower() in {"false", "none", "null", "n/a", "no"}:
        return ""
    match = _COMMIT_HASH_RE.search(text)
    return match.group(0) if match else text


# START_FUNCTION_CONTRACT
# name: find_commit_marker
# purpose: Find a commit marker in nested payload keys that represent commit hashes or markers.
# inputs:
#   value: Nested dictionary/list payload.
# returns: First detected commit marker string, or empty string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def find_commit_marker(value: object) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            is_commit_key = normalized_key in _COMMIT_MARKER_KEYS or (
                "commit" in normalized_key
                and any(marker in normalized_key for marker in ("hash", "sha", "marker"))
            )
            if is_commit_key:
                marker = normalize_commit_marker(item)
                if marker:
                    return marker
            if isinstance(item, (dict, list, tuple)):
                marker = find_commit_marker(item)
                if marker:
                    return marker
    if isinstance(value, (list, tuple)):
        for item in value:
            marker = find_commit_marker(item)
            if marker:
                return marker
    return ""


# START_FUNCTION_CONTRACT
# name: candidate_file_path
# purpose: Normalize a single raw file candidate into a commit-candidate path.
# inputs:
#   value: Raw path-like value.
# returns: Normalized path string or None.
# side_effects: Resolves absolute paths relative to PROJECT_ROOT when possible.
# emitted_logs: None.
# error_behavior: Returns None for invalid path candidates.
# END_FUNCTION_CONTRACT
def candidate_file_path(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    text = raw.strip("`'\" \t\r\n")
    text = re.sub(r"^\s*[-*]\s+", "", text).strip()
    text = text.rstrip(".,;)")
    if not text or text.lower() in {"-", "none", "n/a", "null"}:
        return None
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "trace_id:", "request_id:", "report_id:", "correlation_id:")):
        return None
    if any(ch.isspace() for ch in text):
        return None
    if "/" not in text and "\\" not in text and not Path(text).suffix:
        return None
    if ":" in text:
        text = re.sub(r"(:\d+)(?::\d+)?$", "", text)
    path = Path(text)
    if path.is_absolute():
        try:
            text = str(path.resolve().relative_to(PROJECT_ROOT))
        except (OSError, ValueError):
            text = str(path)
    elif text.startswith("./"):
        text = text[2:]
    return text


# START_FUNCTION_CONTRACT
# name: path_candidates_from_text
# purpose: Extract unique path candidates from free-form text.
# inputs:
#   value: Raw text.
# returns: Ordered unique normalized path candidates.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def path_candidates_from_text(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    candidates: list[str] = []
    exact = candidate_file_path(text)
    if exact:
        candidates.append(exact)
    for match in _PATH_TOKEN_RE.finditer(text):
        candidate = candidate_file_path(match.group("path"))
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


# START_FUNCTION_CONTRACT
# name: add_candidate_file
# purpose: Add candidate file paths from nested values into a destination list.
# inputs:
#   files: Mutable destination list.
#   value: Raw scalar/list/dict candidate payload.
# returns: None.
# side_effects: Mutates only the provided list.
# emitted_logs: None.
# error_behavior: Skips empty optional values.
# END_FUNCTION_CONTRACT
def add_candidate_file(files: list[str], value: object) -> None:
    if value in (None, "", [], {}):
        return
    if isinstance(value, dict):
        collect_candidate_commit_files_from_payload(value, files)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            add_candidate_file(files, item)
        return
    for candidate in path_candidates_from_text(value):
        if candidate not in files:
            files.append(candidate)


# START_FUNCTION_CONTRACT
# name: collect_candidate_commit_files_from_payload
# purpose: Traverse payload dictionaries/lists and collect known commit-candidate path fields.
# inputs:
#   payload: Nested payload.
#   files: Mutable destination list.
# returns: None.
# side_effects: Mutates only the provided list.
# emitted_logs: None.
# error_behavior: Skips unsupported payload shapes.
# END_FUNCTION_CONTRACT
def collect_candidate_commit_files_from_payload(payload: object, files: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key in _CANDIDATE_LIST_KEYS or normalized_key in _CANDIDATE_PATH_KEYS:
                add_candidate_file(files, value)
            elif isinstance(value, dict):
                collect_candidate_commit_files_from_payload(value, files)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        collect_candidate_commit_files_from_payload(item, files)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                collect_candidate_commit_files_from_payload(item, files)


# START_FUNCTION_CONTRACT
# name: feature_line_records
# purpose: Read current persisted records associated with one feature id.
# inputs:
#   feature_id: Feature identifier.
#   state_root: State root directory path.
# returns: List of matching record dictionaries from known state files.
# side_effects: Reads state store only.
# emitted_logs: None.
# error_behavior: Missing state files yield empty record groups through load_state.
# END_FUNCTION_CONTRACT
def feature_line_records(feature_id: str, *, state_root: Path | str) -> list[dict]:
    records: list[dict] = []
    for state_name, key in (
        ("features", "features"),
        ("packets", "packets"),
        ("verifications", "verifications"),
        ("reviews", "reviews"),
        ("wave_reviews", "wave_reviews"),
    ):
        for item in list(load_state(state_name, state_root=state_root).get(key) or []):
            if str(item.get("feature_id") or "") == feature_id:
                records.append(dict(item))
    return records


# START_FUNCTION_CONTRACT
# name: collect_candidate_commit_files
# purpose: Collect candidate commit file paths from feature, packet, verification, review, wave, and persisted state payloads.
# inputs:
#   feature_id: Feature identifier for read-only state lookup.
#   feature: Feature record payload.
#   packet_results: Packet run result payloads.
#   verification_records: Verification record payloads.
#   review_routes: Reviewer routing payloads.
#   wave_routes: Wave routing payloads.
#   state_root: State root directory path.
# returns: Ordered unique candidate commit file paths.
# side_effects: Reads current state records.
# emitted_logs: None.
# error_behavior: Skips malformed optional payloads.
# END_FUNCTION_CONTRACT
def collect_candidate_commit_files(
    *,
    feature_id: str,
    feature: dict,
    packet_results: dict,
    verification_records: list[dict],
    review_routes: list[dict],
    wave_routes: list[dict],
    state_root: Path | str,
) -> list[str]:
    files: list[str] = []
    collect_candidate_commit_files_from_payload(feature, files)
    collect_candidate_commit_files_from_payload(packet_results, files)
    collect_candidate_commit_files_from_payload(verification_records, files)
    collect_candidate_commit_files_from_payload(review_routes, files)
    collect_candidate_commit_files_from_payload(wave_routes, files)
    for record in feature_line_records(feature_id, state_root=state_root):
        collect_candidate_commit_files_from_payload(record, files)
    return files


# START_FUNCTION_CONTRACT
# name: normalize_evidence_path
# purpose: Normalize an evidence path relative to PROJECT_ROOT when possible.
# inputs:
#   path: Path or string path.
# returns: Relative or absolute normalized path string.
# side_effects: Resolves path metadata.
# emitted_logs: None.
# error_behavior: Returns raw string on resolution errors.
# END_FUNCTION_CONTRACT
def normalize_evidence_path(path: Path | str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    try:
        resolved = candidate.resolve()
    except OSError:
        return raw
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


# START_FUNCTION_CONTRACT
# name: append_evidence_path
# purpose: Append a normalized evidence path to a list once.
# inputs:
#   paths: Mutable destination list.
#   value: Raw path candidate.
# returns: None.
# side_effects: Mutates only the provided list.
# emitted_logs: None.
# error_behavior: Ignores empty values.
# END_FUNCTION_CONTRACT
def append_evidence_path(paths: list[str], value: object) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    candidate = Path(raw)
    if candidate.is_absolute():
        normalized = normalize_evidence_path(candidate)
    elif raw.startswith("./"):
        normalized = raw[2:]
    else:
        normalized = raw
    if normalized and normalized not in paths:
        paths.append(normalized)


# START_FUNCTION_CONTRACT
# name: existing_file_path
# purpose: Return a Path only when a raw value points to an existing file.
# inputs:
#   value: Raw path value.
# returns: Path or None.
# side_effects: Reads filesystem metadata.
# emitted_logs: None.
# error_behavior: Returns None on OS errors.
# END_FUNCTION_CONTRACT
def existing_file_path(value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        if path.is_file():
            return path
    except OSError:
        return None
    return None


# START_FUNCTION_CONTRACT
# name: verifier_packet_for_run
# purpose: Resolve the packet record associated with a verifier run.
# inputs:
#   verifier_run: Verifier run dictionary.
#   state_root: State root directory path.
# returns: Packet record dictionary or empty dictionary.
# side_effects: Reads state store only.
# emitted_logs: None.
# error_behavior: Missing packet records return empty dictionary.
# END_FUNCTION_CONTRACT
def verifier_packet_for_run(verifier_run: dict, *, state_root: Path | str) -> dict:
    packet_id = str(verifier_run.get("packet_id") or "").strip()
    if not packet_id:
        return {}
    try:
        return find_record("packets", "packets", "packet_id", packet_id, state_root=state_root)
    except KeyError:
        return {}


# START_FUNCTION_CONTRACT
# name: artifact_glob_matches
# purpose: Resolve artifact glob patterns to normalized file paths.
# inputs:
#   patterns: Glob patterns.
#   workdir: Base directory for relative globs.
# returns: Ordered normalized artifact file paths.
# side_effects: Reads filesystem metadata.
# emitted_logs: None.
# error_behavior: Skips empty patterns and non-file matches.
# END_FUNCTION_CONTRACT
def artifact_glob_matches(patterns: list[str], *, workdir: Path) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        raw_pattern = str(pattern or "").strip()
        if not raw_pattern:
            continue
        search_pattern = raw_pattern if Path(raw_pattern).is_absolute() else str(workdir / raw_pattern)
        for match in glob.glob(search_pattern, recursive=True):
            path = Path(match)
            if not path.is_file():
                continue
            normalized = normalize_evidence_path(path)
            if normalized and normalized not in matches:
                matches.append(normalized)
            if len(matches) >= _MAX_ENRICHED_EVIDENCE_PATHS:
                return matches
    return matches


# START_FUNCTION_CONTRACT
# name: collect_verifier_supplemental_evidence
# purpose: Collect supplemental verifier artifacts, glob matches, and common observability evidence paths.
# inputs:
#   verifier_run: Verifier run dictionary.
#   verifier_result: Parsed verifier result dictionary.
#   state_root: State root directory path.
# returns: Ordered evidence path list capped at the existing pipeline limit.
# side_effects: Reads state store and filesystem metadata.
# emitted_logs: None.
# error_behavior: Skips missing optional artifacts.
# END_FUNCTION_CONTRACT
def collect_verifier_supplemental_evidence(verifier_run: dict, verifier_result: dict, *, state_root: Path | str) -> list[str]:
    evidence: list[str] = []
    packet = verifier_packet_for_run(verifier_run, state_root=state_root)
    execution_hints = dict(packet.get("execution_hints") or {})
    workdir = Path(str(execution_hints.get("workdir") or PROJECT_ROOT))
    if not workdir.is_absolute():
        workdir = PROJECT_ROOT / workdir

    for key in _VERIFIER_RUN_ARTIFACT_KEYS:
        path = existing_file_path(verifier_run.get(key))
        if path is not None:
            append_evidence_path(evidence, path)

    for attempt in list(verifier_run.get("attempts") or []):
        if not isinstance(attempt, dict):
            continue
        for key in _VERIFIER_RUN_ARTIFACT_KEYS:
            path = existing_file_path(attempt.get(key))
            if path is not None:
                append_evidence_path(evidence, path)

    artifact_globs = [str(item).strip() for item in list(execution_hints.get("artifact_globs") or []) if str(item).strip()]
    for path in artifact_glob_matches(artifact_globs, workdir=workdir):
        append_evidence_path(evidence, path)

    commands_run = [str(item) for item in list(verifier_result.get("commands_run") or [])]
    if any("tools/post_test_review.py" in command or "gracectl.cli evidence review" in command for command in commands_run):
        for candidate in _COMMON_OBSERVABILITY_EVIDENCE:
            path = workdir / candidate
            if path.is_file():
                append_evidence_path(evidence, path)

    return evidence[:_MAX_ENRICHED_EVIDENCE_PATHS]


# START_FUNCTION_CONTRACT
# name: enrich_verifier_evidence_paths
# purpose: Add supplemental run artifacts and expected observability evidence paths to agent verifier results.
# inputs:
#   verifier_run: Verifier packet run payload.
#   verifier_result: Parsed verifier result payload.
#   state_root: State root directory path.
# returns: Original or enriched verifier result dictionary.
# side_effects: Reads filesystem metadata and packet state.
# emitted_logs: None.
# error_behavior: Skips missing optional evidence.
# END_FUNCTION_CONTRACT
def enrich_verifier_evidence_paths(verifier_run: dict, verifier_result: dict, *, state_root: Path | str) -> dict:
    if str(verifier_result.get("source") or "") != "agent_output":
        return verifier_result
    evidence_paths = [str(item).strip() for item in list(verifier_result.get("evidence_paths") or []) if str(item).strip()]
    for path in collect_verifier_supplemental_evidence(verifier_run, verifier_result, state_root=state_root):
        append_evidence_path(evidence_paths, path)
    if evidence_paths == list(verifier_result.get("evidence_paths") or []):
        return verifier_result
    return {
        **verifier_result,
        "evidence_paths": evidence_paths,
        "source": "agent_output_enriched",
    }


_normalize_commit_marker = normalize_commit_marker
_find_commit_marker = find_commit_marker
_candidate_file_path = candidate_file_path
_path_candidates_from_text = path_candidates_from_text
_add_candidate_file = add_candidate_file
_collect_candidate_commit_files_from_payload = collect_candidate_commit_files_from_payload
_feature_line_records = feature_line_records
_collect_candidate_commit_files = collect_candidate_commit_files
_normalize_evidence_path = normalize_evidence_path
_append_evidence_path = append_evidence_path
_existing_file_path = existing_file_path
_verifier_packet_for_run = verifier_packet_for_run
_artifact_glob_matches = artifact_glob_matches
_collect_verifier_supplemental_evidence = collect_verifier_supplemental_evidence
_enrich_verifier_evidence_paths = enrich_verifier_evidence_paths
