# ТЗ: Retention Policy — Branch Cleanup + Sizes в admin

**Статус:** pending implementation
**Приоритет:** P1 (operator pain: stale branches, no size visibility)
**Дата:** 2026-06-07
**Связанные TZ:** TZ_ADMIN_PANEL.md, TZ_SESSION_RESUME.md (отдельная история)

---

## Контекст

### Operator feedback (2026-06-07)

> "Слушай, а че у нас получается? Каждый раз ворк 3 вычищается, и у нас не будет сохранены ни логи, ни артефакты, ничего."

> "А то есть на самом деле сохранять неудачные попытки тоже бы хорошо, чтобы потом можно было анализировать, тогда, получается, будет огромное количество бранчей, да, в этом? Висеть это не очень хорошо."

> "Саш, у нас потом сессии опен саш, они, ну, как бы остаются. Вот это на самом деле тоже не совсем удобно."

> "Чтобы были человеко понимаемое описание размера его. Там байты не надо писать, что 0 0 3 гигабайта, вот. Ну, то есть, чтоб он красиво был оформлен."

> "Чтоб сам бранч просто бы удалился, а физически все файлы бы остались, чтоб потом можно было в админке просматривать артефакты всех Атемов и так далее."

### Найденные проблемы в коде

| # | Проблема | Где |
|---|----------|-----|
| 1 | **Branch'и `agent/<packet_id>-attempt-NNNN` накапливаются** в `target_repo_root` после merge. `MergeService.cleanup_worktree:128-160` удаляет worktree, но **не удаляет ветку** | `src/grace_control/services/merge_service.py:128` |
| 2 | **Worktree + branch заблокированных/rejected пакетов висят вечно** — `RecoveryController` не очищает ресурсы на переходе в BLOCKED_FINAL/REJECTED/FAILED | `src/grace_control/core/recovery_controller.py:37` |
| 3 | **OpenCode session (`.opencode/` в worktree) теряется при cleanup worktree** — но эта потеря ожидаема (нет TZ_SESSION_RESUME) | worktree root |
| 4 | **Нет scheduler'а** для periodic cleanup — TTL конфиг (`stale_state_days: 7`) есть, триггера нет | `src/grace_control/services/supervisor_cleanup_service.py:42-43` |
| 5 | **Нет visibility в admin** — сколько места занимает worktree/state/archive, сколько stale branches, сколько orphaned worktree dirs | admin TZ |

### Решение (high-level)

1. **Branch cleanup на state transitions** — при переходе пакета в `MERGED / REJECTED / FAILED / BLOCKED_*`:
   - удалять `git worktree` + директорию worktree
   - удалять `git branch agent/<packet_id>-attempt-*` (все attempt-ветки пакета одной командой)
   - **НЕ трогать** `.grace/state/packets/<packet_id>/runs/R0X/` (logs, json, command_preview — остаются вечно)

2. **Sizes везде в human-readable** (B/KB/MB/GB) — Jinja filter `fmt_size()`, применить к artifacts, runs, packets, waves, maintenance tab.

3. **Maintenance tab в admin** — disk usage, stale branches/worktrees list с кнопками Delete, кнопка "Cleanup now".

4. **`.gitignore` safety** — `.grace/` в `.gitignore` целевого репо.

---

## Не-цели (явно)

- ❌ **Tar.gz архивирование** — по решению оператора, диск не проблема сейчас
- ❌ **TTL на evidence** — оставляем всё в `.grace/state/`
- ❌ **Per-wave / per-feature branch** — per-packet правильно (industry standard: Cursor, Worktrunk, git-stint, Aider, Claude Code)
- ❌ **Auto scheduler** для periodic cleanup — пока ручной через admin UI
- ❌ **TZ_SESSION_RESUME** (централизованное хранение opencode session) — отдельная TZ, делаем позже
- ❌ **TTL на git objects** (через `git gc`) — оставляем default, unreachable commits живут ~30 дней

---

## Архитектурное решение: granularity ветки

Из исследования 7 индустриальных паттернов (Cursor 3.5, Worktrunk, git-stint, work, Shard, Aider, Claude Code):

