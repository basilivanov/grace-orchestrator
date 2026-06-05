# ############################################################################
# AI_HEADER: nightly_batch_recheck
# ROLE: Read-only stale-safe preflight recheck for nightly batch plans.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Re-read current packet, registry, dependency, evidence, and Prefect binding state before batch execution.
# inputs: Saved nightly batch selection JSON or in-process batch selection parameters.
# returns: NightlyBatchRecheckResult with bounded confirmation or blocker summary.
# side_effects: Acquires/releases runtime lock only; no execution, registry writes, worktrees, Prefect runs, or Git mutations.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers on stale or unavailable state.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: PacketRecheckSummary
#   - dataclass: NightlyBatchRecheckResult
#   - function: recheck_nightly_batch
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import hashlib
import json

from prefect_grace.platform.nightly_batch_selection import (
    BatchSelectionResult,
    _cost_exceeds_limit,
    select_safe_batch,
)
from prefect_grace.platform.nightly_preflight_risk_report import (
    _check_evidence,
    _check_review,
)
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.prefect_worker_binding import run_prefect_worker_binding_preflight
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.runtime_lock import RuntimeLock
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import (
    RegistryStatus,
    is_runnable_registry_status,
)


MAX_ITEMS = 25
DEFAULT_MAX_PACKETS = 10
DEFAULT_MAX_COST = "live_required"


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass
class PacketRecheckSummary:
    packet_id: str
    status: str
    blocker_classes: list[str] = field(default_factory=list)
    blocker_codes: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize a bounded packet recheck summary.
    # inputs: none.
    # returns: dict with packet_id, status, blocker classes, and blocker codes.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "status": self.status,
            "blocker_classes": self.blocker_classes[:MAX_ITEMS],
            "blocker_codes": self.blocker_codes[:MAX_ITEMS],
        }


@dataclass
class NightlyBatchRecheckResult:
    ok: bool
    project_key: str
    mode: str = "nightly_batch_recheck"
    dry_run: bool = True
    preflight_status: str = "blocked"
    selected_total: int = 0
    confirmed_total: int = 0
    blocked_total: int = 0
    blocker_classes: list[str] = field(default_factory=list)
    packet_samples: list[PacketRecheckSummary] = field(default_factory=list)
    packet_samples_total: int = 0
    plan_hash: str = ""
    recheck_hash: str = ""
    batch_limits: dict[str, Any] = field(default_factory=dict)
    lock_status: dict[str, Any] = field(default_factory=dict)
    side_effects: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize recheck result with bounded lists and zero side-effect counters.
    # inputs: none.
    # returns: dict with bounded preflight recheck result.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "preflight_status": self.preflight_status,
            "selected_total": self.selected_total,
            "confirmed_total": self.confirmed_total,
            "blocked_total": self.blocked_total,
            "blocker_classes": self.blocker_classes[:MAX_ITEMS],
            "packet_samples": [sample.to_dict() for sample in self.packet_samples[:MAX_ITEMS]],
            "packet_samples_total": self.packet_samples_total,
            "plan_hash": self.plan_hash,
            "recheck_hash": self.recheck_hash,
            "batch_limits": dict(self.batch_limits),
            "lock_status": dict(self.lock_status),
            "side_effects": dict(self.side_effects),
            "warnings": self.warnings[:MAX_ITEMS],
            "errors": self.errors[:MAX_ITEMS],
            "blockers": self.blockers[:MAX_ITEMS],
        }


def _zero_side_effects() -> dict[str, int]:
    return {
        "registry_updates": 0,
        "prefect_runs_created": 0,
        "live_agents_started": 0,
        "worktrees_created": 0,
        "git_mutations_count": 0,
    }


