import { useEffect, useState } from "react";

type Proposal = { id: string; status: string };
type CommandRecord = { exitCode?: number | null; durationMs?: number; output?: string; timedOut?: boolean };
type SandboxExecution = {
  id: string;
  proposalId: string;
  packageVersion: number;
  packageSha256: string;
  sourceCommit: string;
  status: string;
  branchName: string | null;
  validation: CommandRecord;
  test: CommandRecord;
  lastErrorCode: string | null;
  appliedToInformationBase: false;
};
type SandboxEvent = { id: number; type: string; actor: string; payload: Record<string, unknown>; createdAt: string };

const statusLabels: Record<string, string> = {
  created: "Создан",
  preparing: "Подготовка worktree",
  prepared: "Worktree готов",
  applying: "Применение diff",
  validating: "Ожидает validation/build",
  testing: "Ожидает тесты",
  awaiting_acceptance: "Ожидает решения владельца",
  rollback_required: "Требуется rollback",
  rolling_back: "Rollback",
  rolled_back: "Отменен и очищен",
  failed: "Ошибка подготовки",
};

const sandboxRequest = async <T,>(path: string, token: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options?.body ? { "Content-Type": "application/json" } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json() as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep a bounded public status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
};

export function SandboxPanel({
  proposal,
  authToken,
  onMessage,
  onError,
}: {
  proposal: Proposal | null;
  authToken: string;
  onMessage: (value: string) => void;
  onError: (value: string) => void;
}) {
  const [available, setAvailable] = useState(false);
  const [execution, setExecution] = useState<SandboxExecution | null>(null);
  const [events, setEvents] = useState<SandboxEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const token = authToken.trim();

  const loadEvents = async (executionId: string) => {
    const result = await sandboxRequest<{ events: SandboxEvent[] }>(
      `/api/v1/sandbox-executions/${executionId}/events`,
      token,
    );
    setEvents(result.events);
  };

  const discover = async () => {
    if (!proposal || proposal.status !== "approved" || !token) {
      setAvailable(false);
      setExecution(null);
      setEvents([]);
      return;
    }
    try {
      const rows = await sandboxRequest<SandboxExecution[]>("/api/v1/sandbox-executions?limit=100", token);
      const current = rows.find((item) => item.proposalId === proposal.id) ?? null;
      setAvailable(true);
      setExecution(current);
      if (current) await loadEvents(current.id);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "";
      setAvailable(message !== "HTTP 404" && !message.includes("Not Found"));
      setExecution(null);
      setEvents([]);
    }
  };

  useEffect(() => { void discover(); }, [proposal?.id, proposal?.status, token]);

  const createExecution = async () => {
    if (!proposal) return;
    setBusy(true);
    onError("");
    try {
      const versions = await sandboxRequest<{ versions: { version: number; sha256: string }[] }>(
        `/api/v1/patch-proposals/${proposal.id}/package/versions`,
        token,
      );
      const latest = versions.versions[0];
      if (!latest) throw new Error("Сначала нажмите EXPORT PACKAGE для approved proposal.");
      const created = await sandboxRequest<SandboxExecution>("/api/v1/sandbox-executions", token, {
        method: "POST",
        body: JSON.stringify({
          proposalId: proposal.id,
          packageVersion: latest.version,
          packageSha256: latest.sha256,
          note: "Created from Inspector owner control surface.",
        }),
      });
      setExecution(created);
      await loadEvents(created.id);
      onMessage("Sandbox execution создан. Следующий шаг: подготовить одноразовый worktree.");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Не удалось создать sandbox execution.");
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (action: "prepare" | "apply" | "validate" | "test" | "rollback") => {
    if (!execution) return;
    setBusy(true);
    onError("");
    try {
      const updated = await sandboxRequest<SandboxExecution>(
        `/api/v1/sandbox-executions/${execution.id}/${action}`,
        token,
        { method: "POST" },
      );
      setExecution(updated);
      await loadEvents(updated.id);
      onMessage(`Sandbox action ${action} завершено. Состояние: ${statusLabels[updated.status] ?? updated.status}.`);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : `Sandbox action ${action} не выполнено.`);
      await discover();
    } finally {
      setBusy(false);
    }
  };

  if (!available || !proposal || proposal.status !== "approved" || !token) return null;

  return (
    <section className="panel sandbox-panel" id="sandbox-executor">
      <div className="panel-heading">
        <div><span className="panel-index">SX</span><h3>Sandbox Executor</h3></div>
        <span className="panel-note">WORKTREE ONLY · 1C WRITE: FALSE</span>
      </div>
      <p className="panel-intro">Owner-only контур применяет signed diff в одноразовой Git-ветке. Он не меняет InfoBase, не выполняет merge и не делает push.</p>
      {!execution ? (
        <button type="button" className="primary-button" disabled={busy} onClick={() => void createExecution()}>
          {busy ? "СОЗДАНИЕ..." : "СОЗДАТЬ SANDBOX EXECUTION"}
        </button>
      ) : (
        <>
          <div className={`sandbox-state sandbox-${execution.status}`}>
            <div><span>STATE</span><strong>{statusLabels[execution.status] ?? execution.status}</strong></div>
            <code>{execution.id}</code>
          </div>
          <dl className="data-list sandbox-facts">
            <div><dt>Branch</dt><dd>{execution.branchName ?? "не создана"}</dd></div>
            <div><dt>Source commit</dt><dd>{execution.sourceCommit.slice(0, 16)}…</dd></div>
            <div><dt>Package</dt><dd>v{execution.packageVersion} · {execution.packageSha256.slice(0, 12)}…</dd></div>
            <div><dt>InfoBase write</dt><dd className="safe">false</dd></div>
            {execution.lastErrorCode && <div><dt>Последняя ошибка</dt><dd className="warning">{execution.lastErrorCode}</dd></div>}
          </dl>
          <div className="patch-actions sandbox-actions">
            {execution.status === "created" && <button type="button" className="primary-button" disabled={busy} onClick={() => void runAction("prepare")}>PREPARE WORKTREE</button>}
            {execution.status === "prepared" && <button type="button" className="primary-button" disabled={busy} onClick={() => void runAction("apply")}>APPLY SIGNED DIFF</button>}
            {execution.status === "validating" && <button type="button" className="primary-button" disabled={busy} onClick={() => void runAction("validate")}>RUN VALIDATION / BUILD</button>}
            {execution.status === "testing" && <button type="button" className="primary-button" disabled={busy} onClick={() => void runAction("test")}>RUN SANDBOX TESTS</button>}
            {["awaiting_acceptance", "rollback_required"].includes(execution.status) && <button type="button" className="ghost-button danger-button" disabled={busy} onClick={() => void runAction("rollback")}>ROLLBACK + CLEANUP</button>}
            <button type="button" className="ghost-button compact" disabled={busy} onClick={() => void discover()}>ОБНОВИТЬ</button>
          </div>
          {execution.validation.output !== undefined && <CommandOutput title="VALIDATION / BUILD" value={execution.validation} />}
          {execution.test.output !== undefined && <CommandOutput title="SANDBOX TESTS" value={execution.test} />}
          <div className="event-log">
            <div className="event-log-title">Sandbox audit · {events.length} events</div>
            {events.map((event) => <div className="event-row" key={event.id}><span>{event.type}</span><small>{event.actor} · {new Date(event.createdAt).toLocaleString()}</small></div>)}
          </div>
        </>
      )}
    </section>
  );
}

function CommandOutput({ title, value }: { title: string; value: CommandRecord }) {
  return (
    <div className="sandbox-output">
      <div><span>{title}</span><strong>{value.timedOut ? "TIMEOUT" : `EXIT ${value.exitCode ?? "—"}`} · {value.durationMs ?? 0} ms</strong></div>
      <pre>{value.output || "Команда не вернула текст."}</pre>
    </div>
  );
}
