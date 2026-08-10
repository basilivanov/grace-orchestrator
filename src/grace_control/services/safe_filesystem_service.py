# ############################################################################
# AI_HEADER: safe_filesystem_service — bounded project-local file reads
# ROLE: Owns the project runtime's allow-listed filesystem read surface. API
#       routers pass named roots and relative paths; this service enforces
#       containment, secret denial and bounded text/binary handling.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Read metadata, bounded previews and bounded tails from explicit
#          server-resolved GRACE operational roots.
# inputs: Named root identifiers, relative paths and bounded read parameters.
# returns: JSON-safe metadata/content dictionaries or typed read errors.
# side_effects: Reads local files under configured operational roots only.
# emitted_logs: filesystem_read_rejected, filesystem_read_done.
# error_behavior: Raises FilesystemReadError with an HTTP-safe code/status for
#                 invalid roots, unsafe paths, missing files and read limits.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: FilesystemReadError
#     methods:
#       - to_dict
#   - class: SafeFilesystemService
#     methods:
#       - from_runtime
#       - list_roots
#       - list_entries
#       - stat
#       - read_file
#       - tail_file
# END_MODULE_MAP

from __future__ import annotations

import base64
import heapq
import mimetypes
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("safe_filesystem")


# START_BLOCK_ERRORS
class FilesystemReadError(ValueError):
    """Typed, non-secret error raised by the safe filesystem boundary."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Build an error with a stable machine code and HTTP status.
    # inputs: code (str), status_code (int), detail (str).
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Stores only the bounded safe detail text.
    # END_FUNCTION_CONTRACT
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail[:240]
        super().__init__(self.detail)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Return the stable JSON error DTO for an API response.
    # inputs: None.
    # returns: Dict with code and message.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.detail}


# END_BLOCK_ERRORS


# START_BLOCK_ROOTS
@dataclass(frozen=True, slots=True)
class FilesystemRoot:
    """One server-resolved operational root."""

    key: str
    path: Path
    description: str


# END_BLOCK_ROOTS


# START_BLOCK_SERVICE
class SafeFilesystemService:
    """Allow-listed filesystem reader with realpath and size boundaries."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure named roots and bounded read limits.
    # inputs: roots — mapping of safe names to server-resolved directories;
    #          max_preview_bytes, max_tail_lines, max_tail_bytes, max_entries.
    # returns: None.
    # side_effects: Resolves configured root paths; does not read file content.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for invalid root names or limits.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        roots: Mapping[str, Path | str],
        *,
        max_preview_bytes: int = 64 * 1024,
        max_tail_lines: int = 1000,
        max_tail_bytes: int = 128 * 1024,
        max_entries: int = 1000,
    ) -> None:
        if not roots:
            raise ValueError("at least one filesystem root is required")
        for key in roots:
            if not isinstance(key, str) or not _valid_root_key(key):
                raise ValueError(f"invalid filesystem root key: {key!r}")
        limits = (max_preview_bytes, max_tail_lines, max_tail_bytes, max_entries)
        if any(int(value) <= 0 for value in limits):
            raise ValueError("filesystem limits must be positive")
        self._roots = {
            key: FilesystemRoot(key, Path(value).expanduser().resolve(), key)
            for key, value in roots.items()
        }
        self._max_preview_bytes = int(max_preview_bytes)
        self._max_tail_lines = int(max_tail_lines)
        self._max_tail_bytes = int(max_tail_bytes)
        self._max_entries = int(max_entries)

    # START_FUNCTION_CONTRACT
    # name: from_runtime
    # purpose: Build roots from the current project's explicit GRACE settings.
    # inputs: settings_obj — optional GraceSettings-like object; project_root —
    #          optional server-side project root.
    # returns: SafeFilesystemService with state/worktrees/runs/logs roots.
    # side_effects: Reads local configuration and resolves configured paths.
    # emitted_logs: None.
    # error_behavior: Propagates malformed local configuration errors.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_runtime(
        cls,
        settings_obj: Any | None = None,
        project_root: Path | str | None = None,
    ) -> SafeFilesystemService:
        from grace_control.config.runtime_identity import get_runtime_identity

        runtime_settings = settings_obj
        identity = get_runtime_identity()
        root = Path(project_root or identity["project_root"]).resolve()
        state = Path(identity["state_root"])
        worktrees = Path(identity["worktree_root"])
        runs = Path(identity["runtime_artifacts_root"])
        logs = _configured_path(
            getattr(runtime_settings, "planning_logs_root", "")
            or identity.get("planning_logs_root", ""),
            root,
        )
        return cls({"state": state, "worktrees": worktrees, "runs": runs, "logs": logs})

    # START_FUNCTION_CONTRACT
    # name: list_roots
    # purpose: Describe the named roots without accepting a client filesystem path.
    # inputs: None.
    # returns: List of root key/existence/description DTOs.
    # side_effects: Reads directory metadata.
    # emitted_logs: None.
    # error_behavior: Never raises for configured roots.
    # END_FUNCTION_CONTRACT
    def list_roots(self) -> list[dict[str, Any]]:
        return [
            {
                "root": item.key,
                "description": item.description,
                "exists": item.path.is_dir(),
                "kind": "directory",
            }
            for item in self._roots.values()
        ]

    # START_FUNCTION_CONTRACT
    # name: list_entries
    # purpose: List bounded safe children under a named operational root.
    # inputs: root — configured root key; path — relative directory path.
    # returns: Root/path and bounded entry metadata.
    # side_effects: Reads directory entries and file metadata.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: Raises FilesystemReadError for unsafe or missing paths.
    # END_FUNCTION_CONTRACT
    def list_entries(self, root: str, path: str = "") -> dict[str, Any]:
        directory = self._resolve(root, path, expect="directory")
        entries: list[dict[str, Any]] = []
        try:
            children = heapq.nsmallest(
                self._max_entries + 1,
                directory.iterdir(),
                key=lambda item: item.name,
            )
        except OSError as exc:
            raise _fs_error("READ_ERROR", 403, "directory cannot be read") from exc
        for child in children[: self._max_entries]:
            relative = _relative_path(self._roots[root].path, child)
            try:
                candidate = self._resolve(root, relative)
                entry = _entry_metadata(candidate, relative)
            except FilesystemReadError:
                continue
            entries.append(entry)
        _log.info("filesystem_read_done", operation="list", root=root)
        return {
            "root": root,
            "path": _clean_relative(path),
            "entries": entries,
            "truncated": len(children) > self._max_entries,
        }

    # START_FUNCTION_CONTRACT
    # name: stat
    # purpose: Return bounded metadata for one named-root relative resource.
    # inputs: root — configured root key; path — relative resource path.
    # returns: File/directory metadata DTO.
    # side_effects: Reads file metadata only.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: Raises FilesystemReadError for unsafe or missing paths.
    # END_FUNCTION_CONTRACT
    def stat(self, root: str, path: str = "") -> dict[str, Any]:
        target = self._resolve(root, path)
        return _entry_metadata(target, _clean_relative(path), include_root=root)

    # START_FUNCTION_CONTRACT
    # name: read_file
    # purpose: Return a bounded text preview or base64 binary payload.
    # inputs: root — configured root key; path — relative file path;
    #          max_bytes — requested preview cap.
    # returns: JSON-safe content and metadata DTO.
    # side_effects: Reads at most max_preview_bytes plus one byte.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: Raises FilesystemReadError for unsafe/missing/non-file data.
    # END_FUNCTION_CONTRACT
    def read_file(
        self,
        root: str,
        path: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve(root, path, expect="file")
        limit = _bounded_limit(max_bytes, self._max_preview_bytes)
        raw, truncated = _read_prefix(target, limit)
        result = _content_result(root, path, target, raw, truncated)
        _log.info("filesystem_read_done", operation="file", root=root)
        return result

    # START_FUNCTION_CONTRACT
    # name: tail_file
    # purpose: Return a bounded tail of a text file or a binary-safe payload.
    # inputs: root — configured root key; path — relative file path; lines —
    #          requested line cap; max_bytes — optional byte cap.
    # returns: JSON-safe tail content and metadata DTO.
    # side_effects: Reads at most max_tail_bytes plus bounded decoder overhead.
    # emitted_logs: filesystem_read_rejected, filesystem_read_done.
    # error_behavior: Raises FilesystemReadError for unsafe/missing/non-file data.
    # END_FUNCTION_CONTRACT
    def tail_file(
        self,
        root: str,
        path: str,
        lines: int = 200,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve(root, path, expect="file")
        line_limit = _bounded_limit(lines, self._max_tail_lines)
        byte_limit = _bounded_limit(max_bytes, self._max_tail_bytes)
        raw, byte_truncated = _read_tail(target, byte_limit)
        if _is_binary(raw):
            result = _content_result(root, path, target, raw, byte_truncated)
            result["tail_lines"] = line_limit
            return result
        decoded = raw.decode("utf-8", errors="replace")
        all_lines = decoded.splitlines()
        line_truncated = len(all_lines) > line_limit
        content = "\n".join(all_lines[-line_limit:])
        result = {
            "root": root,
            "path": _clean_relative(path),
            "size": target.stat().st_size,
            "mime": _mime_for(target),
            "binary": False,
            "encoding": "utf-8",
            "content": content,
            "content_base64": None,
            "truncated": byte_truncated or line_truncated,
            "tail_lines": line_limit,
        }
        _log.info("filesystem_read_done", operation="tail", root=root)
        return result

    # START_FUNCTION_CONTRACT
    # name: _resolve
    # purpose: Resolve a named-root relative path with secret and realpath checks.
    # inputs: root, path, expect — optional file/directory type requirement.
    # returns: Contained resolved Path.
    # side_effects: Reads path metadata.
    # emitted_logs: filesystem_read_rejected.
    # error_behavior: Raises typed FilesystemReadError on every unsafe condition.
    # END_FUNCTION_CONTRACT
    def _resolve(self, root: str, path: str, expect: str | None = None) -> Path:
        if root not in self._roots:
            raise _fs_error("ROOT_NOT_FOUND", 404, "unknown filesystem root")
        relative = _validate_relative(path)
        if _is_secret_path(relative):
            raise _fs_error("SECRET_PATH_DENIED", 403, "path is denied by filesystem policy")
        root_path = self._roots[root].path
        if not root_path.exists() or not root_path.is_dir():
            raise _fs_error("ROOT_NOT_FOUND", 404, "configured filesystem root is unavailable")
        candidate = Path(os.path.realpath(root_path / relative))
        root_real = Path(os.path.realpath(root_path))
        if not _contained(root_real, candidate):
            raise _fs_error("SYMLINK_ESCAPE", 403, "path resolves outside the configured root")
        resolved_relative = candidate.relative_to(root_real).as_posix()
        if _is_secret_path(resolved_relative):
            raise _fs_error("SECRET_PATH_DENIED", 403, "path is denied by filesystem policy")
        if not candidate.exists():
            raise _fs_error("PATH_NOT_FOUND", 404, "path was not found")
        if expect == "file" and not candidate.is_file():
            raise _fs_error("NOT_FILE", 422, "path is not a regular file")
        if expect == "directory" and not candidate.is_dir():
            raise _fs_error("NOT_DIRECTORY", 422, "path is not a directory")
        return candidate


# END_BLOCK_SERVICE


# START_BLOCK_HELPERS
def _valid_root_key(value: str) -> bool:
    return value.replace("_", "").replace("-", "").isalnum() and len(value) <= 64


def _configured_path(value: str, root: Path) -> Path:
    path = Path(value or root).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _validate_relative(value: str) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise _fs_error("INVALID_PATH", 400, "path must be a relative POSIX path")
    if value.startswith("/"):
        raise _fs_error("ABSOLUTE_PATH", 400, "absolute paths are not accepted")
    parts = PurePosixPath(value).parts
    if ".." in parts:
        raise _fs_error("PATH_TRAVERSAL", 400, "parent traversal is not accepted")
    return "/".join(part for part in parts if part not in ("", "."))


def _clean_relative(value: str) -> str:
    return _validate_relative(value)


def _is_secret_path(relative: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(relative).parts]
    for part in parts:
        if part == ".env" or part.startswith(".env."):
            return True
        if part.endswith(".pem") or part.endswith(".key") or part.startswith("id_rsa"):
            return True
        if part == "credentials" or part.startswith("credentials"):
            return True
        if part == "secrets" or part.startswith("secrets"):
            return True
    return len(parts) >= 2 and parts[-2] == ".git" and parts[-1] == "credentials"


def _contained(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _entry_metadata(path: Path, relative: str, include_root: str | None = None) -> dict[str, Any]:
    try:
        info = path.stat()
    except OSError as exc:
        raise _fs_error("READ_ERROR", 403, "metadata cannot be read") from exc
    is_dir = path.is_dir()
    result: dict[str, Any] = {
        "name": path.name or relative,
        "relative_path": relative,
        "size": info.st_size if not is_dir else 0,
        "mtime": info.st_mtime,
        "kind": "directory" if is_dir else "file",
        "mime": "inode/directory" if is_dir else _mime_for(path),
        "preview_capable": not is_dir,
    }
    if include_root is not None:
        result["root"] = include_root
    return result


def _mime_for(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _bounded_limit(value: int | None, maximum: int) -> int:
    if value is None:
        return maximum
    if int(value) <= 0:
        raise _fs_error("INVALID_LIMIT", 422, "read limit must be positive")
    return min(int(value), maximum)


def _read_prefix(path: Path, limit: int) -> tuple[bytes, bool]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise _fs_error("READ_ERROR", 403, "file cannot be read") from exc
    return raw[:limit], len(raw) > limit


def _read_tail(path: Path, limit: int) -> tuple[bytes, bool]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            start = max(0, size - limit - 1)
            handle.seek(start)
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise _fs_error("READ_ERROR", 403, "file cannot be read") from exc
    return raw[-limit:], size > limit


def _is_binary(raw: bytes) -> bool:
    if b"\x00" in raw:
        return True
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _content_result(
    root: str,
    path: str,
    target: Path,
    raw: bytes,
    truncated: bool,
) -> dict[str, Any]:
    binary = _is_binary(raw)
    return {
        "root": root,
        "path": _clean_relative(path),
        "size": target.stat().st_size,
        "mime": _mime_for(target),
        "binary": binary,
        "encoding": None if binary else "utf-8",
        "content": None if binary else raw.decode("utf-8", errors="replace"),
        "content_base64": base64.b64encode(raw).decode("ascii") if binary else None,
        "truncated": truncated,
    }


def _fs_error(code: str, status_code: int, detail: str) -> FilesystemReadError:
    _log.warn("filesystem_read_rejected", reason=code)
    return FilesystemReadError(code, status_code, detail)


# END_BLOCK_HELPERS
