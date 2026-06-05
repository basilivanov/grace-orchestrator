# Review: `72a0e5e` W13 final follow-up

Date: 2026-06-05
Reviewed commit: `72a0e5e4ce1b0c414b682a327d48f73bea79f842`
Previous review: `source/codex/review-2026-06-05-582ea84-w13-followup.md`

## Verdict

Almost accepted, but one cleanup blocker remains.

The actual W13 architecture issues from the previous review are now fixed:

- `llm_runner.py` resolves an executor profile via `get_agent_profile(cli)`.
- `llm_runner.py` no longer builds the command list inline.
- `llm_runner.py` no longer writes a duplicate prompt file.
- `CommandTemplateRenderer` unused import/global was removed.
- `AgentRunService` now sets/writes `packet_path` before command rendering.
- Regression tests were added for profile resolution, unknown profile, and empty/non-zero output.
- Reported test suite is green: `405 passed, 0 failed`.

However, the commit also appears to add generated runtime artifacts under `agents/llm_architect_*/EXECUTION_PACKET.md`. These must not live in the repository.

---

## Accepted items

### A1. `llm_runner.py` is now profile-backed

Accepted.

The new flow is:

```python
executor_id = cli or f"llm_{role}"
profile = get_agent_profile(executor_id)
executor = profile.to_dict()
```

This replaces the previous inline command construction:

```python
[cli, "run", "--model", model, ...]
```

Now command shape comes from `agent_profiles.yaml`, which matches the UniversalCliAgentBackend design.

### A2. `packet_path` is available before command rendering

Accepted.

`AgentRunService` now handles file input before rendering command:

```python
if input_mode == "file":
    effective_run_dir = run_dir or (state_root / "agents" / packet_id)
    packet_path = effective_run_dir / "EXECUTION_PACKET.md"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(packet_markdown)
    ctx["packet_path"] = str(packet_path)

command = self._renderer.render(executor.get("command", []), ctx)
```

This fixes the previous bug where `{packet_path}` rendered to an empty string.

### A3. Duplicate prompt file removed

Accepted.

`llm_runner.py` no longer writes a separate `.grace/llm_prompts/...` file that is ignored by the backend. Packet materialization is now owned by `AgentRunService` file mode.

### A4. W13 tests added

Accepted.

The new tests cover:

- profile-backed `run_llm()` resolution;
- unknown profile failure;
- empty/non-zero output failure.

---

# Remaining blocker

## P1. Generated runtime artifacts were committed

The commit diff includes new files like:

```text
agents/llm_architect_1eb971/EXECUTION_PACKET.md
agents/llm_architect_492a2e/EXECUTION_PACKET.md
agents/llm_architect_a3dd49/EXECUTION_PACKET.md
agents/llm_architect_c39b55/EXECUTION_PACKET.md
agents/llm_architect_c6fe84/EXECUTION_PACKET.md
agents/llm_architect_fca328/EXECUTION_PACKET.md
```

These are generated runtime/test artifacts, not source files.

Impact:

- repository gets polluted by local/test execution state;
- future tests may accidentally depend on stale artifacts;
- this violates the cleanup/canon goal of keeping runtime state outside source control.

Required fix:

1. Delete committed `agents/llm_architect_*/EXECUTION_PACKET.md` files from the repository.
2. Add an ignore rule for generated local agent artifacts, for example:

```gitignore
/agents/
```

or a narrower pattern:

```gitignore
/agents/llm_*/
```

3. Add/adjust tests so W13 tests write artifacts only under `tmp_path`, not repository root.
4. Re-run tests and confirm green.

---

## Optional quality notes

### O1. Test mutates `PATH`

The new tests prepend fake CLI path into `os.environ["PATH"]`. This is acceptable in tests, but safer with `monkeypatch.setenv()` to avoid cross-test leakage.

### O2. `opencode` profile in config is acceptable

The new `agents.opencode` profile has concrete `opencode` command. This is allowed because CLI command names belong in config, not runtime code.

---

## Required next patch

Title:

```text
fix(W13): remove generated agent artifacts from repo
```

Scope:

```text
agents/llm_architect_*/EXECUTION_PACKET.md
.gitignore
tests/grace_control/core/test_llm_runner.py
```

Acceptance:

1. No `agents/llm_architect_*` files are tracked.
2. `.gitignore` prevents generated `/agents/` test/runtime artifacts from being re-added.
3. W13 tests use `tmp_path` / isolated state root and do not create files under repo root.
4. Test suite remains green.

Once this is done, W13 can be accepted cleanly.