| Паттерн | Per-packet | Per-wave | Per-feature |
|---------|------------|----------|-------------|
| Per-task worktree (рекомендован AWS Well-Architected: "keep feature branches short-lived") | ✅ | ❌ | ❌ |
| Trunk-based (AWS DevOps Guidance) | ❌ | ❌ | ❌ |
| GitFlow (legacy) | ❌ | ❌ | ✅ |

**Per-packet branch — правильный выбор для GRACE:**
1. Recovery в GRACE — per-packet (`RecoveryController` оперирует `packet_id`)
2. Merge в GRACE — per-packet (`MergeService.merge_packet`)
3. Per-wave: нельзя мержить частично, failed packet блокирует всю волну
4. Per-feature: ещё хуже, нет селективного merge

**Решение:** per-packet branch, агрессивный auto-cleanup всех attempt-веток пакета при достижении terminal state.

---

## Retention policy (target)

### Поведение по слоям

| Слой | Где | MERGED | REJECTED/FAILED | BLOCKED_* | Active (RUNNING) |
|------|-----|--------|-----------------|-----------|------------------|
| **1. Worktree** | `.grace/worktrees/<slug>/` | **Удалить** сразу | **Удалить** сразу | **Удалить** сразу | Держать |
| **2. Branch** | `target_repo_root`, `agent/<packet_id>-attempt-NNNN` | `git branch -D` всех attempt-веток пакета **сразу** | `git branch -D` всех attempt-веток пакета **сразу** | `git branch -D` всех attempt-веток пакета **сразу** | Держать |
| **3. Run artifacts** | `.grace/state/packets/<id>/runs/R0X/` | **НЕ трогать** (живут вечно) | **НЕ трогать** (живут вечно) | **НЕ трогать** (живут вечно) | **НЕ трогать** |
| **4. .opencode/ session** | внутри worktree | Теряется при cleanup worktree | Теряется | Теряется | Создаётся |

### Триггеры cleanup

| Триггер | Где вызывается | Что делает |
|---------|----------------|------------|
| **MERGED** (success) | `MergeService.cleanup_worktree:128` + `merge_packet:97` | worktree remove + `git branch -D agent/<packet_id>-attempt-*` |
| **REJECTED / FAILED** (verifier/reviewer) | `TerminalStateCleanup.run(packet_id, state)` в `_route_after:147` | worktree remove + `git branch -D agent/<packet_id>-attempt-*` |
| **BLOCKED_FINAL / BLOCKED_RECOVERABLE / BLOCKED** | `TerminalStateCleanup.run(packet_id, state)` в `_route_after:147` | worktree remove + `git branch -D agent/<packet_id>-attempt-*` |
| **Periodic** (каждые 6ч) | не реализуем сейчас (manual через admin) | — |
| **Manual** через admin UI | кнопка "Cleanup now" → `POST /api/admin/maintenance/cleanup` | sweep всех stale branches + worktree dirs |

### Что НЕ очищается автоматически

- `.grace/state/packets/<id>/runs/R0X/` — логи, json, command_preview, agent_*_log, acceptance_report.json
- DB rows (events, packet_runs, features, waves, packets)
- `.git/objects/` unreachable commits (живут до `git gc`, default ~30 дней)
- `.grace/archive/` (не используется, задел на будущее)

---

## Phase 1: Branch cleanup on state transitions

### 1.1 Новый сервис: `TerminalStateCleanup`

**Файл:** `src/grace_control/core/cleanup_on_state.py`

```python
class TerminalStateCleanup:
    """Очищает git worktree + branch refs при достижении пакетом terminal state.

    Не трогает .grace/state/ (run artifacts живут вечно для анализа).
    """

    def __init__(self, git: GitService, worktree_cleanup: WorktreeCleanupService,
                 project_root: Path, worktree_root: str = ".grace/worktrees"):
        ...

    def run(self, packet_id: str, attempt: int, state: str) -> CleanupResult:
        """Вызывается на переходе в terminal state.
        Returns: {branches_deleted: [..], worktree_removed: bool, errors: [..]}
        """
        slug = f"{packet_id}-attempt-{attempt:04d}"
        branch_pattern = f"agent/{packet_id}-attempt-*"

        # 1. Worktree cleanup
        wt_removed = self._worktree_cleanup.cleanup_attempt(
            self.project_root, slug, worktree_root=self.worktree_root
        )

        # 2. Branch cleanup (all attempt-branches for this packet)
        branches_deleted = self._delete_branches(branch_pattern)

        return CleanupResult(
            branches_deleted=branches_deleted,
            worktree_removed=wt_removed,
            errors=[],
        )

    def _delete_branches(self, pattern: str) -> list[str]:
        # git branch --list <pattern>
        # git branch -D <name> для каждого
        ...
```

