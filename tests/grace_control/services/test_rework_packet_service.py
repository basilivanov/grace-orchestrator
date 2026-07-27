"""Tests for ReworkPacketService — pure logic + DB integration."""

from __future__ import annotations

from copy import deepcopy

import pytest

from grace_control.core.uid import generate_unique_id, new_packet_uid
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave
from grace_control.services.rework_packet_service import (
    ArchitectRepackConflictError,
    ArchitectRepackValidationError,
    RUNTIME_FAILURE_CODES,
    create_architect_repack_packet,
    create_rework_packet,
    resolve_rework_spec,
)


def test_resolve_rework_spec_preserves_runtime_recovery_selectors(db):
    with get_db() as d:
        packet = Packet(
            id="pkt-runtime-selector",
            feature_id="feat-runtime-selector",
            wave_id="W01",
            slug="runtime-selector",
            title="Runtime selector",
            spec_json={
                "scope": ["src/"],
                "recovery": {"requested_executor_id": "coder-mini-swe"},
                "rerun_stage": "verifier",
            },
            acceptance_profile="STRICT",
            attempt_count=2,
            max_attempts=3,
            state=PacketState.BLOCKED_RECOVERABLE.value,
        )
        d.add(packet)
        d.commit()

        resolved = resolve_rework_spec(d, packet)

    assert resolved["recovery"]["requested_executor_id"] == "coder-mini-swe"
    assert resolved["rerun_stage"] == "verifier"


def test_resolve_rework_spec_does_not_inherit_parent_runtime_state(db):
    with get_db() as d:
        parent = Packet(
            id="pkt-runtime-parent",
            feature_id="feat-runtime-lineage",
            wave_id="W01",
            slug="runtime-parent",
            title="Runtime parent",
            spec_json={
                "scope": ["src/"],
                "recovery": {"requested_executor_id": "coder-mini-swe"},
                "rerun_stage": "verifier",
                "architect_repair": {"reason": "old contract"},
            },
            acceptance_profile="STRICT",
            attempt_count=3,
            max_attempts=3,
            state=PacketState.BLOCKED_FINAL.value,
        )
        child = Packet(
            id="pkt-runtime-child",
            feature_id="feat-runtime-lineage",
            wave_id="W01",
            slug="runtime-child",
            title="Runtime child",
            spec_json={
                "origin": "review_rework",
                "parent_packet_id": parent.id,
                "scope": ["src/", "tests/"],
            },
            acceptance_profile="STRICT",
            attempt_count=0,
            max_attempts=3,
            state=PacketState.READY.value,
        )
        d.add_all([parent, child])
        d.commit()

        resolved = resolve_rework_spec(d, child)

    assert "recovery" not in resolved
    assert "rerun_stage" not in resolved
    assert "architect_repair" not in resolved
    assert resolved["scope"] == ["src/", "tests/"]


def test_resolve_rework_spec_preserves_current_child_runtime_state(db):
    with get_db() as d:
        parent = Packet(
            id="pkt-current-runtime-parent",
            feature_id="feat-current-runtime-lineage",
            wave_id="W01",
            slug="current-runtime-parent",
            title="Current runtime parent",
            spec_json={"scope": ["src/"]},
            acceptance_profile="STRICT",
            attempt_count=1,
            max_attempts=3,
            state=PacketState.REJECTED.value,
        )
        child = Packet(
            id="pkt-current-runtime-child",
            feature_id="feat-current-runtime-lineage",
            wave_id="W01",
            slug="current-runtime-child",
            title="Current runtime child",
            spec_json={
                "origin": "review_rework",
                "parent_packet_id": parent.id,
                "scope": ["src/"],
                "recovery": {"requested_executor_id": "coder-deepseek"},
                "rerun_stage": "reviewer",
            },
            acceptance_profile="STRICT",
            attempt_count=1,
            max_attempts=3,
            state=PacketState.BLOCKED_RECOVERABLE.value,
        )
        d.add_all([parent, child])
        d.commit()

        resolved = resolve_rework_spec(d, child)

    assert resolved["recovery"]["requested_executor_id"] == "coder-deepseek"
    assert resolved["rerun_stage"] == "reviewer"


