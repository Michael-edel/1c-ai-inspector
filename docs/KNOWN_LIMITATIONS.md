# Known Limitations

## Read-only scope

- The platform does not change 1C configuration, execute `execute_query`, apply BSL, update a test database, create Git branches or deploy artifacts.
- Patch Planner remains proposal-only. Checkpoints, approvals, packages and manual handoff records describe a possible change; `applied` remains `false`. Controlled apply is deferred to v0.3 Sandbox Executor.
- Only `sandbox` and `test` environments are allowed in v0.1. Staging and production execution are blocked by policy.

## Source and MCP data

- The current bridge retrieves BSL from a separate read-only dump and does not require changing the 1C configuration.
- `read_source` reads one module as a whole. `MAX_METHODS_READ` therefore limits module reads; a true per-method limit requires an MCP contract that accepts a method selector.
- If a full source module is unavailable, the report is marked `sourceCoverage=partial` or `none`; the audit agent must not invent source evidence.
- Search results are narrowed to the requested object/module, but the quality of findings still depends on the source returned by MCP and the model response.

## Execution and model behavior

- Cancellation is cooperative. An already-running MCP or model HTTP request is not forcefully terminated; the task deadline bounds the remaining work.
- Model cost is an estimate from `MODEL_INPUT_COST_PER_1K` and `MODEL_OUTPUT_COST_PER_1K`. A zero tariff means unknown cost, not free usage.
- Cached input tokens are recorded when the provider returns them. Existing usage rows are not backfilled.
- Model duration is measured around the adapter request and existing usage rows receive a zero migration default.
- Model response checksums, cached token counts, pricing source and duration are recorded for new executions; report responses backfill model usage fields from the audit row, while historical rows may still have null or default values for fields introduced by earlier migrations.
- The runtime audit protection is database-role based. Cryptographic chained audit immutability and external WORM storage are outside v0.1.

## Identity and tenancy

- Production requires an external JWKS-compatible IdP or the deployed Keycloak test IdP; local signed auth is not a production identity service.
- Enterprise RBAC, multi-tenancy, billing, Telegram, Redis and API Gateway are outside the v0.1 scope.
- The current model is a single application deployment with one configured MCP integration and one active policy snapshot.

## Recovery and operations

- Worker recovery is designed for lease expiry and idempotent read-only retrieval. It is not a distributed workflow engine and has no automatic rollback.
- Backups and restore require explicit operational commands and confirmation. Application availability does not by itself prove a recent recoverable backup.
- Production acceptance validates the deployed smoke path; it does not replace monitoring, secret rotation, backup restore drills or review of model findings by a 1C specialist.
