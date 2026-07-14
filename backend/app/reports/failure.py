from app.reports.schema import ModelUsage, StructuredReport, ToolUsage


def build_failure_report(
    task_id: str,
    error_code: str,
    model_name: str = "unknown",
) -> StructuredReport:
    return StructuredReport(
        taskId=task_id,
        status="failed",
        summary="Задача завершена без проверенного результата.",
        findings=[],
        objectsReviewed=[],
        validation={"readOnly": True, "errorCode": error_code},
        sourceCoverage="none",
        toolUsage=ToolUsage(calls=0, durationMs=0),
        modelUsage=ModelUsage(
            model=model_name,
            inputTokens=0,
            outputTokens=0,
            durationMs=0,
            estimatedCost=0,
        ),
        limitations=["Обработка остановлена до формирования проверенного отчета."],
        nextActions=["Устранить причину ошибки и повторить задачу."],
    )


def normalize_failure_report(
    payload: object,
    task_id: str,
    error_code: str,
    model_name: str = "unknown",
) -> dict[str, object]:
    normalized = build_failure_report(task_id, error_code, model_name).model_dump(by_alias=True)
    if isinstance(payload, dict):
        normalized.update(payload)
    normalized["taskId"] = task_id
    normalized["status"] = "failed"
    validation = normalized.get("validation")
    if not isinstance(validation, dict):
        validation = {}
        normalized["validation"] = validation
    validation.setdefault("readOnly", True)
    validation.setdefault("errorCode", error_code)
    return normalized