class TestCreateReworkPacket:
    """Unit tests for create_rework_packet()."""

    def test_creates_packet_with_origin_review_rework(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-original-001",
                feature_id="feat-001",
                wave_id="W01",
                slug="test-packet",
                title="Original Packet",
                spec_json={
                    "scope": ["src/grace_control/"],
                    "frozen_scope": ["docs/archived/"],
                    "verification": {"t1": [["echo", "ok"]]},
                    "expected_evidence": [{
                        "id": "EV-ORIGINAL",
                        "kind": "test",
                        "artifact_patterns": ["verification-output/original.log"],
                    }],
                    "acceptance_criteria": ["Original contract still holds"],
                    "depends_on": ["Earlier Packet"],
                    "target_repo_root": "/tmp/repo",
                    "workspace_mode": "target_repo_worktree",
                },
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-original-001",
                feature_id="feat-001",
                wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL",
                title="Original Packet",
                slug="test-packet",
                max_attempts=3,
                verdict_source="reviewer",
                summary="Tests need fixing",
                blocking_issues=["test_foo fails", "test_bar missing"],
                coder_instructions=["Fix the tests"],
                rework_base_sha="a" * 40,
            )
            d.commit()

            assert rework.id.startswith("pkt_")
            assert rework.feature_id == "feat-001"
            assert rework.wave_id == "W01"
            assert rework.state == PacketState.READY.value
            assert rework.acceptance_profile == "NORMAL"
            assert rework.attempt_count == 0
            assert rework.max_attempts == 3
            assert "rework" in rework.slug

            spec = rework.spec_json
            assert spec["origin"] == "review_rework"
            assert spec["parent_packet_id"] == "pkt-original-001"
            assert spec["original_packet_id"] == "pkt-original-001"
            assert spec["scope"] == ["src/grace_control/"]
            assert spec["frozen_scope"] == ["docs/archived/"]
            assert spec["target_repo_root"] == "/tmp/repo"
            assert spec["workspace_mode"] == "target_repo_worktree"
            assert spec["expected_evidence"] == [{
                "id": "EV-ORIGINAL",
                "kind": "test",
                "artifact_patterns": ["verification-output/original.log"],
            }]
            assert spec["acceptance_criteria"] == ["Original contract still holds"]
            assert spec["depends_on"] == ["Earlier Packet"]
            assert spec["priority"] == "immediate"
            assert spec["rework_source"] == "reviewer"
            assert spec["rework_summary"] == "Tests need fixing"
            assert spec["rework_base_sha"] == "a" * 40
            assert spec["coder_ladder_base_attempt"] == 2
            assert spec["blocking_issues"] == ["test_foo fails", "test_bar missing"]
            assert spec["coder_instructions"] == ["Fix the tests"]
            assert "review rework packet" in spec["rework_prompt"].lower()
            assert "do not redesign" in spec["rework_prompt"].lower()

            rework_from_db = d.query(Packet).filter_by(id=rework.id).first()
            assert rework_from_db is not None
            assert rework_from_db.spec_json["origin"] == "review_rework"

    def test_preserves_feature_and_wave_ids(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-002",
                feature_id="feat-custom",
                wave_id="W99",
                slug="my-packet",
                title="My Packet",
                spec_json={"scope": ["src/"]},
                acceptance_profile="STRICT",
                attempt_count=2,
                max_attempts=5,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-002",
                feature_id="feat-custom",
                wave_id="W99",
                original_spec=original.spec_json,
                acceptance_profile="STRICT",
                title="My Packet",
                slug="my-packet",
                max_attempts=5,
                verdict_source="evidence_verifier",
                summary="Evidence missing",
                blocking_issues=["no evidence for requirement X"],
            )
            d.commit()

            assert rework.feature_id == "feat-custom"
            assert rework.wave_id == "W99"
            assert rework.acceptance_profile == "STRICT"
            assert rework.max_attempts == 5
            assert rework.spec_json["rework_source"] == "evidence_verifier"

    def test_defaults_with_empty_spec(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-003",
                feature_id="feat-003",
                wave_id="W01",
                slug="empty-pkt",
                title="Empty",
                spec_json={},
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-003",
                feature_id="feat-003",
                wave_id="W01",
                original_spec={},
                acceptance_profile="NORMAL",
                title="Empty",
                slug="empty-pkt",
                max_attempts=3,
                verdict_source="reviewer",
                summary="fix",
                blocking_issues=[],
            )
            d.commit()

            spec = rework.spec_json
            assert spec["origin"] == "review_rework"
            assert spec["parent_packet_id"] == "pkt-orig-003"
            assert spec["scope"] == ["src/grace_control/"]
            assert "target_repo_root" not in spec or spec["target_repo_root"] == ""
            assert "workspace_mode" not in spec

    def test_no_workspace_mode_when_not_in_original(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-004",
                feature_id="feat-004",
                wave_id="W01",
                slug="no-ws",
                title="No Workspace",
                spec_json={"scope": ["src/"], "target_repo_root": "/tmp/r"},
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-004",
                feature_id="feat-004",
                wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL",
                title="No Workspace",
                slug="no-ws",
                max_attempts=3,
                verdict_source="evidence_verifier",
                summary="fix",
                blocking_issues=[],
            )
            d.commit()

            assert "workspace_mode" not in rework.spec_json
            assert rework.spec_json["target_repo_root"] == "/tmp/r"

    def test_claim_hydrates_legacy_rework_with_parent_contract(self, db):
        import asyncio

        from grace_control.services.packet_service import PacketService

        with get_db() as d:
            d.add(Packet(
                id="pkt-legacy-parent",
                feature_id="feat-legacy",
                wave_id="W01",
                slug="legacy-parent",
                title="Original",
                spec_json={
                    "scope": ["src/original.py"],
                    "verification": {"t1": ["pytest -q"]},
                    "expected_evidence": [{
                        "id": "EV-LEGACY-PARENT",
                        "kind": "test",
                        "artifact_patterns": ["verification-output/legacy.log"],
                    }],
                    "acceptance_criteria": ["parent criterion"],
                    "depends_on": ["Earlier Packet"],
                    "coder_instructions": ["preserve the original contract"],
                },
                acceptance_profile="STRICT",
                attempt_count=3,
                max_attempts=3,
                state=PacketState.FAILED.value,
            ))
            d.add(Packet(
                id="pkt-legacy-rework",
                feature_id="feat-legacy",
                wave_id="W01",
                slug="legacy-rework",
                title="Rework: Original",
                spec_json={
                    "origin": "review_rework",
                    "parent_packet_id": "pkt-legacy-parent",
                    "scope": ["src/original.py"],
                    "verification": {"t1": ["pytest -q"]},
                    "blocking_issues": ["missing evidence"],
                    "coder_instructions": ["add the missing evidence"],
                },
                acceptance_profile="STRICT",
                attempt_count=0,
                max_attempts=3,
                state=PacketState.READY.value,
            ))
            d.commit()

        claim = asyncio.run(PacketService().claim("pkt-legacy-rework", "worker"))

        assert claim.spec["expected_evidence"][0]["id"] == "EV-LEGACY-PARENT"
        assert claim.spec["acceptance_criteria"] == ["parent criterion"]
        assert claim.spec["depends_on"] == ["Earlier Packet"]
        assert claim.spec["coder_instructions"] == [
            "preserve the original contract",
            "add the missing evidence",
        ]
        assert claim.spec["blocking_issues"] == ["missing evidence"]
        with get_db() as d:
            hydrated = d.query(Packet).filter_by(id="pkt-legacy-rework").first()
            assert hydrated.spec_json["expected_evidence"][0]["id"] == "EV-LEGACY-PARENT"


