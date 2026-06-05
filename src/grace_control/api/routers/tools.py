# ############################################################################
# AI_HEADER: api_routers_tools
# ROLE: Tools router — POST /api/tools/grace-lint/run.
#       W10 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose GraceLint core as an HTTP endpoint for agents and humans.
#          Delegates to grace_control.tools.grace_lint.checker.
# inputs: RunLintRequest JSON {paths, strict, rules}.
# returns: RunLintResponse {ok, violations}.
# side_effects: None (reads source files).
# emitted_logs: grace_lint_run.
# error_behavior: Never raises; returns violations in payload.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - POST /run
#   - class: RunLintRequest
#   - class: RunLintResponse
#   - class: LintViolation
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from grace_control.tools.grace_lint.checker import lint_file, lint_text

router = APIRouter(tags=["tools"])


class LintViolation(BaseModel):
    code: str
    message: str
    file: str
    line: int = 1


class RunLintRequest(BaseModel):
    paths: list[str] = Field(default_factory=lambda: ["src/grace_control"])
    strict: bool = False
    rules: list[str] | None = None


class RunLintResponse(BaseModel):
    ok: bool
    violations: list[LintViolation] = Field(default_factory=list)


# START_FUNCTION_CONTRACT
# name: run_lint
# purpose: Run the GraceLint checker over requested paths and return violations.
# inputs: req (RunLintRequest) — paths to lint, strict mode toggle, optional rule filter.
# returns: RunLintResponse.
# side_effects: None (reads source files on disk).
# emitted_logs: grace_lint_run.
# error_behavior: Never raises; returns violations in payload.
# END_FUNCTION_CONTRACT
@router.post("/grace-lint/run", response_model=RunLintResponse)
def run_lint(req: RunLintRequest) -> RunLintResponse:
    all_violations: list[LintViolation] = []
    for target_path in req.paths:
        p = Path(target_path)
        if not p.exists():
            continue
        files: list[Path] = []
        if p.is_file() and p.suffix == ".py":
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.py"))
        for fp in files:
            if "__pycache__" in str(fp):
                continue
            if req.strict:
                violations = lint_text(fp.read_text(), str(fp), rules_enabled=req.rules)
            else:
                violations = lint_file(fp, rules_enabled=req.rules)
            for v in violations:
                all_violations.append(LintViolation(code=v.code, message=v.message, file=v.file, line=v.line))
    return RunLintResponse(ok=len(all_violations) == 0, violations=all_violations)
