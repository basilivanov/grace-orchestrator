# ############################################################################
# AI_HEADER: admin_git_read_service — bounded project-local Git inspection
# ROLE: Provides read-only branch, status, worktree, commit, diff and tracked
#       file inspection for one server-resolved repository. It validates every
#       client ref/path before delegating execution to the canonical GitService.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose safe, bounded Git read primitives for the project-local API.
# inputs: Server-resolved repository root and validated read parameters.
# returns: JSON-safe repository/status/commit/file DTOs.
# side_effects: Runs bounded-timeout read-only Git commands through the
#               canonical Git adapter.
# emitted_logs: git_read_rejected, git_read_done.
# error_behavior: Raises GitReadError with stable HTTP-safe error codes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: GitReadError
#     methods:
#       - to_dict
#   - class: AdminGitReadService
#     methods:
#       - repository
#       - worktrees
#       - commits
#       - changed_files
#       - diff_stat
#       - diff
#       - tracked_files
#       - show_file
# END_MODULE_MAP

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitResult, GitService

_log = GraceLogger("admin_git_read")

_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@~^{}-]{0,199}$")
_REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


# START_BLOCK_ERRORS
class GitReadError(ValueError):
    """Typed error returned by the project-local Git read boundary."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Build a stable error with machine code and HTTP status.
    # inputs: code (str), status_code (int), detail (str).
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Stores bounded safe detail text only.
    # END_FUNCTION_CONTRACT
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail[:240]
        super().__init__(self.detail)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Return JSON-safe error data for the API layer.
    # inputs: None.
    # returns: Dict with code and message.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.detail}


# END_BLOCK_ERRORS


# START_BLOCK_SERVICE
class AdminGitReadService:
    """Read-only Git service tied to one immutable server-side repository."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure repository identity, branch defaults and output caps.
    # inputs: repo_root; target_branch/base_branch/remote; optional GitService;
    #          timeout_seconds and max_output_bytes.
    # returns: None.
    # side_effects: Resolves the repository root; does not run Git yet.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for invalid limits or metadata.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        repo_root: Path | str,
        *,
        target_branch: str | None = None,
        base_branch: str | None = None,
        remote: str | None = None,
        git_service: GitService | None = None,
        timeout_seconds: int = 15,
        max_output_bytes: int = 1024 * 1024,
    ) -> None:
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("Git read limits must be positive")
        self.repo_root = Path(repo_root).expanduser().resolve()
        from grace_control.config.settings import settings

        self.target_branch = _validate_ref(
            target_branch or settings.target_branch,
            "target branch",
        )
        self.base_branch = _validate_ref(
            base_branch or settings.base_branch,
            "base branch",
        )
        self.remote = _validate_remote(remote or settings.git_remote)
        self._git = git_service or GitService()
        self._timeout_seconds = int(timeout_seconds)
        self._max_output_bytes = int(max_output_bytes)

    # START_FUNCTION_CONTRACT
    # name: repository
    # purpose: Return branch/HEAD/remote/status/worktree repository metadata.
    # inputs: None.
    # returns: Repository identity and clean/dirty status DTO.
    # side_effects: Runs read-only Git commands.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unavailable/non-Git repositories.
    # END_FUNCTION_CONTRACT
    def repository(self) -> dict[str, Any]:
        self._require_repo()
        branch = self._text(["branch", "--show-current"], optional=True).strip()
        head = self._text(["rev-parse", "HEAD"], optional=True).strip()
        target_head = self._text(
            ["rev-parse", "--verify", f"{self.target_branch}^{{commit}}"],
            optional=True,
        ).strip() or None
        status_text = self._text(["status", "--porcelain=v1", "--branch"])
        status_lines = status_text.splitlines()
        entries = [line for line in status_lines if line and not line.startswith("##")]
        remote = self._text(["remote", "get-url", self.remote], optional=True).strip()
        result = {
            "repo_root": str(self.repo_root),
            "current_branch": branch,
            "head": head,
            "target_branch": self.target_branch,
            "target_branch_head": target_head,
            "base_branch": self.base_branch,
            "remote": self.remote,
            "remote_url": _mask_remote(remote),
            "clean": not entries,
            "status": entries,
        }
        _log.info("git_read_done", operation="repository")
        return result

    # START_FUNCTION_CONTRACT
    # name: worktrees
    # purpose: List Git worktrees using porcelain output without exposing tokens.
    # inputs: None.
    # returns: List of path/HEAD/branch/worktree metadata.
    # side_effects: Runs one read-only Git command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError when Git cannot list worktrees.
    # END_FUNCTION_CONTRACT
    def worktrees(self) -> list[dict[str, Any]]:
        output = self._text(["worktree", "list", "--porcelain"])
        records: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in output.splitlines() + [""]:
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            if key == "worktree":
                current["path"] = value
            elif key == "HEAD":
                current["head"] = value
            elif key == "branch":
                current["branch"] = value.removeprefix("refs/heads/")
            elif key == "detached":
                current["detached"] = True
            elif key == "bare":
                current["bare"] = True
            elif key == "prunable":
                current["prunable"] = value
        _log.info("git_read_done", operation="worktrees")
        return records

    # START_FUNCTION_CONTRACT
    # name: commits
    # purpose: Return bounded commit metadata for a validated ref.
    # inputs: ref — safe Git ref or default target branch; limit — 1..200.
    # returns: List of commit metadata DTOs.
    # side_effects: Runs one read-only Git log command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe/unresolvable refs.
    # END_FUNCTION_CONTRACT
    def commits(self, ref: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        count = _bounded_count(limit, 200)
        safe_ref = self._resolve_ref(ref or self.target_branch)
        output = self._text([
            "log", "--no-ext-diff", f"-n{count}",
            "--format=%H%x09%an%x09%aI%x09%s", safe_ref,
        ])
        result = []
        for line in output.splitlines():
            fields = line.split("\t", 3)
            if len(fields) == 4:
                result.append({
                    "sha": fields[0],
                    "author": fields[1],
                    "committed_at": fields[2],
                    "subject": fields[3],
                })
        _log.info("git_read_done", operation="commits")
        return result

    # START_FUNCTION_CONTRACT
    # name: changed_files
    # purpose: List status/name changes between a validated ref and HEAD.
    # inputs: ref — safe base ref or default base branch.
    # returns: List of status/path DTOs.
    # side_effects: Runs one read-only Git diff command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe/unresolvable refs.
    # END_FUNCTION_CONTRACT
    def changed_files(self, ref: str | None = None) -> list[dict[str, str]]:
        safe_ref = self._resolve_ref(ref or self.base_branch)
        output = self._text(["diff", "--name-status", safe_ref, "HEAD", "--"])
        result = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2:
                item = {"status": fields[0], "path": fields[-1]}
                if len(fields) == 3:
                    item["old_path"] = fields[1]
                result.append(item)
        _log.info("git_read_done", operation="changed_files")
        return result

    # START_FUNCTION_CONTRACT
    # name: diff_stat
    # purpose: Return bounded human-readable diff statistics for a ref.
    # inputs: ref — safe base ref or default base branch; path — optional safe path.
    # returns: DTO containing stat text and truncation flag.
    # side_effects: Runs one read-only Git diff command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe refs/paths.
    # END_FUNCTION_CONTRACT
    def diff_stat(self, ref: str | None = None, path: str | None = None) -> dict[str, Any]:
        output = self._diff_output("--stat", ref, path)
        result = _bounded_git_text(output)
        return {**result, "stat": result["text"]}

    # START_FUNCTION_CONTRACT
    # name: diff
    # purpose: Return a bounded unified diff for a safe ref/path selection.
    # inputs: ref — safe base ref or default base branch; path — optional safe path.
    # returns: DTO containing unified diff text and truncation flag.
    # side_effects: Runs one read-only Git diff command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe refs/paths.
    # END_FUNCTION_CONTRACT
    def diff(self, ref: str | None = None, path: str | None = None) -> dict[str, Any]:
        output = self._diff_output("--patch", ref, path)
        result = _bounded_git_text(output)
        return {**result, "diff": result["text"]}

    # START_FUNCTION_CONTRACT
    # name: tracked_files
    # purpose: List Git-tracked files under an optional safe relative path.
    # inputs: path — optional relative tracked path.
    # returns: Bounded list of tracked paths and truncation metadata.
    # side_effects: Runs one read-only Git ls-files command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe paths or Git failure.
    # END_FUNCTION_CONTRACT
    def tracked_files(self, path: str | None = None) -> dict[str, Any]:
        args = ["ls-files", "--"]
        if path:
            args.append(_validate_path(path))
        output = self._read_result(args)
        bounded = _bounded_git_text(output)
        lines = [line for line in bounded["text"].splitlines() if line]
        return {
            "files": lines,
            "truncated": bounded["truncated"],
            "path": path or "",
        }

    # START_FUNCTION_CONTRACT
    # name: show_file
    # purpose: Read a bounded Git-tracked file at a validated ref/path.
    # inputs: ref — safe Git ref; path — safe tracked relative path;
    #          max_bytes — requested byte cap.
    # returns: Text/binary-safe file DTO.
    # side_effects: Runs one read-only Git show command.
    # emitted_logs: git_read_rejected, git_read_done.
    # error_behavior: Raises GitReadError for unsafe/missing refs or paths.
    # END_FUNCTION_CONTRACT
    def show_file(
        self,
        ref: str,
        path: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        safe_ref = self._resolve_ref(ref)
        safe_path = _validate_path(path)
        limit = min(_positive_or_default(max_bytes, self._max_output_bytes), self._max_output_bytes)
        result = self._read_result(
            ["show", "--no-ext-diff", "--format=", f"{safe_ref}:{safe_path}"],
            max_output_bytes=limit,
        )
        raw = result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")
        bounded = raw[:limit]
        binary = b"\x00" in bounded
        return {
            "ref": safe_ref,
            "path": safe_path,
            "size": self._object_size(safe_ref, safe_path) or len(raw),
            "binary": binary,
            "content": None if binary else bounded.decode("utf-8", errors="replace"),
            "content_base64": _base64(bounded) if binary else None,
            "truncated": result.stdout_truncated or len(raw) > limit,
        }

    # START_FUNCTION_CONTRACT
    # name: _require_repo
    # purpose: Verify that the configured server-side root is a Git worktree.
    # inputs: None.
    # returns: None.
    # side_effects: Runs git rev-parse through GitService.
    # emitted_logs: git_read_rejected.
    # error_behavior: Raises GitReadError when the repo is unavailable.
    # END_FUNCTION_CONTRACT
    def _require_repo(self) -> None:
        if not self.repo_root.is_dir():
            raise _git_error("REPO_NOT_FOUND", 404, "configured repository is unavailable")
        result = self._git.run_bounded(
            ["rev-parse", "--is-inside-work-tree"],
            self.repo_root,
            max_output_bytes=min(self._max_output_bytes, 256),
            timeout=self._timeout_seconds,
        )
        if not result.success or result.stdout.strip() != "true":
            raise _git_error("NOT_GIT_REPOSITORY", 422, "configured root is not a Git repository")

    # START_FUNCTION_CONTRACT
    # name: _text
    # purpose: Run one validated Git read and bound its textual output.
    # inputs: args — already validated read-only Git arguments; optional flag.
    # returns: Bounded stdout text.
    # side_effects: Runs Git through GitService.
    # emitted_logs: git_read_rejected on failure.
    # error_behavior: Raises GitReadError on failed commands unless optional.
    # END_FUNCTION_CONTRACT
    def _text(self, args: list[str], optional: bool = False) -> str:
        try:
            return self._read_result(args).stdout
        except GitReadError:
            if optional:
                return ""
            raise

    # START_FUNCTION_CONTRACT
    # name: _read_result
    # purpose: Execute one read-only Git operation through the byte-bounded
    #          canonical process primitive.
    # inputs: args — validated read-only Git arguments; max_output_bytes —
    #          optional per-operation cap no greater than the service cap.
    # returns: GitResult with bounded output and truncation metadata.
    # side_effects: Executes Git with the configured timeout/cap.
    # emitted_logs: git_read_rejected on repository or command failure.
    # error_behavior: Raises GitReadError when the command cannot be completed.
    # END_FUNCTION_CONTRACT
    def _read_result(self, args: list[str], max_output_bytes: int | None = None) -> GitResult:
        self._require_repo()
        limit = min(max_output_bytes or self._max_output_bytes, self._max_output_bytes)
        result = self._git.run_bounded(
            args,
            self.repo_root,
            max_output_bytes=limit,
            timeout=self._timeout_seconds,
        )
        if not result.success:
            raise _git_error("GIT_READ_FAILED", 422, "Git read command failed")
        return result

    # START_FUNCTION_CONTRACT
    # name: _resolve_ref
    # purpose: Validate and resolve a ref to a commit expression accepted by Git.
    # inputs: ref — untrusted ref string; required controls missing-ref behavior.
    # returns: Validated ref string or None for an optional missing ref.
    # side_effects: Runs git rev-parse through GitService.
    # emitted_logs: git_read_rejected on invalid/unresolvable required refs.
    # error_behavior: Raises GitReadError for unsafe or missing required refs.
    # END_FUNCTION_CONTRACT
    def _resolve_ref(self, ref: str, required: bool = True) -> str | None:
        safe_ref = _validate_ref(ref, "Git ref")
        self._require_repo()
        result = self._git.run_bounded(
            ["rev-parse", "--verify", f"{safe_ref}^{{commit}}"],
            self.repo_root,
            max_output_bytes=self._max_output_bytes,
            timeout=self._timeout_seconds,
        )
        if not result.success:
            if not required:
                return None
            raise _git_error("REF_NOT_FOUND", 404, "Git ref was not found")
        return safe_ref

    # START_FUNCTION_CONTRACT
    # name: _diff_output
    # purpose: Build and execute a validated bounded diff/stat command.
    # inputs: mode, ref and optional relative path.
    # returns: Raw bounded text.
    # side_effects: Runs Git through GitService.
    # emitted_logs: git_read_rejected.
    # error_behavior: Raises GitReadError for unsafe refs/paths/command failure.
    # END_FUNCTION_CONTRACT
    def _diff_output(self, mode: str, ref: str | None, path: str | None) -> GitResult:
        safe_ref = self._resolve_ref(ref or self.base_branch)
        args = ["diff", "--no-ext-diff", mode, safe_ref, "HEAD", "--"]
        if path:
            args.append(_validate_path(path))
        return self._read_result(args)

    # START_FUNCTION_CONTRACT
    # name: _object_size
    # purpose: Read the full byte size of one validated Git object without
    #          loading its content.
    # inputs: ref — validated commit ref; path — validated tracked path.
    # returns: Object byte size or None when Git cannot report it.
    # side_effects: Runs a bounded git cat-file metadata command.
    # emitted_logs: git_read_rejected on command failure, suppressed here.
    # error_behavior: Returns None for an unavailable size metadata lookup.
    # END_FUNCTION_CONTRACT
    def _object_size(self, ref: str, path: str) -> int | None:
        try:
            result = self._read_result(["cat-file", "-s", f"{ref}:{path}"])
            return int(result.stdout.strip())
        except (GitReadError, ValueError):
            return None


# END_BLOCK_SERVICE


# START_BLOCK_HELPERS
def _validate_ref(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError(f"{label} is invalid")
    if any(char.isspace() for char in value) or not _REF_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    if ".." in value or value.endswith("/"):
        raise ValueError(f"{label} is invalid")
    return value


def _validate_remote(value: str) -> str:
    if not isinstance(value, str) or not _REMOTE_PATTERN.fullmatch(value):
        raise ValueError("Git remote is invalid")
    return value


def _validate_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise _git_error("INVALID_PATH", 400, "Git path must be relative")
    if value.startswith("/") or value.startswith("-"):
        raise _git_error("INVALID_PATH", 400, "Git path must be relative")
    value = value.rstrip("/")
    if not value:
        raise _git_error("INVALID_PATH", 400, "Git path must be relative")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or ":" in value:
        raise _git_error("PATH_TRAVERSAL", 400, "Git path is unsafe")
    return value


def _bounded_count(value: int, maximum: int) -> int:
    if int(value) < 1:
        raise GitReadError("INVALID_LIMIT", 422, "limit must be positive")
    return min(int(value), maximum)


def _positive_or_default(value: int | None, default: int) -> int:
    if value is None:
        return default
    if int(value) <= 0:
        raise GitReadError("INVALID_LIMIT", 422, "max_bytes must be positive")
    return int(value)


def _bounded_git_text(result: GitResult) -> dict[str, Any]:
    raw = result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")
    return {
        "text": result.stdout,
        "truncated": result.stdout_truncated,
        "bytes": len(raw),
    }


def _mask_remote(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    return value.split("?", 1)[0]


def _base64(value: bytes) -> str:
    import base64

    return base64.b64encode(value).decode("ascii")


def _git_error(code: str, status_code: int, detail: str) -> GitReadError:
    _log.warn("git_read_rejected", reason=code)
    return GitReadError(code, status_code, detail)


# END_BLOCK_HELPERS
