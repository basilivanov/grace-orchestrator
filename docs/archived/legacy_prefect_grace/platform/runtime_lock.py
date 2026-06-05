# ############################################################################
# AI_HEADER: runtime_lock
# ROLE: Bounded runtime lock helper for GRACE controller dry-runs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide project-scoped file locks contained under runtime_state_root.
# inputs: Runtime state root, lock name, max age, and owner metadata.
# returns: RuntimeLockResult records for acquire/release attempts.
# side_effects: Creates/removes JSON lock files under <runtime_state_root>/state/locks.
# emitted_logs: None.
# error_behavior: Fails closed when lock path escapes runtime_state_root or an active lock exists.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RuntimeLockResult
#   - class: RuntimeLock
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass
class RuntimeLockResult:
    path: str
    acquired: bool = False
    released: bool = False
    already_running: bool = False
    stale_replaced: bool = False
    ephemeral: bool = False
    owner: str = ""
    existing_owner: str = ""
    message: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert lock result to JSON-safe dictionary.
    # inputs: None.
    # returns: dict with lock state and errors.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict:
        return asdict(self)


class RuntimeLock:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Build a bounded runtime lock path under a project runtime state root.
    # inputs:
    #   runtime_state_root: Configured project runtime state root.
    #   name: Lock filename stem.
    #   owner: Optional lock owner string.
    #   max_age_seconds: Age after which an existing lock may be replaced.
    # returns: RuntimeLock instance.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        runtime_state_root: Path | str,
        *,
        name: str = "backlog-controller",
        owner: str | None = None,
        max_age_seconds: int = 3600,
        allow_ephemeral: bool = False,
    ) -> None:
        self.runtime_state_root = Path(runtime_state_root).resolve()
        self.lock_path = self.runtime_state_root / "state" / "locks" / f"{name}.lock"
        self.owner = owner or f"{os.getpid()}:{uuid.uuid4()}"
        self.max_age_seconds = int(max_age_seconds)
        self.allow_ephemeral = bool(allow_ephemeral)
        self._acquired = False

    def _contained_error(self) -> RuntimeLockResult | None:
        if _is_relative_to(self.lock_path, self.runtime_state_root):
            return None
        return RuntimeLockResult(
            path=str(self.lock_path),
            owner=self.owner,
            message="Lock path escapes runtime_state_root",
            errors=[{"code": "LOCK_PATH_ESCAPE", "message": "Lock path escapes runtime_state_root"}],
        )

    def _read_existing(self) -> dict:
        if not self.lock_path.exists():
            return {}
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _is_stale(self, payload: dict) -> bool:
        created_at = str(payload.get("created_at") or "")
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (_utc_now() - created).total_seconds() > self.max_age_seconds

    # START_FUNCTION_CONTRACT
    # name: acquire
    # purpose: Acquire the lock or report active/stale lock state.
    # inputs: None.
    # returns: RuntimeLockResult with acquired/already_running/stale fields.
    # side_effects: Creates or replaces lock file when safe.
    # emitted_logs: None.
    # error_behavior: Returns errors instead of raising for containment and active lock failures.
    # END_FUNCTION_CONTRACT
    def acquire(self) -> RuntimeLockResult:
        contained_error = self._contained_error()
        if contained_error is not None:
            return contained_error
        existing = self._read_existing()
        stale_replaced = False
        if existing and not self._is_stale(existing):
            return RuntimeLockResult(
                path=str(self.lock_path),
                acquired=False,
                already_running=True,
                owner=self.owner,
                existing_owner=str(existing.get("owner") or ""),
                message="controller_already_running",
                errors=[{"code": "controller_already_running", "message": "Controller lock is already active"}],
            )
        if existing:
            stale_replaced = True

        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            if not self.allow_ephemeral:
                return RuntimeLockResult(
                    path=str(self.lock_path),
                    acquired=False,
                    owner=self.owner,
                    message=str(exc),
                    errors=[{"code": "LOCK_PERMISSION_DENIED", "message": str(exc)}],
                )
            return RuntimeLockResult(
                path=str(self.lock_path),
                acquired=True,
                released=True,
                ephemeral=True,
                owner=self.owner,
                message="lock_not_persisted_permission_denied",
            )
        payload = {
            "owner": self.owner,
            "created_at": _utc_now().isoformat(),
            "pid": os.getpid(),
            "lock_path": str(self.lock_path),
        }
        try:
            self.lock_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except PermissionError as exc:
            if not self.allow_ephemeral:
                return RuntimeLockResult(
                    path=str(self.lock_path),
                    acquired=False,
                    owner=self.owner,
                    message=str(exc),
                    errors=[{"code": "LOCK_PERMISSION_DENIED", "message": str(exc)}],
                )
            return RuntimeLockResult(
                path=str(self.lock_path),
                acquired=True,
                released=True,
                ephemeral=True,
                owner=self.owner,
                message="lock_not_persisted_permission_denied",
            )
        self._acquired = True
        return RuntimeLockResult(
            path=str(self.lock_path),
            acquired=True,
            released=False,
            stale_replaced=stale_replaced,
            owner=self.owner,
        )

    # START_FUNCTION_CONTRACT
    # name: release
    # purpose: Release a lock previously acquired by this RuntimeLock instance.
    # inputs:
    #   result: Existing RuntimeLockResult to update, optional.
    # returns: RuntimeLockResult with released status.
    # side_effects: Removes lock file if owned by this instance.
    # emitted_logs: None.
    # error_behavior: Reports owner mismatch or removal failures in result errors.
    # END_FUNCTION_CONTRACT
    def release(self, result: RuntimeLockResult | None = None) -> RuntimeLockResult:
        lock_result = result or RuntimeLockResult(path=str(self.lock_path), owner=self.owner)
        if not self._acquired:
            return lock_result
        existing = self._read_existing()
        if existing and str(existing.get("owner") or "") != self.owner:
            lock_result.errors.append({"code": "LOCK_OWNER_MISMATCH", "message": "Lock owner changed before release"})
            return lock_result
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
            lock_result.released = True
            self._acquired = False
        except OSError as exc:
            lock_result.errors.append({"code": "LOCK_RELEASE_FAILED", "message": str(exc)})
        return lock_result
