# Backlog v0.3

1C AI Inspector - Sandbox Executor

Цель релиза: контролируемо применить одобренный подписанный Patch Planner package только в одноразовый Git worktree, выполнить оператором настроенные EDT validation и тесты, а затем передать результат в `awaiting_acceptance` либо гарантированно очистить sandbox через rollback.

## Definition of Done

Релиз v0.3 считается готовым, если:

1. Sandbox Executor регистрируется только при `SANDBOX_EXECUTOR_ENABLED=true`; production по умолчанию не публикует write routes.
2. Execution создается только из `approved` proposal и проверенной immutable package version с совпадающим SHA-256.
3. Source repository и sandbox root задаются оператором, а не HTTP-запросом; оба пути проверяются до записи.
4. Для execution создается отдельный Git worktree и уникальная ветка от подтвержденного immutable commit.
5. Signed diff проходит `git apply --check` и применяется только внутри созданного worktree; основной repository и 1С не изменяются.
6. EDT validation/build запускается только через фиксированную операторскую команду с ограничением времени и размера результата.
7. Тестовая stage запускается только через отдельную фиксированную команду; успешный результат переводит execution в `awaiting_acceptance`.
8. Ошибка apply, validation или tests переводит execution в `rollback_required`; rollback удаляет worktree и sandbox branch и сохраняет audit event.
9. Только verified owner может запускать apply и rollback; identity из body не принимается.
10. Каждый переход состояния и side effect записывается append-only; токены, package bytes и полный command output в event не попадают.
11. Production acceptance подтверждает, что при выключенном feature flag `/api/v1/sandbox-executions` и write/apply routes отсутствуют.

## State machine

```text
created
-> preparing
-> prepared
-> applying
-> validating
-> testing
-> awaiting_acceptance

failure -> rollback_required -> rolling_back -> rolled_back
```

Terminal `failed` разрешен только если sandbox не был создан. После первого filesystem side effect любая ошибка обязана пройти через `rollback_required`.

## Trust boundary

- Browser передает только execution/proposal identifiers и operator note.
- Backend повторно проверяет owner role, proposal status, package signature/hash, commit и state transition.
- Source repository и sandbox root не принимаются из HTTP.
- Validation/test commands задаются environment variables и не дополняются пользовательскими аргументами.
- Write-capable MCP tools в v0.3 не публикуются; изменения выполняются локальным sandbox adapter.
- `InfoBase1`, production repository, staging и production deployment не входят в этот релиз.

## Не входит в v0.3

- merge sandbox branch;
- push branch в remote;
- запись в рабочую или production конфигурацию 1С;
- staging/production deployment;
- принятие результата без ручного owner acceptance;
- произвольные shell-команды из API;
- автоматическое исправление validation/test failures.
