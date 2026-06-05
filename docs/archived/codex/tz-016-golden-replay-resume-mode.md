# TZ 016 — Golden-only replay/resume mode for fast stage debugging

Audience: Flash coder / literal executor.

Goal: add a strictly golden-only debug mechanism that lets us resume/replay from already successful stages during internal golden testing, without enabling any skip/override behavior in normal production/autonomous runs.

This is only for `grace/features/golden*` internal test features. It must be impossible or fail-closed for normal product features, external customer repos, and production/self-improvement runs unless explicitly running in golden debug mode.

---

## 0. Why this is needed

During the first live golden, many failures happened near the end of the pipeline:

```text
agent already succeeded
files were already created
acceptance already succeeded
but merge/verifier/reviewer failed later
```

Each rerun had to repeat slow earlier work, often waiting 5–7+ minutes just to reach the same failing stage.

We need a golden-only way to say:

```text
The earlier stage already produced valid artifacts.
Reuse them and continue from the stage I am debugging.
```

Examples:

```text
agent succeeded → rerun only acceptance/merge
acceptance succeeded → rerun only verifier/reviewer/merge
verifier succeeded → rerun only reviewer/merge
merge failed → rerun only merge with the same branch/worktree/commit
```

---

## 1. Hard safety rule

This feature must never affect normal pipeline execution.

Replay/resume is allowed only when **all** are true:

```text
1. CLI flag --golden-debug is present
2. env GRACE_GOLDEN_DEBUG=1 is set
3. feature file path is under grace/features/ and filename starts with golden
4. target_repo_root equals control_plane_root OR is explicitly marked as test-only
5. state_root/worktree_root are under /tmp/grace-eval/ or another explicitly allowed test root
```

If any condition is false:

```text
fail closed with a clear error
```

Never silently enable replay.

---

## 2. New CLI flags

File likely to change:

```text
src/grace_control/cli/main.py
```

Add to `grace eval run`:

```text
--golden-debug
--resume-from STAGE
--reuse-artifacts
--run-id TEXT
```

Allowed `--resume-from` values:

```text
plan
agent
commit
acceptance
verifier
reviewer
merge
```

Meaning:

```text
plan       → reuse generated/imported plan if valid, then continue
agent      → skip plan/claim/agent only if agent checkpoint valid; continue from commit/acceptance
commit     → skip until commit verification; continue from commit check
acceptance → skip agent/commit if valid; rerun acceptance and later
verifier   → skip agent/commit/acceptance if valid; rerun verifier and later
reviewer   → skip through verifier if valid; rerun reviewer and later
merge      → skip through reviewer/acceptance if valid; rerun merge only
```

For the first MVP, implement only:

```text
--resume-from acceptance
--resume-from merge
```

but define the enum with all stage names for future compatibility.

`--reuse-artifacts` means:

```text
use valid checkpoint automatically when fingerprint matches;
otherwise rerun the stage normally.
```

`--resume-from` is stricter:

```text
required checkpoint must exist and be valid;
if not valid, fail instead of silently rerunning earlier stages.
```

---

## 3. Checkpoint directory

Use state root, not repo root.

Path:

```text
{GRACE_STATE_ROOT}/golden_checkpoints/{run_id}/
```

If `--run-id` is not supplied:

```text
run_id = feature_file_stem
```

Example:

```text
/tmp/grace-eval/golden-smoke-live-001/state/golden_checkpoints/golden-smoke-live-001/
```

Files:

```text
plan.json
agent.json
commit.json
acceptance.json
verifier.json
reviewer.json
merge.json
```

Do not store checkpoints in target repo.

---

## 4. Checkpoint schema

Add new module:

```text
src/grace_control/core/golden_replay.py
```

Add models:

```python
class GoldenStage(str, Enum):
    PLAN = "plan"
    AGENT = "agent"
    COMMIT = "commit"
    ACCEPTANCE = "acceptance"
    VERIFIER = "verifier"
    REVIEWER = "reviewer"
    MERGE = "merge"

class GoldenCheckpoint(BaseModel):
    run_id: str
    feature_path: str
    feature_yaml_hash: str
    packet_id: str
    packet_contract_hash: str
    stage: GoldenStage
    status: Literal["passed", "failed", "skipped"]
    created_at: str

    target_repo_root: str
    control_plane_root: str
    state_root: str
    worktree_root: str
    base_ref: str
    base_sha: str

    worktree_path: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    acceptance_report_path: str | None = None
    verifier_report_path: str | None = None
    reviewer_report_path: str | None = None
    merge_result: dict[str, Any] | None = None

    extra: dict[str, Any] = Field(default_factory=dict)
```

Add helpers:

