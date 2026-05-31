# GRACE AI-First Data Model

## Философия

**AI-first = Machine-readable first**

- Основной формат: JSON/YAML (structured data)
- Markdown: только для debugging (опционально)
- Люди смотрят через UI (парсит JSON)
- Агенты читают/пишут JSON напрямую

---

## 1. Database Schema (source of truth)

### 1.1 Основные таблицы

```sql
-- Packets
CREATE TABLE packets (
    id TEXT PRIMARY KEY,
    feature_id TEXT,
    wave_id TEXT,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    acceptance_profile TEXT,
    spec_json TEXT NOT NULL,        -- Полный spec в JSON
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Packet runs
CREATE TABLE packet_runs (
    id TEXT PRIMARY KEY,
    packet_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,               -- Structured result
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (packet_id) REFERENCES packets(id)
);

-- Agent runs
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    role TEXT NOT NULL,
    executor TEXT NOT NULL,
    status TEXT NOT NULL,
    input_json TEXT,                -- Agent input
    output_json TEXT,               -- Agent output (structured)
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Test runs
CREATE TABLE test_runs (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,      -- Test results (structured)
    duration_ms INTEGER,
    created_at TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Evidence items
CREATE TABLE evidence_items (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    tier TEXT,
    path TEXT NOT NULL,             -- Path to JSON file
    metadata_json TEXT,             -- Additional metadata
    created_at TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Events (audit trail)
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,     -- Event data (structured)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Filesystem Structure (artifacts)

### 2.1 Packet artifacts (machine-readable)

```text
.grace/packets/{packet_id}/
├── packet.json                     # Packet specification
├── runs/
│   └── {run_id}/
│       ├── result.json             # Run result (structured)
│       ├── agent/
│       │   ├── input.json          # Agent input
│       │   ├── output.json         # Agent output
│       │   └── logs.jsonl          # Structured logs
│       ├── tests/
│       │   ├── T0-lint.json
│       │   ├── T1-tests.json
│       │   └── T2-tests.json
│       ├── evidence/
│       │   ├── manifest.json       # Evidence index
│       │   ├── diff.patch          # Git diff
│       │   └── changed_files.json  # List of changed files
│       └── debug/                  # Optional: only if debug enabled
│           ├── summary.md
│           ├── agent_prompt.md
│           └── agent_response.md
└── evidence/
    └── manifest.json               # Cumulative evidence
