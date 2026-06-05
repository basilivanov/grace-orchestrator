from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

try:
    from prefect.artifacts import create_markdown_artifact
except ModuleNotFoundError:  # pragma: no cover - local fallback mode
    create_markdown_artifact = None


def _bullet(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and str(item).strip()]
    return "\n".join(f"- {item}" for item in cleaned) if cleaned else "- none"


def _artifact_key(*parts: object) -> str:
    raw = "-".join(str(part) for part in parts if part not in (None, ""))
    key = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return re.sub(r"-+", "-", key) or "grace-artifact"


def _artifact_description(title: str, **fields: object) -> str:
    details = [f"{name}={value}" for name, value in fields.items() if value not in (None, "", [], {})]
    if not details:
        return title
    return f"{title} ({', '.join(details)})"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_none_\n"
    header_row = "| " + " | ".join(headers) + " |"
    divider_row = "| " + " | ".join("---" for _ in headers) + " |"
    body_rows = ["| " + " | ".join(cell.replace("\n", "<br>") for cell in row) + " |" for row in rows]
    return "\n".join([header_row, divider_row, *body_rows]) + "\n"


def _packet_run_lines(packet_results: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for name, payload in packet_results.items():
        if not isinstance(payload, dict):
            continue
        returncode = payload.get("returncode", "-")
        runner = payload.get("launcher") or payload.get("runner") or "n/a"
        last_message = payload.get("last_message_path") or "-"
        lines.append(f"{name}: rc={returncode}, runner={runner}, last_message={last_message}")
    return lines


def _business_context_lines(context: dict[str, Any]) -> list[str]:
    if not context:
        return ["none"]
    lines: list[str] = []
    brief_path = context.get("brief_path")
    if brief_path:
        lines.append(f"brief_path: {brief_path}")
    for key in ["scope", "acceptance_criteria", "non_goals", "visual_expectations", "open_decisions"]:
        values = list(context.get(key) or [])
        if values:
            lines.append(f"{key}: {'; '.join(str(value) for value in values)}")
    return lines or ["none"]


def _wave_progression_lines(wave_progression: list[dict[str, Any]]) -> list[str]:
    if not wave_progression:
        return ["none"]
    lines: list[str] = []
    for wave in wave_progression:
        wave_id = str(wave.get("wave_id") or "-")
        status = str(wave.get("status") or "pending")
        required = "required" if bool(wave.get("required", True)) else "optional"
        title = str(wave.get("title") or "")
        gate = str(wave.get("architect_gate_packet_id") or "-")
        if title:
            lines.append(f"{wave_id}: {status} ({required}) — {title}; architect_gate={gate}")
        else:
            lines.append(f"{wave_id}: {status} ({required}); architect_gate={gate}")
    return lines


def _path_status(path: str | None) -> str:
    if not path:
        return "-"
    file_path = Path(path)
    if not file_path.exists():
        return f"{path} (missing)"
    if file_path.is_file():
        return f"{path} ({file_path.stat().st_size} bytes)"
    return f"{path} (dir)"


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


def _action_hint_ru(next_action: str | None) -> str:
    value = str(next_action or "").strip()
    if not value:
        return "-"
    if value.lower() == "commit-feature-changes":
        return "Дальше: закоммитить изменения."
    normalized = value.lower()
    if normalized == "feature-complete":
        return "Фича завершена."
    if normalized == "inspect-domain-blocker":
        return "Проверьте доменный блокер."
    if normalized == "architect-decision-required":
        return "Нужно решение архитектора."
    if normalized in {"fix-planner-contract", "fix-packet-graph-contract"}:
        return "Исправьте контракт графа пакетов."
    if normalized.startswith("architect-wave-rework-required:"):
        return f"Нужна доработка {value.split(':', 1)[1]}."
    if normalized.startswith("architect-wave-blocked:"):
        return f"Волна {value.split(':', 1)[1]} заблокирована."
    if normalized.startswith("inspect-review-blockers:"):
        return f"Проверьте блокеры ревью для {value.split(':', 1)[1]}."
    if normalized.startswith("inspect-failed-"):
        return "Проверьте упавший этап пайплайна."
    if normalized.startswith("missing-"):
        return "Не хватает обязательного этапа пайплайна."
    if normalized.startswith("architect-user-decision-required"):
        return "Нужно решение архитектора или пользователя."
    if normalized.startswith("architect-planner-decomposition-required"):
        return "Нужна пересборка плана и декомпозиции."
    return "Следующий шаг зафиксирован в пайплайне."


def _user_facing_title(title: str | None, status: str | None) -> str:
    cleaned_title = " ".join(str(title or "").strip().split())
    if cleaned_title and not _looks_like_service_english(cleaned_title):
        return cleaned_title
    status_value = str(status or "").strip().lower()
    return {
        "accepted": "Пользовательский итог по фиче",
        "awaiting_commit": "Принято, ждёт коммита",
        "in_progress": "Пользовательский статус фичи",
        "architect_ready": "Требуется решение архитектора",
        "blocked": "Фича заблокирована",
        "pipeline_invalid": "Пайплайн требует исправления",
        "verification_blocked": "Проверка заблокировала выпуск",
        "environment_blocked": "Среда заблокировала выпуск",
        "product_blocked": "Требуется продуктовое решение",
    }.get(status_value, "Пользовательский статус фичи")


def _role_for_agent_run(name: str, payload: dict[str, Any], role_by_packet_id: dict[str, str]) -> str:
    packet_id = str(payload.get("packet_id") or "")
    if packet_id in role_by_packet_id:
        return role_by_packet_id[packet_id]
    if name in {"architect", "planner"}:
        return name
    if name.startswith("verifier-run:"):
        return "verifier"
    if name.startswith("run:"):
        packet_id_from_key = name.removeprefix("run:")
        return role_by_packet_id.get(packet_id_from_key, "-")
    return "-"


def _agent_output_summary(last_message_path: str | None) -> str:
    if not last_message_path:
        return "-"
    path = Path(last_message_path)
    if not path.exists():
        return "-"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return "-"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) > 160:
        return f"{first_line[:157]}..."
    return first_line or "-"


