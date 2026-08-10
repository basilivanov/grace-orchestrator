# ############################################################################
# AI_HEADER: test_tz06_multiworker_integration — real multi-worker runtime proof
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove the worker-facing API uses atomic safe claims, retains fenced
#          parallel leases through ACCEPTED, exposes runtime diagnostics, and
#          fails closed when multi-worker guards are disabled.
# inputs: File-backed SQLite databases, ASGI API clients, and real Worker loops.
# returns: Pytest acceptance results.
# side_effects: Creates temporary databases, packet rows, and concurrent tasks.
# emitted_logs: None.
# error_behavior: Assertions identify a TZ06 runtime integration regression.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SlowWorkerExecutor
#   - class: RealGitExecutor
#   - class: TimedGitService
#   - function: test_real_workers_overlap_on_disjoint_wave_packets
#   - function: test_scope_conflict_waits_then_worker_runs
#   - function: test_conflict_key_waits_then_worker_runs
#   - function: test_dependency_waits_for_merged_producer_and_uses_fresh_base
#   - function: test_stale_runtime_recheck_preserves_target_on_conflict_or_verification
#   - function: test_parallel_merge_requires_exact_fencing_identity
#   - function: test_concurrency_one_real_workers_remain_sequential
#   - function: test_parallel_mode_fails_closed_when_scope_guard_disabled
#   - function: test_accepted_packet_renews_parallel_lease
#   - function: test_diagnostics_surface_parallel_runtime_state
#   - function: test_cleanup_reclaims_crashed_accepted_packet
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from grace_control.adapters.packet_executor import ExecutionResult
from grace_control.api.main import app
from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketRun, PacketState, ParallelLease, Wave
from grace_control.db.schema import Worker as DBWorker
from grace_control.services.git_service import GitService
from grace_control.services.parallel_lease_service import ParallelLeaseService
from grace_control.services.supervisor_cleanup_service import SupervisorCleanupService
from grace_control.worker.api_client import WorkerAPIClient
from grace_control.worker.worker import Worker

_log = GraceLogger("test_tz06_multiworker")


# START_BLOCK_HELPERS

def _seed_wave(packet_count: int, worker_count: int) -> None:
    with get_db() as db:
        db.add(Feature(
            id="tz06-feature",
            slug="tz06-feature",
            title="TZ06 feature",
            spec_json={},
            status="active",
        ))
        db.add(Wave(
            id="tz06-wave",
            feature_id="tz06-feature",
            slug="tz06-wave",
            title="TZ06 wave",
            order=1,
            status="IN_PROGRESS",
        ))
        for index in range(worker_count):
            db.add(DBWorker(id=f"tz06-worker-{index}", status="idle"))
        for index in range(packet_count):
            packet_id = f"tz06-packet-{index}"
            db.add(Packet(
                id=packet_id,
                feature_id="tz06-feature",
                wave_id="tz06-wave",
                slug=packet_id,
                title=packet_id,
                spec_json={
                    "scope": [f"src/tz06/{index}.py"],
                    "conflict_keys": [],
                    "depends_on": [],
                },
                state=PacketState.READY.value,
                attempt_count=0,
                max_attempts=3,
            ))


