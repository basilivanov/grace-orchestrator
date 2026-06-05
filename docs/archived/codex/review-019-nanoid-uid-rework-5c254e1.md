# Codex Review 019 — NanoID UID rework after `5c254e1`

Commit reviewed: `5c254e1e67e95798580c540ca37268261966da28`

Previous review: `docs/codex/review-018-nanoid-uid-addendum-8980e2a.md`

Verdict: **PASS FOR TZ-018/TZ-018B CORE. OK TO CONTINUE GOLDEN RUNS.**

The rework closes the important review-018 items: same-title feature creation is now tested, architect response includes explicit slug aliases and packet summaries, UID generation supports an in-memory reserved set, and a source-audit test exists to prevent reintroducing legacy ID parsing patterns.

---

## Fixed from review-018

### P0-1 — Same-title regression test

Status: **fixed.**

`tests/api/test_architect_api.py` now includes:

```python
test_same_title_creates_different_feature_ids
```

It posts the same feature title twice and asserts:

```python
feature_id differs
slug is equal
```

This directly protects the original bug:

```text
same title → same deterministic feature ID → old failed feature reused
```

---

### P1-1 — Packet object summaries in architect response

Status: **fixed.**

`/api/architect/plan` now returns:

```json
"packet_summaries": [
  {
    "id": "pkt_...",
    "slug": "...",
    "title": "...",
    "wave_id": "wave_..."
  }
]
```

It keeps backward-compatible lists:

```json
"packets": ["pkt_..."],
"packet_ids": ["pkt_..."]
```

This is a good compatibility shape.

---

### P1-2 — `feature_slug` alias

Status: **fixed.**

Response now includes both:

```json
"feature_slug": "...",
"slug": "..."
```

Good. New clients can use explicit `feature_slug`; old code can still use `slug`.

---

### P1-3 — In-memory reserved UID collision handling

Status: **fixed for single-plan batch collisions.**

`generate_unique_id(...)` now accepts:

```python
reserved: set[str] | None = None
```

and rejects values already in `reserved`.

`architect.py` tracks:

```python
plan_used_ids: set[str] = set()
```

and passes it while generating feature/wave/packet IDs.

This covers forced in-memory collisions during a single plan build.

P2 note: true parallel API-request collisions are still theoretically possible between UID generation and DB insert. With 10-char NanoID this is practically negligible. If this ever matters, catch DB `IntegrityError` around persist and retry the whole plan ID generation.

---

### P1-4 — Source audit test

Status: **fixed.**

`tests/test_no_legacy_id_assumptions.py` scans:

```text
src
tests
scripts
grace
```

for forbidden patterns:

```text
split("-W") / split('-W')
split("-P") / split('-P')
startswith("FEAT-") / startswith('FEAT-')
```

This is the right guard against semantic parsing of legacy deterministic IDs.

P2 note: the allowlist includes a few tests by filename. Keep that list small; do not let it become a place to hide new ID parsing assumptions.

---

### P1-5 — Scripts clean

Status: **accepted based on source-audit test and reported grep.**

The source audit includes `scripts`, and the commit report says scripts were already clean. Good enough.

---

### P2 — Schema docstring typo

Status: **fixed.**

`title-derivated` was corrected to `title-derived`.

---

## What looks correct in current implementation

### Architect creates generated IDs, not deterministic title IDs

Current flow:

```python
feature_id = generate_unique_id(db, Feature, new_feature_uid, reserved=plan_used_ids)
wave_id = generate_unique_id(db, Wave, new_wave_uid, reserved=plan_used_ids)
pkt_id = generate_unique_id(db, Packet, new_packet_uid, reserved=plan_used_ids)
```

IDs are no longer built from title/wave/order/action.

---

### Slugs remain separate human-readable labels

Persist still uses:

```python
Feature(id=feature_id, slug=slug, ...)
Wave(id=wave_id, slug=wave_slug, ...)
Packet(id=pkt_id, slug=pkt_slug, ...)
```

This matches the intended model:

```text
id = canonical UID
slug = readable label, not identity
```

---

### API compatibility is preserved

Old clients can still read:

```json
"packets": ["pkt_..."]
```

New clients can use:

```json
"packet_ids": [...]
"packet_summaries": [...]
"feature_slug": "..."
```

This avoids breaking current worker/eval/golden scripts while enabling cleaner UI/scripts later.

---

## Remaining non-blocking notes

### P2-1 — `packet_summaries` does not include `wave_slug` or packet order

Not required by review-018, but useful for admin UI.

Later consider:

```json
{
  "id": "pkt_...",
  "slug": "...",
  "title": "...",
  "wave_id": "wave_...",
  "wave_slug": "...",
  "order": 1
}
```

Not a blocker.

---

### P2-2 — Source audit test uses grep subprocess

This is acceptable for now. Later, Python-native scanning with `Path.rglob()` would be more portable and easier to allowlist precisely.

Not a blocker.

---

### P2-3 — Parallel insert collision is not retried

As noted above, `reserved` protects one in-memory plan. It does not protect against two API calls generating the same random UID before either commits.

Given 62^10-ish space and internal system scope, this is fine. If you want perfect correctness later, add DB unique-violation retry on persist.

Not a blocker.

---

## Suggested tests to run

```bash
pytest tests/api/test_architect_api.py -q
pytest tests/grace_control/core/test_uid.py -q
pytest tests/test_no_legacy_id_assumptions.py -q
pytest tests/integration/test_wave_gate_flow.py -q
pytest tests/test_db_schema.py -q
pytest tests/test_self_evolution.py -q
pytest tests -q
```

No GitHub combined statuses were attached to `5c254e1e67e95798580c540ca37268261966da28`, so I could not independently verify local test claims.

---

## Final verdict

**PASS FOR TZ-018/TZ-018B CORE.**

This is good enough to continue golden runs and rely on NanoID-style feature/wave/packet identities for the current control-plane workflow.
