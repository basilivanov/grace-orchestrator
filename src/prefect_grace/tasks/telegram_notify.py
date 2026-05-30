from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from typing import Any

from prefect_grace.runtime_config import load_runtime_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_FEATURE_NOTIFY_STATUSES = {
    "in_progress",
    "accepted",
    "awaiting_commit",
    "blocked",
    "pipeline_invalid",
    "verification_blocked",
    "environment_blocked",
    "product_blocked",
}
DEFAULT_PACKET_NOTIFY_STATUSES = {
    "escalate_to_architect",
}
DEFAULT_WAVE_NOTIFY_VERDICTS = {
    "accepted",
    "rework_required",
    "blocked",
}


def _env_file_value(key: str) -> str | None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _parse_int(raw: object) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value or None


def _parse_int_list(raw: object) -> list[int]:
    if raw in (None, ""):
        return []
    values: list[int] = []
    for item in str(raw).split(","):
        parsed = _parse_int(item)
        if parsed is not None:
            values.append(parsed)
    return values


def _parse_csv_set(raw: object) -> set[str]:
    if raw in (None, ""):
        return set()
    values: set[str] = set()
    for item in str(raw).split(","):
        normalized = item.strip().lower()
        if normalized:
            values.add(normalized)
    return values


def _status_filter(name: str, default: set[str]) -> set[str] | None:
    env_value = os.environ.get(name)
    file_value = _env_file_value(name)
    configured = _parse_csv_set(env_value or file_value)
    if not configured:
        return set(default)
    if "all" in configured:
        return None
    if "none" in configured:
        return set()
    return configured


def _feature_status_allowed(status: str) -> bool:
    allowed = _status_filter("GRACE_NOTIFY_FEATURE_STATUSES", DEFAULT_FEATURE_NOTIFY_STATUSES)
    return allowed is None or status in allowed


def _packet_status_allowed(status: str) -> bool:
    allowed = _status_filter("GRACE_NOTIFY_PACKET_STATUSES", DEFAULT_PACKET_NOTIFY_STATUSES)
    return allowed is None or status in allowed


def _wave_verdict_allowed(verdict: str) -> bool:
    allowed = _status_filter("GRACE_NOTIFY_WAVE_VERDICTS", DEFAULT_WAVE_NOTIFY_VERDICTS)
    return allowed is None or verdict in allowed


def _telegram_bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or _env_file_value("TELEGRAM_BOT_TOKEN")


def _notify_urls() -> list[str]:
    values = [
        os.environ.get("GRACE_NOTIFY_URL"),
        os.environ.get("SUPERVISOR_NOTIFY_URL"),
    ]
    bot_internal_url = os.environ.get("BOT_INTERNAL_URL") or _env_file_value("BOT_INTERNAL_URL")
    if bot_internal_url:
        values.append(f"{str(bot_internal_url).rstrip('/')}/notify")
    values.append("http://127.0.0.1:8001/notify")

    urls: list[str] = []
    for value in values:
        candidate = str(value).strip() if value else ""
        if candidate and candidate not in urls:
            urls.append(candidate)
    return urls


def _notify_url() -> str | None:
    urls = _notify_urls()
    return urls[0] if urls else None


def _notify_chat_id() -> int | None:
    direct = (
        os.environ.get("GRACE_NOTIFY_CHAT_ID")
        or os.environ.get("SUPERVISOR_NOTIFY_CHAT_ID")
        or os.environ.get("DUCTOR_CHAT_ID")
    )
    if direct:
        return _parse_int(direct)

    file_direct = (
        _env_file_value("GRACE_NOTIFY_CHAT_ID")
        or _env_file_value("SUPERVISOR_NOTIFY_CHAT_ID")
        or _env_file_value("DUCTOR_CHAT_ID")
    )
    if file_direct:
        return _parse_int(file_direct)

    admin_ids = os.environ.get("BOT_ADMIN_IDS") or _env_file_value("BOT_ADMIN_IDS")
    parsed_ids = _parse_int_list(admin_ids)
    if parsed_ids:
        return parsed_ids[-1]
    return None