def _agent_output_rows(packet_results: dict[str, Any]) -> list[list[str]]:
    role_by_packet_id: dict[str, str] = {}
    for packet in list(dict(packet_results.get("planner_materialized") or {}).get("packets") or []):
        if isinstance(packet, dict) and packet.get("packet_id"):
            role_by_packet_id[str(packet["packet_id"])] = str(packet.get("role") or "-")

    rows: list[list[str]] = []
    for name, payload in packet_results.items():
        if not isinstance(payload, dict):
            continue
        if "returncode" not in payload or not (payload.get("stdout_path") or payload.get("last_message_path")):
            continue
        packet_id = str(payload.get("packet_id") or name)
        rows.append(
            [
                packet_id,
                _role_for_agent_run(name, payload, role_by_packet_id),
                str(payload.get("returncode", "-")),
                str(payload.get("launcher") or payload.get("runner") or "-"),
                _path_status(payload.get("last_message_path")),
                _path_status(payload.get("stdout_path")),
                _path_status(payload.get("stderr_path")),
                _agent_output_summary(payload.get("last_message_path")),
            ]
        )
    return rows


def _feature_summary_markdown(
    *,
    feature: dict[str, Any],
    verification: dict[str, Any] | None,
    review_route: dict[str, Any] | None,
    wave_route: dict[str, Any] | None,
    final_status: dict[str, Any] | None,
    packet_results: dict[str, Any],
) -> str:
    final_feature = dict((final_status or {}).get("feature") or feature)
    review = dict((review_route or {}).get("review") or {})
    wave_review = dict((wave_route or {}).get("wave_review") or {})
    feature_id = final_feature.get("feature_id") or feature.get("feature_id")
    final_outcome = str((final_status or {}).get("final_outcome") or "n/a")
    user_facing_status = str((final_status or {}).get("user_facing_status") or final_feature.get("status") or feature.get("status") or "n/a")
    user_summary = str((final_status or {}).get("user_summary") or final_feature.get("summary") or feature.get("summary") or "n/a")
    if _looks_like_service_english(user_summary):
        user_summary = "Итог по фиче зафиксирован в русской пользовательской формулировке."
    title_line = _user_facing_title(final_feature.get('title') or feature.get('title'), user_facing_status)
    candidate_commit_files = list((final_status or {}).get("candidate_commit_files") or final_feature.get("candidate_commit_files") or [])
    commit_status = str((final_status or {}).get("commit_status") or final_feature.get("commit_status") or "-")
    commit_hash = str((final_status or {}).get("commit_hash") or final_feature.get("commit_hash") or "-")
    wave_progression = list((final_status or {}).get("wave_progression") or final_feature.get("wave_progression") or packet_results.get("wave_progression") or [])
    lines = [
        f"# GRACE Feature Snapshot: {feature_id}",
        "",
        f"- updated_at: {datetime.now(timezone.utc).isoformat()}",
        f"- feature_id: {feature_id}",
        f"- title: {final_feature.get('title') or feature.get('title')}",
        f"- user_facing_title: {title_line}",
        f"- status: {final_feature.get('status') or feature.get('status')}",
        f"- final_outcome: {final_outcome}",
        f"- user_facing_status: {user_facing_status}",
        f"- next_action: {(final_status or {}).get('next_action', 'n/a')}",
        f"- next_action_label_ru: {_action_hint_ru((final_status or {}).get('next_action'))}",
        f"- commit_status: {commit_status}",
        f"- commit_hash: {commit_hash}",
        f"- next_wave_id: {(final_status or {}).get('next_wave_id') or final_feature.get('next_wave_id') or '-'}",
        f"- all_required_waves_accepted: {(final_status or {}).get('all_required_waves_accepted', final_feature.get('all_required_waves_accepted', '-'))}",
        f"- failure_category: {(final_status or {}).get('failure_category', 'n/a')}",
        f"- feature_dir: {final_feature.get('feature_dir', '-')}",
        f"- wave_plan_path: {final_feature.get('wave_plan_path', '-')}",
        f"- brief_path: {(final_feature.get('business_context') or {}).get('brief_path', '-')}",
        f"- architect_slice_dir: {final_feature.get('architect_slice_dir', '-')}",
        f"- architect_manifest_path: {final_feature.get('architect_manifest_path', '-')}",
        f"- execution_packet_path: {final_feature.get('execution_packet_path', '-')}",
        f"- architect_materialization_mode: {final_feature.get('architect_materialization_mode', '-')}",
        "",
        "## User Facing Outcome",
        _bullet([user_summary]),
        "",
        "## Business Context",
        _bullet(_business_context_lines(final_feature.get('business_context') or {})),
        "",
        "## Wave Progression",
        _bullet(_wave_progression_lines(wave_progression)),
        "",
        "## Blocker Reasons",
        _bullet(list((final_status or {}).get("reasons") or final_feature.get("blocker_reasons") or ["none"])),
        "",
        "## Packet Runs",
        _bullet(_packet_run_lines(packet_results)),
        "",
        "## Candidate Commit Files",
        _bullet(candidate_commit_files or ["none"]),
    ]
    if verification:
        lines.extend(
            [
                "",
                "## Verification",
                _bullet(
                    [
                        f"packet_id: {verification.get('packet_id', '-')}",
                        f"test_verdict: {verification.get('test_verdict', '-')}",
                        f"observability_verdict: {verification.get('observability_verdict', '-')}",
                        f"frontend_visual_verdict: {verification.get('frontend_visual_verdict', '-')}",
                        f"verification_path: {verification.get('verification_path', '-')}",
                    ]
                ),
            ]
        )
    if review:
        lines.extend(
            [
                "",
                "## Reviewer Gate",
                _bullet(
                    [
                        f"verdict: {review.get('verdict', '-')}",
                        f"follow_up_action: {review.get('follow_up_action', '-')}",
                        f"review_path: {review.get('review_path', '-')}",
                    ]
                ),
            ]
        )
    if wave_review:
        lines.extend(
            [
                "",
                "## Architect Wave Gate",
                _bullet(
                    [
                        f"verdict: {wave_review.get('verdict', '-')}",
                        f"review_path: {wave_review.get('review_path', '-')}",
                    ]
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def _verification_markdown(verification: dict[str, Any]) -> str:
    packet_id = verification.get("packet_id", "-")
    wave_id = verification.get("wave_id") or (str(packet_id).split("-")[3] if str(packet_id).count("-") >= 3 else "-")
    return "\n".join(
        [
            f"# Verifier Snapshot: {packet_id}",
            "",
            f"- feature_id: {verification.get('feature_id', '-')}",
            f"- packet_id: {packet_id}",
            f"- wave_id: {wave_id}",
            f"- grace_feature_ref: {verification.get('grace_feature_ref', '-')}",
            f"- grace_wave_ref: {verification.get('grace_wave_ref', '-')}",
            f"- grace_packet_ref: {verification.get('grace_packet_ref', '-')}",
            f"- test_verdict: {verification.get('test_verdict', '-')}",
            f"- observability_verdict: {verification.get('observability_verdict', '-')}",
            f"- frontend_visual_verdict: {verification.get('frontend_visual_verdict', '-')}",
            "",
            "## Commands Run",
            _bullet(list(verification.get("commands_run") or [])),
            "",
            "## Evidence Paths",
            _bullet(list(verification.get("evidence_paths") or [])),
            "",
            "## Blocking Issues",
            _bullet(list(verification.get("blocking_issues") or [])),
            "",
            f"- verification_path: {verification.get('verification_path', '-')}",
        ]
    ) + "\n"


def _review_markdown(review_route: dict[str, Any]) -> str:
    review = dict(review_route.get("review") or {})
    rework = dict(review_route.get("rework") or {})
    decision = dict(review_route.get("decision") or {})
    packet_id = review.get("packet_id", "-")
    wave_id = review.get("wave_id") or (str(packet_id).split("-")[3] if str(packet_id).count("-") >= 3 else "-")
    return "\n".join(
        [
            f"# Reviewer Snapshot: {packet_id}",
            "",
            f"- feature_id: {review.get('feature_id', '-')}",
            f"- packet_id: {packet_id}",
            f"- wave_id: {wave_id}",
            f"- grace_feature_ref: {review.get('grace_feature_ref', '-')}",
            f"- grace_wave_ref: {review.get('grace_wave_ref', '-')}",
            f"- grace_packet_ref: {review.get('grace_packet_ref', '-')}",
            f"- verdict: {review.get('verdict', '-')}",
            f"- follow_up_action: {review.get('follow_up_action', '-')}",
            f"- review_path: {review.get('review_path', '-')}",
            "",
            "## Reasons",
            _bullet(list(review.get("reasons") or [])),
            "",
            "## Follow-up Objects",
            _bullet(
                [
                    f"rework_packet: {rework.get('packet_id', '-')}" if rework else "",
                    f"architect_decision: {decision.get('decision_id', '-')}" if decision else "",
                ]
            ),
        ]
    ) + "\n"


def _packet_review_markdown(review_route: dict[str, Any]) -> str:
    review = dict(review_route.get("review") or {})
    rework = dict(review_route.get("rework") or {})
    decision = dict(review_route.get("decision") or {})
    packet_id = str(review.get("packet_id") or "-")
    return "\n".join(
        [
            f"# Артефакты ревью пакета: {packet_id}",
            "",
            f"- Фича: {review.get('feature_id', '-')}",
            f"- Волна: {review.get('wave_id', '-')}",
            f"- Вердикт: {review.get('verdict', '-')}",
            f"- Следующее действие: {_action_hint_ru(review.get('follow_up_action'))}",
            f"- Review file: {review.get('review_path', '-')}",
            "",
            "## Причины",
            _bullet(list(review.get("reasons") or [])),
            "",
            "## Следующие объекты",
            _bullet(
                [
                    f"rework_packet: {rework.get('packet_id', '-')}" if rework else "",
                    f"architect_decision: {decision.get('decision_id', '-')}" if decision else "",
                ]
            ),
        ]
    ) + "\n"


def _wave_markdown(wave_route: dict[str, Any]) -> str:
    review = dict(wave_route.get("wave_review") or {})
    progression = dict(wave_route.get("wave_progress") or {})
    return "\n".join(
        [
            f"# Architect Wave Snapshot: {review.get('architect_packet_id', '-')}",
            "",
            f"- feature_id: {review.get('feature_id', '-')}",
            f"- wave_id: {review.get('wave_id', '-')}",
            f"- verdict: {review.get('verdict', '-')}",
            f"- progression_status: {progression.get('status', '-')}",
            f"- required: {progression.get('required', '-')}",
            f"- review_path: {review.get('review_path', '-')}",
            "",
            "## Reasons",
            _bullet(list(review.get("reasons") or [])),
        ]
    ) + "\n"


def _packet_verification_markdown(verification: dict[str, Any]) -> str:
    packet_id = str(verification.get("packet_id") or "-")
    return "\n".join(
        [
            f"# Артефакты проверки пакета: {packet_id}",
            "",
            f"- test_verdict: {verification.get('test_verdict', '-')}",
            f"- observability_verdict: {verification.get('observability_verdict', '-')}",
            f"- frontend_visual_verdict: {verification.get('frontend_visual_verdict', '-')}",
            f"- verification_path: {verification.get('verification_path', '-')}",
            "",
            "## Команды",
            _bullet(list(verification.get("commands_run") or [])),
            "",
            "## Артефакты / evidence paths",
            _bullet(list(verification.get("evidence_paths") or [])),
            "",
            "## Блокеры",
            _bullet(list(verification.get("blocking_issues") or [])),
        ]
    ) + "\n"


def publish_packet_task_artifacts(
    *,
    verification: dict[str, Any] | None = None,
    review_route: dict[str, Any] | None = None,
) -> list[str]:
    if create_markdown_artifact is None:
        return []
    artifact_ids: list[str] = []
    if verification:
        packet_id = str(verification.get("packet_id") or "unknown-packet")
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-task-verification", packet_id),
                    description=_artifact_description(
                        "Packet task verification artifact",
                        packet_id=packet_id,
                        test=verification.get("test_verdict"),
                        obs=verification.get("observability_verdict"),
                    ),
                    markdown=_packet_verification_markdown(verification),
                )
            )
        )
    if review_route and review_route.get("review"):
        review = dict(review_route.get("review") or {})
        packet_id = str(review.get("packet_id") or "unknown-packet")
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-task-review", packet_id),
                    description=_artifact_description(
                        "Packet task review artifact",
                        packet_id=packet_id,
                        verdict=review.get("verdict"),
                    ),
                    markdown=_packet_review_markdown(review_route),
                )
            )
        )
    return artifact_ids


