# 1C AI Inspector v0.1

Read-only web-приложение для анализа кода 1С через EDT MCP Server.

Первый срез реализует технический фундамент:

- FastAPI и Python 3.13;
- PostgreSQL с отдельными migration/runtime ролями;
- Alembic и одноразовый Compose-сервис `migrate`;
- отдельный PostgreSQL worker;
- OpenAI-compatible model adapter для трёх профилей агентов и structured report validation;
- worker claim через `FOR UPDATE SKIP LOCKED` с lease/heartbeat и возвратом зависших задач;
- атомарный claim через `SELECT ... FOR UPDATE SKIP LOCKED`;
- MCP policy с checksum;
- нормализацию toolset с отдельным checksum;
- публикацию только `read-only` tools;
- `/health`, `/api/v1/system/readiness` и `/api/v1/system/policy`.
- `/api/v1/system/ready` с проверкой toolset и PostgreSQL.
- `/api/v1/system/mcp/tools` для discovery разрешённых MCP tools.
- `/api/v1/system/mcp/health` для безопасной проверки MCP `initialize`.
- `/api/v1/system/capabilities` для проверки покрытия capabilities всеми агентами.
- `/api/v1/system/diagnostics` для проверки конфигурации MCP, policy и Model API без раскрытия секретов.
- `POST /api/v1/tasks` с Readiness Gate и execution snapshot.
- `GET /api/v1/tasks/{task_id}` для статуса, attempt и result readiness.
- `GET /api/v1/agents` с тремя агентами v0.1.
- React/Vite web UI на `http://localhost:5173`.
- `GET /api/v1/tasks/{task_id}/audit` для task events, tool calls и model usage.
- `GET /api/v1/tasks/{task_id}/report` для structured report и сохранённых findings.
- `POST /api/v1/projects/sync` для read-only MCP-синхронизации проектов.

## Запуск в PowerShell

```powershell
Copy-Item .env.example .env
notepad .env
docker compose --env-file .env up --build
```

После запуска откройте `http://localhost:5173`. Панель показывает readiness, проекты из PostgreSQL, policy/toolset checksums, registry агентов, запускает MCP discovery и позволяет просматривать audit/report созданной task.

Frontend dependencies не коммитятся; `frontend/package-lock.json` фиксирует версии для повторяемой установки.

