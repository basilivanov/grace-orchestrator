# TZ 018b — NanoID UID addendum: DB schema semantics + YAML/contracts/fixtures audit

Audience: Flash coder / literal executor.

Parent spec: `docs/codex/tz-018-nanoid-uid-identity-model.md`

Goal: make TZ-018 complete. Before implementing NanoID identity, verify and update DB schema semantics, YAML contracts, fixture contracts, tests, runbooks, and admin UI so no old deterministic `FEAT-...-W01-P01...` identity assumptions remain.

---

## 0. Clarification: DB schema change strategy

Current DB schema already has:

```python
Feature.id = Column(String, primary_key=True)
Feature.slug = Column(String, nullable=False, index=True)
Wave.id = Column(String, primary_key=True)
Wave.feature_id = Column(String, nullable=False, index=True)
Wave.slug = Column(String, nullable=False)
Packet.id = Column(String, primary_key=True)
Packet.feature_id = Column(String, nullable=False, index=True)
Packet.wave_id = Column(String, nullable=False, index=True)
Packet.slug = Column(String, nullable=False)
```

So TZ-018 intentionally does **not** require adding new DB columns for UID.

Instead:

```text
Feature.id changes meaning from deterministic slug-derived ID to generated UID.
Wave.id changes meaning from deterministic wave ID to generated UID.
Packet.id changes meaning from deterministic packet ID to generated UID.
slug remains separate human-readable title slug.
```

Do not add an extra `uid` column in this task. That creates duplicate identity fields and more migration/API complexity.

Required schema updates are documentation/comments/tests, not new columns:

```text
Feature.id comment/docstring: canonical generated UID, e.g. feat_K7F3P9Qx2L
Wave.id comment/docstring: canonical generated UID, e.g. wave_A9mP2qR7Vz
Packet.id comment/docstring: canonical generated UID, e.g. pkt_T4V9K2mA1b
slug comment/docstring: human-readable non-unique title-derived slug
```

If there are migrations or schema snapshot tests, update them to reflect this meaning. Do not create a migration unless the project already has migration machinery and tests require it.

---

## 1. DB schema checklist

File:

```text
src/grace_control/db/schema.py
```

Update class docstrings/comments so the identity model is explicit:

```text
Feature.id is generated UID, not slug.
Wave.id is generated UID, not order/slug.
Packet.id is generated UID, not feature/wave/action path.
```

Keep columns:

```python
id = Column(String, primary_key=True)
slug = Column(String, nullable=False, index=True)
```

Do not make slug unique.
Do not make title unique.
Do not add `uid` column.

Add tests:

```text
test_schema_feature_id_is_documented_as_uid
test_schema_slug_is_not_unique_identity
```

If source-level docstring tests feel too brittle, test via create plan:

```text
same title twice -> different Feature.id, same Feature.slug
```

---

## 2. YAML feature contracts must not contain generated IDs

Feature YAML contracts should remain author-friendly and should not hardcode generated IDs.

Good YAML:

```yaml
title: Golden Smoke Live 001
waves:
  - title: Sandbox smoke
    packets:
      - title: Add sandbox date utility
```

Bad YAML after NanoID change:

```yaml
feature_id: FEAT-GOLDEN-SMOKE-LIVE-001
id: FEAT-GOLDEN-SMOKE-LIVE-001
wave_id: GOLDEN-SMOKE-LIVE-001-W01
packet_id: FEAT-GOLDEN-SMOKE-LIVE-001-...-P01-ADD-DATE
```

The architect/API should generate UIDs at creation time.

---

## 3. Required audit: all YAML/contracts/fixtures/docs

Search and update all repository files for legacy deterministic ID assumptions.

Run locally:

```bash
grep -RInE "FEAT-[A-Z0-9_-]+|-[Ww][0-9]{2}|-[Pp][0-9]{2}|feature_id:|wave_id:|packet_id:|startswith\(\"FEAT-|split\(\"-W|split\(\"-P" . \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude-dir=.grace_state \
  --exclude-dir=.grace_worktrees \
  --exclude-dir=__pycache__
```

Audit these categories:

```text
grace/features/*.yaml
grace/features/*.yml
docs/**/*.md
tests/**/*.py
tests/**/*.yaml
tests/**/*.json
scripts/**/*.py
src/**/*.py
src/grace_control/ui/templates/**
src/grace_control/ui/static/**
```

For each occurrence, classify it:

```text
A. Real contract input → remove hardcoded IDs; use title/slug only.
B. Test fixture expected ID → update to generated UID pattern or returned response ID.
C. API route path value in test → use returned feature_id/packet_id.
D. Historical docs/postmortem → can remain if explicitly marked LEGACY/HISTORICAL.
E. Prompt example → leave unless it teaches deterministic IDs.
```

User instruction: prompts do not need broad rewrite. But contracts/fixtures/runbooks do.

---

## 4. Current known YAML status

`grace/features/golden-smoke-live-001.yaml` is already in the good shape: it has title/waves/packet titles, no explicit old feature/wave/packet IDs.

Keep it that way.

But still audit all other golden YAMLs and generated fixtures.

---

## 5. Contract format after UID change

Canonical feature YAML contract should be:

