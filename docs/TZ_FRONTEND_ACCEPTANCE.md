# ТЗ: Frontend Acceptance — Browser E2E + Visual Regression для React/Telegram Mini App

**Статус:** pending (готов к реализации)
**Приоритет:** P0 — без этого React-пакеты принимаются только по линту
**Дата:** 2026-06-07

---

## Контекст

Orchestrator сейчас умеет:
- T0 scope+lint, T1 targeted, T2 full checks (shell-команды)
- Evidence kinds: `command`, `file`, `diff`, `log`
- Verifier = LLM, читает только текст

Для Astra (React Telegram Mini App SaaS) этого мало:
- React рендерится в headless без понимания, что DOM правильный
- Скриншоты не снимаются, визуальная регрессия не отслеживается
- Telegram WebApp SDK не мокается → `window.Telegram.WebApp is undefined` в тестах
- LLM-verifier не видит UI, не может оценить «выглядит правильно»

---

## Архитектурные решения

| # | Решение | Значение |
|---|---------|----------|
| 1 | Telegram mode | профильно: NORMAL→mock, STRICT→real (ngrok+initData) |
| 2 | Playwright тесты | уже есть в Astra, orchestrator только запускает |
| 3 | Visual diff lib | Playwright `toHaveScreenshot` |
| 4 | Stage placement | новые T2_BROWSER_E2E + T3_VISUAL_REGRESSION |
| 5 | Verifier | мультимодальный (читает скриншоты) |
| 6 | Baselines | `tests/e2e/**/*-snapshots/` в worktree |
| 7 | Dev-сервер | локально через `process_supervisor` |
| 8 | Viewport | mobile-only matrix: 360x780 (android) + 390x844 (iphone), параллельно |
| 9 | Routing | architect решает через `spec.frontend.*`, profile = hard constraints |
| 10 | Video recording | нет (для failed — только trace.zip) |
| 11 | Traces | да, `<run_dir>/traces/<packet_id>/<viewport>/trace.zip` |
| 12 | Diff threshold | global default 0.001 + per-packet override |
| 13 | Storybook | нет, только e2e |

---

## Routing model: architect решает, profile ограничивает

### Источник истины — `spec.frontend` в пакете

```json
"frontend": {
  "enabled": true,                        // ← архитект решает
  "dev_command": "npm run dev",
  "base_url": "http://localhost:3000",
  "viewports": ["android", "iphone"],     // ← опц., default = оба
  "telegram_mode": "mock",                // ← architect, downgrade при NORMAL+real
  "e2e":    {"required": true},           // ← опт-инит T2_BROWSER
  "visual": {"required": true, "max_diff_pct": 0.01}  // ← опт-инит T3_VISUAL
}
```

### Routing (orchestrator вычисляет через `resolve_browser_routing`)

| `frontend.enabled` | `profile` | Результат |
|--------------------|-----------|-----------|
| отсутствует / `false` | любой | T2_BROWSER + T3_VISUAL **skipped** |
| `true` | `FAST` | T2_BROWSER + T3_VISUAL **skipped** (hard constraint) |
| `true` | `NORMAL` | T2_BROWSER run (если `e2e.required`), T3_VISUAL run (если `visual.required`), `telegram_mode=mock` |
| `true` | `STRICT` | то же, но `telegram_mode=real` допустим (ngrok поднимается) |
| `true` | `NORMAL` + `telegram_mode=real` | downgrade → mock + warning в лог |

### Defaults (когда architect не указал)

| Поле | Default |
|------|---------|
| `frontend.enabled` | `false` (отсутствие = false) |
| `frontend.e2e.required` | `true` (если `frontend.enabled=true`) |
| `frontend.visual.required` | `false` (явный opt-in) |
| `frontend.telegram_mode` | `"mock"` |
| `frontend.viewports` | `["android", "iphone"]` |
| `frontend.visual.max_diff_pct` | `0.001` (из `agent_profiles.yaml`) |

