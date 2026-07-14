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

Windows MCP continuity evidence:

- `SalesAiManager-1C-MCP-Bridge` runs at Windows boot under `SYSTEM` and remains active while the bridge process is serving port `8091`;
- duplicate bridge and Tunnel logon tasks are disabled after their XML definitions were backed up locally;
- authenticated local and external bridge health checks both returned HTTP `200` after the scheduled bridge restart;
- `sales-ai-onec-mcp-cloudflared` is running with Docker restart policy `unless-stopped`, and Docker Desktop is enabled in the Windows Startup registry and application settings.

MCP bridge secret rotation evidence:

- `scripts/rotate-mcp-bridge-token.ps1` rotated the Windows `ONEC_MCP_BRIDGE_TOKEN` and production `MCP_BRIDGE_TOKEN` as one fail-safe operation on 2026-07-14;
- backend and worker were recreated without changing the remaining production stack, and the Windows boot task was restarted;
- the new token returned HTTP `200` from both local and external bridge health endpoints, while the retired token returned `401`/`403`;
- the post-rotation production monitor returned health `ok`, readiness `ready`, 9 MCP tools and 1 project;
- the production secret audit passed without printing values, and root-only pre-rotation env snapshots remain in `/var/backups/1c-ai-inspector`;
- the current token was written only to `D:\пароль.txt`, whose ACL contains three explicit full-control rules for the current Windows user, `SYSTEM` and built-in administrators, with no inherited rules.

Off-site backup evidence:

- `scripts/download-production-backups.ps1` downloaded the latest application and Keycloak dumps to `D:\Backups\1c-ai-inspector`;
- both downloaded files matched the SHA-256 values calculated on the VPS, and no remote staging files remained;
- `last-success.json` records the verified filenames, hashes, sizes and UTC completion time without storing credentials;
- Windows task `OneCAIInspector-OffsiteBackup` completed manually with result `0x00000000` and is scheduled daily at 09:00 with `StartWhenAvailable` and three retries.
- Cloudflare R2 bucket `onec-ai-inspector-backups` was created in `EEUR` with Standard storage; `r2.dev` is disabled and no custom domain is connected;
- lifecycle rule `expire-production-backups` expires the `production/` prefix after 30 days, while incomplete multipart uploads expire after 7 days;
- the full VPS -> local disk -> R2 pipeline uploaded the latest application and Keycloak dumps, downloaded both objects again and matched their SHA-256 values;
- Windows task `OneCAIInspector-OffsiteBackup` now runs `scripts/offsite-production-backup.ps1`, not the download-only stage; its previous XML definition is retained under `C:\tools\task-backups`;
- SSH/SCP calls are non-interactive and use bounded connection attempts plus keepalive failure detection so the scheduled pipeline fails instead of hanging indefinitely.

Production checkout evidence:

- the active checkout was fast-forwarded to deployed release `911c050cee558032962c290d826d37db02e1034c` without deleting local environment or operational files;
- 188 of 189 previous release files matched `d15bc5b` after BOM/CRLF normalization; the only substantive difference was the already accepted restore-drill fix;
- root-only backup `production-checkout-pre-sync-20260714T130857Z.tar.gz` was created before synchronization;
- all tracked files now equal the exact release blobs, `git status` is clean and `git fsck` passes;
- `/opt/1c-ai-inspector` and its Git metadata are owned by `root:root` with mode `755`, `.env` has mode `600`, and no checkout entry is writable by group or other users;
- production container identities remained unchanged during normalization, and the external production monitor remained green.

Full-source retrieval evidence:

- production task `tsk_f56e0327aad845b48142ac33f38533ac` was created through an intentionally stale retrieval plan that omitted `read_source`;
- backend normalization inserted the mandatory full-source step and the completed execution called `read_source`, `bsl_syntax_help` and `search_code` in that order;
- the report recorded `sourceCoverage=full`, returned three persisted findings and located the requested `ОбработкаЗаполнения` procedure;
- this confirms that object-aware Code Assistant and Audit Agent requests cannot silently degrade to fragment-only analysis when submitted by an old frontend or external API client.

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
