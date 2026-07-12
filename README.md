# 1C AI Inspector v0.3

Read-only web-приложение для анализа кода 1С через EDT MCP Server.

Текущий этап v0.3 развивает proposal-only Patch Planner: система готовит изменения, проверяет source snapshot, impact evidence и validation gates, но не применяет их к 1С, workspace или Git.

`POST /api/v1/patch-proposals` принимает безопасные пары `original/proposed`, проверяет относительные пути, считает SHA-256 и сохраняет unified diff. Proposal создается в статусе `proposed`; файловая система и Git не изменяются.

`POST /api/v1/patch-proposals/{id}/impact` строит candidate impact analysis по измененным путям 1С. В body можно передать только evidence от read-only `search_code` или `get_object_structure`; совпавшие объекты получают `risk: evidenced`, остальные остаются candidate.

`POST /api/v1/patch-proposals/{id}/checkpoint` создает детерминированную логическую checkpoint-ссылку по revision и SHA-256 diff. Checkpoint не выполняет `git commit`, не создает ветку, не меняет workspace и не записывает изменения в 1С; в ответе `applied` всегда остается `false`.

`POST /api/v1/patch-proposals/{id}/approve` принимает `actor`, `role` и `note` только для checkpointed proposal; роль `maintainer` или `owner` обязательна. `POST /api/v1/patch-proposals/{id}/reject` фиксирует отказ для незавершенного proposal; доступна роль `reviewer`, `maintainer` или `owner`. Оба endpoint только сохраняют решение и возвращают `applied: false`; автоматического применения diff нет.

`GET /api/v1/patch-proposals/{id}/events` возвращает append-only историю действий proposal. В UI Patch Planner можно создать proposal, просмотреть diff, запустить impact/checkpoint и зафиксировать approve/reject; отдельного действия `apply` интерфейс не предоставляет.

`GET /api/v1/patch-proposals/{id}/package` возвращает ZIP-пакет в памяти с `manifest.json`, `proposal.diff` и README-инструкцией. Manifest содержит `applyAllowed: false`; сервер не сохраняет ZIP на диск и не выполняет изменения.

`POST /api/v1/patch-proposals/{id}/revalidate` принимает текущий read-only snapshot и revision, сравнивает SHA-256 с исходным proposal и сохраняет `valid` или `stale`. Checkpoint разрешен только после `valid`; изменившийся или неполный source snapshot блокирует checkpoint.

`POST /api/v1/patch-proposals/{id}/validate` выполняет детерминированные validation-gates: source status, unified diff, SHA snapshot, количество измененных строк и допустимое расширение файла. Approval разрешен только после `sourceValidationStatus=valid` и `validationStatus=valid`.

Approve, reject и package download требуют signed Bearer token из `INSPECTOR_AUTH_SECRET`. Subject и role берутся из проверенной подписи, а не из request body; роли `maintainer` и `owner` могут approve, `reviewer` может reject. Токен не выводится в UI или audit.

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
- `search_code` для read-only поиска по выгруженным BSL-модулям конфигурации.

## Запуск в PowerShell

```powershell
Copy-Item .env.example .env
notepad .env
docker compose --env-file .env up --build
```

Для защищенных approval/package endpoint задайте в `.env` случайный `INSPECTOR_AUTH_SECRET` длиной не менее 32 символов. Signed Bearer tokens должен выпускать внешний issuer или gateway; Inspector только проверяет подпись и expiry.

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
Финальную приемку v0.1 с проверкой готовности, project sync, read-only toolset и конкретных task reports запускайте так:

```powershell
.\scripts\v01-acceptance.ps1 `
  -CodeTaskId <code-task-id> `
  -QueryTaskId <query-task-id> `
  -AuditTaskId <audit-task-id>