class TestCreateArchitectRepackPacket:
    def _add_failed_packet(self, db, *, packet_id: str = "pkt-repack-parent") -> None:
        db.add(Feature(
            id="feat-repack",
            slug="feat-repack",
            title="Feature",
            spec_json={},
            status="degraded",
        ))
        db.add(Wave(
            id="wave-repack",
            feature_id="feat-repack",
            slug="wave-repack",
            title="Wave",
            order=1,
            status="IN_PROGRESS",
        ))
        db.add(Packet(
            id=packet_id,
            feature_id="feat-repack",
            wave_id="wave-repack",
            slug="repack-parent",
            title="Original Contract",
            spec_json={
                "scope": ["src/app.py"],
                "frozen_scope": ["docs"],
                "verification": {
                    "t0": ["test -f src/app.py"],
                    "t1": ["pytest tests/test_app.py -q"],
                    "t2": ["docker compose up -d db && pytest -q"],
                },
                "expected_evidence": [{
                    "id": "EV-REPACK",
                    "kind": "test",
                    "stage": "packet_local",
                    "owner": "coder",
                    "producer": "cli",
                    "required": True,
                    "coder_blocking": True,
                    "artifact_patterns": ["verification-output/repack.log"],
                }],
                "acceptance_criteria": ["PostgreSQL integration passes"],
                "depends_on": ["Earlier Packet"],
                "coder_instructions": ["Preserve the original implementation intent"],
                "target_repo_root": "/tmp/repo",
            },
            acceptance_profile="STRICT",
            attempt_count=3,
            max_attempts=3,
            state=PacketState.FAILED.value,
        ))
        db.commit()

    def test_creates_strict_repack_with_bounded_verification_override(self, db):
        replacement_verification = {
            "t0": ["test -f src/app.py"],
            "t1": ["pytest tests/test_app.py -q"],
            "t2": ["docker compose up -d postgres && pytest -q"],
        }
        with get_db() as session:
            self._add_failed_packet(session)
            replacement, created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification=replacement_verification,
                reason="Dependency created compose service postgres instead of db",
                coder_instructions=["Use the merged dependency's compose contract"],
            )
            session.commit()

            assert created is True
            assert replacement.state == PacketState.READY.value
            assert replacement.acceptance_profile == "STRICT"
            feature = session.query(Feature).filter_by(id="feat-repack").one()
            wave = session.query(Wave).filter_by(id="wave-repack").one()
            assert feature.status == "queued"
            assert wave.status == "IN_PROGRESS"
            assert replacement.spec_json["origin"] == "review_rework"
            assert replacement.spec_json["rework_source"] == "architect_repack"
            assert replacement.spec_json["rework_kind"] == "contract_repack"
            assert replacement.spec_json["parent_packet_id"] == "pkt-repack-parent"
            assert replacement.spec_json["verification"] == replacement_verification
            assert replacement.spec_json["scope"] == ["src/app.py"]
            assert replacement.spec_json["frozen_scope"] == ["docs"]
            assert replacement.spec_json["expected_evidence"][0]["id"] == "EV-REPACK"
            assert replacement.spec_json["acceptance_criteria"] == [
                "PostgreSQL integration passes"
            ]
            assert replacement.spec_json["depends_on"] == ["Earlier Packet"]

    def test_exact_repack_request_is_idempotent(self, db):
        verification = {
            "t0": ["test -f src/app.py"],
            "t1": ["pytest tests/test_app.py -q"],
            "t2": ["docker compose up -d postgres && pytest -q"],
        }
        reason = "Dependency compose service name differs from original verification"
        instructions = ["Follow the merged compose contract"]
        with get_db() as session:
            self._add_failed_packet(session)
            first, first_created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification=verification,
                reason=reason,
                coder_instructions=instructions,
            )
            session.commit()
            feature = session.query(Feature).filter_by(id="feat-repack").one()
            feature.status = "COMPLETED"
            session.commit()
            second, second_created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification=verification,
                reason=reason,
                coder_instructions=instructions,
            )

            assert first_created is True
            assert second_created is False
            assert second.id == first.id
            assert feature.status == "queued"

    # START_FUNCTION_CONTRACT
    # name: test_repack_can_widen_scope_without_removing_original_paths
    # purpose: Verify architect repack may add required production paths while preserving original scope.
    # inputs: db — isolated database fixture.
    # returns: None.
    # side_effects: Inserts feature, wave, and packet rows in the test database.
    # emitted_logs: None.
    # error_behavior: AssertionError on regression.
    # END_FUNCTION_CONTRACT
    def test_repack_can_widen_scope_without_removing_original_paths(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            replacement, created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification={
                    "t0": ["git diff -- src/app.py src/service.py"],
                    "t1": ["pytest tests/test_app.py -q"],
                    "t2": ["docker compose up -d postgres && pytest -q"],
                },
                reason="Reviewer proved that production service scope is required",
                coder_instructions=["Implement the behavior in the production service"],
                scope=["src/app.py", "src/service.py"],
                frozen_scope=["docs"],
            )
            session.commit()

            assert created is True
            assert replacement.spec_json["scope"] == ["src/app.py", "src/service.py"]
            assert replacement.spec_json["frozen_scope"] == ["docs"]

    # START_FUNCTION_CONTRACT
    # name: test_repack_rejects_removing_original_scope
    # purpose: Verify architect repack cannot weaken the source write contract by removing paths.
    # inputs: db — isolated database fixture.
    # returns: None.
    # side_effects: Inserts feature, wave, and packet rows in the test database.
    # emitted_logs: None.
    # error_behavior: AssertionError when unsafe scope is accepted.
    # END_FUNCTION_CONTRACT
    def test_repack_rejects_removing_original_scope(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            with pytest.raises(
                ArchitectRepackValidationError,
                match="scope cannot remove original paths",
            ):
                create_architect_repack_packet(
                    session,
                    original_packet_id="pkt-repack-parent",
                    verification={
                        "t0": ["test -f src/service.py"],
                        "t1": ["pytest tests/test_app.py -q"],
                        "t2": ["docker compose up -d postgres && pytest -q"],
                    },
                    reason="Attempted replacement omitted the original source scope",
                    scope=["src/service.py"],
                )

    def test_repack_rejects_removed_verification_gate(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            with pytest.raises(
                ArchitectRepackValidationError,
                match="verification.t2 cannot remove gates",
            ):
                create_architect_repack_packet(
                    session,
                    original_packet_id="pkt-repack-parent",
                    verification={
                        "t0": ["test -f src/app.py"],
                        "t1": ["pytest tests/test_app.py -q"],
                        "t2": [],
                    },
                    reason="Attempted removal of the incompatible full verification gate",
                )

    # START_FUNCTION_CONTRACT
    # name: test_repack_can_correct_evidence_expectation_without_weakening_it
    # purpose: Verify a repack may repair an impossible evidence expectation while retaining the required evidence identity and blocking strength.
    # inputs: db — isolated database fixture.
    # returns: None.
    # side_effects: Inserts feature, wave, and packet rows in the test database.
    # emitted_logs: None.
    # error_behavior: AssertionError on regression.
    # END_FUNCTION_CONTRACT
    def test_repack_can_correct_evidence_expectation_without_weakening_it(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            original = session.query(Packet).filter_by(id="pkt-repack-parent").one()
            evidence = deepcopy(original.spec_json["expected_evidence"])
            evidence[0]["expectation"] = "exists"
            replacement, created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification=original.spec_json["verification"],
                reason="The compiler inferred deletion from an unrelated removal phrase",
                expected_evidence=evidence,
            )

            assert created is True
            assert replacement.spec_json["expected_evidence"][0]["id"] == "EV-REPACK"
            assert replacement.spec_json["expected_evidence"][0]["expectation"] == "exists"
            assert replacement.spec_json["expected_evidence"][0]["required"] is True
            assert replacement.spec_json["expected_evidence"][0]["coder_blocking"] is True

    # START_FUNCTION_CONTRACT
    # name: test_repack_rejects_removed_or_weakened_evidence
    # purpose: Verify a repack cannot remove a source evidence ID or downgrade its coder-blocking requirement.
    # inputs: db — isolated database fixture.
    # returns: None.
    # side_effects: Inserts feature, wave, and packet rows in the test database.
    # emitted_logs: None.
    # error_behavior: AssertionError when unsafe evidence replacement is accepted.
    # END_FUNCTION_CONTRACT
    def test_repack_rejects_removed_or_weakened_evidence(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            original = session.query(Packet).filter_by(id="pkt-repack-parent").one()
            with pytest.raises(
                ArchitectRepackValidationError,
                match="cannot remove original ids",
            ):
                create_architect_repack_packet(
                    session,
                    original_packet_id="pkt-repack-parent",
                    verification=original.spec_json["verification"],
                    reason="The replacement attempted to omit required evidence",
                    expected_evidence=[{
                        "id": "EV-OTHER",
                        "kind": "test",
                        "required": True,
                        "coder_blocking": True,
                        "expectation": "exists",
                    }],
                )

            weakened = deepcopy(original.spec_json["expected_evidence"])
            weakened[0]["coder_blocking"] = False
            with pytest.raises(
                ArchitectRepackValidationError,
                match="cannot weaken coder blocking",
            ):
                create_architect_repack_packet(
                    session,
                    original_packet_id="pkt-repack-parent",
                    verification=original.spec_json["verification"],
                    reason="The replacement attempted to weaken required evidence",
                    expected_evidence=weakened,
                )

    def test_repack_rejects_competing_active_child(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification={
                    "t0": ["test -f src/app.py"],
                    "t1": ["pytest tests/test_app.py -q"],
                    "t2": ["docker compose up -d postgres && pytest -q"],
                },
                reason="Dependency compose service name differs from original verification",
            )
            session.commit()
            with pytest.raises(ArchitectRepackConflictError, match="active replacement"):
                create_architect_repack_packet(
                    session,
                    original_packet_id="pkt-repack-parent",
                    verification={
                        "t0": ["test -f src/app.py"],
                        "t1": ["pytest tests/test_app.py -q"],
                        "t2": ["docker compose up -d postgres && python -m pytest -q"],
                    },
                    reason="A different repair was requested after an active child existed",
                )

    # START_FUNCTION_CONTRACT
    # name: test_repack_allows_operator_cancelled_inconsistent_contract
    # purpose: Verify an operator may stop an impossible active contract and still create an audited strict replacement.
    # inputs: db — isolated database fixture.
    # returns: None.
    # side_effects: Inserts feature, wave, original packet, and replacement packet rows.
    # emitted_logs: None.
    # error_behavior: AssertionError on regression.
    # END_FUNCTION_CONTRACT
    def test_repack_allows_operator_cancelled_inconsistent_contract(self, db):
        with get_db() as session:
            self._add_failed_packet(session)
            original = session.query(Packet).filter_by(id="pkt-repack-parent").one()
            original.state = PacketState.CANCELLED.value
            original.attempt_count = 1
            original.max_attempts = 3
            replacement, created = create_architect_repack_packet(
                session,
                original_packet_id="pkt-repack-parent",
                verification=original.spec_json["verification"],
                reason="Operator stopped repeated execution of an inconsistent contract",
            )

            assert created is True
            assert replacement.state == PacketState.READY.value
            assert replacement.acceptance_profile == "STRICT"


class TestRuntimeFailureCodes:
    """Verify RUNTIME_FAILURE_CODES contains expected values."""

    def test_runtime_failure_codes_defined(self):
        assert "auth_error" in RUNTIME_FAILURE_CODES
        assert "timeout" in RUNTIME_FAILURE_CODES
        assert "worktree_missing" in RUNTIME_FAILURE_CODES
        assert "not_git" in RUNTIME_FAILURE_CODES
        assert "AGENT_WORKTREE_NOT_GIT" in RUNTIME_FAILURE_CODES
        assert "AGENT_NO_CHANGES_PRODUCED" in RUNTIME_FAILURE_CODES
        assert "AGENT_DIFF_INSPECTION_FAILED" in RUNTIME_FAILURE_CODES
        assert "AGENT_CHANGED_OUT_OF_SCOPE" in RUNTIME_FAILURE_CODES

    def test_acceptance_failure_not_runtime(self):
        assert "t1_failed" not in RUNTIME_FAILURE_CODES
        assert "scope_violation" not in RUNTIME_FAILURE_CODES
        assert "unknown" not in RUNTIME_FAILURE_CODES
        assert "REWORK_TO_CODER" not in RUNTIME_FAILURE_CODES
        assert "RETURN_TO_ARCHITECT" not in RUNTIME_FAILURE_CODES


class TestIdempotency:
    """Idempotency: same original + source must not create duplicate rework packets."""

    def test_maybe_create_skips_when_rework_exists(self, db, tmp_path):
        """_maybe_create_rework_packet skips when existing rework packet is found."""
        from unittest.mock import MagicMock, patch
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        from grace_control.core.uid import generate_unique_id, new_packet_uid

        with get_db() as d:
            original = Packet(
                id="pkt-idem-adapter-001",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt",
                title="Idempotency Test",
                spec_json={"scope": ["src/"]},
                acceptance_profile="NORMAL",
                attempt_count=1, max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)

            existing_rework = Packet(
                id="pkt-existing-rework",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt-rework",
                title="Rework: Idempotency Test",
                spec_json={
                    "origin": "review_rework",
                    "parent_packet_id": "pkt-idem-adapter-001",
                    "rework_source": "reviewer",
                },
                acceptance_profile="NORMAL",
                attempt_count=0, max_attempts=3,
                state=PacketState.READY.value,
            )
            d.add(existing_rework)
            d.commit()

        adapter = PacketExecutionAdapter(
            project_root=tmp_path,
            state_root=tmp_path,
            worktree_root=tmp_path,
            backend=MagicMock(),
        )

        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            adapter._maybe_create_rework_packet(
                "pkt-idem-adapter-001",
                verdict_source="reviewer",
                summary="fix it",
                blocking_issues=["issue"],
            )

        with get_db() as d:
            rework_packets = [
                p for p in d.query(Packet).all()
                if (p.spec_json or {}).get("origin") == "review_rework"
            ]
            assert len(rework_packets) == 1
            assert rework_packets[0].id == "pkt-existing-rework"

    def test_maybe_create_skips_when_rework_already_merged(self, db, tmp_path):
        from unittest.mock import MagicMock, patch

        from grace_control.adapters.packet_executor import PacketExecutionAdapter

        with get_db() as d:
            d.add(Packet(
                id="pkt-idem-merged-parent",
                feature_id="feat-idem-merged",
                wave_id="W01",
                slug="idem-merged-parent",
                title="Merged Idempotency Test",
                spec_json={"scope": ["src/"]},
                acceptance_profile="NORMAL",
                attempt_count=3,
                max_attempts=3,
                state=PacketState.CANCELLED.value,
            ))
            d.add(Packet(
                id="pkt-idem-merged-child",
                feature_id="feat-idem-merged",
                wave_id="W01",
                slug="idem-merged-child",
                title="Rework: Merged Idempotency Test",
                spec_json={
                    "origin": "review_rework",
                    "parent_packet_id": "pkt-idem-merged-parent",
                    "rework_source": "reviewer",
                },
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.MERGED.value,
            ))
            d.commit()

        adapter = PacketExecutionAdapter(
            project_root=tmp_path,
            state_root=tmp_path,
            worktree_root=tmp_path,
            backend=MagicMock(),
        )

        with patch(
            "grace_control.config.settings.settings.agent_runtime_rework_packets_enabled",
            True,
        ):
            adapter._maybe_create_rework_packet(
                "pkt-idem-merged-parent",
                verdict_source="reviewer",
                summary="late duplicate callback",
                blocking_issues=["already resolved"],
            )

        with get_db() as d:
            children = [
                packet for packet in d.query(Packet).all()
                if isinstance(packet.spec_json, dict)
                and packet.spec_json.get("parent_packet_id") == "pkt-idem-merged-parent"
            ]
            assert [packet.id for packet in children] == ["pkt-idem-merged-child"]

    def test_maybe_create_creates_when_no_existing_rework(self, db, tmp_path):
        """_maybe_create_rework_packet creates when no existing rework packet found."""
        from unittest.mock import MagicMock, patch
        from grace_control.adapters.packet_executor import PacketExecutionAdapter

        with get_db() as d:
            original = Packet(
                id="pkt-idem-adapter-002",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt-2",
                title="Idempotency Test 2",
                spec_json={"scope": ["src/"]},
                acceptance_profile="NORMAL",
                attempt_count=1, max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

        adapter = PacketExecutionAdapter(
            project_root=tmp_path,
            state_root=tmp_path,
            worktree_root=tmp_path,
            backend=MagicMock(),
        )

        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            adapter._maybe_create_rework_packet(
                "pkt-idem-adapter-002",
                verdict_source="reviewer",
                summary="fix it",
                blocking_issues=["issue"],
            )

        with get_db() as d:
            rework_packets = [
                p for p in d.query(Packet).all()
                if (p.spec_json or {}).get("origin") == "review_rework"
            ]
            assert len(rework_packets) == 1
            spec = rework_packets[0].spec_json
            assert spec["parent_packet_id"] == "pkt-idem-adapter-002"
            assert spec["rework_source"] == "reviewer"

    def test_create_rework_packet_twice_produces_two_packets(self, db):
        """Service layer has no guard — _maybe_create_rework_packet owns idempotency."""
        with get_db() as d:
            original = Packet(
                id="pkt-idem-001",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt",
                title="Idempotency Test",
                spec_json={
                    "scope": ["src/grace_control/"],
                    "frozen_scope": ["docs/archived/"],
                },
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            first = create_rework_packet(
                d, original_packet_id="pkt-idem-001",
                feature_id="feat-idem", wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL", title="Idempotency Test",
                slug="idem-pkt", max_attempts=3,
                verdict_source="reviewer", summary="fix issues",
                blocking_issues=["issue 1"],
            )
            d.commit()

            second = create_rework_packet(
                d, original_packet_id="pkt-idem-001",
                feature_id="feat-idem", wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL", title="Idempotency Test",
                slug="idem-pkt", max_attempts=3,
                verdict_source="reviewer", summary="fix issues again",
                blocking_issues=["issue 2"],
            )
            d.commit()

            assert first.id != second.id

            all_rework = [p for p in d.query(Packet).all()
                          if (p.spec_json or {}).get("origin") == "review_rework"]
            assert len(all_rework) == 2
