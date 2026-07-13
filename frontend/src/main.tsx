import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Readiness = { status: string; capabilitiesStatus: string; policyChecksum: string; toolsetChecksum: string; reasons: string[] };
type Policy = { policyId: string; version: string; publishedTools: string[]; normalizedTools: string[]; discoveredTools: string[]; toolsetChecksum: string };
type Agent = { code: string; name: string; prompt_version: string; task_kind: string };
type Audit = { task_id: string; status: string; events: { type: string }[]; tool_calls: { toolName: string; status: string }[]; model_usage: { model: string; estimatedCost: number }[] };
type TaskState = { taskId: string; status: string; resultReady: boolean; lastErrorCode: string | null };
type Project = { id: string; name: string; environment: string; availableCapabilities: string[] };
type Report = { status: string; summary: string; findings: unknown[]; persistedFindings: unknown[] };
type PatchImpact = { objectFqn: string; relation: string; risk: string; source: string };
type PatchProposal = { id: string; status: string; title: string; summary: string; sourceRevision: string | null; diff: string; impact: PatchImpact[]; checkpointRef: string | null; approvedBy: string | null; approvalNote: string | null; sourceValidationStatus: string; validationStatus: string };
type PatchEvent = { id: number; type: string; actor: string; payload: Record<string, unknown>; createdAt: string };