```

Скрипт отклоняет `execute_query`, write tools и findings без evidence.

Финальную приемку v0.2 Patch Planner запускайте при работающем Compose:

```powershell
.\scripts\v02-acceptance.ps1
```

Скрипт создает временные proposal-only данные, проверяет candidate impact, логический checkpoint, approve/reject и журнал из событий. Он не применяет diff, не меняет workspace/Git и не записывает изменения в конфигурацию 1С.

Финальную приемку v0.3 запускайте при работающем Compose:

```powershell
.\scripts\v03-acceptance.ps1 -AuthToken <signed-token>
```

Скрипт проверяет read-only impact evidence, source revalidation, validation-gates, checkpoint, role policy, ZIP package и полный audit log. Весь контур остается proposal-only.

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

Task Orchestrator не создаёт агентную задачу, если toolset не готов: API возвращает `409 AGENT_TOOLSET_NOT_READY`. При успешном создании сначала сохраняется строка task, затем связанный execution snapshot и событие создания; задача получает `queued`, worker атомарно переводит её в `running`, после чего разрешены только `completed`, `failed` или `cancelled`. Сохраняются state, policy checksum, toolset checksum, prompt version и model snapshot.

Синхронизация проектов включается только при заданном `MCP_PROJECTS_TOOL`. Для MCP-сервера, который возвращает список проектов, укажите его read-only tool name. Для текущего локального `mcp-1c` используйте `MCP_PROJECTS_TOOL=get_configuration_info`: Inspector создаёт одну карточку проекта из фактов конфигурации 1С и capabilities активной policy. Имя должно быть опубликовано в `mcp_policy.yaml`; иначе вызов блокируется до сетевого запроса.

Patch Planner в v0.3 сохраняет proposal-only режим: после создания diff нужно выполнить source revalidation, затем можно построить candidate impact и логический checkpoint. Ни один endpoint этого среза не применяет код, не меняет конфигурацию 1С и не создает Git-коммиты.

Текущий signed-token слой заменяет self-claimed role, но не является SSO/IdP: перед production нужно подключить внешний issuer или корпоративный gateway, который будет выпускать эти claims.

Agent retrieval принимает только явный `request.retrieval` plan. Каждый шаг проверяется по опубликованному read-only tool и capability конкретного агента, результат маркируется как untrusted MCP context, а вызов попадает в `tool_calls` audit.
Количество retrieval calls ограничивается `MAX_TOOL_CALLS` до первого сетевого вызова.
Даже failed MCP calls сохраняются в `tool_calls` с `status=failed` и безопасным `errorCode`.
Для read-only tools policy может задать ограниченное число повторов через `retries`; повторяются только transport/HTTP ошибки.

MCP connector использует Streamable HTTP session lifecycle: `initialize`, `notifications/initialized`, `Mcp-Session-Id`, `MCP-Protocol-Version`, повторное использование клиента и уникальные JSON-RPC request ids с проверкой response id. Ответы JSON и `text/event-stream` поддерживаются; project sync принимает list и вложенный `{projects: [...]}`.

Для `sales-ai-manager/onec-mcp-bridge` доступен режим `MCP_TRANSPORT=bridge`: Inspector вызывает bridge endpoints `/health`, `/tools`, `/tools/call` и передаёт `MCP_BRIDGE_TOKEN` как Bearer token. Raw MCP режим остаётся `MCP_TRANSPORT=streamable-http`.

Текущая bridge policy публикует только фактически доступные read-only tools: syntax help, configuration info, event log, form/metadata/object structure, code search и query validation. `execute_query` намеренно не публикуется. `search_code` работает по отдельной выгрузке конфигурации через `DumpConfigToFiles` и не требует изменения конфигурации 1С; bridge запускается с параметром `mcp-1c --dump <path>`. Без успешного discovery Code Assistant и Audit Agent по-прежнему блокируются readiness gate.

При повторном discovery отсутствующие на MCP инструменты получают статус `retired` в `normalized_tools`, поэтому старые capabilities не остаются активными в базе.

Model adapter принимает JSON string, content blocks и JSON в markdown fence, после чего всё равно валидирует ответ как `StructuredReport`.
Для моделей GPT-5 адаптер не передаёт `temperature=0`, потому что эти модели принимают только значение по умолчанию; для остальных OpenAI-compatible моделей сохраняется детерминированный `temperature=0`.
Agent prompt получает фактическую JSON Schema `StructuredReport`, но итоговый ответ всё равно проверяется сервером перед сохранением task и findings.
Telemetry в `StructuredReport` не доверяет значениям модели: model usage берётся из adapter, а tool usage — из фактически записанных retrieval calls и их длительности.

Live-проверка Query Agent подтверждена на подключенной базе: `validate_query` проверил запрос без выполнения данных, `get_metadata_tree` подтвердил наличие справочника, а итоговый report сохранил validation, audit и фактическое model/tool usage.
Live-проверка Audit Agent также подтверждена: read-only поиск кода и чтение структуры документа сформировали findings с evidence, а те же findings были сохранены в PostgreSQL и доступны через report endpoint.

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
