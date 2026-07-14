# 1C AI Inspector v0.6

Read-only web-приложение для анализа кода 1С через EDT MCP Server.

Документы контура: [Backlog v0.2](docs/BACKLOG_V0.2.md), [Security Model](docs/SECURITY_MODEL.md), [Architecture Overview](docs/ARCHITECTURE.md), [Known Limitations](docs/KNOWN_LIMITATIONS.md) и [матрица ошибок](docs/ERROR_MATRIX.md).

Текущий этап v0.6 развивает proposal-only Patch Planner: система использует signed auth/RBAC или внешний JWT issuer через JWKS, автоматический read-only MCP evidence, source snapshot и signed package, но не применяет изменения к 1С, workspace или Git.

Definition of Done для Patch Planner зафиксирован в `docs/BACKLOG_V0.2.md`. В v0.2 разрешена только подготовка и ручная передача подписанного пакета: Inspector всегда возвращает `applied: false`. Controlled apply, sandbox branch, EDT validation, тестовая база и rollback относятся к v0.3 Sandbox Executor.

`POST /api/v1/patch-proposals` принимает безопасные пары `original/proposed`, проверяет относительные пути, считает SHA-256 и сохраняет unified diff. Proposal создается в статусе `proposed`; файловая система и Git не изменяются.

`POST /api/v1/patch-proposals/from-finding` создает proposal из завершенной задачи и сохраненного finding. Endpoint требует Bearer identity, берет Original только из соответствующего успешного `read-only` вызова `read_source`, отклоняет отсутствующий или неоднозначный source и фиксирует `taskId`, `findingId`, `toolCallId` и модуль в событии `source_imported`. В UI после загрузки отчета можно выбрать finding; введенное вручную поле Original в этом режиме backend не использует.

`POST /api/v1/patch-proposals/{id}/impact` строит candidate impact analysis по измененным путям 1С. В body можно передать только evidence от read-only `search_code` или `get_object_structure`; совпавшие объекты получают `risk: evidenced`, остальные остаются candidate.

`POST /api/v1/patch-proposals/{id}/impact/mcp` автоматически вызывает настроенный policy-published `MCP_PATCH_SEARCH_TOOL` через существующий bridge/Streamable HTTP connector. Вызов допускается только для категории `code.search`; результат ограничивается 20 evidence на объект и записывается в proposal audit.

`POST /api/v1/patch-proposals/{id}/checkpoint` создает детерминированную логическую checkpoint-ссылку по revision и SHA-256 diff. Checkpoint не выполняет `git commit`, не создает ветку, не меняет workspace и не записывает изменения в 1С; в ответе `applied` всегда остается `false`.

`POST /api/v1/patch-proposals/{id}/checkpoint/git` требует Bearer identity и проверяет immutable Git checkpoint. Backend принимает только полный 40/64-символьный commit SHA, разрешает его в оператором смонтированном read-only repository и через `git cat-file blob` проверяет существование каждого BSL-пути и совпадение bytes с `originalSha256` proposal. `GIT_OPTIONAL_LOCKS=0`; branch, index и working tree не изменяются. UI-кнопка `CHECKPOINT` использует этот fail-closed endpoint. Старый логический endpoint сохранен только для API-совместимости.

Backend image содержит только необходимый Git CLI; путь repository не принимается из HTTP-запроса и задается оператором через `PATCH_GIT_REPOSITORY`.

Для локальной Git-проверки задайте `PATCH_GIT_HOST_PATH` и подключите отдельный read-only override:

```powershell
docker compose --env-file .env -f docker-compose.yml -f docker-compose.patch-git.yml up --build
```

`POST /api/v1/patch-proposals/{id}/revalidate/from-task` повторно получает Original из сохраненного `read_source` того же finding и сравнивает SHA-256 на backend. Исходный BSL не требуется возвращать браузеру для revalidation.

`POST /api/v1/patch-proposals/{id}/approve` принимает `actor`, `role` и `note` только для checkpointed proposal; роль `maintainer` или `owner` обязательна. `POST /api/v1/patch-proposals/{id}/reject` фиксирует отказ для незавершенного proposal; доступна роль `reviewer`, `maintainer` или `owner`. Оба endpoint только сохраняют решение и возвращают `applied: false`; автоматического применения diff нет.

`GET /api/v1/patch-proposals/{id}/events` возвращает append-only историю действий proposal. В UI Patch Planner можно создать proposal, просмотреть diff, запустить impact/checkpoint и зафиксировать approve/reject; отдельного действия `apply` интерфейс не предоставляет.

