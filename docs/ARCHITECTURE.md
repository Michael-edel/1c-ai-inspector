# Architecture Overview

## Runtime Topology

```text
Browser
  |
  v
Caddy :443  --->  Keycloak/JWKS IdP
  |
  +--> Frontend (React/Vite)
  |
  +--> Backend (FastAPI) ---> PostgreSQL
                              ^
                              |
                         Worker process
                              |
                              +--> MCP Connector ---> onec-mcp-bridge ---> 1C/EDT
                              |
                              +--> OpenAI-compatible Model API

Migrate service ---> PostgreSQL schema and grants
```

The production edge exposes Caddy only. Frontend and backend are bound to the internal Compose network, and PostgreSQL is not published externally. Keycloak is an optional persistent IdP profile; an external JWKS issuer can be used instead.

## Patch Planner v0.2 Boundary

Patch Planner consumes persisted read-only task evidence, prepares source snapshots and diffs, verifies an operator-configured Git revision, records approval decisions and creates signed immutable packages. A manual handoff records which package was transferred to an operator, but it does not mean that the proposal was applied.

The backend has no apply operation. It does not write to an EDT workspace, invoke a write-capable MCP tool, alter a Git working tree or update a 1C database. Controlled writes, sandbox branches, EDT validation and rollback are a separate v0.3 Sandbox Executor boundary.

## Request and Execution Flow

1. Startup loads the policy, initializes authentication and performs bounded MCP discovery.
2. Discovery normalizes only policy-approved tools, computes the toolset checksum and persists the snapshot.
3. The readiness gate checks the policy, discovered tools, capabilities, project environment and read-only publication.
4. `POST /api/v1/tasks` creates a task in `created` and an immutable execution snapshot in one transaction.
5. The worker claims one task with PostgreSQL row locking, assigns a lease and sends only the explicit retrieval plan to the MCP connector.
6. Each retrieval call is bounded, validated and persisted in `tool_calls`; failed calls receive a stable error code.
7. The model adapter receives a bounded untrusted context and a concrete `StructuredReport` schema. Its JSON response is validated before findings are persisted.
8. The worker writes model usage, findings and terminal task events, then releases the lease.
9. The UI polls task state and loads the canonical persisted report, audit and execution snapshot.

## Persistence and Roles

Alembic migrations run once through the `migrate` Compose service using `MIGRATION_DATABASE_URL`. Backend and worker use `DATABASE_URL` with the runtime role. Normal application tables receive only the permissions they need; audit tables receive runtime `SELECT, INSERT` and no `UPDATE, DELETE`.

The v0.1 task state machine is `created -> discovering -> analyzing -> reporting -> completed`, with terminal `failed` and `cancelled` branches. Every transition is appended to `task_events`. PostgreSQL claiming uses `created` as the queue-ready state; legacy `queued/running` rows remain recoverable during rolling deployment. Heartbeat, lease recovery, cooperative cancellation, idempotent retrieval reuse and the overall task deadline protect the worker from duplicate or abandoned execution.

## Deployment Artifacts

- `docker-compose.yml`: local services and dependencies.
- `docker-compose.production.yml`: private application bindings and restart policy.
- `docker-compose.keycloak.production.yml`: persistent Keycloak and IdP database.
- `docker-compose.edge.production.yml`: Caddy TLS edge and public host routing.
- `scripts/final-production-acceptance.ps1`: monitor, error contract, three agents and security/load verification.
