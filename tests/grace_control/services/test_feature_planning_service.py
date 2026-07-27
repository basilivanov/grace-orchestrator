"""Tests for FeaturePlanningService: approve_plan compiler error handling."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grace_control.db.schema import Feature, Packet, PacketState, Wave


class TestApprovePlanCompilerErrors:

    def test_approve_plan_preserves_strict_acceptance_profile(self, db, monkeypatch):
        from grace_control.core.plan_compiler import CompileResult, PlanCompiler
        from grace_control.db import get_db
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService

        monkeypatch.setattr(
            PlanCompiler,
            "compile_plan",
            lambda self, *args, **kwargs: CompileResult(ok=True),
        )

        with get_db() as session:
            intake = FeatureIntakeService(session)
            result = intake.create_feature(title="Strict packet", mode="draft_plan")
            feature_id = result["feature_id"]
            feature = session.query(Feature).filter_by(id=feature_id).one()
            spec = dict(feature.spec_json or {})
            spec["plan_json"] = {
                "waves": [{
                    "title": "W00",
                    "packets": [{
                        "title": "Strict docs packet",
                        "role": "coder",
                        "scope": ["docs/requirements.md"],
                        "frozen_scope": [],
                        "acceptance_profile": "STRICT",
                        "depends_on": [],
                        "description": "Create strict documentation.",
                        "coder_instructions": ["Create the requested document."],
                        "acceptance_criteria": ["Document exists."],
                        "verification": {"t0": [], "t1": ["true"], "t2": []},
                        "expected_evidence": [{
                            "id": "EV-DOC",
                            "kind": "file",
                            "stage": "t1",
                            "owner": "coder",
                            "producer": "agent",
                            "required": True,
                            "coder_blocking": True,
                            "artifact_patterns": ["docs/requirements.md"],
                            "description": "Strict document exists.",
                        }],
                    }],
                }],
                "constraints": {},
                "verification": {"t0": [], "t1": [], "t2": []},
            }
            feature.spec_json = spec
            feature.status = "PLAN_READY"
            session.commit()

            FeaturePlanningService(session).approve_plan(feature_id)

            packet = session.query(Packet).filter_by(feature_id=feature_id).one()
            assert packet.acceptance_profile == "STRICT"
            assert packet.spec_json["acceptance_profile"] == "STRICT"

    def test_approve_plan_with_compiler_errors_raises_valueerror(self, db):
        """When plan compiler finds errors, approve_plan must raise ValueError
        and must NOT create any packets or waves."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as db:
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Compiler Error Test",
                mode="draft_plan",
            )
            fid = result["feature_id"]

            feature = db.query(Feature).filter_by(id=fid).first()
            spec = dict(feature.spec_json)
            # Plan with non-canonical scope path — compiler will reject
            spec["plan_json"] = {
                "waves": [
                    {
                        "title": "Wave 1",
                        "packets": [
                            {
                                "title": "Empty Scope Packet",
                                "scope": [],
                                "acceptance_profile": "FAST",
                                "depends_on": [],
                                "description": "test packet with no scope",
                                "verification": {"t0": [], "t1": [], "t2": []},
                                "expected_evidence": [],
                            }
                        ]
                    }
                ]
            }
            feature.spec_json = spec
            feature.status = "PLAN_READY"
            db.commit()

            planning = FeaturePlanningService(db)

            with pytest.raises(ValueError, match="Plan compiler found"):
                planning.approve_plan(fid)

            # Verify no packets or waves were created
            packets = db.query(Packet).filter_by(feature_id=fid).all()
            assert len(packets) == 0, "No packets should be created on compiler failure"
            waves = db.query(Wave).filter_by(feature_id=fid).all()
            assert len(waves) == 0, "No waves should be created on compiler failure"

            # Feature status should remain PLAN_FAILED
            feature = db.query(Feature).filter_by(id=fid).first()
            assert feature.status == "PLAN_FAILED"


@pytest.mark.asyncio
async def test_run_architect_persists_resolved_mini_swe_profile(db, monkeypatch):
    from grace_control.core import executor_selector, llm_runner
    from grace_control.db import get_db
    from grace_control.db.schema import FeaturePlanningRun
    from grace_control.services.feature_intake_service import FeatureIntakeService
    from grace_control.services.feature_planning_service import FeaturePlanningService

    captured = {}
    monkeypatch.delenv("GRACE_CONTEXT_DISABLED", raising=False)

    async def fake_run_llm(*args, **kwargs):
        captured.update(kwargs)
        return '{"title":"Plan","description":"Demo","waves":[]}'

    monkeypatch.setattr(llm_runner, "run_llm", fake_run_llm)
    monkeypatch.setattr(
        executor_selector,
        "resolve_model",
        lambda role: {
            "model": "openai/gpt-5.5",
            "command": "python3",
            "kind": "mini-swe",
            "executor_id": "architect-mini-swe",
        },
    )

    with get_db() as session:
        intake = FeatureIntakeService(session)
        result = intake.create_feature(title="Mini SWE architect", mode="draft_plan")
        feature_id = result["feature_id"]
        service = FeaturePlanningService(session)

        plan = await service.run_architect(
            feature_id,
            {"summary": "empty repository", "files": []},
        )

        run = session.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id,
            stage="architect",
        ).one()
        feature = session.query(Feature).filter_by(id=feature_id).one()

        assert plan["waves"] == []
        assert run.status == "done"
        assert run.executor_id == "architect-mini-swe"
        assert run.model == "openai/gpt-5.5"
        assert feature.status == "PLAN_READY"
        assert captured["session_dir"] == Path(run.stdout_path).parent


@pytest.mark.asyncio
async def test_run_architect_uses_disposable_standalone_clone(db, monkeypatch, tmp_path):
    from grace_control.core import executor_selector, llm_runner
    from grace_control.db import get_db
    from grace_control.services.feature_intake_service import FeatureIntakeService
    from grace_control.services.feature_planning_service import FeaturePlanningService

    monkeypatch.delenv("GRACE_CONTEXT_DISABLED", raising=False)
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("target")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    captured = {}

    async def fake_run_llm(*args, **kwargs):
        planning_root = kwargs["cwd"]
        captured["cwd"] = planning_root
        captured["exists_during_run"] = planning_root.exists()
        captured["target_common"] = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        captured["planning_common"] = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            cwd=planning_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return '{"title":"Plan","waves":[]}'

    monkeypatch.setattr(llm_runner, "run_llm", fake_run_llm)
    monkeypatch.setattr(
        executor_selector,
        "resolve_model",
        lambda role: {
            "model": "openai/gpt-5.5",
            "command": "python3",
            "kind": "mini-swe",
            "executor_id": "architect-mini-swe",
        },
    )

    with get_db() as session:
        result = FeatureIntakeService(session).create_feature(
            title="Isolated architect",
            mode="draft_plan",
            target_repo_root=str(repo),
        )
        service = FeaturePlanningService(session)

        await service.run_architect(
            result["feature_id"],
            {"summary": "repo", "files": [], "target_repo_root": str(repo)},
            target_repo_root=str(repo),
        )

    assert captured["exists_during_run"] is True
    assert captured["cwd"] != repo
    assert captured["planning_common"] != captured["target_common"]
    assert not captured["cwd"].exists()