```

### 2.2 JSON schemas

#### packet.json
```json
{
  "id": "PKT-001",
  "feature_id": "FEAT-001",
  "wave_id": "WAV-001",
  "title": "Add JWT utilities",
  "description": "Implement JWT token generation and validation",
  "scope": [
    "src/auth/jwt.py",
    "tests/auth/test_jwt.py"
  ],
  "complexity": "medium",
  "risk": "high",
  "acceptance_profile": "STRICT",
  "depends_on": [],
  "acceptance_criteria": [
    "JWT tokens generated with correct claims",
    "Token expiration works",
    "All tests pass"
  ],
  "created_at": "2026-05-31T10:00:00Z"
}
```

#### result.json
```json
{
  "packet_id": "PKT-001",
  "run_id": "RUN-001",
  "attempt": 1,
  "status": "succeeded",
  "agent": {
    "role": "coder",
    "executor": "claude-sonnet-4-6",
    "status": "succeeded",
    "duration_ms": 45000
  },
  "changes": {
    "files_changed": [
      "src/auth/jwt.py",
      "tests/auth/test_jwt.py"
    ],
    "lines_added": 120,
    "lines_deleted": 5,
    "diff_path": ".grace/packets/PKT-001/runs/RUN-001/evidence/diff.patch"
  },
  "tests": {
    "T0": {
      "status": "passed",
      "duration_ms": 1200,
      "result_path": ".grace/packets/PKT-001/runs/RUN-001/tests/T0-lint.json"
    },
    "T1": {
      "status": "passed",
      "duration_ms": 3400,
      "result_path": ".grace/packets/PKT-001/runs/RUN-001/tests/T1-tests.json"
    },
    "T2": {
      "status": "passed",
      "duration_ms": 8900,
      "result_path": ".grace/packets/PKT-001/runs/RUN-001/tests/T2-tests.json"
    }
  },
  "evidence": {
    "manifest_path": ".grace/packets/PKT-001/runs/RUN-001/evidence/manifest.json",
    "items": [
      {
        "type": "DIFF_SUMMARY",
        "path": ".grace/packets/PKT-001/runs/RUN-001/evidence/diff.patch"
      },
      {
        "type": "TEST_OUTPUT",
        "tier": "T0",
        "path": ".grace/packets/PKT-001/runs/RUN-001/tests/T0-lint.json"
      }
    ]
  },
  "acceptance": {
    "decision": "ACCEPT",
    "reason": "All required tests passed, no policy violations",
    "profile": "STRICT",
    "reviewer_required": true,
    "reviewer_status": "pending"
  },
  "started_at": "2026-05-31T10:05:00Z",
  "finished_at": "2026-05-31T10:05:45Z"
}
```

#### T0-lint.json
```json
{
  "tier": "T0",
  "name": "Mechanical checks",
  "status": "passed",
  "commands": [
    {
      "command": "ruff check .",
      "exit_code": 0,
      "stdout": "",
      "stderr": "",
      "duration_ms": 450
    },
    {
      "command": "ruff format --check .",
      "exit_code": 0,
      "stdout": "All files formatted correctly",
      "stderr": "",
      "duration_ms": 320
    },
    {
      "command": "mypy src",
      "exit_code": 0,
      "stdout": "Success: no issues found",
      "stderr": "",
      "duration_ms": 430
    }
  ],
  "summary": {
    "total_commands": 3,
    "passed": 3,
    "failed": 0,
    "duration_ms": 1200
  }
}
```

#### T1-tests.json
```json
{
  "tier": "T1",
  "name": "Touched scope tests",
  "status": "passed",
  "resolver": "touched_scope",
  "resolved_tests": [
    "tests/auth/test_jwt.py::test_generate_token",
    "tests/auth/test_jwt.py::test_validate_token",
    "tests/auth/test_jwt.py::test_expired_token"
  ],
  "command": "pytest tests/auth/test_jwt.py -v",
  "exit_code": 0,
  "results": {
    "total": 3,
    "passed": 3,
    "failed": 0,
    "skipped": 0,
    "duration_ms": 3400
  },
  "tests": [
    {
      "name": "test_generate_token",
      "status": "passed",
      "duration_ms": 1100
    },
    {
      "name": "test_validate_token",
      "status": "passed",
      "duration_ms": 1200
    },
    {
      "name": "test_expired_token",
      "status": "passed",
      "duration_ms": 1100
    }
  ]
}
```

#### agent/output.json
```json
{
  "agent_run_id": "ARUN-001",
  "role": "coder",
  "executor": "claude-sonnet-4-6",
  "status": "succeeded",
  "summary": "Implemented JWT token generation and validation",
  "changes": {
    "files_created": [
      "src/auth/jwt.py",
      "tests/auth/test_jwt.py"
    ],
    "files_modified": [
      "requirements.txt"
    ],
    "files_deleted": []
  },
  "implementation_notes": [
    "Used PyJWT library for token generation",
    "Added expiration time of 1 hour",
    "Implemented token validation with signature check"
  ],
  "risks": [],
  "open_questions": [],
  "tokens": {
    "input": 12000,
    "output": 8500,
    "total": 20500
  },
  "duration_ms": 45000
}
```

#### logs.jsonl (structured logs)
```jsonl
{"timestamp": "2026-05-31T10:05:00Z", "level": "info", "message": "Starting agent run", "agent_run_id": "ARUN-001"}
{"timestamp": "2026-05-31T10:05:05Z", "level": "info", "message": "Created worktree", "path": "/tmp/wt/PKT-001"}
{"timestamp": "2026-05-31T10:05:10Z", "level": "info", "message": "Agent started", "executor": "claude-sonnet-4-6"}
{"timestamp": "2026-05-31T10:05:45Z", "level": "info", "message": "Agent completed", "status": "succeeded"}
{"timestamp": "2026-05-31T10:05:46Z", "level": "info", "message": "Running tests", "tier": "T0"}
```

---

## 3. Debug Mode (optional MD files)

### 3.1 Configuration

```yaml
# project.yaml
debug:
  enabled: false              # true только для отладки
  save_prompts: true          # Сохранять промпты агентам
  save_responses: true        # Сохранять ответы агентов
  generate_summaries: true    # Генерировать MD summaries
  save_diffs_as_md: false     # Сохранять diff как MD (по умолчанию .patch)
```

### 3.2 Debug artifacts (только если debug.enabled)

```text
.grace/packets/{packet_id}/runs/{run_id}/debug/
├── summary.md              # Human-readable summary
├── agent_prompt.md         # Что отправили агенту
├── agent_response.md       # Что агент ответил
├── diff.md                 # Diff в MD формате (если enabled)
└── timeline.md             # Timeline событий
```

#### summary.md (пример)
```markdown
# Packet PKT-001: Add JWT utilities

**Status:** ACCEPTED  
**Profile:** STRICT  
**Duration:** 45s

## Changes
- Created `src/auth/jwt.py` (85 lines)
- Created `tests/auth/test_jwt.py` (35 lines)
- Modified `requirements.txt` (+1 line)