def _architect_markdown(*, feature: dict[str, Any], packet_results: dict[str, Any]) -> str:
    architect_plan = dict(packet_results.get("architect_artifact_plan") or {})
    architect_written = dict(packet_results.get("architect_artifacts") or {})
    manifest = dict(architect_written.get("manifest") or {})
    waves = list(manifest.get("waves") or [])
    root_deltas = dict(manifest.get("root_deltas") or {})

    return "\n".join(
        [
            f"# Architect Snapshot: {feature.get('feature_id', '-')}",
            "",
            f"- source: {architect_plan.get('source', '-')}",
            f"- parser_error: {architect_plan.get('parser_error', '-')}",
            f"- slice_id: {architect_written.get('slice_id', manifest.get('slice_id', '-'))}",
            f"- slice_slug: {architect_written.get('slice_slug', manifest.get('slice_slug', '-'))}",
            f"- slice_dir: {architect_written.get('slice_dir', manifest.get('slice_dir', '-'))}",
            f"- materialization_mode: {architect_written.get('materialization_mode', manifest.get('materialization_mode', '-'))}",
            f"- architect_manifest_path: {architect_written.get('architect_manifest_path', '-')}",
            f"- execution_packet_path: {architect_written.get('execution_packet_path', '-')}",
            f"- wave_count: {len(waves)}",
            "",
            "## Impacted Modules",
            _bullet(list(manifest.get("impacted_modules") or [])),
            "",
            "## Planner Inputs",
            _bullet(list(manifest.get("planner_inputs") or [])),
            "",
            "## Waves",
            _markdown_table(
                ["wave_id", "title", "objective"],
                [
                    [
                        str(item.get("wave_id") or "-"),
                        str(item.get("title") or "-"),
                        str(item.get("objective") or "-"),
                    ]
                    for item in waves
                ],
            ),
            "",
            "## Root Deltas",
            _bullet([f"{name}: {value}" for name, value in root_deltas.items()] or ["none"]),
            "",
        ]
    )


