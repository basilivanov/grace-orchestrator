# Review: Solar Sage Pilot 006 rework 2

**Review status:** NEEDS_REWORK_3
**Date:** 2026-06-11

## Reviewed refs

- `grace-orchestrator`: `4a4d348`
- `solarsage-astro`: `fd74eb1`

## Verdict

Not clean PASS yet.

## Finding 1 — unnamed BLOCK markers are skipped, not reported

The frontend and backend linter parsers now make marker ids optional. They then skip unnamed BLOCK markers with `continue`.

That means an unnamed BLOCK marker is ignored rather than emitted as a lint violation. Since block pairing does not require at least one block marker, this can let invalid unnamed blocks pass as if they were absent.

Required next fix:

- MODULE_CONTRACT and MODULE_MAP stay no-id canonical.
- BLOCK must require a name.
- unnamed BLOCK markers must produce an explicit lint violation.
- add frontend and backend negative tests for unnamed START_BLOCK / END_BLOCK.

## Finding 2 — canon.yaml glob test is weak

The orchestrator now passes raw exclude patterns from canon.yaml into PurePosixPath matching. This is the right direction.

However, the current test uses a path under components/ui, which is already covered by the hardcoded prefix exclusion. So the test can pass without proving config glob behavior.

Required next fix:

- add a glob exclusion test using a path not covered by hardcoded exclusions.
- example: a generated folder pattern and one normal source file that must remain linted.

## Finding 3 — admin artifacts final state

Comparing from the stated restore base `e6f6947` to `4a4d348`, the final changed file list no longer includes admin UI/service files. This is acceptable.

Comparing from `dd243ab` to `4a4d348` still shows those files because the revert itself is in that range. The final report should state this clearly.

## Positive checks

- Solar Sage `40a728d..fd74eb1` is narrow: only the two linter scripts changed.
- `gate_resolver.py` now uses PurePosixPath for config exclude matching.
- empty-list guard and false-origin guard remain in place.

## Final decision

**NEEDS_REWORK_3**
