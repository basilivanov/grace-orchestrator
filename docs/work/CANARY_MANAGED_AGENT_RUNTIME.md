# Canary Managed Agent Runtime

This file verifies that the Managed Agent Runtime can safely run an agent, capture changed files, enforce scope, and produce runtime diagnostics.

## Scope

Allowed write scope:

docs/work/CANARY_MANAGED_AGENT_RUNTIME.md

Frozen scope:

src/
tests/
.grace/

Agent must not modify any other files.

## Expected runtime behavior

After execution, must have:

- diff_inspection ok
- scope_enforcement ok
- runtime_diagnostics.json exists
- changed_files.json includes this file
- acceptance passed
- packet completed

## Acceptance commands

test -f docs/work/CANARY_MANAGED_AGENT_RUNTIME.md
grep -q "Managed Agent Runtime" docs/work/CANARY_MANAGED_AGENT_RUNTIME.md

## Failure conditions

Fail the packet if:

- any file outside this one changes
- any frozen scope file changes
- diff inspection fails
- scope enforcement fails
- runtime diagnostics are missing