`GET /api/v1/patch-proposals/{id}/package` возвращает последнюю immutable-версию подписанного ZIP-пакета с `manifest.json`, `proposal.diff`, `signature.json` и README-инструкцией. Первая выдача сохраняет пакет в PostgreSQL с SHA-256 и actor; `GET /api/v1/patch-proposals/{id}/package?version=N` получает конкретную версию, а `/package/versions` возвращает metadata без ZIP. Manifest содержит `applyAllowed: false`; `POST /api/v1/patch-proposals/{id}/package/verify` проверяет подпись и целостность загруженного package. Сервер не сохраняет ZIP на диск и не выполняет изменения.

Новая версия package создается только после `approved`. Если immutable package более раннего состояния уже существует, export сохраняет следующую версию с approved manifest, не перезаписывая архив. `POST /api/v1/patch-proposals/{id}/handoff` требует роль `maintainer` или `owner`, точные version/SHA-256 и target environment. Backend повторно проверяет хеш, HMAC-подпись, status, checkpoint и environment внутри manifest, затем добавляет `manual_handoff_created` в append-only audit. Handoff означает передачу пакета внешнему оператору и всегда возвращает `applyAllowed: false`, `applied: false`; apply endpoint отсутствует.

`POST /api/v1/patch-proposals/{id}/revalidate` принимает текущий read-only snapshot и revision, сравнивает SHA-256 с исходным proposal и сохраняет `valid` или `stale`. Checkpoint разрешен только после `valid`; изменившийся или неполный source snapshot блокирует checkpoint.

Approval transitions and first package-version creation lock the proposal row with PostgreSQL `FOR UPDATE`, so concurrent decisions cannot both commit a final state or duplicate version `1`.

Каждый HTTP-запрос получает `X-Request-ID`; JSON logs содержат только method, path, status, duration и request id, без Authorization, body и query parameters. Aggregate metrics доступны через `GET /api/v1/system/metrics` с Bearer token.

Матрица публичных ошибок и retry/state-поведения находится в `docs/ERROR_MATRIX.md`; для каждого класса там указаны HTTP-поверхность, audit/state, повторный запуск и отсутствие диагностических деталей. Для production smoke используйте `.\scripts\error-contract-acceptance.ps1 -BaseUrl https://inspector.michael.kz -CompletedTaskId <completed-task-id>`; скрипт проверяет только безопасные 404/409/401-контракты и не изменяет завершённую задачу.

`POST /api/v1/patch-proposals/{id}/validate` выполняет детерминированные validation-gates: source status, unified diff, SHA snapshot, количество измененных строк и допустимое расширение файла. Approval разрешен только после `sourceValidationStatus=valid` и `validationStatus=valid`.

Approve, reject и package download требуют Bearer token. В локальном режиме `INSPECTOR_AUTH_MODE=signed` Inspector проверяет HMAC-подпись из `INSPECTOR_AUTH_SECRET`; в production режиме `INSPECTOR_AUTH_MODE=jwks` он загружает RSA-ключи из `AUTH_JWKS_URL` и проверяет `AUTH_ISSUER`, `AUTH_AUDIENCE`, expiry, subject и роли. Subject и role берутся из проверенного токена, а не из request body; роли `maintainer` и `owner` могут approve, `reviewer` может reject. Токен не выводится в UI или audit.

Approval policy учитывает environment и impact risk: `sandbox` с полностью evidenced impact доступен maintainer/owner, `test` требует owner, а любой оставшийся `candidate` требует owner. Approval также блокируется, если environment proposal не совпадает с `APP_ENVIRONMENT` backend.

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
- `/api/v1/system/metrics` для авторизованных aggregate-метрик proposal/task/tool-call/package без идентификаторов proposal и секретов.
- `POST /api/v1/tasks` с Readiness Gate и execution snapshot.
- `GET /api/v1/tasks` возвращает последние 50 задач для безопасной истории без исходного запроса и результата.
- `GET /api/v1/tasks/{task_id}` для статуса, attempt и result readiness.
- `POST /api/v1/tasks/{task_id}/cancel` для отмены queued-задачи или cooperative cancel выполняющейся задачи.
- `GET /api/v1/agents` с тремя агентами v0.1.
- React/Vite web UI на `http://localhost:5173`.
- `GET /api/v1/tasks/{task_id}/audit` для task events, tool calls и model usage.
- `GET /api/v1/tasks/{task_id}/report` для structured report и сохранённых findings.
- `GET /api/v1/tasks/{task_id}/report/export` для JSON-файла с report и audit-данными без исходного запроса.
- `POST /api/v1/projects/sync` для read-only MCP-синхронизации проектов.
- `search_code` для read-only поиска по выгруженным BSL-модулям конфигурации и `read_source` для полного текста одного модуля, если bridge настроен с `ONEC_MCP_DUMP_PATH`.

