import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  getLibraryAgents, createLibraryAgent, updateLibraryAgent, deleteLibraryAgent, duplicateLibraryAgent,
  getLibraryAgentLabs, getLibraryAgentStats,
  getToolSets, getPipelines, getBuiltinTools,
  getAgentInstances, createAgentInstance, deleteAgentInstance,
  runAgentInstance, pauseAgentInstance, resumeAgentInstance, stopAgentInstance,
  // Lab-side APIs reused for instance feed / inspector tabs
  resetLab,
  getLabAgents, updateLabAgent,
  getLabMessages, getLabMemories, toggleLabMemoryVisibility,
  getLabResources, uploadLabResource, deleteLabResource, getLabResourceUrl,
  getLabOutputFiles, getLabOutputFileUrl, getLabOutputFileContent, getLabOutputFileHistory,
  getLabResourceContent,
  downloadFile, getAuthBlobUrl,
  injectLabMessage,
  getRagCollections, getLabRagAccess, grantLabRagAccess, revokeLabRagAccess, updateLabRagAccess,
  getLabWeb3Access, getLabWeb3Candidates, grantLabWeb3Access, revokeLabWeb3Access,
  getLabServerAccess, getLabServerCandidates, grantLabServerAccess, revokeLabServerAccess,
  getPromptTemplates,
} from '../../services/api';
import { AgentEditForm, HermesPanel } from '../labs/LabsView';
import '../labs/LabsView.css';

/* ── Icons ── */
const IC = {
  plus: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  trash: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>,
  bot: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><line x1="12" y1="7" x2="12" y2="11"/><circle cx="8" cy="16" r="1"/><circle cx="16" cy="16" r="1"/></svg>,
  check: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>,
  copy: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  search: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  play: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>,
  pause: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>,
  stop: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14"/></svg>,
  spark: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  chevron: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="6 9 12 15 18 9"/></svg>,
  user: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
  chip: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3"/><path d="M15 1v3"/><path d="M9 20v3"/><path d="M15 20v3"/><path d="M20 9h3"/><path d="M20 14h3"/><path d="M1 9h3"/><path d="M1 14h3"/></svg>,
  settings: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  tool: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>,
};

const MSG_TYPE_COLORS = {
  message: 'rgba(255,255,255,0.5)',
  task: '#3b82f6',
  result: '#22c55e',
  error: '#ef4444',
  tool_call: '#a855f7',
  tool_result: '#8b5cf6',
  inject: '#fbbf24',
  summary: '#06b6d4',
  file_event: '#f97316',
};

function formatMsgTime(ts) {
  if (!ts) return '';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function renderMsgContent(content) {
  if (!content) return null;
  const allRegex = /!\[([^\]]*)\]\(([^)]+)\)|(data:image\/[a-z]+;base64,[A-Za-z0-9+/=]+)/g;
  if (!allRegex.test(content)) return content;
  allRegex.lastIndex = 0;
  const parts = [];
  let lastIndex = 0;
  let match;
  while ((match = allRegex.exec(content)) !== null) {
    if (match.index > lastIndex) parts.push(<span key={lastIndex}>{content.slice(lastIndex, match.index)}</span>);
    const imgUrl = match[2] || match[3];
    parts.push(<img key={match.index} src={imgUrl} alt={match[1] || 'image'} style={{ maxWidth: '100%', maxHeight: 300, borderRadius: 4, margin: '4px 0', display: 'block', border: '1px solid rgba(255,255,255,0.1)' }} />);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) parts.push(<span key={lastIndex}>{content.slice(lastIndex)}</span>);
  return <>{parts}</>;
}

// Solo-agent strategy pauses at iter 0 when no user seed exists.
// That's distinct from a user-initiated pause — the agent is alive and waiting
// for the first message. Detector + label live here so every status badge in
// this file renders the same nuance.
function isAwaitingInput(inst) {
  return !!inst && inst.status === 'paused' && (inst.current_iteration ?? 0) === 0;
}

function statusBadge(inst) {
  if (isAwaitingInput(inst)) {
    return { label: 'awaiting input', className: 'agents-inst-status agents-inst-status--awaiting' };
  }
  const s = inst?.status || 'unknown';
  return { label: s, className: `agents-inst-status agents-inst-status--${s}` };
}

const EMPTY_AGENT = {
  name: '', description: '', system_prompt: '',
  role: '',
  model_id: null, backend: 'native', temperature: 0.7, max_tokens: 4096,
  tools: [], tool_set_ids: [],
  is_active: true,
  cron_expression: '', cron_instruction: '',
  anti_loop_enabled: false,
  share_memory: false,
  callable_agents: [],
};

function SensitiveToolTag({ tool }) {
  if (!tool?.sensitive) return null;
  return (
    <span
      title={tool.sensitive_reason || 'This tool can perform real, hard-to-reverse actions on external accounts or assets.'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 2,
        marginLeft: 6, padding: '0 5px',
        fontSize: '0.55rem', fontWeight: 600, lineHeight: '1.05rem',
        color: '#ffd5d5', background: 'rgba(220, 38, 38, 0.18)',
        border: '1px solid rgba(220, 38, 38, 0.5)', borderRadius: 3,
        textTransform: 'uppercase', letterSpacing: '0.06em', cursor: 'help',
        verticalAlign: 'middle',
      }}
    >⚠ Sensitive</span>
  );
}