## Tests
- ✅ T0: Mechanical checks (1.2s)
- ✅ T1: Touched scope tests (3.4s)
- ✅ T2: Full unit tests (8.9s)

## Acceptance
**Decision:** ACCEPT  
**Reason:** All required tests passed, no policy violations
```

---

## 4. API Responses (structured data)

### 4.1 GET /api/packets/{packet_id}

```json
{
  "id": "PKT-001",
  "feature_id": "FEAT-001",
  "wave_id": "WAV-001",
  "title": "Add JWT utilities",
  "state": "ACCEPTED",
  "acceptance_profile": "STRICT",
  "spec": {
    "scope": ["src/auth/jwt.py", "tests/auth/test_jwt.py"],
    "complexity": "medium",
    "risk": "high"
  },
  "current_run": {
    "id": "RUN-001",
    "attempt": 1,
    "status": "succeeded",
    "result": {
      "changes": {
        "files_changed": ["src/auth/jwt.py", "tests/auth/test_jwt.py"],
        "lines_added": 120,
        "lines_deleted": 5
      },
      "tests": {
        "T0": {"status": "passed", "duration_ms": 1200},
        "T1": {"status": "passed", "duration_ms": 3400},
        "T2": {"status": "passed", "duration_ms": 8900}
      },
      "acceptance": {
        "decision": "ACCEPT",
        "reason": "All required tests passed"
      }
    },
    "artifacts": {
      "result": "/api/packets/PKT-001/runs/RUN-001/result.json",
      "agent_output": "/api/packets/PKT-001/runs/RUN-001/agent/output.json",
      "tests": {
        "T0": "/api/packets/PKT-001/runs/RUN-001/tests/T0-lint.json",
        "T1": "/api/packets/PKT-001/runs/RUN-001/tests/T1-tests.json"
      },
      "diff": "/api/packets/PKT-001/runs/RUN-001/evidence/diff.patch"
    }
  },
  "created_at": "2026-05-31T10:00:00Z",
  "updated_at": "2026-05-31T10:06:00Z"
}
```

### 4.2 GET /api/packets/{packet_id}/runs/{run_id}/result.json

Возвращает полный `result.json` (см. выше).

### 4.3 GET /api/packets/{packet_id}/runs/{run_id}/tests/T0-lint.json

Возвращает полный `T0-lint.json` (см. выше).

---

## 5. UI Rendering (парсит JSON)

### 5.1 Packet Detail Page

```typescript
function PacketDetailPage({ packetId }) {
  const { data: packet } = useQuery(['packet', packetId], () =>
    api.get(`/api/packets/${packetId}`).then(r => r.data)
  );
  
  return (
    <div>
      <Header>
        <h1>{packet.title}</h1>
        <Badge color={stateColor(packet.state)}>{packet.state}</Badge>
      </Header>
      
      <Section title="Changes">
        <FileList files={packet.current_run.result.changes.files_changed} />
        <Stats>
          <Stat label="Added" value={packet.current_run.result.changes.lines_added} color="green" />
          <Stat label="Deleted" value={packet.current_run.result.changes.lines_deleted} color="red" />
        </Stats>
      </Section>
      
      <Section title="Tests">
        {Object.entries(packet.current_run.result.tests).map(([tier, test]) => (
          <TestResult
            key={tier}
            tier={tier}
            status={test.status}
            duration={test.duration_ms}
            onClick={() => viewTestDetails(packetId, packet.current_run.id, tier)}
          />
        ))}
      </Section>
      
      <Section title="Acceptance">
        <AcceptanceDecision decision={packet.current_run.result.acceptance} />
      </Section>
    </div>
  );
}
```

### 5.2 Test Results Modal

```typescript
function TestResultsModal({ packetId, runId, tier }) {
  const { data: testResult } = useQuery(
    ['test', packetId, runId, tier],
    () => api.get(`/api/packets/${packetId}/runs/${runId}/tests/${tier}.json`).then(r => r.data)
  );
  
  return (
    <Modal>
      <h2>{testResult.name}</h2>
      <Badge>{testResult.status}</Badge>
      
      {testResult.commands?.map((cmd, i) => (
        <CommandResult key={i}>
          <Code>{cmd.command}</Code>
          <ExitCode code={cmd.exit_code} />
          <Duration ms={cmd.duration_ms} />
          {cmd.stdout && <Output type="stdout">{cmd.stdout}</Output>}
          {cmd.stderr && <Output type="stderr">{cmd.stderr}</Output>}
        </CommandResult>
      ))}
      
      {testResult.tests?.map((test, i) => (
        <TestCase key={i}>
          <TestName>{test.name}</TestName>
          <TestStatus status={test.status} />
          <TestDuration ms={test.duration_ms} />
        </TestCase>
      ))}
    </Modal>
  );
}
```

---

## 6. Agent Integration

### 6.1 Agents читают JSON

```python
# Agent читает packet spec
import httpx