const isTerminalTaskStatus = (status: string) => ["completed", "failed", "cancelled"].includes(status);
const taskStatusLabels: Record<string, string> = {
  queued: "В очереди",
  running: "Выполняется",
  completed: "Завершена",
  failed: "Ошибка",
  cancelled: "Отменена",
};
const taskStatusDescriptions: Record<string, string> = {
  queued: "Задача ожидает свободного worker.",
  running: "MCP и модель обрабатывают запрос.",
  completed: "Отчет готов и загружен ниже.",
  failed: "Обработка завершилась ошибкой.",
  cancelled: "Задача была отменена.",
};
const formatElapsed = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
const taskStatusLabel = (status: string) => taskStatusLabels[status] ?? "Подготовка";
const taskStatusDescription = (status: string) => taskStatusDescriptions[status] ?? "Получаем состояние задачи.";
const extractObjectReference = (text: string) => {
  const match = text.match(/(?:^|[\s(])(документ[A-Za-zА-Яа-яЁё0-9_]*|справочник[A-Za-zА-Яа-яЁё0-9_]*|регистр[A-Za-zА-Яа-яЁё0-9_]*)\s*[.:]?\s*([A-Za-zА-Яа-яЁё0-9_]+)/i);
  if (!match) return null;
  const type = match[1].toLowerCase();
  return {
    name: match[2],
    type: type.startsWith("документ") ? "Document" : type.startsWith("справочник") ? "Catalog" : "InformationRegister",
    category: type.startsWith("документ") ? "Документ" : type.startsWith("справочник") ? "Справочник" : "РегистрСведений",
  };
};
const isAuditRequest = (text: string) => /\b(аудит\w*|audit|finding\w*|потенциальн\w*\s+ошиб\w*|небезопасн\w*\s+мест\w*)\b/i.test(text);
const auditAgentMismatch = (agentCode: string, text: string) => isAuditRequest(text) && agentCode !== "1c_audit_agent";
const retrievalPlanForAgent = (agentCode: string, text: string) => {
  const query = text.trim();
  const object = extractObjectReference(query);
  const searchQuery = object?.name ?? query;
  if (agentCode === "1c_query_agent") {
    return [
      { tool: "validate_query", arguments: { query } },
      { tool: "get_metadata_tree", arguments: { filter: object?.name ?? query } },
    ];
  }
  if (agentCode === "1c_audit_agent" && object) {
    return [
      { tool: "search_code", arguments: { query: searchQuery, limit: 500, category: object.category, module: "МодульОбъекта", mode: "exact" } },
      { tool: "get_object_structure", arguments: { object_type: object.type, object_name: object.name } },
    ];
  }
  return [
    { tool: "bsl_syntax_help", arguments: { query: searchQuery } },
    { tool: "search_code", arguments: { query: searchQuery, limit: 5, mode: "smart" } },
  ];
};

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
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [taskStatus, setTaskStatus] = useState("");
  const [taskStartedAt, setTaskStartedAt] = useState<number | null>(null);
  const [taskElapsedSeconds, setTaskElapsedSeconds] = useState(0);
  const [taskLastErrorCode, setTaskLastErrorCode] = useState("");
  const [taskPollingError, setTaskPollingError] = useState("");
  const [patchPath, setPatchPath] = useState("CommonModules/Example.bsl");
  const [patchTitle, setPatchTitle] = useState("Proposal-only change");
  const [patchSummary, setPatchSummary] = useState("Review a proposed BSL change before any manual application.");
  const [patchRevision, setPatchRevision] = useState("local-draft");
  const [patchOriginal, setPatchOriginal] = useState("Procedure Check();\n\tReturn True;\nEndProcedure;");
  const [patchProposed, setPatchProposed] = useState("Procedure Check();\n\t// review before apply\n\tReturn True;\nEndProcedure;");
  const [patchActor, setPatchActor] = useState("reviewer");
  const [patchNote, setPatchNote] = useState("Reviewed in Inspector proposal workflow.");
  const [authToken, setAuthToken] = useState("");
  const [patchProposal, setPatchProposal] = useState<PatchProposal | null>(null);
  const [patchEvents, setPatchEvents] = useState<PatchEvent[]>([]);
  const [patchBusy, setPatchBusy] = useState(false);

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
      try {
        const nextProjects = await api<Project[]>("/api/v1/projects");
        setProjects(nextProjects);
        setSelectedProject((current) => current || nextProjects[0]?.id || "");
      } catch {
        setProjects([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить состояние");
    }
  };

  const syncProjects = async () => {
    setError("");
    try {
      const result = await api<{ synced: number }>("/api/v1/projects/sync", { method: "POST" });
      setMessage(`Синхронизировано проектов: ${result.synced}`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Синхронизация проектов недоступна");
    }
  };

  useEffect(() => { void refresh(); }, []);
  const canCreateTask = readiness?.status === "ready";
  const shouldUseAuditAgent = auditAgentMismatch(selectedAgent, taskText);

  useEffect(() => {
    if (!taskId || !taskStartedAt || isTerminalTaskStatus(taskStatus)) return;
    const timer = window.setInterval(() => {
      setTaskElapsedSeconds(Math.floor((Date.now() - taskStartedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [taskId, taskStartedAt, taskStatus]);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let pollTimer: number | undefined;
    const poll = async () => {
      try {
        const state = await api<TaskState>(`/api/v1/tasks/${taskId}`);
        if (cancelled) return;
        setTaskStatus(state.status);
        setTaskLastErrorCode(state.lastErrorCode ?? "");
        const nextAudit = await api<Audit>(`/api/v1/tasks/${taskId}/audit`);
        if (cancelled) return;
        setAudit(nextAudit);
        if (state.resultReady) {
          setReport(await api<Report>(`/api/v1/tasks/${taskId}/report`));
        }
        setTaskPollingError("");
        if (isTerminalTaskStatus(state.status)) {
          if (pollTimer !== undefined) window.clearInterval(pollTimer);
          setMessage(state.status === "completed" ? "Задача завершена. Отчет загружен ниже." : `Задача завершилась: ${taskStatusLabel(state.status)}.`);
        }
      } catch {
        if (!cancelled) setTaskPollingError("Не удалось обновить статус задачи. Проверьте соединение с Inspector.");
      }
    };
    void poll();
    pollTimer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
    };
  }, [taskId]);

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
    if (!canCreateTask || !taskText.trim() || !selectedProject) return;
    if (shouldUseAuditAgent) {
      setError("Этот запрос похож на аудит. Выберите профиль 1C Audit Agent.");
      return;
    }
    setMessage("");
    setError("");
    try {
      const created = await api<{ task_id: string; status: string }>("/api/v1/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: selectedProject, agentId: selectedAgent, request: { text: taskText.trim(), retrieval: retrievalPlanForAgent(selectedAgent, taskText) } }),
      });
      setTaskId(created.task_id);
      setTaskStatus(created.status || "queued");
      setTaskStartedAt(Date.now());
      setTaskElapsedSeconds(0);
      setTaskLastErrorCode("");
      setTaskPollingError("");
      setAudit(null);
      setTaskText("");
      setReport(null);
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

  const loadReport = async () => {
    if (!taskId) return;
    try {
      setReport(await api<Report>(`/api/v1/tasks/${taskId}/report`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Report ещё не готов");
    }
  };

  const loadPatch = async (proposalId: string) => {
    const [proposal, eventLog] = await Promise.all([
      api<PatchProposal>(`/api/v1/patch-proposals/${proposalId}`),
      api<{ events: PatchEvent[] }>(`/api/v1/patch-proposals/${proposalId}/events`),
    ]);
    setPatchProposal(proposal);
    setPatchEvents(eventLog.events);
  };

  const createPatchProposal = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedProject || !patchPath.trim() || patchOriginal === patchProposed) return;
    setPatchBusy(true);
    setError("");
    try {
      const created = await api<PatchProposal>("/api/v1/patch-proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProject,
          title: patchTitle.trim(),
          summary: patchSummary.trim(),
          sourceRevision: patchRevision.trim() || null,
          files: [{ path: patchPath.trim(), original: patchOriginal, proposed: patchProposed }],
        }),
      });
      await loadPatch(created.id);
      setMessage("Proposal создан. Изменения остаются только в preview.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось создать proposal");
    } finally {
      setPatchBusy(false);
    }
  };

  const runPatchAction = async (action: "impact" | "revalidate" | "validate" | "checkpoint" | "approve" | "reject") => {
    if (!patchProposal) return;
    setPatchBusy(true);
    setError("");
    try {
      const options: RequestInit = { method: "POST" };
      if (action === "revalidate") {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify({ currentRevision: patchProposal.sourceRevision, files: [{ path: patchPath, current: patchOriginal }] });
      } else if (action === "approve" || action === "reject") {
        options.headers = { "Content-Type": "application/json", Authorization: `Bearer ${authToken.trim()}` };
        options.body = JSON.stringify({ note: patchNote.trim() });
      }
      await api(`/api/v1/patch-proposals/${patchProposal.id}/${action}`, options);
      await loadPatch(patchProposal.id);
      setMessage(`Действие ${action} сохранено в журнале proposal.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Действие proposal недоступно");
    } finally {
      setPatchBusy(false);
    }
  };

  const exportPatchPackage = async () => {
    if (!patchProposal || !authToken.trim()) return;
    setPatchBusy(true);
    try {
      const response = await fetch(`/api/v1/patch-proposals/${patchProposal.id}/package`, { headers: { Authorization: `Bearer ${authToken.trim()}` } });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${patchProposal.id}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось экспортировать package");
    } finally {
      setPatchBusy(false);
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
      {taskId && <section className={`task-monitor ${isTerminalTaskStatus(taskStatus) ? "finished" : ""} ${taskStatus === "failed" ? "failed" : ""}`} aria-live="polite"><div className="task-monitor-head"><div><span className="card-label">TASK MONITOR</span><strong>{taskStatusLabel(taskStatus)}</strong></div><span className="task-elapsed">Прошло {formatElapsed(taskElapsedSeconds)}</span></div><div className="task-monitor-track"><span /></div><p>{taskStatusDescription(taskStatus)}</p>{taskPollingError && <p className="task-monitor-warning">{taskPollingError}</p>}{taskLastErrorCode && <p className="task-monitor-warning">Код ошибки: {taskLastErrorCode}</p>}{taskElapsedSeconds >= 45 && !isTerminalTaskStatus(taskStatus) && <p className="task-monitor-warning">Проверка длится дольше обычного. MCP или модель могут отвечать медленно.</p>}</section>}
      <section className="metrics-row"><div className="metric"><span>Policy</span><strong>{policy?.version ?? "—"}</strong><small>{policy?.policyId ?? "loading"}</small></div><div className="metric"><span>Capabilities</span><strong>{policy?.normalizedTools.length ?? 0}</strong><small>{readiness?.capabilitiesStatus ?? "—"}</small></div><div className="metric"><span>Discovered</span><strong>{policy?.discoveredTools.length ?? 0}</strong><small>from MCP server</small></div></section>
      <section className="work-grid"><div className="panel task-panel"><div className="panel-heading"><div><span className="panel-index">01</span><h3>Поставить задачу</h3></div><span className="lock">{canCreateTask ? "OPEN" : "LOCKED"}</span></div><form onSubmit={createTask}><label htmlFor="project">EDT project</label><select id="project" value={selectedProject} onChange={(event) => setSelectedProject(event.target.value)} disabled={!canCreateTask || projects.length === 0}><option value="">Выберите проект</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select><label htmlFor="agent">Agent profile</label><select id="agent" value={selectedAgent} onChange={(event) => setSelectedAgent(event.target.value)} disabled={!canCreateTask}>{agents.map((agent) => <option key={agent.code} value={agent.code}>{agent.name}</option>)}</select><label htmlFor="task">Запрос по коду 1С</label><textarea id="task" value={taskText} onChange={(event) => setTaskText(event.target.value)} placeholder="Например: проверь запросы в модуле документа ЗаказКлиента" disabled={!canCreateTask} /><button className="primary-button" disabled={!canCreateTask || !selectedProject || !taskText.trim()}>{canCreateTask ? "Создать read-only задачу" : "Ожидание MCP tools"}</button></form></div><div className="panel" id="policy"><div className="panel-heading"><div><span className="panel-index">02</span><h3>Policy snapshot</h3></div><div className="heading-actions"><button className="ghost-button compact" onClick={() => void syncProjects()}>SYNC PROJECTS</button><button className="ghost-button compact" onClick={() => void discoverTools()} disabled={discovering}>{discovering ? "DISCOVERING" : "DISCOVER MCP"}</button></div></div><dl className="data-list"><div><dt>Projects</dt><dd>{projects.length}</dd></div><div><dt>Policy checksum</dt><dd>{readiness?.policyChecksum?.slice(0, 16) ?? "—"}…</dd></div><div><dt>Toolset checksum</dt><dd>{policy?.toolsetChecksum?.slice(0, 16) ?? "—"}…</dd></div><div><dt>Published tools</dt><dd className="safe">{policy?.publishedTools.length ?? 0} read-only</dd></div></dl></div></section>
      <section className="panel agents-panel" id="agents"><div className="panel-heading"><div><span className="panel-index">03</span><h3>Agent registry</h3></div><span className="panel-note">v0.1 / 3 profiles</span></div><div className="agent-list">{agents.map((agent, index) => <div className="agent-row" key={agent.code}><span className="agent-number">0{index + 1}</span><div><strong>{agent.name}</strong><small>{agent.task_kind} · prompt {agent.prompt_version}</small></div><span className="agent-state">STAGED</span></div>)}</div></section>
      <section className="panel patch-panel" id="patch-planner"><div className="panel-heading"><div><span className="panel-index">04</span><h3>Patch Planner</h3></div><span className="panel-note">PROPOSAL ONLY</span></div><p className="panel-intro">Сформируйте diff для проверки. Inspector не меняет файлы, Git или конфигурацию 1С.</p><form onSubmit={createPatchProposal} className="patch-form"><label htmlFor="patch-title">Название proposal</label><input id="patch-title" value={patchTitle} onChange={(event) => setPatchTitle(event.target.value)} /><label htmlFor="patch-path">Относительный путь BSL</label><input id="patch-path" value={patchPath} onChange={(event) => setPatchPath(event.target.value)} /><div className="patch-form-grid"><div><label htmlFor="patch-revision">Source revision</label><input id="patch-revision" value={patchRevision} onChange={(event) => setPatchRevision(event.target.value)} /></div><div><label htmlFor="patch-summary">Summary</label><input id="patch-summary" value={patchSummary} onChange={(event) => setPatchSummary(event.target.value)} /></div></div><label htmlFor="patch-original">Original</label><textarea id="patch-original" value={patchOriginal} onChange={(event) => setPatchOriginal(event.target.value)} /><label htmlFor="patch-proposed">Proposed</label><textarea id="patch-proposed" value={patchProposed} onChange={(event) => setPatchProposed(event.target.value)} /><div className="patch-actions"><button className="primary-button" disabled={patchBusy || !selectedProject || !patchPath.trim() || patchOriginal === patchProposed}>Сформировать proposal</button><button type="button" className="ghost-button compact" onClick={() => void runPatchAction("impact")} disabled={patchBusy || !patchProposal}>ANALYZE IMPACT</button><button type="button" className="ghost-button compact" onClick={() => void runPatchAction("revalidate")} disabled={patchBusy || !patchProposal}>REVALIDATE SOURCE</button><button type="button" className="ghost-button compact" onClick={() => void runPatchAction("checkpoint")} disabled={patchBusy || !patchProposal || patchProposal.sourceValidationStatus !== "valid" || !["proposed", "checkpointed"].includes(patchProposal.status)}>CHECKPOINT</button></div></form>{patchProposal && <div className="patch-result"><div className="patch-result-head"><div><strong>{patchProposal.title}</strong><small>{patchProposal.id} · revision {patchProposal.sourceRevision ?? "—"}</small></div><span className={`patch-status ${patchProposal.status}`}>{patchProposal.status}</span></div><pre className="diff-view">{patchProposal.diff}</pre><div className="patch-meta"><span>Impact: {patchProposal.impact.length} candidate(s)</span><span>Source: {patchProposal.sourceValidationStatus}</span><span>Checkpoint: {patchProposal.checkpointRef ? "recorded" : "not recorded"}</span></div><div className="patch-decision"><label htmlFor="patch-actor">Actor</label><input id="patch-actor" value={patchActor} onChange={(event) => setPatchActor(event.target.value)} /><label htmlFor="patch-note">Decision note</label><input id="patch-note" value={patchNote} onChange={(event) => setPatchNote(event.target.value)} /><div className="patch-actions"><button type="button" className="primary-button" onClick={() => void runPatchAction("approve")} disabled={patchBusy || !["checkpointed", "awaiting_approval"].includes(patchProposal.status)}>Approve proposal</button><button type="button" className="ghost-button compact danger-button" onClick={() => void runPatchAction("reject")} disabled={patchBusy || ["approved", "rejected"].includes(patchProposal.status)}>Reject proposal</button><button type="button" className="ghost-button compact" onClick={exportPatchPackage} disabled={patchBusy}>EXPORT PACKAGE</button></div></div><div className="event-log"><div className="event-log-title">Proposal event log</div>{patchEvents.map((item) => <div className="event-row" key={item.id}><span>{item.type}</span><small>{item.actor} · {new Date(item.createdAt).toLocaleString()}</small></div>)}</div></div>}</section>
      <section className="panel patch-validation-bar"><div className="panel-heading"><div><span className="panel-index">05</span><h3>Validation gate</h3></div><span className="panel-note">SOURCE + DIFF</span></div><p className="panel-intro">Approval разрешен только после source revalidation и детерминированной проверки diff.</p><div className="patch-actions"><span className="panel-note">{patchProposal ? `source: ${patchProposal.sourceValidationStatus} · patch: ${patchProposal.validationStatus}` : "Создайте proposal"}</span><label htmlFor="auth-token">Inspector token</label><input id="auth-token" type="password" value={authToken} onChange={(event) => setAuthToken(event.target.value)} placeholder="Bearer token без префикса" /><button type="button" className="ghost-button compact" onClick={() => void runPatchAction("validate")} disabled={patchBusy || !patchProposal || patchProposal.sourceValidationStatus !== "valid"}>VALIDATE PATCH</button></div></section>
      <section className="panel agents-panel"><div className="panel-heading"><div><span className="panel-index">06</span><h3>Execution audit</h3></div><div className="heading-actions"><button className="ghost-button compact" onClick={() => void loadAudit()} disabled={!taskId}>REFRESH AUDIT</button><button className="ghost-button compact" onClick={() => void loadReport()} disabled={!taskId}>LOAD REPORT</button></div></div>{taskId ? <dl className="data-list"><div><dt>Task</dt><dd>{taskId.slice(0, 18)}…</dd></div><div><dt>Status</dt><dd>{audit?.status ?? taskStatusLabel(taskStatus)}</dd></div><div><dt>Events</dt><dd>{audit?.events.length ?? 0}</dd></div><div><dt>MCP calls</dt><dd>{audit?.tool_calls.length ?? 0}</dd></div><div><dt>Model cost</dt><dd>{audit?.model_usage.reduce((sum, item) => sum + item.estimatedCost, 0).toFixed(4) ?? "0.0000"}</dd></div>{report && <><div><dt>Summary</dt><dd>{report.summary}</dd></div><div><dt>Findings</dt><dd>{report.persistedFindings.length}</dd></div></>}</dl> : <p className="empty-note">Создайте задачу после прохождения readiness gate.</p>}</section>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