def _execution_packet_artifact_markdown(packet_path: str) -> str:
    path = Path(str(packet_path or "").strip())
    if not path.is_file():
        return "\n".join(
            [
                "# Execution Packet",
                "",
                f"- path: {packet_path or '-'}",
                "- status: missing",
                "",
            ]
        )
    return "\n".join(
        [
            f"# Execution Packet: {path.name}",
            "",
            f"- path: {path}",
            "",
            path.read_text(encoding="utf-8"),
        ]
    )


def _packet_graph_markdown(*, feature: dict[str, Any], packet_results: dict[str, Any]) -> str:
    planner_contract = dict(packet_results.get("planner_contract") or {})
    materialized = dict(packet_results.get("planner_materialized") or {})
    validation = dict(packet_results.get("planner_validation") or {})
    contract = dict(planner_contract.get("contract") or {})
    waves = list(contract.get("waves") or [])
    packets = list(contract.get("packets") or [])
    materialized_packets = list(materialized.get("packets") or [])

    def _deps(packet: dict[str, Any]) -> str:
        values = list(packet.get("dependencies") or [])
        return ", ".join(str(item) for item in values) if values else "-"

    def _execution_values(packet: dict[str, Any], key: str) -> str:
        execution = dict(dict(packet.get("verification_profile") or {}).get("execution") or {})
        values = list(execution.get(key) or [])
        return "<br>".join(str(item) for item in values) if values else "-"

    return "\n".join(
        [
            f"# Packet Graph Snapshot: {feature.get('feature_id', '-')}",
            "",
            f"- source: {planner_contract.get('source', '-')}",
            f"- parser_error: {planner_contract.get('parser_error', '-')}",
            f"- validation_valid: {validation.get('valid', '-')}",
            f"- wave_count: {len(waves)}",
            f"- packet_count: {len(packets)}",
            f"- materialized_packet_count: {len(materialized_packets)}",
            f"- wave_plan_path: {materialized.get('wave_plan_path', feature.get('wave_plan_path', '-'))}",
            "",
            "## Validation Issues",
            _bullet(list(validation.get("issues") or [])),
            "",
            "## Waves",
            _markdown_table(
                ["wave_id", "title", "objective"],
                [
                    [
                        str(item.get("wave_id") or "-"),
                        str(item.get("title") or "-"),
                        str(item.get("objective") or "-"),
                    ]
                    for item in waves
                ],
            ),
            "",
            "## Packet Graph",
            _markdown_table(
                ["key", "wave", "role", "title", "dependencies", "review_target_key"],
                [
                    [
                        str(packet.get("key") or "-"),
                        str(packet.get("wave_id") or "-"),
                        str(packet.get("role") or "-"),
                        str(packet.get("title") or "-"),
                        _deps(packet),
                        str(packet.get("review_target_key") or "-"),
                    ]
                    for packet in packets
                ],
            ),
            "",
            "## Verifier Execution Lanes",
            _markdown_table(
                ["key", "scope", "canonical_flow_commands", "frontend_commands", "observability_commands", "artifact_globs"],
                [
                    [
                        str(packet.get("key") or "-"),
                        str(((dict(packet.get("verification_profile") or {}).get("execution") or {}).get("observability_scope") or "-")),
                        _execution_values(packet, "canonical_flow_commands"),
                        _execution_values(packet, "frontend_commands"),
                        _execution_values(packet, "observability_commands"),
                        _execution_values(packet, "artifact_globs"),
                    ]
                    for packet in packets
                    if str(packet.get("role") or "") == "verifier"
                ],
            ),
            "",
            "## Materialized Packets",
            _markdown_table(
                ["packet_id", "wave", "role", "status", "dependencies"],
                [
                    [
                        str(packet.get("packet_id") or "-"),
                        str(packet.get("wave_id") or "-"),
                        str(packet.get("role") or "-"),
                        str(packet.get("status") or "-"),
                        _deps(packet),
                    ]
                    for packet in materialized_packets
                ],
            ),
            "",
        ]
    )


