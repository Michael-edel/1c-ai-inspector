# Security Model

## Scope

1C AI Inspector v0.7 keeps its production inspection contour read-only. It may retrieve metadata, validate queries and read exported BSL source, but it does not write to the 1C configuration, execute database queries or perform a deployment. The separately feature-flagged Sandbox Executor may create and modify only its disposable local Git worktree.

Patch Planner v0.2 may generate a signed package and a manual handoff record. Both are descriptions of an operator-reviewed change, not permission to execute it. Patch Planner keeps `applied=false` and rejects every MCP tool outside the read-only policy. Controlled local apply belongs only to the separately reviewed v0.3 Sandbox Executor router.

Sandbox Executor v0.3 is a separate feature-flagged trust boundary. When enabled, it may write only to a disposable Git worktree below an operator-configured root. Owner authorization, package signature/hash, immutable commit, state transition and path containment are revalidated before every side effect. Commands and filesystem roots never come from HTTP. The contour cannot merge, push, deploy or update an information base.

## Trust Boundaries

- **Browser and frontend:** untrusted client. The browser may submit task text and display data, but it cannot grant itself a role or authorize a tool.
- **Caddy/reverse proxy:** public TLS edge. It routes the application and IdP domains; it is not the application authorization boundary.
- **FastAPI backend:** policy and state-machine boundary. It validates requests, environment, capabilities, execution snapshots and report schemas.
- **Worker:** execution boundary. It claims tasks transactionally, rechecks readiness, calls only policy-published read-only tools and persists audit facts.
- **PostgreSQL:** state and audit boundary. `migrate` uses the migration role; backend and worker use the runtime role. Audit tables are append-only for the runtime role.
- **MCP bridge/EDT and model provider:** external systems. Their responses are untrusted data and are bounded, validated and recorded without exposing provider diagnostics to users.

## Authorization Rules

Tool visibility is not tool authorization. Discovery and progressive tool disclosure only determine which policy-approved tools are available; every call is checked server-side against the normalized policy, capability and read-only mode before a network request.

The v0.1 policy publishes only `read-only` tools. `write`, `conditional-write`, query execution, arbitrary commands and debug modification are blocked before MCP invocation. Prompt instructions, task text, source comments and object names cannot change role, environment, policy or tool permissions.

Production uses JWT verification through the configured JWKS issuer, including signature, issuer, audience, expiry, subject and roles. Local signed mode is for development. Approval and package endpoints use the verified identity; role or actor values from a request body are not trusted.

## Data Protection

- HTTP logs contain method, path, status, duration and request ID, not authorization headers, request bodies or query parameters.
- MCP results are bounded by `MAX_RESULT_CHARS` and task context by `MAX_CONTEXT_CHARS`. Oversized output is rejected and its original size is retained without retaining the content.
- Model audit stores token counts, cost, pricing source and SHA-256 response checksum; it does not store the raw model response.
- Audit events, tool calls, findings, finding status events, model usage and execution snapshots cannot be updated or deleted by the runtime role. Corrections use compensating events.
- User-facing errors use stable public codes and do not expose stack traces, tokens or raw provider diagnostics.

## Operational Rules

Backend and worker start only after the migration service succeeds. Production PostgreSQL is private to the Compose network, and the public edge exposes only Caddy. Secrets are supplied through environment files or secret management and are checked without printing their values.

Security acceptance must verify readiness, absence of write/conditional-write calls, audit persistence, authorization of metrics and non-root application containers. See [ERROR_MATRIX.md](ERROR_MATRIX.md) for public error and retry behavior.