## Запуск в PowerShell

```powershell
Copy-Item .env.example .env
notepad .env
docker compose --env-file .env up --build
```

Для локального signed-режима задайте в `.env` случайный `INSPECTOR_AUTH_SECRET` длиной не менее 32 символов. При ротации сначала укажите новый current secret, старый в `INSPECTOR_AUTH_SECRET_PREVIOUS` и Unix deadline в `INSPECTOR_AUTH_SECRET_PREVIOUS_UNTIL`; после deadline удалите previous secret. Для production задайте отдельный `INSPECTOR_PACKAGE_SIGNING_SECRET`, чтобы package-подпись не зависела от auth-контура. Выберите `INSPECTOR_AUTH_MODE=jwks` и задайте `AUTH_JWKS_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE`; ключи issuer кэшируются на `AUTH_JWKS_CACHE_TTL_SEC` секунд и обновляются при смене `kid`. Inspector не выпускает внешние токены и не хранит их.

В `jwks`-режиме backend не стартует без `AUTH_JWKS_URL`, `AUTH_ISSUER`, `AUTH_AUDIENCE` и отдельного `INSPECTOR_PACKAGE_SIGNING_SECRET`. Реальный endpoint ключей можно проверить командой `.\scripts\idp-jwks-acceptance.ps1`; скрипт принимает только RSA `RS256/RS384/RS512` keys и не печатает токены.

После запуска откройте `http://localhost:5173`. Backend автоматически выполняет read-only MCP discovery с ограниченным числом повторов, поэтому после рестарта readiness восстанавливается без ручного вызова `DISCOVER MCP`; кнопка остается доступной для принудительного обновления. Панель показывает readiness, проекты из PostgreSQL, policy/toolset checksums, registry агентов и позволяет просматривать audit/report созданной task. После создания задачи UI автоматически добавляет read-only retrieval plan для выбранного агента, извлекает имя объекта вроде `Документ.ЗаказКлиента` для точного поиска, передает MCP тип объекта в формате `Document/Catalog/...`, а `1C Audit Agent` ограничивает поиск категорией и типом модуля (`Документ` + `МодульОбъекта`). Для `1C Query Agent` текст поля передается как исходный запрос 1С, а metadata retrieval использует допустимую категорию (`Документы`, `Справочники`, `РегистрыСведений`). Report details показывает `sourceCoverage`: `full`, `partial`, `none` или `unknown`, список findings/evidence, ограничения и `nextActions`; дополнительно отображаются число проверенных объектов, MCP calls, длительность tools, токены и стоимость модели, read-only/validation status. UI опрашивает статус каждые 2 секунды, показывает elapsed time и этапы `created/discovering/analyzing/reporting/completed`, предупреждает о выполнении дольше 45 секунд и загружает готовый report без ручного обновления страницы. В production frontend получает `APP_DOMAIN` и принимает запросы только для этого домена, `localhost` и `127.0.0.1`; это предотвращает ошибку Vite `Blocked request. This host is not allowed` за reverse proxy.

Frontend dependencies не коммитятся; `frontend/package-lock.json` фиксирует версии для повторяемой установки.

В report API и блоке `Execution snapshot` отображаются версии prompt, модели, policy и toolset из неизменяемого execution snapshot задачи; checksums сокращены только визуально, полный JSON доступен через `EXPORT JSON`.

Перед постановкой задачи API проверяет `project.environment` против `APP_ENVIRONMENT` и доступные capabilities выбранного агента. Несовпадение окружения или неполный read-only toolset создаёт terminal blocked task с событием `task_blocked`, стабильным кодом ошибки и нулевым числом MCP calls; `staging` и `production` не допускаются в v0.1.

При cooperative cancel worker проверяет флаг перед каждым новым retrieval tool call, обновляет heartbeat, сохраняет уже завершённые calls и переводит задачу в `cancelled` до запуска следующего MCP-вызова или модели. Terminal-задачи освобождают worker lease; зависшая задача в `discovering`, `analyzing` или `reporting` возвращается в `created` с событиями `task_status_changed`, `task_recovered` и кодом `WORKER_LEASE_EXPIRED`. Каждый фактический retrieval call сохраняется сразу после ответа MCP; при recovery совпадающий завершённый вызов переиспользуется по fingerprint `tool + arguments`, но только для idempotent contract, поэтому повторный MCP-вызов не выполняется.

