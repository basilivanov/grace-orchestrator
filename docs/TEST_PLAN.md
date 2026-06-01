# GRACE Control Plane — Full-Scale Test Plan

## Quick Run

```bash
bash scripts/verify_all.sh
```

## Test Matrix

| # | Category | Tests | Command | Time |
|---|----------|-------|---------|------|
| 1 | Smoke | 3 | `curl health + dashboard` | 5s |
| 2 | Unit | 39 | `pytest tests/ -q` | 6s |
| 3 | Live Pipeline | 1 packet | `architect → claim → release → merge` | 30s |
| 4 | Wave Gate | 2 waves | W01→W02 gate opens on completion | 60s |
| 5 | Failure Recovery | 3 scenarios | crash, retry, cancel | 3min |
| 6 | Concurrent | 2 workers | 10 packets, no duplicates | 2min |
| 7 | Stress | 100 packets | insert + claim/release 100 cycles | 3min |
| 8 | Security | 3 checks | bind 127.0.0.1, CORS, cancel blocked | 1min |

## Total: 39 automated + 10 manual scenarios