**CleanupResult DTO:**
```python
@dataclass
class CleanupResult:
    branches_deleted: list[str]  # ["agent/pkt_xxx-attempt-0001", ...]
    worktree_removed: bool
    errors: list[str]
```

### 1.2 Интеграция в `MergeService`

**Файл:** `src/grace_control/services/merge_service.py:128-160`

В `MergeService.cleanup_worktree` после `shutil.rmtree` добавить:
```python
# Удалить ВСЕ attempt-ветки пакета (не только текущую)
branch_pattern = f"agent/{packet_id}-attempt-*"
self._delete_branches_in_target(branch_pattern)
```

В `MergeService.merge_packet` после `git.push("origin", target_branch)`:
```python
# После успешного merge — cleanup всех attempt-веток
self._delete_branches_in_target(f"agent/{packet_id}-attempt-*")
```

### 1.3 Интеграция в `PacketExecutor._route_after`

**Файл:** `src/grace_control/adapters/packet_executor.py:147`

В функции `_route_after` после `_rej` / `_err` / `_blocked`:
```python
if result.is_terminal_failure:
    cleanup_result = self._terminal_cleanup.run(
        packet_id=packet.id,
        attempt=attempt_count,
        state=result.new_state,
    )
    log.info("terminal_cleanup_executed", extra={
        "packet_id": packet.id,
        "state": result.new_state,
        "branches_deleted": len(cleanup_result.branches_deleted),
        "worktree_removed": cleanup_result.worktree_removed,
    })
```

**Terminal states:** `REJECTED, FAILED, BLOCKED, BLOCKED_RECOVERABLE, BLOCKED_FINAL, MERGED` (последний уже обработан в MergeService).

### 1.4 Тесты Phase 1

**Файл:** `tests/grace_control/core/test_cleanup_on_state.py`

- `test_terminal_state_rejected_deletes_worktree_and_branches`
- `test_terminal_state_failed_deletes_worktree_and_branches`
- `test_terminal_state_blocked_final_deletes_worktree_and_branches`
- `test_terminal_state_deletes_all_attempt_branches_for_packet` (packet с 3 attempts → 3 ветки → все удалены)
- `test_terminal_state_preserves_run_artifacts_in_state_dir` (`.grace/state/.../runs/R0X/` не тронут)
- `test_terminal_state_no_op_if_no_worktree` (cleanup idempotent)
- `test_terminal_state_no_op_if_no_branches`
- `test_terminal_state_collects_errors_but_continues` (если branch -D fail → лог + continue)

**Файл:** `tests/grace_control/services/test_merge_service.py` (обновить)

- `test_merge_deletes_all_attempt_branches_for_packet` (после merge → `git branch -D agent/<id>-attempt-*`)
- `test_merge_keeps_run_artifacts` (`.grace/state/.../runs/R0X/` не удалён)

**Файл:** `tests/ui/test_admin_ui_artifacts.py` (новый)

- `test_artifacts_tab_works_after_branch_removal` (admin Artifacts tab читает из state dir, branch cleanup не мешает)

---

## Phase 2: Sizes в admin (human-readable)

### 2.1 Jinja filter `fmt_size()`

**Файл:** `src/grace_control/ui/admin_template_filters.py`

```python
def fmt_size(num_bytes: int | None) -> str:
    """2.3 MB / 156 KB / 4 B / 1.5 GB. None/0 → '0 B'."""
    if num_bytes is None or num_bytes == 0:
        return "0 B"
    abs_bytes = abs(num_bytes)
    if abs_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    val = float(num_bytes)
    for unit in units:
        val /= 1024.0
        if abs(val) < 1024.0:
            return f"{val:.1f} {unit}"
    return f"{val:.1f} PB"
```