### Что решает architect vs orchestrator

| Решение | Кто |
|---------|-----|
| Трогает ли пакет UI? (`frontend.enabled`) | **architect** |
| Поднимать ли playwright? (`e2e.required`) | **architect** |
| Делать ли visual regression? (`visual.required`) | **architect** |
| Mock или real Telegram? (`telegram_mode`) | **architect**, downgrade при NORMAL+real |
| FAST → skip browser (даже если architect хочет) | **orchestrator** (hard) |
| STRICT → real Telegram разрешён | **orchestrator** (валидация) |
| Viewports какие именно | **architect** (defaults: android+iphone) |
| `max_diff_pct` | **architect** (default 0.001 global) |

### Architect guidelines (что заполнять)

- Любой пакет с UI-изменениями → `frontend.enabled: true`
- Новый экран / изменение layout → `visual.required: true`
- Маленький bugfix без визуала → `e2e.required: true, visual.required: false`
- Экраны с динамикой (дашборд, лента) → `visual.max_diff_pct: 0.01-0.05`
- Бэкенд-only пакет → `frontend` отсутствует или `enabled: false`
- Финальная приёмка крупной фичи → `acceptance_profile: STRICT` + `telegram_mode: real`

---

## ПРОБЛЕМА 1: Нет browser-based acceptance

### Корневая причина
`acceptance_pipeline.py` имеет только T0/T1/T2 = shell-команды. Для frontend-пакета нужны:
- Поднять dev-сервер (vite/next) в worktree
- Запустить Playwright в headless
- Mobile-only matrix: android + iphone параллельно
- Проверить ARIA, клики, навигацию
- Снять скриншоты, сделать visual diff

### Задачи
| # | Что | Файл | P |
|---|-----|------|---|
| 1.1 | Расширить `StageName`: +`T2_BROWSER_E2E`, +`T3_VISUAL_REGRESSION` | `core/contracts.py:50-53` | P0 |
| 1.2 | `FrontendSpec` schema в `project_config.py`: `enabled, dev_command, base_url, viewports, telegram_mode, e2e.{required}, visual.{required, max_diff_pct}` | `config/project_config.py` | P0 |
| 1.3 | `PlaywrightRunner` service: lifecycle dev-сервера (start → wait_ready → run → stop), запуск `npx playwright test` с matrix projects, сбор артефактов в `<run_dir>/browser/<viewport>/` | `services/playwright_runner.py` (NEW) | P0 |
| 1.4 | `resolve_browser_routing(packet_spec, profile) -> BrowserRouting` функция: возвращает `(run_t2_browser, run_t3_visual, telegram_mode, viewports, max_diff_pct)` | `core/frontend_stages.py` (NEW) | P0 |
| 1.5 | `AcceptancePipeline.run()` — после T2 вызвать `_run_t2_browser()` и `_run_t3_visual()` через `frontend_stages` | `core/acceptance_pipeline.py:200-230` | P0 |
| 1.6 | Traces на failure: `<run_dir>/traces/<packet_id>/<viewport>/trace.zip` (через `playwright --trace=on`) | `services/playwright_runner.py` | P0 |
| 1.7 | Cleanup: dev-server killed, port released, traces собраны | `services/supervisor_cleanup_service.py` | P1 |
| 1.8 | Frontend-профили в `agent_profiles.yaml`: `frontend_e2e: npx playwright test --reporter=html,json`, `frontend_visual: npx playwright test --grep @visual`, `frontend_a11y: npx @axe-core/cli` | `config/agent_profiles.yaml:279` | P1 |

---

## ПРОБЛЕМА 2: Нет evidence для visual/UX

### Корневая причина
`EvidenceRequirement.kind` поддерживает только `command/file/diff/log`. LLM-verifier получает только текст, не видит UI.

