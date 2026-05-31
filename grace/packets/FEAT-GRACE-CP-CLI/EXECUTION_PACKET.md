# Execution Packet: FEAT-GRACE-CP-CLI-W03-CLI-COMMANDS

## Objective

Create the CLI for GRACE Control Plane: `grace architect plan <file>`, `grace packet list/get`, `grace worker start`, `grace api start`, `grace health`. Rich formatting (tables, colors), httpx-based API calls, JSON output option.

The CLI is a thin wrapper over the API — all business logic lives in the server.

## Slice

- slice_id: `SLICE-CLI`
- slice_slug: `cli-commands`
- feature_id: `FEAT-GRACE-CP-CLI`
- packet_id: `FEAT-GRACE-CP-CLI-W03-CLI-COMMANDS`
- wave_id: `W03`
- status: `ready`
- phase: `PHASE-3`
- depends_on: `FEAT-GRACE-CP-API-W02-FASTAPI-SERVER`
- feature_dir: `grace/packets/FEAT-GRACE-CP-CLI`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §9 (vertical slice: grace architect plan)
- `tasks/PHASE_3_CLI_E2E_REVISED.md` Task #19
- `development-plan.xml` — FEAT-GRACE-CLI
- `pyproject.toml` — [project.scripts] grace = "grace_control.cli.main:cli"

## Impacted Modules

- `M-GRACE-CP-CLI`

## Allowed Write Scope

- `src/grace_control/cli/__init__.py`
- `src/grace_control/cli/main.py`
- `src/grace_control/logging.py`
- `tests/test_cli.py`
- `grace/packets/FEAT-GRACE-CP-CLI/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/db/**` — read-only
- `src/grace_control/api/**` — server, CLI is client
- `src/grace_control/worker/**` — worker, CLI launches it
- `src/grace_control/adapters/**` — read-only
- `src/grace_control/core/**` — read-only

## Must Preserve

- CLI uses click (not typer — typer is legacy)
- All API calls via httpx
- Rich formatting (Table for lists, colored statuses)
- JSON output via --json flag: {"ok": true, "result": {...}, "warnings": [], "errors": []}
- API URL configurable via --api-url (default: http://localhost:8042)
- Port configurable via --port flag on `grace api start`
- No business logic in CLI — just HTTP calls + formatting

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (`prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: `# AI_HEADER: cli` + `# ROLE: CLI entry point for GRACE Control Plane`
- **MODULE_CONTRACT**: purpose, inputs, returns, side_effects, emitted_logs, error_behavior
- **MODULE_MAP**: cli, architect, packet, worker, api, health
- **FUNCTION_CONTRACT**: у каждой команды — purpose, параметры, что вызывает
- **Блоки**: `#START_BLOCK_CLI_GROUPS`, `#START_BLOCK_COMMANDS`
- **Лимиты**: файл ≤ 1000 строк (CLI может быть длинным, но ≤1000)
- **Логирование**: `log_event()` для ошибок CLI
- **T0**: `ruff check`, `ruff format --check`, `mypy`, `compileall`

## Required Design Decisions

### 1. CLI Structure (click groups)

```python
@click.group()
def cli():
    """GRACE Control Plane CLI."""

@cli.group()
def architect():
    """Architect commands."""

@architect.command("plan")
@click.argument("feature_file", type=click.Path(exists=True))
def architect_plan(feature_file): ...

@cli.group()
def packet():
    """Packet commands."""

@packet.command("list")
@click.option("--state")
@click.option("--feature")
def packet_list(state, feature): ...

@packet.command("get")
@click.argument("packet_id")
def packet_get(packet_id): ...

@cli.group()
def worker():
    """Worker commands."""

@worker.command("start")
@click.option("--worker-id")
@click.option("--api-url", default="http://localhost:8042")
def worker_start(worker_id, api_url): ...

@cli.group()
def api():
    """API server commands."""

@api.command("start")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8042)
def api_start(host, port): ...

@cli.command("health")
def health(): ...
```

### 2. JSON Envelope Output

```python
@click.option("--json", is_flag=True, help="JSON output")
def packet_list(state, feature, json):
    if json:
        click.echo(json.dumps({"ok": True, "result": data, "warnings": [], "errors": []}))
    else:
        # Rich table
        console.print(table)
```

### 3. Rich Table for packet list

```python
table = Table(title="Packets")
table.add_column("ID", style="cyan")
table.add_column("Title", style="white")
table.add_column("State", style="green")
table.add_column("Attempts", style="yellow")
for p in data:
    state_color = {"ready": "green", "running": "yellow", "accepted": "blue",
                   "rejected": "red", "failed": "red"}.get(p["state"], "white")
    table.add_row(p["id"], p["title"], f"[{state_color}]{p['state']}[/{state_color}]",
                  f"{p['attempt_count']}/{p['max_attempts']}")
```

## Implementation Requirements

1. `src/grace_control/cli/main.py`:
   - 6 commands: architect plan, packet list, packet get, worker start, api start, health
   - All HTTP calls via httpx
   - Rich tables for list commands
   - --json flag for machine-readable output
   - --api-url flag for server location

2. `src/grace_control/logging.py`:
   - `GraceLogger(component)` class for structured JSONL logging
   - `log_event(level, message, **kwargs)` function
   - `trace_context(trace_id)` context manager

3. `tests/test_cli.py`:
   - test_packet_list_empty
   - test_packet_list_with_data
   - test_packet_get
   - test_health_command
   - test_json_output_format
   - test_api_unreachable_error

## Acceptance Criteria

- [ ] `grace architect plan test.yaml` → POST /api/architect/plan
- [ ] `grace packet list` → GET /api/packets/ with Rich table
- [ ] `grace packet list --state ready` → filtered results
- [ ] `grace packet get PKT-001` → detailed output
- [ ] `grace worker start` → launches Worker.start()
- [ ] `grace api start` → launches uvicorn
- [ ] `grace health` → system status display
- [ ] `grace packet list --json` → valid JSON envelope
- [ ] All tests pass: `pytest tests/test_cli.py -v`

## Verification

```bash
# Ensure API is running
grace api start &
sleep 2

# Test all commands
grace health
grace packet list
grace packet list --json

# Architect (requires test YAML file)
echo 'title: Test
waves:
  - title: W1
    packets:
      - title: Add test
        scope: src/test.py' > /tmp/test_feature.yaml
grace architect plan /tmp/test_feature.yaml
grace packet list

kill %1

pytest tests/test_cli.py -v
ruff check src/grace_control/cli/
mypy src/grace_control/cli/
```

## Expected Evidence

- `test-results/cli.xml`
- CLI command output (all 6 commands)
- JSON output validation
- ruff/mypy clean

## Escalation Triggers

- API unreachable at configured URL
- click version conflict with legacy typer
- Rich import error
- CLI file exceeds 1000 lines
- Subprocess (worker start) fails to launch

## Reviewer Gate

Reviewer must reject if:
- CLI contains business logic (state transitions, DB queries)
- Missing --json flag
- Missing --api-url flag
- Direct Prefect imports (not through compat layer)
- Missing GRACE contracts
- Port hardcoded (should use --port flag or default)