response = httpx.get("http://localhost:8000/api/packets/PKT-001")
packet = response.json()

print(f"Working on: {packet['title']}")
print(f"Scope: {packet['spec']['scope']}")
print(f"Acceptance profile: {packet['acceptance_profile']}")
```

### 6.2 Agents пишут JSON

```python
# Agent записывает результат
result = {
    "status": "succeeded",
    "changes": {
        "files_changed": ["src/auth/jwt.py"],
        "lines_added": 85,
        "lines_deleted": 0
    },
    "summary": "Implemented JWT utilities",
    "tokens": {
        "input": 12000,
        "output": 8500
    }
}

# Сохраняем в файл
with open(".grace/packets/PKT-001/runs/RUN-001/agent/output.json", "w") as f:
    json.dump(result, f, indent=2)

# Или через API
httpx.post(
    f"http://localhost:8000/api/packets/PKT-001/runs/RUN-001/result",
    json=result
)
```

### 6.3 Agents парсят test results

```python
# Agent читает результаты тестов
with open(".grace/packets/PKT-001/runs/RUN-001/tests/T1-tests.json") as f:
    test_result = json.load(f)

if test_result["status"] == "passed":
    print(f"✓ All {test_result['results']['total']} tests passed")
else:
    failed = [t for t in test_result["tests"] if t["status"] == "failed"]
    print(f"✗ {len(failed)} tests failed:")
    for test in failed:
        print(f"  - {test['name']}")
```

---

## 7. Преимущества AI-first подхода

### 7.1 Machine-readable

✅ **Агенты парсят напрямую** — не нужно парсить MD
✅ **Structured queries** — можно фильтровать/агрегировать
✅ **Type safety** — JSON schema validation
✅ **API-friendly** — прямая сериализация

### 7.2 Human-friendly через UI

✅ **UI парсит JSON** — красивое отображение
✅ **Real-time updates** — WebSocket с JSON
✅ **Drill-down** — клик → загрузить детали
✅ **Search/filter** — по structured data

### 7.3 Debug-friendly

✅ **MD только когда нужно** — debug mode
✅ **Structured logs** — JSONL для анализа
✅ **Full audit trail** — все в events таблице
✅ **Reproducible** — все inputs/outputs сохранены

---

## 8. Migration from current code

### 8.1 Что меняем

**Было:**
```python
# Сохраняем MD
summary_md = generate_summary_md(result)
Path("summary.md").write_text(summary_md)
```

**Стало:**
```python
# Сохраняем JSON
result_json = {
    "status": result.status,
    "changes": result.changes,
    "tests": result.tests,
}
Path("result.json").write_text(json.dumps(result_json, indent=2))

# MD только если debug enabled
if config.debug.enabled:
    summary_md = generate_summary_md(result)
    Path("debug/summary.md").write_text(summary_md)
```

### 8.2 Existing evidence collection

Адаптируем существующий `evidence_manifest.py`:

```python
# Было: собираем пути к файлам
evidence_paths = collect_evidence_paths(packet_run)

# Стало: собираем structured evidence
evidence_items = []
for path in evidence_paths:
    if path.suffix == ".json":
        # Уже JSON — добавляем как есть
        evidence_items.append({
            "type": infer_type(path),
            "path": str(path),
            "format": "json"
        })
    elif path.suffix == ".md":
        # MD — только если debug enabled
        if config.debug.enabled:
            evidence_items.append({
                "type": "DEBUG_SUMMARY",
                "path": str(path),
                "format": "markdown"
            })

# Сохраняем manifest
manifest = {
    "packet_id": packet_id,
    "run_id": run_id,
    "items": evidence_items
}
Path("evidence/manifest.json").write_text(json.dumps(manifest, indent=2))
```

---

## 9. Configuration

### 9.1 project.yaml

```yaml
version: 2

project:
  key: my-project
  root: /path/to/project

runtime:
  database_url: sqlite:///grace.db
  artifacts_root: .grace/packets

# Debug mode (optional)
debug:
  enabled: false              # true только для отладки
  save_prompts: true
  save_responses: true
  generate_summaries: true
  save_diffs_as_md: false

# Artifact formats
artifacts:
  primary_format: json        # json | yaml
  include_markdown: false     # true только если debug.enabled
  structured_logs: true       # JSONL вместо plain text
```

---

## 10. Summary

**Основной формат:** JSON (machine-readable)
**Markdown:** Только для debug mode
**UI:** Парсит JSON и показывает красиво
**Агенты:** Читают/пишут JSON напрямую
**Audit trail:** Всё в DB + structured artifacts

**Результат:** AI-first система где люди смотрят через UI, а агенты работают с structured data.
