# Production acceptance record

## 2026-07-14

Environment: `https://inspector.michael.kz`

Deployed application commits:

- `833aeda` — v0.1 task lifecycle `created -> discovering -> analyzing -> reporting -> completed`;
- `724d07c` — machine JSON report viewer;
- `d15bc5b` — current application release during the final production and SSH hardening checks.

Database recovery evidence:

- application backup: `inspector-postgres-20260714T122258Z.dump`;
- Keycloak backup: `inspector-keycloak-20260714T122303Z.dump`;
- both dumps restored successfully by `infra/ops/restore-drill.sh` into disposable `postgres:16-alpine` containers;
- the drill waited for the final PostgreSQL server after the image init phase, avoiding the transient `pg_isready` window before the normal init restart;
- an intentionally invalid dump failed as expected and its disposable container was removed by the same EXIT cleanup path;
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

SSH hardening evidence:

- key-only login for `inspector-admin` and passwordless administrative commands through `sudo` were verified in a separate SSH session;
- effective `sshd -T` values are `permitrootlogin no`, `passwordauthentication no`, `kbdinteractiveauthentication no` and `pubkeyauthentication yes`;
- direct `root` login with the previously valid production key is rejected;
- `ssh.service` remained active after configuration validation and reload;
- emergency recovery remains available through the Contabo console/VNC and must be used only if key-based access is lost.

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

## Patch Planner v0.2 release gate

Release scope commits: `1b22b6c` through `d56e41c`, plus the acceptance/documentation commit that contains this section.

Required evidence before and after deployment:

- full backend suite and frontend production build pass;
- a fresh PostgreSQL volume completes the full Alembic chain without duplicate-column errors;
- `scripts/v02-acceptance.ps1` passes against a backend with an operator-mounted read-only Git repository;
- Git working tree status is unchanged by checkpoint verification;
- production OpenAPI contains `from-finding`, `revalidate/from-task`, `checkpoint/git` and `handoff`;
- production OpenAPI contains no `/apply` route;
- production policy contains no `write` or `conditional-write` tools;
- production monitor, three-agent UAT and 20-request security/load smoke remain green.

The production instance does not claim a successful Git checkpoint unless `PATCH_GIT_REPOSITORY` is mounted. Without that mount, the endpoint must return `PATCH_GIT_REPOSITORY_NOT_CONFIGURED`; this is the intended fail-closed behavior, not an applied patch.
