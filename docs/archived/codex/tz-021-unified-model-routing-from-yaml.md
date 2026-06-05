# TZ 021 — Unified Model Routing from agent_profiles.yaml

Audience: Coder (literal executor).

Goal: eliminate 4 hardcoded model/CLI references in architect, verifier, reviewer, and context_collector. Route all LLM calls through `executor_selector.py` reading `agent_profiles.yaml`.

---

## 0. Why

`agent_profiles.yaml` already defines executors with model, CLI, and roles:

```yaml
codex:
  executors:
    - executor_id: architect-premium
      model: deepseek/deepseek-v4-pro
      command: opencode
      roles: [architect, reviewer]
    - executor_id: coder-flash
      model: deepseek/deepseek-v4-flash
      roles: [coder]
```

But 4 call sites bypass this and hardcode models:

| File | Role | Hardcoded |
|------|------|-----------|
| `architect.py:46` | architect | `ARCHITECT_MODEL = "deepseek/deepseek-v4-pro"` |
| `architect.py:220` | context_collector | `model="deepseek/deepseek-v4-flash"` |
| `evidence_verifier.py:140` | verifier | `model="gemini-3.5-flash", cli="agy"` |
| `reviewer_gate.py:135` | reviewer | `model="deepseek/deepseek-v4-pro", cli="opencode"` |

Only `coder` role uses `executor_selector.py:select_executor()` (via `packet_executor.py:177`).

---

## 1. Required changes — agent_profiles.yaml

### 1.1 Add executor for verifier

Under `codex.executors`, add:

```yaml
    # ── Verifier (agy) ────────────────────────────────────────
    - executor_id: verifier-agy
      kind: agy
      command: agy
      model: gemini-3.5-flash
      roles: [verifier]
      priority: 10
      metadata:
        provider: gemini
```

### 1.2 Add executor for context_collector

Under `codex.executors`, add:

```yaml
    # ── Context Collector (opencode) ────────────────────────────
    - executor_id: context-collector-flash
      kind: opencode
      command: opencode
      model: deepseek/deepseek-v4-flash
      roles: [context_collector]
      priority: 10
      metadata:
        provider: deepseek
```

---

## 2. Required changes — executor_selector.py

### 2.1 Add `resolve_model(role: str) -> dict`

New public function. Returns `{model, command, kind}` for the first executor matching the role.

```python
def resolve_model(role: str) -> dict:
    """Return {model, command, kind} for the best executor matching the role.
    No attempt-based escalation — always picks highest priority."""
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])

    matching = [e for e in executors if role in e.get("roles", [])]
    if not matching:
        return {
            "model": DEFAULT_MODEL,
            "command": DEFAULT_EXECUTOR["command"],
            "kind": "default",
        }

    matching.sort(key=lambda e: e.get("priority", 0), reverse=True)
    best = matching[0]
    return {
        "model": best.get("model", DEFAULT_MODEL),
        "command": best.get("command", "opencode"),
        "kind": best.get("kind", "opencode"),
    }
```

### 2.2 Do NOT change `select_executor()`

`select_executor()` keeps its attempt-based escalation logic for coder. Not touched.

---

## 3. Required changes — call sites

### 3.1 architect.py:46 — remove ARCHITECT_MODEL constant

**Before:**
```python
ARCHITECT_MODEL = "deepseek/deepseek-v4-pro"
```

**After:**
```python
# Deleted. Replace usage with resolve_model("architect")["model"].
```

Also at line 358 where `ARCHITECT_MODEL` is used:
```python
raw = await _run_opencode(prompt, ARCHITECT_MODEL)
```
Replace with:
```python
from grace_control.core.executor_selector import resolve_model
executor = resolve_model("architect")
raw = await _run_opencode(prompt, executor["model"])
```

### 3.2 architect.py:220 — context_collector model

**Before:**
```python
collector = ContextCollector(cli="opencode", model="deepseek/deepseek-v4-flash")
```

**After:**
```python
executor = resolve_model("context_collector")
collector = ContextCollector(cli=executor["command"], model=executor["model"])
```

### 3.3 evidence_verifier.py:140 — verifier model+CLI

**Before:**
```python
raw = await run_llm(full_prompt, role="verifier", model="gemini-3.5-flash", cli="agy")
```

**After:**
```python
from grace_control.core.executor_selector import resolve_model
executor = resolve_model("verifier")
raw = await run_llm(full_prompt, role="verifier", model=executor["model"], cli=executor["command"])
```

### 3.4 reviewer_gate.py:135 — reviewer model+CLI

**Before:**
```python
raw = await run_llm(full_prompt, role="reviewer", model="deepseek/deepseek-v4-pro", cli="opencode")
```

**After:**
```python
from grace_control.core.executor_selector import resolve_model
executor = resolve_model("reviewer")
raw = await run_llm(full_prompt, role="reviewer", model=executor["model"], cli=executor["command"])
```

---

## 4. Affected files

```text
src/prefect_grace/agent_profiles.yaml          — add 2 executors
src/grace_control/core/executor_selector.py    — add resolve_model()
src/grace_control/api/routers/architect.py      — 2 replacements
src/grace_control/core/evidence_verifier.py     — 1 replacement
src/grace_control/core/reviewer_gate.py         — 1 replacement
```

5 files, ~40 lines changed, ~15 lines added.

---

## 5. What must NOT change

- `executor_selector.py:select_executor()` — keeps coder escalation logic
- `llm_runner.py` — already accepts model/cli as parameters, no change needed
- `agent_profiles.yaml:roles.*` — timeout/sandbox config, no change needed
- `agent_profiles.yaml:executors:coder-*` — already used, no change needed
- Any golden test YAMLs — not affected
- Acceptance pipeline — not affected
- Merge logic — not affected

---

## 6. Acceptance criteria

- `resolve_model("architect")` returns `{model: "deepseek/deepseek-v4-pro", command: "opencode"}`
- `resolve_model("verifier")` returns `{model: "gemini-3.5-flash", command: "agy"}`
- `resolve_model("reviewer")` returns `{model: "deepseek/deepseek-v4-pro", command: "opencode"}`
- `resolve_model("context_collector")` returns `{model: "deepseek/deepseek-v4-flash", command: "opencode"}`
- `resolve_model("nonexistent")` returns default fallback (gemini-3.5-flash, agy)
- All 7 golden live tests still pass (no model/CLI changes — same values, just sourced from YAML)
- No new imports in call sites break existing tests
- `ARCHITECT_MODEL` constant deleted and all usages replaced

---

## 7. Implementation order

```text
1. Add 2 executors to agent_profiles.yaml
2. Add resolve_model() to executor_selector.py
3. Replace architect.py (2 places)
4. Replace evidence_verifier.py (1 place)
5. Replace reviewer_gate.py (1 place)
6. Re-run golden tests 001-007 to verify no regressions
```