def _flow_run_url(flow_run_id: str | None) -> str | None:
    if not flow_run_id:
        return None
    runtime = load_runtime_config()
    if not runtime.public_ui_url:
        return None
    return f"{runtime.public_ui_url.rstrip('/')}/runs/flow-run/{flow_run_id}"


def _packet_run_url(task_run_id: str | None) -> str | None:
    if not task_run_id:
        return None
    runtime = load_runtime_config()
    if not runtime.public_ui_url:
        return None
    return f"{runtime.public_ui_url.rstrip('/')}/runs/task-run/{task_run_id}"


def _post_json(url: str, payload: dict[str, Any]) -> bool:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = getattr(response, "status", 200)
            return 200 <= int(status) < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def _send_via_internal_notify(*, chat_id: int, text: str) -> bool:
    payload = {
        "telegram_id": chat_id,
        "text": text,
    }
    for notify_url in _notify_urls():
        if _post_json(notify_url, payload):
            return True
    return False


def _send_via_telegram_api(*, chat_id: int, text: str) -> bool:
    bot_token = _telegram_bot_token()
    if not bot_token:
        return False
    return _post_json(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


def _send_html_message(text: str) -> bool:
    chat_id = _notify_chat_id()
    if not chat_id:
        return False
    if _send_via_internal_notify(chat_id=chat_id, text=text):
        return True
    return _send_via_telegram_api(chat_id=chat_id, text=text)


def _lines_to_html(lines: list[str]) -> str:
    return "\n".join(lines)


def _short_reason(reason: str) -> str:
    text = " ".join(str(reason or "").strip().split())
    if len(text) <= 120:
        return text
    return text[:117].rstrip() + "..."


def _looks_like_service_english(text: str | None) -> bool:
    value = " ".join(str(text or "").strip().split())
    if not value:
        return False
    lowered = value.lower()
    service_markers = (
        "feature",
        "wave",
        "packet",
        "planner",
        "architect",
        "reviewer",
        "verifier",
        "skip w00",
        "optional",
        "slice",
        "complete",
        "blocked",
        "rework",
    )
    if "awaiting_commit" in lowered:
        return False
    ascii_letters = sum(1 for ch in value if "a" <= ch.lower() <= "z")
    cyrillic_letters = sum(1 for ch in value if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    return ascii_letters > cyrillic_letters and any(marker in lowered for marker in service_markers)


def _user_title_line(title: str | None, status: str) -> str | None:
    cleaned_title = " ".join(str(title or "").strip().split())
    if cleaned_title and not _looks_like_service_english(cleaned_title):
        return cleaned_title
    return {
        "accepted": "Короткий итог по фиче готов.",
        "completed": "Короткий итог по фиче готов.",
        "awaiting_commit": "Фича принята, но ещё ждёт коммита.",
        "in_progress": "Фича остаётся в работе.",
        "architect_ready": "Нужно решение архитектора по фиче.",
        "blocked": "Фича не может быть завершена без разбора блокера.",
        "pipeline_invalid": "Пайплайн требует исправления перед продолжением.",
        "verification_blocked": "Проверка остановила выпуск фичи.",
        "environment_blocked": "Среда не позволяет завершить фичу.",
        "product_blocked": "Нужно продуктовое решение по фиче.",
    }.get(status, "Обновление по фиче.")


def _action_hint_label(next_action: str | None) -> str | None:
    value = str(next_action or "").strip()
    if not value:
        return None
    normalized = value.lower()
    if normalized == "commit-feature-changes":
        return "Дальше: закоммитить изменения."
    if normalized == "feature-complete":
        return "Фича завершена."
    if normalized == "inspect-domain-blocker":
        return "Проверьте доменный блокер."
    if normalized == "architect-decision-required":
        return "Нужно решение архитектора."
    if normalized in {"fix-planner-contract", "fix-packet-graph-contract"}:
        return "Исправьте контракт графа пакетов."
    if normalized.startswith("architect-wave-rework-required:"):
        wave_id = value.split(":", 1)[1]
        return f"Нужна доработка волны {wave_id}."
    if normalized.startswith("architect-wave-blocked:"):
        wave_id = value.split(":", 1)[1]
        return f"Волна {wave_id} заблокирована."
    if normalized.startswith("inspect-review-blockers:"):
        packet_id = value.split(":", 1)[1]
        return f"Проверьте блокеры ревью для {packet_id}."
    if normalized.startswith("inspect-failed-"):
        return "Проверьте упавший этап пайплайна."
    if normalized.startswith("missing-"):
        return "Не хватает обязательного этапа пайплайна."
    if normalized.startswith("dependency-deadlock:"):
        return "Обнаружена взаимная блокировка зависимостей."
    if normalized.startswith("run-rework-packet"):
        return "Запустите пакет доработки."
    if normalized.startswith("architect-user-decision-required"):
        return "Нужно решение архитектора или пользователя."
    if normalized.startswith("architect-planner-decomposition-required"):
        return "Нужна пересборка плана и декомпозиции."
    return "Следующий шаг зафиксирован в пайплайне."



def _reason_summary_ru(reason: str) -> str:
    text = " ".join(str(reason or "").strip().split())
    lowered = text.lower()
    if not text:
        return "Причина зафиксирована в артефактах."
    if "latest reviewer/verifier evidence" in lowered or "resolves the earlier frontend visual blocker" in lowered:
        return "Свежие ревью и проверка закрыли предыдущий блокер по визуальному подтверждению."
    if "canonical week continuity" in lowered or "fail-closed" in lowered or "packet-local observability" in lowered:
        return "Поведение Week, fail-closed состояние и локальная observability подтверждены."
    if "fresh visual artifacts" in lowered and "show" in lowered:
        return "Свежие визуальные артефакты собраны и указывают на оставшийся блокер."
    if "frontend visual" in lowered or "visual proof" in lowered:
        return "Нужно визуальное подтверждение фронтенда."
    if "observability" in lowered and "no-evidence" in lowered:
        return "Не хватает свежих observability evidence."
    if "rework" in lowered and "accepted" in lowered:
        return "Доработка принята."
    if _looks_like_service_english(text):
        return "Подробная причина сохранена в артефактах."
    return _short_reason(text)


def _reason_summaries_ru(reasons: list[str] | None, *, limit: int = 3) -> list[str]:
    summaries: list[str] = []
    for reason in reasons or []:
        summary = _reason_summary_ru(reason)
        if summary and summary not in summaries:
            summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries

def _feature_status_label(status: str) -> str:
    return {
        "in_progress": "в работе",
        "awaiting_commit": "принято, ждёт коммита",
        "accepted": "принято",
        "completed": "принято",
        "blocked": "заблокировано",
        "pipeline_invalid": "пайплайн некорректен",
        "verification_blocked": "проверка заблокировала выпуск",
        "environment_blocked": "среда заблокировала выпуск",
        "product_blocked": "требуется продуктовое решение",
        "architect_ready": "нужно решение архитектора",
    }.get(status, status or "обновление")


def _packet_status_label(status: str) -> str:
    return {
        "accepted": "принят",
        "review": "на ревью",
        "rework_required": "нужна доработка",
        "blocked": "заблокирован",
        "escalate_to_architect": "эскалация архитектору",
        "running": "в работе",
    }.get(status, status or "обновление")


def _wave_verdict_label(verdict: str) -> str:
    return {
        "accepted": "волна принята",
        "rework_required": "волна требует доработки",
        "blocked": "волна заблокирована",
    }.get(verdict, verdict or "обновление волны")


def _wave_progress_label(status: str | None, required: bool | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return None
    suffix = "обязательная" if bool(required) else "optional"
    return {
        "pending": f"Статус в sequence: pending ({suffix}).",
        "running": f"Статус в sequence: running ({suffix}).",
        "accepted": f"Статус в sequence: accepted ({suffix}).",
        "blocked": f"Статус в sequence: blocked ({suffix}).",
    }.get(normalized, f"Статус в sequence: {normalized} ({suffix}).")


def _feature_summary_text(status: str, summary: str | None, blockers: list[str] | None, next_action: str | None) -> str | None:
    normalized = str(status).strip().lower()
    cleaned_summary = " ".join(str(summary or "").strip().split())
    if _looks_like_service_english(cleaned_summary):
        cleaned_summary = ""
    reason = _short_reason((blockers or [""])[0]) if blockers else ""
    if normalized == "awaiting_commit":
        return "Итог: принято, ждёт коммита."
    if normalized == "accepted":
        return cleaned_summary or "Итог: принято и закоммичено."
    if normalized in {"blocked", "pipeline_invalid", "verification_blocked", "environment_blocked", "product_blocked"}:
        if reason:
            return f"Итог: { _feature_status_label(normalized) }. {reason}"
        if next_action:
            action_hint = _action_hint_label(next_action)
            if action_hint:
                return f"Итог: { _feature_status_label(normalized) }. {action_hint}"
            return f"Итог: { _feature_status_label(normalized) }."
        return f"Итог: { _feature_status_label(normalized) }."
    if normalized == "architect_ready":
        if reason:
            return f"Итог: нужно решение архитектора. {reason}"
        return "Итог: требуется решение архитектора."
    if normalized == "in_progress":
        if reason:
            return f"Итог: нужна доработка. {reason}"
        if next_action and "rework" in next_action:
            action_hint = _action_hint_label(next_action)
            if action_hint:
                return f"Итог: нужна доработка. {action_hint}"
            return "Итог: нужна доработка."
        return cleaned_summary or "Фича в работе."
    return cleaned_summary or None


def notify_feature_event(
    *,
    feature_id: str,
    title: str | None,
    status: str,
    summary: str | None = None,
    wave_id: str | None = None,
    flow_run_id: str | None = None,
    blockers: list[str] | None = None,
    next_action: str | None = None,
) -> bool:
    normalized_status = str(status).strip().lower()
    if not _feature_status_allowed(normalized_status):
        return False
    icon = {
        "in_progress": "🚀",
        "awaiting_commit": "📝",
        "accepted": "🏁",
        "completed": "🏁",
        "blocked": "⛔",
        "pipeline_invalid": "🧯",
        "verification_blocked": "🔬",
        "environment_blocked": "🛠",
        "product_blocked": "📌",
        "architect_ready": "🧠",
    }.get(normalized_status, "📣")
    short_summary = _feature_summary_text(normalized_status, summary, blockers, next_action)
    title_line = _user_title_line(title, normalized_status)
    lines = [
        f"{icon} <b>Фича: {escape(_feature_status_label(normalized_status))}</b>",
        f"<b>{escape(feature_id)}</b>",
    ]
    if title_line:
        lines.append(escape(title_line))
    if wave_id:
        lines.append(f"Волна: <b>{escape(wave_id)}</b>")
    if short_summary:
        lines.append(escape(short_summary))
    if next_action:
        action_hint = _action_hint_label(next_action)
        if action_hint:
            lines.append(escape(action_hint))
    if blockers:
        for blocker in _reason_summaries_ru(blockers, limit=3):
            lines.append(f"• {escape(blocker)}")
    url = _flow_run_url(flow_run_id)
    if url:
        lines.append(f"<a href=\"{escape(url)}\">Открыть запуск в Prefect</a>")
    return _send_html_message(_lines_to_html(lines))


def notify_packet_event(
    *,
    feature_id: str,
    packet_id: str,
    role: str,
    status: str,
    wave_id: str | None = None,
    title: str | None = None,
    reasons: list[str] | None = None,
    task_run_id: str | None = None,
    flow_run_id: str | None = None,
) -> bool:
    normalized_status = str(status).strip().lower()
    if not _packet_status_allowed(normalized_status):
        return False
    icon = {
        "accepted": "✅",
        "review": "🧪",
        "rework_required": "🔁",
        "blocked": "⛔",
        "escalate_to_architect": "🧠",
        "running": "🏃",
    }.get(normalized_status, "📦")
    lines = [
        f"{icon} <b>Пакет: {escape(_packet_status_label(normalized_status))}</b>",
        f"Фича: <b>{escape(feature_id)}</b>",
        f"Волна: <b>{escape(wave_id or '-')}</b>",
        f"Роль: <b>{escape(role)}</b>",
        f"Пакет: <code>{escape(packet_id)}</code>",
    ]
    if title:
        lines.append(f"Задача: {escape(title)}")
    if reasons:
        for reason in _reason_summaries_ru(reasons, limit=3):
            lines.append(f"• {escape(reason)}")
    task_url = _packet_run_url(task_run_id)
    if task_url:
        lines.append(f"<a href=\"{escape(task_url)}\">Открыть запуск задачи</a>")
    flow_url = _flow_run_url(flow_run_id)
    if flow_url:
        lines.append(f"<a href=\"{escape(flow_url)}\">Открыть запуск фичи</a>")
    return _send_html_message(_lines_to_html(lines))


def notify_wave_event(
    *,
    feature_id: str,
    wave_id: str,
    verdict: str,
    reasons: list[str] | None = None,
    progression_status: str | None = None,
    required: bool | None = None,
    flow_run_id: str | None = None,
) -> bool:
    normalized_verdict = str(verdict).strip().lower()
    if not _wave_verdict_allowed(normalized_verdict):
        return False
    icon = {
        "accepted": "🌊",
        "rework_required": "🔁",
        "blocked": "⛔",
    }.get(normalized_verdict, "🌊")
    lines = [
        f"{icon} <b>{escape(_wave_verdict_label(normalized_verdict))}</b>",
        f"Фича: <b>{escape(feature_id)}</b>",
        f"Волна: <b>{escape(wave_id)}</b>",
    ]
    progress_label = _wave_progress_label(progression_status, required)
    if progress_label:
        lines.append(escape(progress_label))
    if reasons:
        for reason in _reason_summaries_ru(reasons, limit=3):
            lines.append(f"• {escape(reason)}")
    url = _flow_run_url(flow_run_id)
    if url:
        lines.append(f"<a href=\"{escape(url)}\">Открыть запуск в Prefect</a>")
    return _send_html_message(_lines_to_html(lines))


def notify_submission_event(
    *,
    feature_id: str,
    title: str,
    execute: bool,
    brief_path: str | None = None,
    flow_run_id: str | None = None,
) -> bool:
    mode = "боевой" if execute else "черновой"
    icon = "🧾" if execute else "⚠️"
    lines = [
        f"{icon} <b>Фича поставлена в очередь</b>",
        f"<b>{escape(feature_id)}</b> — {escape(title)}",
        f"Режим: <b>{escape(mode)}</b>",
    ]
    if not execute:
        lines.append("Агенты Codex не стартуют, пока не включён <code>execute: true</code>.")
    if brief_path:
        lines.append(f"Бриф: <code>{escape(brief_path)}</code>")
    url = _flow_run_url(flow_run_id)
    if url:
        lines.append(f"<a href=\"{escape(url)}\">Открыть запуск в Prefect</a>")
    return _send_html_message(_lines_to_html(lines))


def notify_agent_work_event(
    *,
    status: str,
    title: str,
    summary: str | None = None,
    packet_id: str | None = None,
    next_action: str | None = None,
    link: str | None = None,
) -> bool:
    normalized_status = str(status or "info").strip().lower()
    label = {
        "started": "стартовал",
        "done": "закончил работу",
        "blocked": "остановился с блокером",
        "failed": "завершился с ошибкой",
        "info": "обновление",
    }.get(normalized_status, normalized_status or "обновление")
    icon = {
        "started": "▶️",
        "done": "✅",
        "blocked": "⛔",
        "failed": "❌",
        "info": "ℹ️",
    }.get(normalized_status, "ℹ️")

    lines = [
        f"{icon} <b>GRACE agent: {escape(label)}</b>",
        f"Задача: {escape(_short_reason(title or 'без названия'))}",
    ]
    if packet_id:
        lines.append(f"Пакет: <code>{escape(packet_id)}</code>")
    if summary:
        for line in str(summary).splitlines()[:6]:
            compact = _short_reason(line)
            if compact:
                lines.append(escape(compact))
    if next_action:
        lines.append(f"Дальше: {escape(_short_reason(next_action))}")
    if link:
        lines.append(f"<a href=\"{escape(link)}\">Открыть ссылку</a>")
    return _send_html_message(_lines_to_html(lines))