Зарегистрировать в `app.jinja_env.filters` как `fmt_size`.

### 2.2 Service: `SizeCalculator`

**Файл:** `src/grace_control/services/size_calculator.py`

```python
class SizeCalculator:
    def du(self, path: Path) -> int:
        """Total size in bytes (recursive). Returns 0 if path doesn't exist."""

    def packet_runs_size(self, packet_id: str) -> int:
        """Sum of all R0X/ sizes in .grace/state/packets/<packet_id>/runs/"""

    def worktree_size(self, slug: str) -> int:
        """.grace/worktrees/<slug>/ total size"""

    def all_worktrees_total(self) -> int:
        """.grace/worktrees/ total"""

    def all_state_total(self) -> int:
        """.grace/state/ total"""

    def list_runs_with_sizes(self, packet_id: str) -> list[RunSizeInfo]:
        """[{run_id, path, size_bytes, size_human}, ...]"""
```

### 2.3 Где показывать sizes

| UI место | Что | Источник |
|----------|-----|----------|
| **Artifacts tab** (Packet detail) | Per-file size в tree | `artifacts_summary.files[].size` (уже есть по TZ_ADMIN_PANEL §3.6) |
| **Attempts tab** (Packet detail) | Per-run total size (R0X dir) | `SizeCalculator.packet_runs_size` |
| **Packet detail header / meta block** | Total runs size | сумма R0X |
| **Wave details** (правая колонка) | Wave total size (sum of packets) | сумма |
| **Master tree** | "1 packet · 234 KB" | per-packet size |
| **Maintenance tab** | см. Phase 3 | `SizeCalculator` |

### 2.4 Тесты Phase 2

**Файл:** `tests/grace_control/services/test_size_calculator.py`

- `test_fmt_size_bytes` (0, 1, 999 → "B")
- `test_fmt_size_kb` (1024 → "1.0 KB", 2048 → "2.0 KB")
- `test_fmt_size_mb` (1048576 → "1.0 MB", 1572864 → "1.5 MB")
- `test_fmt_size_gb_tb` (1 GB, 1.5 TB)
- `test_fmt_size_none` (None → "0 B")
- `test_size_calculator_du` (recursive file size)
- `test_size_calculator_packet_runs_size`
- `test_size_calculator_missing_path` (returns 0)
- `test_size_calculator_all_worktrees_total`

**Файл:** `tests/ui/test_admin_ui_sizes.py`

- `test_packet_detail_shows_runs_size_in_human_readable`
- `test_artifacts_files_show_human_readable_size`
- `test_wave_details_shows_total_size`
- `test_mobile_390_sizes_visible`

---

## Phase 3: Maintenance tab в admin

### 3.1 Endpoint

**Файл:** `src/grace_control/api/routers/admin_ui.py` (расширить)

```
GET /admin/_partial/maintenance
  → HTML partial (self-wrapped: <div id="maintenance-pane" class="maintenance-pane">)
  → returns disk usage, stale branches list, stale worktrees list, archives placeholder

POST /admin/maintenance/cleanup
  → { "ok": true, "branches_deleted": [...], "worktrees_removed": [...] }
  → triggers SupervisorCleanupService + TerminalStateCleanup sweep for all terminal packets
```

### 3.2 Partial template

**Файл:** `src/grace_control/ui/templates/admin/_maintenance.html`

