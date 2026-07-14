# Production acceptance record

## 2026-07-14

Environment: `https://inspector.michael.kz`

Deployed application commits:

- `833aeda` — v0.1 task lifecycle `created -> discovering -> analyzing -> reporting -> completed`;
- `724d07c` — machine JSON report viewer.

Database recovery evidence:

- application backup: `inspector-postgres-20260714T054036Z.dump`;
- Keycloak backup: `inspector-keycloak-20260714T054038Z.dump`;
- both dumps restored successfully by `infra/ops/restore-drill.sh` into disposable `postgres:16-alpine` containers;
- production PostgreSQL, Keycloak and their volumes were not modified by the drill.

State machine evidence:

- task: `tsk_d57deee6ca084726a01109f516b5f782`;
- initial API status: `created`;
- persisted audit transitions: `created -> discovering -> analyzing -> reporting -> completed`;
- exported machine payload contained report, audit and prompt/model/policy/toolset execution versions.

Final acceptance evidence:

- production monitor: health `ok`, readiness `ready`, 9 MCP tools, 1 project;
- error contracts and safe task history: passed;
- Code Assistant: passed, 2 read-only calls, 3 findings;
- Query Agent: passed, 2 read-only calls;
- Audit Agent: passed, 3 read-only calls, 4 persisted findings;
- security/load: passed, including protected metrics, non-root backend and 20 concurrent health requests.

Commands used:

```powershell
.\scripts\production-monitor.ps1 -BaseUrl https://inspector.michael.kz
.\scripts\final-production-acceptance.ps1 -BaseUrl https://inspector.michael.kz `
  -CodeTaskId tsk_d57deee6ca084726a01109f516b5f782 `
  -QueryTaskId tsk_b37b085a2dd74c0e87788e559e39e23b `
  -AuditTaskId tsk_53a96d3db88d4e37bbc78735ca3669df `
  -LoadCount 20
```

```bash
bash infra/ops/backup-postgres.sh
bash infra/ops/restore-drill.sh
```