```python
def hash_file(path: Path) -> str: ...
def hash_packet_contract(packet: ExecutionPacketContract) -> str: ...
def checkpoint_path(state_root: Path, run_id: str, stage: GoldenStage) -> Path: ...
def write_checkpoint(...): ...
def read_checkpoint(...): ...
def validate_checkpoint(...): ...
def assert_golden_debug_allowed(...): ...
```

Use SHA256 for hashes.

---

## 5. Fingerprint validation

A checkpoint is valid only if all match:

```text
feature_yaml_hash
packet_contract_hash
base_sha
target_repo_root
control_plane_root
worktree_root
packet_id
```

For checkpoints that contain worktree/branch/commit:

```text
worktree_path must exist
worktree_path must be a git worktree
branch_name must exist in target repo
commit_sha must exist in target repo/worktree
```

For acceptance checkpoint:

```text
acceptance_report_path must exist
report final_verdict must be accepted
```

For verifier checkpoint:

```text
verifier_report_path must exist
verdict must be PASS
```

For reviewer checkpoint:

```text
reviewer_report_path must exist
verdict must be PASS
```

For merge checkpoint:

```text
merge_result must show merged=true or packet state merged
```

If validation fails:

```text
--reuse-artifacts → rerun that stage normally
--resume-from → fail closed with clear reason
```

---

## 6. Stage checkpoints to write

### 6.1 Plan checkpoint

After YAML is parsed / plan created/imported:

```text
plan.json
```

Fields:

```text
feature_yaml_hash
feature_path
run_id
packets list summary
```

### 6.2 Agent checkpoint

After legacy runner returns agent/worktree result:

```text
agent.json
```

Required fields:

```text
packet_id
worktree_path
branch_name
base_ref
base_sha
status=passed only if result.ok=true or domain_status accepted/check_passed equivalent
```

### 6.3 Commit checkpoint

After commit verification / agent commit SHA capture:

```text
commit.json
```

Required fields:

```text
worktree_path
branch_name
commit_sha
changed_files
```

### 6.4 Acceptance checkpoint

After deterministic acceptance report is saved:

```text
acceptance.json
```

Required fields:

```text
acceptance_report_path
status=passed only if final_verdict accepted
```

### 6.5 Verifier checkpoint

After Evidence Verifier returns PASS:

```text
verifier.json
```

For FAST profile, verifier may be skipped. In that case:

```text
status=skipped
extra.reason="FAST profile skips evidence verifier"
```

Do not treat skipped verifier as valid for STRICT resume-to-reviewer unless profile is FAST/NORMAL and reviewer is not required.

### 6.6 Reviewer checkpoint

After Reviewer returns PASS:

```text
reviewer.json
```

For FAST/NORMAL where reviewer is skipped:

```text
status=skipped
extra.reason="profile skips reviewer"
```

### 6.7 Merge checkpoint

After merge endpoint succeeds:

```text
merge.json
```

Fields:

```text
merge_result
commit_sha
branch_name
packet_state_after_merge
```

---

## 7. First MVP behavior

Do not implement everything at once.

### MVP A — checkpoint writing only

Implement writing checkpoints for:

```text
agent
commit
acceptance
merge
```

No skipping yet.

This gives observability and artifact reuse later.

### MVP B — `--resume-from merge`

If golden debug is enabled and merge checkpoint is absent but commit/acceptance checkpoint are valid:

```text
skip agent and acceptance
call merge endpoint using saved worktree_path, branch_name, commit_sha, target_repo_root
```

This is the most useful for debugging merge failures.

### MVP C — `--resume-from acceptance`

If golden debug is enabled and agent/commit checkpoint valid:

```text
skip agent
reuse worktree_path/branch_name/commit_sha
rerun acceptance
then continue normally
```

This is useful when acceptance code was changed but agent output is still valid.

Implement A+B first if time is limited. Do not implement unsafe manual override in the first patch.

---

## 8. What NOT to implement in MVP

Do not add manual `mark-stage passed` command yet.
Do not allow arbitrary DB status mutation.
Do not allow replay for non-golden features.
Do not allow replay without env + CLI guard.
Do not allow replay from stale fingerprints.
Do not skip merge validation.
Do not disable scope guard.
Do not disable acceptance.
Do not reuse artifacts when target repo is dirty.
Do not use production target repo paths outside `/tmp` for golden replay.

---

## 9. API/worker design option

Prefer keeping replay orchestration in `eval run`, not normal worker/API.

The normal worker should stay honest:

```text
claim → execute → release → merge
```

For golden debug resume, the eval runner may invoke a special internal path that reuses checkpoint data.

If adding worker support is easier, it must be guarded by:

```text
GRACE_GOLDEN_DEBUG=1
packet.feature_path starts with grace/features/golden
explicit debug payload flag
```

But prefer eval-level orchestration to keep production worker clean.

---

## 10. Audit logs