```html
<div id="maintenance-pane" class="maintenance-pane">

  <!-- Section 1: Disk usage -->
  <div class="maint-section">
    <h2>Disk usage</h2>
    <div class="maint-grid">
      <div class="maint-cell">
        <div class="maint-label">Worktrees (.grace/worktrees/)</div>
        <div class="maint-value">{{ fmt_size(worktrees_total) }}</div>
        <div class="maint-meta">{{ worktree_count }} dirs</div>
      </div>
      <div class="maint-cell">
        <div class="maint-label">Run artifacts (.grace/state/)</div>
        <div class="maint-value">{{ fmt_size(state_total) }}</div>
        <div class="maint-meta">{{ packet_count }} packets, {{ run_count }} runs</div>
      </div>
      <div class="maint-cell">
        <div class="maint-label">Target repo branches</div>
        <div class="maint-value">{{ branch_count }}</div>
        <div class="maint-meta">{{ agent_branch_count }} agent/* branches</div>
      </div>
    </div>
  </div>

  <!-- Section 2: Stale branches -->
  <div class="maint-section">
    <h2>Stale branches ({{ stale_branches|length }})</h2>
    <p class="maint-help">
      agent/* branches left in target_repo_root. Delete to keep git clean.
    </p>
    {% if stale_branches %}
    <table class="maint-table">
      <thead>
        <tr><th>Branch</th><th>Age</th><th>Last state</th><th>Action</th></tr>
      </thead>
      <tbody>
        {% for sb in stale_branches %}
        <tr>
          <td class="mono">{{ sb.name }}</td>
          <td>{{ sb.age_human }}</td>
          <td>{{ sb.last_state_label }}</td>
          <td>
            <button class="maint-btn-danger"
                    hx-post="/admin/maintenance/cleanup?branch={{ sb.name }}"
                    hx-target="#maintenance-pane"
                    hx-swap="outerHTML">
              Delete
            </button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">No stale branches</div>
    {% endif %}
  </div>

  <!-- Section 3: Stale worktrees -->
  <div class="maint-section">
    <h2>Stale worktrees ({{ stale_worktrees|length }})</h2>
    <p class="maint-help">
      Orphaned worktree directories. Delete to free disk.
    </p>
    {% if stale_worktrees %}
    <table class="maint-table">
      <thead>
        <tr><th>Path</th><th>Slug</th><th>Age</th><th>Size</th><th>Action</th></tr>
      </thead>
      <tbody>
        {% for sw in stale_worktrees %}
        <tr>
          <td class="mono">{{ sw.path }}</td>
          <td class="mono">{{ sw.slug }}</td>
          <td>{{ sw.age_human }}</td>
          <td>{{ fmt_size(sw.size_bytes) }}</td>
          <td>
            <button class="maint-btn-danger"
                    hx-post="/admin/maintenance/cleanup?worktree={{ sw.slug }}">
              Delete
            </button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">No stale worktrees</div>
    {% endif %}
  </div>

  <!-- Section 4: Archives placeholder -->
  <div class="maint-section">
    <h2>Archives</h2>
    <p class="maint-help">
      tar.gz archive of terminal packets (not enabled yet). All run artifacts remain in <code>.grace/state/</code>.
    </p>
    <div class="empty">No archive configured</div>
  </div>

  <!-- Section 5: Actions -->
  <div class="maint-section">
    <h2>Actions</h2>
    <div class="maint-actions">
      <button class="maint-btn-primary"
              hx-post="/admin/maintenance/cleanup?full=true"
              hx-target="#maintenance-pane"
              hx-swap="outerHTML"
              hx-confirm="Run full cleanup? Will delete all stale branches and worktrees.">
        Cleanup now
      </button>
      <a href="/admin" class="maint-btn-secondary">Back to dashboard</a>
    </div>
  </div>

</div>
```

### 3.3 Service: `MaintenanceService`

**Файл:** `src/grace_control/services/maintenance_service.py`

```python
class MaintenanceService:
    def snapshot(self) -> MaintenanceSnapshot:
        """Disk usage + stale branches + stale worktrees"""

    def cleanup_branch(self, branch: str) -> bool:
        """git branch -D <branch>"""

    def cleanup_worktree(self, slug: str) -> bool:
        """git worktree remove + rmtree"""

    def cleanup_all_stale(self) -> CleanupResult:
        """Full sweep: все terminal packets + все stale branches + worktrees"""
```

**Stale branch definition:** `agent/*` branch whose packet is in `MERGED / REJECTED / FAILED / BLOCKED_*` (т.е. terminal state).

**Stale worktree definition:** `*.grace/worktrees/<slug>/` dir whose associated packet is in terminal state.

### 3.4 Тесты Phase 3

**Файл:** `tests/grace_control/services/test_maintenance_service.py`