```yaml
title: Golden Smoke Live 002
description: "..."
constraints:
  frozen_scope:
    - src/prefect_grace/
verification:
  t0: []
  t1: []
  t2: []
waves:
  - title: Sandbox smoke
    packets:
      - title: Add sandbox date utility
        scope:
          - sandbox/golden/live_002/
        acceptance_profile: FAST
```

No `feature_id`, `wave_id`, or `packet_id` in author-provided YAML.

API response should include generated IDs:

```json
{
  "data": {
    "feature_id": "feat_K7F3P9Qx2L",
    "feature_slug": "golden-smoke-live-002",
    "waves": [
      {"id": "wave_A9mP2qR7Vz", "slug": "sandbox-smoke"}
    ],
    "packets": [
      {"id": "pkt_T4V9K2mA1b", "slug": "add-sandbox-date-utility"}
    ]
  }
}
```

If current response only returns `packets: [id, id]`, update or add fields without breaking existing tests too much:

```json
"packet_ids": ["pkt_..."]
"packets": [{"id": "pkt_...", "slug": "...", "title": "..."}]
```

Keep backward compatibility if needed by adding new fields rather than removing old immediately.

---

## 6. API/run scripts must use returned IDs

Golden scripts and tests must not predict IDs from titles.

Bad:

```python
feature_id = "FEAT-GOLDEN-SMOKE-LIVE-002"
packet_id = "FEAT-GOLDEN-SMOKE-LIVE-002-GOLDEN...-P01-ADD-DATE"
```

Good:

```python
plan = post_architect_plan(...)
feature_id = plan["data"]["feature_id"]
packet_id = plan["data"]["packet_ids"][0] or plan["data"]["packets"][0]["id"]
```

For curl/runbooks:

```bash
FEATURE_ID=$(jq -r '.data.feature_id' plan.json)
PACKET_ID=$(jq -r '.data.packets[0].id // .data.packet_ids[0]' plan.json)
```

Update all runbooks that say:

```bash
curl -X DELETE localhost:8042/api/features/FEAT-...
```

For golden debug, deletion should use returned/current feature UID, not title-derived constant.

---

## 7. Dependency contracts

Author-provided dependencies should remain human-friendly action names or explicit generated IDs only when known.

Input YAML may use:

```yaml
depends_on:
  - add-date-util
```

or packet title action extracted by `_extract_action(...)`.

Planner must resolve those to generated packet UIDs internally before DAG validation and DB persist.

In persisted `spec_json`, either keep original author dependency and add resolved dependency:

```json
"depends_on": ["pkt_..."]
"depends_on_input": ["add-date-util"]
```

or replace `depends_on` with UIDs consistently.

Do not persist old deterministic packet IDs.

---

## 8. Admin UI audit

Admin UI must not assume IDs are long deterministic strings.

Update templates/JS to display:

```text
Title
Slug
UID
```

Links/actions must use UID.

Search UI files for old patterns:

```text
FEAT-
-W01
-P01
feature_id derived from title
packet_id split/parsing
```

If a UI wants wave/packet order labels, use `Wave.order` and packet display order from `spec_json.display_order`, not the ID string.

---

## 9. Tests to add/update

Add tests beyond TZ-018:

```text
test_feature_yaml_has_no_required_ids
test_golden_yaml_001_has_no_legacy_ids
test_same_title_creates_distinct_feature_ids_and_same_slug
test_architect_response_contains_feature_id_and_feature_slug
test_architect_response_packet_objects_include_id_slug_title
test_run_golden_uses_returned_ids_not_hardcoded_feat_slug
test_no_code_splits_packet_id_by_wave_or_packet_markers
test_no_contract_fixture_contains_legacy_deterministic_feature_id_unless_marked_legacy
```

The last two can be source/fixture grep tests if acceptable.

Example source-level test:

```python
def test_no_legacy_id_parsing_patterns():
    forbidden = ['split("-W"', "split('-W'", 'split("-P"', "split('-P'"]
    for path in Path("src").rglob("*.py"):
        text = path.read_text()
        assert not any(p in text for p in forbidden)
```

Allowlist migration/historical docs if needed.

---

## 10. Acceptance criteria addendum

TZ-018 is complete only if:

1. DB schema clearly treats `id` as UID and `slug` as non-unique label.
2. No new redundant `uid` column is added.
3. Same-title feature creation creates a new `feat_...` ID every time.
4. All author YAML contracts omit feature/wave/packet IDs.
5. All tests/scripts use returned IDs, not deterministic title-derived IDs.
6. Admin UI shows UID + slug/title separately.
7. No production code parses semantic meaning out of ID strings.
8. Historical docs with old `FEAT-...` IDs are either updated or explicitly marked legacy/history.
9. Existing FAST golden still passes.

---

## 11. Do not do

Do not rewrite prompts broadly.
Do not add `uid` columns in addition to `id` columns.
Do not make slug unique.
Do not require IDs in YAML contracts.
Do not keep title as idempotency key.
Do not delete old rows just to make tests pass.
Do not break reading legacy `FEAT-...` IDs.

---

## 12. Final coder report format

Coder must report:

```text
DB schema semantics updated: yes/no
New redundant uid column added: yes/no (must be no)
YAML contracts audited: yes/no
Fixtures/tests updated: yes/no
Run scripts updated to use returned IDs: yes/no
Admin UI updated: yes/no
Legacy ID assumptions removed from production code: yes/no
Tests added
Tests run
Remaining blockers
```
