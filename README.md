# 1C AI Inspector v0.1

Read-only web-приложение для анализа кода 1С через EDT MCP Server.

Первый срез реализует технический фундамент:

- FastAPI и Python 3.13;
- PostgreSQL с отдельными migration/runtime ролями;
- Alembic и одноразовый Compose-сервис `migrate`;
- отдельный PostgreSQL worker;
- worker claim через `FOR UPDATE SKIP LOCKED` с lease/heartbeat и возвратом зависших задач;
- атомарный claim через `SELECT ... FOR UPDATE SKIP LOCKED`;
- MCP policy с checksum;
- нормализацию toolset с отдельным checksum;
- публикацию только `read-only` tools;
- `/health`, `/api/v1/system/readiness` и `/api/v1/system/policy`.
- `/api/v1/system/ready` с проверкой toolset и PostgreSQL.
- `/api/v1/system/mcp/tools` для discovery разрешённых MCP tools.
- `/api/v1/system/mcp/health` для безопасной проверки MCP `initialize`.
- `POST /api/v1/tasks` с Readiness Gate и execution snapshot.
- `GET /api/v1/agents` с тремя агентами v0.1.
- React/Vite web UI на `http://localhost:5173`.
- `GET /api/v1/tasks/{task_id}/audit` для task events, tool calls и model usage.

## Запуск в PowerShell

```powershell
Copy-Item .env.example .env
notepad .env
docker compose --env-file .env up --build
```

После запуска откройте `http://localhost:5173`. Панель показывает readiness, policy/toolset checksums, registry агентов и блокирует создание task, пока MCP tools не готовы.

Frontend dependencies не коммитятся; `frontend/package-lock.json` фиксирует версии для повторяемой установки.

Проверка:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/system/readiness
Invoke-RestMethod http://localhost:8000/api/v1/system/policy
Invoke-RestMethod http://localhost:8000/api/v1/system/ready
```

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

MCP discovery получает `tools/list`, принимает только инструменты, перечисленные в policy, сохраняет нормализованный snapshot в PostgreSQL и отправляет на MCP Server исходное имя инструмента. Неизвестные инструменты отклоняются до сетевого запроса. Readiness становится `ready` только после успешного discovery через `/api/v1/system/mcp/tools`; policy без реальных EDT tool names остаётся `NOT READY`. PostgreSQL создаёт отдельные migration/runtime роли и default privileges для runtime-запросов.

Task Orchestrator не создаёт агентную задачу, если toolset не готов: API возвращает `409 AGENT_TOOLSET_NOT_READY`. При успешном создании сохраняются state, policy checksum, toolset checksum, prompt version и model snapshot.

Агенты v0.1: `1c_code_assistant`, `1c_query_agent`, `1c_audit_agent`. Structured report требует непустой `evidence` для каждого finding и ссылку на объект 1С.

Стоимость модели считается только по явно заданным `MODEL_INPUT_COST_PER_1K` и `MODEL_OUTPUT_COST_PER_1K`; значения `0` по умолчанию не маскируют неизвестные тарифы. Audit endpoint возвращает длительность и статусы tool calls, токены и estimated cost.

Финальная локальная проверка без Docker:

```powershell
cd backend
python -m pytest -q
python -m compileall -q app migrations tests
cd ..\frontend
npm run build
```

Для полной проверки Compose требуется запущенный Docker Engine. На текущем окружении `docker compose config` проверен, но сборка контейнеров не выполнялась, потому что Docker Engine недоступен.

Пока не реализованы полноценные синхронизация EDT-проектов, Code Assistant, Query Agent, Audit Agent, structured findings и вызов модели. MCP connector уже имеет серверную проверку policy, но транспорт и реальное обнаружение tools будут расширены следующим шагом.