- `test_snapshot_disk_usage` (3 папки + branch count)
- `test_snapshot_lists_stale_branches` (с packet state)
- `test_snapshot_lists_stale_worktrees` (с age, size)
- `test_cleanup_branch_removes_from_git`
- `test_cleanup_worktree_removes_dir`
- `test_cleanup_all_stale_sweeps_everything`

**Файл:** `tests/ui/test_admin_ui_maintenance.py`

- `test_maintenance_tab_renders_disk_usage`
- `test_maintenance_tab_renders_stale_branches`
- `test_maintenance_tab_renders_stale_worktrees`
- `test_maintenance_cleanup_button_triggers_action`
- `test_maintenance_sizes_in_human_readable`
- `test_maintenance_empty_states`

### 3.5 CSS

**Файл:** `src/grace_control/ui/static/admin.css`

```css
.maintenance-pane { padding: 16px 20px; }
.maint-section { margin-bottom: 24px; }
.maint-section h2 { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.maint-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.maint-cell { padding: 12px; border: 1px solid var(--sev-muted); border-radius: 4px; background: rgba(255,255,255,0.02); }
.maint-label { font-size: 11px; color: var(--sev-muted); margin-bottom: 4px; }
.maint-value { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.maint-meta { font-size: 11px; color: var(--sev-muted); }
.maint-table { width: 100%; border-collapse: collapse; }
.maint-table th, .maint-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 12px; }
.maint-btn-danger { background: var(--sev-crit-bg); color: var(--sev-crit); border: 1px solid var(--sev-crit); padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; }
.maint-btn-primary { background: var(--sev-ok); color: #fff; border: 1px solid var(--sev-ok); padding: 6px 14px; border-radius: 3px; cursor: pointer; font-size: 12px; }
.maint-btn-secondary { background: transparent; color: var(--sev-muted); border: 1px solid var(--sev-muted); padding: 6px 14px; border-radius: 3px; text-decoration: none; font-size: 12px; }
.maint-help { color: var(--sev-muted); font-size: 12px; margin-bottom: 8px; }
```

### 3.6 Navigation: добавить таб/ссылку

В `console.html` или `_stats.html` добавить ссылку "Maintenance":
```html
<a href="/admin?view=maintenance" class="hdr-link">Maintenance</a>
```

Или в `shell_url()` Jinja global добавить `view=maintenance` параметр.

---

## Phase 4: `.gitignore` safety

**Файл:** целевой репозиторий — `.gitignore`

Добавить (если ещё нет):
```
# GRACE orchestrator runtime data
.grace/
.grace/worktrees/
.grace/state/
```

**Реализация:** в `GitService.worktree_add` (`src/grace_control/services/git_service.py:122-132`) — НЕ менять .gitignore (это user-managed). Лучше — **документировать** в README/TZ и оставить оператору. Если хочется автоматически — добавить в `app_factory.py` startup hook, который проверяет наличие `.gitignore` и добавляет строки (опционально, off by default).

**Решение:** только документируем, не делаем автоправку `.gitignore`.

---

## Файлы

### Новые
| Файл | Назначение |
|------|-----------|
| `docs/TZ_RETENTION_POLICY.md` | это ТЗ |
| `src/grace_control/core/cleanup_on_state.py` | `TerminalStateCleanup` service |
| `src/grace_control/services/size_calculator.py` | `SizeCalculator` + `MaintenanceSnapshot` |
| `src/grace_control/services/maintenance_service.py` | `MaintenanceService` |
| `src/grace_control/ui/templates/admin/_maintenance.html` | Maintenance tab partial |
| `tests/grace_control/core/test_cleanup_on_state.py` | unit tests |
| `tests/grace_control/services/test_size_calculator.py` | unit tests |
| `tests/grace_control/services/test_maintenance_service.py` | unit tests |
| `tests/ui/test_admin_ui_maintenance.py` | integration tests |
| `tests/ui/test_admin_ui_sizes.py` | integration tests |

