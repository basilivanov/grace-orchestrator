# Review 008 — Admin Control Center Stage 02

Status: CHANGES REQUIRED

Implementation commit reviewed: `956075c79263fb223fbea1cd14f2a02293567519`.

The Stage 02 shape is broadly correct: project-local raw packet/run/stage DTOs, events payload drill-down, lease diagnostics, named-root filesystem API, Git read API, OpenAPI retrieval and capability discovery are present. However three acceptance/security issues remain.

## Required fixes

### 1. Secret-path policy is bypassable through an in-root symlink alias

`SafeFilesystemService._resolve()` checks `_is_secret_path(relative)` only on the caller-supplied relative path, then resolves `realpath` and checks containment. This blocks symlink escape outside the root, but it does not re-apply the deny policy to the resolved in-root path.

Example inside an allowed root:

```text
.env                 # denied directly
public-link -> .env  # currently readable via public-link
```

Because `public-link` is not a denied name and its realpath remains inside the allowed root, `read_file("state", "public-link")` can disclose the denied `.env` content.

Required:

- after `realpath`, derive the resolved path relative to the canonical root and apply the same normalized secret-path deny policy to that resolved relative path;
- preserve normal safe in-root symlink behavior if desired, but aliases to denied paths must be rejected;
- add a real temp filesystem test for an in-root symlink alias to `.env` (and/or another denied pattern), in addition to the existing outside-root symlink test.

### 2. Git reads are only truncated after unbounded stdout has already been captured

`AdminGitReadService` calls `GitService._run(...)`, whose implementation uses `subprocess.run(..., capture_output=True, text=True)`. Methods such as `diff`, `diff_stat`, `tracked_files`, `commits` and `show_file` then apply `_bounded_text()` / slicing only after the complete Git stdout is already resident in memory.

That does not satisfy Task 008 constraints 10 and 14: Git output must be bounded, and large diffs/files must not be read unbounded into memory.

Required:

- enforce the byte/output cap while reading the Git subprocess output, not only when serializing the response;
- retain a bounded timeout;
- terminate/stop consuming safely once the configured cap is reached and return `truncated: true` where appropriate;
- do not weaken ref/path validation;
- add an acceptance test with Git output materially larger than the configured cap and prove the bounded read path is used. Avoid a test that only asserts the final JSON string length after a full capture.

A dedicated bounded read primitive in `GitService` is preferable to duplicating raw subprocess logic in routers.

### 3. `runtime_identity.code_sha` reports the target repository SHA, not the GRACE runtime SHA

`get_runtime_identity()` currently computes:

```python
code_sha = GitService().current_sha(target_repo_root)
```

For the intended topology GRACE may run separately from the target project, so this value is the target repository HEAD, not the **GRACE code SHA** required by TZ02. The Control Center needs to distinguish GRACE runtime build/version from target-project Git state.

Required:

- expose GRACE runtime code/build SHA from the GRACE runtime/package/repository context;
- expose target repository HEAD separately (for example `target_head`) if available;
- keep `version` as the GRACE version;
- add a test where GRACE/runtime identity and target repo are intentionally different so the two values cannot accidentally collapse to one field.

## Scope

Do not start Task 009 or Stage 03. Fix only these Stage 02 issues and any directly exposed regressions.

Re-run the focused Stage 02 acceptance tests plus relevant Admin/Trace/Events/Diagnostics/Task 007 regressions, Ruff, `py_compile`, GRACE lint and `git diff --check`.

Then create/update:

`docs/work/agent_exchange/outbox/008_RESUBMISSION.md`

Include the fix commit SHA and concise results.