### Новые kinds
| kind | Что хранит | Как проверяется |
|------|-----------|----------------|
| `screenshot` | PNG путь + viewport + page url | file exists, размер > 0 |
| `dom_snapshot` | AX-tree HTML/JSON | file exists, содержит required ARIA roles |
| `console_log` | путь к логу | substring в логе (e.g. "error" → fail) |
| `network_log` | HAR-файл | required URL was hit (e.g. /api/auth) |
| `visual_diff` | baseline path + current path + diff path | pixel diff ≤ `max_diff_pct` |

### Задачи
| # | Что | Файл | P |
|---|-----|------|---|
| 2.1 | Расширить `EvidenceRequirement.kind` literal: +5 значений | `core/contracts.py:120` | P0 |
| 2.2 | Расширить `_check_evidence_kind()`: обработчики для 5 новых kinds | `core/evidence.py:63-105` | P0 |
| 2.3 | `VisualBaselineManager`: `compare(baseline, current, max_diff_pct) -> (passed, diff_path, diff_pct)`. Использует Playwright snapshot metadata (`pixelmatch` под капотом) | `services/visual_baseline_manager.py` (NEW) | P1 |
| 2.4 | `MultimodalEvidencePack` dataclass: `screenshots: list[ScreenshotRef]`, `dom_snapshots, console_log_path, network_log_path, visual_diff_path` | `core/contracts.py` | P1 |
| 2.5 | `EvidenceVerifier` extended prompt: секция `## Visual Evidence` со ссылками на скриншоты + `<image>` теги если executor multimodal | `core/evidence_verifier.py:121-163` | P1 |
| 2.6 | `multimodal: true` flag в `agent_profiles.yaml` для verifier-профилей | `config/agent_profiles.yaml` | P1 |

---

## ПРОБЛЕМА 3: Нет Telegram WebApp интеграции

### Корневая причина
Telegram Mini App = React SPA + `window.Telegram.WebApp` SDK. Без SDK React сразу падает на `Cannot read properties of undefined`. Нужно мокать в headless (NORMAL) или подключать реальный Telegram (STRICT).

### Mock mode (NORMAL + STRICT-default)

`TelegramWebAppMock` инжектит `<script>` в `<head>` ПЕРЕД bundle:

```js
window.Telegram = { WebApp: {
  initData: "mock_init_data",
  initDataUnsafe: { user: { id: 123, first_name: "Test" } },
  version: "7.0", platform: "web", colorScheme: "light",
  themeParams: {
    bg_color: "#ffffff", text_color: "#000000",
    hint_color: "#707579", link_color: "#3390ec",
    button_color: "#3390ec", button_text_color: "#ffffff"
  },
  viewportHeight: 780, viewportStableHeight: 780, isExpanded: true,
  ready() {}, expand() {}, close() {},
  MainButton: { setText(){}, show(){}, hide(){}, onClick(){}, offClick(){}, enable(){}, disable(){} },
  BackButton: { show(){}, hide(){}, onClick(){}, offClick(){} },
  HapticFeedback: { impactOccurred(){}, notificationOccurred(){}, selectionChanged(){} },
  onEvent(){}, offEvent(){}, sendData(){}
}};
```

Записывает вызовы в `telegram_calls.log` для evidence (например, "MainButton.setText('Confirm') → submit button click → /api/orders POST").

### Real mode (STRICT + `telegram_mode=real`)

`TelegramBridgeService`:
1. `ngrok http 3000` → `https://abc123.ngrok-free.app`
2. Генерирует signed initData через bot token (HMAC-SHA256 на `TELEGRAM_BOT_TOKEN`)
3. Подменяет URL в playwright config
4. После прогона → `ngrok kill`