Worker поддерживает heartbeat отдельным циклом с интервалом `WORKER_HEARTBEAT_INTERVAL_SEC` во время MCP retrieval и вызова модели; Compose передаёт эту настройку только worker-контейнеру, а значение должно быть меньше `WORKER_LEASE_TIMEOUT_SEC`, иначе backend не стартует. Каждая задача получает уникальный lease owner: после recovery старый worker не может обновить heartbeat, сохранить tool call или записать report поверх нового владельца. `TASK_TIMEOUT_SEC` задаёт общий deadline выполнения от claim до report: MCP-вызов получает минимум из contract `timeout_sec` и оставшегося времени задачи, модель получает тот же остаток. Истечение deadline сохраняется как стабильная ошибка `TASK_TIMEOUT` без автоматического повтора.

Если задача завершилась со статусом `failed` или отчёт не получил исходный модуль, обновите состояние панели и создайте новую задачу. Для аудита выбирайте `1C Audit Agent`; UI не отправляет явный audit-запрос с другим профилем, чтобы не получить нерелевантный read-only контекст.

Object-aware audit распознаёт русские формы объектов (`документ`, `документа`, `справочник`, `регистр`) и извлекает имя вроде `ЗаказКлиента` перед построением точного retrieval plan.

Блок `История задач` свернут по умолчанию, но последняя задача остается видимой; кнопка `ПОКАЗАТЬ ВСЕ` раскрывает полный список, а `СВЕРНУТЬ` возвращает компактное состояние. В раскрытом списке доступны фильтры по статусу и агенту, счетчик показывает число видимых задач. Выбор любой задачи повторно загружает её статус, audit и report. В `TASK MONITOR` кнопка `ОТМЕНИТЬ` запрашивает безопасную отмену задачи в `created`, `discovering`, `analyzing` или `reporting`; состояние `ОТМЕНА ЗАПРОШЕНА` означает, что текущий MCP-вызов завершится, но новые этапы не начнутся. `Execution audit` показывает attempt, cancel state, список фактических MCP tool calls с режимом, статусом, длительностью и безопасным кодом ошибки. Кнопка `LOAD REPORT` показывает состояние загрузки и загружает подробный human-readable report. `ПОКАЗАТЬ JSON` отображает на странице канонический machine payload `report + audit`, а `EXPORT JSON` скачивает тот же результат файлом. Экспорт отчёта и proposal package использует отложенное освобождение browser download URL, а ошибки API нормализуются в пользовательские сообщения без raw stack trace и внутренних деталей. Поля `persistedFindings` берутся из сохранённых записей PostgreSQL, поэтому UI показывает канонический результат после worker, а не только исходный ответ модели.

Проверка:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/system/readiness
Invoke-RestMethod http://localhost:8000/api/v1/system/policy
Invoke-RestMethod http://localhost:8000/api/v1/system/ready
```

Статическую acceptance-проверку можно запустить без поднятия контейнеров: `.\scripts\acceptance.ps1 -SkipDockerRuntime`. Полная проверка дополнительно требует доступный Docker Engine и выполняет backend health smoke test. Offline acceptance-тест отдельно проходит mock MCP -> project sync -> retrieval -> report контур и не заменяет live EDT/MODEL E2E.
Live acceptance после настройки `.env` запускается командой `.\scripts\live-acceptance.ps1`; для оставления контейнеров работающими используйте `-KeepRunning`. Скрипт проверяет Docker, backend health, diagnostics, MCP health/discovery, bridge tool smoke call и project sync, а при placeholder-конфигурации перечисляет все отсутствующие ключи. Docker preflight завершается с timeout, если daemon не отвечает.
При `MCP_TRANSPORT=bridge` значение `MCP_SERVER_URL` должно быть доступно из backend/worker-контейнеров: для bridge на Windows host используйте `http://host.docker.internal:<port>`, а не `127.0.0.1`; `MCP_LIVE_PROBE_URL` используется только host-side smoke probe. Production E2E проверяет три read-only профиля через `v01-acceptance.ps1`: Code Assistant, Query Agent и Audit Agent.
Финальную приемку v0.1 с проверкой готовности, project sync, read-only toolset и конкретных task reports запускайте так:

```powershell
.\scripts\v01-acceptance.ps1 `
  -CodeTaskId <code-task-id> `
  -QueryTaskId <query-task-id> `
  -AuditTaskId <audit-task-id>
