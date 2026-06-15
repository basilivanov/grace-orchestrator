# W10 — Remove Legacy Defaults, Duplicates, and Misleading Config

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Delete or disable legacy defaults and duplicate logic that keep reintroducing fail-open behavior.

## Scope

- planning/scope compiler paths
- prompt/profile definitions
- runtime/lease config
- process/command runner
- worker loop
- settings/config files
- `tests/`

## Removal targets

Planning and scope:

- `PacketMaterializer.DEFAULT_SCOPE = "src/"` for executable packets.
- contract fallback to `src/grace_control/`.
- `pkt.setdefault("scope", [])` in executable planning path.
- executable fallback plan with empty scope.
- silent absolute path stripping.
- silent frozen/scope overlap removal.

Prompts/profiles:

- duplicate architect prompt bodies after W03.
- incompatible `architect-premium` or unused profiles.
- active use of `allowed_files`, `forbidden_files`, `evidence_required` once transition is over.

Runtime/lease/process:

- unused lease timeout constants.
- hardcoded worktree cleanup roots.
- release paths without lease fencing.
- generic `shell=True` when not explicit.
- unbounded process waits.
- silent cwd creation.
- dead duplicate `except Exception`.
- critical `except: pass` paths.

## Acceptance

- Dangerous defaults are removed or impossible to use for executable packets.
- Duplicate config/prompt/profile sources are either deleted or disabled.
- Critical exceptions are logged and observable.
- Tests prevent reintroducing broad default scope or unfenced release paths.

## Required tests

- `test_no_default_broad_scope_constants_used_for_execution`
- `test_no_duplicate_opencode_server_url_setting`
- `test_no_selected_profile_uses_legacy_architect_schema`
- `test_critical_exceptions_are_logged_not_silently_passed`
- `test_no_release_endpoint_without_lease_fencing`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W10_001_SUBMISSION.md` when done.