### Изменяемые
| Файл | Что |
|------|-----|
| `src/grace_control/services/merge_service.py:128-160` | branch cleanup в `cleanup_worktree` + `merge_packet` |
| `src/grace_control/adapters/packet_executor.py:_route_after` | вызов `TerminalStateCleanup.run()` на REJECTED/FAILED/BLOCKED_* |
| `src/grace_control/ui/admin_template_filters.py` | `fmt_size()` Jinja filter |
| `src/grace_control/services/admin_aggregation_service.py` | добавить `size_bytes` в packet data (R0X total) |
| `src/grace_control/api/routers/admin_ui.py` | `GET /admin/_partial/maintenance`, `POST /admin/maintenance/cleanup` |
| `src/grace_control/ui/templates/admin/_timeline.html` | sizes в master tree + wave card meta |
| `src/grace_control/ui/templates/admin/_detail.html` | sizes в packet header + run list |
| `src/grace_control/ui/templates/admin/_tab.html` | sizes в artifacts tree |
| `src/grace_control/ui/templates/admin/console.html` | ссылка "Maintenance" |
| `src/grace_control/ui/static/admin.css` | maintenance tab styles + sizes utilities |
| `docs/TZ_ADMIN_PANEL.md` | ссылка на TZ_RETENTION_POLICY.md |

---

## Acceptance criteria

### Phase 1 (branch cleanup)
1. ✅ Пакет в REJECTED → `agent/<id>-attempt-*` удалены из git
2. ✅ Пакет в FAILED → `agent/<id>-attempt-*` удалены
3. ✅ Пакет в BLOCKED_FINAL → `agent/<id>-attempt-*` удалены
4. ✅ Пакет в MERGED → `agent/<id>-attempt-*` удалены (после merge)
5. ✅ `.grace/state/.../runs/R0X/` НЕ удалён ни в одном случае
6. ✅ Admin Artifacts tab работает для terminal-state пакетов (читает из state dir)
7. ✅ Worktree dir удалён на terminal state
8. ✅ Cleanup идемпотентен (повторный вызов → no-op без ошибок)

### Phase 2 (sizes)
9. ✅ `fmt_size()` корректно форматирует B/KB/MB/GB/TB
10. ✅ Per-file size в Artifacts tab в human-readable
11. ✅ Per-run size (R0X dir) в Attempts tab
12. ✅ Per-packet total в packet detail header
13. ✅ Per-wave total в wave details
14. ✅ Все sizes на мобильном (≤768px) видны

### Phase 3 (maintenance)
15. ✅ Maintenance tab рендерится с 4 секциями (disk, branches, worktrees, archives placeholder)
16. ✅ Disk usage показывает 3 папки + branch count
17. ✅ Stale branches list с кнопками "Delete" per branch
18. ✅ Stale worktrees list с кнопками "Delete" per worktree
19. ✅ Кнопка "Cleanup now" запускает полный sweep
20. ✅ Empty states (если stale = 0)
21. ✅ Sizes в human-readable

### Phase 4 (gitignore)
22. ✅ TZ документирует необходимость `.gitignore` для `.grace/`

### Tests
23. ✅ `pytest tests/grace_control/ tests/ui -q` → **без регрессий** (baseline: 25 pre-existing failed)

---

## Открытые вопросы (закрыто)

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Branch granularity (per-packet / per-wave / per-feature)? | **Per-packet** (industry standard, recovery/merge — per-packet) |
| 2 | Auto archive в tar.gz? | **Нет** (disk не проблема сейчас) |
| 3 | TTL на evidence? | **Нет** (хранить всё) |
| 4 | Scheduler для periodic cleanup? | **Нет** (manual через admin UI) |
| 5 | OpenCode session persistence? | **TZ_SESSION_RESUME** (отдельная TZ, делаем позже) |
| 6 | Per-attempt branches — удалять? | **Да, все сразу при terminal state** |
| 7 | Sizes в admin — где? | **Везде: artifacts, runs, packets, waves, maintenance** |
| 8 | `git gc` для unreachable commits? | **Default ~30 дней** (не трогаем) |

## Открытые вопросы (для будущего)

- TZ_SESSION_RESUME (централизованное хранение opencode session + cross-reference)
- APScheduler в supervisor (periodic auto-cleanup)
- Tar.gz archiving (если disk станет проблемой)
- Multi-host maintenance (cleanup на нескольких worker'ах одновременно)