```

Скрипт отклоняет `execute_query`, write tools и findings без evidence.

Единый UAT для трёх production-задач запускается после создания Code Assistant, Query Agent и Audit Agent задач:

```powershell
.\scripts\v07-uat.ps1 `
  -BaseUrl https://inspector.michael.kz `
  -CodeTaskId <code-task-id> `
  -QueryTaskId <query-task-id> `
  -AuditTaskId <audit-task-id>
```

Скрипт дополнительно сверяет report с `persistedFindings`, проверяет model/tool audit и наличие evidence у каждого сохраненного finding.

Финальную приемку v0.2 Patch Planner запускайте при работающем Compose:

```powershell
.\scripts\v02-acceptance.ps1 `
  -OwnerToken <owner-token> `
  -TaskId <completed-task-id> `
  -FindingId <persisted-finding-id> `
  -GitCommit <full-commit-sha> `
  -GitPath CommonModules/AcceptanceSmoke.bsl
```

Backend должен быть запущен с `docker-compose.patch-git.yml`, а `GitPath` должен существовать в указанном commit. Скрипт проверяет полный контур `completed task/finding -> persisted read_source -> diff -> source revalidation -> Git checkpoint -> validation -> owner approval -> signed package -> manual handoff -> audit`. В конце он проверяет OpenAPI и отклоняет релиз, если появился `/apply`; Git, workspace и конфигурация 1С не изменяются.

Финальную приемку v0.3 запускайте при работающем Compose:

```powershell
.\scripts\v03-acceptance.ps1 -AuthToken <signed-token>
```

Скрипт проверяет read-only impact evidence, source revalidation, validation-gates, checkpoint, role policy, ZIP package и полный audit log. Весь контур остается proposal-only.

Финальную приемку v0.4 запускайте при работающем Compose с двумя signed tokens:

```powershell
.\scripts\v04-acceptance.ps1 -AuthToken <maintainer-token> -OwnerToken <owner-token>
```

Скрипт проверяет signed auth, автоматический MCP evidence, policy для candidate risk, signed package и server-side verify. Токены и секреты не печатаются.

Финальную приемку v0.5 запускайте при работающем Compose с maintainer и owner tokens:

```powershell
.\scripts\v05-acceptance.ps1 -AuthToken <maintainer-token> -OwnerToken <owner-token>
```

Скрипт проверяет auth, automatic MCP evidence, immutable package version `1`, explicit version download, metrics authorization, final-state conflict и owner-only candidate policy. Он не применяет diff и не меняет конфигурацию 1С.

Live-проверка именно EDT MCP запускается так:

```powershell
.\scripts\edt-live-acceptance.ps1
```

Скрипт проверяет MCP initialize, discovery фактического `MCP_PATCH_SEARCH_TOOL`, режим `read-only`/категорию `code.search`, project sync и evidence через `impact/mcp`. Он создает только proposal-only данные.

Production deployment использует override `docker-compose.production.yml`: PostgreSQL не публикуется наружу, backend/frontend доступны только внутри Compose для reverse proxy, а сервисы имеют `restart: unless-stopped`. Для постоянного Keycloak добавьте `docker-compose.keycloak.production.yml`: он использует отдельные PostgreSQL/Keycloak volumes и `start`, а не `start-dev`. Edge-профиль `docker-compose.edge.production.yml` добавляет Caddy на 80/443, автоматический HTTPS и reverse proxy для `APP_DOMAIN` и `IDP_DOMAIN`; `/openapi.json` направляется в backend с `Cache-Control: no-store`, чтобы release gate проверял текущую API-схему. Перед запуском настройте DNS, выполните `.\scripts\production-preflight.ps1 -WithKeycloak -WithEdge`, затем `docker compose --env-file .env -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.keycloak.production.yml -f docker-compose.edge.production.yml up --build -d`.

Перед production-деплоем проверяйте секреты без вывода их значений: `.\scripts\production-secrets-audit.ps1 -EnvFile .env -WithKeycloak`. На VPS используется `WITH_KEYCLOAK=1 /opt/1c-ai-inspector/infra/ops/audit-secrets.sh`; скрипты проверяют отсутствие placeholder-значений, минимальную длину и дублирование секретов, но не выполняют ротацию автоматически.

Резервная копия PostgreSQL в Windows: `.\scripts\backup.ps1 -OutputDirectory .\backups`. Для production Linux используйте `infra/ops/backup-postgres.sh`: он создает custom-format dump для application PostgreSQL и Keycloak, проверяет каждый dump через `pg_restore --list` внутри соответствующего контейнера, удаляет незавершенные `.tmp`-файлы при завершении и хранит только dump-файлы не старше `KEEP_DAYS` (по умолчанию 14) в `/var/backups/1c-ai-inspector`. Unit `infra/ops/1c-ai-inspector-backup.timer` запускает этот backup ежедневно в 03:30 UTC. Восстановление намеренно требует явного подтверждения: `.\scripts\restore.ps1 -BackupFile .\backups\<file>.dump -ConfirmRestore`.