def _agent_outputs_markdown(*, feature: dict[str, Any], packet_results: dict[str, Any]) -> str:
    rows = _agent_output_rows(packet_results)
    return "\n".join(
        [
            f"# Agent Outputs Snapshot: {feature.get('feature_id', '-')}",
            "",
            f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Agent Run Files",
            _markdown_table(
                ["packet_id", "role", "rc", "runner", "last_message", "stdout", "stderr", "summary"],
                rows,
            ),
        ]
    )


def publish_feature_artifacts(
    *,
    feature: dict[str, Any],
    packet_results: dict[str, Any],
    verification: dict[str, Any] | None = None,
    review_route: dict[str, Any] | None = None,
    wave_route: dict[str, Any] | None = None,
    final_status: dict[str, Any] | None = None,
) -> list[str]:
    if create_markdown_artifact is None:
        return []

    feature_id = str(feature.get("feature_id") or "unknown-feature")
    artifact_ids = [
        str(
            create_markdown_artifact(
                key=_artifact_key("grace-feature", feature_id),
                description=_artifact_description(
                    "Live GRACE feature snapshot",
                    feature_id=feature_id,
                    status=(final_status or {}).get("feature", {}).get("status") if isinstance((final_status or {}).get("feature"), dict) else feature.get("status"),
                ),
                markdown=_feature_summary_markdown(
                    feature=feature,
                    verification=verification,
                    review_route=review_route,
                    wave_route=wave_route,
                    final_status=final_status,
                    packet_results=packet_results,
                ),
            )
        )
    ]
    if packet_results.get("architect_artifact_plan") or packet_results.get("architect_artifacts"):
        architect_written = dict(packet_results.get("architect_artifacts") or {})
        execution_packet_path = str(architect_written.get("execution_packet_path") or feature.get("execution_packet_path") or "").strip()
        if execution_packet_path:
            artifact_ids.append(
                str(
                    create_markdown_artifact(
                        key=_artifact_key("grace-execution-packet", feature_id),
                        description=_artifact_description(
                            "Execution packet markdown",
                            feature_id=feature_id,
                            path=execution_packet_path,
                        ),
                        markdown=_execution_packet_artifact_markdown(execution_packet_path),
                    )
                )
            )
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-architect", feature_id),
                    description=_artifact_description(
                        "Architect slice snapshot",
                        feature_id=feature_id,
                        slice_id=dict(packet_results.get("architect_artifacts") or {}).get("slice_id"),
                    ),
                    markdown=_architect_markdown(feature=feature, packet_results=packet_results),
                )
            )
        )
    if packet_results.get("planner_contract") or packet_results.get("planner_materialized"):
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-packet-graph", feature_id),
                    description=_artifact_description(
                        "Packet graph snapshot",
                        feature_id=feature_id,
                        source=dict(packet_results.get("planner_contract") or {}).get("source"),
                    ),
                    markdown=_packet_graph_markdown(feature=feature, packet_results=packet_results),
                )
            )
        )
    if _agent_output_rows(packet_results):
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-agent-outputs", feature_id),
                    description=_artifact_description(
                        "Agent output files snapshot",
                        feature_id=feature_id,
                    ),
                    markdown=_agent_outputs_markdown(feature=feature, packet_results=packet_results),
                )
            )
        )
    if review_route and review_route.get("review"):
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-review", review_route["review"].get("packet_id", feature_id)),
                    description=_artifact_description(
                        "Reviewer gate snapshot",
                        packet_id=review_route["review"].get("packet_id"),
                        verdict=review_route["review"].get("verdict"),
                    ),
                    markdown=_review_markdown(review_route),
                )
            )
        )
    if verification:
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-verification", verification.get("packet_id", feature_id)),
                    description=_artifact_description(
                        "Verifier evidence snapshot",
                        packet_id=verification.get("packet_id"),
                        test=verification.get("test_verdict"),
                        obs=verification.get("observability_verdict"),
                    ),
                    markdown=_verification_markdown(verification),
                )
            )
        )
    if wave_route and wave_route.get("wave_review"):
        wave_review = dict(wave_route["wave_review"])
        artifact_ids.append(
            str(
                create_markdown_artifact(
                    key=_artifact_key("grace-wave", wave_review.get("feature_id", feature_id), wave_review.get("wave_id", "W00")),
                    description=_artifact_description(
                        "Architect wave gate snapshot",
                        feature_id=wave_review.get("feature_id", feature_id),
                        wave_id=wave_review.get("wave_id", "W00"),
                        verdict=wave_review.get("verdict"),
                    ),
                    markdown=_wave_markdown(wave_route),
                )
            )
        )
    return artifact_ids


