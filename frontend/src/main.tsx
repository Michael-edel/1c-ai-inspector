import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Readiness = { status: string; capabilitiesStatus: string; policyChecksum: string; toolsetChecksum: string; reasons: string[] };
type Policy = { policyId: string; version: string; publishedTools: string[]; normalizedTools: string[]; discoveredTools: string[]; toolsetChecksum: string };
type Agent = { code: string; name: string; prompt_version: string; task_kind: string };
type Audit = { task_id: string; status: string; events: { type: string }[]; model_usage: { model: string; estimatedCost: number }[] };

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
};

function App() {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState("1c_code_assistant");
  const [taskText, setTaskText] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState("");
  const [audit, setAudit] = useState<Audit | null>(null);
  const [discovering, setDiscovering] = useState(false);

  const refresh = async () => {
    try {
      setError("");
      const [nextReadiness, nextPolicy, nextAgents] = await Promise.all([
        api<Readiness>("/api/v1/system/readiness"),
        api<Policy>("/api/v1/system/policy"),
        api<Agent[]>("/api/v1/agents"),
      ]);
      setReadiness(nextReadiness);
      setPolicy(nextPolicy);
      setAgents(nextAgents);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить состояние");
    }
  };

  useEffect(() => { void refresh(); }, []);
  const canCreateTask = readiness?.status === "ready";

  const discoverTools = async () => {
    setDiscovering(true);
    setError("");
    try {
      await api("/api/v1/system/mcp/tools");
      await refresh();
      setMessage("MCP toolset обнаружен и сохранён.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP discovery недоступен");
    } finally {
      setDiscovering(false);
    }
  };

  const createTask = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canCreateTask || !taskText.trim()) return;
    setMessage("");
    setError("");
    try {
      const created = await api<{ task_id: string }>("/api/v1/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: "default", agentId: selectedAgent, request: { text: taskText.trim() } }),
      });
      setTaskId(created.task_id);
      setAudit(null);
      setTaskText("");
      setMessage("Задача создана и отправлена в очередь.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось создать задачу");
    }
  };

  const loadAudit = async () => {
    if (!taskId) return;
    try {
      setAudit(await api<Audit>(`/api/v1/tasks/${taskId}/audit`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Audit недоступен");
    }
  };

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">1C</span><span>AI Inspector</span></div>
      <div className="side-caption">DEVELOPMENT CONTOUR</div>
      <nav><a className="nav-item active" href="#overview"><span className="nav-dot" />Обзор</a><a className="nav-item" href="#agents"><span className="nav-dot muted" />Агенты</a><a className="nav-item" href="#policy"><span className="nav-dot muted" />Policy & tools</a></nav>
      <div className="side-footer"><span className="live-dot" />локальный sandbox</div>
    </aside>
    <main className="content">
      <header className="topbar"><div><p className="eyebrow">CONTROL SURFACE</p><h1>Инспектор 1С</h1></div><button className="ghost-button" onClick={() => void refresh()}>Обновить состояние</button></header>
      <section className="hero-grid" id="overview"><div className="hero-copy"><span className="status-kicker">READ-ONLY MVP</span><h2>Проверяем контур до запуска агента.</h2><p>Каждый вызов проходит через policy, нормализованный toolset и execution snapshot. Запись в проект не разрешена.</p></div><div className={`readiness-card ${readiness?.status === "ready" ? "ready" : "blocked"}`}><div className="card-label">READINESS GATE</div><div className="readiness-status">{readiness?.status === "ready" ? "READY" : "NOT READY"}</div><p>{readiness?.reasons?.[0] === "no_tools_discovered" ? "MCP tools ещё не обнаружены" : "Проверка выполняется"}</p><div className="progress-line"><span /></div></div></section>
      {error && <div className="alert error">{error}</div>}{message && <div className="alert success">{message}</div>}
      <section className="metrics-row"><div className="metric"><span>Policy</span><strong>{policy?.version ?? "—"}</strong><small>{policy?.policyId ?? "loading"}</small></div><div className="metric"><span>Capabilities</span><strong>{policy?.normalizedTools.length ?? 0}</strong><small>{readiness?.capabilitiesStatus ?? "—"}</small></div><div className="metric"><span>Discovered</span><strong>{policy?.discoveredTools.length ?? 0}</strong><small>from MCP server</small></div></section>
      <section className="work-grid"><div className="panel task-panel"><div className="panel-heading"><div><span className="panel-index">01</span><h3>Поставить задачу</h3></div><span className="lock">{canCreateTask ? "OPEN" : "LOCKED"}</span></div><form onSubmit={createTask}><label htmlFor="agent">Agent profile</label><select id="agent" value={selectedAgent} onChange={(event) => setSelectedAgent(event.target.value)} disabled={!canCreateTask}>{agents.map((agent) => <option key={agent.code} value={agent.code}>{agent.name}</option>)}</select><label htmlFor="task">Запрос по коду 1С</label><textarea id="task" value={taskText} onChange={(event) => setTaskText(event.target.value)} placeholder="Например: проверь запросы в модуле документа ЗаказКлиента" disabled={!canCreateTask} /><button className="primary-button" disabled={!canCreateTask || !taskText.trim()}>{canCreateTask ? "Создать read-only задачу" : "Ожидание MCP tools"}</button></form></div><div className="panel" id="policy"><div className="panel-heading"><div><span className="panel-index">02</span><h3>Policy snapshot</h3></div><button className="ghost-button compact" onClick={() => void discoverTools()} disabled={discovering}>{discovering ? "DISCOVERING" : "DISCOVER MCP"}</button></div><dl className="data-list"><div><dt>Policy checksum</dt><dd>{readiness?.policyChecksum?.slice(0, 16) ?? "—"}…</dd></div><div><dt>Toolset checksum</dt><dd>{policy?.toolsetChecksum?.slice(0, 16) ?? "—"}…</dd></div><div><dt>Published tools</dt><dd className="safe">{policy?.publishedTools.length ?? 0} read-only</dd></div><div><dt>Environment</dt><dd>sandbox</dd></div></dl></div></section>
      <section className="panel agents-panel" id="agents"><div className="panel-heading"><div><span className="panel-index">03</span><h3>Agent registry</h3></div><span className="panel-note">v0.1 / 3 profiles</span></div><div className="agent-list">{agents.map((agent, index) => <div className="agent-row" key={agent.code}><span className="agent-number">0{index + 1}</span><div><strong>{agent.name}</strong><small>{agent.task_kind} · prompt {agent.prompt_version}</small></div><span className="agent-state">STAGED</span></div>)}</div></section>
      <section className="panel agents-panel"><div className="panel-heading"><div><span className="panel-index">04</span><h3>Execution audit</h3></div><button className="ghost-button compact" onClick={() => void loadAudit()} disabled={!taskId}>REFRESH AUDIT</button></div>{taskId ? <dl className="data-list"><div><dt>Task</dt><dd>{taskId.slice(0, 18)}…</dd></div><div><dt>Status</dt><dd>{audit?.status ?? "queued"}</dd></div><div><dt>Events</dt><dd>{audit?.events.length ?? 0}</dd></div><div><dt>Model cost</dt><dd>{audit?.model_usage.reduce((sum, item) => sum + item.estimatedCost, 0).toFixed(4) ?? "0.0000"}</dd></div></dl> : <p className="empty-note">Создайте задачу после прохождения readiness gate.</p>}</section>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
