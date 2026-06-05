# Codex Review 018 — NanoID UID addendum after `8980e2a`

Commit reviewed: `8980e2a0687c259f81c9c493bc341f7fbf5820e6`

Specs:

```text
docs/codex/tz-018-nanoid-uid-identity-model.md
docs/codex/tz-018b-nanoid-db-contracts-audit-addendum.md
```

Verdict: **REWORK_REQUIRED BEFORE RELYING ON NANOID FULLY. PASS FOR PARTIAL ADDENDUM CLEANUP.**

This commit correctly updates schema documentation and removes a few deterministic ID assumptions from tests. But the broader TZ-018/TZ-018b contract is not fully closed yet. Most importantly, the architect response still does not expose packet objects with slug/title, there is no found API regression test proving same-title feature creation creates two distinct feature UIDs, and UID generation currently checks only DB collisions, not collisions inside the same in-memory planning batch.

---

## What this commit fixes

### 1. Schema comments now clarify ID semantics

`Feature`, `Wave`, and `Packet` docstrings now say:

```text
id = canonical generated UID
slug = human-readable title-derived label
```

This matches the intended DB strategy: no new `uid` column, `id` changes semantic meaning to UID.

Minor typo remains: `title-derivated` should be `title-derived`.

---

### 2. `packet_ids` added to architect response

The response now includes:

```json
"packets": [...],
"packet_ids": [...]
```

This is useful for backwards-compatible scripts.

---

### 3. Some deterministic ID assumptions removed from tests

Good changes:

```text
test_wave_gate_flow no longer filters packet IDs by W01/W02 substrings
test_db_schema uses feat_test/wave_test/pkt_test
test_self_evolution uses feat_test instead of FEAT-TEST
```

This is directionally correct.

---

## P0-1 — Missing regression test for the original bug: same title should create distinct features

The original failure was:

```text
same title → same slug → same feature_id → old failed feature reused
```

The code on current `main` appears to generate a new `feature_id` before persist, so behavior may be fixed. But I did not find a dedicated API test proving it.

Required test:

```text
tests/api/test_architect_ids.py::test_same_title_creates_different_feature_ids_and_same_slug
```

Test logic:

```python
payload = {"feature_spec": {"title": "Golden Smoke Live 002", "waves": [...]}}
r1 = await api.post("/api/architect/plan", json=payload)
r2 = await api.post("/api/architect/plan", json=payload)

assert r1.json()["data"]["feature_id"].startswith("feat_")
assert r2.json()["data"]["feature_id"].startswith("feat_")
assert r1.json()["data"]["feature_id"] != r2.json()["data"]["feature_id"]
assert r1.json()["data"]["slug"] == r2.json()["data"]["slug"] == "golden-smoke-live-002"
```

This is the most important regression test for TZ-018.

---

## P1-1 — Architect response still returns `packets` as string list, not packet objects

TZ-018b requested either adding packet objects or preserving old list while adding a richer object field.

Current response still has:

```json
"packets": ["pkt_...", "pkt_..."],
"packet_ids": ["pkt_...", "pkt_..."]
```

This duplicates the same list twice but does not expose:

```json
{"id": "pkt_...", "slug": "add-date-util", "title": "Add date util"}
```

Required fix:

Keep backward compatibility, but add object list:

```json
"packet_ids": ["pkt_..."],
"packets": [
  {"id": "pkt_...", "slug": "add-date-util", "title": "Add date util", "wave_id": "wave_..."}
]
```

If changing `packets` would break too much, use:

```json
"packet_ids": ["pkt_..."],
"packet_summaries": [
  {"id": "pkt_...", "slug": "add-date-util", "title": "Add date util", "wave_id": "wave_..."}
]
```

Then update scripts/tests to prefer `packet_summaries[0].id` or fallback to `packet_ids[0]`.

Add test:

```text
test_architect_response_packet_objects_include_id_slug_title
```

---

## P1-2 — Architect response should include `feature_slug` alias

Current response includes:

```json
"slug": "golden-smoke-live-002"
```

For clarity after separating UID vs slug, add:

```json
"feature_slug": "golden-smoke-live-002"
```

Keep `slug` for compatibility.

Add test:

