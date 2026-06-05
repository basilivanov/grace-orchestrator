# GraceLint Rules

Enforced by `scripts/grace_lint.py` (thin wrapper around
`grace_control.tools.grace_lint.checker`).

## Rule table

| Code | Check | Scope | Allowlist |
| --- | --- | --- | --- |
| `GRC001` | AI_HEADER present | All `.py` | — |
| `GRC002` | MODULE_CONTRACT START/END balanced | All `.py` | — |
| `GRC003` | MODULE_MAP START/END balanced | All `.py` | — |
| `GRC004` | START_BLOCK/END_BLOCK pairing | All `.py` | — |
| `GRC005` | File ≤ 1000 lines | All `.py` | — |
| `GRC010` | Public function has FUNCTION_CONTRACT | All `.py` | — |
| `GRC011` | FUNCTION_CONTRACT has required fields | All `.py` | — |
| `GRC012` | Function ≤ 4000 tokens | All `.py` | — |
| `GRC020` | MODULE_CONTRACT present | All `.py` | — |
| `GRC021` | MODULE_MAP present | All `.py` | — |
| `GRC030` | No compressed file | All `.py` | — |
| `GRC100` | No `os.environ` outside config/tests/scripts | `src/grace_control/` | `.grace/lint_allowlist.yaml` |
| `GRC101` | No `subprocess` outside service/tests/scripts boundary | `src/grace_control/` | `.grace/lint_allowlist.yaml` |
| `GRC102` | No `prefect_grace` import in runtime code | `src/grace_control/` | `.grace/lint_allowlist.yaml` |
| `GRC103` | No `Packet.state` mutation outside `PacketService` | `src/grace_control/` (-services/tests) | `.grace/lint_allowlist.yaml` |
| `GRC105` | No hardcoded `/tmp/grace-*` paths | `src/grace_control/` | `.grace/lint_allowlist.yaml` |
| `GRC106` | No hardcoded `"main"` / `"origin"` outside config | `src/grace_control/` | `.grace/lint_allowlist.yaml` |
| `GRC108` | Modules > 300 lines must have `START_BLOCK` sections | `src/grace_control/` | `.grace/lint_allowlist.yaml` |

## Allowlist

The file `.grace/lint_allowlist.yaml` contains temporary exemptions. Each
entry includes:

```yaml
- rule: GRC100
  path: src/grace_control/adapters/packet_executor.py
  reason: os.environ.setdefault for sandbox bypass (W11 target)
  expires_wave: W11
```

## How to run

```bash
# Default: all rules, all files
make lint

# Specific rules
python3 scripts/grace_lint.py src/ --rules GRC100 GRC101

# Skip function contracts (faster)
python3 scripts/grace_lint.py src/ --skip-function-contracts

# Via API
curl -X POST http://localhost:8042/api/tools/grace-lint/run \
  -H "Content-Type: application/json" \
  -d '{"paths": ["src/grace_control/api/routers"], "strict": true}'
```

## Adding a new rule

1. Add a `_check_*` function in `checker.py`
2. Wire it into `lint_text()` and add to `DEFAULT_RULES`
3. Write a fixture test in `tests/grace_control/core/test_grace_lint.py`
4. Add a row to this table
5. Add any necessary allowlist entries in `.grace/lint_allowlist.yaml`