Every replay/skip must emit a visible event/log:

```text
golden_checkpoint_written
golden_checkpoint_validated
golden_stage_reused
golden_resume_requested
golden_resume_denied
golden_replay_fingerprint_mismatch
```

The report JSON should include:

```json
"golden_debug": {
  "enabled": true,
  "run_id": "...",
  "resume_from": "merge",
  "reused_stages": ["agent", "commit", "acceptance"],
  "checkpoint_dir": "..."
}
```

If golden debug is off:

```json
"golden_debug": {"enabled": false}
```

---

## 11. CLI examples

### Normal honest golden run

```bash
export GRACE_GOLDEN_DEBUG=

grace eval run grace/features/golden-normal-001.yaml \
  --workers 1 \
  --timeout 1200 \
  --report /tmp/grace-eval/golden-normal-001/report.json
```

### Golden debug rerun merge only

```bash
export GRACE_GOLDEN_DEBUG=1

grace eval run grace/features/golden-normal-001.yaml \
  --golden-debug \
  --resume-from merge \
  --run-id golden-normal-001 \
  --workers 1 \
  --timeout 1200 \
  --state-root /tmp/grace-eval/golden-normal-001/state \
  --worktree-root /tmp/grace-eval/golden-normal-001/worktrees \
  --report /tmp/grace-eval/golden-normal-001/report.json
```

### Golden debug rerun acceptance and later

```bash
export GRACE_GOLDEN_DEBUG=1

grace eval run grace/features/golden-normal-001.yaml \
  --golden-debug \
  --resume-from acceptance \
  --run-id golden-normal-001 \
  --workers 1 \
  --timeout 1200 \
  --state-root /tmp/grace-eval/golden-normal-001/state \
  --worktree-root /tmp/grace-eval/golden-normal-001/worktrees \
  --report /tmp/grace-eval/golden-normal-001/report.json
```

---

## 12. Tests required

Create tests:

```text
tests/grace_control/core/test_golden_replay.py
tests/grace_control/cli/test_golden_debug_flags.py
```

### Core tests

```text
test_assert_golden_debug_requires_env_and_flag
test_assert_golden_debug_rejects_non_golden_feature
test_checkpoint_roundtrip
test_checkpoint_validation_rejects_feature_hash_mismatch
test_checkpoint_validation_rejects_packet_contract_hash_mismatch
test_checkpoint_validation_rejects_missing_worktree
test_checkpoint_validation_accepts_valid_commit_checkpoint
test_resume_from_merge_requires_commit_and_acceptance_checkpoints
test_reuse_artifacts_reruns_on_fingerprint_mismatch
```

### CLI tests

```text
test_eval_run_rejects_resume_without_golden_debug_flag
test_eval_run_rejects_golden_debug_without_env
test_eval_run_rejects_resume_for_non_golden_yaml
test_eval_run_accepts_resume_for_golden_yaml_with_env
test_eval_report_contains_golden_debug_section
```

### Integration-style test

Add one lightweight test with fake artifacts:

```text
test_resume_from_merge_uses_saved_worktree_branch_commit_without_agent_call
```

Use mocks for worker/agent; do not run real opencode/agy.

---

## 13. Acceptance criteria

Done only if:

1. Normal eval run behavior is unchanged when `--golden-debug` is absent.
2. Replay/resume is impossible without both env and CLI flag.
3. Replay/resume is impossible for non-golden feature files.
4. Checkpoints are written under `GRACE_STATE_ROOT`, not target repo.
5. Checkpoints include feature hash, packet contract hash, base SHA, worktree path, branch, commit SHA where applicable.
6. `--resume-from merge` can reuse valid commit/acceptance checkpoints and skip agent rerun.
7. `--resume-from acceptance` can reuse valid agent/commit checkpoints and rerun acceptance.
8. Fingerprint mismatch fails closed for `--resume-from`.
9. Fingerprint mismatch reruns normally for `--reuse-artifacts`.
10. Report JSON shows which stages were reused.
11. Tests prove golden-only safety guards.
12. Existing FAST golden still runs without debug mode.

---

## 14. Suggested implementation order

1. Add `golden_replay.py` models/helpers.
2. Add CLI flags and safety guard validation.
3. Write checkpoints only, no skip behavior yet.
4. Add resume-from-merge using saved commit/acceptance checkpoint.
5. Add resume-from-acceptance using saved agent/commit checkpoint.
6. Add report JSON golden_debug section.
7. Add tests.

---

## 15. Final coder report format

Coder must report:

```text
Files changed
Golden debug safety guard implemented: yes/no
Checkpoint write implemented: yes/no
Resume-from merge implemented: yes/no
Resume-from acceptance implemented: yes/no
Normal mode unchanged: yes/no
Tests added
Tests run
Remaining blockers
```