/* ── Expandable pipeline tool group ── */
function ExpandableToolGroup({ toolDef, tools, pipelines, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const prefix = toolDef.name + ':';
  const pipelineEntries = tools.filter(t => t.startsWith(prefix));
  const selectedNames = pipelineEntries.map(t => t.split(':')[1]);
  const allSelected = pipelines.length > 0 && pipelines.every(p => selectedNames.includes(p.name));
  const someSelected = selectedNames.length > 0;

  const toggleAll = () => {
    const base = tools.filter(t => !t.startsWith(prefix) && t !== toolDef.name);
    if (allSelected) {
      onChange(base);
    } else {
      onChange([...base, ...pipelines.map(p => `${toolDef.name}:${p.name}`)]);
    }
  };
  const toggleOne = (name) => {
    const key = `${toolDef.name}:${name}`;
    onChange(tools.includes(key) ? tools.filter(t => t !== key) : [...tools, key]);
  };
  const checkboxRef = useRef(null);
  useEffect(() => { if (checkboxRef.current) checkboxRef.current.indeterminate = someSelected && !allSelected; }, [someSelected, allSelected]);

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <label className="agents-tool-checkbox" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" ref={checkboxRef} checked={someSelected} onChange={toggleAll} />
        <span className="agents-tool-info" style={{ flex: 1 }}>
          <span className="agents-tool-name">{toolDef.name.toUpperCase()}<SensitiveToolTag tool={toolDef} /></span>
          <span className="agents-tool-desc">{toolDef.description}</span>
        </span>
        {pipelines.length > 0 && (
          <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
            style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 4px' }}>
            {expanded ? '▾' : '▸'} {selectedNames.length}/{pipelines.length}
          </button>
        )}
      </label>
      {expanded && (
        <div style={{ marginLeft: 22, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {pipelines.map(p => (
            <label key={p.name} className="agents-tool-checkbox" style={{ fontSize: '0.65rem' }}>
              <input type="checkbox" checked={selectedNames.includes(p.name)} onChange={() => toggleOne(p.name)} />
              <span className="agents-tool-info">
                <span className="agents-tool-name">{p.name}</span>
                <span className="agents-tool-desc">{p.description}{!p.has_provider ? ' ⚠ no provider' : ''}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Sub-tool selection group (mail, twitter, youtube) ── */
function SubToolGroup({ toolDef, tools, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const prefix = toolDef.name + ':';
  const subEntries = tools.filter(t => t.startsWith(prefix));
  // slice(prefix.length) — not split(':')[1] — so group names that themselves
  // contain a colon (e.g. MCP groups named "mcp:<slug>") parse correctly.
  const selectedSubs = subEntries.map(t => t.slice(prefix.length));
  const allSelected = toolDef.subTools.length > 0 && toolDef.subTools.every(s => selectedSubs.includes(s.name));
  const someSelected = selectedSubs.length > 0;

  const toggleAll = () => {
    const base = tools.filter(t => !t.startsWith(prefix));
    if (allSelected) {
      onChange(base);
    } else {
      onChange([...base, ...toolDef.subTools.map(s => `${toolDef.name}:${s.name}`)]);
    }
  };
  const toggleOne = (name) => {
    const key = `${toolDef.name}:${name}`;
    onChange(tools.includes(key) ? tools.filter(t => t !== key) : [...tools, key]);
  };
  const checkboxRef = useRef(null);
  useEffect(() => { if (checkboxRef.current) checkboxRef.current.indeterminate = someSelected && !allSelected; }, [someSelected, allSelected]);

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <label className="agents-tool-checkbox" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" ref={checkboxRef} checked={someSelected} onChange={toggleAll} />
        <span className="agents-tool-info" style={{ flex: 1 }}>
          <span className="agents-tool-name">{toolDef.name.toUpperCase()}<SensitiveToolTag tool={toolDef} /></span>
          <span className="agents-tool-desc">{toolDef.description}</span>
        </span>
        <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
          style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 4px' }}>
          {expanded ? '▾' : '▸'} {selectedSubs.length}/{toolDef.subTools.length}
        </button>
      </label>
      {expanded && (
        <div style={{ marginLeft: 22, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {toolDef.subTools.map(s => (
            <label key={s.name} className="agents-tool-checkbox" style={{ fontSize: '0.65rem' }}>
              <input type="checkbox" checked={selectedSubs.includes(s.name)} onChange={() => toggleOne(s.name)} />
              <span className="agents-tool-info">
                <span className="agents-tool-name">{s.name}{s.sensitive ? <SensitiveToolTag tool={s} /> : null}</span>
                <span className="agents-tool-desc">{s.desc}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Instance control panel ── */
function InstancePanel({ instance, template, busy, onAction, onDelete }) {
  const status = instance.status;
  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isStopped = !isRunning && !isPaused;
  const openInLabs = () => {
    try { window.location.hash = `#labs?lab=${instance.lab_id}`; } catch {}
  };
  return (
    <div className="agents-editor-form">
      <div className="agents-editor-header">
        <h2>{instance.name}</h2>
        <div className="agents-editor-actions">
          {(() => { const b = statusBadge(instance); return <span className={b.className}>{b.label}</span>; })()}
        </div>
      </div>
      <div className="agents-form-grid">
        <div className="agents-instance-controls">
          {isStopped && (
            <button className="agents-btn-save" disabled={!!busy} onClick={() => onAction('run')}>▶ Run</button>
          )}
          {isRunning && (
            <button className="agents-btn-save" disabled={!!busy} onClick={() => onAction('pause')}>⏸ Pause</button>
          )}
          {isPaused && (
            <button className="agents-btn-save" disabled={!!busy} onClick={() => onAction('resume')}>▶ Resume</button>
          )}
          {(isRunning || isPaused) && (
            <button className="agents-btn-secondary" disabled={!!busy} onClick={() => onAction('stop')}>■ Stop</button>
          )}
          <button className="agents-btn-secondary" onClick={openInLabs} title="Open underlying lab">Open in Labs ↗</button>
          <button className="agents-btn-secondary agents-btn-danger" onClick={onDelete} disabled={isRunning}>Delete</button>
        </div>

        <div className="agents-field agents-field-full">
          <label>Status details</label>
          <div className="agents-instance-meta">
            <div><span>Iteration</span><b>{instance.current_iteration ?? 0}{instance.max_iterations ? ` / ${instance.max_iterations}` : ''}</b></div>
            <div><span>Started</span><b>{instance.started_at ? new Date(instance.started_at).toLocaleString() : '—'}</b></div>
            <div><span>Paused</span><b>{instance.paused_at ? new Date(instance.paused_at).toLocaleString() : '—'}</b></div>
            <div><span>Completed</span><b>{instance.completed_at ? new Date(instance.completed_at).toLocaleString() : '—'}</b></div>
            <div><span>Created</span><b>{instance.created_at ? new Date(instance.created_at).toLocaleString() : '—'}</b></div>
          </div>
        </div>

        {template && (
          <div className="agents-field agents-field-full">
            <label>Template</label>
            <div className="agents-instance-template">
              <div className="agents-tool-name">{template.name}</div>
              {template.description && <div className="agents-tool-desc">{template.description}</div>}
              {template.tools?.length > 0 && (
                <div className="agents-tool-desc">{template.tools.length} tools</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Central feed for a selected instance ── */
function InstanceFeed({
  instance, messages, outputFiles, busy,
  onRun, onPause, onResume, onStop, onReset, onClose,
  allExpanded, onToggleExpandAll,
  menuOpen, setMenuOpen,
  injectText, setInjectText, onInject, messagesEndRef,
  expandedMessages, setExpandedMessages,
  onOpenOutputFile,
}) {
  const status = instance.status;
  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isCreated = status === 'created';
  const isDone = status === 'completed' || status === 'failed';
  const toggleExpanded = (id) => setExpandedMessages(p => ({ ...p, [id]: !p[id] }));

  const renderMessage = (msg) => {
    const isExpanded = allExpanded || !!expandedMessages[msg.id];
    const senderType = msg.sender_type || 'system';
    const messageType = msg.message_type || 'message';
    const content = typeof msg.content === 'string' ? msg.content : (msg.content ? JSON.stringify(msg.content) : '');
    let preview = content.length > 120 ? content.slice(0, 120) + '…' : content;
    if (messageType === 'tool_call' && msg.tool_name) {
      const args = msg.tool_input ? Object.entries(msg.tool_input).map(([k,v]) => {
        const vs = typeof v === 'string' ? v : JSON.stringify(v);
        return `${k}=${vs.length > 40 ? vs.slice(0,40) + '…' : vs}`;
      }).join(', ') : '';
      const status = msg.tool_output ? (msg.tool_output.success === false ? ' ✗' : ' ✓') : '';
      preview = `${msg.tool_name}(${args})${status}`;
      if (preview.length > 150) preview = preview.slice(0, 150) + '…';
    }
    const avatarBg = senderType === 'user' ? 'rgba(185,28,28,0.2)' :
      senderType === 'orchestrator' ? 'rgba(59,130,246,0.2)' :
      senderType === 'agent' ? 'rgba(34,197,94,0.2)' : 'rgba(255,255,255,0.08)';
    const avatarColor = senderType === 'user' ? '#b91c1c' :
      senderType === 'orchestrator' ? '#3b82f6' :
      senderType === 'agent' ? '#22c55e' : 'rgba(255,255,255,0.5)';
    const avatarIcon = senderType === 'user' ? IC.user :
      senderType === 'orchestrator' ? IC.chip :
      senderType === 'agent' ? IC.bot : IC.settings;
    const typeColor = MSG_TYPE_COLORS[messageType] || 'rgba(255,255,255,0.5)';
    const isTerminalTool = ['python_exec','shell_exec','db_query','db_execute','db_schema'].includes(msg.tool_name);
    return (
      <div key={msg.id}
        className={`lab-msg lab-msg-${senderType} lab-msg-type-${messageType}${isExpanded ? ' lab-msg-expanded' : ''}`}
        onClick={() => toggleExpanded(msg.id)}
        style={{ cursor: 'pointer' }}>
        <div className="lab-msg-avatar" style={{ background: avatarBg, color: avatarColor }}>
          {avatarIcon}
        </div>
        <div className="lab-msg-body">
          <div className="lab-msg-meta">
            <span className="lab-msg-expand-icon">{isExpanded ? '▾' : '▸'}</span>
            <span className="lab-msg-sender" style={{ color: typeColor }}>
              {senderType === 'orchestrator' ? (instance?.name || msg.sender_name || 'AGENT') : (msg.sender_name || senderType.toUpperCase())}
            </span>
            {msg.target_name && <span className="lab-msg-target">→ {msg.target_name}</span>}
            <span className="lab-msg-type-badge" style={{ background: `${typeColor}20`, color: typeColor }}>{messageType}</span>
            <span className="lab-msg-time">{formatMsgTime(msg.created_at)}</span>
            {msg.model_used && <span className="lab-msg-model">{msg.model_used}</span>}
            {msg.tokens_out > 0 && (
              <span className="lab-msg-tokens">{msg.tokens_in}→{msg.tokens_out}t · {msg.duration_ms}ms</span>
            )}
          </div>
          {isExpanded ? (
            <>
              {!(messageType === 'tool_call' && msg.tool_name) && (
                <div className="lab-msg-content">{renderMsgContent(content)}</div>
              )}
              {msg.tool_name && (
                <div className={`lab-msg-tool ${isTerminalTool ? 'lab-msg-tool-terminal' : ''}`}>
                  <div className="lab-msg-tool-header">
                    {isTerminalTool ? (
                      <span className="lab-msg-tool-terminal-title">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                        {msg.tool_name === 'python_exec' ? 'Python' : msg.tool_name === 'shell_exec' ? 'Shell' : 'SQL'}
                      </span>
                    ) : (
                      <span>{IC.tool} {msg.tool_name}</span>
                    )}
                    {msg.tool_output && (
                      <span className={`lab-msg-tool-status ${msg.tool_output.success === false ? 'error' : 'success'}`}>
                        {msg.tool_output.success === false ? '✗ failed' : '✓ ok'}
                      </span>
                    )}
                  </div>
                  {msg.tool_input && (
                    <pre className="lab-msg-tool-code">{
                      (msg.tool_name === 'python_exec' || msg.tool_name === 'shell_exec')
                        ? (msg.tool_input.code || msg.tool_input.command || '')
                        : (['db_query','db_execute','db_schema'].includes(msg.tool_name))
                        ? (msg.tool_input.sql || JSON.stringify(msg.tool_input, null, 2))
                        : JSON.stringify(msg.tool_input, null, 2)
                    }</pre>
                  )}
                  {msg.tool_output && (
                    <pre className="lab-msg-tool-output">{typeof msg.tool_output === 'string' ? msg.tool_output : (msg.tool_output.output || JSON.stringify(msg.tool_output, null, 2))}</pre>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="lab-msg-preview">{preview}</div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="agents-feed">
      <div className="lab-timeline-header">
        <div className="lab-timeline-info" style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>{instance.name}</h2>
          {(() => { const b = statusBadge(instance); return <span className={b.className}>{b.label}</span>; })()}
          {instance.current_iteration > 0 && (
            <span className="lab-iter-badge">
              Iteration {instance.current_iteration}{instance.max_iterations ? ` / ${instance.max_iterations}` : ''}
            </span>
          )}
        </div>
        <div className="lab-timeline-actions">
          {isCreated && (
            <button className="lab-btn-action lab-btn-run" disabled={!!busy} onClick={onRun} title="Run">
              ▶ Run
            </button>
          )}
          {isDone && (
            <>
              <button className="lab-btn-action lab-btn-run" disabled={!!busy} onClick={onRun} title="Continue from where it stopped">
                ▶ Continue
              </button>
              <button className="lab-btn-action lab-btn-reset" disabled={!!busy} onClick={onReset} title="Reset to fresh state">
                ↺ Reset
              </button>
            </>
          )}
          {isRunning && (
            <button className="lab-btn-action lab-btn-pause" disabled={!!busy} onClick={onPause} title="Pause">
              ⏸ Pause
            </button>
          )}
          {isPaused && (
            <button className="lab-btn-action lab-btn-run" disabled={!!busy} onClick={onResume} title="Resume">
              ▶ Resume
            </button>
          )}
          {(isRunning || isPaused) && (
            <button className="lab-btn-action lab-btn-stop" disabled={!!busy} onClick={onStop} title="Stop">
              ■ Stop
            </button>
          )}
          {messages.length > 0 && (
            <button className="lab-btn-action lab-btn-ghost" onClick={onToggleExpandAll} title={allExpanded ? 'Collapse all' : 'Expand all'}>
              {allExpanded ? '▾ Collapse' : '▸ Expand'}
            </button>
          )}
          <button
            className="lab-toolbar-close-btn"
            onClick={onClose}
            title="Close"
            aria-label="Close"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
          </button>
        </div>
      </div>

      <div className="agents-feed-messages" ref={messagesEndRef}>
        {messages.length === 0 ? (
          <div className="agents-feed-empty">No messages yet. Run the agent to start.</div>
        ) : messages.map(renderMessage)}
      </div>

      {outputFiles.length > 0 && (
        <div className="agents-feed-outputs">
          <div className="agents-feed-outputs-title">Output files</div>
          <div className="agents-feed-outputs-list">
            {outputFiles.map((f, i) => (
              <button
                key={i}
                className="agents-feed-output-link"
                onClick={() => onOpenOutputFile && onOpenOutputFile(f.path, f.name)}
                title="Open in viewer"
              >
                {f.name || f.path}
              </button>
            ))}
          </div>
        </div>
      )}

      {isAwaitingInput(instance) && (
        <div className="agents-feed-await-hint">
          Waiting for user input — type a message below to start the agent.
        </div>
      )}
      <div className="agents-feed-inject">
        <textarea
          placeholder={isAwaitingInput(instance) ? 'Type a message to start the agent…' : 'Send a message to the agent…'}
          value={injectText}
          onChange={e => setInjectText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) onInject();
          }}
          rows={2}
        />
        <button
          className="agents-btn-save"
          onClick={onInject}
          disabled={!injectText.trim()}
        >Send</button>
      </div>
    </div>
  );
}

/* ── Right inspector for a selected instance ── */
function InstanceInspector(props) {
  const { tab, setTab } = props;
  const tabs = [
    { id: 'agent', label: 'Agent' },
    { id: 'resources', label: 'Resources' },
    { id: 'memory', label: 'Memory' },
    { id: 'links', label: 'Links' },
  ];
  return (
    <aside className="agents-inspector">
      <div className="agents-inspector-tabs">
        {tabs.map(t => (
          <button
            key={t.id}
            className={`agents-inspector-tab${tab === t.id ? ' agents-inspector-tab--active' : ''}`}
            onClick={() => setTab(t.id)}
          >{t.label}</button>
        ))}
      </div>
      <div className="agents-inspector-body">
        {tab === 'agent' && <InspectorAgentTab {...props} />}
        {tab === 'resources' && <InspectorResourcesTab {...props} />}
        {tab === 'memory' && <InspectorMemoryTab {...props} />}
        {tab === 'links' && <InspectorLinksTab {...props} />}
      </div>
    </aside>
  );
}

function InspectorAgentTab({
  instance, template, labAgents, editingLabAgent, setEditingLabAgent,
  beginEditLabAgent, saveEditLabAgent, cancelEditLabAgent,
  allModels, toolSets = [], pipelines = [], builtinTools = [], promptTemplates = [],
  onDelete, onOpenPromptEditor,
}) {
  const a = labAgents[0];
  const modelById = React.useMemo(
    () => new Map((allModels || []).map(m => [m.id, m])),
    [allModels]
  );
  const resolveModelName = (id) =>
    (id && modelById.get(id)?.model_identifier) || 'Default';

  return (
    <div className="agents-inspector-section">
      <div className="agents-inspector-row">
        <span className="agents-inspector-label">Status</span>
        {(() => { const b = statusBadge(instance); return <span className={b.className}>{b.label}</span>; })()}
      </div>
      <div className="agents-inspector-row">
        <span className="agents-inspector-label">Iteration</span>
        <b>{instance.current_iteration ?? 0}{instance.max_iterations ? ` / ${instance.max_iterations}` : ''}</b>
      </div>
      <div className="agents-inspector-row">
        <span className="agents-inspector-label">Started</span>
        <span>{instance.started_at ? new Date(instance.started_at).toLocaleString() : '—'}</span>
      </div>
      <div className="agents-inspector-row">
        <span className="agents-inspector-label">Created</span>
        <span>{instance.created_at ? new Date(instance.created_at).toLocaleString() : '—'}</span>
      </div>
      {template && (
        <div className="agents-inspector-row">
          <span className="agents-inspector-label">Template</span>
          <span>{template.name}</span>
        </div>
      )}

      <div className="agents-inspector-divider" />

      {!a ? (
        <div className="agents-feed-empty">No underlying agent found.</div>
      ) : (
        <div className="lab-agent-card" style={{ cursor: 'default', marginBottom: 8 }}>
          {editingLabAgent ? (
            <AgentEditForm
              agent={editingLabAgent}
              allModels={allModels}
              toolSets={toolSets}
              promptTemplates={promptTemplates}
              agents={labAgents}
              availablePipelines={pipelines}
              builtinTools={builtinTools}
              showShareMemory={false}
              showAntiLoop
              onOpenPromptEditor={onOpenPromptEditor}
              onSave={(data) => {
                setEditingLabAgent({ ...editingLabAgent, ...data });
                setTimeout(() => saveEditLabAgent({ ...editingLabAgent, ...data }), 0);
              }}
              onCancel={cancelEditLabAgent}
            />
          ) : (
            <>
              <div className="lab-agent-header">
                <div className="lab-agent-info">
                  <span className="lab-agent-name">{IC.bot} {a.name}</span>
                  {a.role && <span className="lab-agent-role">{a.role}</span>}
                </div>
                <div className="lab-agent-actions">
                  <button className="lab-btn-xs" onClick={beginEditLabAgent} title="Edit agent">✏️</button>
                </div>
              </div>
              <div className="lab-agent-details">
                <div className="lab-agent-detail">
                  <span className="lab-detail-label">Model</span>
                  <span className="lab-detail-value">{resolveModelName(a.model_id) || a.model || 'Default'}</span>
                </div>
                <div className="lab-agent-detail">
                  <span className="lab-detail-label">Temp</span>
                  <span className="lab-detail-value">{a.temperature ?? '—'}</span>
                </div>
                {a.system_prompt && (
                  <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                    <span className="lab-detail-label">Prompt</span>
                    <span className="lab-detail-value lab-prompt-preview">{a.system_prompt}</span>
                  </div>
                )}
                <div className="lab-agent-detail">
                  <span className="lab-detail-label">Active</span>
                  <span className="lab-detail-value" style={{ color: a.is_active ? '#22c55e' : '#ef4444' }}>
                    {a.is_active ? 'Yes' : 'No'}
                  </span>
                </div>
                <div className="lab-agent-detail">
                  <span className="lab-detail-label">Anti loop</span>
                  <span className="lab-detail-value" style={{ color: a.anti_loop_enabled ? '#a855f7' : 'rgba(255,255,255,0.4)' }}>
                    {a.anti_loop_enabled ? 'On' : 'Off'}
                  </span>
                </div>
                {(a.tools?.length > 0 || a.tool_set_ids?.length > 0) && (
                  <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                    <span className="lab-detail-label">Tools</span>
                    <span className="lab-detail-value">
                      {a.tool_set_ids?.length > 0
                        ? `${a.tools?.length ?? 0} tools (+${a.tool_set_ids.length} sets)`
                        : a.tools.join(', ')
                      }
                    </span>
                  </div>
                )}
                {a.cron_expression && (
                  <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                    <span className="lab-detail-label">CRON</span>
                    <span className="lab-detail-value" style={{ color: '#a855f7' }}>
                      {a.cron_expression}{a.cron_instruction ? ` → ${a.cron_instruction}` : ''}
                    </span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function InspectorResourcesTab({ instance, resources, outputFiles, onUploadResource, onDeleteResource, onOpenResource, onOpenOutputFile }) {
  const fileInputRef = useRef(null);
  return (
    <div className="agents-inspector-section">
      <div className="agents-inspector-subhead">Inputs</div>
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={e => {
          const f = e.target.files?.[0];
          if (f) onUploadResource(f);
          e.target.value = '';
        }}
      />
      <button className="agents-btn-secondary" onClick={() => fileInputRef.current?.click()}>+ Upload</button>
      {resources.length === 0 ? (
        <div className="agents-feed-empty">No resources.</div>
      ) : resources.map(r => (
        <div key={r.id} className="lab-resource-card" style={{ cursor: 'pointer' }} onClick={() => onOpenResource && onOpenResource(r)}>
          <div className="lab-resource-header">
            <span className="lab-resource-icon">
              {r.resource_type === 'image' ? '🖼️' : r.resource_type === 'pdf' ? '📄' : r.resource_type === 'code' ? '💻' : '📁'}
            </span>
            <div className="lab-resource-info">
              <span className="lab-resource-name">{r.original_name || r.filename}</span>
              <span className="lab-resource-meta">
                {r.resource_type || 'file'}{r.size_bytes ? ` · ${r.size_bytes > 1024 ? `${(r.size_bytes/1024).toFixed(1)} KB` : `${r.size_bytes} B`}` : ''}
              </span>
            </div>
            <button
              className="lab-btn-xs"
              onClick={e => { e.stopPropagation(); downloadFile(getLabResourceUrl(instance.lab_id, r.id), r.original_name || r.filename); }}
              title="Download"
            >⬇</button>
            <button
              className="lab-btn-xs lab-btn-danger-xs"
              onClick={e => { e.stopPropagation(); onDeleteResource(r); }}
              title="Delete"
            >×</button>
          </div>
        </div>
      ))}

      <div className="agents-inspector-divider" />
      <div className="agents-inspector-subhead">Outputs</div>
      {outputFiles.length === 0 ? (
        <div className="agents-feed-empty">No output files yet.</div>
      ) : outputFiles.map((f, i) => (
        <div key={i} className="lab-resource-card" style={{ cursor: 'pointer' }} onClick={() => onOpenOutputFile && onOpenOutputFile(f.path, f.name)}>
          <div className="lab-resource-header">
            <span className="lab-resource-icon">📄</span>
            <div className="lab-resource-info">
              <span className="lab-resource-name">{f.name || f.path}</span>
              {f.size_bytes != null && (
                <span className="lab-resource-meta">{f.size_bytes > 1024 ? `${(f.size_bytes/1024).toFixed(1)} KB` : `${f.size_bytes} B`}</span>
              )}
            </div>
            <button
              className="lab-btn-xs"
              onClick={e => { e.stopPropagation(); downloadFile(getLabOutputFileUrl(instance.lab_id, f.path), f.name || f.path); }}
              title="Download"
            >⬇</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function InspectorMemoryTab({ memories, onToggleMemoryHidden }) {
  if (!memories.length) return <div className="agents-feed-empty">No memories.</div>;
  // Group by agent_id (or 'orchestrator')
  const groups = {};
  for (const m of memories) {
    const k = m.agent_name || (m.agent_id ? `agent:${m.agent_id}` : 'orchestrator');
    (groups[k] = groups[k] || []).push(m);
  }
  return (
    <div className="agents-inspector-section">
      {Object.entries(groups).map(([k, items]) => (
        <div key={k}>
          <div className="agents-inspector-subhead">{k}</div>
          {items.map(m => (
            <div key={m.id} className={`agents-feed-msg ${m.is_hidden ? 'agents-mem-hidden' : ''}`}>
              <div className="agents-feed-msg-head">
                <span className="agents-feed-msg-role">{m.memory_type || 'mem'}</span>
                <span className="agents-feed-msg-time">{m.created_at ? new Date(m.created_at).toLocaleString() : ''}</span>
                <button
                  className="agents-feed-msg-toggle"
                  onClick={() => onToggleMemoryHidden(m)}
                  title={m.is_hidden ? 'Unhide' : 'Hide'}
                >{m.is_hidden ? 'unhide' : 'hide'}</button>
              </div>
              <div className="agents-feed-msg-body">
                {typeof m.content === 'string' ? m.content : JSON.stringify(m.content)}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function InspectorLinksTab({
  ragCollectionsAll, ragAccess, onToggleRagLink, onUpdateRagFlag,
  web3Access, web3Candidates, onToggleWalletLink,
  serverAccess, serverCandidates, onToggleServerLink,
}) {
  return (
    <div className="agents-links">
      {/* RAG Collections */}
      <div className="agents-links-section">
        <h3 className="agents-links-section-title">RAG Collections</h3>
        {(ragCollectionsAll || []).length === 0 ? (
          <div className="agents-feed-empty">No RAG collections. Create one in the RAG page.</div>
        ) : (
          <div className="agents-links-list">
            {ragCollectionsAll.map(col => {
              const access = ragAccess.find(r => String(r.collection_id) === String(col.id));
              const linked = !!access;
              return (
                <div key={col.id} className="agents-link-card">
                  <div className="agents-link-card-row">
                    <div className="agents-link-card-info">
                      <div className="agents-link-card-name">
                        {col.display_name || col.name}
                        {col.rag_mode === 'lightrag' && (
                          <span className="agents-link-badge agents-link-badge--lightrag">LightRAG</span>
                        )}
                      </div>
                      <div className="agents-link-card-meta">
                        {col.document_count || 0} docs · {col.chunk_count || 0} chunks
                      </div>
                    </div>
                    <label className="agents-link-checkbox">
                      <input type="checkbox" checked={linked} onChange={() => onToggleRagLink(col)} />
                      Link
                    </label>
                  </div>
                  {linked && (
                    <div className="agents-link-flags">
                      <label>
                        <input type="checkbox" checked={access.can_read !== false} onChange={e => onUpdateRagFlag(col.id, 'can_read', e.target.checked)} />
                        Read
                      </label>
                      <label>
                        <input type="checkbox" checked={!!access.can_write} onChange={e => onUpdateRagFlag(col.id, 'can_write', e.target.checked)} />
                        Write
                      </label>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <div className="agents-links-hint">
          Linked collections provide <code>rag_search</code> and <code>rag_list_collections</code> tools.
        </div>
      </div>

      {/* Wallets */}
      <div className="agents-links-section">
        <h3 className="agents-links-section-title">Wallet Collections</h3>
        {(web3Candidates || []).length === 0 ? (
          <div className="agents-feed-empty">No tracked wallets. Add wallets in the Web3 page.</div>
        ) : (
          <div className="agents-links-list">
            {web3Candidates.map(wallet => {
              const access = web3Access.find(a => String(a.wallet_id) === String(wallet.wallet_id));
              const linked = !!access;
              return (
                <div key={wallet.wallet_id} className="agents-link-card">
                  <div className="agents-link-card-row">
                    <div className="agents-link-card-info">
                      <div className="agents-link-card-name">{wallet.label || wallet.address}</div>
                      <div className="agents-link-card-meta agents-link-mono">{wallet.address}</div>
                    </div>
                    <label className="agents-link-checkbox">
                      <input type="checkbox" checked={linked} onChange={() => onToggleWalletLink(wallet)} />
                      Link
                    </label>
                  </div>
                  {linked && (
                    <div className="agents-link-flags">
                      <span>Read-only</span>
                      <span><code>web3_portfolio</code></span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <div className="agents-links-hint">
          Linked wallets provide the read-only <code>web3_portfolio</code> tool.
        </div>
      </div>

      {/* Servers */}
      <div className="agents-links-section">
        <h3 className="agents-links-section-title">Servers</h3>
        {(serverCandidates || []).length === 0 ? (
          <div className="agents-feed-empty">No servers. Add servers in the Servers page.</div>
        ) : (
          <div className="agents-links-list">
            {serverCandidates.map(srv => {
              const access = serverAccess.find(a => String(a.server_id) === String(srv.server_id));
              const linked = !!access;
              const online = srv.status === 'online';
              return (
                <div key={srv.server_id} className="agents-link-card">
                  <div className="agents-link-card-row">
                    <div className="agents-link-card-info">
                      <div className="agents-link-card-name">
                        {srv.name}
                        <span className={`agents-link-badge ${online ? 'agents-link-badge--online' : 'agents-link-badge--offline'}`}>{srv.status}</span>
                      </div>
                      <div className="agents-link-card-meta agents-link-mono">{srv.host}</div>
                    </div>
                    <label className="agents-link-checkbox">
                      <input type="checkbox" checked={linked} onChange={() => onToggleServerLink(srv)} />
                      Link
                    </label>
                  </div>
                  {linked && (
                    <div className="agents-link-flags">
                      <span><code>control_server</code></span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <div className="agents-links-hint">
          Linked servers provide the <code>control_server</code> tool.
        </div>
      </div>
    </div>
  );
}

/* ── Empty-state dashboard ── */
function AgentsDashboard({ templates, instances, onSelectTemplate, onSelectInstance, onCreateInstance }) {
  const runningCount = instances.filter(i => i.status === 'running').length;
  const awaitingCount = instances.filter(isAwaitingInput).length;
  const pausedCount = instances.filter(i => i.status === 'paused').length - awaitingCount;
  const recent = [...instances]
    .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))
    .slice(0, 10);
  return (
    <div className="agents-dashboard">
      <h2>Agents Dashboard</h2>
      <div className="agents-dashboard-cards">
        <div className="agents-stat-card"><div className="agents-stat-value">{templates.length}</div><div className="agents-stat-label">Templates</div></div>
        <div className="agents-stat-card"><div className="agents-stat-value">{instances.length}</div><div className="agents-stat-label">Instances</div></div>
        <div className="agents-stat-card agents-stat-success"><div className="agents-stat-value">{runningCount}</div><div className="agents-stat-label">Running</div></div>
        <div className="agents-stat-card"><div className="agents-stat-value">{awaitingCount}</div><div className="agents-stat-label">Awaiting input</div></div>
        <div className="agents-stat-card"><div className="agents-stat-value">{pausedCount}</div><div className="agents-stat-label">Paused</div></div>
      </div>

      <div className="agents-dashboard-section">
        <h3>Recent instances</h3>
        {recent.length === 0 ? (
          <div className="agents-feed-empty">No instances yet. Click ⚡ on a template to create one.</div>
        ) : (
          <table className="agents-dashboard-table">
            <thead><tr><th>Name</th><th>Status</th><th>Iter</th><th>Updated</th></tr></thead>
            <tbody>
              {recent.map(inst => (
                <tr key={inst.lab_id} onClick={() => onSelectInstance(inst)}>
                  <td>{inst.name}</td>
                  <td>{(() => { const b = statusBadge(inst); return <span className={b.className}>{b.label}</span>; })()}</td>
                  <td>{inst.current_iteration ?? 0}</td>
                  <td>{inst.updated_at ? new Date(inst.updated_at).toLocaleString() : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="agents-dashboard-section">
        <h3>Templates</h3>
        {templates.length === 0 ? (
          <div className="agents-feed-empty">No templates yet.</div>
        ) : (
          <div className="agents-dashboard-templates">
            {templates.slice(0, 12).map(t => (
              <div key={t.id} className="agents-dashboard-template-card">
                <div className="agents-tool-name" onClick={() => onSelectTemplate(t)} style={{ cursor: 'pointer' }}>{t.name}</div>
                {t.description && <div className="agents-tool-desc">{t.description}</div>}
                <button className="agents-btn-secondary" onClick={() => onCreateInstance(t)}>⚡ Instance</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AgentsView({ allModels: allModelsRaw = [] }) {
  // Deduplicate models by model_identifier (prefer available rows).
  // Mirrors LabsView so the orchestrator/agent dropdown is identical here.
  const allModels = React.useMemo(() => {
    const map = new Map();
    for (const m of allModelsRaw) {
      const existing = map.get(m.model_identifier);
      if (!existing || (m.is_available && !existing.is_available)) {
        map.set(m.model_identifier, m);
      }
    }
    return Array.from(map.values()).sort((a, b) =>
      (a.model_identifier || '').localeCompare(b.model_identifier || '')
    );
  }, [allModelsRaw]);

  const [agents, setAgents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [editForm, setEditForm] = useState(null); // null = no selection, object = editing
  const [creating, setCreating] = useState(false);
  const [toolSets, setToolSets] = useState([]);
  const [pipelines, setPipelines] = useState([]);
  const [builtinTools, setBuiltinTools] = useState([]);
  const [promptTemplates, setPromptTemplates] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [saving, setSaving] = useState(false);
  // Stats panel (Feature 2)
  const [agentLabs, setAgentLabs] = useState([]);
  const [agentStats, setAgentStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Agent Instances (single-agent runnable labs)
  const [instances, setInstances] = useState([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState(null);
  const [sectionOpen, setSectionOpen] = useState({ templates: true, instances: true });
  const [instanceBusy, setInstanceBusy] = useState({}); // { lab_id: 'run'|'pause'|... }
  const [pendingInstance, setPendingInstance] = useState(null); // { template, pseudo }
  const [creatingInstance, setCreatingInstance] = useState(false);

  // Right inspector tab for selected instance: 'agent'|'resources'|'memory'|'links'
  const [inspectorTab, setInspectorTab] = useState('agent');

  // Per-instance data (loaded when an instance is selected)
  const [instanceLabAgents, setInstanceLabAgents] = useState([]);
  const [instanceMessages, setInstanceMessages] = useState([]);
  const [instanceMemories, setInstanceMemories] = useState([]);
  const [instanceResources, setInstanceResources] = useState([]);
  const [instanceOutputFiles, setInstanceOutputFiles] = useState([]);
  const [instanceRagAccess, setInstanceRagAccess] = useState([]);
  const [ragCollectionsAll, setRagCollectionsAll] = useState([]);
  const [instanceWeb3Access, setInstanceWeb3Access] = useState([]);
  const [instanceWeb3Candidates, setInstanceWeb3Candidates] = useState([]);
  const [instanceServerAccess, setInstanceServerAccess] = useState([]);
  const [instanceServerCandidates, setInstanceServerCandidates] = useState([]);
  const [injectText, setInjectText] = useState('');
  const [expandedMessages, setExpandedMessages] = useState({});
  const [allMessagesExpanded, setAllMessagesExpanded] = useState(false);
  const [feedMenuOpen, setFeedMenuOpen] = useState(false);
  const [editingLabAgent, setEditingLabAgent] = useState(null); // form draft when overriding
  const [promptEditor, setPromptEditor] = useState(null); // { agentId, agentName, value, dirty }
  const [fileViewer, setFileViewer] = useState(null); // { type:'output'|'resource', path?, resourceId?, name }
  const [fileViewerData, setFileViewerData] = useState(null);
  const [fileViewerLoading, setFileViewerLoading] = useState(false);
  const [fileViewerBlobUrl, setFileViewerBlobUrl] = useState(null);

  // Filter outputs to exclude files that are also uploaded resources
  const resourceFilenames = new Set(instanceResources.map(r => r.filename));
  const filteredOutputFiles = instanceOutputFiles.filter(
    f => !resourceFilenames.has(f.name) && !resourceFilenames.has(f.path)
  );

  const messagesEndRef = useRef(null);

  const loadAgents = useCallback(async () => {
    try {
      const res = await getLibraryAgents();
      setAgents(res.data || []);
    } catch (e) { console.error('Failed to load agents', e); }
  }, []);

  const loadInstances = useCallback(async () => {
    try {
      const res = await getAgentInstances();
      setInstances(res.data || []);
    } catch (e) { console.error('Failed to load agent instances', e); }
  }, []);

  useEffect(() => {
    loadAgents();
    loadInstances();
    getToolSets().then(r => setToolSets(r.data || [])).catch(() => {});
    getPipelines().then(r => setPipelines(r.data || [])).catch(() => {});
    getBuiltinTools().then(r => setBuiltinTools(r.data || [])).catch(() => {});
    getPromptTemplates().then(r => setPromptTemplates(r.data || [])).catch(() => {});
  }, [loadAgents, loadInstances]);

  // Auto-refresh instance statuses while any of them are running/paused
  useEffect(() => {
    const hasActive = instances.some(i => i.status === 'running' || i.status === 'paused');
    if (!hasActive) return;
    const t = setInterval(() => { loadInstances(); }, 3000);
    return () => clearInterval(t);
  }, [instances, loadInstances]);

  const selectAgent = (agent) => {
    setSelectedId(agent.id);
    setSelectedInstanceId(null);
    setEditForm({ ...agent });
    setCreating(false);
  };

  const selectInstance = (inst) => {
    setSelectedInstanceId(inst.lab_id);
    setSelectedId(null);
    setEditForm(null);
    setCreating(false);
  };

  const startCreate = () => {
    setSelectedId(null);
    setSelectedInstanceId(null);
    setEditForm({ ...EMPTY_AGENT });
    setCreating(true);
  };

  // ── Instance lifecycle ──
  const startCreateInstance = (template) => {
    setPendingInstance({ template, pseudo: '' });
    setSectionOpen(s => ({ ...s, instances: true }));
  };
  const cancelCreateInstance = () => setPendingInstance(null);
  const confirmCreateInstance = async () => {
    if (!pendingInstance) return;
    setCreatingInstance(true);
    try {
      const res = await createAgentInstance(pendingInstance.template.id, {
        pseudo: pendingInstance.pseudo.trim() || null,
      });
      setPendingInstance(null);
      await loadInstances();
      if (res?.data?.lab_id) selectInstance(res.data);
    } catch (e) {
      console.error('Failed to create instance', e);
      alert(e?.response?.data?.detail || 'Failed to create instance');
    } finally {
      setCreatingInstance(false);
    }
  };

  const handleDeleteInstance = async (inst) => {
    if (!window.confirm(`Delete instance "${inst.name}"?`)) return;
    try {
      await deleteAgentInstance(inst.lab_id);
      if (selectedInstanceId === inst.lab_id) setSelectedInstanceId(null);
      await loadInstances();
    } catch (e) { console.error('Failed to delete instance', e); }
  };

  const runInstanceAction = async (inst, action) => {
    setInstanceBusy(b => ({ ...b, [inst.lab_id]: action }));
    try {
      if (action === 'run') await runAgentInstance(inst.lab_id);
      else if (action === 'pause') await pauseAgentInstance(inst.lab_id);
      else if (action === 'resume') await resumeAgentInstance(inst.lab_id);
      else if (action === 'stop') await stopAgentInstance(inst.lab_id);
      else if (action === 'reset') await runAgentInstance(inst.lab_id, { reset: true });
      await loadInstances();
      if (action === 'reset') await loadInstanceData(inst.lab_id);
    } catch (e) {
      console.error(`Failed to ${action} instance`, e);
      alert(e?.response?.data?.detail || `Failed to ${action} instance`);
    } finally {
      setInstanceBusy(b => { const n = { ...b }; delete n[inst.lab_id]; return n; });
    }
  };

  const handleResetInstance = async (inst) => {
    if (!window.confirm(`Reset "${inst.name}"? This clears all messages, memories and outputs.`)) return;
    setInstanceBusy(b => ({ ...b, [inst.lab_id]: 'reset' }));
    try {
      // Stop runner first if active
      if (inst.status === 'running' || inst.status === 'paused') {
        try { await stopAgentInstance(inst.lab_id); } catch (e) { /* ignore */ }
        // brief wait so the runner registry releases
        await new Promise(r => setTimeout(r, 600));
      }
      await resetLab(inst.lab_id);
      await loadInstances();
      await loadInstanceData(inst.lab_id);
    } catch (e) {
      console.error('Failed to reset instance', e);
      alert(e?.response?.data?.detail || 'Failed to reset instance');
    } finally {
      setInstanceBusy(b => { const n = { ...b }; delete n[inst.lab_id]; return n; });
    }
  };
  const handleContinueInstance = async (inst) => {
    if (inst.status === 'running') return runInstanceAction(inst, 'pause');setFileViewer(null); setFileViewerData(null); if (fileViewerBlobUrl) { URL.revokeObjectURL(fileViewerBlobUrl); setFileViewerBlobUrl(null); } 
    if (inst.status === 'paused') return runInstanceAction(inst, 'resume');
    return runInstanceAction(inst, 'run');
  };
  const closeInstance = () => { setSelectedInstanceId(null); setPromptEditor(null); };

  // ── Per-instance loaders ──
  const loadInstanceData = useCallback(async (labId) => {
    if (!labId) return;
    try {
      const [a, m, mem, r, o] = await Promise.all([
        getLabAgents(labId).catch(() => ({ data: [] })),
        getLabMessages(labId).catch(() => ({ data: [] })),
        getLabMemories(labId).catch(() => ({ data: [] })),
        getLabResources(labId).catch(() => ({ data: [] })),
        getLabOutputFiles(labId).catch(() => ({ data: [] })),
      ]);
      setInstanceLabAgents(a.data || []);
      setInstanceMessages(m.data || []);
      setInstanceMemories(mem.data || []);
      setInstanceResources(r.data || []);
      setInstanceOutputFiles(o.data || []);
    } catch (e) { console.error('Failed loading instance data', e); }
  }, []);

  const loadInstanceLinks = useCallback(async (labId) => {
    if (!labId) return;
    try {
      const [rag, ragAll, w3a, w3c, sa, sc] = await Promise.all([
        getLabRagAccess(labId).catch(() => ({ data: [] })),
        getRagCollections().catch(() => ({ data: [] })),
        getLabWeb3Access(labId).catch(() => ({ data: [] })),
        getLabWeb3Candidates(labId).catch(() => ({ data: [] })),
        getLabServerAccess(labId).catch(() => ({ data: [] })),
        getLabServerCandidates(labId).catch(() => ({ data: [] })),
      ]);
      setInstanceRagAccess(rag.data || []);
      setRagCollectionsAll(ragAll.data || []);
      setInstanceWeb3Access(w3a.data || []);
      setInstanceWeb3Candidates(w3c.data || []);
      setInstanceServerAccess(sa.data || []);
      setInstanceServerCandidates(sc.data || []);
    } catch (e) { console.error('Failed loading instance links', e); }
  }, []);

  // Load per-instance data when an instance is selected
  useEffect(() => {
    if (!selectedInstanceId) {
      setInstanceLabAgents([]); setInstanceMessages([]); setInstanceMemories([]);
      setInstanceResources([]); setInstanceOutputFiles([]); setEditingLabAgent(null);
      return;
    }
    loadInstanceData(selectedInstanceId);
    loadInstanceLinks(selectedInstanceId);
  }, [selectedInstanceId, loadInstanceData, loadInstanceLinks]);

  // Poll the selected instance's data AND the instance list while open.
  // We deliberately do NOT gate on status===running/paused — a completed
  // lab can be woken up by inject (handleInjectInstance), and without
  // polling here the badge stays stale until the user remounts the panel.
  // Verified via DevTools Network: the previous gate caused the entire
  // bug — when no instance was active, instances-list polling never
  // started, so the badge couldn't refresh after inject.
  useEffect(() => {
    if (!selectedInstanceId) return;
    const t = setInterval(() => {
      loadInstanceData(selectedInstanceId);
      loadInstances();
    }, 3000);
    return () => clearInterval(t);
  }, [selectedInstanceId, loadInstanceData, loadInstances]);

  // Auto-scroll feed when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) messagesEndRef.current.scrollTop = messagesEndRef.current.scrollHeight;
  }, [instanceMessages.length]);

  const handleInjectInstance = async () => {
    if (!selectedInstanceId || !injectText.trim()) return;
    try {
      await injectLabMessage(selectedInstanceId, { content: injectText.trim() });
      setInjectText('');
      // Refresh the instance LIST too — inject on a completed lab flips the
      // status to running, but without this the polling effect below stays
      // dormant (it gates on status), leaving the badge stuck on "completed"
      // until the user navigates away and back.
      await Promise.all([
        loadInstances(),
        loadInstanceData(selectedInstanceId),
      ]);
    } catch (e) {
      console.error('Failed to inject', e);
      alert(e?.response?.data?.detail || 'Failed to inject message');
    }
  };

  // ── File viewer (central panel) ──
  const openOutputFile = async (filePath, displayName) => {
    if (!selectedInstanceId) return;
    setFileViewer({ type: 'output', path: filePath, name: displayName || filePath.split('/').pop() });
    setFileViewerLoading(true);
    setFileViewerData(null);
    if (fileViewerBlobUrl) { URL.revokeObjectURL(fileViewerBlobUrl); setFileViewerBlobUrl(null); }
    try {
      const res = await getLabOutputFileContent(selectedInstanceId, filePath);
      setFileViewerData(res.data);
      const d = res.data;
      if (d?.is_image || d?.is_audio || d?.is_video) {
        const url = await getAuthBlobUrl(getLabOutputFileUrl(selectedInstanceId, filePath));
        setFileViewerBlobUrl(url);
      }
    } catch (e) { console.error('Open output failed', e); }
    setFileViewerLoading(false);
  };
  const openResourceFile = async (resource) => {
    if (!selectedInstanceId) return;
    setFileViewer({ type: 'resource', resourceId: resource.id, name: resource.original_name || resource.filename });
    setFileViewerLoading(true);
    setFileViewerData(null);
    if (fileViewerBlobUrl) { URL.revokeObjectURL(fileViewerBlobUrl); setFileViewerBlobUrl(null); }
    try {
      const res = await getLabResourceContent(selectedInstanceId, resource.id);
      setFileViewerData(res.data);
      const d = res.data;
      if (d?.is_image || d?.is_audio || d?.is_video) {
        const url = await getAuthBlobUrl(getLabResourceUrl(selectedInstanceId, resource.id));
        setFileViewerBlobUrl(url);
      }
    } catch (e) { console.error('Open resource failed', e); }
    setFileViewerLoading(false);
  };
  const closeFileViewer = () => {
    if (fileViewerBlobUrl) URL.revokeObjectURL(fileViewerBlobUrl);
    setFileViewerBlobUrl(null);
    setFileViewer(null);
    setFileViewerData(null);
  };

  // ── Instance LabAgent override ──
  const beginEditLabAgent = () => {
    const a = instanceLabAgents[0];
    if (!a) return;
    setEditingLabAgent({ ...a });
  };
  const saveEditLabAgent = async (overrideData = null) => {
    if (!editingLabAgent || !selectedInstanceId) return;
    try {
      const source = overrideData || editingLabAgent;
      const { id: _id, lab_id: _lid, library_agent_id: _laid, created_at: _ca, updated_at: _ua, ...patch } = source;
      const targetId = editingLabAgent.id;
      await updateLabAgent(selectedInstanceId, targetId, patch);
      setEditingLabAgent(null);
      await loadInstanceData(selectedInstanceId);
    } catch (e) {
      console.error('Failed to update agent', e);
      alert(e?.response?.data?.detail || 'Failed to save agent');
    }
  };
  const cancelEditLabAgent = () => setEditingLabAgent(null);

  // ── Inspector links: toggles ──
  const toggleRagLink = async (collection) => {
    if (!selectedInstanceId) return;
    const linked = instanceRagAccess.find(r => r.collection_id === collection.id);
    try {
      if (linked) await revokeLabRagAccess(selectedInstanceId, collection.id);
      else await grantLabRagAccess(selectedInstanceId, { collection_id: collection.id, can_read: true, can_write: false });
      await loadInstanceLinks(selectedInstanceId);
    } catch (e) { console.error('Failed to toggle RAG access', e); }
  };
  const updateRagFlag = async (collectionId, field, value) => {
    if (!selectedInstanceId) return;
    try {
      await updateLabRagAccess(selectedInstanceId, collectionId, { [field]: value });
      await loadInstanceLinks(selectedInstanceId);
    } catch (e) { console.error('Failed to update RAG flag', e); }
  };
  const toggleWalletLink = async (wallet) => {
    if (!selectedInstanceId) return;
    const wid = wallet.wallet_id;
    const linked = instanceWeb3Access.find(w => String(w.wallet_id) === String(wid));
    try {
      if (linked) await revokeLabWeb3Access(selectedInstanceId, wid);
      else await grantLabWeb3Access(selectedInstanceId, [wid]);
      await loadInstanceLinks(selectedInstanceId);
    } catch (e) { console.error('Failed to toggle wallet link', e); }
  };
  const toggleServerLink = async (server) => {
    if (!selectedInstanceId) return;
    const sid = server.server_id;
    const linked = instanceServerAccess.find(s => String(s.server_id) === String(sid));
    try {
      if (linked) await revokeLabServerAccess(selectedInstanceId, sid);
      else await grantLabServerAccess(selectedInstanceId, [sid]);
      await loadInstanceLinks(selectedInstanceId);
    } catch (e) { console.error('Failed to toggle server link', e); }
  };
  const toggleMemoryHidden = async (memory) => {
    if (!selectedInstanceId) return;
    try {
      await toggleLabMemoryVisibility(selectedInstanceId, memory.id, !memory.is_hidden);
      await loadInstanceData(selectedInstanceId);
    } catch (e) { console.error('Failed to toggle memory visibility', e); }
  };
  const handleUploadResource = async (file) => {
    if (!selectedInstanceId || !file) return;
    try {
      await uploadLabResource(selectedInstanceId, file);
      await loadInstanceData(selectedInstanceId);
    } catch (e) {
      console.error('Failed to upload resource', e);
      alert(e?.response?.data?.detail || 'Failed to upload resource');
    }
  };
  const handleDeleteResource = async (resource) => {
    if (!selectedInstanceId) return;
    if (!window.confirm(`Delete resource "${resource.original_name || resource.filename}"?`)) return;
    try {
      await deleteLabResource(selectedInstanceId, resource.id);
      await loadInstanceData(selectedInstanceId);
    } catch (e) { console.error('Failed to delete resource', e); }
  };

  const handleSave = async () => {
    if (!editForm || !editForm.name.trim()) return;
    setSaving(true);
    try {
      if (creating) {
        const res = await createLibraryAgent(editForm);
        setAgents(prev => [...prev, res.data]);
        setSelectedId(res.data.id);
        setCreating(false);
      } else {
        await updateLibraryAgent(selectedId, editForm);
      }
      await loadAgents();
    } catch (e) { console.error('Failed to save agent', e); }
    setSaving(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this agent?')) return;
    try {
      await deleteLibraryAgent(id);
      if (selectedId === id) { setSelectedId(null); setEditForm(null); }
      await loadAgents();
    } catch (e) { console.error('Failed to delete agent', e); }
  };

  const handleDuplicate = async (agent) => {
    try {
      const res = await duplicateLibraryAgent(agent.id);
      await loadAgents();
      selectAgent(res.data);
    } catch (e) {
      // Fallback: manual duplicate if endpoint missing
      try {
        const dup = { ...agent, name: agent.name + ' (copy)' };
        delete dup.id; delete dup.created_at; delete dup.updated_at;
        const res2 = await createLibraryAgent(dup);
        await loadAgents();
        selectAgent(res2.data);
      } catch (e2) { console.error('Failed to duplicate agent', e2); }
    }
  };

  const toggleTool = (toolName) => {
    if (!editForm) return;
    const tools = editForm.tools || [];
    if (tools.includes(toolName)) {
      setEditForm({ ...editForm, tools: tools.filter(t => t !== toolName) });
    } else {
      setEditForm({ ...editForm, tools: [...tools, toolName] });
    }
  };

  const addToolSetTools = (tsId) => {
    const ts = toolSets.find(t => t.id === tsId);
    if (!ts || !editForm) return;
    const merged = [...new Set([...(editForm.tools || []), ...(ts.tools || [])])];
    setEditForm({ ...editForm, tools: merged });
  };

  const filteredAgents = agents.filter(a =>
    !searchQuery || a.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const filteredInstances = instances.filter(i =>
    !searchQuery || (i.name || '').toLowerCase().includes(searchQuery.toLowerCase())
  );
  const selectedInstance = instances.find(i => i.lab_id === selectedInstanceId) || null;

  // Load stats + labs for selected agent (Feature 2)
  useEffect(() => {
    if (!selectedId || creating) {
      setAgentLabs([]);
      setAgentStats(null);
      return;
    }
    let cancelled = false;
    setStatsLoading(true);
    Promise.all([
      getLibraryAgentLabs(selectedId).catch(() => ({ data: [] })),
      getLibraryAgentStats(selectedId).catch(() => ({ data: null })),
    ]).then(([labsRes, statsRes]) => {
      if (cancelled) return;
      setAgentLabs(labsRes.data || []);
      setAgentStats(statsRes.data || null);
      setStatsLoading(false);
    });
    return () => { cancelled = true; };
  }, [selectedId, creating]);

  return (
    <div className="agents-view">
      {/* ── Left: Agent List ── */}
      <aside className="agents-sidebar">
        <div className="agents-sidebar-header">
          <div className="agents-search-row">
            {IC.search}
            <input
              className="agents-search"
              placeholder="Search agents…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
          <button className="agents-btn-create" onClick={startCreate} title="New agent">
            {IC.plus} New
          </button>
        </div>
        <div className="agents-list">
          {/* ── Templates section ── */}
          <div className="agents-section-header" onClick={() => setSectionOpen(s => ({ ...s, templates: !s.templates }))}>
            <span className={`agents-section-chevron ${sectionOpen.templates ? 'open' : ''}`}>{IC.chevron}</span>
            <span className="agents-section-title">Templates</span>
            <span className="agents-section-count">{filteredAgents.length}</span>
          </div>
          {sectionOpen.templates && (
            <div className="agents-section-body">
              {filteredAgents.map(a => (
                <div
                  key={a.id}
                  className={`agents-list-item ${selectedId === a.id ? 'active' : ''}`}
                  onClick={() => selectAgent(a)}
                >
                  <div className="agents-list-item-top">
                    <span className="agents-list-name">{IC.bot} {a.name}</span>
                    {!a.is_active && <span className="agents-list-inactive">OFF</span>}
                  </div>
                  <div className="agents-list-meta">
                    {a.tools?.length > 0 && <span>{a.tools.length} tools</span>}
                    {a.description && <span className="agents-list-desc">{a.description.slice(0, 40)}</span>}
                  </div>
                  <div className="agents-list-actions">
                    <button
                      onClick={e => { e.stopPropagation(); startCreateInstance(a); }}
                      title="Create instance"
                      className="agents-list-action-primary"
                    >{IC.spark}</button>
                    <button onClick={e => { e.stopPropagation(); handleDuplicate(a); }} title="Duplicate">{IC.copy}</button>
                    <button onClick={e => { e.stopPropagation(); handleDelete(a.id); }} title="Delete">{IC.trash}</button>
                  </div>
                </div>
              ))}
              {filteredAgents.length === 0 && (
                <div className="agents-empty">No templates. Click "New" to create one.</div>
              )}
            </div>
          )}

          {/* ── Instance Agents section ── */}
          <div className="agents-section-header" onClick={() => setSectionOpen(s => ({ ...s, instances: !s.instances }))}>
            <span className={`agents-section-chevron ${sectionOpen.instances ? 'open' : ''}`}>{IC.chevron}</span>
            <span className="agents-section-title">Instance Agents</span>
            <span className="agents-section-count">{filteredInstances.length}</span>
          </div>
          {sectionOpen.instances && (
            <div className="agents-section-body">
              {pendingInstance && (
                <div className="agents-pending-instance">
                  <div className="agents-pending-template">
                    {IC.bot} <span className="agents-tool-name">{pendingInstance.template.name}</span>
                  </div>
                  <input
                    autoFocus
                    placeholder="Pseudo (e.g. Hot wallet)"
                    value={pendingInstance.pseudo}
                    onChange={e => setPendingInstance(p => ({ ...p, pseudo: e.target.value }))}
                    onKeyDown={e => {
                      if (e.key === 'Enter') confirmCreateInstance();
                      else if (e.key === 'Escape') cancelCreateInstance();
                    }}
                  />
                  <div className="agents-pending-actions">
                    <button
                      className="agents-btn-save"
                      onClick={confirmCreateInstance}
                      disabled={creatingInstance}
                    >{creatingInstance ? 'Saving…' : 'Save'}</button>
                    <button
                      className="agents-btn-secondary"
                      onClick={cancelCreateInstance}
                      disabled={creatingInstance}
                    >Cancel</button>
                  </div>
                </div>
              )}
              {filteredInstances.map(inst => {
                const busy = instanceBusy[inst.lab_id];
                const isRunning = inst.status === 'running';
                const isPaused = inst.status === 'paused';
                return (
                  <div
                    key={inst.lab_id}
                    className={`agents-list-item ${selectedInstanceId === inst.lab_id ? 'active' : ''}`}
                    onClick={() => selectInstance(inst)}
                  >
                    <div className="agents-list-item-top">
                      <span className="agents-list-name">{IC.bot} {inst.name}</span>
                      {(() => { const b = statusBadge(inst); return <span className={b.className}>{b.label}</span>; })()}
                    </div>
                    <div className="agents-list-meta">
                      {inst.current_iteration > 0 && (
                        <span>iter {inst.current_iteration}{inst.max_iterations ? `/${inst.max_iterations}` : ''}</span>
                      )}
                    </div>
                    <div className="agents-list-actions">
                      {!isRunning && !isPaused && (
                        <button
                          onClick={e => { e.stopPropagation(); runInstanceAction(inst, 'run'); }}
                          title="Run" disabled={!!busy}
                          className="agents-list-action-primary"
                        >{IC.play}</button>
                      )}
                      {isRunning && (
                        <button
                          onClick={e => { e.stopPropagation(); runInstanceAction(inst, 'pause'); }}
                          title="Pause" disabled={!!busy}
                        >{IC.pause}</button>
                      )}
                      {isPaused && (
                        <button
                          onClick={e => { e.stopPropagation(); runInstanceAction(inst, 'resume'); }}
                          title="Resume" disabled={!!busy}
                          className="agents-list-action-primary"
                        >{IC.play}</button>
                      )}
                      {(isRunning || isPaused) && (
                        <button
                          onClick={e => { e.stopPropagation(); runInstanceAction(inst, 'stop'); }}
                          title="Stop" disabled={!!busy}
                        >{IC.stop}</button>
                      )}
                      <button onClick={e => { e.stopPropagation(); handleDeleteInstance(inst); }} title="Delete">{IC.trash}</button>
                    </div>
                  </div>
                );
              })}
              {filteredInstances.length === 0 && (
                <div className="agents-empty">
                  No instances yet. Click {IC.spark} on a template to create one.
                </div>
              )}
            </div>
          )}
        </div>
      </aside>

      {/* ── Center: Template editor / Instance feed / Dashboard ── */}
      <main className="agents-editor">
        {selectedInstance && fileViewer ? (
          /* ═══ Central File Viewer ═══ */
          <div className="lab-file-viewer">
            <div className="lab-file-viewer-header">
              <button className="lab-btn-ghost" onClick={closeFileViewer} title="Back to feed">← Back</button>
              <span className="lab-file-viewer-name">📄 {fileViewer.name}</span>
              <button className="lab-btn-sm" style={{ marginLeft: 'auto' }} onClick={() => {
                const url = fileViewer.type === 'resource'
                  ? getLabResourceUrl(selectedInstanceId, fileViewer.resourceId)
                  : getLabOutputFileUrl(selectedInstanceId, fileViewer.path);
                downloadFile(url, fileViewer.name);
              }}>⬇ Download</button>
            </div>
            <div className="lab-file-viewer-body">
              <div className="lab-file-viewer-content">
                {fileViewerLoading ? (
                  <div className="lab-empty" style={{ paddingTop: 60 }}>Loading…</div>
                ) : fileViewerData?.is_image && fileViewerBlobUrl ? (
                  <div style={{ textAlign: 'center', padding: 20 }}>
                    <img src={fileViewerBlobUrl} alt={fileViewer.name} style={{ maxWidth: '100%', maxHeight: '80vh', borderRadius: 8 }} />
                  </div>
                ) : fileViewerData?.is_audio && fileViewerBlobUrl ? (
                  <div style={{ textAlign: 'center', padding: 40 }}>
                    <div style={{ fontSize: 48, marginBottom: 20 }}>🎵</div>
                    <audio controls src={fileViewerBlobUrl} style={{ width: '100%', maxWidth: 500 }} />
                  </div>
                ) : fileViewerData?.is_video && fileViewerBlobUrl ? (
                  <div style={{ textAlign: 'center', padding: 20 }}>
                    <video controls src={fileViewerBlobUrl} style={{ maxWidth: '100%', maxHeight: '80vh', borderRadius: 8 }} />
                  </div>
                ) : fileViewerData?.is_text && fileViewerData?.content != null ? (
                  <pre className="lab-file-viewer-pre">{fileViewerData.content}</pre>
                ) : (
                  <div className="lab-empty" style={{ paddingTop: 60 }}>
                    Binary file — cannot preview.
                    <br/><button className="lab-btn-ghost" onClick={() => {
                      const url = fileViewer.type === 'resource'
                        ? getLabResourceUrl(selectedInstanceId, fileViewer.resourceId)
                        : getLabOutputFileUrl(selectedInstanceId, fileViewer.path);
                      downloadFile(url, fileViewer.name);
                    }}>Download file</button>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : selectedInstance && promptEditor ? (
          /* ═══ Full-View System Prompt Editor ═══ */
          <div className="lab-prompt-editor-view">
            <div className="lab-file-viewer-header">
              <button className="lab-btn-ghost" onClick={() => setPromptEditor(null)} title="Back to timeline">← Back</button>
              <span className="lab-file-viewer-name">🤖 Agent Prompt: {promptEditor.agentName}</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <button
                  className="lab-btn-primary"
                  style={{ fontSize: '0.72rem', padding: '4px 12px' }}
                  disabled={!promptEditor.dirty}
                  onClick={async () => {
                    try {
                      await updateLabAgent(selectedInstanceId, promptEditor.agentId, { system_prompt: promptEditor.value });
                      const agRes = await getLabAgents(selectedInstanceId);
                      const updated = agRes.data.find(a => a.id === promptEditor.agentId);
                      if (updated && editingLabAgent?.id === promptEditor.agentId) {
                        setEditingLabAgent({ ...editingLabAgent, ...updated });
                      }
                      setInstanceLabAgents(agRes.data);
                    } catch (e) { console.error('Prompt save failed', e); }
                    setPromptEditor(prev => ({ ...prev, dirty: false }));
                  }}
                >💾 Save</button>
              </div>
            </div>
            <div className="lab-prompt-editor-body">
              <textarea
                className="lab-prompt-editor-textarea"
                value={promptEditor.value}
                onChange={e => setPromptEditor(prev => ({ ...prev, value: e.target.value, dirty: true }))}
                spellCheck={false}
                placeholder="System prompt…"
              />
            </div>
          </div>
        ) : selectedInstance ? (
          <InstanceFeed
            instance={selectedInstance}
            messages={instanceMessages}
            outputFiles={filteredOutputFiles}
            busy={instanceBusy[selectedInstance.lab_id]}
            onRun={() => runInstanceAction(selectedInstance, 'run')}
            onPause={() => runInstanceAction(selectedInstance, 'pause')}
            onResume={() => runInstanceAction(selectedInstance, 'resume')}
            onReset={() => handleResetInstance(selectedInstance)}
            onStop={() => runInstanceAction(selectedInstance, 'stop')}
            onClose={closeInstance}
            allExpanded={allMessagesExpanded}
            onToggleExpandAll={() => setAllMessagesExpanded(v => !v)}
            menuOpen={feedMenuOpen}
            setMenuOpen={setFeedMenuOpen}
            injectText={injectText}
            setInjectText={setInjectText}
            onInject={handleInjectInstance}
            messagesEndRef={messagesEndRef}
            expandedMessages={expandedMessages}
            setExpandedMessages={setExpandedMessages}
            onOpenOutputFile={openOutputFile}
          />
        ) : !editForm ? (
          <AgentsDashboard
            templates={agents}
            instances={instances}
            onSelectTemplate={selectAgent}
            onSelectInstance={selectInstance}
            onCreateInstance={startCreateInstance}
          />
        ) : (
          <div className="agents-editor-form">
            <div className="agents-editor-header">
              <h2>{creating ? 'New Agent' : editForm.name || 'Edit Agent'}</h2>
              <div className="agents-editor-actions">
                <label className="agents-toggle-label">
                  <input
                    type="checkbox"
                    checked={editForm.is_active}
                    onChange={e => setEditForm({ ...editForm, is_active: e.target.checked })}
                  />
                  Active
                </label>
                <button className="agents-btn-save" onClick={handleSave} disabled={saving}>
                  {IC.check} {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>

            <div className="agents-form-grid">
              {/* Name */}
              <div className="agents-field">
                <label>Name</label>
                <input
                  value={editForm.name}
                  onChange={e => setEditForm({ ...editForm, name: e.target.value })}
                  placeholder="Agent name"
                />
              </div>

              {/* Description */}
              <div className="agents-field">
                <label>Description</label>
                <input
                  value={editForm.description || ''}
                  onChange={e => setEditForm({ ...editForm, description: e.target.value })}
                  placeholder="Short description"
                />
              </div>

              {/* Backend */}
              <div className="agents-field">
                <label>Backend</label>
                <select
                  value={editForm.backend || 'native'}
                  onChange={e => setEditForm({ ...editForm, backend: e.target.value })}
                >
                  <option value="native">Native (Bob Lab loop)</option>
                  <option value="hermes">Hermes (external agent)</option>
                </select>
              </div>

              {(editForm.backend || 'native') === 'hermes' && editForm.id && (
                <div className="agents-field agents-field-full">
                  <HermesPanel agentKey={editForm.id} />
                </div>
              )}

              {/* Model */}
              <div className="agents-field">
                <label>{(editForm.backend || 'native') === 'hermes' ? 'Model Hermes uses' : 'Model (optional override)'}</label>
                <select
                  value={editForm.model_id || ''}
                  onChange={e => setEditForm({ ...editForm, model_id: e.target.value || null })}
                >
                  <option value="">Use conversation model</option>
                  {allModels.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.model_identifier}{m.is_available === false ? ' (offline)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* Temperature & Max Tokens */}
              <div className="agents-field-row">
                <div className="agents-field">
                  <label>Temperature</label>
                  <input
                    type="number" min="0" max="2" step="0.05"
                    value={editForm.temperature}
                    onChange={e => setEditForm({ ...editForm, temperature: parseFloat(e.target.value) || 0.7 })}
                  />
                </div>
                <div className="agents-field">
                  <label>Max Tokens</label>
                  <input
                    type="number" min="256" step="256"
                    value={editForm.max_tokens}
                    onChange={e => setEditForm({ ...editForm, max_tokens: parseInt(e.target.value) || 4096 })}
                  />
                </div>
              </div>

              {/* System Prompt */}
              <div className="agents-field agents-field-full">
                <label>System Prompt</label>
                <textarea
                  value={editForm.system_prompt || ''}
                  onChange={e => setEditForm({ ...editForm, system_prompt: e.target.value })}
                  placeholder="Instructions for the agent…"
                  rows={6}
                />
              </div>

              {/* Schedule (cron) */}
              <div className="agents-field agents-field-full agents-cron-section">
                <label>
                  Schedule (cron)
                  <span className="agents-label-count" style={{ color: 'rgba(255,255,255,0.4)' }}>
                    optional — runs this agent on a recurring schedule
                  </span>
                </label>
                <div className="agents-field-row">
                  <div className="agents-field" style={{ flex: '0 0 220px' }}>
                    <label style={{ fontSize: '0.65rem' }}>Cron expression</label>
                    <input
                      value={editForm.cron_expression || ''}
                      onChange={e => setEditForm({ ...editForm, cron_expression: e.target.value })}
                      placeholder="e.g. 0 9 * * 1-5"
                    />
                  </div>
                  <div className="agents-field">
                    <label style={{ fontSize: '0.65rem' }}>Cron instruction</label>
                    <input
                      value={editForm.cron_instruction || ''}
                      onChange={e => setEditForm({ ...editForm, cron_instruction: e.target.value })}
                      placeholder="What to do when triggered"
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: '0.7rem', color: 'rgba(255,255,255,0.55)' }}>
                  <label className="agents-toggle-label">
                    <input
                      type="checkbox"
                      checked={!!editForm.anti_loop_enabled}
                      onChange={e => setEditForm({ ...editForm, anti_loop_enabled: e.target.checked })}
                    />
                    Anti-loop
                  </label>
                  <label className="agents-toggle-label">
                    <input
                      type="checkbox"
                      checked={!!editForm.share_memory}
                      onChange={e => setEditForm({ ...editForm, share_memory: e.target.checked })}
                    />
                    Share memory
                  </label>
                </div>
              </div>

              {/* Tools — hidden for Hermes agents (Hermes runs its own tools) */}
              {(editForm.backend || 'native') === 'hermes' && (
                <div className="agents-field agents-field-full">
                  <label>Tools</label>
                  <div style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.45)' }}>
                    Hermes runs its own tools inside its container — Bob Lab tools don't apply.
                  </div>
                </div>
              )}
              {(editForm.backend || 'native') !== 'hermes' && (
              <div className="agents-field agents-field-full">
                <label>
                  Tools
                  <span className="agents-label-count">{(editForm.tools || []).length} selected</span>
                </label>

                {toolSets.length > 0 && (
                  <div className="agents-toolset-row">
                    <select
                      defaultValue=""
                      onChange={e => { if (e.target.value) { addToolSetTools(e.target.value); e.target.value = ''; } }}
                    >
                      <option value="">+ Add tool set…</option>
                      {toolSets.map(ts => (
                        <option key={ts.id} value={ts.id}>{ts.name} ({(ts.tools || []).length} tools)</option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="agents-tools-grid">
                  {builtinTools.map(t => {
                    if (t.expandable) {
                      return <ExpandableToolGroup key={t.name} toolDef={t} tools={editForm.tools || []} pipelines={pipelines}
                        onChange={next => setEditForm({ ...editForm, tools: next })} />;
                    }
                    if (t.subTools) {
                      return <SubToolGroup key={t.name} toolDef={t} tools={editForm.tools || []}
                        onChange={next => setEditForm({ ...editForm, tools: next })} />;
                    }
                    return (
                      <label key={t.name} className="agents-tool-checkbox">
                        <input
                          type="checkbox"
                          checked={(editForm.tools || []).includes(t.name)}
                          onChange={() => toggleTool(t.name)}
                        />
                        <span className="agents-tool-info">
                          <span className="agents-tool-name">{t.name.toUpperCase()}<SensitiveToolTag tool={t} /></span>
                          <span className="agents-tool-desc">{t.description}</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* ── Right: Instance Inspector (4 tabs) ── */}
      {selectedInstance && (
        <InstanceInspector
          instance={selectedInstance}
          template={agents.find(a => a.id === selectedInstance.library_agent_id) || null}
          tab={inspectorTab}
          setTab={setInspectorTab}
          labAgents={instanceLabAgents}
          editingLabAgent={editingLabAgent}
          setEditingLabAgent={setEditingLabAgent}
          beginEditLabAgent={beginEditLabAgent}
          saveEditLabAgent={saveEditLabAgent}
          cancelEditLabAgent={cancelEditLabAgent}
          allModels={allModels}
          toolSets={toolSets}
          pipelines={pipelines}
          builtinTools={builtinTools}
          promptTemplates={promptTemplates}
          resources={instanceResources}
          outputFiles={filteredOutputFiles}
          onUploadResource={handleUploadResource}
          onDeleteResource={handleDeleteResource}
          onOpenResource={openResourceFile}
          onOpenOutputFile={openOutputFile}
          memories={instanceMemories}
          onToggleMemoryHidden={toggleMemoryHidden}
          ragCollectionsAll={ragCollectionsAll}
          ragAccess={instanceRagAccess}
          onToggleRagLink={toggleRagLink}
          onUpdateRagFlag={updateRagFlag}
          web3Access={instanceWeb3Access}
          web3Candidates={instanceWeb3Candidates}
          onToggleWalletLink={toggleWalletLink}
          serverAccess={instanceServerAccess}
          serverCandidates={instanceServerCandidates}
          onToggleServerLink={toggleServerLink}
          busy={instanceBusy[selectedInstance.lab_id]}
          onAction={(action) => runInstanceAction(selectedInstance, action)}
          onDelete={() => handleDeleteInstance(selectedInstance)}
          onOpenPromptEditor={(info) => setPromptEditor({
            agentId: info.agentId,
            agentName: instanceLabAgents.find(a => a.id === info.agentId)?.name || 'Agent',
            value: info.value,
            dirty: false,
          })}
        />
      )}

      {/* ── Right: Stats panel (template only) ── */}
      {selectedId && !creating && !selectedInstance && (
        <aside className="agents-stats-panel">
          <div className="agents-stats-header">
            <h3>Usage</h3>
            {statsLoading && <span style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.3)' }}>loading…</span>}
          </div>
          <div className="agents-stats-grid">
            <div className="agents-stat-card">
              <div className="agents-stat-value">{agentStats?.labs_count ?? agentLabs.length ?? 0}</div>
              <div className="agents-stat-label">Labs</div>
            </div>
            <div className="agents-stat-card">
              <div className="agents-stat-value">{agentStats?.messages_total ?? 0}</div>
              <div className="agents-stat-label">Messages</div>
            </div>
            <div className="agents-stat-card agents-stat-success">
              <div className="agents-stat-value">{agentStats?.successes ?? 0}</div>
              <div className="agents-stat-label">Successes</div>
            </div>
            <div className="agents-stat-card agents-stat-failure">
              <div className="agents-stat-value">{agentStats?.failures ?? 0}</div>
              <div className="agents-stat-label">Failures</div>
            </div>
            <div className="agents-stat-card agents-stat-warn">
              <div className="agents-stat-value">{agentStats?.loop_triggers ?? 0}</div>
              <div className="agents-stat-label">Anti-loop</div>
            </div>
            <div className="agents-stat-card">
              <div className="agents-stat-value" style={{ fontSize: '0.85rem' }}>
                {((agentStats?.tokens_in_total ?? 0) + (agentStats?.tokens_out_total ?? 0)).toLocaleString()}
              </div>
              <div className="agents-stat-label">Tokens</div>
            </div>
          </div>
          {agentStats?.last_active && (
            <div className="agents-stats-lastactive">
              Last active: {new Date(agentStats.last_active).toLocaleString()}
            </div>
          )}
          {(() => {
            const instanceLabIds = new Set(instances.map(i => i.lab_id));
            const soloEntries = agentLabs.filter(l => instanceLabIds.has(l.lab_id));
            const labEntries = agentLabs.filter(l => !instanceLabIds.has(l.lab_id));
            const renderRow = (l, kind) => (
              <div
                key={l.lab_agent_id || l.lab_id}
                className="agents-stats-lab-row"
                onClick={() => {
                  if (kind === 'solo') {
                    const inst = instances.find(i => i.lab_id === l.lab_id);
                    if (inst) {
                      selectInstance(inst);
                      setSectionOpen(s => ({ ...s, instances: true }));
                    }
                  } else {
                    try { window.location.hash = `#labs?lab=${l.lab_id}`; } catch {}
                  }
                }}
                title={kind === 'solo' ? 'Open this solo agent' : 'Open this lab'}
              >
                <div className="agents-stats-lab-name">{l.lab_name}</div>
                <div className="agents-stats-lab-meta">
                  <span className={`agents-stats-lab-status agents-stats-lab-status--${l.status}`}>{l.status}</span>
                  {l.current_iteration > 0 && (
                    <span>iter {l.current_iteration}{l.max_iterations ? `/${l.max_iterations}` : ''}</span>
                  )}
                </div>
              </div>
            );
            return (
              <>
                <div className="agents-stats-section-title">Solo agents ({soloEntries.length})</div>
                <div className="agents-stats-labs-list">
                  {soloEntries.length === 0 ? (
                    <div className="agents-empty" style={{ padding: 12, fontSize: '0.7rem' }}>No solo agent instances yet.</div>
                  ) : soloEntries.map(l => renderRow(l, 'solo'))}
                </div>
                <div className="agents-stats-section-title">Used in labs ({labEntries.length})</div>
                <div className="agents-stats-labs-list">
                  {labEntries.length === 0 ? (
                    <div className="agents-empty" style={{ padding: 12, fontSize: '0.7rem' }}>Not used in any lab yet.</div>
                  ) : labEntries.map(l => renderRow(l, 'lab'))}
                </div>
              </>
            );
          })()}
        </aside>
      )}

      <style>{`
        .agents-view {
          display: flex;
          height: 100%;
          width: 100%;
          background: #0e0e0e;
          color: #e0e0e0;
          overflow: hidden;
        }

        /* ── Sidebar ── */
        .agents-sidebar {
          width: 280px;
          min-width: 280px;
          flex-shrink: 0;
          border-right: 1px solid rgba(255,255,255,0.06);
          display: flex;
          flex-direction: column;
        }
        .agents-sidebar-header {
          padding: 12px;
          display: flex;
          gap: 8px;
          align-items: center;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .agents-search-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex: 1;
          background: rgba(255,255,255,0.05);
          border-radius: 8px;
          padding: 4px 8px;
          color: rgba(255,255,255,0.4);
        }
        .agents-search {
          background: none;
          border: none;
          color: #e0e0e0;
          font-size: 0.78rem;
          outline: none;
          width: 100%;
        }
        .agents-btn-create {
          display: flex;
          align-items: center;
          gap: 4px;
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
          border: 1px solid rgba(185,28,28,0.3);
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: pointer;
          white-space: nowrap;
        }
        .agents-btn-create:hover { background: rgba(185,28,28,0.35); }
        .agents-list {
          flex: 1;
          overflow-y: auto;
          padding: 6px;
        }
        .agents-list-item {
          padding: 10px 12px;
          border-radius: 8px;
          cursor: pointer;
          margin-bottom: 2px;
          border: 1px solid transparent;
          position: relative;
        }
        .agents-list-item:hover {
          background: rgba(255,255,255,0.04);
        }
        .agents-list-item.active {
          background: rgba(185,28,28,0.12);
          border-color: rgba(185,28,28,0.25);
        }
        .agents-list-item-top {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .agents-list-name {
          font-size: 0.82rem;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 5px;
        }
        .agents-list-inactive {
          font-size: 0.6rem;
          background: rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.3);
          padding: 1px 5px;
          border-radius: 4px;
          font-weight: 600;
        }
        .agents-list-meta {
          display: flex;
          gap: 8px;
          font-size: 0.68rem;
          color: rgba(255,255,255,0.35);
          margin-top: 3px;
          padding-left: 23px;
        }
        .agents-list-desc {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .agents-list-actions {
          position: absolute;
          right: 8px;
          top: 8px;
          display: none;
          gap: 4px;
        }
        .agents-list-item:hover .agents-list-actions { display: flex; }
        .agents-list-actions button {
          background: rgba(255,255,255,0.06);
          border: none;
          color: rgba(255,255,255,0.4);
          padding: 3px 5px;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.7rem;
        }
        .agents-list-actions button:hover { color: #fff; background: rgba(255,255,255,0.12); }
        .agents-list-action-primary { color: #34d399 !important; background: rgba(52,211,153,0.10) !important; }
        .agents-list-action-primary:hover { background: rgba(52,211,153,0.22) !important; color: #fff !important; }
        .agents-list-actions button:disabled { opacity: 0.4; cursor: not-allowed; }

        /* ── Sidebar sections ── */
        .agents-section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 10px;
          margin: 4px 4px 2px;
          font-size: 0.68rem;
          font-weight: 700;
          color: rgba(255,255,255,0.55);
          text-transform: uppercase;
          letter-spacing: 0.6px;
          cursor: pointer;
          border-radius: 6px;
          user-select: none;
        }
        .agents-section-header:hover { background: rgba(255,255,255,0.04); color: #fff; }
        .agents-section-chevron {
          display: inline-flex;
          transition: transform 120ms ease;
          transform: rotate(-90deg);
          color: rgba(255,255,255,0.4);
        }
        .agents-section-chevron.open { transform: rotate(0deg); }
        .agents-section-title { flex: 1; }
        .agents-section-count {
          background: rgba(255,255,255,0.06);
          color: rgba(255,255,255,0.55);
          padding: 1px 6px;
          border-radius: 8px;
          font-size: 0.62rem;
          font-weight: 600;
          letter-spacing: 0;
        }
        .agents-section-body { display: flex; flex-direction: column; }

        /* ── Instance status pills ── */
        .agents-inst-status {
          font-size: 0.58rem;
          padding: 1px 6px;
          border-radius: 4px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          background: rgba(180,189,205,0.12);
          color: #b4bdcd;
        }
        .agents-inst-status--running { background: rgba(52,211,153,0.16); color: #34d399; }
        .agents-inst-status--paused { background: rgba(251,191,36,0.16); color: #fbbf24; }
        .agents-inst-status--awaiting { background: rgba(59,130,246,0.18); color: #60a5fa; }
        .agents-feed-await-hint {
          margin: 0 8px 4px 8px;
          padding: 6px 10px;
          font-size: 0.72rem;
          color: #60a5fa;
          background: rgba(59,130,246,0.10);
          border-left: 2px solid #60a5fa;
          border-radius: 3px;
        }
        .agents-inst-status--completed { background: rgba(34,211,238,0.14); color: #22d3ee; }
        .agents-inst-status--failed { background: rgba(248,113,113,0.16); color: #f87171; }
        .agents-inst-status--created { background: rgba(180,189,205,0.10); color: #b4bdcd; }

        /* ── Instance panel ── */
        .agents-instance-controls {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .agents-btn-secondary {
          background: rgba(255,255,255,0.06);
          color: #e0e0e0;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 8px;
          padding: 6px 12px;
          font-size: 0.78rem;
          font-weight: 600;
          cursor: pointer;
        }
        .agents-btn-secondary:hover { background: rgba(255,255,255,0.12); }
        .agents-btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
        .agents-btn-danger { color: #f87171; border-color: rgba(248,113,113,0.25); }
        .agents-btn-danger:hover { background: rgba(248,113,113,0.12); }
        .agents-instance-meta {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 8px;
        }
        .agents-instance-meta > div {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .agents-instance-meta span {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.4);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .agents-instance-meta b {
          font-size: 0.78rem;
          color: #e0e0e0;
          font-weight: 600;
        }
        .agents-instance-template {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px;
          padding: 10px 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .agents-empty {
          padding: 24px;
          text-align: center;
          color: rgba(255,255,255,0.25);
          font-size: 0.78rem;
        }

        /* ── Editor ── */
        .agents-editor {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .agents-editor > .agents-editor-form,
        .agents-editor > .agents-placeholder {
          flex: 1;
          overflow-y: auto;
          padding: 24px 32px;
        }
        .agents-placeholder {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: rgba(255,255,255,0.15);
          gap: 12px;
          font-size: 0.85rem;
        }
        .agents-placeholder svg { width: 48px; height: 48px; }
        .agents-editor-form {
          max-width: 780px;
        }
        .agents-editor-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 20px;
          padding-bottom: 12px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .agents-editor-header h2 {
          font-size: 1.1rem;
          font-weight: 600;
          margin: 0;
        }
        .agents-editor-actions {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .agents-toggle-label {
          display: flex;
          align-items: center;
          gap: 5px;
          font-size: 0.75rem;
          color: rgba(255,255,255,0.5);
          cursor: pointer;
        }
        .agents-btn-save {
          display: flex;
          align-items: center;
          gap: 4px;
          background: var(--accent, #b91c1c);
          color: white;
          border: none;
          border-radius: 8px;
          padding: 6px 14px;
          font-size: 0.78rem;
          font-weight: 600;
          cursor: pointer;
        }
        .agents-btn-save:hover { opacity: 0.9; }
        .agents-btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

        /* ── Form fields ── */
        .agents-form-grid {
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .agents-field label {
          display: block;
          font-size: 0.72rem;
          font-weight: 600;
          color: rgba(255,255,255,0.5);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 4px;
        }
        .agents-label-count {
          font-weight: 400;
          text-transform: none;
          letter-spacing: 0;
          margin-left: 8px;
          color: var(--accent, #b91c1c);
        }
        .agents-field input[type="text"],
        .agents-field input[type="number"],
        .agents-field input:not([type]),
        .agents-field select,
        .agents-field textarea {
          width: 100%;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 8px;
          color: #e0e0e0;
          padding: 8px 10px;
          font-size: 0.82rem;
          font-family: inherit;
          outline: none;
          box-sizing: border-box;
        }
        .agents-field textarea {
          resize: vertical;
          min-height: 80px;
        }
        .agents-field input:focus,
        .agents-field select:focus,
        .agents-field textarea:focus {
          border-color: rgba(185,28,28,0.4);
        }
        .agents-field-row {
          display: flex;
          gap: 12px;
        }
        .agents-field-row .agents-field { flex: 1; }
        .agents-field-full { width: 100%; }

        /* ── Tool set ── */
        .agents-toolset-row {
          margin-bottom: 8px;
        }
        .agents-toolset-row select {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 8px;
          color: #e0e0e0;
          padding: 6px 8px;
          font-size: 0.78rem;
          cursor: pointer;
        }

        /* ── Tools grid ── */
        .agents-tools-grid {
          display: flex;
          flex-direction: column;
          gap: 2px;
          width: 100%;
        }
        .agents-tool-checkbox {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 4px 0;
          cursor: pointer;
          font-size: 0.72rem;
          color: rgba(255,255,255,0.6);
          width: 100%;
        }
        .agents-tool-checkbox:hover {
          background: rgba(255,255,255,0.04);
        }
        .agents-tool-checkbox input[type="checkbox"] {
          accent-color: var(--accent, #b91c1c);
          margin-top: 2px;
          flex-shrink: 0;
          width: 14px;
          height: 14px;
        }
        .agents-tool-info {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
        }
        .agents-tool-name {
          font-weight: 600;
          font-size: 0.72rem;
          color: rgba(255,255,255,0.8);
        }
        .agents-tool-desc {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.35);
          line-height: 1.3;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        /* ── Cron section ── */
        .agents-cron-section {
          background: rgba(34,211,238,0.04);
          border: 1px solid rgba(34,211,238,0.18);
          border-radius: 10px;
          padding: 12px 14px;
        }
        .agents-cron-section > label:first-child {
          color: #22d3ee;
        }

        /* ── Right stats panel ── */
        .agents-stats-panel {
          width: 300px;
          min-width: 260px;
          border-left: 1px solid rgba(255,255,255,0.06);
          background: rgba(10,13,20,0.4);
          padding: 16px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .agents-stats-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .agents-stats-header h3 {
          font-size: 0.85rem;
          font-weight: 600;
          margin: 0;
          color: #22d3ee;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .agents-stats-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .agents-stat-card {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px;
          padding: 10px;
          text-align: center;
        }
        .agents-stat-value {
          font-size: 1.1rem;
          font-weight: 700;
          color: #e0e0e0;
        }
        .agents-stat-label {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.45);
          margin-top: 3px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .agents-stat-success { border-color: rgba(34,197,94,0.25); }
        .agents-stat-success .agents-stat-value { color: #22c55e; }
        .agents-stat-failure { border-color: rgba(239,68,68,0.25); }
        .agents-stat-failure .agents-stat-value { color: #ef4444; }
        .agents-stat-warn { border-color: rgba(251,191,36,0.25); }
        .agents-stat-warn .agents-stat-value { color: #fbbf24; }

        .agents-stats-lastactive {
          font-size: 0.65rem;
          color: rgba(255,255,255,0.4);
          text-align: center;
        }
        .agents-stats-section-title {
          font-size: 0.7rem;
          font-weight: 600;
          color: rgba(255,255,255,0.5);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-top: 4px;
          padding-top: 8px;
          border-top: 1px solid rgba(255,255,255,0.06);
        }
        .agents-stats-labs-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .agents-stats-lab-row {
          padding: 8px 10px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.05);
          border-radius: 6px;
          cursor: pointer;
        }
        .agents-stats-lab-row:hover {
          background: rgba(34,211,238,0.08);
          border-color: rgba(34,211,238,0.25);
        }
        .agents-stats-lab-name {
          font-size: 0.75rem;
          font-weight: 600;
          color: #e0e0e0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .agents-stats-lab-meta {
          display: flex;
          gap: 6px;
          font-size: 0.62rem;
          color: rgba(255,255,255,0.4);
          margin-top: 3px;
          align-items: center;
        }
        .agents-stats-lab-status {
          padding: 1px 6px;
          border-radius: 4px;
          font-weight: 600;
          text-transform: uppercase;
          font-size: 0.58rem;
        }
        .agents-stats-lab-status--running { background: rgba(52,211,153,0.14); color: #34d399; }
        .agents-stats-lab-status--paused { background: rgba(251,191,36,0.14); color: #fbbf24; }
        .agents-stats-lab-status--completed { background: rgba(34,211,238,0.14); color: #22d3ee; }
        .agents-stats-lab-status--failed { background: rgba(248,113,113,0.14); color: #f87171; }
        .agents-stats-lab-status--created { background: rgba(180,189,205,0.10); color: #b4bdcd; }

        /* ── Pending instance create form ── */
        .agents-pending-instance {
          background: rgba(99,102,241,0.08);
          border: 1px solid rgba(99,102,241,0.3);
          border-radius: 8px;
          padding: 0.6rem;
          margin-bottom: 0.5rem;
          display: flex;
          flex-direction: column;
          gap: 0.4rem;
        }
        .agents-pending-template {
          display: flex; align-items: center; gap: 0.4rem;
          font-size: 0.75rem; color: rgba(255,255,255,0.7);
        }
        .agents-pending-instance input {
          background: rgba(0,0,0,0.3);
          border: 1px solid rgba(255,255,255,0.12);
          color: #fff; padding: 0.4rem 0.55rem; border-radius: 6px;
          font-size: 0.78rem; outline: none;
        }
        .agents-pending-instance input:focus { border-color: #6366f1; }
        .agents-pending-actions { display: flex; gap: 0.4rem; }

        /* ── Central feed ── */
        .agents-feed {
          display: flex; flex-direction: column; height: 100%;
          gap: 0; overflow: hidden;
        }
        .agents-feed-topbar {
          display: flex; justify-content: space-between; align-items: center;
          padding: 10px 16px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
          background: rgba(15,15,20,0.5);
          gap: 12px;
        }
        .agents-feed-topbar-left {
          display: flex; align-items: center; gap: 10px;
          min-width: 0; flex: 1;
        }
        .agents-feed-topbar-left h2 {
          margin: 0; font-size: 0.95rem; color: #fff;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          max-width: 320px;
        }
        .agents-feed-iter { color: rgba(255,255,255,0.45); font-size: 0.7rem; }
        .agents-feed-topbar-right {
          display: flex; gap: 6px; align-items: center; flex-shrink: 0;
        }
        .agents-topbar-btn {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.85);
          padding: 6px 12px; border-radius: 6px; cursor: pointer;
          font-size: 0.75rem; display: inline-flex; align-items: center; gap: 4px;
          transition: background 0.12s, border-color 0.12s;
        }
        .agents-topbar-btn:hover { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.15); }
        .agents-topbar-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .agents-topbar-btn--primary {
          background: rgba(99,102,241,0.18); border-color: rgba(99,102,241,0.45); color: #a5b4fc;
        }
        .agents-topbar-btn--primary:hover { background: rgba(99,102,241,0.28); }
        .agents-topbar-btn--warn {
          background: rgba(251,146,60,0.10); border-color: rgba(251,146,60,0.35); color: #fdba74;
        }
        .agents-topbar-btn--warn:hover { background: rgba(251,146,60,0.18); }
        .agents-topbar-btn--icon { padding: 6px 9px; }
        .agents-topbar-menu-wrap { position: relative; }
        .agents-topbar-menu {
          position: absolute; right: 0; top: 100%; margin-top: 4px;
          background: #1a1a22; border: 1px solid rgba(255,255,255,0.1);
          border-radius: 6px; min-width: 140px; z-index: 50;
          box-shadow: 0 6px 20px rgba(0,0,0,0.5);
          display: flex; flex-direction: column; padding: 4px;
        }
        .agents-topbar-menu button {
          background: none; border: none; color: rgba(255,255,255,0.85);
          padding: 7px 10px; text-align: left; cursor: pointer; font-size: 0.75rem;
          border-radius: 4px;
        }
        .agents-topbar-menu button:hover:not(:disabled) { background: rgba(255,255,255,0.06); }
        .agents-topbar-menu button:disabled { opacity: 0.4; cursor: not-allowed; }
        .agents-feed-messages {
          flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 0.4rem;
          padding: 1rem 1rem 0.5rem;
        }
        .agents-feed-empty {
          color: rgba(255,255,255,0.35); font-size: 0.78rem; text-align: center; padding: 1.25rem;
        }
        .agents-feed-msg {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 6px; padding: 0.55rem 0.7rem;
        }
        .agents-feed-msg--assistant { border-left: 2px solid #6366f1; }
        .agents-feed-msg--user { border-left: 2px solid #34d399; }
        .agents-feed-msg--tool { border-left: 2px solid #fbbf24; }
        .agents-feed-msg--system { border-left: 2px solid rgba(255,255,255,0.2); }
        .agents-feed-msg-head {
          display: flex; gap: 0.5rem; align-items: center;
          font-size: 0.65rem; color: rgba(255,255,255,0.5); margin-bottom: 0.25rem;
          text-transform: uppercase; letter-spacing: 0.04em;
        }
        .agents-feed-msg-role { color: #fff; font-weight: 600; }
        .agents-feed-msg-agent { color: #6366f1; }
        .agents-feed-msg-tool { color: #fbbf24; }
        .agents-feed-msg-time { margin-left: auto; }
        .agents-feed-msg-body {
          font-size: 0.78rem; color: rgba(255,255,255,0.8);
          white-space: pre-wrap; word-break: break-word;
        }
        .agents-feed-msg-toggle {
          background: none; border: none; color: #6366f1; cursor: pointer;
          font-size: 0.7rem; padding: 0.25rem 0; margin-top: 0.2rem;
        }
        .agents-feed-outputs {
          background: rgba(255,255,255,0.03); border-radius: 6px; padding: 0.5rem 0.7rem;
          margin: 0 1rem;
        }
        .agents-feed-outputs-title {
          font-size: 0.65rem; text-transform: uppercase; color: rgba(255,255,255,0.45);
          margin-bottom: 0.3rem;
        }
        .agents-feed-outputs-list { display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.75rem; }
        .agents-feed-outputs-list a { color: #6366f1; text-decoration: none; }
        .agents-feed-outputs-list a:hover { text-decoration: underline; }
        .agents-feed-inject {
          display: flex; gap: 0.5rem; align-items: stretch;
          border-top: 1px solid rgba(255,255,255,0.06);
          padding: 0.6rem 1rem;
        }
        .agents-feed-inject textarea {
          flex: 1; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12);
          color: #fff; padding: 0.5rem 0.6rem; border-radius: 6px; resize: none;
          font-family: inherit; font-size: 0.78rem; outline: none;
        }
        .agents-feed-inject textarea:focus { border-color: #6366f1; }

        /* ── Right inspector ── */
        .agents-inspector {
          width: 300px; min-width: 300px; flex-shrink: 0;
          background: rgba(15,15,20,0.6);
          border-left: 1px solid rgba(255,255,255,0.06);
          display: flex; flex-direction: column; overflow: hidden;
        }
        .agents-inspector-tabs {
          display: flex; border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .agents-inspector-tab {
          flex: 1; padding: 0.6rem 0.5rem;
          background: none; border: none; cursor: pointer;
          color: rgba(255,255,255,0.55); font-size: 0.74rem;
          border-bottom: 2px solid transparent;
        }
        .agents-inspector-tab:hover { color: #fff; background: rgba(255,255,255,0.04); }
        .agents-inspector-tab--active {
          color: #fff; border-bottom-color: #6366f1; background: rgba(99,102,241,0.06);
        }
        .agents-inspector-body {
          flex: 1; overflow-y: auto; padding: 0.75rem;
        }
        .agents-inspector-section { display: flex; flex-direction: column; gap: 0.5rem; }
        .agents-inspector-row {
          display: flex; justify-content: space-between; align-items: center;
          font-size: 0.76rem; gap: 0.5rem;
        }
        .agents-inspector-row a { color: #6366f1; text-decoration: none; word-break: break-all; }
        .agents-inspector-row a:hover { text-decoration: underline; }
        .agents-inspector-link-row label { display: flex; gap: 0.4rem; align-items: center; flex: 1; cursor: pointer; }
        .agents-inspector-flags { display: flex; gap: 0.5rem; font-size: 0.7rem; color: rgba(255,255,255,0.55); }
        .agents-inspector-flags label { display: inline-flex; gap: 0.2rem; align-items: center; cursor: pointer; }
        .agents-inspector-label { color: rgba(255,255,255,0.5); font-size: 0.7rem; text-transform: uppercase; }
        .agents-inspector-subhead {
          font-size: 0.7rem; color: rgba(255,255,255,0.5); text-transform: uppercase;
          letter-spacing: 0.06em; margin-top: 0.25rem;
        }
        .agents-inspector-divider { height: 1px; background: rgba(255,255,255,0.06); margin: 0.6rem 0; }
        .agents-inspector-field {
          display: flex; flex-direction: column; gap: 0.25rem;
          font-size: 0.72rem; color: rgba(255,255,255,0.55);
        }
        .agents-inspector-field input,
        .agents-inspector-field select,
        .agents-inspector-field textarea {
          background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12);
          color: #fff; padding: 0.4rem 0.55rem; border-radius: 6px; outline: none;
          font-family: inherit; font-size: 0.78rem;
        }
        .agents-inspector-field input:focus,
        .agents-inspector-field select:focus,
        .agents-inspector-field textarea:focus { border-color: #6366f1; }
        .agents-inspector-field-row { flex-direction: row; align-items: center; gap: 0.5rem; }
        .agents-mem-hidden { opacity: 0.45; }

        /* ── Links tab cards ── */
        .agents-links { display: flex; flex-direction: column; gap: 14px; }
        .agents-links-section { display: flex; flex-direction: column; gap: 6px; }
        .agents-links-section-title {
          font-size: 0.78rem; color: #fff; margin: 4px 0;
          font-weight: 600;
        }
        .agents-links-list { display: flex; flex-direction: column; gap: 6px; }
        .agents-link-card {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 6px;
          padding: 8px 10px;
        }
        .agents-link-card-row {
          display: flex; align-items: center; justify-content: space-between; gap: 8px;
        }
        .agents-link-card-info { flex: 1; min-width: 0; }
        .agents-link-card-name {
          font-weight: 600; font-size: 0.8rem; color: #fff;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          display: flex; align-items: center; gap: 6px;
        }
        .agents-link-card-meta {
          font-size: 0.7rem; color: rgba(255,255,255,0.4); margin-top: 2px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .agents-link-mono { font-family: monospace; }
        .agents-link-checkbox {
          display: flex; align-items: center; gap: 4px;
          font-size: 0.75rem; cursor: pointer; white-space: nowrap;
          color: rgba(255,255,255,0.7);
        }
        .agents-link-flags {
          display: flex; gap: 12px; margin-top: 6px;
          font-size: 0.7rem; color: rgba(255,255,255,0.5);
        }
        .agents-link-flags label {
          display: flex; align-items: center; gap: 4px; cursor: pointer;
        }
        .agents-link-flags code {
          background: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 3px;
        }
        .agents-link-badge {
          font-size: 0.6rem; padding: 1px 5px; border-radius: 3px;
          font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
        }
        .agents-link-badge--lightrag { background: rgba(139,92,246,0.18); color: #a78bfa; }
        .agents-link-badge--online { background: rgba(34,197,94,0.18); color: #22c55e; }
        .agents-link-badge--offline { background: rgba(239,68,68,0.18); color: #ef4444; }
        .agents-links-hint {
          margin-top: 6px; font-size: 0.68rem; color: rgba(255,255,255,0.3);
        }
        .agents-links-hint code {
          background: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 3px;
        }

        /* ── Dashboard ── */
        .agents-dashboard {
          padding: 1.5rem; overflow-y: auto; height: 100%;
        }
        .agents-dashboard h2 { margin: 0 0 1rem; color: #fff; }
        .agents-dashboard h3 { color: #fff; font-size: 0.85rem; margin: 1.5rem 0 0.6rem; }
        .agents-dashboard-cards {
          display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
          gap: 0.75rem;
        }
        .agents-dashboard-section { margin-top: 0.5rem; }
        .agents-dashboard-table {
          width: 100%; border-collapse: collapse; font-size: 0.78rem;
        }
        .agents-dashboard-table th, .agents-dashboard-table td {
          padding: 0.5rem 0.6rem; text-align: left;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .agents-dashboard-table th { color: rgba(255,255,255,0.5); font-weight: 500; font-size: 0.68rem; text-transform: uppercase; }
        .agents-dashboard-table tr { cursor: pointer; }
        .agents-dashboard-table tbody tr:hover { background: rgba(255,255,255,0.04); }
        .agents-dashboard-templates {
          display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 0.6rem;
        }
        .agents-dashboard-template-card {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px; padding: 0.7rem; display: flex; flex-direction: column; gap: 0.4rem;
        }
      `}</style>
    </div>
  );
}