def _selection_payload(selection: BatchSelectionResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(selection, BatchSelectionResult):
        return selection.to_dict()
    if isinstance(selection, dict) and isinstance(selection.get("result"), dict):
        return dict(selection["result"])
    if isinstance(selection, dict) and isinstance(selection.get("data"), dict):
        return dict(selection["data"])
    if isinstance(selection, dict):
        return dict(selection)
    return {}


def _load_saved_selection(path: Path | str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return _selection_payload(json.load(handle))


def _packet_path(
    *,
    repo_root: Path,
    packets_dir: Path,
    packet_id: str,
    registry_record: dict[str, Any] | None,
) -> Path:
    record_path = str((registry_record or {}).get("path") or "")
    if record_path:
        candidate = Path(record_path)
        return candidate if candidate.is_absolute() else repo_root / candidate
    feature_id = packet_id.split("-W", 1)[0] if "-W" in packet_id else packet_id
    return packets_dir / feature_id / "EXECUTION_PACKET.md"


def _review_status(packet_path: Path) -> str:
    has_review, review_accepted = _check_review(packet_path)
    if not has_review:
        return "missing"
    return "accepted" if review_accepted else "blocked"


def _evidence_status(packet_path: Path) -> str:
    has_evidence, evidence_valid = _check_evidence(packet_path)
    if not has_evidence:
        return "missing"
    return "valid" if evidence_valid else "invalid"


def _current_fact(
    *,
    repo_root: Path,
    packets_dir: Path,
    packet_id: str,
    registry_record: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    packet_path = _packet_path(
        repo_root=repo_root,
        packets_dir=packets_dir,
        packet_id=packet_id,
        registry_record=registry_record,
    )
    parsed = None
    if packet_path.exists():
        try:
            parsed = parse_packet_markdown(packet_path, mode="lenient")
        except Exception as exc:
            blockers.append(_error("SOURCE_PARSE_FAILED", f"Packet source cannot be parsed: {exc}", blocker_class="source"))
    else:
        blockers.append(_error("SOURCE_PACKET_MISSING", "Packet source file is missing", blocker_class="source"))

    registry_status = str((registry_record or {}).get("registry_status") or "")
    source_hash = parsed.source_hash if parsed is not None else ""
    registry_source_hash = str((registry_record or {}).get("source_hash") or "")

    fact = {
        "packet_id": packet_id,
        "source_hash": source_hash,
        "registry_source_hash": registry_source_hash,
        "registry_status": registry_status,
        "source_status": parsed.status if parsed is not None else "",
        "depends_on": list((registry_record or {}).get("depends_on") or []),
        "review_status": _review_status(packet_path) if packet_path.exists() else "missing",
        "evidence_status": _evidence_status(packet_path) if packet_path.exists() else "missing",
    }
    return fact, blockers


def _add_blocker(
    blockers: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    blocker_class: str,
    packet_id: str | None = None,
) -> None:
    payload = _error(code, message, blocker_class=blocker_class)
    if packet_id:
        payload["packet_id"] = packet_id
    blockers.append(payload)


def _limit_blockers(
    *,
    selected_total: int,
    facts_by_id: dict[str, dict[str, Any]],
    max_packets: int,
    max_cost: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if selected_total > max_packets:
        _add_blocker(
            blockers,
            "CURRENT_MAX_PACKETS_EXCEEDED",
            f"Saved selection has {selected_total} packets; current limit is {max_packets}",
            blocker_class="limits",
        )
    for packet_id, fact in facts_by_id.items():
        cost = str(fact.get("cost_estimate") or "unknown")
        if _cost_exceeds_limit(cost, max_cost):
            _add_blocker(
                blockers,
                "CURRENT_MAX_COST_EXCEEDED",
                f"Packet cost {cost} exceeds current max cost {max_cost}",
                blocker_class="limits",
                packet_id=packet_id,
            )
    return blockers


def _plan_integrity_blockers(
    *,
    declared_total: int,
    selected_packets: list[str],
    plan_facts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if declared_total != len(selected_packets):
        _add_blocker(
            blockers,
            "PLAN_SELECTED_TOTAL_MISMATCH",
            "Saved selected_total does not match the selected packet list available for recheck",
            blocker_class="plan_integrity",
        )
    for packet_id in selected_packets:
        if packet_id not in plan_facts:
            _add_blocker(
                blockers,
                "PLAN_PACKET_FACT_MISSING",
                "Saved plan lacks required selected packet facts",
                blocker_class="plan_integrity",
                packet_id=packet_id,
            )
    return blockers


def _check_packet_staleness(
    *,
    packet_id: str,
    plan_fact: dict[str, Any],
    current_fact: dict[str, Any],
    registry_record: dict[str, Any] | None,
    selected_before: set[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not plan_fact.get("source_hash"):
        _add_blocker(blockers, "PLAN_SOURCE_HASH_MISSING", "Saved plan lacks selected packet source hash", blocker_class="source", packet_id=packet_id)
    elif plan_fact.get("source_hash") != current_fact.get("source_hash"):
        _add_blocker(blockers, "SOURCE_HASH_CHANGED", "Selected packet source hash changed", blocker_class="source", packet_id=packet_id)

    if not registry_record:
        _add_blocker(blockers, "REGISTRY_RECORD_MISSING", "Selected packet is missing from registry", blocker_class="registry", packet_id=packet_id)
        return blockers

    if current_fact.get("registry_source_hash") and current_fact.get("source_hash"):
        if current_fact["registry_source_hash"] != current_fact["source_hash"]:
            _add_blocker(blockers, "SOURCE_RUNTIME_MISMATCH", "Registry source hash differs from current source", blocker_class="source", packet_id=packet_id)

    if plan_fact.get("registry_status") and plan_fact.get("registry_status") != current_fact.get("registry_status"):
        _add_blocker(blockers, "REGISTRY_STATUS_CHANGED", "Registry status changed since selection", blocker_class="registry", packet_id=packet_id)

    if not is_runnable_registry_status(str(current_fact.get("registry_status") or "")):
        _add_blocker(blockers, "REGISTRY_STATUS_NOT_RUNNABLE", "Selected packet is no longer runnable", blocker_class="registry", packet_id=packet_id)

    saved_deps = list(plan_fact.get("depends_on") or [])
    current_deps = list(current_fact.get("depends_on") or [])
    if saved_deps != current_deps:
        _add_blocker(blockers, "DEPENDENCIES_CHANGED", "Dependency list changed since selection", blocker_class="dependency", packet_id=packet_id)

    for dep_id in current_deps:
        dep_record = registry_record.get("_dependency_records", {}).get(dep_id) if registry_record else None
        dep_status = str((dep_record or {}).get("registry_status") or "")
        if dep_id not in selected_before and dep_status != RegistryStatus.ACCEPTED.value:
            _add_blocker(blockers, "DEPENDENCY_NOT_ACCEPTED", "Dependency is neither accepted nor selected earlier", blocker_class="dependency", packet_id=packet_id)

    if plan_fact.get("review_status") and plan_fact.get("review_status") != current_fact.get("review_status"):
        _add_blocker(blockers, "REVIEW_STATUS_CHANGED", "Review status changed since selection", blocker_class="review", packet_id=packet_id)
    if current_fact.get("review_status") != "accepted":
        _add_blocker(blockers, "REVIEW_BLOCKS_PACKET", "Latest review does not accept the packet", blocker_class="review", packet_id=packet_id)

    if plan_fact.get("evidence_status") and plan_fact.get("evidence_status") != current_fact.get("evidence_status"):
        _add_blocker(blockers, "EVIDENCE_STATUS_CHANGED", "Evidence status changed since selection", blocker_class="evidence", packet_id=packet_id)
    if current_fact.get("evidence_status") != "valid":
        _add_blocker(blockers, "EVIDENCE_BLOCKS_PACKET", "Evidence is missing or invalid", blocker_class="evidence", packet_id=packet_id)

    return blockers


# START_FUNCTION_CONTRACT
# name: recheck_nightly_batch
# purpose: Confirm a saved or generated nightly batch selection against current authoritative state.
# inputs:
#   project_config: Explicit or default project config path.
#   selection_path: Optional saved selection JSON path.
#   max_packets: Current maximum packet limit.
#   max_cost: Current maximum cost limit.
#   allow_conflicts: Selection generation flag when no saved selection is supplied.
#   allow_risky: Selection generation flag when no saved selection is supplied.
#   selection_runner: Optional test hook for in-process selection generation.
#   binding_checker: Optional test hook for Prefect binding status.
#   prefect_client: Optional injected Prefect sync client for default binding status checks.
#   prefect_client_factory: Optional factory for creating a Prefect sync client.
#   lock_factory: Optional test hook for runtime lock.
# returns: NightlyBatchRecheckResult with ready or blocked status.
# side_effects: Acquires/releases runtime lock only.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers.
# END_FUNCTION_CONTRACT
def recheck_nightly_batch(
    *,
    project_config: Path | str | None = None,
    selection_path: Path | str | None = None,
    max_packets: int = DEFAULT_MAX_PACKETS,
    max_cost: str = DEFAULT_MAX_COST,
    allow_conflicts: bool = False,
    allow_risky: bool = False,
    selection_runner: Callable[..., BatchSelectionResult] | None = None,
    binding_checker: Callable[..., Any] | None = None,
    prefect_client: Any | None = None,
    prefect_client_factory: Callable[[], Any | None] | None = None,
    lock_factory: Callable[..., RuntimeLock] | None = None,
) -> NightlyBatchRecheckResult:
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return NightlyBatchRecheckResult(
            ok=False,
            project_key="",
            side_effects=_zero_side_effects(),
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    result = NightlyBatchRecheckResult(
        ok=False,
        project_key=project.project_key,
        batch_limits={"max_packets": max_packets, "max_cost": max_cost},
        side_effects=_zero_side_effects(),
    )

    lock_builder = lock_factory or RuntimeLock
    lock = lock_builder(
        Path(project.repo_root) / project.runtime_state_root,
        name="nightly-batch-recheck",
        max_age_seconds=7200,
        allow_ephemeral=True,
    )
    lock_result = lock.acquire()
    result.lock_status = {
        "acquired": lock_result.acquired,
        "released": lock_result.released,
        "ephemeral": lock_result.ephemeral,
        "already_running": lock_result.already_running,
    }

    if not lock_result.acquired:
        _add_blocker(result.blockers, "LOCK_UNAVAILABLE", "Runtime lock unavailable", blocker_class="lock")
        result.errors.extend(lock_result.errors)
        lock.release(lock_result)
        result.lock_status.update({
            "acquired": lock_result.acquired,
            "released": lock_result.released,
            "ephemeral": lock_result.ephemeral,
            "already_running": lock_result.already_running,
        })
        result.blocked_total = 1
        result.blocker_classes = ["lock"]
        result.preflight_status = "blocked"
        result.recheck_hash = _stable_hash({"lock": result.lock_status, "blockers": result.blockers})
        return result

    try:
        if selection_path:
            plan_payload = _load_saved_selection(selection_path)
        else:
            runner = selection_runner or select_safe_batch
            plan_payload = _selection_payload(runner(
                project_config=project_config,
                max_packets=max_packets,
                max_cost=max_cost,
                allow_conflicts=allow_conflicts,
                allow_risky=allow_risky,
            ))

        result.plan_hash = _stable_hash(plan_payload)
        selected_packets = [str(pid) for pid in plan_payload.get("selected_packets") or []]
        plan_facts = {
            str(fact.get("packet_id")): dict(fact)
            for fact in (plan_payload.get("selected_packet_facts") or [])
            if isinstance(fact, dict) and fact.get("packet_id")
        }
        try:
            declared_selected_total = int(plan_payload.get("selected_total", len(selected_packets)))
        except (TypeError, ValueError):
            declared_selected_total = len(selected_packets)
            _add_blocker(
                result.blockers,
                "PLAN_SELECTED_TOTAL_INVALID",
                "Saved selected_total is not an integer",
                blocker_class="plan_integrity",
            )
        result.selected_total = declared_selected_total
        result.batch_limits.update(dict(plan_payload.get("batch_limits") or {}))
        result.batch_limits["current_max_packets"] = max_packets
        result.batch_limits["current_max_cost"] = max_cost

        result.blockers.extend(_plan_integrity_blockers(
            declared_total=declared_selected_total,
            selected_packets=selected_packets,
            plan_facts=plan_facts,
        ))
        limit_blockers = _limit_blockers(
            selected_total=declared_selected_total,
            facts_by_id=plan_facts,
            max_packets=max_packets,
            max_cost=max_cost,
        )
        result.blockers.extend(limit_blockers)

        if selected_packets:
            if binding_checker is not None:
                binding_result = binding_checker(project_config=project_config, dry_run=True, apply_deployment=False)
                client_available = True
            else:
                client = prefect_client
                if client is None:
                    client_factory = prefect_client_factory
                    if client_factory is None:
                        from prefect_grace.platform.runtime_adapter import create_prefect_sync_client
                        client_factory = create_prefect_sync_client
                    client = client_factory()
                client_available = client is not None
                binding_project_config = (
                    Path(project_config)
                    if project_config is not None
                    else Path(project.repo_root) / "prefect_grace" / "project.yaml"
                )
                binding_result = run_prefect_worker_binding_preflight(
                    project_config=binding_project_config,
                    dry_run=True,
                    apply_deployment=False,
                    prefect_client=client,
                )
            binding_ok = bool(getattr(binding_result, "ok", False))
            result.lock_status["binding_checked"] = True
            result.lock_status["prefect_client_available"] = client_available
            if not binding_ok:
                _add_blocker(
                    result.blockers,
                    "PREFECT_BINDING_NOT_READY",
                    "Prefect deployment, work pool, or queue binding is not ready",
                    blocker_class="prefect_binding",
                )
                result.errors.extend(list(getattr(binding_result, "errors", []) or []))

        repo_root = Path(project.repo_root)
        packets_dir = repo_root / project.packets_dir
        registry = PacketRegistryStore(repo_root / project.runtime_state_root / "state")
        selected_before: set[str] = set()
        current_facts: list[dict[str, Any]] = []
        global_packet_blockers = list(result.blockers)

        for packet_id in selected_packets:
            packet_blockers: list[dict[str, Any]] = []
            registry_record = registry.load_packet(packet_id)
            if registry_record:
                registry_record = dict(registry_record)
                registry_record["_dependency_records"] = {
                    dep_id: registry.load_packet(dep_id)
                    for dep_id in list(registry_record.get("depends_on") or [])
                }
            current_fact, current_fact_blockers = _current_fact(
                repo_root=repo_root,
                packets_dir=packets_dir,
                packet_id=packet_id,
                registry_record=registry_record,
            )
            current_facts.append(current_fact)
            packet_blockers.extend(current_fact_blockers)
            packet_blockers.extend(_check_packet_staleness(
                packet_id=packet_id,
                plan_fact=plan_facts.get(packet_id, {"packet_id": packet_id}),
                current_fact=current_fact,
                registry_record=registry_record,
                selected_before=set(selected_before),
            ))
            selected_before.add(packet_id)

            result.blockers.extend(packet_blockers)
            sample_blockers = global_packet_blockers + packet_blockers
            packet_status = "blocked" if sample_blockers else "confirmed"
            if packet_status == "confirmed":
                result.confirmed_total += 1
            else:
                result.blocked_total += 1
            result.packet_samples.append(PacketRecheckSummary(
                packet_id=packet_id,
                status=packet_status,
                blocker_classes=sorted({str(blocker.get("blocker_class") or "unknown") for blocker in sample_blockers}),
                blocker_codes=[str(blocker.get("code") or "") for blocker in sample_blockers[:MAX_ITEMS]],
            ))

        if result.blockers and not selected_packets:
            result.blocked_total = 1
        result.packet_samples_total = len(result.packet_samples)
        result.blocker_classes = sorted({str(blocker.get("blocker_class") or "unknown") for blocker in result.blockers})
        result.preflight_status = "blocked" if result.blockers else "ready"
        result.ok = result.preflight_status == "ready"
        result.recheck_hash = _stable_hash({
            "selected_packets": selected_packets,
            "current_facts": current_facts,
            "blocker_classes": result.blocker_classes,
            "blocker_codes": [blocker.get("code") for blocker in result.blockers],
            "batch_limits": result.batch_limits,
        })
    except Exception as exc:
        result.errors.append(_error("NIGHTLY_BATCH_RECHECK_FAILED", str(exc)))
        _add_blocker(result.blockers, "NIGHTLY_BATCH_RECHECK_FAILED", str(exc), blocker_class="recheck")
        result.blocker_classes = sorted({str(blocker.get("blocker_class") or "unknown") for blocker in result.blockers})
        result.preflight_status = "blocked"
        result.recheck_hash = _stable_hash({"errors": result.errors, "blockers": result.blockers})
    finally:
        lock.release(lock_result)
        result.lock_status.update({
            "acquired": lock_result.acquired,
            "released": lock_result.released,
            "ephemeral": lock_result.ephemeral,
            "already_running": lock_result.already_running,
        })

    return result
