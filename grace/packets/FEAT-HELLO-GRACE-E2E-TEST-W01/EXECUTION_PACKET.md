# Execution Packet: FEAT-HELLO-GRACE-E2E-TEST-W01

## Objective

Create a simple Python module to validate the GRACE orchestrator end-to-end pipeline through Prefect.

This packet tests the complete orchestrator workflow: packet parsing, worktree isolation, agent execution, test verification, and review process. It validates Plan D architectural changes including configuration loading (P0-1), CLI execution (P0-3), state storage (P0-6), and security policies (P0-7).

## Slice

- slice_id: `SLICE-HELLO-GRACE-E2E-TEST`
- slice_slug: `hello-grace-e2e-test`
- feature_id: `FEAT-HELLO-GRACE-E2E-TEST`
- packet_id: `FEAT-HELLO-GRACE-E2E-TEST-W01`
- wave_id: `W01`
- status: `ready`
- phase: `PHASE-TEST`
- depends_on: ``
- feature_dir: `/tmp/grace-orchestrator-export/grace/packets/FEAT-HELLO-GRACE-E2E-TEST`

## Source Of Truth

- `/tmp/grace-orchestrator-export/src/hello_grace_e2e.py` (to be created)
- `/tmp/grace-orchestrator-export/tests/test_hello_grace_e2e.py` (to be created)

## Impacted Modules

- `M-TEST`

## Allowed Write Scope

- `/tmp/grace-orchestrator-export/src/hello_grace_e2e.py`
- `/tmp/grace-orchestrator-export/tests/test_hello_grace_e2e.py`
- `/tmp/grace-orchestrator-export/grace/packets/FEAT-HELLO-GRACE-E2E-TEST-W01/**`

## Frozen Scope

- `/tmp/grace-orchestrator-export/backend/**`
- `/tmp/grace-orchestrator-export/frontend/**`
- `/tmp/grace-orchestrator-export/prefect_grace/**`
- `/tmp/grace-orchestrator-export/.env`
- `/tmp/grace-orchestrator-export/grace/project.yaml`
- All other files

## Must Preserve

- Follow PEP 8 style guide
- Include type hints on all functions
- Add docstrings to all public functions
- Tests must be comprehensive and pass
- No external dependencies beyond stdlib and pytest
- Do not modify existing GRACE code
- Do not run Docker, backend, frontend, or live services

## Required Design Decisions

### 1. Function Signature

Create `greet(name: str) -> str` function that returns "Hello {name} from GRACE!"

### 2. Test Coverage

Minimum 2 tests:
- Test correct greeting format
- Test with different input values

### 3. Code Quality

- Type hints required
- Docstrings required
- PEP 8 compliant

## Implementation Requirements

1. Create `src/hello_grace_e2e.py` with `greet()` function
2. Function returns "Hello {name} from GRACE!" where {name} is the input parameter
3. Add proper type hints: `def greet(name: str) -> str:`
4. Add docstring explaining the function
5. Create `tests/test_hello_grace_e2e.py` with at least 2 tests
6. All tests must pass when run with pytest

## Acceptance Criteria

- `src/hello_grace_e2e.py` exists with `greet()` function
- Function has type hints and docstring
- `tests/test_hello_grace_e2e.py` exists with at least 2 tests
- All tests pass: `pytest tests/test_hello_grace_e2e.py -v`
- Code follows PEP 8
- Manual verification: `python3 -c "import sys; sys.path.insert(0, 'src'); from hello_grace_e2e import greet; assert greet('World') == 'Hello World from GRACE!'"`

## Verification

Run tests:

```bash
cd /tmp/grace-orchestrator-export
pytest tests/test_hello_grace_e2e.py -v
```

Manual verification:

```bash
cd /tmp/grace-orchestrator-export
python3 -c "import sys; sys.path.insert(0, 'src'); from hello_grace_e2e import greet; print(greet('World'))"
```

## Expected Evidence

- Test output showing 2+ tests passing
- Function implementation with type hints and docstring
- PEP 8 compliant code

## Escalation Triggers

- Tests fail
- Function signature incorrect
- Missing type hints or docstrings
- PEP 8 violations
- Timeout (> 600 seconds)
