# Error Matrix

Public API responses and the UI use stable codes without returning stack traces, authorization values or raw provider diagnostics. `HTTP` describes a direct API response; `task 200` means the worker records the error in the task and the status endpoint remains readable.

| Code | HTTP surface | User-visible behavior | Audit/state | Retry and restart | Diagnostics |
| --- | ---: | --- | --- | --- | --- |
| `REQUEST_TOO_LARGE` | 413 | Запрос слишком большой. | No task is created. | Reduce the request and retry. | No body or stack trace. |
| `AUTH_REQUIRED` | 401 | Требуется авторизация. | No task audit. Request ID only. | Send a valid bearer token. | No authorization value is logged. |
| `AUTH_INVALID` | 401 | Недействительная авторизация. | No task audit. Request ID only. | Obtain a new valid token. | No issuer/JWKS diagnostic is returned. |
| `AUTH_NOT_CONFIGURED` | 503 | Авторизация временно недоступна. | No task audit. | Fix server configuration, then retry. | No secret or stack trace. |
| `AUTH_JWKS_NOT_CONFIGURED` | 503 | Авторизация временно недоступна. | No task audit. | Configure JWKS issuer, then retry. | No URL or provider detail. |
| `AUTH_JWKS_UNAVAILABLE` | 503 | Авторизация временно недоступна. | No task audit. | Retry after issuer recovery. | No network exception. |
| `AGENT_TOOLSET_NOT_READY` | 409 | MCP tools ещё не готовы. | No tool call; task creation is blocked. | Run discovery and create a new task. | Readiness reasons are safe codes only. |
| `PROJECT_NOT_FOUND` | 404 | Проект не найден. | No task audit. | Refresh projects and retry with a current ID. | No database detail. |
| `AGENT_NOT_FOUND` | 404 | Агент не найден. | No task audit. | Use an agent from the registry. | No database detail. |
| `PROJECT_ENVIRONMENT_NOT_ALLOWED` | 409 | Проект нельзя запускать в текущем окружении. | Terminal blocked task and `task_blocked` event; no tool call. | Select matching `sandbox`/`test` project and create a new task. | No configuration values exposed. |
| `PROJECT_CAPABILITIES_NOT_READY` | 409 | У проекта недостаточно read-only capabilities. | Terminal blocked task and `task_blocked` event; no tool call. | Sync project/discovery and create a new task. | Only capability names/reasons are returned. |
| `TASK_NOT_FOUND` | 404 | Задача не найдена. | No state change. | Refresh task history. | No query or database detail. |
| `TASK_NOT_CANCELLABLE` | 409 | Задачу уже нельзя отменить. | Existing terminal state is unchanged. | Do not retry cancellation. | No stack trace. |
| `REPORT_NOT_READY` | 409 | Отчёт ещё не готов. | No state change. | Poll task status, then load the report. | No worker detail. |
| `TASK_CANCELLED_BY_USER` | `task 200` | Задача отменена пользователем. | `cancel_requested`, `task_cancelled`; terminal `cancelled`. | No automatic retry; create a new task. | No active request diagnostics. |
| `RETRIEVAL_PLAN_INVALID` | `task 200` | Не удалось подготовить read-only контекст. | `task_failed`; no unsafe call. | Correct the retrieval plan and create a new task. | Stable code only. |
| `RETRIEVAL_LIMIT_EXCEEDED` | `task 200` | Превышен лимит retrieval calls. | `task_failed`; completed calls remain in audit. | Narrow the plan and create a new task. | No raw MCP output. |
| `RETRIEVAL_STEP_INVALID` | `task 200` | Некорректный retrieval step. | `task_failed`; invalid step is not called. | Correct the plan and create a new task. | Stable code only. |
| `RETRIEVAL_ARGUMENTS_INVALID` | `task 200` | Некорректные аргументы read-only tool. | `task_failed`; no network call for the invalid step. | Correct arguments and create a new task. | No provider diagnostics. |
| `RETRIEVAL_CAPABILITY_NOT_ALLOWED` | `task 200` | Capability агента не разрешена. | `task_failed`; tool call is blocked. | Use the correct agent or sync policy, then create a new task. | Policy details are not secrets. |
| `MCP_TOOL_CALL_FAILED` | `task 200` | MCP временно недоступен. | Failed call in `tool_calls`; `task_failed`. | Only policy-approved transport retries; otherwise create a new task. | Safe `errorCode`, no stack trace. |
| `MCP_RESULT_TOO_LARGE` | `task 200` | MCP вернул слишком большой результат. | Failed call with original `resultSizeChars`; content is not stored; `task_failed`. | Reduce retrieval scope and create a new task. | Oversized content is never returned. |
| `TASK_TIMEOUT` | `task 200` | Задача превысила общий deadline. | `task_failed`; no next stage or automatic retry. | Create a new task with a narrower scope. | No provider timeout detail. |
| `METHOD_READ_LIMIT_EXCEEDED` | `task 200` | Превышен лимит чтения модулей. | `task_failed`; calls already completed remain audited. | Reduce source scope and create a new task. | No source content is exposed by the error. |
| `NON_IDEMPOTENT_RETRY_BLOCKED` | `task 200` | Повтор read-only call заблокирован policy. | `task_failed`; prior call remains the source of facts. | Review audit and create a new task if needed. | Stable code only. |
| `CONTEXT_LIMIT_EXCEEDED` | `task 200` | Контекст задачи слишком большой. | `task_failed`; model is not called. | Reduce retrieval scope and create a new task. | No context body in the error. |
| `MODEL_REQUEST_FAILED` | `task 200` | Модель временно недоступна. | `task_failed`; no report or findings persisted. | Up to `MODEL_RETRIES` retries for timeout/408/409/425/429/5xx/transport errors; create a new task after exhaustion. | Provider exception is not returned. |
| `MODEL_RESPONSE_INVALID` | `task 200` | Модель вернула неподдерживаемый ответ. | `task_failed`; no findings persisted. | Narrow the task or retry as a new task. | Raw model response is not returned. |
| `MODEL_REPORT_INVALID` | `task 200` | Отчёт модели не прошёл проверку схемы. | `task_failed`; no findings persisted. | Correct scope/prompt configuration and create a new task. | Validation details are not exposed as stack traces. |
| `MODEL_REPORT_TASK_MISMATCH` | `task 200` | Ответ модели не относится к этой задаче. | `task_failed`; no findings persisted. | Create a new task after model recovery. | No model payload is returned. |
| `FINDINGS_LIMIT_EXCEEDED` | `task 200` | Отчёт содержит слишком много findings. | `task_failed`; findings are not persisted. | Narrow task scope and create a new task. | No oversized report is returned. |
| `RETRIEVAL_FAILED` | `task 200` | Read-only retrieval завершился ошибкой. | `task_failed`; completed audit calls remain. | Inspect safe audit codes and create a new task. | Original exception is hidden. |
| `WORKER_LEASE_EXPIRED` | `task 200` | Задача продолжает выполнение после восстановления worker. | Task is requeued; `task_recovered` event is appended. | Recovery is automatic for eligible idempotent calls. | No worker internals are public. |
| `DATABASE_UNAVAILABLE` | 503 | Сервис временно недоступен. | No partial public state is fabricated. | Retry after PostgreSQL recovery. | No connection string or stack trace. |
| `METRICS_UNAVAILABLE` | 503 | Метрики временно недоступны. | No task state change. | Retry with valid identity after recovery. | No database diagnostic. |
| `PROJECT_SYNC_NOT_CONFIGURED` | 503 | Синхронизация проектов не настроена. | No project state change. | Configure the read-only project tool and retry. | No environment secret is returned. |
| `PROJECT_SYNC_UNAVAILABLE` | 503 | MCP project sync временно недоступен. | No partial sync is committed. | Retry after MCP recovery. | No provider exception. |

Patch Planner uses the same public rules for `PATCH_*` validation, approval, package and source-revalidation codes: direct validation failures return 409/422 or 404 as appropriate, no file or Git change is applied, the proposal/patch audit records the state transition, and a new request is required after a terminal failure. Package content and signatures are never included in an error response.

The `task_events` and `tool_calls` audit records remain the source of execution facts. A running task cancellation is cooperative: an already-running MCP or model request is not forcefully terminated, but no next stage starts after the request completes. Every public error path omits stack traces, authorization values, raw request bodies and raw provider diagnostics.