@dataclass
class SlowWorkerExecutor:
    """Artificially slow coder seam used only to expose execution overlap."""

    delay_seconds: float = 0.08
    intervals: list[tuple[str, float, float]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Hold one claimed packet in execution long enough for peers to
    #          claim and execute independently.
    # inputs: packet_id, worker_id, claim_data.
    # returns: Recoverable blocked result after the slow execution interval.
    # side_effects: Records monotonic start/end timestamps in memory.
    # emitted_logs: None.
    # error_behavior: None for valid claim data.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str, claim_data: dict) -> ExecutionResult:
        del claim_data
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(self.delay_seconds)
        finished = asyncio.get_running_loop().time()
        self.intervals.append((worker_id, started, finished))
        return ExecutionResult(
            accepted=False,
            domain_status="blocked",
            reason="tz06_slow_smoke_complete",
            duration_ms=int((finished - started) * 1000),
        )


async def _worker(
    worker_id: str,
    executor,
    target_repo_root: Path | None = None,
) -> Worker:
    client = WorkerAPIClient("http://tz06.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tz06.test",
    )
    worker = Worker.__new__(Worker)
    worker.worker_id = worker_id
    worker.api = client
    worker.executor = executor
    worker.running = True
    worker.log = _log
    worker._git_context = SimpleNamespace(
        target_repo_root=target_repo_root or Path.cwd()
    )
    worker._active_packet_id = None
    worker._active_lease_id = None
    worker._active_claimed_attempt = None
    worker._active_parallel_lease_id = None
    worker._active_lease_released = False
    worker._active_lease_loss_reason = ""
    return worker


@dataclass
class RealGitExecutor:
    """Create real packet worktrees and commits for the TZ006 proof."""

    target_repo_root: Path
    delay_seconds: float = 0.04
    hold: asyncio.Event | None = None
    advance_target: tuple[str, str] | None = None
    intervals: list[tuple[str, float, float]] = field(default_factory=list)
    base_shas: dict[str, str] = field(default_factory=dict)
    advanced_sha: str = ""
    started_events: dict[str, asyncio.Event] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Materialize an isolated real git worktree, commit the packet
    #          change, and return accepted Worker execution metadata.
    # inputs: packet_id, worker_id, claim_data — real Worker claim context.
    # returns: Accepted ExecutionResult with branch, worktree, and commit SHA.
    # side_effects: Creates git worktrees/branches, commits files, and records
    #               file-backed PacketRun base snapshots.
    # emitted_logs: None.
    # error_behavior: Propagates git or database setup errors to Worker.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str, claim_data: dict) -> ExecutionResult:
        del worker_id
        loop = asyncio.get_running_loop()
        started = loop.time()
        self.started_events.setdefault(packet_id, asyncio.Event()).set()
        spec = claim_data.get("spec", {})
        target = self.target_repo_root.resolve()
        base_sha = _git_output(target, "rev-parse", "main")
        self.base_shas[packet_id] = base_sha
        attempt = int(claim_data.get("attempt", 1))
        branch = f"agent/{packet_id}-attempt-{attempt:04d}"
        worktree = target.parent / f"{target.name}-worktrees" / packet_id
        _run_git(target, "worktree", "add", "-b", branch, str(worktree), "main")
        relative_path = str((spec.get("scope") or [f"src/tz06/{packet_id}.py"])[0])
        if relative_path.endswith("/"):
            relative_path = f"{relative_path}{packet_id}.txt"
        packet_file = worktree / relative_path
        packet_file.parent.mkdir(parents=True, exist_ok=True)
        packet_file.write_text(f"packet:{packet_id}\n")
        _run_git(worktree, "add", relative_path)
        _run_git(worktree, "commit", "-m", f"packet {packet_id}")
        commit_sha = _git_output(worktree, "rev-parse", "HEAD")
        self._persist_base_snapshot(packet_id, attempt, base_sha, spec)

        if self.advance_target is not None:
            advance_path, advance_content = self.advance_target
            target_file = target / advance_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(advance_content)
            _run_git(target, "add", advance_path)
            _run_git(target, "commit", "-m", f"advance target for {packet_id}")
            self.advanced_sha = _git_output(target, "rev-parse", "main")

        if self.hold is not None:
            await self.hold.wait()
        else:
            await asyncio.sleep(self.delay_seconds)
        finished = loop.time()
        self.intervals.append((packet_id, started, finished))
        return ExecutionResult(
            accepted=True,
            domain_status="accepted",
            worktree_path=str(worktree),
            branch_name=branch,
            commit_sha=commit_sha,
            duration_ms=int((finished - started) * 1000),
        )

    def _persist_base_snapshot(
        self,
        packet_id: str,
        attempt: int,
        base_sha: str,
        spec: dict,
    ) -> None:
        with get_db() as db:
            run_id = f"{packet_id}-R{attempt:02d}"
            run = db.query(PacketRun).filter_by(
                id=run_id
            ).first()
            if run is None:
                run = PacketRun(
                    id=run_id,
                    packet_id=packet_id,
                    run_number=attempt,
                    status="running",
                    started_at=datetime.now(UTC),
                )
                db.add(run)
                db.flush()
            run.base_sha = base_sha
            run.result_json = {
                "parallel_execution": {
                    "base_sha": base_sha,
                    "conflict_keys": list(spec.get("conflict_keys", [])),
                }
            }
            db.commit()


class TimedGitService(GitService):
    """Run real git while recording target mutation intervals."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Attach a shared mutation timeline to a real GitService.
    # inputs: timeline — mutable target-operation interval list.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        timeline: list[tuple[str, float, float]],
        target_repo_root: Path | None = None,
    ) -> None:
        self.timeline = timeline
        self.target_repo_root = target_repo_root.resolve() if target_repo_root else None
        self.target_branch_mutations: list[str] = []

    # START_FUNCTION_CONTRACT
    # name: _run
    # purpose: Execute real git and record mutating target commands.
    # inputs: args, cwd, timeout — GitService command parameters.
    # returns: GitResult from the real command.
    # side_effects: Executes git subprocesses and records selected intervals.
    # emitted_logs: None.
    # error_behavior: Preserves GitService's non-raising GitResult behavior.
    # END_FUNCTION_CONTRACT
    def _run(self, args, cwd, timeout=None):
        mutating = bool(args) and (
            args[0] in {"checkout", "fetch", "merge", "push", "worktree"}
            or (args[0] == "branch" and "-D" in args)
        )
        started = asyncio.get_running_loop().time() if mutating else 0.0
        result = super()._run(args, cwd, timeout)
        if mutating:
            self.timeline.append((str(args[0]), started, asyncio.get_running_loop().time()))
            if (
                self.target_repo_root is not None
                and Path(cwd).resolve() == self.target_repo_root
                and args[0] in {"checkout", "merge", "push"}
            ):
                self.target_branch_mutations.append(str(args[0]))
        return result


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _target_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "tz06-target"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "branch", "-M", "main")
    _run_git(repo, "config", "user.email", "tz06@example.test")
    _run_git(repo, "config", "user.name", "TZ06")
    (repo / "README.md").write_text("tz06\n")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial target")
    return repo, _git_output(repo, "rev-parse", "main")


def _seed_runtime_wave(packets: list[dict], worker_count: int = 4) -> None:
    now = datetime.now(UTC)
    with get_db() as db:
        db.add(Feature(
            id="tz06-runtime-feature",
            slug="tz06-runtime-feature",
            title="TZ06 runtime feature",
            spec_json={},
            status="active",
        ))
        db.add(Wave(
            id="tz06-runtime-wave",
            feature_id="tz06-runtime-feature",
            slug="tz06-runtime-wave",
            title="TZ06 runtime wave",
            order=1,
            status="IN_PROGRESS",
        ))
        for index in range(worker_count):
            db.add(DBWorker(id=f"tz06-runtime-worker-{index}", status="idle"))
        for index, item in enumerate(packets):
            spec = {
                "scope": list(item.get("scope", [])),
                "conflict_keys": list(item.get("conflict_keys", [])),
                "depends_on": list(item.get("depends_on", [])),
                "target_repo_root": item["target_repo_root"],
                "verification": item.get(
                    "verification",
                    {"t1": [["python3", "-c", "pass"]]},
                ),
            }
            db.add(Packet(
                id=item["id"],
                feature_id="tz06-runtime-feature",
                wave_id="tz06-runtime-wave",
                slug=item.get("slug", item["id"]),
                title=item.get("title", item["id"]),
                spec_json=spec,
                state=PacketState.READY.value,
                acceptance_profile=item.get("acceptance_profile", "NORMAL"),
                attempt_count=0,
                max_attempts=3,
                created_at=now + timedelta(microseconds=index),
            ))


async def _wait_for_executor_start(executor: RealGitExecutor, packet_id: str) -> None:
    for _ in range(200):
        if packet_id in executor.started_events:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"executor did not start for {packet_id}")


def _assert_non_overlapping_mutations(timeline: list[tuple[str, float, float]]) -> None:
    ordered = sorted(timeline, key=lambda item: item[1])
    for left, right in zip(ordered, ordered[1:], strict=False):
        assert left[2] <= right[1], f"target mutation overlap: {left} vs {right}"


# END_BLOCK_HELPERS


# START_BLOCK_TESTS

# START_FUNCTION_CONTRACT
# name: test_real_workers_overlap_on_disjoint_wave_packets
# purpose: Prove four real Worker cycles claim and execute disjoint same-wave
#          packets concurrently through the file-backed API claim path.
# inputs: api — isolated ASGI client fixture; tmp_path — test database root.
# returns: None.
# side_effects: Runs concurrent worker tasks and writes packet/lease state.
# emitted_logs: None.
# error_behavior: Assertion failure on missing overlap or duplicate claims.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_real_workers_overlap_on_disjoint_wave_packets(api, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, _initial_sha = _target_repo(tmp_path)
    _seed_runtime_wave([
        {
            "id": f"tz06-real-packet-{index}",
            "scope": [f"src/tz06/{index}.py"],
            "target_repo_root": str(repo),
        }
        for index in range(4)
    ])
    executor = RealGitExecutor(repo)
    timeline: list[tuple[str, float, float]] = []
    from grace_control.services import merge_service as merge_module

    monkeypatch.setattr(
        merge_module,
        "GitService",
        lambda: TimedGitService(timeline),
    )
    workers = [
        await _worker(
            f"tz06-runtime-worker-{index}",
            executor,
            target_repo_root=repo,
        )
        for index in range(4)
    ]
    try:
        await asyncio.gather(*(worker._run_one_cycle(1) for worker in workers))
    finally:
        await asyncio.gather(*(worker.api.close() for worker in workers))

    assert len(executor.intervals) == 4
    ordered = sorted(executor.intervals, key=lambda item: item[1])
    assert any(
        left[1] < right[1] < left[2]
        for left, right in zip(ordered, ordered[1:], strict=True)
    )
    _assert_non_overlapping_mutations(timeline)
    assert timeline
    with get_db() as db:
        assert db.query(Packet).filter_by(state=PacketState.MERGED.value).count() == 4
        runs = db.query(PacketRun).all()
        assert any(
            run.result_json["parallel_execution"]["integration_recheck"] == "passed"
            for run in runs
            if isinstance(run.result_json, dict)
            and isinstance(run.result_json.get("parallel_execution"), dict)
            and run.result_json["parallel_execution"].get("stale_base")
        )
    assert all((repo / f"src/tz06/{index}.py").exists() for index in range(4))


# START_FUNCTION_CONTRACT
# name: test_scope_conflict_waits_then_worker_runs
# purpose: Prove a same-scope frontier returns a typed wait to a competing
#          real Worker and the waiter runs after the owner is MERGED.
# inputs: api, tmp_path, monkeypatch — file DB, target repo, and concurrency.
# returns: None.
# side_effects: Runs two real Worker/API claim-release-merge cycles.
# emitted_logs: None.
# error_behavior: Assertion failure on unsafe overlap or missing progress.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_scope_conflict_waits_then_worker_runs(api, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, _initial_sha = _target_repo(tmp_path)
    _seed_runtime_wave([
        {
            "id": "tz06-scope-a",
            "scope": ["src/tz06/shared.py"],
            "target_repo_root": str(repo),
        },
        {
            "id": "tz06-scope-b",
            "scope": ["src/tz06/shared.py"],
            "target_repo_root": str(repo),
        },
    ], worker_count=2)
    hold = asyncio.Event()
    executor = RealGitExecutor(repo, hold=hold)
    workers = [
        await _worker(f"tz06-runtime-worker-{index}", executor, repo)
        for index in range(2)
    ]
    first_task = asyncio.create_task(workers[0]._run_one_cycle(1))
    try:
        await _wait_for_executor_start(executor, "tz06-scope-a")
        waiting = await api.post(
            "/api/packets/claim",
            json={"worker_id": "tz06-runtime-worker-1"},
        )
        assert waiting.status_code == 404
        assert waiting.json()["detail"] == "waiting_for_scope_conflict"
        hold.set()
        await first_task
        await workers[1]._run_one_cycle(1)
    finally:
        hold.set()
        if not first_task.done():
            await first_task
        await asyncio.gather(*(worker.api.close() for worker in workers))

    with get_db() as db:
        assert db.query(Packet).filter_by(state=PacketState.MERGED.value).count() == 2


# START_FUNCTION_CONTRACT
# name: test_conflict_key_waits_then_worker_runs
# purpose: Prove a same-conflict-key/different-scope frontier is serialized by
#          the real API claim path and later makes progress.
# inputs: api, tmp_path, monkeypatch — file DB, target repo, and concurrency.
# returns: None.
# side_effects: Runs two real Worker/API claim-release-merge cycles.
# emitted_logs: None.
# error_behavior: Assertion failure on missing key wait or duplicate merge.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_conflict_key_waits_then_worker_runs(api, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, _initial_sha = _target_repo(tmp_path)
    _seed_runtime_wave([
        {
            "id": "tz06-key-a",
            "scope": ["src/tz06/key_a.py"],
            "conflict_keys": ["db:schema"],
            "target_repo_root": str(repo),
        },
        {
            "id": "tz06-key-b",
            "scope": ["src/tz06/key_b.py"],
            "conflict_keys": ["db:schema"],
            "target_repo_root": str(repo),
        },
    ], worker_count=2)
    hold = asyncio.Event()
    executor = RealGitExecutor(repo, hold=hold)
    workers = [
        await _worker(f"tz06-runtime-worker-{index}", executor, repo)
        for index in range(2)
    ]
    first_task = asyncio.create_task(workers[0]._run_one_cycle(1))
    try:
        await _wait_for_executor_start(executor, "tz06-key-a")
        waiting = await api.post(
            "/api/packets/claim",
            json={"worker_id": "tz06-runtime-worker-1"},
        )
        assert waiting.status_code == 404
        assert waiting.json()["detail"] == "waiting_for_conflict_key"
        hold.set()
        await first_task
        await workers[1]._run_one_cycle(1)
    finally:
        hold.set()
        if not first_task.done():
            await first_task
        await asyncio.gather(*(worker.api.close() for worker in workers))

    with get_db() as db:
        assert db.query(Packet).filter_by(state=PacketState.MERGED.value).count() == 2


# START_FUNCTION_CONTRACT
# name: test_dependency_waits_for_merged_producer_and_uses_fresh_base
# purpose: Prove a dependency consumer waits for MERGED, then its real
#          workspace/base snapshot starts at the producer's fresh target HEAD.
# inputs: api, tmp_path, monkeypatch — file DB, target repo, and concurrency.
# returns: None.
# side_effects: Runs producer and consumer Worker/API cycles against real git.
# emitted_logs: None.
# error_behavior: Assertion failure on premature claim or stale consumer base.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_dependency_waits_for_merged_producer_and_uses_fresh_base(
    api,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, _initial_sha = _target_repo(tmp_path)
    _seed_runtime_wave([
        {
            "id": "tz06-dep-producer",
            "title": "producer",
            "scope": ["src/tz06/producer.py"],
            "target_repo_root": str(repo),
        },
        {
            "id": "tz06-dep-consumer",
            "title": "consumer",
            "scope": ["src/tz06/consumer.py"],
            "depends_on": ["producer"],
            "target_repo_root": str(repo),
        },
    ], worker_count=2)
    hold = asyncio.Event()
    executor = RealGitExecutor(repo, hold=hold)
    workers = [
        await _worker(f"tz06-runtime-worker-{index}", executor, repo)
        for index in range(2)
    ]
    first_task = asyncio.create_task(workers[0]._run_one_cycle(1))
    try:
        await _wait_for_executor_start(executor, "tz06-dep-producer")
        waiting = await api.post(
            "/api/packets/claim",
            json={"worker_id": "tz06-runtime-worker-1"},
        )
        assert waiting.status_code == 404
        assert waiting.json()["detail"] == "waiting_for_dependency"
        hold.set()
        await first_task
        producer_head = _git_output(repo, "rev-parse", "main")
        await workers[1]._run_one_cycle(1)
    finally:
        hold.set()
        if not first_task.done():
            await first_task
        await asyncio.gather(*(worker.api.close() for worker in workers))

    assert executor.base_shas["tz06-dep-consumer"] == producer_head
    with get_db() as db:
        assert db.query(Packet).filter_by(state=PacketState.MERGED.value).count() == 2


# START_FUNCTION_CONTRACT
# name: test_stale_runtime_recheck_preserves_target_on_conflict_or_verification
# purpose: Prove the real Worker/API merge path rechecks an independently stale
#          ACCEPTED packet and leaves target HEAD unchanged on conflict or T1
#          verification failure.
# inputs: api, tmp_path, monkeypatch, mode — isolated runtime and failure mode.
# returns: None.
# side_effects: Creates real packet/target commits and disposable recheck trees.
# emitted_logs: None.
# error_behavior: Assertion failure on target mutation or missing TZ05 evidence.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["conflict", "verification"])
async def test_stale_runtime_recheck_preserves_target_on_conflict_or_verification(
    api,
    tmp_path: Path,
    monkeypatch,
    mode: str,
):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, initial_sha = _target_repo(tmp_path)
    packet = {
        "id": f"tz06-stale-{mode}",
        "scope": ["value.txt" if mode == "conflict" else "packet.txt"],
        "target_repo_root": str(repo),
    }
    if mode == "verification":
        packet.update({
            "acceptance_profile": "NORMAL",
            "verification": {
                "t1": [["sh", "-c", "exit 1"]],
            },
        })
    _seed_runtime_wave([packet], worker_count=1)
    advance = (
        ("value.txt", "target\n")
        if mode == "conflict"
        else ("target.txt", "target\n")
    )
    executor = RealGitExecutor(repo, advance_target=advance)
    timeline: list[tuple[str, float, float]] = []
    timed_git = TimedGitService(timeline, repo)
    from grace_control.services import merge_service as merge_module

    monkeypatch.setattr(merge_module, "GitService", lambda: timed_git)
    worker = await _worker("tz06-runtime-worker-0", executor, repo)
    try:
        await worker._run_one_cycle(1)
    finally:
        await worker.api.close()

    assert initial_sha != executor.advanced_sha
    assert _git_output(repo, "rev-parse", "main") == executor.advanced_sha
    assert not timed_git.target_branch_mutations
    with get_db() as db:
        packet_row = db.query(Packet).filter_by(id=packet["id"]).one()
        run = db.query(PacketRun).filter_by(packet_id=packet["id"]).one()
        assert packet_row.state == PacketState.BLOCKED_RECOVERABLE.value
        expected_failure = (
            "stale_base_conflict"
            if mode == "conflict"
            else "integration_verification_failed"
        )
        assert run.result_json["failure_class"] == expected_failure
        assert run.result_json["parallel_execution"]["integration_recheck"] == "failed"
    if mode == "conflict":
        assert (repo / "value.txt").read_text() == "target\n"
    else:
        assert (repo / "target.txt").read_text() == "target\n"


# START_FUNCTION_CONTRACT
# name: test_parallel_merge_requires_exact_fencing_identity
# purpose: Prove parallel ACCEPTED merge requests without or with stale TZ03
#          identity fail before checkout/merge/push mutation.
# inputs: api, tmp_path, monkeypatch — accepted packet and real target repo.
# returns: None.
# side_effects: Calls the real merge API twice with invalid fencing identity.
# emitted_logs: None.
# error_behavior: Assertion failure on fail-open merge or target mutation.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_parallel_merge_requires_exact_fencing_identity(api, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    repo, _initial_sha = _target_repo(tmp_path)
    _seed_runtime_wave([{
        "id": "tz06-fenced-merge",
        "scope": ["src/tz06/fenced.py"],
        "target_repo_root": str(repo),
    }], worker_count=1)
    claim_response = await api.post(
        "/api/packets/claim",
        json={"worker_id": "tz06-runtime-worker-0"},
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()["data"]
    release_response = await api.post(
        "/api/packets/tz06-fenced-merge/release",
        json={
            "worker_id": "tz06-runtime-worker-0",
            "lease_id": claim["lease_id"],
            "claimed_attempt": claim["claimed_attempt"],
            "status": "accepted",
            "result": {"accepted": True},
        },
    )
    assert release_response.status_code == 200

    timeline: list[tuple[str, float, float]] = []
    timed_git = TimedGitService(timeline, repo)
    from grace_control.services import merge_service as merge_module

    monkeypatch.setattr(merge_module, "GitService", lambda: timed_git)
    merge_payload = {
        "target_repo_root": str(repo),
        "worktree_path": str(repo / "not-a-worktree"),
        "branch_name": "agent/tz06-fenced-merge-attempt-0001",
        "worker_id": "tz06-runtime-worker-0",
    }
    missing = await api.post(
        "/api/packets/tz06-fenced-merge/merge",
        json=merge_payload,
    )
    assert missing.status_code == 409
    assert "parallel_lease_lost" in missing.json()["detail"]["merge_failed"]
    wrong = await api.post(
        "/api/packets/tz06-fenced-merge/merge",
        json={
            **merge_payload,
            "parallel_lease_id": "stale-parallel-lease",
            "claimed_attempt": claim["claimed_attempt"],
        },
    )
    assert wrong.status_code == 409
    assert "parallel_lease_lost" in wrong.json()["detail"]["merge_failed"]
    assert timed_git.target_branch_mutations == []
    with get_db() as db:
        assert db.query(ParallelLease).filter_by(
            packet_id="tz06-fenced-merge"
        ).one_or_none() is not None


# START_FUNCTION_CONTRACT
# name: test_concurrency_one_real_workers_remain_sequential
# purpose: Prove the real worker/API claim path retains one-active-packet
#          behavior and allows the next contender only after release.
# inputs: api, tmp_path, monkeypatch — file DB and two Worker contenders.
# returns: None.
# side_effects: Claims/releases packets through the real API routes.
# emitted_logs: None.
# error_behavior: Assertion failure if two packets are active concurrently.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_concurrency_one_real_workers_remain_sequential(api, tmp_path: Path, monkeypatch):
    del tmp_path
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "1")
    _seed_wave(packet_count=2, worker_count=2)
    executor = SlowWorkerExecutor(delay_seconds=0.01)
    workers = [
        await _worker(f"tz06-worker-{index}", executor)
        for index in range(2)
    ]
    try:
        claims = await asyncio.gather(*(worker._phase_claim() for worker in workers))
        assert sum(claim is not None for claim in claims) == 1
        winner = next(worker for worker, claim in zip(workers, claims, strict=True) if claim)
        claim = next(claim for claim in claims if claim)
        await winner.api.release_packet(
            claim.packet_id,
            winner.worker_id,
            "rejected",
            {"accepted": False, "reason": "sequential-proof"},
            lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
        )
        next_claim = await workers[1]._phase_claim()
        if next_claim is None:
            next_claim = await workers[0]._phase_claim()
        assert next_claim is not None
    finally:
        await asyncio.gather(*(worker.api.close() for worker in workers))
# START_FUNCTION_CONTRACT
# name: test_parallel_mode_fails_closed_when_scope_guard_disabled
# purpose: Prove max concurrency cannot silently select the legacy unsafe claim
#          path when the required scope guard is disabled.
# inputs: api — isolated ASGI client fixture; monkeypatch — runtime overrides.
# returns: None.
# side_effects: Performs one rejected API claim request.
# emitted_logs: None.
# error_behavior: Assertion failure if unsafe mode is accepted.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_parallel_mode_fails_closed_when_scope_guard_disabled(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    monkeypatch.setattr(settings, "parallel_scope_guard_enabled", False)
    response = await api.post("/api/packets/claim", json={"worker_id": "tz06-unsafe"})
    assert response.status_code == 503
    assert response.json()["detail"].startswith("parallel_safety_disabled:")


# START_FUNCTION_CONTRACT
# name: test_accepted_packet_renews_parallel_lease
# purpose: Prove the worker-facing API retains and renews the parallel lease
#          after ordinary RUNNING ownership is released as ACCEPTED.
# inputs: api — isolated ASGI client fixture; monkeypatch — concurrency setting.
# returns: None.
# side_effects: Claims, accepts, and renews one packet lease.
# emitted_logs: None.
# error_behavior: Assertion failure on missing retained lease renewal.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_accepted_packet_renews_parallel_lease(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed_wave(packet_count=1, worker_count=1)
    claim_response = await api.post(
        "/api/packets/claim",
        json={"worker_id": "tz06-worker-0"},
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()["data"]
    release_response = await api.post(
        f"/api/packets/{claim['packet_id']}/release",
        json={
            "worker_id": "tz06-worker-0",
            "lease_id": claim["lease_id"],
            "claimed_attempt": claim["claimed_attempt"],
            "status": "accepted",
            "result": {"accepted": True},
        },
    )
    assert release_response.status_code == 200
    renew_response = await api.post(
        f"/api/packets/{claim['packet_id']}/renew-parallel-lease",
        json={
            "worker_id": "tz06-worker-0",
            "parallel_lease_id": claim["parallel_lease_id"],
            "claimed_attempt": claim["claimed_attempt"],
        },
    )
    assert renew_response.status_code == 200
    assert renew_response.json()["data"]["renewed"] is True


# START_FUNCTION_CONTRACT
# name: test_diagnostics_surface_parallel_runtime_state
# purpose: Prove the diagnostics API exposes effective concurrency, active
#          workers/parallel leases, and packet base/recheck read models.
# inputs: api — isolated ASGI client fixture; monkeypatch — concurrency setting.
# returns: None.
# side_effects: Claims one packet and reads the diagnostics endpoint.
# emitted_logs: None.
# error_behavior: Assertion failure on missing operational fields.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_diagnostics_surface_parallel_runtime_state(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed_wave(packet_count=1, worker_count=1)
    claim_response = await api.post(
        "/api/packets/claim",
        json={"worker_id": "tz06-worker-0"},
    )
    assert claim_response.status_code == 200
    diagnostics = await api.get("/api/diagnostics/state")
    assert diagnostics.status_code == 200
    data = diagnostics.json()["data"]
    assert data["effective_max_concurrency"] == 4
    assert data["active_workers"] == 1
    assert data["active_parallel_lease_count"] == 1
    assert data["active_parallel_leases"][0]["packet_id"] == "tz06-packet-0"


# START_FUNCTION_CONTRACT
# name: test_cleanup_reclaims_crashed_accepted_packet
# purpose: Prove stale cleanup fences an ACCEPTED packet whose worker died
#          after ordinary release and before serialized merge.
# inputs: api — isolated file-backed database; tmp_path — cleanup roots.
# returns: None on success.
# side_effects: Inserts an expired parallel lease and runs cleanup recovery.
# emitted_logs: None.
# error_behavior: Assertion failure if stale accepted ownership survives.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_cleanup_reclaims_crashed_accepted_packet(api, tmp_path: Path):
    packet_id = "tz06-crashed-accepted"
    with get_db() as db:
        db.add(Packet(
            id=packet_id,
            feature_id="tz06-feature",
            wave_id="tz06-wave",
            slug=packet_id,
            title=packet_id,
            spec_json={"scope": ["src/tz06/crashed.py"], "conflict_keys": []},
            state=PacketState.ACCEPTED.value,
            attempt_count=1,
            max_attempts=3,
        ))
        db.add(DBWorker(
            id="tz06-crashed-worker",
            status="active",
            current_packet_id=packet_id,
        ))
        lease = ParallelLeaseService(ttl_seconds=30).acquire(
            db,
            packet_id=packet_id,
            feature_id="tz06-feature",
            wave_id="tz06-wave",
            worker_id="tz06-crashed-worker",
            claimed_attempt=1,
            scope=["src/tz06/crashed.py"],
            conflict_keys=[],
            base_sha="a" * 40,
            now=datetime.now(UTC) - timedelta(minutes=2),
        )
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        stale_lease_id = lease.id

    target = tmp_path / "cleanup-target"
    source = tmp_path / "cleanup-source"
    target.mkdir()
    source.mkdir()
    report = SupervisorCleanupService(target, source).run(
        worktrees=False,
        state_files=False,
        stale_lease_minutes=1,
    )

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).one()
        assert packet.state == PacketState.BLOCKED_RECOVERABLE.value
        assert db.query(DBWorker).filter_by(id="tz06-crashed-worker").one().current_packet_id is None
        assert db.query(ParallelLease).filter_by(packet_id=packet_id).one_or_none() is None
    assert report.stale_leases_released == 1
    stale_merge = await api.post(
        f"/api/packets/{packet_id}/merge",
        json={
            "target_repo_root": str(target),
            "worktree_path": str(target / "stale-worktree"),
            "branch_name": f"agent/{packet_id}",
            "worker_id": "tz06-crashed-worker",
            "parallel_lease_id": stale_lease_id,
            "claimed_attempt": 1,
        },
    )
    assert stale_merge.status_code == 400


# END_BLOCK_TESTS
