# Error Matrix

Public API responses and the UI use stable codes without returning stack traces, authorization values or raw provider diagnostics.

| Code | HTTP | User-visible behavior | Retry/state effect |
| --- | ---: | --- | --- |
| `REQUEST_TOO_LARGE` | 413 | Запрос слишком большой. | No task is created; reduce the request and retry. |
| `AGENT_TOOLSET_NOT_READY` | 409 | MCP tools ещё не готовы. | No tool call; run discovery and retry task creation. |
| `PROJECT_ENVIRONMENT_NOT_ALLOWED` | 409 | Проект нельзя запускать в текущем окружении Inspector. | Terminal blocked task is recorded in `task_events`; no tool call; select a matching sandbox/test project. |
| `PROJECT_CAPABILITIES_NOT_READY` | 409 | У проекта недостаточно read-only capabilities для выбранного агента. | Terminal blocked task is recorded in `task_events`; no tool call; sync the project and retry. |
| `TASK_NOT_FOUND` | 404 | Задача не найдена. | Refresh history; no state change. |
| `TASK_NOT_CANCELLABLE` | 409 | Задачу уже нельзя отменить. | Terminal completed/failed state is unchanged. |
| `TASK_CANCELLED_BY_USER` | — | Задача отменена пользователем. | Terminal `cancelled`; no automatic retry. |
| `RETRIEVAL_PLAN_INVALID` | — | Не удалось подготовить read-only контекст. | Task becomes `failed`; audit records the failed stage. |
| `MCP_TOOL_CALL_FAILED` | — | MCP временно недоступен. | Task becomes `failed`; only policy-approved transport retries apply. |
| `NON_IDEMPOTENT_RETRY_BLOCKED` | — | Повтор неидемпотентного read-only вызова заблокирован. | Task becomes `failed`; inspect the audit and retry only as a new reviewed task. |
| `CONTEXT_LIMIT_EXCEEDED` | — | Контекст задачи слишком большой. | Task becomes `failed`; reduce scope and create a new task. |
| `MODEL_REPORT_INVALID` | — | Модель вернула неподдерживаемый отчёт. | Task becomes `failed`; no findings are persisted. |
| `DATABASE_UNAVAILABLE` | 503 | Сервис временно недоступен. | Retry after database recovery; no stack trace is returned. |
| `METRICS_UNAVAILABLE` | 503 | Метрики временно недоступны. | Retry with a valid identity after database recovery. |

The `task_events` and `tool_calls` audit records remain the source of execution facts. A running task cancellation is cooperative: an already-running MCP or model request is not forcefully terminated, but no next stage starts after the request completes.