### Задачи
| # | Что | Файл | P |
|---|-----|------|---|
| 3.1 | `TelegramWebAppMock` service: генерация JS, инъекция через `page.addInitScript()`, запись вызовов | `services/telegram_webapp_mock.py` (NEW) | P0 |
| 3.2 | `MockInjector` в `PlaywrightRunner`: `context.add_init_script(mock_js)` перед `page.goto()` | `services/playwright_runner.py` | P0 |
| 3.3 | `TelegramBridgeService` (real mode): ngrok lifecycle, signed initData, URL rotation | `services/telegram_bridge_service.py` (NEW) | P1 |
| 3.4 | Предустановка: `npx playwright install chromium` через `process_supervisor` (отдельный setup-шаг, идемпотентный) | `services/process_supervisor.py` | P1 |
| 3.5 | Cleanup ngrok в `supervisor_cleanup_service` (если `telegram_mode == "real"`) | `services/supervisor_cleanup_service.py` | P1 |
| 3.6 | Mock-mode downgrade: `if profile==NORMAL and telegram_mode=="real" → log.warn + force mock` | `core/frontend_stages.py` | P0 |

---

## ПРОБЛЕМА 4: Verifier не видит UI

### Корневая причина
`run_evidence_verifier` собирает prompt из текстовых полей packet'а. Скриншоты не прокидываются.

### Решение
`EvidenceVerifier` (LLM) получает multimodal-контекст:
- Текст packet'а + acceptance report (как сейчас)
- Список скриншотов (paths) + краткое описание viewport/url
- `diff_path` если есть visual regression
- `console_log_path` если есть ошибки

Использует `<image>{path}</image>` тег (Anthropic native) или `image_url` (OpenAI). Если executor не multimodal — fallback на текстовое описание («screenshot сохранён, diff = 0.5%»).

### Задачи
| # | Что | Файл | P |
|---|-----|------|---|
| 4.1 | `ScreenshotRef`, `DomSnapshotRef` dataclasses в `core/contracts.py` | `core/contracts.py` | P1 |
| 4.2 | `run_evidence_verifier()` extended: формирует multimodal секцию, проверяет `executor.metadata.multimodal` | `core/evidence_verifier.py:121-163` | P1 |
| 4.3 | Detected multimodal → использует `image_url`/`<image>` tags; иначе → текстовая секция «Visual evidence: 2 screenshots saved at ..., diff_pct=0.5%» | `core/evidence_verifier.py` | P1 |
| 4.4 | `agent_profiles.yaml`: пометить `verifier-premium` (claude-sonnet-4-6) как `multimodal: true`; cheap agy — fallback | `config/agent_profiles.yaml` | P1 |

---

## Спецификация пакета (пример для Astra)

### NORMAL пакет (типичный frontend-фикс)
```json
{
  "id": "pkt_astra_login_v1",
  "title": "Login screen с Telegram WebApp auth",
  "spec": {
    "scope": ["src/screens/Login/", "src/components/TelegramAuth/"],
    "acceptance_profile": "NORMAL",
    "frontend": {
      "enabled": true,
      "dev_command": "npm run dev",
      "base_url": "http://localhost:3000",
      "viewports": ["android", "iphone"],
      "telegram_mode": "mock",
      "telegram_user": {"id": 12345, "first_name": "Test"},
      "e2e":    {"required": true},
      "visual": {"required": true, "max_diff_pct": 0.005},
      "expected_evidence": [
        {"id": "login_screen",        "kind": "screenshot",   "required": true, "pattern": "**/login-*.png"},
        {"id": "aria_main",           "kind": "dom_snapshot", "required": true, "pattern": "main[role=main]"},
        {"id": "no_console_errors",   "kind": "console_log",  "required": true, "pattern": "no_errors"},
        {"id": "auth_api_called",     "kind": "network_log",  "required": true, "pattern": "/api/auth"},
        {"id": "visual_no_regression","kind": "visual_diff",  "required": true, "pattern": "max_diff_pct=0.005"}
      ]
    },
    "verification": {
      "t1":         [["npm", "test", "--", "--reporter=json"]],
      "t2":         [["npm", "run", "build"]],
      "t2_browser": [["npx", "playwright", "test", "tests/e2e/login.spec.ts"]],
      "t3_visual":  [["npx", "playwright", "test", "tests/e2e/login.visual.spec.ts"]]
    }
  }
}
```

