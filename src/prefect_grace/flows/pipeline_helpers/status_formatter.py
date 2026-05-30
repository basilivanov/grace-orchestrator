# ############################################################################
# AI_HEADER: pipeline_helpers.status_formatter
# ROLE: Pure status and user-summary formatting helpers for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Format feature pipeline statuses, labels, and terminal user summaries without side effects.
# inputs: Feature status strings, outcomes, summaries, next actions, and reasons.
# returns: FeatureStatus values and formatted strings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: failure_status_for_category
#   - function: short_reason
#   - function: status_label_ru
#   - function: final_user_summary
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.models import FeatureStatus


# START_FUNCTION_CONTRACT
# name: failure_status_for_category
# purpose: Map a pipeline failure category to the persisted feature status.
# inputs:
#   category: Failure category string.
# returns: FeatureStatus for that category, defaulting to blocked.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def failure_status_for_category(category: str) -> FeatureStatus:
    return {
        "pipeline_invalid": FeatureStatus.PIPELINE_INVALID,
        "verification_blocked": FeatureStatus.VERIFICATION_BLOCKED,
        "environment_blocked": FeatureStatus.ENVIRONMENT_BLOCKED,
        "product_blocked": FeatureStatus.PRODUCT_BLOCKED,
    }.get(category, FeatureStatus.BLOCKED)


# START_FUNCTION_CONTRACT
# name: short_reason
# purpose: Normalize and truncate a reason for compact user-facing summaries.
# inputs:
#   reason: Raw reason text.
# returns: A single-line reason capped at 140 characters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def short_reason(reason: str) -> str:
    text = " ".join(str(reason or "").strip().split())
    if len(text) <= 140:
        return text
    return text[:137].rstrip() + "..."


# START_FUNCTION_CONTRACT
# name: status_label_ru
# purpose: Convert feature status values to existing Russian user-facing labels.
# inputs:
#   status: Feature status string.
# returns: Russian label or normalized status fallback.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def status_label_ru(status: str) -> str:
    return {
        FeatureStatus.ACCEPTED.value: "принято",
        FeatureStatus.AWAITING_COMMIT.value: "принято, ждёт коммита",
        FeatureStatus.IN_PROGRESS.value: "нужна доработка",
        FeatureStatus.ARCHITECT_READY.value: "нужно решение архитектора",
        FeatureStatus.BLOCKED.value: "заблокировано",
        FeatureStatus.PRODUCT_BLOCKED.value: "заблокировано продуктовым решением",
        FeatureStatus.VERIFICATION_BLOCKED.value: "заблокировано проверкой",
        FeatureStatus.PIPELINE_INVALID.value: "пайплайн некорректен",
        FeatureStatus.ENVIRONMENT_BLOCKED.value: "среда заблокировала выпуск",
    }.get(str(status or "").strip().lower(), str(status or "").strip().lower())


# START_FUNCTION_CONTRACT
# name: final_user_summary
# purpose: Build the existing terminal user summary text for feature pipeline outcomes.
# inputs:
#   outcome: Final outcome category.
#   status: Feature status string.
#   summary: Existing feature summary.
#   next_action: Next action string, retained for API compatibility.
#   reasons: Optional blocker or rework reasons.
# returns: User-facing final summary string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def final_user_summary(
    *,
    outcome: str,
    status: str,
    summary: str,
    next_action: str,
    reasons: list[str] | None = None,
) -> str:
    cleaned_summary = " ".join(str(summary or "").strip().split())
    primary_reason = short_reason((reasons or [""])[0]) if reasons else ""
    normalized_outcome = str(outcome or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    if normalized_outcome == "awaiting_commit" or normalized_status == FeatureStatus.AWAITING_COMMIT.value:
        return "Итог: принято, ждёт коммита. Дальше: закоммитить изменения."
    if normalized_outcome == "accepted":
        return cleaned_summary or "Итог: принято и закоммичено."
    if normalized_outcome == "rework_required":
        if primary_reason:
            return f"Итог: нужна доработка. {primary_reason}"
        if cleaned_summary:
            return f"Итог: нужна доработка. {cleaned_summary}"
        return "Итог: нужна доработка."
    if normalized_outcome == "awaiting_architect":
        if primary_reason:
            return f"Итог: нужно решение архитектора. {primary_reason}"
        return "Итог: нужно решение архитектора."
    if normalized_outcome == "blocked":
        if primary_reason:
            return f"Итог: {status_label_ru(normalized_status)}. {primary_reason}"
        return f"Итог: {status_label_ru(normalized_status)}."
    if cleaned_summary:
        return cleaned_summary
    return f"Итог: {status_label_ru(normalized_status)}."


_failure_status_for_category = failure_status_for_category
_short_reason = short_reason
_status_label_ru = status_label_ru
_final_user_summary = final_user_summary
