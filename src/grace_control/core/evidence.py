# ############################################################################
# AI_HEADER: evidence
# ROLE: Collect machine-readable evidence from acceptance pipeline stages.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Collect evidence strings from stage results; check if required evidence is present.
# inputs: stage (StageResult), expected_evidence (list[str]), profile (AcceptanceProfile).
# returns: list[str] (evidence strings), bool (has required).
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: EvidenceCollector
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.contracts import AcceptanceProfile, StageResult


class EvidenceCollector:

    def collect_from_stage(self, stage: StageResult) -> list[str]:
        evidence: list[str] = []
        for cmd in stage.commands:
            evidence.append(f"command:{' '.join(cmd.command)}")
            evidence.append(f"exit_code:{cmd.exit_code}")
        return evidence

    def has_required_evidence(
        self,
        *,
        expected_evidence: list[str],
        collected_evidence: list[str],
        acceptance_profile: AcceptanceProfile,
    ) -> bool:
        if acceptance_profile == AcceptanceProfile.FAST:
            return True  # FAST only needs T0

        if not expected_evidence:
            return False

        passed_commands = [e for e in collected_evidence if e.startswith("exit_code:0")]
        return len(passed_commands) >= 1
