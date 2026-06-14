"""Tests for FeaturePlanningService: approve_plan compiler error handling."""
from __future__ import annotations

import pytest

from grace_control.db.schema import Feature, Packet, PacketState, Wave


class TestApprovePlanCompilerErrors:

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
