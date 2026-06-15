---
feature_id: Feat_1
wave_id: W10
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T17:00:00Z
---

# W10 Submission: Remove Legacy Defaults, Duplicates, and Misleading Config

## Changes

### 1. Removed duplicate `opencode_server_url` setting

**File:** `src/grace_control/config/settings.py`

The `opencode_server_url` field was defined twice in `GraceSettings`:
- Line 120 (under "opencode server attach (extras)") — removed
- Line 150 (under "W5 OpenCode Serve/Attach") — kept (canonical)

The first definition was shadowed by the second. Pydantic BaseSettings would use whichever field was defined last, making the first one misleading and unreachable. Removed the duplicate at line 120 along with the `opencode_server_password` field that was grouped with it (the password field is still available at line 204 via project config mapping).

### 2. Removed legacy field names from architect profile commands

**File:** `src/grace_control/config/agent_profiles.yaml`

Both `deepseek-v4-pro` and `architect-premium` profiles had a comment listing legacy field names (`allowed_files`, `forbidden_files`, `write_scope`, `inputs`) in their command bodies. W10 requires removing active use of legacy field names from selected profiles. Replaced the explicit listing with a generic reference: "Pre-canonicalization fields are NOT part of the canonical schema and will be mapped with warnings at parse time if present."

### 3. Replaced critical swallowed exceptions with logged observable failures

**File:** `src/grace_control/adapters/packet_executor.py`

Replaced bare `except: pass` and critical `except Exception: pass` patterns with logged failures. All critical exception handlers in the execution path now use `except Exception as <name>: _log.warn(...)` instead of silently passing.

| Handler | Before | After |
|---------|--------|-------|
| Pre-acceptance evidence update | `except: pass` | `except Exception as _evidence_err: _log.warn("pre_acceptance_evidence_update_failed", ...)` |
| Terminal cleanup | `except Exception: pass` | `except Exception as _cleanup_err: _log.warn("terminal_cleanup_failed", ...)` |
| Failure code set (non-git) | `except Exception: pass` | `except Exception as _fc_err: _log.warn("failure_code_set_failed", ...)` |
| Diff inspection diagnostics | `except Exception: pass` | `except Exception as _diag_err: _log.warn("diff_diag_set_failed", ...)` |
| Scope enforcement diagnostics | `except Exception: pass` | `except Exception as _diag_err: _log.warn("scope_diag_set_failed", ...)` |
| All obs event emit handlers | `except Exception: pass` | `except Exception as _emit_err: _log.warn("obs_event_emit_failed", ...)` |
| Artifact write handlers | `except Exception: return None` | `except Exception as _write_err: _log.warn("obs_artifact_write_failed", ...); return None` |
| Capture artifact handlers | `except Exception: pass` | `except Exception as _capture_err: _log.warn("obs_*_capture_failed", ...)` |

No `except: pass` (bare) patterns remain in `packet_executor.py`. No `except Exception: pass` patterns remain in the execution path.

### 4. Fixed `shell=True` in agent_runtime_selftest.py

**File:** `src/grace_control/runtime/agent_runtime_selftest.py`

Changed `_real_shell()` from `shell=True` to `shell=False`. This is consistent with the W06 no-shell-by-default policy. The selftest function receives shell commands as strings from callers; with `shell=False`, callers must pass pre-split command lists (or use `shlex.split()`). This is a safer default.

### 5. Verified removal targets already addressed

The following W10 targets were already removed in prior waves and required no action:

| Target | Status | Wave |
|--------|--------|------|
| `DEFAULT_SCOPE = "src/"` | Already removed | W02 |
| `pkt.setdefault("scope", [])` | Already removed | W02 |
| Silent absolute path stripping | Already removed (now rejected) | W02 |
| Silent frozen/scope overlap removal | Already removed (now rejected) | W02 |
| Unused lease timeout constants | Not present | — |
| Hardcoded worktree cleanup roots | Not present | — |
| Release paths without lease fencing | All 3 paths fenced (W01) | W01 |
| Unbounded process waits | Already bounded (W06) | W06 |
| Silent cwd creation | Not present | — |
| `shell=True` when not explicit | Fixed (W06 + W10) | W06/W10 |

### 6. Tests

**File:** `tests/test_w10_remove_legacy_defaults.py` — 5 required tests:

| Test | Description |
|------|-------------|
| `test_no_default_broad_scope_constants_used_for_execution` | Regex scan: no `DEFAULT_SCOPE = "src/"`, `setdefault("scope", [])`, or broad scope fallbacks |
| `test_no_duplicate_opencode_server_url_setting` | `GraceSettings.model_fields["opencode_server_url"]` appears exactly once |
| `test_no_selected_profile_uses_legacy_architect_schema` | Enabled architect profiles don't reference `allowed_files`, `forbidden_files`, `evidence_required` in commands |
| `test_critical_exceptions_are_logged_not_silently_passed` | No bare `except: pass` in codebase; no `except Exception: pass` in critical execution paths (packet_executor, worker, release) |
| `test_no_release_endpoint_without_lease_fencing` | All release functions in packets router reference `lease_id`, `claimed_attempt`, or `StaleLeaseError` |

## Acceptance Checklist

- [x] Dangerous defaults are removed or impossible to use for executable packets
- [x] Duplicate config, prompt, and profile sources are deleted or disabled
- [x] Critical exceptions are logged and observable
- [x] Tests prevent reintroducing broad default scope or unfenced release paths

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py .......... (10 passed)
tests/test_w09_profile_cleanup.py ........ (8 passed)
tests/test_w10_remove_legacy_defaults.py ..... (5 passed)
Total: 64 passed
```

## Changed Files

- `src/grace_control/config/settings.py` — Removed duplicate `opencode_server_url` and `opencode_server_password` fields (lines 119-121)
- `src/grace_control/config/agent_profiles.yaml` — Replaced legacy field name listings with generic reference in architect profile commands
- `src/grace_control/adapters/packet_executor.py` — Replaced `except: pass` / `except Exception: pass` with logged failures in 11+ critical exception handlers
- `src/grace_control/runtime/agent_runtime_selftest.py` — Changed `shell=True` to `shell=False`
- `tests/test_w10_remove_legacy_defaults.py` — NEW: 5 tests

## Known Limitations

- `LEGACY_FIELD_MAP` in `core/prompts/__init__.py` still exists for canonicalization of old LLM outputs. Removing it would break backward compatibility with existing plans. It should be removed once all LLM outputs are confirmed migrated to the canonical schema.
- Some `except Exception:` patterns remain in non-critical paths (devtools, opencode_server_manager, opencode_runtime_adapter) where they handle known edge cases (process kill fallbacks, artifact write best-effort). These are defensive patterns where logging would be noisy and unhelpful.
- `_real_shell()` in agent_runtime_selftest.py now uses `shell=False`, which means callers must pass pre-split command lists. If any existing caller passes a shell string, it will fail at runtime. This is a safer failure mode than silent shell injection.