Для локального production-like smoke, если 80/443 заняты, задайте временные `CADDY_HTTP_PORT` и `CADDY_HTTPS_PORT` и добавьте `docker-compose.edge.local.yml`; этот override использует `tls internal` для тестовых доменов. Production defaults остаются 80/443 и публичный ACME/TLS из `docker-compose.edge.production.yml`.

Production PostgreSQL проходит всю Alembic-цепочку на чистой базе; foundation revision явно откладывает поля, принадлежащие последующим column migrations, поэтому clean install не получает повторное `ADD COLUMN`. `migrate` повторяет запуск до пяти раз только при transient startup race. Compose-override закрывает базовый `5432`, а edge-override оставляет backend/frontend/Keycloak доступными только внутри сети.

Security/load smoke запускается командой `.\scripts\security-load-acceptance.ps1 -Count 20`. Он проверяет security headers, auth на metrics, наличие report-to-patch/Git/handoff маршрутов, отсутствие `/apply`, отсутствие `write` и `conditional-write` tools в policy, non-root backend и параллельные health requests. API отклоняет запросы больше `MAX_REQUEST_BYTES` с `413 REQUEST_TOO_LARGE`.

Единый production acceptance запускается после создания трех завершенных read-only задач:

```powershell
.\scripts\final-production-acceptance.ps1 `
  -BaseUrl https://inspector.michael.kz `
  -CodeTaskId <code-task-id> `
  -QueryTaskId <query-task-id> `
  -AuditTaskId <audit-task-id> `
  -LoadCount 20
```

После backup выполните на VPS `bash infra/ops/restore-drill.sh`. Скрипт берет свежие dump-файлы application PostgreSQL и Keycloak, восстанавливает их в одноразовые контейнеры `postgres:16-alpine` и удаляет контейнеры после проверки; рабочие базы и сервисы не изменяются. Максимальный возраст dump задается `MAX_AGE_HOURS` (по умолчанию 48). Последний подтверждённый restore drill и production UAT зафиксированы в [`docs/PRODUCTION_ACCEPTANCE.md`](docs/PRODUCTION_ACCEPTANCE.md).

Единый production release acceptance текущего контура запускается после создания трех завершенных read-only задач:

```powershell
.\scripts\final-production-acceptance.ps1 `
  -BaseUrl https://inspector.michael.kz `
  -CodeTaskId <code-task-id> `
  -QueryTaskId <query-task-id> `
  -AuditTaskId <audit-task-id> `
  -LoadCount 20
```

Сценарий проверяет production monitor, безопасные error contracts, v0.7 UAT для трех агентов и security/load smoke. Он не считает release принятым без реального внешнего IdP/JWKS, readiness, read-only MCP calls и persisted evidence.

Единый UAT/release acceptance запускается командой `.\scripts\release-acceptance.ps1 -KeepRunning`. Он проверяет реальный локальный Keycloak JWT flow, EDT MCP evidence, security/load smoke и PostgreSQL backup. Для EDT-проверки предусмотрены до трех попыток на случай краткого таймаута bridge. Для production env-файла добавьте `-ProductionEnvFile C:\path\to\production.env`; preflight проверит persistent Keycloak и Caddy edge, но не запускает production без явной команды Compose.

Для тестовой среды с локальным IdP используйте Keycloak:

```powershell
.\scripts\keycloak-acceptance.ps1 -Build -KeepRunning
```

Скрипт поднимает Keycloak на `http://127.0.0.1:8081`, импортирует realm `inspector`, создает временных пользователей с ролями `maintainer` и `owner`, подключает backend к внутреннему JWKS URL и выполняет реальный JWT approval flow. `-Build` нужен только после изменения образов; при повторном запуске достаточно `.\scripts\keycloak-acceptance.ps1 -KeepRunning`. Пароли и package secret генерируются только в памяти процесса; конфигурация 1С не меняется. Для остановки: `docker compose --env-file .env -f docker-compose.yml -f docker-compose.keycloak.yml down`.

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