```text
test_architect_response_contains_feature_id_and_feature_slug
```

---

## P1-3 — UID generation checks DB collisions but not in-memory batch collisions

Current flow generates UIDs before persist using separate DB sessions:

```python
with get_db() as db:
    feature_id = generate_unique_id(db, Feature, new_feature_uid)
...
with get_db() as db:
    wave_id = generate_unique_id(db, Wave, new_wave_uid)
...
with get_db() as db:
    pkt_id = generate_unique_id(db, Packet, new_packet_uid)
```

`generate_unique_id(...)` checks existing DB rows, but it does not know about IDs already generated earlier in the same plan and not yet committed.

For real NanoID, collision probability is tiny, but tests should force collisions and the code should handle them deterministically.

Required fix:

Add in-memory `used_ids: set[str]` during plan creation:

```python
used_ids = set()

def generate_plan_uid(db, model, factory):
    for _ in range(10):
        value = generate_unique_id(db, model, factory)
        if value not in used_ids:
            used_ids.add(value)
            return value
    raise RuntimeError("failed to generate unique in-plan id")
```

Or update `generate_unique_id(...)` to accept:

```python
reserved: set[str] | None = None
```

and reject values already in `reserved`.

Tests:

```text
test_generate_unique_id_retries_on_reserved_collision
test_architect_plan_packet_uid_batch_collision_retries
```

---

## P1-4 — Need source audit tests for old ID parsing assumptions

TZ-018b requested source/fixture audit for old assumptions:

```text
split("-W")
split("-P")
startswith("FEAT-")
packet_id contains W01/P01
```

This commit fixes one test, but does not add a source-level guard to prevent recurrence.

Add test:

```text
tests/test_no_legacy_id_assumptions.py
```

It should scan `src/`, `tests/`, `scripts/`, `grace/features/` with a small allowlist for historical docs/TZ files.

Required forbidden production patterns:

```python
'split("-W"'
"split('-W'"
'split("-P"'
"split('-P'"
'startswith("FEAT-"'
"startswith('FEAT-'"
```

Allow historical docs in `docs/codex/` if needed.

---

## P1-5 — Golden scripts/runbooks still need direct verification

The commit message says YAML contracts are clean, but this commit does not show script changes. Make sure `run_golden.py` or equivalent scripts use returned IDs, not deterministic constants.

Required test if script exists:

```text
test_run_golden_uses_returned_feature_id_not_deterministic_slug
```

Manual grep command:

```bash
grep -RInE "FEAT-|W01|P01|feature_id =|packet_id =" scripts grace tests src \
  --exclude-dir=__pycache__
```

Classify hits as either valid display labels or bugs.

---

## P2 — Schema docstring typo

Fix:

```text
title-derivated → title-derived
```

Not a blocker.

---

## What is good enough for current golden?

This is likely safe for continuing golden work if the current golden script uses returned IDs and the API server is restarted on the new code.

But do not call TZ-018/TZ-018b fully complete until the regression tests above are added, especially the same-title duplicate creation test.

---

## Required rework checklist

1. Add `test_same_title_creates_different_feature_ids_and_same_slug`.
2. Add `feature_slug` alias to architect response.
3. Add packet object summaries to architect response, or make `packets` object list and keep `packet_ids` as legacy list.
4. Add in-memory reserved UID collision handling during plan creation.
5. Add source audit test for legacy ID parsing assumptions.
6. Verify/update golden scripts to use returned IDs.
7. Fix schema docstring typo.

---

## Suggested tests

```bash
pytest tests/grace_control/core/test_uid.py -q
pytest tests/api/test_architect_ids.py -q
pytest tests/integration/test_wave_gate_flow.py -q
pytest tests/test_db_schema.py -q
pytest tests/test_self_evolution.py -q
pytest tests -q
```

No GitHub combined statuses were attached to `8980e2a0687c259f81c9c493bc341f7fbf5820e6`, so I could not independently verify the claimed 40 tests.

---

## Final verdict

**REWORK_REQUIRED BEFORE RELYING ON NANOID FULLY. PASS FOR PARTIAL ADDENDUM CLEANUP.**

The commit is a useful cleanup, but it does not yet close the core regression coverage required by TZ-018/TZ-018b.
