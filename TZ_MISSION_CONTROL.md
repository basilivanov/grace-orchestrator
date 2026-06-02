# GRACE Mission Control Center

## 1. Цель
Сделать понятную и удобную админку для `grace-orchestrator`, которая показывает, что происходит с feature, waves, packets, runs и artifacts.

Название: GRACE Mission Control Center.

Главная задача — пользователь должен быстро понять: что сейчас выполняется, где проблемы, какие packets готовы/упали/ждут/merged, где artifacts, почему packet был принят/отклонён/завис, какие задачи относятся к self-improvement.

## 2. Стек
FastAPI, HTML/templates, CSS, vanilla JavaScript, текущий backend/control plane, Playwright для браузерных тестов. НЕ подключаем React/Vue/Svelte/build-tools.

## 3. Главный принцип UX
Overview first → Detail on click → Deep debug only when needed. На главном экране только общее состояние и проблемные места.

## 4. Информационная модель
Feature → Wave → Packet → Run/Attempt → Artifacts/Evidence/Events. Отдельный тип: Self-improvement Feature.

## 5. Desktop layout
Спокойный 2-колоночный: левая = features list, правая = selected feature с waves/packets.

## 6. Верхняя панель
GRACE Mission Control Center, Live/Offline, Running, Ready, Needs attention, Merged, Workers summary, Last update. Без длинных ids, raw timestamps, полного списка workers/events.

## 7. Status Summary
Компактные карточки: Running, Ready, Needs attention, Merged, Workers. Needs attention = failed + rejected + stale worker + stuck running + missing artifacts.

## 8. Левая колонка: Features
Список features с title, packets count, compact status, progress bar, warning badge, Self-improvement badge.

## 9. Правая зона: Selected Feature
Выбранная feature с waves/packets. Packet строки: short title, state, attempt count, last reason, artifact indicator, self-improvement badge. Компактные, не большие плитки.

## 10. Packet Detail
Открывается по клику. Tabs: Overview, Runs, Artifacts, Events, Spec.

## 11. Overview tab
Goal, current state, next action, last run result, failure/rejection reason, acceptance profile, worker, started/finished time, artifact count.

## 12. Timeline
Lifecycle: Ready → Claimed → Running → Evidence → Accepted → Merged. Rejected/retry: Ready → Running → Rejected → Retry Ready. Failed: Ready → Running → Failed.

## 13. Runs tab
Все attempts: run id, status, worker/executor, started_at, finished_at, duration, result summary, artifact count, кнопка Open artifacts.

## 14. Artifacts tab
Группировка: Logs (stdout.log, stderr.log), Evidence (evidence.json), Diff (diff.patch), Images (screenshot.png). Preview: text/log tail, JSON pretty, image thumbnail, patch/diff monospace.

## 15. Events tab
Timestamp, event type, human-readable message, collapsed payload, trace_id. Фильтры: lifecycle, worker, errors, merge, notifications.

## 16. Spec tab
Readable spec_json: title, scope, acceptance criteria, expected changes, non-goals, risk/complexity. Raw JSON collapsed.

## 17. Self-improvement
Self-improvement = задачи где GRACE меняет сам себя: UI, runner, orchestrator, prompts, acceptance gates, test system. Отдельная feature/mode, отдельный badge, safety banner, affected subsystem, risk level, required gates, rollback note. Gates checklist: JS syntax check, Backend tests, API contract tests, Playwright smoke, Reviewer approval.

## 18. Mobile layout
Drill-down: Features → Waves/Packets → Packet Detail → Artifacts/Logs. 390px без horizontal scroll, крупные строки, sticky top bar, back button, breadcrumb, bottom tabs в packet detail.

## 19. API changes
Добавить GET /api/dashboard/v2 с полями system, stats, features. Расширить GET /api/packets/{packet_id} с полями packet, feature, wave, runs, events, artifacts, next_action, self_improvement. Исправить artifact endpoints для run_id в формате R01 без двойного префикса.

## 20. Frontend structure
Vanilla JS. Если один файл — структурирован по секциям. Если несколько: dashboard.js, api.js, state.js, render_features.js, render_packets.js, render_packet_detail.js, render_artifacts.js, mobile_nav.js, dashboard.css.

## 21. Auto-refresh
WebSocket обновляет dashboard state, polling fallback, refresh не сбрасывает selected feature/packet/tab. При offline показывать Offline, retrying.

## 22. Empty/error states
no features, no packets, no runs, no artifacts, API error, WebSocket offline, worker stale, run not found, artifact file missing. Human-readable, не raw exception.

## 23. Visual style
Calm, sparse, readable, operational. Меньше цветов, больше воздуха, не более 4 summary cards, компактные packet rows, ids мелким monospace только в detail, logs monospace, raw JSON collapsed. Не dense cockpit.

## 24-32. Тестовая стратегия
JS syntax check (node --check на всех JS файлах), HTML template smoke tests, API contract tests (dashboard/v2, packet detail, artifacts), Artifact regression tests (run_id=R01 и packet_id-R01 форматы), Playwright tests (dashboard opens, overview renders, packet detail opens, artifacts visible, refresh preserves selection, mobile viewports 390x844 + 430x932 + 768x1024 + 1440x900, self-improvement visible), Console error gate (fail on pageerror/console.error), Demo data fixtures (normal feature, self-improvement feature, waves, packets with all states, artifacts: stdout.log, stderr.log, evidence.json, diff.patch, screenshot.png), CI acceptance gate (backend + JS syntax + API contract + artifact regression + Playwright smoke + Playwright mobile + Self-improvement UI).

## 33. Приоритет
Первым делом: runs + artifacts + events + tests. Главный сценарий: пользователь видит проблему → кликает packet → видит причину → открывает runs/artifacts → понимает что произошло.