MCP discovery получает `tools/list`, принимает только инструменты, перечисленные в policy, сохраняет нормализованный snapshot в PostgreSQL и отправляет на MCP Server исходное имя инструмента. Неизвестные инструменты отклоняются до сетевого запроса. Readiness становится `ready` только после успешного discovery и покрытия capabilities всех трёх агентов; policy без реальных EDT tool names остаётся `NOT READY`. PostgreSQL создаёт отдельные migration/runtime роли и default privileges для runtime-запросов. Новые таблицы по умолчанию доступны runtime только для `SELECT/INSERT`; `task_events`, `tool_calls`, `findings`, `finding_status_events`, `model_usage` и `prompt_execution_snapshots` дополнительно защищены от `UPDATE/DELETE` на уровне роли и остаются append-only для приложения.

Task Orchestrator не создаёт агентную задачу, если toolset не готов: API возвращает `409 AGENT_TOOLSET_NOT_READY`. При успешном создании сначала сохраняется строка task со статусом `created`, затем связанный execution snapshot и событие создания. Worker атомарно захватывает задачу и проводит её только по state machine `created → discovering → analyzing → reporting → completed`; из каждой активной фазы разрешены `failed` и `cancelled`. Каждый переход сохраняется отдельным событием `task_status_changed`. Legacy-статусы `queued/running` принимаются только для безопасного завершения или recovery задач, созданных до обновления. Сохраняются state, policy checksum, toolset checksum, prompt version и model snapshot.

Отмена задачи не прерывает уже выполняющийся HTTP-вызов MCP или модель принудительно, но общий deadline ограничивает их длительность. API сохраняет `cancel_requested`, worker проверяет флаг перед retrieval, сохранением tool calls и вызовом модели, после чего переводит задачу в `cancelled` и пишет audit event. При истечении deadline worker переводит задачу в `failed`, сохраняет `TASK_TIMEOUT` и не запускает следующий этап. Завершённые и failed-задачи повторно отменить нельзя.

Синхронизация проектов включается только при заданном `MCP_PROJECTS_TOOL`. Для MCP-сервера, который возвращает список проектов, укажите его read-only tool name. Для текущего локального `mcp-1c` используйте `MCP_PROJECTS_TOOL=get_configuration_info`: Inspector создаёт одну карточку проекта из фактов конфигурации 1С и capabilities активной policy. Имя должно быть опубликовано в `mcp_policy.yaml`; иначе вызов блокируется до сетевого запроса.

Patch Planner в v0.4 сохраняет proposal-only режим: после создания diff нужно выполнить source revalidation, read-only impact evidence и validation gates, затем можно создать signed package и пройти approval policy. Ни один endpoint этого среза не применяет код, не меняет конфигурацию 1С и не создает Git-коммиты.

Signed-режим оставлен для локальной разработки. Для production используйте внешний IdP или корпоративный gateway в режиме JWKS; Inspector принимает только JWT с поддержанным RSA-алгоритмом и проверяет подпись до извлечения роли.

Agent retrieval принимает только явный `request.retrieval` plan. Каждый шаг проверяется по опубликованному read-only tool и capability конкретного агента, результат маркируется как untrusted MCP context, а вызов попадает в `tool_calls` audit. Для object-aware `search_code` backend оставляет в контексте только совпадающие заголовки модулей, чтобы большой результат поиска не вытеснял полезный код за пределы model context.
Количество retrieval calls ограничивается `MAX_TOOL_CALLS` до первого сетевого вызова. Каждый ответ MCP ограничивается `MAX_RESULT_CHARS` до compacting и записи в context/audit; слишком большой ответ завершается с `MCP_RESULT_TOO_LARGE` без сохранения содержимого, а исходный размер сохраняется в audit как `resultSizeChars`. Итоговый StructuredReport ограничен `MAX_FINDINGS`; превышение фиксируется как `FINDINGS_LIMIT_EXCEEDED`. Так как текущий read-only `read_source` читает один модуль целиком и не принимает имя метода, `MAX_METHODS_READ` ограничивает число таких module reads в одной задаче; per-method limit потребует отдельного MCP tool contract.
Даже failed MCP calls сохраняются в `tool_calls` с `status=failed` и безопасным `errorCode`.
Для read-only tools policy может задать ограниченное число повторов через `retries`; повторяются только transport/HTTP ошибки.

MCP connector использует Streamable HTTP session lifecycle: `initialize`, `notifications/initialized`, `Mcp-Session-Id`, `MCP-Protocol-Version`, повторное использование клиента и уникальные JSON-RPC request ids с проверкой response id. Ответы JSON и `text/event-stream` поддерживаются; project sync принимает list и вложенный `{projects: [...]}`.
MCP connector также принимает deadline родительской задачи и не повторяет вызов после `TASK_TIMEOUT`.