### STRICT пакет (финальная приёмка фичи)
```json
{
  "spec": {
    "acceptance_profile": "STRICT",
    "frontend": {
      "enabled": true,
      "telegram_mode": "real",
      "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN_STAGING",
      "e2e": {"required": true},
      "visual": {"required": true, "max_diff_pct": 0.001}
    }
  }
}
```

### Backend-only пакет (frontend не запускается)
```json
{
  "spec": {
    "acceptance_profile": "NORMAL",
    "scope": ["src/api/", "src/services/"]
    // frontend отсутствует → T2_BROWSER/T3_VISUAL skipped
  }
}
```

---

## AcceptanceProfile → Stage matrix (финальная)

| `frontend.enabled` | `profile` | T0 | T1 | T2 | T2_BROWSER | T3_VISUAL | Telegram |
|--------------------|-----------|----|----|----|-----------|-----------|----------|
| отсутствует/false | любой | ✓ | ✓ (если есть) | ✓ (если есть) | **skip** | **skip** | n/a |
| true | FAST | ✓ | skip | skip | **skip** | **skip** | n/a |
| true | NORMAL | ✓ | ✓ | ✓ (если есть) | **✓** (если `e2e.required`) | **✓** (если `visual.required`) | mock |
| true | STRICT | ✓ | ✓ | ✓ | **✓** | **✓** | real (если architect указал) |

---

## Затронутые файлы

### Новые
| Файл | Назначение |
|------|-----------|
| `src/grace_control/services/playwright_runner.py` | dev-server lifecycle, run playwright matrix, collect artifacts, traces |
| `src/grace_control/services/visual_baseline_manager.py` | pixel diff через Playwright snapshot metadata |
| `src/grace_control/services/telegram_webapp_mock.py` | mock window.Telegram.WebApp |
| `src/grace_control/services/telegram_bridge_service.py` | real Telegram через ngrok + signed initData |
| `src/grace_control/core/frontend_stages.py` | T2_BROWSER_E2E + T3_VISUAL_REGRESSION реализации, `resolve_browser_routing()` |
| `src/grace_control/core/multimodal_evidence.py` | `MultimodalEvidencePack` бандл для verifier |
| `tests/grace_control/test_playwright_runner.py` | lifecycle + matrix routing |
| `tests/grace_control/test_telegram_webapp_mock.py` | JS-инъекция, call recording |
| `tests/grace_control/test_visual_baseline_manager.py` | pixel diff edge cases |
| `tests/grace_control/test_frontend_stages.py` | `resolve_browser_routing` table-driven |
| `tests/grace_control/test_telegram_bridge_service.py` | ngrok lifecycle, signed initData |
| `docs/TZ_FRONTEND_ACCEPTANCE.md` | это ТЗ |

### Изменяемые
| Файл | Изменения |
|------|----------|
| `core/contracts.py` | +2 `StageName`, +5 `EvidenceRequirement.kind`, +`ScreenshotRef`/`DomSnapshotRef` |
| `core/evidence.py` | +5 обработчиков в `_check_evidence_kind` |
| `core/acceptance_pipeline.py` | routing через `resolve_browser_routing`, вызов frontend_stages |
| `core/evidence_verifier.py` | multimodal prompt, image refs, executor detection |
| `services/command_template_renderer.py` | +`{base_url}`, `{viewport}`, `{telegram_mode}`, `{max_diff_pct}` template vars |
| `services/process_supervisor.py` | +`playwright_install` action, dev-server lifecycle logging |
| `services/supervisor_cleanup_service.py` | kill leftover dev-server/ngrok, cleanup traces dir |
| `config/agent_profiles.yaml` | +`frontend_e2e/visual/a11y` profiles, +`multimodal: true` на verifier-premium |
| `config/project_config.py` | +`FrontendSpec` schema с вложенным `VisualSpec` и `TelegramSpec` |
| `grace/project.yaml` | пример для Astra с `frontend.enabled: true` |
| `docs/SUPERVISOR.md` | секция «Frontend execution» |
| `docs/grace/EXECUTION_BACKENDS.md` | секция «Browser e2e + visual regression» |
| `docs/grace/CONFIGURATION.md` | FrontendSpec schema reference |