Проверка:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/system/readiness
Invoke-RestMethod http://localhost:8000/api/v1/system/policy
Invoke-RestMethod http://localhost:8000/api/v1/system/ready
```

Статическую acceptance-проверку можно запустить без поднятия контейнеров: `.scriptsacceptance.ps1 -SkipDockerRuntime`. Полная проверка дополнительно требует доступный Docker Engine и выполняет backend health smoke test. Offline acceptance-тест отдельно проходит mock MCP -> project sync -> retrieval -> report контур и не заменяет live EDT/MODEL E2E.
Live acceptance после настройки `.env` запускается командой `.scripts\live-acceptance.ps1`; для оставления контейнеров работающими используйте `-KeepRunning`. Скрипт проверяет Docker, backend health, diagnostics, MCP health/discovery, bridge tool smoke call и project sync, а при placeholder-конфигурации перечисляет все отсутствующие ключи. Docker preflight завершается с timeout, если daemon не отвечает.

Тесты без Docker:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

## Ограничения текущего среза

Readiness Gate возвращает `not_ready`, пока tools не обнаружены и не нормализованы. Это блокирует запуск агентного контура до появления доступных read-only capabilities.

MCP discovery получает `tools/list`, принимает только инструменты, перечисленные в policy, сохраняет нормализованный snapshot в PostgreSQL и отправляет на MCP Server исходное имя инструмента. Неизвестные инструменты отклоняются до сетевого запроса. Readiness становится `ready` только после успешного discovery и покрытия capabilities всех трёх агентов; policy без реальных EDT tool names остаётся `NOT READY`. PostgreSQL создаёт отдельные migration/runtime роли и default privileges для runtime-запросов.

Task Orchestrator не создаёт агентную задачу, если toolset не готов: API возвращает `409 AGENT_TOOLSET_NOT_READY`. При успешном создании задача получает `queued`, worker атомарно переводит её в `running`, после чего разрешены только `completed`, `failed` или `cancelled`. Сохраняются state, policy checksum, toolset checksum, prompt version и model snapshot.

Синхронизация проектов включается только при заданном `MCP_PROJECTS_TOOL`. Имя должно быть опубликовано в `mcp_policy.yaml`; иначе вызов блокируется до сетевого запроса.

Agent retrieval принимает только явный `request.retrieval` plan. Каждый шаг проверяется по опубликованному read-only tool и capability конкретного агента, результат маркируется как untrusted MCP context, а вызов попадает в `tool_calls` audit.
Количество retrieval calls ограничивается `MAX_TOOL_CALLS` до первого сетевого вызова.
Даже failed MCP calls сохраняются в `tool_calls` с `status=failed` и безопасным `errorCode`.
Для read-only tools policy может задать ограниченное число повторов через `retries`; повторяются только transport/HTTP ошибки.

MCP connector использует Streamable HTTP session lifecycle: `initialize`, `notifications/initialized`, `Mcp-Session-Id`, `MCP-Protocol-Version`, повторное использование клиента и уникальные JSON-RPC request ids с проверкой response id. Ответы JSON и `text/event-stream` поддерживаются; project sync принимает list и вложенный `{projects: [...]}`.

Для `sales-ai-manager/onec-mcp-bridge` доступен режим `MCP_TRANSPORT=bridge`: Inspector вызывает bridge endpoints `/health`, `/tools`, `/tools/call` и передаёт `MCP_BRIDGE_TOKEN` как Bearer token. Raw MCP режим остаётся `MCP_TRANSPORT=streamable-http`.

Текущая bridge policy публикует только фактически доступные read-only tools: syntax help, configuration info, event log, form/metadata/object structure и query validation. `execute_query` намеренно не публикуется. Если bridge не возвращает `search_code`, Code Assistant и Audit Agent остаются заблокированными readiness gate до появления этого capability.

При повторном discovery отсутствующие на MCP инструменты получают статус `retired` в `normalized_tools`, поэтому старые capabilities не остаются активными в базе.

Model adapter принимает JSON string, content blocks и JSON в markdown fence, после чего всё равно валидирует ответ как `StructuredReport`.

Агенты v0.1: `1c_code_assistant`, `1c_query_agent`, `1c_audit_agent`. Structured report требует непустой `evidence` для каждого finding и ссылку на объект 1С.

Стоимость модели считается только по явно заданным `MODEL_INPUT_COST_PER_1K` и `MODEL_OUTPUT_COST_PER_1K`; значения `0` по умолчанию не маскируют неизвестные тарифы. Audit endpoint возвращает длительность и статусы tool calls, токены и estimated cost.

Worker вызывает модель только после claim задачи. Ответ обязан соответствовать `StructuredReport`; findings без evidence отклоняются, а token usage и estimated cost пишутся в audit.
Контекст задачи ограничивается `MAX_CONTEXT_CHARS` и передаётся модели как `<untrusted_context>`: содержимое проекта трактуется только как данные, а не как инструкции. Findings и evidence сохраняются в `findings` и `finding_status_events`.

Финальная локальная проверка без Docker:

```powershell
cd backend
python -m pytest -q
python -m compileall -q app migrations tests
cd ..\frontend
npm run build
```

Для полной проверки Compose требуется запущенный Docker Engine. На текущем окружении `docker compose config` проверен, но сборка контейнеров не выполнялась, потому что Docker Engine недоступен.

Синхронизация проектов и retrieval-контекст реализованы через конфигурируемые read-only MCP tools. Реальный запуск всё ещё требует рабочего EDT MCP endpoint, заполненной policy и ключа модели. Docker-образы запускаются от non-root пользователей и используют lockfile frontend dependencies.

Перед runtime запуском проверьте `Invoke-RestMethod http://localhost:8000/api/v1/system/diagnostics`. Endpoint показывает только факт настройки API key (`true/false`), но не его значение.