Для `sales-ai-manager/onec-mcp-bridge` доступен режим `MCP_TRANSPORT=bridge`: Inspector вызывает bridge endpoints `/health`, `/tools`, `/tools/call` и передаёт `MCP_BRIDGE_TOKEN` как Bearer token. Raw MCP режим остаётся `MCP_TRANSPORT=streamable-http`.

Текущая bridge policy версии `1.1.0` публикует только фактически доступные read-only tools: syntax help, configuration info, event log, form/metadata/object structure, code search, full source retrieval и query validation. `execute_query` намеренно не публикуется. `search_code` и `read_source` работают по отдельной read-only выгрузке конфигурации через `DumpConfigToFiles` и не требуют изменения конфигурации 1С. При заданных category/module Inspector дополнительно оставляет в поисковом контексте только секции целевого объекта и модуля, чтобы findings не строились по чужому документу. Для полного исходника агенту передаётся точный лимит строк каждого модуля. Сервер проверяет модуль и диапазон строк по полному `read_source`; неподтверждённые диапазоны исключаются из отчёта, а неподтверждённые excerpts удаляются при сохранении проверенного диапазона. Все такие случаи отражаются в `limitations`, поэтому неподтверждённый finding не сохраняется. Без успешного discovery Code Assistant и Audit Agent по-прежнему блокируются readiness gate. Если полный источник недоступен, отчет явно показывает `sourceCoverage=partial` или `none`.

При повторном discovery отсутствующие на MCP инструменты получают статус `retired` в `normalized_tools`, поэтому старые capabilities не остаются активными в базе.

Model adapter принимает JSON string, content blocks и JSON в markdown fence, после чего всё равно валидирует ответ как `StructuredReport`. Для аудита он сохраняет только SHA-256 `responseChecksum` ответа модели в `model_usage`; содержимое ответа в audit не записывается.
Model adapter использует оставшееся время общего task deadline и не отправляет запрос при уже истёкшем deadline. `MODEL_RETRIES` ограничивает повторы модели от `0` до `3`: повторяются только timeout, transport и transient HTTP `408/409/425/429/5xx`; невалидный JSON и невалидный StructuredReport не повторяются.
Для моделей GPT-5 адаптер не передаёт `temperature=0`, потому что эти модели принимают только значение по умолчанию; для остальных OpenAI-compatible моделей сохраняется детерминированный `temperature=0`.
Agent prompt получает фактическую JSON Schema `StructuredReport`, но итоговый ответ всё равно проверяется сервером перед сохранением task и findings.
Telemetry в `StructuredReport` не доверяет значениям модели: model usage берётся из adapter, а tool usage — из фактически записанных retrieval calls и их длительности.

Live-проверка Query Agent подтверждена на подключенной базе: `validate_query` проверил запрос без выполнения данных, `get_metadata_tree` подтвердил наличие справочника, а итоговый report сохранил validation, audit и фактическое model/tool usage.
Live-проверка Audit Agent также подтверждена: read-only поиск кода и чтение структуры документа сформировали findings с evidence, а те же findings были сохранены в PostgreSQL и доступны через report endpoint.

Агенты v0.1: `1c_code_assistant`, `1c_query_agent`, `1c_audit_agent`. Structured report требует непустой `evidence` для каждого finding и ссылку на объект 1С.

Стоимость модели считается только по явно заданным `MODEL_INPUT_COST_PER_1K` и `MODEL_OUTPUT_COST_PER_1K`; значения `0` по умолчанию не маскируют неизвестные тарифы. Model adapter отдельно сохраняет `cachedInputTokens`, имя модели и длительность запроса, а `pricingSource=environment` показывает, что тарифы взяты из этих environment-настроек. Audit endpoint возвращает длительность и статусы tool calls, длительность model call, размеры результатов, токены, стоимость, источник тарифа и checksum ответа модели без раскрытия самого ответа. Report endpoint обогащает исторические отчёты теми же значениями из append-only `model_usage`.

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
Production monitor проверяет health, security headers, readiness, policy, наличие минимум 8 MCP tools, синхронизированные проекты и отсутствие исходного запроса/результата в истории. Windows: .\scripts\production-monitor.ps1 -BaseUrl https://inspector.michael.kz. VPS: BASE_URL=https://inspector.michael.kz /opt/1c-ai-inspector/infra/ops/monitor.sh. Финальная acceptance-проверка выполняется единым `scripts/final-production-acceptance.ps1`, затем запускаются `infra/ops/backup-postgres.sh` и `infra/ops/restore-drill.sh`.