---

## Порядок выполнения

### P0 (блокирующие)
```
1.1 → StageName.T2_BROWSER_E2E + T3_VISUAL_REGRESSION
1.2 → FrontendSpec schema
1.3 → PlaywrightRunner service
1.4 → resolve_browser_routing()
1.5 → AcceptancePipeline routing через frontend_stages
1.6 → Traces на failure
3.1 → TelegramWebAppMock
3.2 → MockInjector в PlaywrightRunner
3.6 → Mock-mode downgrade для NORMAL+real
2.1 → EvidenceRequirement.kind expansion
2.2 → _check_evidence_kind для 5 новых kinds
```

### P1 (качество)
```
2.3 → VisualBaselineManager
2.4 → MultimodalEvidencePack
2.5 → EvidenceVerifier extended prompt
2.6 → multimodal: true в agent_profiles
4.1 → ScreenshotRef/DomSnapshotRef dataclasses
4.2 → run_evidence_verifier multimodal
4.3 → Multimodal executor detection
4.4 → agent_profiles multimodal: true
1.7 → Cleanup dev-server
1.8 → Frontend profiles в agent_profiles.yaml
3.3 → TelegramBridgeService
3.4 → npx playwright install через process_supervisor
3.5 → Cleanup ngrok
```

### P2 (расширения)
```
- a11y axe-core в T2_BROWSER
- Десктоп viewport как опция
- Visual diff threshold tuning UI
- Storybook (отложено)
- Video recording (отложено)
```

---

## Критерии приёмки

1. ✅ Пакет без `frontend` → T2_BROWSER/T3_VISUAL skipped
2. ✅ FAST профиль → T2_BROWSER/T3_VISUAL skipped даже при `frontend.enabled=true`
3. ✅ NORMAL + `telegram_mode=real` → downgrade в mock + warning
4. ✅ `pkt_astra_login` с NORMAL+mock → T2_BROWSER_E2E запускается, mobile matrix (android+iphone) параллельно
5. ✅ `EvidenceRequirement(kind=screenshot, ...)` — файл существует, размер > 0
6. ✅ Playwright `toHaveScreenshot` — diff ≤ `max_diff_pct`, иначе `StageStatus.FAILED`
7. ✅ Trace.zip на failure: `<run_dir>/traces/<packet_id>/<viewport>/trace.zip`
8. ✅ TelegramWebAppMock: `window.Telegram.WebApp.MainButton.setText('OK')` в `telegram_calls.log`
9. ✅ STRICT + `telegram_mode=real`: dev-server в worktree поднимается через `process_supervisor`, ngrok туннель работает
10. ✅ Verifier LLM получает скриншоты в prompt (если executor multimodal), иначе fallback
11. ✅ Cleanup: после packet — dev-server killed, ngrok killed, traces собраны
12. ✅ Pre-existing tests: 445 passed, без регрессий
13. ✅ Документация обновлена: SUPERVISOR.md, EXECUTION_BACKENDS.md, CONFIGURATION.md

---

## Открытые вопросы (закрыто)

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Video recording для failed packets? | **Нет** |
| 2 | Traces storage location? | **Да**, `<run_dir>/traces/<packet_id>/<viewport>/trace.zip` |
| 3 | Parallel viewport matrix? | **Mobile-only**: android + iphone |
| 4 | Visual diff threshold? | **Global default 0.001 + per-packet override** |
| 5 | Storybook? | **Нет**, только e2e |
