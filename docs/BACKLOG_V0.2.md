# Backlog v0.2

1C AI Inspector - Patch Planner

Цель релиза: на основании сохраненного read-only отчета и исходного BSL-кода подготовить проверяемое предложение изменения, связать его с неизменяемой Git revision, провести impact analysis и передать подписанный пакет оператору для ручного применения.

Статус реализации: все пункты Definition of Done покрыты backend tests, frontend build и `scripts/v02-acceptance.ps1`. Production release дополнительно обязан пройти `scripts/final-production-acceptance.ps1`; без read-only Git mount production сохраняет fail-closed режим для Git checkpoint.

## Definition of Done

Релиз v0.2 считается готовым, если пользователь может:

1. выбрать finding из завершенной задачи и создать patch proposal без ручного копирования исходного BSL-кода;
2. увидеть исходный snapshot, proposed source, unified diff и SHA-256 каждого файла;
3. получить read-only impact evidence и детерминированный результат validation gates;
4. привязать proposal к существующему immutable Git commit и получить проверенный checkpoint;
5. approve или reject proposal только с проверенной ролью и обязательным audit trail;
6. сформировать, скачать и проверить подписанный immutable ZIP-пакет;
7. создать ручной handoff с версией и SHA-256 пакета, не применяя diff внутри Inspector;
8. подтвердить тестами и production smoke, что API, worker и MCP не выполняют write или conditional-write операции.

## EPIC 1. Proposal из отчета

- Источник proposal - завершенная задача и сохраненный finding.
- Original source берется только из сохраненного успешного read-only `read_source` tool call этой задачи.
- Пользователь задает proposed source и относительный путь BSL; backend проверяет принадлежность finding задаче и соответствие исходного модуля.
- В audit сохраняются идентификаторы задачи, finding и source module, но не Bearer token.

## EPIC 2. Git checkpoint

- Git repository задается оператором через серверную конфигурацию и открывается только для чтения.
- Revision разрешается в полный commit SHA; произвольный filesystem path из запроса запрещен.
- Каждый изменяемый путь должен существовать в выбранном commit.
- Отсутствующий repository, revision или path блокирует checkpoint безопасной публичной ошибкой.
- Inspector не создает branch, commit, tag и не изменяет index или working tree.

## EPIC 3. Approval и ручной handoff

- Approval следует environment/impact role policy.
- Handoff доступен только для approved proposal и существующей проверяемой версии signed package.
- Handoff фиксирует package version, package SHA-256, target environment, actor и timestamp.
- Handoff означает только передачу пакета оператору; `applied` остается `false`.

## EPIC 4. Приемка и безопасность

- Backend tests покрывают source provenance, Git checkpoint, role policy, package integrity и handoff audit.
- Frontend build подтверждает report-to-proposal и ручной handoff workflow.
- Acceptance подтверждает отсутствие apply endpoint и write tools.
- README, Security Model, Architecture и Known Limitations соответствуют фактическому поведению.

## Не входит в v0.2

- запись BSL в EDT workspace или конфигурацию 1С;
- создание Git branch/commit или изменение working tree;
- обновление тестовой базы;
- запуск write/conditional-write MCP tools;
- автоматическое применение или rollback.

Эти операции относятся к v0.3 Sandbox Executor и требуют отдельного write policy, sandbox branch, EDT validation, тестовой базы, rollback и awaiting-acceptance state.