def publish_live_dashboard_artifact(
    *,
    feature_status_counts: dict[str, int],
    packet_status_counts: dict[str, int],
    job_status_counts: dict[str, int],
    blocked_features: list[str],
    blocked_packets: list[str],
    pending_packets: list[str],
    active_jobs: list[str],
    run_mappings: list[str],
) -> str | None:
    if create_markdown_artifact is None:
        return None
    markdown = "\n".join(
        [
            "# GRACE Live Dashboard",
            "",
            f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Feature Statuses",
            _bullet([f"{key}: {value}" for key, value in sorted(feature_status_counts.items())]),
            "",
            "## Packet Statuses",
            _bullet([f"{key}: {value}" for key, value in sorted(packet_status_counts.items())]),
            "",
            "## Job Statuses",
            _bullet([f"{key}: {value}" for key, value in sorted(job_status_counts.items())]),
            "",
            "## Blocked Features",
            _bullet(blocked_features),
            "",
            "## Blocked Packets",
            _bullet(blocked_packets),
            "",
            "## Pending / Ready Packets",
            _bullet(pending_packets),
            "",
            "## Active Jobs",
            _bullet(active_jobs),
            "",
            "## Prefect Run Mapping",
            _bullet(run_mappings),
            "",
        ]
    )
    return str(
        create_markdown_artifact(
            key="grace-live-dashboard",
            description=_artifact_description("Live GRACE status dashboard", scope="features+packets+waves+jobs"),
            markdown=markdown,
        )
    )


def publish_run_mapping_artifact(*, mappings: list[dict[str, Any]]) -> str | None:
    if create_markdown_artifact is None:
        return None
    rows: list[list[str]] = []
    for item in mappings:
        artifact_paths = list(item.get("artifact_paths") or [])
        rows.append(
            [
                str(item.get("flow_run_id") or "-"),
                str(item.get("feature_id") or "-"),
                str(item.get("wave") or "-"),
                str(item.get("packet_id") or "-"),
                str(item.get("role") or "-"),
                str(item.get("status") or "-"),
                "<br>".join(artifact_paths) if artifact_paths else "-",
            ]
        )
    markdown = "\n".join(
        [
            "# GRACE Run Mapping",
            "",
            f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            _markdown_table(
                ["flow_run_id", "feature_id", "wave", "packet_id", "role", "status", "artifact_paths"],
                rows,
            ),
        ]
    )
    return str(
        create_markdown_artifact(
            key="grace-run-mapping",
            description=_artifact_description("GRACE run mapping table", scope="flow+feature+wave+packet"),
            markdown=markdown,
        )
    )
