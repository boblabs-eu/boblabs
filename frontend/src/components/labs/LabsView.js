/**
 * Bob Manager — Labs View
 *
 * 3-panel layout:
 *  - Left: Lab list + new lab
 *  - Center: Execution timeline (messages, tasks, user inject)
 *  - Right: Agent inspector + lab config
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import './LabsView.css';
import {
  getLabs, createLab, getLab, updateLab, deleteLab, duplicateLab,
  exportLab, importLab,
  runLab, resetLab, pauseLab, resumeLab, stopLab, injectLabMessage,
  getLabAgents, getAgentLibrary, createLabAgent, updateLabAgent, deleteLabAgent,
  getLabTools, createLabTool, deleteLabTool,
  getLabMessages, getLabMemories, toggleLabMemoryVisibility,
  getLabResources, uploadLabResource, deleteLabResource, getLabResourceUrl,
  getLabOutputFiles, getLabOutputFileUrl, downloadFile, getAuthBlobUrl,
  getLabOutputFileContent, saveLabOutputFileContent, getLabOutputFileHistory, getLabResourceContent,
  getToolSets, createToolSet, updateToolSet, deleteToolSet, duplicateToolSet,
  getPromptTemplates, createPromptTemplate, updatePromptTemplate, deletePromptTemplate, duplicatePromptTemplate,
  getLibraryAgents, createLibraryAgent, updateLibraryAgent, deleteLibraryAgent, duplicateLibraryAgent,
  getCronJobs, createCronJob, updateCronJob, deleteCronJob, duplicateCronJob, getCronJobLabs,
  getAIModels, getAIAgents, createAIAgent,
  getStrategyPrompt,
  getLoopStrategies,
  getPipelines, getBuiltinTools,
  getRagCollections, getLabRagAccess, grantLabRagAccess, revokeLabRagAccess, updateLabRagAccess,
  getLabWeb3Access, getLabWeb3Candidates, grantLabWeb3Access, revokeLabWeb3Access,
  getLabServerAccess, getLabServerCandidates, grantLabServerAccess, revokeLabServerAccess,
  getToolConfigs, upsertToolConfig,
  hermesActivate, hermesDeactivate, hermesStatus,
} from '../../services/api';
import wsService from '../../services/websocket';
import ShareModal from '../common/ShareModal';
import LabDashboard from './LabDashboard';

/* ── Icons ─── */
const IC = {
  plus: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  play: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>,
  pause: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>,
  stop: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>,
  trash: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>,
  send: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  bot: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><line x1="12" y1="7" x2="12" y2="11"/><circle cx="8" cy="16" r="1"/><circle cx="16" cy="16" r="1"/></svg>,
  user: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
  chevronRight: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="9 18 15 12 9 6"/></svg>,
  loader: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="lab-spinner"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>,
  settings: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  edit: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  brain: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M9.5 2A5.5 5.5 0 0 0 4 7.5c0 1.58.66 3 1.72 4.01A4.5 4.5 0 0 0 4 15.5C4 17.98 6.02 20 8.5 20H9v2h6v-2h.5c2.48 0 4.5-2.02 4.5-4.5 0-1.57-.8-2.95-2.01-3.76A5.5 5.5 0 0 0 14.5 2h-5z"/></svg>,
  tool: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>,
  close: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  save: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>,
  chip: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>,
  search: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  more: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/><circle cx="5" cy="12" r="1.4"/></svg>,
  copy: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  download: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
  upload: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  share: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>,
  refresh: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>,
  database: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
  folder: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>,
};

const STATUS_COLORS = {
  created: { bg: 'rgba(180,189,205,0.10)', color: '#b4bdcd' },
  running: { bg: 'rgba(52,211,153,0.14)', color: '#34d399' },
  paused: { bg: 'rgba(251,191,36,0.14)', color: '#fbbf24' },
  completed: { bg: 'rgba(34,211,238,0.14)', color: '#22d3ee' },
  failed: { bg: 'rgba(248,113,113,0.14)', color: '#f87171' },
  scheduled: { bg: 'rgba(124,92,255,0.14)', color: '#a78bff' },
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

/* ── Available builtin tools ── */
/* BUILTIN_TOOL_LIST is now fetched dynamically from /orchestrator/builtin-tools */

/* ── Sensitive-tool warning pill ── */
function SensitivePill({ tool }) {
  if (!tool || !tool.sensitive) return null;
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

/* ── Pipeline sub-selection component ── */
function PipelineToolGroup({ tools, pipelines, onChange, disabled }) {
  const [expanded, setExpanded] = useState(false);
  const pipelineEntries = tools.filter(t => t.startsWith('media_pipeline:'));
  const selectedNames = pipelineEntries.map(t => t.split(':')[1]);
  const allSelected = pipelines.length > 0 && pipelines.every(p => selectedNames.includes(p.name));
  const someSelected = selectedNames.length > 0;

  const toggleAll = () => {
    const base = tools.filter(t => !t.startsWith('media_pipeline:'));
    if (allSelected) {
      onChange(base);
    } else {
      onChange([...base, ...pipelines.map(p => `media_pipeline:${p.name}`)]);
    }
  };

  const toggleOne = (name) => {
    const key = `media_pipeline:${name}`;
    if (tools.includes(key)) {
      onChange(tools.filter(t => t !== key));
    } else {
      onChange([...tools, key]);
    }
  };

  const checkboxRef = useRef(null);
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = someSelected && !allSelected;
    }
  }, [someSelected, allSelected]);

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <label className="lab-tool-checkbox" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" ref={checkboxRef}
          checked={someSelected} disabled={disabled} onChange={toggleAll} />
        <span className="lab-tool-info" style={{ flex: 1 }}>
          <span className="lab-tool-name">media_pipeline</span>
          <span className="lab-tool-desc">Generate media via pipelines</span>
        </span>
        {!disabled && pipelines.length > 0 && (
          <button type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
            style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 4px' }}>
            {expanded ? '▾' : '▸'} {selectedNames.length}/{pipelines.length}
          </button>
        )}
      </label>
      {expanded && !disabled && (
        <div style={{ marginLeft: 22, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {pipelines.map(p => (
            <label key={p.name} className="lab-tool-checkbox" style={{ fontSize: '0.65rem' }}>
              <input type="checkbox" checked={selectedNames.includes(p.name)}
                onChange={() => toggleOne(p.name)} />
              <span className="lab-tool-info">
                <span className="lab-tool-name">{p.name}</span>
                <span className="lab-tool-desc">{p.description}{!p.has_provider ? ' ⚠ no provider' : ''}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Sub-tool selection component (mail, twitter, etc.) ── */
function SubToolGroup({ toolDef, tools, onChange, disabled }) {
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
    if (tools.includes(key)) {
      onChange(tools.filter(t => t !== key));
    } else {
      onChange([...tools, key]);
    }
  };

  const checkboxRef = useRef(null);
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = someSelected && !allSelected;
    }
  }, [someSelected, allSelected]);

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <label className="lab-tool-checkbox" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" ref={checkboxRef}
          checked={someSelected} disabled={disabled} onChange={toggleAll} />
        <span className="lab-tool-info" style={{ flex: 1 }}>
          <span className="lab-tool-name">{toolDef.name}<SensitivePill tool={toolDef} /></span>
          <span className="lab-tool-desc">{toolDef.description || toolDef.desc}</span>
        </span>
        {!disabled && (
          <button type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
            style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 4px' }}>
            {expanded ? '▾' : '▸'} {selectedSubs.length}/{toolDef.subTools.length}
          </button>
        )}
      </label>
      {expanded && !disabled && (
        <div style={{ marginLeft: 22, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {toolDef.subTools.map(s => (
            <label key={s.name} className="lab-tool-checkbox" style={{ fontSize: '0.65rem' }}>
              <input type="checkbox" checked={selectedSubs.includes(s.name)}
                onChange={() => toggleOne(s.name)} />
              <span className="lab-tool-info">
                <span className="lab-tool-name">{s.name}</span>
                <span className="lab-tool-desc">{s.description || s.desc}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Authenticated image component ── */
function AuthImage({ src, alt, style }) {
  const [blobUrl, setBlobUrl] = React.useState(null);
  React.useEffect(() => {
    let revoke = null;
    getAuthBlobUrl(src).then(url => { setBlobUrl(url); revoke = url; });
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [src]);
  if (!blobUrl) return null;
  return <img src={blobUrl} alt={alt} style={style} />;
}

export default function LabsView() {
  // Lab list
  const [labs, setLabs] = useState([]);
  const [activeLab, setActiveLab] = useState(null);

  // Active lab data
  const [agents, setAgents] = useState([]);
  const [messages, setMessages] = useState([]);
  const [memories, setMemories] = useState([]);
  const [resources, setResources] = useState([]);
  const [outputFiles, setOutputFiles] = useState([]);
  const [uploadingResource, setUploadingResource] = useState(false);

  // Available models for selectors
  const [allModelsRaw, setAllModelsRaw] = useState([]);

  // Available media pipelines
  const [availablePipelines, setAvailablePipelines] = useState([]);

  // RAG collections
  const [ragCollections, setRagCollections] = useState([]);
  const [labRagAccess, setLabRagAccess] = useState([]); // access entries for active lab
  const [walletCollections, setWalletCollections] = useState([]);
  const [labWeb3Access, setLabWeb3Access] = useState([]);
  const [serverCandidates, setServerCandidates] = useState([]);
  const [labServerAccess, setLabServerAccess] = useState([]);

  // Deduplicated models (one per model_identifier, prefer available)
  const allModels = React.useMemo(() => {
    const map = new Map();
    for (const m of allModelsRaw) {
      const existing = map.get(m.model_identifier);
      if (!existing || (m.is_available && !existing.is_available)) {
        map.set(m.model_identifier, m);
      }
    }
    return Array.from(map.values());
  }, [allModelsRaw]);

  const contextLengthMap = React.useMemo(() => {
    const map = {};
    for (const m of allModelsRaw) {
      if (m.parameters?.context_length && !map[m.model_identifier]) {
        map[m.model_identifier] = m.parameters.context_length;
      }
    }
    return map;
  }, [allModelsRaw]);

  // Inject input
  const [injectInput, setInjectInput] = useState('');
  const [injecting, setInjecting] = useState(false);
  const [injectFiles, setInjectFiles] = useState([]); // [{file, name, preview?}]
  const injectFileRef = useRef(null);

  // UI state
  const [showCreateLab, setShowCreateLab] = useState(false);
  const [shareTarget, setShareTarget] = useState(null);
  const [newLabName, setNewLabName] = useState('');
  const [newLabDesc, setNewLabDesc] = useState('');
  const [inspectorTab, setInspectorTab] = useState('agents'); // 'agents' | 'memory' | 'config'
  const [inspectorLinksSection, setInspectorLinksSection] = useState({ rag: true, wallets: true, servers: true });
  const [inspectorWidth, setInspectorWidth] = useState(300);
  const inspectorDragging = useRef(false);
  const inspectorStartX = useRef(0);
  const inspectorStartW = useRef(300);
  const [editingAgent, setEditingAgent] = useState(null); // agent obj being edited
  const [showAddAgent, setShowAddAgent] = useState(false);
  const [newAgent, setNewAgent] = useState({ name: '', role: '', system_prompt: '', model_id: '', backend: 'native', share_memory: false, tools: [], tool_set_id: '', callable_agents: [], cron_expression: '', cron_instruction: '', prompt_template_id: '' });
  const [editingLabConfig, setEditingLabConfig] = useState(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [deleteLabConfirm, setDeleteLabConfirm] = useState(null);
  const [deleteAgentConfirm, setDeleteAgentConfirm] = useState(null);
  const [agentLibrary, setAgentLibrary] = useState([]);
  const [showAgentLibrary, setShowAgentLibrary] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState(new Set());
  const [allExpanded, setAllExpanded] = useState(false);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  // Tool Sets
  const [toolSets, setToolSets] = useState([]);
  const [editingToolSet, setEditingToolSet] = useState(null); // { id?, name, description, tools }
  const [showCreateToolSet, setShowCreateToolSet] = useState(false);
  const [newToolSet, setNewToolSet] = useState({ name: '', description: '', tools: [] });

  // Sidebar sections
  const [sidebarSection, setSidebarSection] = useState({ labs: true, labsApps: false, agents: false, toolSets: false, prompts: false, cron: false, toolConfigs: false });
  const [sidebarSearch, setSidebarSearch] = useState('');
  const [labToolbarMenuOpen, setLabToolbarMenuOpen] = useState(false);
  const sidebarQuery = sidebarSearch.trim().toLowerCase();
  const matchesSearch = (...fields) => {
    if (!sidebarQuery) return true;
    return fields.some(f => (f || '').toString().toLowerCase().includes(sidebarQuery));
  };
  // True if a lab was spawned by a consumer app (Phase 1.2 prefix `app:`,
  // plus legacy tag prefixes kept for backward compat).
  const isAppLab = (lab) => {
    const n = (lab?.name || '').toLowerCase();
    return n.startsWith('app:')
      || n.startsWith('showroom:')
      || n.startsWith('showroom_template_');
  };

  // Tool Configs (SMTP, Twitter API keys, etc.)
  const [toolConfigs, setToolConfigs] = useState({});
  const [toolConfigDrafts, setToolConfigDrafts] = useState({});
  const [builtinTools, setBuiltinTools] = useState([]);

  // Library Agents (legacy) + Global AI Agents (unified)
  const [libraryAgents, setLibraryAgents] = useState([]);
  const [globalAgents, setGlobalAgents] = useState([]); // AIAgent from Agents tab
  const [editingLibraryAgent, setEditingLibraryAgent] = useState(null);
  const [showCreateLibraryAgent, setShowCreateLibraryAgent] = useState(false);
  const [newLibraryAgent, setNewLibraryAgent] = useState({ name: '', role: '', system_prompt: '', model_id: '', temperature: 0.7, max_tokens: 4096, tools: [], tool_set_ids: [], share_memory: false, callable_agents: [], cron_expression: '', cron_instruction: '', prompt_template_id: '' });

  // Prompt Templates
  const [promptTemplates, setPromptTemplates] = useState([]);
  const [editingPromptTemplate, setEditingPromptTemplate] = useState(null);
  const [showCreatePromptTemplate, setShowCreatePromptTemplate] = useState(false);
  const [newPromptTemplate, setNewPromptTemplate] = useState({ name: '', description: '', content: '', target: 'agent' });

  // CRON Jobs
  const [cronJobs, setCronJobs] = useState([]);
  const [editingCron, setEditingCron] = useState(null);
  const [showCreateCron, setShowCreateCron] = useState(false);
  const [newCron, setNewCron] = useState({ name: '', description: '', expression: '', method: 'orchestrator_inject', instruction: '' });
  const [deletingCronId, setDeletingCronId] = useState(null);
  const [cronLabsUsing, setCronLabsUsing] = useState({}); // { cronId: [{id, name, status}] }

  // File viewer
  const [fileViewer, setFileViewer] = useState(null); // { type: 'output'|'resource', path?, resourceId?, name }
  const [fileViewerData, setFileViewerData] = useState(null); // { content, is_text, ... }
  const [fileViewerHistory, setFileViewerHistory] = useState([]); // [{ action, agent_name, timestamp }]
  const [fileViewerLoading, setFileViewerLoading] = useState(false);
  const [fileViewerBlobUrl, setFileViewerBlobUrl] = useState(null); // auth'd blob URL for media
  // Inline editing of text workspace files
  const [fileEditing, setFileEditing] = useState(false);
  const [fileEditContent, setFileEditContent] = useState('');
  const [fileSaving, setFileSaving] = useState(false);
  const [fileSaveError, setFileSaveError] = useState(null);

  // Memory viewer (central view)
  const [memoryView, setMemoryView] = useState(null); // 'lab' | agent_id string | null
  const [memorySection, setMemorySection] = useState('lab'); // 'lab' | agent_id for right panel
  // Per-agent feed mode (Feature 1)
  const [selectedAgentId, setSelectedAgentId] = useState(null); // lab_agent_id when viewing one agent
  const [agentMemoryTakeover, setAgentMemoryTakeover] = useState(false); // true → central pane shows agent memories
  const [agentMemories, setAgentMemories] = useState([]);

  // Prompt editor (central view)
  const [promptEditor, setPromptEditor] = useState(null); // { type: 'strategy'|'orchestrator'|'agent', agentId?, value, dirty }

  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const pollRef = useRef(null);

  // ── Inspector panel resize ──────────────────────
  const onInspectorMouseDown = useCallback((e) => {
    e.preventDefault();
    inspectorDragging.current = true;
    inspectorStartX.current = e.clientX;
    inspectorStartW.current = inspectorWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [inspectorWidth]);

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!inspectorDragging.current) return;
      const delta = inspectorStartX.current - e.clientX;
      const newW = Math.min(900, Math.max(250, inspectorStartW.current + delta));
      setInspectorWidth(newW);
    };
    const onMouseUp = () => {
      if (inspectorDragging.current) {
        inspectorDragging.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  // ── Load labs + models on mount ─────────────────
  useEffect(() => {
    loadLabs();
    loadModels();
    loadPipelines();
    loadToolSets();
    loadPromptTemplates();
    loadLibraryAgents();
    loadGlobalAgents();
    loadCronJobs();
    loadRagCollections();
    loadToolConfigs();
    getBuiltinTools().then(r => setBuiltinTools(r.data || [])).catch(() => {});
  }, []);

  // ── Load active lab data ────────────────────────
  useEffect(() => {
    if (activeLab) {
      loadLabAgents(activeLab.id);
      loadLabMessages(activeLab.id);
      loadLabMemories(activeLab.id);
      loadLabResources(activeLab.id);
      loadOutputFiles(activeLab.id);
      loadLabRagAccess(activeLab.id);
      loadLabWeb3Access(activeLab.id);
      loadWalletCollections(activeLab.id);
      loadLabServerAccess(activeLab.id);
      loadServerCandidates(activeLab.id);
    } else {
      setAgents([]);
      setMessages([]);
      setMemories([]);
      setResources([]);
      setOutputFiles([]);
      setLabRagAccess([]);
      setLabWeb3Access([]);
      setWalletCollections([]);
      setLabServerAccess([]);
      setServerCandidates([]);
    }
  }, [activeLab?.id]);

  // ── Poll messages for running labs ──────────────
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (activeLab && (activeLab.status === 'running')) {
      pollRef.current = setInterval(() => {
        loadLabMessages(activeLab.id);
        loadLabMemories(activeLab.id);
        loadOutputFiles(activeLab.id);
      }, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeLab?.id, activeLab?.status]);

  // ── Reset per-agent feed when switching labs ────
  useEffect(() => {
    setSelectedAgentId(null);
    setAgentMemoryTakeover(false);
    setAgentMemories([]);
  }, [activeLab?.id]);

  // ── Re-fetch messages when per-agent selection changes
  useEffect(() => {
    if (!activeLab) return;
    loadLabMessages(activeLab.id);
    if (selectedAgentId && agentMemoryTakeover) {
      loadAgentMemories(activeLab.id, selectedAgentId);
    }
    // eslint-disable-next-line
  }, [selectedAgentId, agentMemoryTakeover]);

  async function loadAgentMemories(labId, agentId) {
    try {
      const res = await getLabMemories(labId, { agent_id: agentId, limit: 200 });
      setAgentMemories(res.data || []);
    } catch (e) {
      console.error('Failed to load agent memories', e);
      setAgentMemories([]);
    }
  }

  // ── WebSocket subscription for lab events ───────
  useEffect(() => {
    const unsubs = [
      wsService.on('lab.started', (data) => {
        if (data.lab_id === activeLab?.id) refreshActiveLab();
        refreshLabList();
      }),
      wsService.on('lab.paused', (data) => {
        if (data.lab_id === activeLab?.id) refreshActiveLab();
        refreshLabList();
      }),
      wsService.on('lab.resumed', (data) => {
        if (data.lab_id === activeLab?.id) refreshActiveLab();
        refreshLabList();
      }),
      wsService.on('lab.completed', (data) => {
        if (data.lab_id === activeLab?.id) refreshActiveLab();
        refreshLabList();
      }),
      wsService.on('lab.error', (data) => {
        if (data.lab_id === activeLab?.id) refreshActiveLab();
        refreshLabList();
      }),
      wsService.on('lab.iteration', (data) => {
        if (data.lab_id === activeLab?.id) {
          refreshActiveLab();
          loadLabMessages(activeLab.id);
        }
      }),
      wsService.on('lab.orchestrator.message', (data) => {
        if (data.lab_id === activeLab?.id) loadLabMessages(activeLab.id);
      }),
      wsService.on('lab.task.start', (data) => {
        if (data.lab_id === activeLab?.id) loadLabMessages(activeLab.id);
      }),
      wsService.on('lab.task.complete', (data) => {
        if (data.lab_id === activeLab?.id) {
          loadLabMessages(activeLab.id);
          loadLabMemories(activeLab.id);
        }
      }),
      wsService.on('lab.task.error', (data) => {
        if (data.lab_id === activeLab?.id) loadLabMessages(activeLab.id);
      }),
      wsService.on('lab.file.event', (data) => {
        if (data.lab_id === activeLab?.id) {
          loadLabMessages(activeLab.id);
          loadOutputFiles(activeLab.id);
        }
      }),
      wsService.on('lab.loop_warning', (data) => {
        if (data.lab_id !== activeLab?.id) return;
        const sev = (data.severity || 'yellow').toUpperCase();
        const sigs = (data.signals || []).map(s => s.name).join(', ');
        // Lightweight banner via console + browser notification fallback
        console.warn(`[anti-loop ${sev}] ${sigs} (score=${data.score})`);
        try {
          window.dispatchEvent(new CustomEvent('bob:toast', {
            detail: { type: 'warning', text: `Loop ${sev}: ${sigs} (score ${data.score})` }
          }));
        } catch {}
      }),
      wsService.on('lab.loop_recovered', (data) => {
        if (data.lab_id !== activeLab?.id) return;
        loadLabMessages(activeLab.id);
        try {
          window.dispatchEvent(new CustomEvent('bob:toast', {
            detail: { type: 'info', text: `Anti-loop: removed ${data.removed_count || 0} looping message(s) and resumed` }
          }));
        } catch {}
      }),
    ];
    return () => unsubs.forEach(u => u());
  }, [activeLab?.id]);

  // ── Scroll detection ────────────────────────────
  const userScrolledUpRef = useRef(false);
  const programmaticScrollRef = useRef(false);
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const handleScroll = () => {
      // Ignore scroll events triggered by programmatic scrollIntoView
      if (programmaticScrollRef.current) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      setShowScrollBtn(!atBottom);
      userScrolledUpRef.current = !atBottom;
    };
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, [activeLab?.id]);

  // ── Auto-scroll only if user is already viewing the bottom ───────
  useEffect(() => {
    if (!userScrolledUpRef.current && messagesEndRef.current) {
      programmaticScrollRef.current = true;
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
      // Reset flag after smooth scroll completes
      setTimeout(() => { programmaticScrollRef.current = false; }, 500);
    }
  }, [messages]);

  const scrollToBottom = () => {
    programmaticScrollRef.current = true;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    setShowScrollBtn(false);
    userScrolledUpRef.current = false;
    setTimeout(() => { programmaticScrollRef.current = false; }, 500);
  };

  const toggleMessage = (msgId) => {
    setExpandedMessages(prev => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  const toggleExpandAll = () => {
    if (allExpanded) {
      setExpandedMessages(new Set());
      setAllExpanded(false);
    } else {
      setExpandedMessages(new Set(messages.map(m => m.id)));
      setAllExpanded(true);
    }
  };

  // ── Data loaders ────────────────────────────────

  async function loadLabs() {
    try {
      const res = await getLabs();
      setLabs(res.data);
    } catch (e) { console.error('Failed to load labs', e); }
  }

  async function loadModels() {
    try {
      const res = await getAIModels();
      setAllModelsRaw(res.data);
    } catch (e) { console.error('Failed to load models', e); }
  }

  async function loadPipelines() {
    try {
      const res = await getPipelines();
      setAvailablePipelines(res.data);
    } catch (e) { console.error('Failed to load pipelines', e); }
  }

  async function loadToolConfigs() {
    try {
      const res = await getToolConfigs();
      const map = {};
      for (const tc of res.data) {
        map[tc.tool_type] = tc.config;
      }
      setToolConfigs(map);
      setToolConfigDrafts(JSON.parse(JSON.stringify(map)));
    } catch (e) { console.error('Failed to load tool configs', e); }
  }

  async function saveToolConfig(toolType) {
    try {
      await upsertToolConfig(toolType, toolConfigDrafts[toolType] || {});
      await loadToolConfigs();
    } catch (e) { console.error('Failed to save tool config', e); }
  }

  async function loadLabAgents(labId) {
    try {
      const res = await getLabAgents(labId);
      setAgents(res.data);
    } catch (e) { console.error('Failed to load agents', e); }
  }

  async function loadLabMessages(labId, opts = {}) {
    try {
      const params = {};
      const agentId = opts.sender_agent_id !== undefined ? opts.sender_agent_id : selectedAgentId;
      if (agentId) {
        params.sender_agent_id = agentId;
        params.include_targeting = true;
      }
      const res = await getLabMessages(labId, params);
      // Only update state if messages actually changed (avoids unnecessary re-renders + scroll)
      setMessages(prev => {
        const next = res.data;
        if (prev.length === next.length && prev.length > 0 && prev[prev.length - 1].id === next[next.length - 1].id) {
          return prev;
        }
        return next;
      });
    } catch (e) { console.error('Failed to load messages', e); }
  }

  async function loadLabMemories(labId) {
    try {
      const res = await getLabMemories(labId);
      setMemories(res.data);
    } catch (e) { console.error('Failed to load memories', e); }
  }

  async function loadLabResources(labId) {
    try {
      const res = await getLabResources(labId);
      setResources(res.data);
    } catch (e) { console.error('Failed to load resources', e); }
  }

  async function loadRagCollections() {
    try {
      const res = await getRagCollections();
      setRagCollections(res.data);
    } catch (e) { console.error('Failed to load RAG collections', e); }
  }

  async function loadLabRagAccess(labId) {
    try {
      const res = await getLabRagAccess(labId);
      setLabRagAccess(res.data);
    } catch (e) { console.error('Failed to load lab RAG access', e); }
  }

  async function loadWalletCollections(labId) {
    try {
      const res = await getLabWeb3Candidates(labId);
      setWalletCollections(res.data);
    } catch (e) { console.error('Failed to load wallet collections', e); }
  }

  async function loadLabWeb3Access(labId) {
    try {
      const res = await getLabWeb3Access(labId);
      setLabWeb3Access(res.data);
    } catch (e) { console.error('Failed to load lab Web3 access', e); }
  }

  async function handleToggleRagAccess(collectionId) {
    if (!activeLab) return;
    const existing = labRagAccess.find(a => a.collection_id === collectionId);
    try {
      if (existing) {
        await revokeLabRagAccess(activeLab.id, collectionId);
      } else {
        await grantLabRagAccess(activeLab.id, { collection_id: collectionId });
      }
      loadLabRagAccess(activeLab.id);
    } catch (e) { console.error('Failed to toggle RAG access', e); }
  }

  async function handleUpdateRagFlag(collectionId, field, value) {
    if (!activeLab) return;
    try {
      await updateLabRagAccess(activeLab.id, collectionId, { [field]: value });
      loadLabRagAccess(activeLab.id);
    } catch (e) { console.error('Failed to update RAG access', e); }
  }

  async function handleToggleWalletAccess(walletId) {
    if (!activeLab) return;
    const existing = labWeb3Access.find(a => a.wallet_id === walletId);
    try {
      if (existing) {
        await revokeLabWeb3Access(activeLab.id, walletId);
      } else {
        await grantLabWeb3Access(activeLab.id, [walletId]);
      }
      loadLabWeb3Access(activeLab.id);
    } catch (e) { console.error('Failed to toggle wallet access', e); }
  }

  async function loadServerCandidates(labId) {
    try {
      const res = await getLabServerCandidates(labId);
      setServerCandidates(res.data);
    } catch (e) { console.error('Failed to load server candidates', e); }
  }

  async function loadLabServerAccess(labId) {
    try {
      const res = await getLabServerAccess(labId);
      setLabServerAccess(res.data);
    } catch (e) { console.error('Failed to load lab server access', e); }
  }

  async function handleToggleServerAccess(serverId) {
    if (!activeLab) return;
    const existing = labServerAccess.find(a => a.server_id === serverId);
    try {
      if (existing) {
        await revokeLabServerAccess(activeLab.id, serverId);
      } else {
        await grantLabServerAccess(activeLab.id, [serverId]);
      }
      loadLabServerAccess(activeLab.id);
    } catch (e) { console.error('Failed to toggle server access', e); }
  }

  async function loadOutputFiles(labId) {
    try {
      const res = await getLabOutputFiles(labId);
      setOutputFiles(res.data);
    } catch (e) { console.error('Failed to load output files', e); }
  }

  async function handleUploadResource(file) {
    if (!activeLab || !file) return;
    setUploadingResource(true);
    try {
      await uploadLabResource(activeLab.id, file);
      await loadLabResources(activeLab.id);
    } catch (e) {
      console.error('Failed to upload resource', e);
      alert(e?.response?.data?.detail || 'Upload failed');
    } finally {
      setUploadingResource(false);
    }
  }

  async function handleDeleteResource(resourceId) {
    if (!activeLab) return;
    try {
      await deleteLabResource(activeLab.id, resourceId);
      setResources(prev => prev.filter(r => r.id !== resourceId));
    } catch (e) { console.error('Failed to delete resource', e); }
  }

  function refreshLabList() {
    loadLabs();
  }

  async function refreshActiveLab() {
    if (!activeLab) return;
    try {
      const res = await getLab(activeLab.id);
      setActiveLab(res.data);
    } catch (e) { console.error('Failed to refresh lab', e); }
  }

  // ── Actions ─────────────────────────────────────

  async function handleCreateLab() {
    if (!newLabName.trim()) return;
    try {
      const res = await createLab({ name: newLabName, description: newLabDesc });
      setShowCreateLab(false);
      setNewLabName('');
      setNewLabDesc('');
      setLabs(prev => [...prev, res.data]);
      setActiveLab(res.data);
    } catch (e) { console.error('Failed to create lab', e); }
  }

  async function handleDeleteLab(labId, e) {
    e.stopPropagation();
    setDeleteLabConfirm(labId);
  }
  async function confirmDeleteLab() {
    const labId = deleteLabConfirm;
    setDeleteLabConfirm(null);
    try {
      await deleteLab(labId);
      setLabs(prev => prev.filter(l => l.id !== labId));
      if (activeLab?.id === labId) setActiveLab(null);
    } catch (e) { console.error('Failed to delete lab', e); }
  }

  async function handleDuplicateLab(labId, e) {
    e.stopPropagation();
    try {
      const res = await duplicateLab(labId);
      refreshLabList();
      setActiveLab(res.data);
    } catch (e) { console.error('Failed to duplicate lab', e); }
  }

  async function handleExportLab(labId, e) {
    e.stopPropagation();
    try {
      const res = await exportLab(labId);
      const json = JSON.stringify(res.data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(res.data.lab?.name || 'lab').replace(/[^a-zA-Z0-9_-]/g, '_')}.lab.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { console.error('Failed to export lab', e); }
  }

  function formatImportLabError(err, fileName = 'selected file') {
    if (err instanceof SyntaxError) {
      return `Import failed: ${fileName} is not valid JSON. ${err.message}`;
    }

    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      const loc = Array.isArray(first?.loc) ? first.loc.join(' > ') : null;
      const msg = first?.msg || 'Request validation failed';
      return loc ? `Import failed: ${msg} (${loc})` : `Import failed: ${msg}`;
    }

    if (typeof detail === 'string' && detail.trim()) {
      return `Import failed: ${detail}`;
    }

    if (err?.message) {
      return `Import failed: ${err.message}`;
    }

    return 'Import failed: unknown error';
  }

  async function handleImportLab() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const blueprint = JSON.parse(text);
        const res = await importLab(blueprint);
        refreshLabList();
        setActiveLab(res.data);
      } catch (err) {
        console.error('Failed to import lab', err);
        alert(formatImportLabError(err, file.name));
      }
    };
    input.click();
  }

  async function handleRunLab({ reset = false } = {}) {
    if (!activeLab) return;
    // Pre-flight: a Continue (or Run) on a lab that has already used all its
    // iterations would silently complete in milliseconds (the runner exits
    // immediately). Warn the user instead so they don't think the button is
    // broken — they need to either Reset or raise max_iterations.
    const maxIter = Number(activeLab.max_iterations || 0);
    const curIter = Number(activeLab.current_iteration || 0);
    if (!reset && maxIter > 0 && curIter >= maxIter) {
      window.alert(
        `This lab has reached its iteration limit (${curIter}/${maxIter}).\n\n` +
        `Continue would exit immediately. To resume work:\n` +
        `  • Click "Reset" to start over from a clean state, or\n` +
        `  • Increase "Max iterations" in the lab settings, then click Continue again.`
      );
      return;
    }
    try {
      await runLab(activeLab.id, { reset });
      setShowResetConfirm(false);
      refreshActiveLab();
      refreshLabList();
      if (reset) {
        setMessages([]);
        setMemories([]);
      }
    } catch (e) { console.error('Failed to run lab', e); }
  }

  async function handleResetLab() {
    if (!activeLab) return;
    try {
      await resetLab(activeLab.id);
      setShowResetConfirm(false);
      setMessages([]);
      setMemories([]);
      refreshActiveLab();
      refreshLabList();
    } catch (e) { console.error('Failed to reset lab', e); }
  }

  async function handlePauseLab() {
    if (!activeLab) return;
    try {
      await pauseLab(activeLab.id);
      refreshActiveLab();
      refreshLabList();
    } catch (e) { console.error('Failed to pause lab', e); }
  }

  async function handleResumeLab() {
    if (!activeLab) return;
    try {
      await resumeLab(activeLab.id);
      refreshActiveLab();
      refreshLabList();
    } catch (e) { console.error('Failed to resume lab', e); }
  }

  async function handleStopLab() {
    if (!activeLab) return;
    try {
      await stopLab(activeLab.id);
      refreshActiveLab();
      refreshLabList();
    } catch (e) { console.error('Failed to stop lab', e); }
  }

  async function handleInject() {
    if (!activeLab || (!injectInput.trim() && !injectFiles.length) || injecting) return;

    // First-run confirmation
    if (activeLab.status === 'created') {
      const ok = window.confirm(
        'You are launching the first run. Ensure everything is well configured (agents, orchestrator model, etc).\n\nContinue?'
      );
      if (!ok) return;
    }

    setInjecting(true);
    try {
      // Upload attached files as lab resources
      const uploadedNames = [];
      for (const f of injectFiles) {
        try {
          await uploadLabResource(activeLab.id, f.file);
          uploadedNames.push(f.name);
        } catch (e) { console.error('Failed to upload', f.name, e); }
      }
      setInjectFiles([]);

      // Build inject content with file references
      let content = injectInput.trim();
      if (uploadedNames.length > 0) {
        const fileList = uploadedNames.map(n => `- ${n}`).join('\n');
        const fileNote = `\n\n[Attached files — now available as resources]\n${fileList}`;
        content = content ? content + fileNote : `[Attached files — now available as resources]\n${fileList}`;
      }

      await injectLabMessage(activeLab.id, { content });
      setInjectInput('');

      // Refresh resources list so new files show up
      if (uploadedNames.length > 0) loadLabResources(activeLab.id);

      // Auto-launch or auto-resume depending on status
      if (activeLab.status === 'paused') {
        await resumeLab(activeLab.id);
        refreshActiveLab();
        refreshLabList();
      } else if (activeLab.status !== 'running') {
        await runLab(activeLab.id);
        refreshActiveLab();
        refreshLabList();
      }

      loadLabMessages(activeLab.id);
    } catch (e) { console.error('Failed to inject', e); }
    setInjecting(false);
  }

  async function handleAddAgent() {
    if (!activeLab || !newAgent.name.trim()) return;
    try {
      const payload = { ...newAgent };
      if (!payload.model_id) delete payload.model_id;
      if (!payload.tool_set_id) delete payload.tool_set_id;
      if (!payload.prompt_template_id) delete payload.prompt_template_id;
      if (!payload.cron_expression) payload.cron_expression = null;
      await createLabAgent(activeLab.id, payload);
      setShowAddAgent(false);
      setNewAgent({ name: '', role: '', system_prompt: '', model_id: '', backend: 'native', share_memory: false, tools: [], tool_set_id: '', callable_agents: [], cron_expression: '', cron_instruction: '', prompt_template_id: '' });
      loadLabAgents(activeLab.id);
      refreshActiveLab();
    } catch (e) { console.error('Failed to add agent', e); }
  }

  async function handleImportAgent(libraryAgent) {
    if (!activeLab) return;
    try {
      await createLabAgent(activeLab.id, {
        library_agent_id: libraryAgent.id,
        name: libraryAgent.name,
        role: libraryAgent.role,
        system_prompt: libraryAgent.system_prompt,
        model_id: libraryAgent.model_id || undefined,
        backend: libraryAgent.backend || 'native',
        temperature: libraryAgent.temperature,
        max_tokens: libraryAgent.max_tokens,
        tools: libraryAgent.tools || [],
        share_memory: libraryAgent.share_memory || false,
      });
      setShowAgentLibrary(false);
      loadLabAgents(activeLab.id);
      refreshActiveLab();
    } catch (e) { console.error('Failed to import agent', e); }
  }

  async function loadAgentLibrary() {
    try {
      const res = await getAgentLibrary();
      setAgentLibrary(res.data);
    } catch (e) { console.error('Failed to load agent library', e); }
  }

  async function handleUpdateAgent(agentId, data) {
    if (!activeLab) return;
    try {
      await updateLabAgent(activeLab.id, agentId, data);
      setEditingAgent(null);
      loadLabAgents(activeLab.id);
    } catch (e) { console.error('Failed to update agent', e); }
  }

  async function handleDeleteAgent(agentId) {
    if (!activeLab) return;
    setDeleteAgentConfirm(agentId);
  }
  async function confirmDeleteAgent() {
    const agentId = deleteAgentConfirm;
    setDeleteAgentConfirm(null);
    if (!activeLab) return;
    try {
      await deleteLabAgent(activeLab.id, agentId);
      loadLabAgents(activeLab.id);
      refreshActiveLab();
    } catch (e) { console.error('Failed to delete agent', e); }
  }

  // ── Tool Sets ───────────────────────────────────

  async function loadToolSets() {
    try {
      const res = await getToolSets();
      setToolSets(res.data);
    } catch (e) { console.error('Failed to load tool sets', e); }
  }

  // ── Library Agents ──────────────────────────────

  async function loadLibraryAgents() {
    try {
      const res = await getLibraryAgents();
      setLibraryAgents(res.data);
    } catch (e) { console.error('Failed to load library agents', e); }
  }

  async function loadGlobalAgents() {
    try {
      const res = await getAIAgents();
      setGlobalAgents(res.data || []);
    } catch (e) { console.error('Failed to load global agents', e); }
  }

  async function handleCreateLibraryAgent() {
    if (!newLibraryAgent.name.trim()) return;
    try {
      const payload = { ...newLibraryAgent };
      if (!payload.model_id) delete payload.model_id;
      if (!payload.prompt_template_id) delete payload.prompt_template_id;
      if (!payload.cron_expression) delete payload.cron_expression;
      await createLibraryAgent(payload);
      setShowCreateLibraryAgent(false);
      setNewLibraryAgent({ name: '', role: '', system_prompt: '', model_id: '', temperature: 0.7, max_tokens: 4096, tools: [], tool_set_ids: [], share_memory: false, callable_agents: [], cron_expression: '', cron_instruction: '', prompt_template_id: '' });
      loadLibraryAgents();
    } catch (e) { console.error('Failed to create library agent', e); }
  }

  async function handleUpdateLibraryAgent(id, data) {
    try {
      await updateLibraryAgent(id, data);
      setEditingLibraryAgent(null);
      loadLibraryAgents();
    } catch (e) { console.error('Failed to update library agent', e); }
  }

  async function handleDeleteLibraryAgent(id, e) {
    e.stopPropagation();
    if (!window.confirm('Delete this library agent?')) return;
    try {
      await deleteLibraryAgent(id);
      setLibraryAgents(prev => prev.filter(a => a.id !== id));
      if (editingLibraryAgent?.id === id) setEditingLibraryAgent(null);
    } catch (e) { console.error('Failed to delete library agent', e); }
  }

  async function handleDuplicateLibraryAgent(id, e) {
    e.stopPropagation();
    try {
      await duplicateLibraryAgent(id);
      loadLibraryAgents();
    } catch (e) { console.error('Failed to duplicate library agent', e); }
  }

  async function handleImportLibraryAgentToLab(libraryAgent) {
    if (!activeLab) return;
    try {
      await createLabAgent(activeLab.id, {
        name: libraryAgent.name,
        role: libraryAgent.role || libraryAgent.description || '',
        system_prompt: libraryAgent.system_prompt,
        prompt_template_id: libraryAgent.prompt_template_id || undefined,
        model_id: libraryAgent.model_id || undefined,
        backend: libraryAgent.backend || 'native',
        temperature: libraryAgent.temperature,
        max_tokens: libraryAgent.max_tokens,
        tools: libraryAgent.tools || [],
        tool_set_ids: libraryAgent.tool_set_ids || [],
        share_memory: libraryAgent.share_memory || false,
        callable_agents: libraryAgent.callable_agents || [],
        cron_expression: libraryAgent.cron_expression || undefined,
        cron_instruction: libraryAgent.cron_instruction || '',
        library_agent_id: libraryAgent.id,
      });
      loadLabAgents(activeLab.id);
      refreshActiveLab();
    } catch (e) { console.error('Failed to import library agent', e); }
  }

  async function handleImportGlobalAgentToLab(agent) {
    if (!activeLab) return;
    try {
      await createLabAgent(activeLab.id, {
        name: agent.name,
        role: agent.description || '',
        system_prompt: agent.system_prompt || '',
        model_id: agent.model_id || undefined,
        temperature: agent.temperature || 0.7,
        max_tokens: agent.max_tokens || 4096,
        tools: agent.tools || [],
      });
      loadLabAgents(activeLab.id);
      refreshActiveLab();
    } catch (e) { console.error('Failed to import agent to lab', e); }
  }

  async function handleCreateLibraryAgentFromLabAgent(labAgent) {
    try {
      const payload = {
        name: labAgent.name,
        role: labAgent.role || '',
        system_prompt: labAgent.system_prompt || '',
        backend: labAgent.backend || 'native',
        temperature: labAgent.temperature ?? 0.7,
        max_tokens: labAgent.max_tokens ?? 4096,
        tools: labAgent.tools || [],
        tool_set_ids: labAgent.tool_set_ids || [],
        share_memory: labAgent.share_memory || false,
        callable_agents: labAgent.callable_agents || [],
        cron_expression: labAgent.cron_expression || '',
        cron_instruction: labAgent.cron_instruction || '',
      };
      if (labAgent.model_id) payload.model_id = labAgent.model_id;
      if (labAgent.prompt_template_id) payload.prompt_template_id = labAgent.prompt_template_id;
      await createLibraryAgent(payload);
      loadLibraryAgents();
    } catch (e) { console.error('Failed to save agent to library', e); }
  }

  // ── Tool Sets ───────────────────────────────────

  async function handleCreateToolSet() {
    if (!newToolSet.name.trim()) return;
    try {
      await createToolSet(newToolSet);
      setShowCreateToolSet(false);
      setNewToolSet({ name: '', description: '', tools: [] });
      loadToolSets();
    } catch (e) { console.error('Failed to create tool set', e); }
  }

  async function handleUpdateToolSet(id, data) {
    try {
      await updateToolSet(id, data);
      setEditingToolSet(null);
      loadToolSets();
    } catch (e) { console.error('Failed to update tool set', e); }
  }

  async function handleDeleteToolSet(id, e) {
    e.stopPropagation();
    try {
      await deleteToolSet(id);
      setToolSets(prev => prev.filter(ts => ts.id !== id));
      if (editingToolSet?.id === id) setEditingToolSet(null);
    } catch (e) { console.error('Failed to delete tool set', e); }
  }

  async function handleDuplicateToolSet(id, e) {
    e.stopPropagation();
    try {
      await duplicateToolSet(id);
      loadToolSets();
    } catch (e) { console.error('Failed to duplicate tool set', e); }
  }

  // ── Prompt Templates ────────────────────────────

  async function loadPromptTemplates() {
    try {
      const res = await getPromptTemplates();
      setPromptTemplates(res.data);
    } catch (e) { console.error('Failed to load prompt templates', e); }
  }

  async function handleCreatePromptTemplate() {
    if (!newPromptTemplate.name.trim() || !newPromptTemplate.content.trim()) return;
    try {
      await createPromptTemplate(newPromptTemplate);
      setShowCreatePromptTemplate(false);
      setNewPromptTemplate({ name: '', description: '', content: '', target: 'agent' });
      loadPromptTemplates();
    } catch (e) { console.error('Failed to create prompt template', e); }
  }

  async function handleUpdatePromptTemplate(id, data) {
    try {
      await updatePromptTemplate(id, data);
      setEditingPromptTemplate(null);
      loadPromptTemplates();
    } catch (e) { console.error('Failed to update prompt template', e); }
  }

  async function handleDeletePromptTemplate(id, e) {
    e.stopPropagation();
    try {
      await deletePromptTemplate(id);
      setPromptTemplates(prev => prev.filter(pt => pt.id !== id));
      if (editingPromptTemplate?.id === id) setEditingPromptTemplate(null);
    } catch (e) { console.error('Failed to delete prompt template', e); }
  }

  async function handleDuplicatePromptTemplate(id, e) {
    e.stopPropagation();
    try {
      await duplicatePromptTemplate(id);
      loadPromptTemplates();
    } catch (e) { console.error('Failed to duplicate prompt template', e); }
  }

  // ── CRON Jobs ───────────────────────────────────

  async function loadCronJobs() {
    try {
      const res = await getCronJobs();
      setCronJobs(res.data);
    } catch (e) { console.error('Failed to load cron jobs', e); }
  }

  async function handleCreateCron() {
    if (!newCron.name.trim() || !newCron.expression.trim()) return;
    try {
      await createCronJob(newCron);
      setShowCreateCron(false);
      setNewCron({ name: '', description: '', expression: '', method: 'orchestrator_inject', instruction: '' });
      loadCronJobs();
    } catch (e) { console.error('Failed to create cron job', e); }
  }

  async function handleUpdateCron(id, data) {
    try {
      await updateCronJob(id, data);
      setEditingCron(null);
      loadCronJobs();
    } catch (e) { console.error('Failed to update cron job', e); }
  }

  async function handleDeleteCron(id) {
    try {
      await deleteCronJob(id);
      setCronJobs(prev => prev.filter(c => c.id !== id));
      if (editingCron?.id === id) setEditingCron(null);
      setDeletingCronId(null);
    } catch (e) { console.error('Failed to delete cron job', e); }
  }

  async function handleDuplicateCron(id, e) {
    e.stopPropagation();
    try {
      await duplicateCronJob(id);
      loadCronJobs();
    } catch (e) { console.error('Failed to duplicate cron job', e); }
  }

  async function handleShowCronLabs(id, e) {
    e.stopPropagation();
    try {
      const res = await getCronJobLabs(id);
      setCronLabsUsing(prev => ({ ...prev, [id]: res.data }));
    } catch (e) { console.error('Failed to load cron labs', e); }
  }

  async function handleUpdateLabConfig(data) {
    if (!activeLab) return;
    try {
      const res = await updateLab(activeLab.id, data);
      setActiveLab(res.data);
      setEditingLabConfig(null);
      refreshLabList();
    } catch (e) { console.error('Failed to update lab', e); }
  }

  function handleInjectKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleInject();
    }
  }

  function handleInjectFileSelect(e) {
    const files = Array.from(e.target.files || []);
    setInjectFiles(prev => [...prev, ...files.map(f => ({
      file: f,
      name: f.name,
      preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
    }))]);
    if (injectFileRef.current) injectFileRef.current.value = '';
  }

  function removeInjectFile(idx) {
    setInjectFiles(prev => {
      const removed = prev[idx];
      if (removed?.preview) URL.revokeObjectURL(removed.preview);
      return prev.filter((_, i) => i !== idx);
    });
  }

  function formatTime(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function renderMessageContent(content) {
    if (!content) return null;
    // Detect markdown images: ![alt](url)
    const imgRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
    // Detect base64 image data URIs
    const b64Regex = /(data:image\/[a-z]+;base64,[A-Za-z0-9+/=]+)/g;

    const hasImages = imgRegex.test(content) || b64Regex.test(content);
    if (!hasImages) return content;

    // Split content and render images inline
    const parts = [];
    let lastIndex = 0;
    const allRegex = /!\[([^\]]*)\]\(([^)]+)\)|(data:image\/[a-z]+;base64,[A-Za-z0-9+/=]+)/g;
    let match;
    while ((match = allRegex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        parts.push(<span key={lastIndex}>{content.slice(lastIndex, match.index)}</span>);
      }
      const imgUrl = match[2] || match[3];
      const alt = match[1] || 'image';
      parts.push(
        <img key={match.index} src={imgUrl} alt={alt}
          style={{ maxWidth: '100%', maxHeight: 300, borderRadius: 4, margin: '4px 0', display: 'block', border: '1px solid rgba(255,255,255,0.1)' }}
        />
      );
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < content.length) {
      parts.push(<span key={lastIndex}>{content.slice(lastIndex)}</span>);
    }
    return <>{parts}</>;
  }

  function getModelName(modelId) {
    const m = allModelsRaw.find(m => m.id === modelId) || allModels.find(m => m.id === modelId);
    return m ? m.model_identifier : '—';
  }

  const statusIcon = (status) => {
    const map = { running: '🟢', paused: '⏸', completed: '🔵', failed: '🔴', created: '⚪', scheduled: '🟣' };
    return map[status] || '⚪';
  };

  const isJsonPreview = (viewer, data) => {
    const contentType = (data?.content_type || '').toLowerCase();
    const fileName = (viewer?.name || '').toLowerCase();
    return contentType.includes('application/json') || fileName.endsWith('.json');
  };

  const formatFileViewerText = (viewer, data) => {
    const content = data?.content;
    if (content == null) return '';
    if (!isJsonPreview(viewer, data)) return content;
    try {
      return JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      return content;
    }
  };

  const renderJsonPreview = (viewer, data) => {
    const formatted = formatFileViewerText(viewer, data);
    const tokenPattern = /("(?:\\.|[^"\\])*")(?=\s*:)|(\s*:)|(\"(?:\\.|[^"\\])*\")|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:]/g;
    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = tokenPattern.exec(formatted)) !== null) {
      if (match.index > lastIndex) {
        parts.push(formatted.slice(lastIndex, match.index));
      }

      const token = match[0];
      let className = 'lab-json-punctuation';

      if (match[1]) {
        className = 'lab-json-key';
      } else if (match[2]) {
        className = 'lab-json-punctuation';
      } else if (match[3]) {
        className = 'lab-json-string';
      } else if (match[4]) {
        className = 'lab-json-boolean';
      } else if (token === 'null') {
        className = 'lab-json-null';
      } else if (/^-?\d/.test(token)) {
        className = 'lab-json-number';
      }

      parts.push(<span key={parts.length} className={className}>{token}</span>);
      lastIndex = tokenPattern.lastIndex;
    }

    if (lastIndex < formatted.length) {
      parts.push(formatted.slice(lastIndex));
    }

    return parts;
  };

  // ── File viewer handlers ──
  const openOutputFile = async (filePath) => {
    if (!activeLab) return;
    setFileViewer({ type: 'output', path: filePath, name: filePath.split('/').pop() });
    setFileViewerLoading(true);
    setFileViewerData(null);
    setFileViewerHistory([]);
    setFileEditing(false);
    setFileSaveError(null);
    if (fileViewerBlobUrl) { URL.revokeObjectURL(fileViewerBlobUrl); setFileViewerBlobUrl(null); }
    try {
      const [contentRes, historyRes] = await Promise.all([
        getLabOutputFileContent(activeLab.id, filePath),
        getLabOutputFileHistory(activeLab.id, filePath),
      ]);
      setFileViewerData(contentRes.data);
      setFileViewerHistory(historyRes.data);
      // Load blob URL for media files (image/audio/video)
      const d = contentRes.data;
      if (d?.is_image || d?.is_audio || d?.is_video) {
        const blobUrl = await getAuthBlobUrl(getLabOutputFileUrl(activeLab.id, filePath));
        setFileViewerBlobUrl(blobUrl);
      }
    } catch (e) { console.error('File viewer error:', e); }
    setFileViewerLoading(false);
  };

  const openResourceFile = async (resource) => {
    if (!activeLab) return;
    setFileViewer({ type: 'resource', resourceId: resource.id, name: resource.original_name });
    setFileViewerLoading(true);
    setFileViewerData(null);
    setFileViewerHistory([]);
    setFileEditing(false);
    setFileSaveError(null);
    if (fileViewerBlobUrl) { URL.revokeObjectURL(fileViewerBlobUrl); setFileViewerBlobUrl(null); }
    try {
      const res = await getLabResourceContent(activeLab.id, resource.id);
      setFileViewerData(res.data);
      setFileViewerHistory([{ action: 'uploaded', agent_name: 'user', timestamp: resource.created_at }]);
      // Load blob URL for media files (image/audio/video)
      const d = res.data;
      if (d?.is_image || d?.is_audio || d?.is_video) {
        const blobUrl = await getAuthBlobUrl(getLabResourceUrl(activeLab.id, resource.id));
        setFileViewerBlobUrl(blobUrl);
      }
    } catch (e) { console.error('Resource viewer error:', e); }
    setFileViewerLoading(false);
  };

  const closeFileViewer = () => {
    if (fileViewerBlobUrl) URL.revokeObjectURL(fileViewerBlobUrl);
    setFileViewerBlobUrl(null);
    setFileViewer(null);
    setFileViewerData(null);
    setFileViewerHistory([]);
    setFileEditing(false);
    setFileSaveError(null);
  };

  // ── Workspace text-file editing ──
  // Editable only for text output files that came back complete (an
  // over-512KB read is truncated, so saving would clobber the dropped tail).
  const canEditFile = (
    fileViewer?.type === 'output' &&
    fileViewerData?.is_text &&
    fileViewerData?.content != null &&
    !fileViewerData?.truncated
  );

  const startFileEdit = () => {
    setFileEditContent(fileViewerData?.content ?? '');
    setFileSaveError(null);
    setFileEditing(true);
  };

  const cancelFileEdit = () => {
    setFileEditing(false);
    setFileEditContent('');
    setFileSaveError(null);
  };

  const saveFileEdit = async () => {
    if (!activeLab || !fileViewer) return;
    setFileSaving(true);
    setFileSaveError(null);
    try {
      await saveLabOutputFileContent(activeLab.id, fileViewer.path, fileEditContent);
      setFileEditing(false);
      // Re-fetch so size/mtime/history reflect the save, then refresh the list.
      await openOutputFile(fileViewer.path);
      loadOutputFiles(activeLab.id);
    } catch (e) {
      setFileSaveError(e?.response?.data?.detail || 'Failed to save file.');
    }
    setFileSaving(false);
  };

  // ── Render ──────────────────────────────────────

  return (
    <div className="lab-layout">
      {/* ══════ Left Panel: Sidebar ══════ */}
      <aside className="lab-list-panel">
        <div className="lab-sidebar-search">
          <span className="lab-sidebar-search-icon">{IC.search}</span>
          <input
            type="text"
            placeholder="Search labs, agents, prompts…"
            value={sidebarSearch}
            onChange={e => setSidebarSearch(e.target.value)}
          />
          {sidebarSearch && (
            <button className="lab-sidebar-search-clear" onClick={() => setSidebarSearch('')} title="Clear search">✕</button>
          )}
        </div>
        <div className="lab-sidebar-scroll">

          <div className="lab-sidebar-group-label">Workspace</div>

          {/* ── Labs Section ── */}
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, labs: !s.labs }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.labs ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>{IC.chip} Labs</h3>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); handleImportLab(); }} title="Import Lab from JSON">
                ↑
              </button>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); setShowCreateLab(!showCreateLab); }} title="New Lab">
                {IC.plus}
              </button>
            </div>

            {sidebarSection.labs && (
              <>
                {showCreateLab && (
                  <div className="lab-create-form">
                    <input
                      className="lab-input-sm"
                      placeholder="Lab name..."
                      value={newLabName}
                      onChange={e => setNewLabName(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleCreateLab()}
                      autoFocus
                    />
                    <input
                      className="lab-input-sm"
                      placeholder="Description (optional)"
                      value={newLabDesc}
                      onChange={e => setNewLabDesc(e.target.value)}
                    />
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleCreateLab}>Create</button>
                      <button className="lab-btn-ghost" onClick={() => setShowCreateLab(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                <div className="lab-sidebar-list">
                  {labs
                    .filter(l => !isAppLab(l))
                    .filter(l => matchesSearch(l.name, l.description))
                    .map(lab => (
                    <div
                      key={lab.id}
                      className={`lab-list-item ${lab.id === activeLab?.id ? 'active' : ''}`}
                      onClick={() => setActiveLab(lab)}
                    >
                      <div className="lab-list-item-header">
                        <span className="lab-status-icon">{statusIcon(lab.status)}</span>
                        <span className="lab-list-name">{lab.name}</span>
                        <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); setShareTarget(lab); }} title="Share" style={{ color: 'rgba(255,255,255,0.25)' }}>
                          👥
                        </button>
                        <button className="lab-list-delete" onClick={(e) => handleExportLab(lab.id, e)} title="Export JSON" style={{ color: 'rgba(255,255,255,0.25)' }}>
                          ↓
                        </button>
                        <button className="lab-list-delete" onClick={(e) => handleDuplicateLab(lab.id, e)} title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>
                          📋
                        </button>
                        <button className="lab-list-delete" onClick={(e) => handleDeleteLab(lab.id, e)} title="Delete">
                          {IC.trash}
                        </button>
                      </div>
                      <div className="lab-list-meta">
                        <span className="lab-list-status" style={{
                          background: STATUS_COLORS[lab.status]?.bg,
                          color: STATUS_COLORS[lab.status]?.color,
                        }}>{lab.status}</span>
                        {lab.status === 'failed' && lab.failure_reason && (
                          <span title={lab.failure_reason} style={{
                            fontSize: '0.65rem', color: '#ef4444', opacity: 0.7,
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            maxWidth: 150, display: 'inline-block', verticalAlign: 'middle',
                          }}>{lab.failure_reason}</span>
                        )}
                        {lab.agent_count > 0 && (
                          <span className="lab-list-agents">{lab.agent_count} agent{lab.agent_count > 1 ? 's' : ''}</span>
                        )}
                        {lab.current_iteration > 0 && (
                          <span className="lab-list-iter">iter {lab.current_iteration}{lab.max_iterations ? `/${lab.max_iterations}` : ''}</span>
                        )}
                      </div>
                    </div>
                  ))}
                  {labs.filter(l => !isAppLab(l)).length === 0 && !showCreateLab && (
                    <div className="lab-empty" style={{ padding: '12px 6px' }}>No labs yet. Click + to create one.</div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* ── Agents Section (Global + Library) ── */}
          <div className="lab-sidebar-group-label">Library</div>

          {/* ── Consumer-App Labs (templates + spawned instances) ── */}
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, labsApps: !s.labsApps }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.labsApps ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>{IC.chip} Consumer-app labs</h3>
            </div>
            {sidebarSection.labsApps && (
              <div className="lab-sidebar-list">
                {labs
                  .filter(l => isAppLab(l))
                  .filter(l => matchesSearch(l.name, l.description))
                  .map(lab => (
                  <div
                    key={lab.id}
                    className={`lab-list-item ${lab.id === activeLab?.id ? 'active' : ''}`}
                    onClick={() => setActiveLab(lab)}
                  >
                    <div className="lab-list-item-header">
                      <span className="lab-status-icon">{statusIcon(lab.status)}</span>
                      <span className="lab-list-name">{lab.name}</span>
                      <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); setShareTarget(lab); }} title="Share" style={{ color: 'rgba(255,255,255,0.25)' }}>
                        👥
                      </button>
                      <button className="lab-list-delete" onClick={(e) => handleExportLab(lab.id, e)} title="Export JSON" style={{ color: 'rgba(255,255,255,0.25)' }}>
                        ↓
                      </button>
                      <button className="lab-list-delete" onClick={(e) => handleDuplicateLab(lab.id, e)} title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>
                        📋
                      </button>
                      <button className="lab-list-delete" onClick={(e) => handleDeleteLab(lab.id, e)} title="Delete">
                        {IC.trash}
                      </button>
                    </div>
                    <div className="lab-list-meta">
                      <span className="lab-list-status" style={{
                        background: STATUS_COLORS[lab.status]?.bg,
                        color: STATUS_COLORS[lab.status]?.color,
                      }}>{lab.status}</span>
                      {lab.status === 'failed' && lab.failure_reason && (
                        <span title={lab.failure_reason} style={{
                          fontSize: '0.65rem', color: '#ef4444', opacity: 0.7,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          maxWidth: 150, display: 'inline-block', verticalAlign: 'middle',
                        }}>{lab.failure_reason}</span>
                      )}
                      {lab.agent_count > 0 && (
                        <span className="lab-list-agents">{lab.agent_count} agent{lab.agent_count > 1 ? 's' : ''}</span>
                      )}
                      {lab.current_iteration > 0 && (
                        <span className="lab-list-iter">iter {lab.current_iteration}{lab.max_iterations ? `/${lab.max_iterations}` : ''}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, agents: !s.agents }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.agents ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>{IC.bot} Agents</h3>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); setShowCreateLibraryAgent(!showCreateLibraryAgent); setSidebarSection(s => ({ ...s, agents: true })); }} title="New Library Agent">{IC.plus}</button>
            </div>
            {sidebarSection.agents && (
              <>
                {/* Global Agents (from Agents tab) */}
                {globalAgents.length > 0 && (
                  <div style={{ padding: '4px 8px 2px', fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Global Agents</div>
                )}
                <div className="lab-sidebar-list">
                  {globalAgents.filter(a => matchesSearch(a.name, a.role, a.description)).map(agent => (
                    <div key={`global-${agent.id}`} className="lab-list-item">
                      <div className="lab-list-item-header">
                        <span style={{ fontSize: '0.7rem' }}>🤖</span>
                        <span className="lab-list-name">{agent.name}</span>
                        {activeLab && (
                          <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); handleImportGlobalAgentToLab(agent); }}
                            title="Add to current lab" style={{ color: 'rgba(255,255,255,0.25)' }}>⬇️</button>
                        )}
                      </div>
                      <div className="lab-list-meta">
                        <span className="lab-list-agents">{agent.description || 'No description'}</span>
                        {agent.tools?.length > 0 && <span className="lab-list-agents" style={{ marginLeft: 6 }}>🔧 {agent.tools.length}</span>}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Library Agents */}
                {(libraryAgents.length > 0 || showCreateLibraryAgent) && (
                  <div style={{ padding: '4px 8px 2px', fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Library Agents</div>
                )}
                {showCreateLibraryAgent && (
                  <div className="lab-create-form">
                    <input className="lab-input-sm" placeholder="Agent name..." value={newLibraryAgent.name}
                      onChange={e => setNewLibraryAgent({...newLibraryAgent, name: e.target.value})}
                      onKeyDown={e => e.key === 'Enter' && handleCreateLibraryAgent()} autoFocus />
                    <input className="lab-input-sm" placeholder="Role (optional)" value={newLibraryAgent.role}
                      onChange={e => setNewLibraryAgent({...newLibraryAgent, role: e.target.value})} />
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleCreateLibraryAgent}>Create</button>
                      <button className="lab-btn-ghost" onClick={() => setShowCreateLibraryAgent(false)}>Cancel</button>
                    </div>
                  </div>
                )}
                <div className="lab-sidebar-list">
                  {libraryAgents.filter(a => matchesSearch(a.name, a.role, a.description)).map(agent => (
                    <div key={agent.id} className={`lab-list-item ${editingLibraryAgent?.id === agent.id ? 'active' : ''}`}
                      onClick={() => setEditingLibraryAgent(editingLibraryAgent?.id === agent.id ? null : { ...agent })}>
                      <div className="lab-list-item-header">
                        <span style={{ fontSize: '0.7rem' }}>{IC.bot}</span>
                        <span className="lab-list-name">{agent.name}</span>
                        {activeLab && (
                          <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); handleImportLibraryAgentToLab(agent); }}
                            title="Add to current lab" style={{ color: 'rgba(255,255,255,0.25)' }}>⬇️</button>
                        )}
                        <button className="lab-list-delete" onClick={(e) => handleDuplicateLibraryAgent(agent.id, e)}
                          title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>📋</button>
                        <button className="lab-list-delete" onClick={(e) => handleDeleteLibraryAgent(agent.id, e)} title="Delete">{IC.trash}</button>
                      </div>
                      <div className="lab-list-meta">
                        <span className="lab-list-agents">{agent.role || 'No role'}</span>
                        {agent.cron_expression && <span className="lab-list-agents" style={{ marginLeft: 6 }}>⏰ {agent.cron_expression}</span>}
                      </div>
                    </div>
                  ))}
                  {libraryAgents.length === 0 && !showCreateLibraryAgent && globalAgents.length === 0 && (
                    <div className="lab-empty" style={{ padding: '12px 6px', fontSize: '0.72rem' }}>No agents. Create them in the Agents tab or click + for a library agent.</div>
                  )}
                </div>
                {editingLibraryAgent && (
                  <LibraryAgentEditForm
                    agent={editingLibraryAgent}
                    allModels={allModels}
                    toolSets={toolSets}
                    promptTemplates={promptTemplates}
                    availablePipelines={availablePipelines}
                    builtinTools={builtinTools}
                    onSave={(data) => handleUpdateLibraryAgent(editingLibraryAgent.id, data)}
                    onCancel={() => setEditingLibraryAgent(null)}
                  />
                )}
              </>
            )}
          </div>

          {/* ── Tool Sets Section ── */}
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, toolSets: !s.toolSets }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.toolSets ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>{IC.tool} Tool Sets</h3>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); setShowCreateToolSet(!showCreateToolSet); setSidebarSection(s => ({ ...s, toolSets: true })); }} title="New Tool Set">
                {IC.plus}
              </button>
            </div>

            {sidebarSection.toolSets && (
              <>
                {showCreateToolSet && (
                  <div className="lab-create-form">
                    <input
                      className="lab-input-sm"
                      placeholder="Tool set name..."
                      value={newToolSet.name}
                      onChange={e => setNewToolSet({...newToolSet, name: e.target.value})}
                      onKeyDown={e => e.key === 'Enter' && handleCreateToolSet()}
                      autoFocus
                    />
                    <input
                      className="lab-input-sm"
                      placeholder="Description (optional)"
                      value={newToolSet.description}
                      onChange={e => setNewToolSet({...newToolSet, description: e.target.value})}
                    />
                    <div className="lab-config-group" style={{ marginTop: 2 }}>
                      <label className="lab-form-label">Tools</label>
                      <div className="lab-tools-grid">
                        {builtinTools.map(t => t.expandable ? (
                          <PipelineToolGroup key={t.name} tools={newToolSet.tools} pipelines={availablePipelines}
                            onChange={tools => setNewToolSet({...newToolSet, tools})} />
                        ) : t.subTools ? (
                          <SubToolGroup key={t.name} toolDef={t} tools={newToolSet.tools}
                            onChange={tools => setNewToolSet({...newToolSet, tools})} />
                        ) : (
                          <label key={t.name} className="lab-tool-checkbox">
                            <input type="checkbox" checked={newToolSet.tools.includes(t.name)}
                              onChange={e => {
                                const tools = e.target.checked
                                  ? [...newToolSet.tools, t.name]
                                  : newToolSet.tools.filter(n => n !== t.name);
                                setNewToolSet({...newToolSet, tools});
                              }} />
                            <span className="lab-tool-info">
                              <span className="lab-tool-name">{t.name}<SensitivePill tool={t} /></span>
                              <span className="lab-tool-desc">{t.description}</span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleCreateToolSet}>Create</button>
                      <button className="lab-btn-ghost" onClick={() => setShowCreateToolSet(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                <div className="lab-sidebar-list">
                  {toolSets.filter(ts => matchesSearch(ts.name, ts.description)).map(ts => (
                    <div key={ts.id} className={`lab-list-item ${editingToolSet?.id === ts.id ? 'active' : ''}`}
                      onClick={() => setEditingToolSet(editingToolSet?.id === ts.id ? null : { ...ts })}>
                      <div className="lab-list-item-header">
                        <span style={{ fontSize: '0.7rem' }}>{IC.tool}</span>
                        <span className="lab-list-name">{ts.name}</span>
                        <button className="lab-list-delete" onClick={(e) => handleDuplicateToolSet(ts.id, e)} title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>
                          📋
                        </button>
                        <button className="lab-list-delete" onClick={(e) => handleDeleteToolSet(ts.id, e)} title="Delete">
                          {IC.trash}
                        </button>
                      </div>
                      <div className="lab-list-meta">
                        <span className="lab-list-agents">{ts.tools?.length || 0} tool{(ts.tools?.length || 0) !== 1 ? 's' : ''}</span>
                      </div>
                    </div>
                  ))}
                  {toolSets.length === 0 && !showCreateToolSet && (
                    <div className="lab-empty" style={{ padding: '12px 6px', fontSize: '0.72rem' }}>No tool sets. Click + to create one.</div>
                  )}
                </div>

                {editingToolSet && (
                  <ToolSetEditForm
                    toolSet={editingToolSet}
                    availablePipelines={availablePipelines}
                    builtinTools={builtinTools}
                    onSave={(data) => handleUpdateToolSet(editingToolSet.id, data)}
                    onCancel={() => setEditingToolSet(null)}
                  />
                )}
              </>
            )}
          </div>

          {/* ── Prompt Templates Section ── */}
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, prompts: !s.prompts }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.prompts ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>{IC.edit} Prompts</h3>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); setShowCreatePromptTemplate(!showCreatePromptTemplate); setSidebarSection(s => ({ ...s, prompts: true })); }} title="New Prompt Template">
                {IC.plus}
              </button>
            </div>

            {sidebarSection.prompts && (
              <>
                {showCreatePromptTemplate && (
                  <div className="lab-create-form">
                    <input
                      className="lab-input-sm"
                      placeholder="Template name..."
                      value={newPromptTemplate.name}
                      onChange={e => setNewPromptTemplate({...newPromptTemplate, name: e.target.value})}
                      onKeyDown={e => e.key === 'Enter' && handleCreatePromptTemplate()}
                      autoFocus
                    />
                    <input
                      className="lab-input-sm"
                      placeholder="Description (optional)"
                      value={newPromptTemplate.description}
                      onChange={e => setNewPromptTemplate({...newPromptTemplate, description: e.target.value})}
                    />
                    <div className="lab-config-group" style={{ marginTop: 2 }}>
                      <label className="lab-form-label">Target</label>
                      <select className="lab-select" value={newPromptTemplate.target}
                        onChange={e => setNewPromptTemplate({...newPromptTemplate, target: e.target.value})}>
                        <option value="agent">Agent</option>
                        <option value="orchestrator">Orchestrator</option>
                      </select>
                    </div>
                    <textarea
                      className="lab-input-sm"
                      placeholder="Prompt content... Use {name}, {role}, {lab_name} as variables"
                      value={newPromptTemplate.content}
                      onChange={e => setNewPromptTemplate({...newPromptTemplate, content: e.target.value})}
                      rows={5}
                      style={{ resize: 'vertical' }}
                    />
                    <div style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', lineHeight: 1.4, padding: '2px 0' }}>
                      Variables: {'{name}'}, {'{role}'}, {'{lab_name}'}, {'{tools}'}, {'{agent_descriptions}'}
                    </div>
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleCreatePromptTemplate}>Create</button>
                      <button className="lab-btn-ghost" onClick={() => setShowCreatePromptTemplate(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                <div className="lab-sidebar-list">
                  {promptTemplates.filter(pt => matchesSearch(pt.name, pt.description, pt.target)).map(pt => (
                    <div key={pt.id} className={`lab-list-item ${editingPromptTemplate?.id === pt.id ? 'active' : ''}`}
                      onClick={() => setEditingPromptTemplate(editingPromptTemplate?.id === pt.id ? null : { ...pt })}>
                      <div className="lab-list-item-header">
                        <span style={{ fontSize: '0.7rem' }}>{IC.edit}</span>
                        <span className="lab-list-name">{pt.name}</span>
                        <button className="lab-list-delete" onClick={(e) => handleDuplicatePromptTemplate(pt.id, e)} title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>
                          📋
                        </button>
                        <button className="lab-list-delete" onClick={(e) => handleDeletePromptTemplate(pt.id, e)} title="Delete">
                          {IC.trash}
                        </button>
                      </div>
                      <div className="lab-list-meta">
                        <span className="lab-list-agents">{pt.target}</span>
                        {pt.description && <span style={{ marginLeft: 4, opacity: 0.5 }}>— {pt.description}</span>}
                      </div>
                    </div>
                  ))}
                  {promptTemplates.length === 0 && !showCreatePromptTemplate && (
                    <div className="lab-empty" style={{ padding: '12px 6px', fontSize: '0.72rem' }}>No prompt templates. Click + to create one.</div>
                  )}
                </div>

                {editingPromptTemplate && (
                  <PromptTemplateEditForm
                    template={editingPromptTemplate}
                    onSave={(data) => handleUpdatePromptTemplate(editingPromptTemplate.id, data)}
                    onCancel={() => setEditingPromptTemplate(null)}
                    onOpenFullView={(content) => setPromptEditor({
                      type: 'promptTemplate',
                      templateId: editingPromptTemplate.id,
                      templateName: editingPromptTemplate.name,
                      value: content,
                      dirty: false,
                    })}
                  />
                )}
              </>
            )}
          </div>

          {/* ── CRON Jobs Section ── */}
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, cron: !s.cron }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.cron ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>⏰ CRON Jobs</h3>
              <button className="lab-btn-icon" onClick={(e) => { e.stopPropagation(); setShowCreateCron(!showCreateCron); setSidebarSection(s => ({ ...s, cron: true })); }} title="New CRON Job">
                {IC.plus}
              </button>
            </div>

            {sidebarSection.cron && (
              <>
                {showCreateCron && (
                  <div className="lab-create-form">
                    <input
                      className="lab-input-sm"
                      placeholder="CRON name..."
                      value={newCron.name}
                      onChange={e => setNewCron({...newCron, name: e.target.value})}
                      onKeyDown={e => e.key === 'Enter' && handleCreateCron()}
                      autoFocus
                    />
                    <input
                      className="lab-input-sm"
                      placeholder="Description (optional)"
                      value={newCron.description}
                      onChange={e => setNewCron({...newCron, description: e.target.value})}
                    />
                    <input
                      className="lab-input-sm"
                      placeholder="Cron expression (e.g. */5 * * * *)"
                      value={newCron.expression}
                      onChange={e => setNewCron({...newCron, expression: e.target.value})}
                    />
                    <div className="lab-config-group" style={{ marginTop: 2 }}>
                      <label className="lab-form-label">Method</label>
                      <select className="lab-select" value={newCron.method}
                        onChange={e => setNewCron({...newCron, method: e.target.value})}>
                        <option value="orchestrator_inject">Orchestrator Inject</option>
                        <option value="direct_cmd_exec">Direct Command Exec</option>
                      </select>
                    </div>
                    <textarea
                      className="lab-input-sm"
                      placeholder={newCron.method === 'orchestrator_inject' ? 'Instruction to inject into lab feed...' : 'Command to execute in container...'}
                      value={newCron.instruction}
                      onChange={e => setNewCron({...newCron, instruction: e.target.value})}
                      rows={3}
                      style={{ resize: 'vertical' }}
                    />
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleCreateCron}>Create</button>
                      <button className="lab-btn-ghost" onClick={() => setShowCreateCron(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                <div className="lab-sidebar-list">
                  {cronJobs.filter(cj => matchesSearch(cj.name, cj.description, cj.expression)).map(cj => (
                    <div key={cj.id}>
                      <div className={`lab-list-item ${editingCron?.id === cj.id ? 'active' : ''}`}
                        onClick={() => { setEditingCron(editingCron?.id === cj.id ? null : { ...cj }); setCronLabsUsing(prev => { const n = {...prev}; delete n[cj.id]; return n; }); }}>
                        <div className="lab-list-item-header">
                          <span style={{ fontSize: '0.7rem' }}>⏰</span>
                          <span className="lab-list-name">{cj.name}</span>
                          <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); handleShowCronLabs(cj.id, e); }} title="Labs using this CRON" style={{ color: 'rgba(255,255,255,0.25)' }}>
                            🔗
                          </button>
                          <button className="lab-list-delete" onClick={(e) => handleDuplicateCron(cj.id, e)} title="Duplicate" style={{ color: 'rgba(255,255,255,0.25)' }}>
                            📋
                          </button>
                          <button className="lab-list-delete" onClick={(e) => { e.stopPropagation(); setDeletingCronId(cj.id); }} title="Delete">
                            {IC.trash}
                          </button>
                        </div>
                        <div className="lab-list-meta">
                          <span className="lab-list-agents" style={{ fontFamily: 'monospace' }}>{cj.expression}</span>
                          <span style={{ marginLeft: 4, opacity: 0.5 }}>— {cj.method === 'orchestrator_inject' ? '🤖 inject' : '⚡ cmd'}</span>
                        </div>
                        {cronLabsUsing[cj.id] && (
                          <div style={{ padding: '4px 0 2px', fontSize: '0.65rem' }}>
                            {cronLabsUsing[cj.id].length === 0 ? (
                              <span style={{ opacity: 0.4 }}>No labs using this CRON</span>
                            ) : (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                {cronLabsUsing[cj.id].map(l => (
                                  <span key={l.id} style={{ background: 'rgba(168,85,247,0.15)', padding: '1px 6px', borderRadius: 4, color: '#c4b5fd' }}>{l.name}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Delete confirmation */}
                      {deletingCronId === cj.id && (
                        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, padding: '8px 10px', margin: '4px 0' }}>
                          <div style={{ fontSize: '0.72rem', color: '#fca5a5', marginBottom: 6 }}>⚠️ Delete "{cj.name}"?</div>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button className="lab-btn-primary" style={{ background: '#ef4444', fontSize: '0.68rem', padding: '3px 10px' }} onClick={() => handleDeleteCron(cj.id)}>Delete</button>
                            <button className="lab-btn-ghost" style={{ fontSize: '0.68rem', padding: '3px 10px' }} onClick={() => setDeletingCronId(null)}>Cancel</button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {cronJobs.length === 0 && !showCreateCron && (
                    <div className="lab-empty" style={{ padding: '12px 6px', fontSize: '0.72rem' }}>No CRON jobs. Click + to create one.</div>
                  )}
                </div>

                {editingCron && (
                  <CronEditForm
                    cron={editingCron}
                    onSave={(data) => handleUpdateCron(editingCron.id, data)}
                    onCancel={() => setEditingCron(null)}
                  />
                )}
              </>
            )}
          </div>

          {/* ── Tool Configs Section ── */}
          <div className="lab-sidebar-group-label">Settings</div>
          <div className="lab-sidebar-section">
            <div className="lab-sidebar-section-header" onClick={() => setSidebarSection(s => ({ ...s, toolConfigs: !s.toolConfigs }))}>
              <span className={`lab-sidebar-chevron ${sidebarSection.toolConfigs ? 'open' : ''}`}>{IC.chevronRight}</span>
              <h3>🔧 Tool Configs</h3>
            </div>

            {sidebarSection.toolConfigs && (
              <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {/* Mail Config */}
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: 6, color: '#a5d8ff' }}>📧 Mail (SMTP / IMAP)</div>
                  {[
                    { key: 'smtp_host', label: 'SMTP Host', placeholder: 'smtp.gmail.com' },
                    { key: 'smtp_port', label: 'SMTP Port', placeholder: '587', type: 'number' },
                    { key: 'smtp_user', label: 'SMTP User', placeholder: 'user@gmail.com' },
                    { key: 'smtp_password', label: 'SMTP Password', placeholder: '••••••••', type: 'password' },
                    { key: 'smtp_from', label: 'From Address', placeholder: 'user@gmail.com' },
                    { key: 'imap_host', label: 'IMAP Host', placeholder: 'imap.gmail.com' },
                    { key: 'imap_port', label: 'IMAP Port', placeholder: '993', type: 'number' },
                    { key: 'imap_user', label: 'IMAP User', placeholder: '(same as SMTP if empty)' },
                    { key: 'imap_password', label: 'IMAP Password', placeholder: '(same as SMTP if empty)', type: 'password' },
                  ].map(f => (
                    <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                      <label style={{ fontSize: '0.65rem', width: 85, opacity: 0.6, flexShrink: 0 }}>{f.label}</label>
                      <input className="lab-input-sm" type={f.type || 'text'} placeholder={f.placeholder}
                        style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                        value={(toolConfigDrafts.mail || {})[f.key] || ''}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, mail: { ...(d.mail || {}), [f.key]: e.target.value } }))}
                      />
                    </div>
                  ))}
                  <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                    <label style={{ fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input type="checkbox" checked={(toolConfigDrafts.mail || {}).smtp_tls !== false}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, mail: { ...(d.mail || {}), smtp_tls: e.target.checked } }))} />
                      SMTP TLS
                    </label>
                    <label style={{ fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input type="checkbox" checked={(toolConfigDrafts.mail || {}).imap_tls !== false}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, mail: { ...(d.mail || {}), imap_tls: e.target.checked } }))} />
                      IMAP TLS
                    </label>
                    <button className="lab-btn-primary" style={{ marginLeft: 'auto', fontSize: '0.62rem', padding: '2px 8px' }}
                      onClick={() => saveToolConfig('mail')}>Save</button>
                  </div>
                </div>

                {/* Twitter Config */}
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: 6, color: '#a5d8ff' }}>𝕏 Twitter / X</div>
                  {[
                    { key: 'api_key', label: 'API Key', type: 'password' },
                    { key: 'api_secret', label: 'API Secret', type: 'password' },
                    { key: 'access_token', label: 'Access Token', type: 'password' },
                    { key: 'access_token_secret', label: 'Access Secret', type: 'password' },
                    { key: 'bearer_token', label: 'Bearer Token', placeholder: '(for read-only)', type: 'password' },
                  ].map(f => (
                    <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                      <label style={{ fontSize: '0.65rem', width: 85, opacity: 0.6, flexShrink: 0 }}>{f.label}</label>
                      <input className="lab-input-sm" type={f.type || 'text'} placeholder={f.placeholder || ''}
                        style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                        value={(toolConfigDrafts.twitter || {})[f.key] || ''}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, twitter: { ...(d.twitter || {}), [f.key]: e.target.value } }))}
                      />
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                    <button className="lab-btn-primary" style={{ fontSize: '0.62rem', padding: '2px 8px' }}
                      onClick={() => saveToolConfig('twitter')}>Save</button>
                  </div>
                </div>

                {/* Postiz Config */}
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: 6, color: '#a5d8ff' }}>📱 Postiz (Social Media)</div>
                  {[
                    { key: 'api_url', label: 'API URL', placeholder: 'http://bob-postiz:5000' },
                    { key: 'api_key', label: 'API Key', placeholder: 'Your Postiz API key', type: 'password' },
                  ].map(f => (
                    <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                      <label style={{ fontSize: '0.65rem', width: 85, opacity: 0.6, flexShrink: 0 }}>{f.label}</label>
                      <input className="lab-input-sm" type={f.type || 'text'} placeholder={f.placeholder || ''}
                        style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                        value={(toolConfigDrafts.postiz || {})[f.key] || ''}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, postiz: { ...(d.postiz || {}), [f.key]: e.target.value } }))}
                      />
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                    <button className="lab-btn-primary" style={{ fontSize: '0.62rem', padding: '2px 8px' }}
                      onClick={() => saveToolConfig('postiz')}>Save</button>
                  </div>
                </div>

                {/* TrustlessOTC Config */}
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: 6, color: '#a5d8ff' }}>🔁 TrustlessOTC (P2P Trading)</div>
                  {[
                    { key: 'api_base_url', label: 'API Base URL', placeholder: 'https://otc.boblabs.eu/api/v1' },
                    { key: 'api_key', label: 'API Key', placeholder: 'otc_… (from mint_apikey)', type: 'password' },
                  ].map(f => (
                    <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                      <label style={{ fontSize: '0.65rem', width: 85, opacity: 0.6, flexShrink: 0 }}>{f.label}</label>
                      <input className="lab-input-sm" type={f.type || 'text'} placeholder={f.placeholder || ''}
                        style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                        value={(toolConfigDrafts.trustless_otc || {})[f.key] || ''}
                        onChange={e => setToolConfigDrafts(d => ({ ...d, trustless_otc: { ...(d.trustless_otc || {}), [f.key]: e.target.value } }))}
                      />
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                    <button className="lab-btn-primary" style={{ fontSize: '0.62rem', padding: '2px 8px' }}
                      onClick={() => saveToolConfig('trustless_otc')}>Save</button>
                  </div>
                </div>

                {/* ── Multi-account Social Media Configs ── */}
                {[
                  { tt: 'social_x', icon: '𝕏', title: 'X (Twitter) — accounts',
                    fields: [
                      { key: 'api_key', label: 'API Key', type: 'password' },
                      { key: 'api_secret', label: 'API Secret', type: 'password' },
                      { key: 'access_token', label: 'Access Token', type: 'password' },
                      { key: 'access_token_secret', label: 'Access Secret', type: 'password' },
                      { key: 'bearer_token', label: 'Bearer Token', type: 'password' },
                    ] },
                  { tt: 'social_linkedin', icon: 'in', title: 'LinkedIn — accounts',
                    fields: [
                      { key: 'client_id', label: 'Client ID' },
                      { key: 'client_secret', label: 'Client Secret', type: 'password' },
                      { key: 'access_token', label: 'Access Token', type: 'password' },
                      { key: 'person_urn', label: 'Person URN', placeholder: 'urn:li:person:…' },
                      { key: 'organization_urn', label: 'Org URN', placeholder: 'urn:li:organization:… (optional)' },
                    ] },
                  { tt: 'social_instagram', icon: '📸', title: 'Instagram — accounts',
                    fields: [
                      { key: 'access_token', label: 'Access Token', type: 'password' },
                      { key: 'ig_user_id', label: 'IG User ID' },
                      { key: 'fb_page_id', label: 'FB Page ID' },
                    ] },
                  { tt: 'social_facebook', icon: 'f', title: 'Facebook — accounts',
                    fields: [
                      { key: 'page_access_token', label: 'Page Access Token', type: 'password' },
                      { key: 'page_id', label: 'Page ID' },
                      { key: 'app_id', label: 'App ID' },
                      { key: 'app_secret', label: 'App Secret', type: 'password' },
                    ] },
                ].map(({ tt, icon, title, fields }) => {
                  const draft = toolConfigDrafts[tt] || {};
                  const accounts = Array.isArray(draft.accounts) ? draft.accounts : [];
                  const updateAccounts = (next) => setToolConfigDrafts(d => ({ ...d, [tt]: { ...(d[tt] || {}), accounts: next } }));
                  return (
                    <div key={tt} style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#a5d8ff' }}>{icon} {title}</div>
                        <span style={{ fontSize: '0.55rem', fontWeight: 600, color: '#ffd5d5', background: 'rgba(220,38,38,0.18)', border: '1px solid rgba(220,38,38,0.5)', borderRadius: 3, padding: '0 5px', textTransform: 'uppercase', letterSpacing: '0.06em' }} title="Used by media_post_* tools — agents can publish to real accounts.">⚠ Sensitive</span>
                      </div>
                      {accounts.length === 0 && (
                        <div style={{ fontSize: '0.65rem', opacity: 0.5, marginBottom: 4 }}>No accounts configured.</div>
                      )}
                      {accounts.map((acc, idx) => (
                        <div key={idx} style={{ borderTop: idx > 0 ? '1px solid rgba(255,255,255,0.05)' : 'none', paddingTop: idx > 0 ? 6 : 0, marginBottom: 6 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                            <input className="lab-input-sm" placeholder="account_id (e.g. boblabs_main)" style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                              value={acc.account_id || ''}
                              onChange={e => { const next = [...accounts]; next[idx] = { ...acc, account_id: e.target.value }; updateAccounts(next); }} />
                            <input className="lab-input-sm" placeholder="Display label" style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                              value={acc.label || ''}
                              onChange={e => { const next = [...accounts]; next[idx] = { ...acc, label: e.target.value }; updateAccounts(next); }} />
                            <button className="lab-btn-ghost" style={{ fontSize: '0.62rem', padding: '2px 6px' }}
                              onClick={() => updateAccounts(accounts.filter((_, i) => i !== idx))}>×</button>
                          </div>
                          {fields.map(f => (
                            <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
                              <label style={{ fontSize: '0.65rem', width: 85, opacity: 0.6, flexShrink: 0 }}>{f.label}</label>
                              <input className="lab-input-sm" type={f.type || 'text'} placeholder={f.placeholder || ''}
                                style={{ flex: 1, fontSize: '0.65rem', padding: '2px 6px' }}
                                value={acc[f.key] || ''}
                                onChange={e => { const next = [...accounts]; next[idx] = { ...acc, [f.key]: e.target.value }; updateAccounts(next); }} />
                            </div>
                          ))}
                        </div>
                      ))}
                      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                        <button className="lab-btn-ghost" style={{ fontSize: '0.62rem', padding: '2px 8px' }}
                          onClick={() => updateAccounts([...accounts, { account_id: '', label: '' }])}>+ Add account</button>
                        <button className="lab-btn-primary" style={{ marginLeft: 'auto', fontSize: '0.62rem', padding: '2px 8px' }}
                          onClick={() => saveToolConfig(tt)}>Save</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </div>
      </aside>

      {/* ══════ Center: Execution Timeline ══════ */}
      <main className="lab-timeline-panel">
        {activeLab ? (
          <>
            {/* Header */}
            <div className={`lab-timeline-header ${selectedAgentId ? 'lab-timeline-header--agent' : ''}`}>
              <div className="lab-timeline-title">
                {selectedAgentId ? (() => {
                  const a = agents.find(x => x.id === selectedAgentId);
                  const ctx = a?.max_tokens ? ` · ctx ${a.max_tokens}` : '';
                  return (
                    <>
                      <span className="lab-status-icon">{IC.bot}</span>
                      <strong>{a?.name || 'Agent'}</strong>
                      <span className="lab-agent-feed-lab">({activeLab.name})</span>
                      <span className="lab-iter-badge" style={{ background: 'rgba(34,211,238,0.12)', color: '#22d3ee' }}>
                        {a?.model_id ? getModelName(a.model_id) : 'Default'}{ctx}
                      </span>
                    </>
                  );
                })() : (
                  <>
                    <span className="lab-status-icon">{statusIcon(activeLab.status)}</span>
                    <strong>{activeLab.name}</strong>
                    <span className="lab-status-badge" style={{
                      background: STATUS_COLORS[activeLab.status]?.bg,
                      color: STATUS_COLORS[activeLab.status]?.color,
                    }}>{activeLab.status}</span>
                    {activeLab.status === 'failed' && activeLab.failure_reason && (
                      <span className="lab-failure-reason" title={activeLab.failure_reason} style={{
                        fontSize: '0.75rem', color: '#ef4444', opacity: 0.85,
                        maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        display: 'inline-block', verticalAlign: 'middle', marginLeft: 6,
                      }}>— {activeLab.failure_reason}</span>
                    )}
                    {activeLab.current_iteration > 0 && (
                      <span className="lab-iter-badge">
                        Iteration {activeLab.current_iteration}{activeLab.max_iterations ? ` / ${activeLab.max_iterations}` : ''}
                      </span>
                    )}
                  </>
                )}
              </div>
              <div className="lab-timeline-actions">
                {selectedAgentId ? (
                  <>
                    <button
                      className="lab-btn-action lab-btn-ghost"
                      onClick={() => setAgentMemoryTakeover(v => !v)}
                      title={agentMemoryTakeover ? 'Back to feed' : 'Show agent memory'}
                    >
                      {agentMemoryTakeover ? '← Back' : `${IC.brain && ''}🧠 Memory`}
                    </button>
                    <button
                      className="lab-btn-action lab-btn-reset"
                      onClick={() => { setSelectedAgentId(null); setAgentMemoryTakeover(false); }}
                      title="Back to full lab feed"
                    >
                      ← Back to lab
                    </button>
                    {messages.length > 0 && !agentMemoryTakeover && (
                      <button className="lab-btn-action lab-btn-ghost" onClick={toggleExpandAll} title={allExpanded ? 'Collapse all' : 'Expand all'}>
                        {allExpanded ? '▾' : '▸'} {allExpanded ? 'Collapse' : 'Expand'}
                      </button>
                    )}
                    <button
                      className="lab-toolbar-close-btn"
                      onClick={() => setActiveLab(null)}
                      title="Close lab (back to dashboard)"
                      aria-label="Close lab"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
                    </button>
                  </>
                ) : (
                  <>
                {activeLab.status === 'created' && (
                  <button className="lab-btn-action lab-btn-run" onClick={() => handleRunLab()} title="Run">
                    {IC.play} Run
                  </button>
                )}
                {(activeLab.status === 'completed' || activeLab.status === 'failed') && (
                  <>
                    <button className="lab-btn-action lab-btn-run" onClick={() => handleRunLab()} title="Continue from where it stopped">
                      {IC.play} Continue
                    </button>
                    <button className="lab-btn-action lab-btn-reset" onClick={() => setShowResetConfirm(true)} title="Reset to fresh state">
                      ↺ Reset
                    </button>
                  </>
                )}
                {activeLab.status === 'running' && (
                  <button className="lab-btn-action lab-btn-pause" onClick={handlePauseLab} title="Pause">
                    {IC.pause} Pause
                  </button>
                )}
                {activeLab.status === 'paused' && (
                  <button className="lab-btn-action lab-btn-run" onClick={handleResumeLab} title="Resume">
                    {IC.play} Resume
                  </button>
                )}
                {(activeLab.status === 'running' || activeLab.status === 'paused') && (
                  <button className="lab-btn-action lab-btn-stop" onClick={handleStopLab} title="Stop">
                    {IC.stop} Stop
                  </button>
                )}
                {messages.length > 0 && (
                  <button className="lab-btn-action lab-btn-ghost" onClick={toggleExpandAll} title={allExpanded ? 'Collapse all' : 'Expand all'}>
                    {allExpanded ? '▾' : '▸'} {allExpanded ? 'Collapse' : 'Expand'}
                  </button>
                )}
                <div className="lab-toolbar-more">
                  <button
                    className="lab-toolbar-more-btn"
                    onClick={(e) => { e.stopPropagation(); setLabToolbarMenuOpen(v => !v); }}
                    title="More actions"
                  >
                    {IC.more}
                  </button>
                  {labToolbarMenuOpen && (
                    <>
                      <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={() => setLabToolbarMenuOpen(false)} />
                      <div className="lab-toolbar-menu" onClick={() => setLabToolbarMenuOpen(false)}>
                        <button className="lab-toolbar-menu-item" onClick={() => setShareTarget(activeLab)}>
                          {IC.share}<span>Share…</span>
                        </button>
                        <button className="lab-toolbar-menu-item" onClick={(e) => handleDuplicateLab(activeLab.id, e)}>
                          {IC.copy}<span>Duplicate</span>
                        </button>
                        <button className="lab-toolbar-menu-item" onClick={(e) => handleExportLab(activeLab.id, e)}>
                          {IC.download}<span>Export JSON</span>
                        </button>
                        <div className="lab-toolbar-menu-divider" />
                        <button className="lab-toolbar-menu-item danger" onClick={() => setDeleteLabConfirm(activeLab.id)}>
                          {IC.trash}<span>Delete lab…</span>
                        </button>
                      </div>
                    </>
                  )}
                </div>
                <button
                  className="lab-toolbar-close-btn"
                  onClick={() => setActiveLab(null)}
                  title="Close lab (back to dashboard)"
                  aria-label="Close lab"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
                </button>
                  </>
                )}
              </div>
            </div>

            {/* Reset confirmation dialog */}
            {showResetConfirm && (
              <div className="lab-reset-overlay">
                <div className="lab-reset-dialog">
                  <div className="lab-reset-warning">⚠️ WARNING</div>
                  <p className="lab-reset-text">
                    All messages, memories, and output files will be <strong>permanently deleted</strong>.<br/>
                    The lab will return to its initial state. Are you sure?
                  </p>
                  <div className="lab-reset-actions">
                    <button className="lab-btn-danger" onClick={handleResetLab}>
                      Yes, Reset
                    </button>
                    <button className="lab-btn-ghost" onClick={() => setShowResetConfirm(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Delete lab confirmation dialog */}
            {deleteLabConfirm && (
              <div className="lab-reset-overlay">
                <div className="lab-reset-dialog">
                  <div className="lab-reset-warning">⚠️ Delete Lab</div>
                  <p className="lab-reset-text">
                    The lab will be <strong>permanently deleted</strong>. All data (agents, messages, memories, resources, output files) will be lost.<br/>
                    Are you sure?
                  </p>
                  <div className="lab-reset-actions">
                    <button className="lab-btn-danger" onClick={confirmDeleteLab}>
                      Yes, Delete
                    </button>
                    <button className="lab-btn-ghost" onClick={() => setDeleteLabConfirm(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Delete agent confirmation dialog */}
            {deleteAgentConfirm && (
              <div className="lab-reset-overlay">
                <div className="lab-reset-dialog">
                  <div className="lab-reset-warning">⚠️ Delete Agent</div>
                  <p className="lab-reset-text">
                    This agent will be <strong>permanently removed</strong> from the lab.<br/>
                    Are you sure?
                  </p>
                  <div className="lab-reset-actions">
                    <button className="lab-btn-danger" onClick={confirmDeleteAgent}>
                      Yes, Delete
                    </button>
                    <button className="lab-btn-ghost" onClick={() => setDeleteAgentConfirm(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}

            {shareTarget && (
              <ShareModal
                resourceType="lab"
                resourceId={shareTarget.id}
                acl={shareTarget.acl}
                isPublic={shareTarget.is_public}
                onClose={() => setShareTarget(null)}
                onUpdated={() => { refreshLabList(); refreshActiveLab(); }}
              />
            )}

            {/* ═══ File Viewer ═══ */}
            {fileViewer ? (
              <div className="lab-file-viewer">
                <div className="lab-file-viewer-header">
                  <button className="lab-btn-ghost" onClick={closeFileViewer} title="Back to timeline">← Back</button>
                  <span className="lab-file-viewer-name">📄 {fileViewer.name}</span>
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                    {fileEditing ? (
                      <>
                        <button className="lab-btn-sm" disabled={fileSaving} onClick={saveFileEdit}>
                          {fileSaving ? 'Saving…' : '💾 Save'}
                        </button>
                        <button className="lab-btn-ghost" disabled={fileSaving} onClick={cancelFileEdit}>Cancel</button>
                      </>
                    ) : (
                      <>
                        {canEditFile && (
                          <button className="lab-btn-sm" onClick={startFileEdit} title="Edit this file">✏️ Edit</button>
                        )}
                        <button className="lab-btn-sm" onClick={() => {
                          const url = fileViewer.type === 'resource'
                            ? getLabResourceUrl(activeLab?.id, fileViewer.resourceId)
                            : getLabOutputFileUrl(activeLab?.id, fileViewer.path);
                          downloadFile(url, fileViewer.name);
                        }}>⬇ Download</button>
                      </>
                    )}
                  </div>
                </div>
                <div className="lab-file-viewer-body">
                  <div className="lab-file-viewer-content">
                    {fileViewerLoading ? (
                      <div className="lab-empty" style={{ paddingTop: 60 }}>Loading...</div>
                    ) : fileViewerData?.is_image && fileViewerBlobUrl ? (
                      <div style={{ textAlign: 'center', padding: 20 }}>
                        <img
                          src={fileViewerBlobUrl}
                          alt={fileViewer.name}
                          style={{ maxWidth: '100%', maxHeight: '80vh', borderRadius: 8 }}
                        />
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
                    ) : fileEditing ? (
                      <div className="lab-file-editor">
                        {fileSaveError && <div className="lab-file-editor-error">{fileSaveError}</div>}
                        <textarea
                          className="lab-file-editor-textarea"
                          value={fileEditContent}
                          onChange={e => setFileEditContent(e.target.value)}
                          spellCheck={false}
                          autoFocus
                        />
                      </div>
                    ) : fileViewerData?.is_text && fileViewerData?.content != null ? (
                      <pre className={`lab-file-viewer-pre ${isJsonPreview(fileViewer, fileViewerData) ? 'lab-file-viewer-pre-json' : ''}`}>
                        {isJsonPreview(fileViewer, fileViewerData)
                          ? renderJsonPreview(fileViewer, fileViewerData)
                          : formatFileViewerText(fileViewer, fileViewerData)}
                      </pre>
                    ) : (
                      <div className="lab-empty" style={{ paddingTop: 60 }}>
                        Binary file — cannot preview.
                        <br/><button className="lab-btn-ghost" onClick={() => {
                          const url = fileViewer.type === 'resource'
                            ? getLabResourceUrl(activeLab?.id, fileViewer.resourceId)
                            : getLabOutputFileUrl(activeLab?.id, fileViewer.path);
                          downloadFile(url, fileViewer.name);
                        }}>Download file</button>
                      </div>
                    )}
                  </div>
                  {fileViewerHistory.length > 0 && (
                    <div className="lab-file-viewer-history">
                      <div className="lab-file-viewer-history-title">File History</div>
                      {fileViewerHistory.map((h, i) => (
                        <div key={i} className="lab-file-viewer-history-item">
                          <span className="lab-file-history-action">{h.action === 'created' ? '🆕' : h.action === 'uploaded' ? '📎' : '✏️'} {h.action}</span>
                          <span className="lab-file-history-time">{h.timestamp ? new Date(h.timestamp).toLocaleString() : '—'}</span>
                          <span className="lab-file-history-agent">by <strong>{h.agent_name}</strong></span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : memoryView ? (
            /* ═══ Memory Viewer ═══ */
            <div className="lab-memory-viewer">
              <div className="lab-file-viewer-header">
                <button className="lab-btn-ghost" onClick={() => setMemoryView(null)} title="Back to timeline">← Back</button>
                <span className="lab-file-viewer-name">🧠 {memoryView === 'lab' ? 'Orchestrator Memory' : agents.find(a => a.id === memoryView)?.name + ' Memory' || 'Agent Memory'}</span>
              </div>
              <div className="lab-memory-viewer-body">
                {(() => {
                  const viewMems = memoryView === 'lab'
                    ? memories.filter(m => m.scope === 'lab')
                    : memories.filter(m => m.agent_id === memoryView);
                  if (viewMems.length === 0) return <div className="lab-empty" style={{ paddingTop: 40 }}>No memories in this scope.</div>;

                  // Determine which agents/orchestrator have access
                  const accessors = memoryView === 'lab'
                    ? ['Orchestrator', ...agents.map(a => a.name)]
                    : [agents.find(a => a.id === memoryView)?.name || 'Agent'].concat(
                        agents.find(a => a.id === memoryView)?.share_memory ? ['Shared'] : []
                      );

                  return (
                    <>
                      <div className="lab-mem-access-bar">
                        <span className="lab-mem-access-label">Accessible by:</span>
                        {accessors.map((name, i) => (
                          <span key={i} className="lab-mem-access-tag">{name}</span>
                        ))}
                      </div>
                      {viewMems
                        .sort((a, b) => b.importance - a.importance)
                        .map(mem => {
                          const preview = (mem.content || '').slice(0, 80).replace(/\n/g, ' ');
                          const hasMore = (mem.content || '').length > 80;
                          const handleToggle = async () => {
                            try {
                              const res = await toggleLabMemoryVisibility(activeLab.id, mem.id, !mem.is_hidden);
                              setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, is_hidden: res.data.is_hidden } : m));
                            } catch (e) { console.error('toggle visibility failed', e); }
                          };
                          return (
                            <div key={mem.id} className={`lab-mem-detail-card ${mem.is_hidden ? 'hidden-mem' : ''}`}>
                              <div className="lab-mem-detail-header">
                                <span className="lab-mem-detail-key">{mem.key}</span>
                                <div className="lab-mem-detail-tags">
                                  {mem.is_hidden && <span className="lab-mem-tag hidden">HIDDEN</span>}
                                  <span className="lab-mem-tag type">{mem.memory_type}</span>
                                  <span className="lab-mem-tag imp">imp {mem.importance}/10</span>
                                  <span className="lab-mem-tag scope" style={{
                                    background: mem.scope === 'agent' ? 'rgba(34,197,94,0.12)' : 'rgba(59,130,246,0.12)',
                                    color: mem.scope === 'agent' ? '#22c55e' : '#3b82f6',
                                  }}>{mem.scope}</span>
                                  <button className="lab-mem-vis-btn-detail" title={mem.is_hidden ? 'Show memory' : 'Hide memory'} onClick={handleToggle}>
                                    {mem.is_hidden ? '👁️‍🗨️ Show' : '👁️ Hide'}
                                  </button>
                                </div>
                              </div>
                              <div className="lab-mem-detail-levels">
                                <div className="lab-mem-level">
                                  <span className="lab-mem-level-label">Level 0 — Index</span>
                                  <div className="lab-mem-level-content">[{mem.key}] imp={mem.importance} {preview}{hasMore ? '…' : ''}</div>
                                </div>
                                <div className="lab-mem-level">
                                  <span className="lab-mem-level-label">Level 1 — Full Content</span>
                                  <pre className="lab-mem-level-content full">{mem.content}</pre>
                                </div>
                              </div>
                              <div className="lab-mem-detail-meta">
                                <span>Updated: {new Date(mem.updated_at).toLocaleString()}</span>
                                {mem.expires_at && <span>Expires: {new Date(mem.expires_at).toLocaleString()}</span>}
                              </div>
                            </div>
                          );
                        })}
                    </>
                  );
                })()}
              </div>
            </div>
            ) : promptEditor ? (
            /* ═══ Prompt Editor (Central View) ═══ */
            <div className="lab-prompt-editor-view">
              <div className="lab-file-viewer-header">
                <button className="lab-btn-ghost" onClick={() => setPromptEditor(null)} title="Back to timeline">← Back</button>
                <span className="lab-file-viewer-name">
                  {promptEditor.type === 'strategy' ? `📋 Strategy Prompt: ${activeLab?.loop_type?.replace(/_/g, ' ')}` :
                   promptEditor.type === 'orchestrator' ? '🧠 Orchestrator Prompt' :
                   promptEditor.type === 'promptTemplate' ? `📝 Template: ${promptEditor.templateName}` :
                   `🤖 Agent Prompt: ${agents.find(a => a.id === promptEditor.agentId)?.name || 'Agent'}`}
                </span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  {promptEditor.type === 'strategy' && promptEditor.dirty && (
                    <button className="lab-btn-ghost" style={{ fontSize: '0.7rem', color: '#ef4444' }} onClick={async () => {
                      await handleUpdateLabConfig({ strategy_prompt_override: null });
                      const res = await getStrategyPrompt(activeLab.loop_type);
                      setPromptEditor({ ...promptEditor, value: res.data.prompt, dirty: false, isOverride: false });
                    }}>↺ Reset to default</button>
                  )}
                  <button className="lab-btn-primary" style={{ fontSize: '0.72rem', padding: '4px 12px' }} onClick={async () => {
                    try {
                      if (promptEditor.type === 'strategy') {
                        await handleUpdateLabConfig({ strategy_prompt_override: promptEditor.value });
                      } else if (promptEditor.type === 'orchestrator') {
                        await handleUpdateLabConfig({ orchestrator_prompt: promptEditor.value });
                      } else if (promptEditor.type === 'agent') {
                        await updateLabAgent(activeLab.id, promptEditor.agentId, { system_prompt: promptEditor.value });
                        const agRes = await getLabAgents(activeLab.id);
                        setAgents(agRes.data);
                        if (editingAgent?.id === promptEditor.agentId) {
                          const updated = agRes.data.find(a => a.id === promptEditor.agentId);
                          if (updated) setEditingAgent({ ...updated });
                        }
                      } else if (promptEditor.type === 'promptTemplate') {
                        await updatePromptTemplate(promptEditor.templateId, { content: promptEditor.value });
                        loadPromptTemplates();
                        if (editingPromptTemplate?.id === promptEditor.templateId) {
                          setEditingPromptTemplate(prev => ({ ...prev, content: promptEditor.value }));
                        }
                      }
                      setPromptEditor(prev => ({ ...prev, dirty: false }));
                    } catch (e) { console.error('Prompt save failed', e); }
                  }} disabled={!promptEditor.dirty}>{IC.save} Save</button>
                </div>
              </div>
              <div className="lab-prompt-editor-body">
                {promptEditor.type === 'strategy' && (
                  <div className="lab-prompt-editor-info">
                    Uses placeholders: <code>{'{lab_name}'}</code>, <code>{'{agent_descriptions}'}</code>
                    {promptEditor.isOverride && <span className="lab-prompt-override-badge">CUSTOM OVERRIDE</span>}
                  </div>
                )}
                <textarea
                  className="lab-prompt-editor-textarea"
                  value={promptEditor.value}
                  onChange={e => setPromptEditor(prev => ({ ...prev, value: e.target.value, dirty: true }))}
                  spellCheck={false}
                />
              </div>
            </div>
            ) : (
            <>
            {selectedAgentId && agentMemoryTakeover ? (
              <div className="lab-timeline-messages lab-agent-memory-view">
                <div className="lab-section-title" style={{ marginBottom: 12 }}>
                  🧠 Agent memory · {agents.find(a => a.id === selectedAgentId)?.name || ''}
                  <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)' }}>
                    {agentMemories.length} entr{agentMemories.length === 1 ? 'y' : 'ies'}
                  </span>
                </div>
                {agentMemories.length === 0 && (
                  <div className="lab-empty" style={{ paddingTop: 40 }}>No memory entries for this agent yet.</div>
                )}
                {agentMemories.map(mem => (
                  <div key={mem.id} className="lab-memory-card">
                    <div className="lab-memory-card-header">
                      <span className="lab-memory-key">{mem.key || mem.scope || 'memory'}</span>
                      {mem.scope && <span className="lab-memory-scope">{mem.scope}</span>}
                      <span style={{ marginLeft: 'auto', fontSize: '0.65rem', color: 'rgba(255,255,255,0.4)' }}>
                        {mem.created_at ? new Date(mem.created_at).toLocaleString() : ''}
                      </span>
                    </div>
                    <pre className="lab-memory-value">{typeof mem.value === 'string' ? mem.value : JSON.stringify(mem.value, null, 2)}</pre>
                  </div>
                ))}
              </div>
            ) : (
            <>
            {/* Messages */}
            <div className="lab-timeline-messages" ref={messagesContainerRef}>
              {messages.length === 0 && (
                <div className="lab-empty" style={{ paddingTop: 60 }}>
                  {activeLab.status === 'created'
                    ? 'Lab is ready. Add agents and click Run to start.'
                    : 'No messages yet.'}
                </div>
              )}
              {messages.map(msg => {
                const isExpanded = expandedMessages.has(msg.id);
                let preview = msg.content?.length > 120 ? msg.content.slice(0, 120) + '…' : msg.content;
                if (msg.message_type === 'tool_call' && msg.tool_name) {
                  const args = msg.tool_input ? Object.entries(msg.tool_input).map(([k,v]) => {
                    const vs = typeof v === 'string' ? v : JSON.stringify(v);
                    return `${k}=${vs.length > 40 ? vs.slice(0,40) + '…' : vs}`;
                  }).join(', ') : '';
                  const status = msg.tool_output ? (msg.tool_output.success === false ? ' ✗' : ' ✓') : '';
                  preview = `${msg.tool_name}(${args})${status}`;
                  if (preview.length > 150) preview = preview.slice(0, 150) + '…';
                }
                return (
                  <div key={msg.id} className={`lab-msg lab-msg-${msg.sender_type} lab-msg-type-${msg.message_type}${isExpanded ? ' lab-msg-expanded' : ''}`}
                       onClick={() => toggleMessage(msg.id)} style={{ cursor: 'pointer' }}>
                    <div className="lab-msg-avatar" style={{
                      background: msg.sender_type === 'user' ? 'rgba(185,28,28,0.2)' :
                                  msg.sender_type === 'orchestrator' ? 'rgba(59,130,246,0.2)' :
                                  msg.sender_type === 'agent' ? 'rgba(34,197,94,0.2)' :
                                  'rgba(255,255,255,0.08)',
                      color: msg.sender_type === 'user' ? '#b91c1c' :
                             msg.sender_type === 'orchestrator' ? '#3b82f6' :
                             msg.sender_type === 'agent' ? '#22c55e' : 'rgba(255,255,255,0.5)',
                    }}>
                      {msg.sender_type === 'user' ? IC.user :
                       msg.sender_type === 'orchestrator' ? IC.chip :
                       msg.sender_type === 'agent' ? IC.bot : IC.settings}
                    </div>
                    <div className="lab-msg-body">
                      <div className="lab-msg-meta">
                        <span className="lab-msg-expand-icon">{isExpanded ? '▾' : '▸'}</span>
                        <span className="lab-msg-sender" style={{ color: MSG_TYPE_COLORS[msg.message_type] || 'rgba(255,255,255,0.5)' }}>
                          {msg.sender_name || msg.sender_type.toUpperCase()}
                        </span>
                        {msg.target_name && (
                          <span className="lab-msg-target">→ {msg.target_name}</span>
                        )}
                        <span className="lab-msg-type-badge" style={{
                          background: `${MSG_TYPE_COLORS[msg.message_type] || 'rgba(255,255,255,0.3)'}20`,
                          color: MSG_TYPE_COLORS[msg.message_type] || 'rgba(255,255,255,0.5)',
                        }}>{msg.message_type}</span>
                        <span className="lab-msg-time">{formatTime(msg.created_at)}</span>
                        {msg.model_used && <span className="lab-msg-model">{msg.model_used}</span>}
                        {msg.tokens_out > 0 && (
                          <span className="lab-msg-tokens">{msg.tokens_in}→{msg.tokens_out}t · {msg.duration_ms}ms</span>
                        )}
                        {msg.tokens_in > 0 && msg.model_used && contextLengthMap[msg.model_used] && (() => {
                          const ctx = contextLengthMap[msg.model_used];
                          const pct = Math.min((msg.tokens_in / ctx) * 100, 100);
                          const color = pct > 90 ? '#ef4444' : pct > 70 ? '#f59e0b' : '#22c55e';
                          return <span className="ctx-bar" title={`Context: ${msg.tokens_in.toLocaleString()} / ${ctx.toLocaleString()} (${pct.toFixed(1)}%)`}>
                            <span className="ctx-bar-fill" style={{ width: `${pct}%`, background: color }} />
                            <span className="ctx-bar-label">{pct.toFixed(0)}%</span>
                          </span>;
                        })()}
                      </div>
                      {isExpanded ? (
                        <>
                          {!(msg.message_type === 'tool_call' && msg.tool_name) && (
                            <div className="lab-msg-content">{renderMessageContent(msg.content)}</div>
                          )}
                          {Array.isArray(msg.extra?.hermes_steps) && msg.extra.hermes_steps.length > 0 && (
                            <div className="lab-msg-tool" style={{ marginTop: 6 }}>
                              <div className="lab-msg-tool-header">
                                <span>⚙ Hermes flow · {msg.extra.hermes_steps.filter(s => s.type === 'turn').length} round{msg.extra.hermes_steps.filter(s => s.type === 'turn').length > 1 ? 's' : ''}</span>
                              </div>
                              {msg.extra.hermes_steps.map((s, i) => (
                                <div key={i} style={{ fontSize: '0.68rem', color: 'rgba(255,255,255,0.55)', padding: '3px 8px', borderTop: i > 0 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                                  {s.type === 'note' ? (
                                    <em>{s.detail}</em>
                                  ) : (
                                    <>
                                      <strong>round {s.round}</strong>
                                      {' · '}{s.api_calls} model call{s.api_calls > 1 ? 's' : ''}
                                      {s.tools?.length > 0 && <> · 🔧 {s.tools.join(', ')}</>}
                                      {s.task_done && <span style={{ color: '#22c55e' }}> · ✓ TASK_DONE</span>}
                                      {s.needs_input && <span style={{ color: '#f59e0b' }}> · ⚠ needs input</span>}
                                      {s.exit_reason && <span style={{ opacity: 0.6 }}> · {s.exit_reason}</span>}
                                      {s.reasoning && (
                                        <div style={{ opacity: 0.7, marginTop: 2, fontStyle: 'italic' }}>💭 {s.reasoning}</div>
                                      )}
                                    </>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                          {msg.tool_name && (
                            <div className={`lab-msg-tool ${(['python_exec','shell_exec','db_query','db_execute','db_schema'].includes(msg.tool_name)) ? 'lab-msg-tool-terminal' : ''}`}>
                              <div className="lab-msg-tool-header">
                                {(['python_exec','shell_exec','db_query','db_execute','db_schema'].includes(msg.tool_name)) ? (
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
              })}
              <div ref={messagesEndRef} />
            </div>

            {/* Scroll to bottom arrow */}
            {showScrollBtn && (
              <button className="lab-scroll-bottom-btn" onClick={scrollToBottom} title="Scroll to latest">
                ↓
              </button>
            )}

            {/* Inject input */}
            <div className="lab-inject-area">
              {injectFiles.length > 0 && (
                <div className="lab-inject-files">
                  {injectFiles.map((f, i) => (
                    <div key={i} className="lab-inject-file-chip">
                      {f.preview ? (
                        <img src={f.preview} alt={f.name} className="lab-inject-file-thumb" />
                      ) : (
                        <span className="lab-inject-file-icon">📄</span>
                      )}
                      <span className="lab-inject-file-name">{f.name}</span>
                      <button className="lab-inject-file-remove" onClick={() => removeInjectFile(i)}>&times;</button>
                    </div>
                  ))}
                </div>
              )}
              <div className="lab-inject-row">
                <input
                  type="file"
                  ref={injectFileRef}
                  multiple
                  style={{ display: 'none' }}
                  onChange={handleInjectFileSelect}
                />
                <button
                  className="lab-inject-attach-btn"
                  onClick={() => injectFileRef.current?.click()}
                  disabled={injecting}
                  title="Attach files"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                </button>
                <textarea
                  className="lab-inject-input"
                  value={injectInput}
                  onChange={e => setInjectInput(e.target.value)}
                  onKeyDown={handleInjectKeyDown}
                  placeholder="Send a message to the lab..."
                  rows={1}
                  disabled={injecting}
                />
                <button
                  className="lab-inject-btn"
                  onClick={handleInject}
                  disabled={(!injectInput.trim() && !injectFiles.length) || injecting}
                >
                  {injecting ? IC.loader : IC.send}
                </button>
              </div>
            </div>
            </>
            )}
            </>
            )}
          </>
        ) : (
          <LabDashboard
            labs={labs}
            onSelect={(lab) => setActiveLab(lab)}
            onRefresh={refreshLabList}
          />
        )}
      </main>

      {/* ══════ Right Panel: Agent Inspector ══════ */}
      {activeLab && (
        <aside className="lab-inspector-panel" style={{ width: inspectorWidth, minWidth: inspectorWidth }}>
          <div className="lab-inspector-resize" onMouseDown={onInspectorMouseDown} />
          <div className="lab-inspector-tabs">
            <button className={`lab-insp-tab ${inspectorTab === 'agents' ? 'active' : ''}`} onClick={() => setInspectorTab('agents')} title="Agents">
              {IC.bot}<span>Agents</span>
            </button>
            <button className={`lab-insp-tab ${inspectorTab === 'resources' ? 'active' : ''}`} onClick={() => setInspectorTab('resources')} title="Resources">
              {IC.folder}<span>Resources</span>
            </button>
            <button className={`lab-insp-tab ${inspectorTab === 'memory' ? 'active' : ''}`} onClick={() => setInspectorTab('memory')} title="Memory">
              {IC.brain}<span>Memory</span>
            </button>
            <button className={`lab-insp-tab ${inspectorTab === 'config' ? 'active' : ''}`} onClick={() => setInspectorTab('config')} title="Config">
              {IC.settings}<span>Config</span>
            </button>
            <button className={`lab-insp-tab ${inspectorTab === 'collections' ? 'active' : ''}`} onClick={() => setInspectorTab('collections')} title="Links">
              {IC.database}<span>Links</span>
            </button>
          </div>

          <div className="lab-inspector-scroll">
            {/* ── Agents Tab ─── */}
            {inspectorTab === 'agents' && (
              <>
                <div className="lab-section-title">
                  Agents ({agents.length})
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button className="lab-btn-sm" onClick={() => { setShowAgentLibrary(!showAgentLibrary); if (!showAgentLibrary) loadGlobalAgents(); }} title="Import from agents">🤖</button>
                    <button className="lab-btn-sm" onClick={() => setShowAddAgent(!showAddAgent)}>{IC.plus}</button>
                  </div>
                </div>

                {showAgentLibrary && (
                  <div className="lab-agent-library">
                    <div className="lab-library-title">Import Agent</div>
                    {globalAgents.length === 0 && (
                      <div className="lab-empty" style={{ fontSize: '0.72rem' }}>No agents available. Create them in the Agents tab.</div>
                    )}
                    {globalAgents.map(a => (
                      <div key={a.id} className="lab-library-item" onClick={() => { handleImportGlobalAgentToLab(a); setShowAgentLibrary(false); }}>
                        <span className="lab-library-name">🤖 {a.name}</span>
                        <span className="lab-library-role">{a.description || 'No description'}</span>
                      </div>
                    ))}
                    <button className="lab-btn-ghost" style={{ width: '100%', marginTop: 4, fontSize: '0.68rem' }}
                      onClick={() => setShowAgentLibrary(false)}>Close</button>
                  </div>
                )}

                {showAddAgent && (
                  <div className="lab-agent-form">
                    <input className="lab-input-sm" placeholder="Agent name" value={newAgent.name}
                      onChange={e => setNewAgent({...newAgent, name: e.target.value})} autoFocus />
                    <input className="lab-input-sm" placeholder="Role (e.g. Researcher)" value={newAgent.role}
                      onChange={e => setNewAgent({...newAgent, role: e.target.value})} />
                    <textarea className="lab-input-sm" placeholder="System prompt" value={newAgent.system_prompt}
                      onChange={e => setNewAgent({...newAgent, system_prompt: e.target.value})} rows={3} style={{ resize: 'vertical' }} />
                    <select className="lab-select" value={newAgent.prompt_template_id}
                      onChange={e => {
                        const tpl = promptTemplates.find(t => t.id === e.target.value);
                        setNewAgent({...newAgent, prompt_template_id: e.target.value, ...(tpl ? { system_prompt: tpl.content } : {})});
                      }}>
                      <option value="">No prompt template</option>
                      {promptTemplates.filter(t => t.target === 'agent').map(t => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </select>
                    <select className="lab-select" value={newAgent.model_id}
                      onChange={e => setNewAgent({...newAgent, model_id: e.target.value})}>
                      <option value="">Select model...</option>
                      {allModels.filter(m => m.is_available).map(m => (
                        <option key={m.id} value={m.id}>{m.model_identifier}</option>
                      ))}
                    </select>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>
                      <input type="checkbox" checked={newAgent.share_memory}
                        onChange={e => setNewAgent({...newAgent, share_memory: e.target.checked})} /> Share memory across all labs
                    </label>
                    <div className="lab-config-group">
                      <label className="lab-form-label">Tools</label>
                      {toolSets.length > 0 && (
                        <select className="lab-select" value={newAgent.tool_set_id}
                          onChange={e => setNewAgent({...newAgent, tool_set_id: e.target.value})}
                          style={{ marginBottom: 4 }}>
                          <option value="">Manual selection</option>
                          {toolSets.map(ts => (
                            <option key={ts.id} value={ts.id}>{ts.name} ({ts.tools?.length || 0} tools)</option>
                          ))}
                        </select>
                      )}
                      {newAgent.tool_set_id ? (
                        <div className="lab-toolset-inherited">
                          {(toolSets.find(ts => ts.id === newAgent.tool_set_id)?.tools || []).map(t => (
                            <span key={t} className="lab-toolset-tag">{t}</span>
                          ))}
                        </div>
                      ) : (
                        <div className="lab-tools-grid">
                          {builtinTools.map(t => t.expandable ? (
                            <PipelineToolGroup key={t.name} tools={newAgent.tools} pipelines={availablePipelines}
                              onChange={tools => setNewAgent({...newAgent, tools})} />
                          ) : t.subTools ? (
                            <SubToolGroup key={t.name} toolDef={t} tools={newAgent.tools}
                              onChange={tools => setNewAgent({...newAgent, tools})} />
                          ) : (
                            <label key={t.name} className="lab-tool-checkbox">
                              <input type="checkbox" checked={newAgent.tools.includes(t.name)}
                                onChange={e => {
                                  const tools = e.target.checked
                                    ? [...newAgent.tools, t.name]
                                    : newAgent.tools.filter(n => n !== t.name);
                                  setNewAgent({...newAgent, tools});
                                }} />
                              <span className="lab-tool-info">
                                <span className="lab-tool-name">{t.name}<SensitivePill tool={t} /></span>
                                <span className="lab-tool-desc">{t.description}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="lab-config-group">
                      <label className="lab-form-label">Callable Agents</label>
                      <div className="lab-tools-grid">
                        {agents.filter(a => a.name !== newAgent.name).map(a => (
                          <label key={a.id} className="lab-tool-checkbox">
                            <input type="checkbox" checked={newAgent.callable_agents.includes(a.name)}
                              onChange={e => {
                                const callable_agents = e.target.checked
                                  ? [...newAgent.callable_agents, a.name]
                                  : newAgent.callable_agents.filter(n => n !== a.name);
                                setNewAgent({...newAgent, callable_agents});
                              }} />
                            <span className="lab-tool-info">
                              <span className="lab-tool-name">{a.name}</span>
                              {a.role && <span className="lab-tool-desc">{a.role}</span>}
                            </span>
                          </label>
                        ))}
                        {agents.filter(a => a.name !== newAgent.name).length === 0 && (
                          <span style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.3)' }}>No other agents yet</span>
                        )}
                      </div>
                    </div>
                    <div className="lab-config-group">
                      <label className="lab-form-label">CRON Schedule</label>
                      <input className="lab-input-sm" placeholder="Cron expression (e.g. 0 */6 * * *)" value={newAgent.cron_expression}
                        onChange={e => setNewAgent({...newAgent, cron_expression: e.target.value})} />
                      <input className="lab-input-sm" placeholder="Cron instruction (task to inject)" value={newAgent.cron_instruction}
                        onChange={e => setNewAgent({...newAgent, cron_instruction: e.target.value})} style={{ marginTop: 4 }} />
                    </div>
                    <div className="lab-create-actions">
                      <button className="lab-btn-primary" onClick={handleAddAgent}>Add Agent</button>
                      <button className="lab-btn-ghost" onClick={() => setShowAddAgent(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                {agents.map(agent => (
                  <div
                    key={agent.id}
                    className={`lab-agent-card${selectedAgentId === agent.id ? ' lab-agent-card--selected-feed' : ''}`}
                    onClick={(e) => {
                      // Avoid hijacking clicks on inner buttons / inputs / edit form
                      if (editingAgent?.id === agent.id) return;
                      const tag = (e.target.tagName || '').toLowerCase();
                      if (tag === 'button' || tag === 'input' || tag === 'select' || tag === 'textarea' || e.target.closest('button')) return;
                      setSelectedAgentId(prev => prev === agent.id ? null : agent.id);
                      setAgentMemoryTakeover(false);
                    }}
                    style={{ cursor: editingAgent?.id === agent.id ? 'default' : 'pointer' }}
                  >
                    {editingAgent?.id === agent.id ? (
                      <AgentEditForm
                        agent={editingAgent}
                        allModels={allModels}
                        toolSets={toolSets}
                        promptTemplates={promptTemplates}
                        agents={agents}
                        availablePipelines={availablePipelines}
                        builtinTools={builtinTools}
                        onSave={(data) => handleUpdateAgent(agent.id, data)}
                        onCancel={() => setEditingAgent(null)}
                        onOpenPromptEditor={setPromptEditor}
                      />
                    ) : (
                      <>
                        <div className="lab-agent-header">
                          <div className="lab-agent-info">
                            <span className="lab-agent-name">{IC.bot} {agent.name}</span>
                            {agent.library_agent_id && <span style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.3)', marginLeft: 4 }}>📚</span>}
                            {agent.role && <span className="lab-agent-role">{agent.role}</span>}
                          </div>
                          <div className="lab-agent-actions">
                            <button className="lab-btn-xs" onClick={() => handleCreateLibraryAgentFromLabAgent(agent)} title="Save to Agents">💾</button>
                            <button className="lab-btn-xs" onClick={() => setEditingAgent({...agent})} title="Edit">{IC.edit}</button>
                            <button className="lab-btn-xs lab-btn-danger-xs" onClick={() => handleDeleteAgent(agent.id)} title="Delete">{IC.trash}</button>
                          </div>
                        </div>
                        <div className="lab-agent-details">
                          <div className="lab-agent-detail">
                            <span className="lab-detail-label">Model</span>
                            <span className="lab-detail-value">{agent.model_id ? getModelName(agent.model_id) : 'Default'}</span>
                          </div>
                          <div className="lab-agent-detail">
                            <span className="lab-detail-label">Temp</span>
                            <span className="lab-detail-value">{agent.temperature}</span>
                          </div>
                          {agent.system_prompt && (
                            <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                              <span className="lab-detail-label">Prompt</span>
                              <span className="lab-detail-value lab-prompt-preview">{agent.system_prompt}</span>
                            </div>
                          )}
                          <div className="lab-agent-detail">
                            <span className="lab-detail-label">Active</span>
                            <span className="lab-detail-value" style={{ color: agent.is_active ? '#22c55e' : '#ef4444' }}>
                              {agent.is_active ? 'Yes' : 'No'}
                            </span>
                          </div>
                          <div className="lab-agent-detail">
                            <span className="lab-detail-label">Memory</span>
                            <span className="lab-detail-value" style={{ color: agent.share_memory ? '#a855f7' : 'rgba(255,255,255,0.4)' }}>
                              {agent.share_memory ? 'Shared' : 'Isolated'}
                            </span>
                          </div>
                          {agent.tools && agent.tools.length > 0 && (
                            <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                              <span className="lab-detail-label">Tools</span>
                              <span className="lab-detail-value">
                                {agent.tool_set_id
                                  ? `📦 ${toolSets.find(ts => ts.id === agent.tool_set_id)?.name || 'Unknown set'}`
                                  : agent.tools.join(', ')
                                }
                              </span>
                            </div>
                          )}
                          {!agent.tools?.length && agent.tool_set_id && (
                            <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                              <span className="lab-detail-label">Tools</span>
                              <span className="lab-detail-value">📦 {toolSets.find(ts => ts.id === agent.tool_set_id)?.name || 'Unknown set'}</span>
                            </div>
                          )}
                          {agent.callable_agents?.length > 0 && (
                            <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                              <span className="lab-detail-label">Callable</span>
                              <span className="lab-detail-value">{agent.callable_agents.join(', ')}</span>
                            </div>
                          )}
                          {agent.cron_expression && (
                            <div className="lab-agent-detail" style={{ gridColumn: '1 / -1' }}>
                              <span className="lab-detail-label">CRON</span>
                              <span className="lab-detail-value" style={{ color: '#a855f7' }}>
                                {agent.cron_expression}{agent.cron_instruction ? ` → ${agent.cron_instruction}` : ''}
                              </span>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}
                {agents.length === 0 && !showAddAgent && (
                  <div className="lab-empty" style={{ fontSize: '0.75rem' }}>No agents. Add one to get started.</div>
                )}
              </>
            )}

            {/* ── Resources Tab ─── */}
            {inspectorTab === 'resources' && (
              <>
                <div className="lab-section-title">
                  Resources ({resources.length})
                  <label className="lab-btn-sm" style={{ cursor: 'pointer', position: 'relative' }}>
                    {uploadingResource ? IC.loader : '📎'}
                    <input
                      type="file"
                      style={{ display: 'none' }}
                      onChange={e => { if (e.target.files[0]) handleUploadResource(e.target.files[0]); e.target.value = ''; }}
                      disabled={uploadingResource}
                    />
                  </label>
                </div>
                {resources.length === 0 && (
                  <div className="lab-empty" style={{ fontSize: '0.75rem' }}>
                    No resources. Upload files (code, images, PDFs) to provide context to agents.
                  </div>
                )}
                {resources.map(res => (
                  <div key={res.id} className="lab-resource-card" style={{ cursor: 'pointer' }} onClick={() => openResourceFile(res)}>
                    <div className="lab-resource-header">
                      <span className="lab-resource-icon">
                        {res.resource_type === 'image' ? '🖼️' : res.resource_type === 'pdf' ? '📄' : res.resource_type === 'code' ? '💻' : '📁'}
                      </span>
                      <div className="lab-resource-info">
                        <span className="lab-resource-name">{res.original_name}</span>
                        <span className="lab-resource-meta">
                          {res.resource_type} · {res.size_bytes > 1024 ? `${(res.size_bytes / 1024).toFixed(1)} KB` : `${res.size_bytes} B`}
                        </span>
                      </div>
                      <button className="lab-btn-xs" onClick={(e) => { e.stopPropagation(); downloadFile(getLabResourceUrl(activeLab?.id, res.id), res.original_name); }} title="Download">⬇</button>
                      <button className="lab-btn-xs lab-btn-danger-xs" onClick={(e) => { e.stopPropagation(); handleDeleteResource(res.id); }} title="Delete">{IC.trash}</button>
                    </div>
                    {res.resource_type === 'image' && (
                      <div className="lab-resource-preview">
                        <AuthImage
                          src={getLabResourceUrl(activeLab?.id, res.id)}
                          alt={res.original_name}
                          style={{ maxWidth: '100%', maxHeight: 150, borderRadius: 4, marginTop: 4 }}
                        />
                      </div>
                    )}
                  </div>
                ))}

                {/* ── Workspace Files ─── */}
                <div className="lab-section-title" style={{ marginTop: 16 }}>
                  Workspace Files ({outputFiles.length})
                </div>
                {outputFiles.length === 0 && (
                  <div className="lab-empty" style={{ fontSize: '0.75rem' }}>
                    No files yet. Files are created by agents via tools.
                  </div>
                )}
                {outputFiles.map(f => (
                  <div key={f.path} className="lab-resource-card lab-output-card" style={{ cursor: 'pointer' }} onClick={() => openOutputFile(f.path)}>
                    <div className="lab-resource-header">
                      <span className="lab-resource-icon">
                        {f.content_type?.startsWith('image/') ? '🖼️' : f.content_type?.startsWith('audio/') ? '🎵' : f.content_type?.startsWith('video/') ? '🎬' : f.name?.endsWith('.py') ? '🐍' : f.name?.endsWith('.json') ? '📋' : f.name?.endsWith('.md') ? '📝' : '📄'}
                      </span>
                      <div className="lab-resource-info">
                        <span className="lab-resource-name">{f.path}</span>
                        <span className="lab-resource-meta">
                          {f.size_bytes > 1024 ? `${(f.size_bytes / 1024).toFixed(1)} KB` : `${f.size_bytes} B`}
                          {f.modified_at ? ` · ${new Date(f.modified_at).toLocaleDateString()} ${new Date(f.modified_at).toLocaleTimeString()}` : ''}
                        </span>
                      </div>
                      <button
                        className="lab-btn-xs"
                        title="Download"
                        onClick={e => { e.stopPropagation(); downloadFile(getLabOutputFileUrl(activeLab?.id, f.path), f.name); }}
                      >⬇</button>
                    </div>
                  </div>
                ))}
              </>
            )}

            {/* ── Memory Tab ─── */}
            {inspectorTab === 'memory' && (
              <>
                {memories.length === 0 && (
                  <div className="lab-empty" style={{ fontSize: '0.75rem' }}>No memories yet. Memories are created during lab execution.</div>
                )}
                {(() => {
                  const labMems = memories.filter(m => m.scope === 'lab');
                  const agentMemMap = {};
                  memories.filter(m => m.scope === 'agent' && m.agent_id).forEach(m => {
                    if (!agentMemMap[m.agent_id]) agentMemMap[m.agent_id] = [];
                    agentMemMap[m.agent_id].push(m);
                  });

                  const handleToggleHidden = async (mem) => {
                    try {
                      const res = await toggleLabMemoryVisibility(activeLab.id, mem.id, !mem.is_hidden);
                      setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, is_hidden: res.data.is_hidden } : m));
                    } catch (e) { console.error('toggle visibility failed', e); }
                  };

                  return (
                    <>
                      {/* Orchestrator Memories */}
                      <div className="lab-mem-section-title" onClick={() => { setMemoryView('lab'); setFileViewer(null); }} style={{ cursor: 'pointer' }}>
                        <span>Orchestrator</span>
                        <span className="lab-mem-count">{labMems.length}</span>
                      </div>
                      <div className="lab-mem-cards">
                        {labMems.map(mem => (
                          <div key={mem.id} className={`lab-mem-chip ${memoryView === 'lab' ? 'active' : ''} ${mem.is_hidden ? 'hidden-mem' : ''}`}
                               onClick={() => { setMemoryView('lab'); setFileViewer(null); }}>
                            <span className="lab-mem-chip-key">{mem.key}</span>
                            <span className="lab-mem-chip-imp">{mem.importance}</span>
                            <button className="lab-mem-vis-btn" title={mem.is_hidden ? 'Show memory' : 'Hide memory'}
                              onClick={e => { e.stopPropagation(); handleToggleHidden(mem); }}>
                              {mem.is_hidden ? '👁️‍🗨️' : '👁️'}
                            </button>
                          </div>
                        ))}
                        {labMems.length === 0 && <div className="lab-empty" style={{ fontSize: '0.68rem', padding: '4px 0' }}>—</div>}
                      </div>

                      {/* Per-Agent Memories */}
                      {agents.filter(a => agentMemMap[a.id]).map(agent => (
                        <div key={agent.id}>
                          <div className="lab-mem-section-title" onClick={() => { setMemoryView(agent.id); setFileViewer(null); }} style={{ cursor: 'pointer' }}>
                            <span>{agent.name}</span>
                            <span className="lab-mem-count">{agentMemMap[agent.id].length}</span>
                          </div>
                          <div className="lab-mem-cards">
                            {agentMemMap[agent.id].map(mem => (
                              <div key={mem.id} className={`lab-mem-chip ${memoryView === agent.id ? 'active' : ''} ${mem.is_hidden ? 'hidden-mem' : ''}`}
                                   onClick={() => { setMemoryView(agent.id); setFileViewer(null); }}>
                                <span className="lab-mem-chip-key">{mem.key}</span>
                                <span className="lab-mem-chip-imp">{mem.importance}</span>
                                <button className="lab-mem-vis-btn" title={mem.is_hidden ? 'Show memory' : 'Hide memory'}
                                  onClick={e => { e.stopPropagation(); handleToggleHidden(mem); }}>
                                  {mem.is_hidden ? '👁️‍🗨️' : '👁️'}
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </>
                  );
                })()}
              </>
            )}

            {/* ── Config Tab ─── */}
            {inspectorTab === 'config' && activeLab && (
              <>
                <div className="lab-section-title">Lab Configuration</div>
                <LabConfigPanel
                  lab={activeLab}
                  allModels={allModels}
                  toolSets={toolSets}
                  promptTemplates={promptTemplates}
                  cronJobs={cronJobs}
                  availablePipelines={availablePipelines}
                  builtinTools={builtinTools}
                  onSave={handleUpdateLabConfig}
                  onOpenPromptEditor={setPromptEditor}
                />
              </>
            )}

            {/* ── Collections (RAG) Tab ─── */}
            {inspectorTab === 'collections' && activeLab && (
              <>
                <div className="lab-sidebar-section" style={{ borderBottom: 'none' }}>
                  <div className="lab-sidebar-section-header" onClick={() => setInspectorLinksSection(s => ({ ...s, rag: !s.rag }))} style={{ padding: '8px 4px 8px 2px', borderRadius: 6 }}>
                    <span className={`lab-sidebar-chevron ${inspectorLinksSection.rag ? 'open' : ''}`}>{IC.chevronRight}</span>
                    <h3>RAG Collections</h3>
                  </div>
                  {inspectorLinksSection.rag && (
                    <div className="lab-sidebar-list" style={{ padding: '0 0 6px' }}>
                      {ragCollections.length === 0 ? (
                        <div className="lab-empty" style={{ fontSize: '0.75rem' }}>
                          No RAG collections exist yet. Create collections in the RAG page first.
                        </div>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {ragCollections.map(col => {
                            const access = labRagAccess.find(a => a.collection_id === col.id);
                            const linked = !!access;
                            return (
                              <div key={col.id} className="lab-resource-card" style={{ padding: '8px 10px', marginBottom: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 600, fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: 6 }}>
                                      {col.display_name || col.name}
                                      {col.rag_mode === 'lightrag' && (
                                        <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: 3, background: 'rgba(139,92,246,0.18)', color: '#a78bfa', fontWeight: 600 }}>LightRAG</span>
                                      )}
                                    </div>
                                    <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>
                                      {col.document_count || 0} docs · {col.chunk_count || 0} chunks
                                    </div>
                                  </div>
                                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                                    <input type="checkbox" checked={linked} onChange={() => handleToggleRagAccess(col.id)} />
                                    Link
                                  </label>
                                </div>
                                {linked && (
                                  <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)' }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                      <input type="checkbox" checked={access.can_read !== false} onChange={e => handleUpdateRagFlag(col.id, 'can_read', e.target.checked)} />
                                      Read
                                    </label>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                      <input type="checkbox" checked={!!access.can_write} onChange={e => handleUpdateRagFlag(col.id, 'can_write', e.target.checked)} />
                                      Write
                                    </label>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      <div style={{ marginTop: 10, fontSize: '0.7rem', color: 'rgba(255,255,255,0.3)' }}>
                        Linked collections provide <code>rag_search</code> and <code>rag_list_collections</code> tools to agents.
                      </div>
                    </div>
                  )}
                </div>

                <div className="lab-sidebar-section" style={{ borderBottom: 'none', marginTop: 8 }}>
                  <div className="lab-sidebar-section-header" onClick={() => setInspectorLinksSection(s => ({ ...s, wallets: !s.wallets }))} style={{ padding: '8px 4px 8px 2px', borderRadius: 6 }}>
                    <span className={`lab-sidebar-chevron ${inspectorLinksSection.wallets ? 'open' : ''}`}>{IC.chevronRight}</span>
                    <h3>Wallet Collections</h3>
                  </div>
                  {inspectorLinksSection.wallets && (
                    <div className="lab-sidebar-list" style={{ padding: '0 0 6px' }}>
                      {walletCollections.length === 0 ? (
                        <div className="lab-empty" style={{ fontSize: '0.75rem' }}>
                          No tracked wallets are available yet. Add wallets in the Web3 page first.
                        </div>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {walletCollections.map(wallet => {
                            const access = labWeb3Access.find(a => a.wallet_id === wallet.wallet_id);
                            const linked = !!access;
                            return (
                              <div key={wallet.wallet_id} className="lab-resource-card" style={{ padding: '8px 10px', marginBottom: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 600, fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                      {wallet.label || wallet.address}
                                    </div>
                                    <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)', marginTop: 2, fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                      {wallet.address}
                                    </div>
                                  </div>
                                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                                    <input type="checkbox" checked={linked} onChange={() => handleToggleWalletAccess(wallet.wallet_id)} />
                                    Link
                                  </label>
                                </div>
                                {linked && (
                                  <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)' }}>
                                    <span>Read-only</span>
                                    <span><code>web3_portfolio</code></span>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      <div style={{ marginTop: 10, fontSize: '0.7rem', color: 'rgba(255,255,255,0.3)' }}>
                        Linked wallets provide the read-only <code>web3_portfolio</code> tool to agents.
                      </div>
                    </div>
                  )}
                </div>

                <div className="lab-sidebar-section" style={{ borderBottom: 'none', marginTop: 8 }}>
                  <div className="lab-sidebar-section-header" onClick={() => setInspectorLinksSection(s => ({ ...s, servers: !s.servers }))} style={{ padding: '8px 4px 8px 2px', borderRadius: 6 }}>
                    <span className={`lab-sidebar-chevron ${inspectorLinksSection.servers ? 'open' : ''}`}>{IC.chevronRight}</span>
                    <h3>Servers</h3>
                  </div>
                  {inspectorLinksSection.servers && (
                    <div className="lab-sidebar-list" style={{ padding: '0 0 6px' }}>
                      {serverCandidates.length === 0 ? (
                        <div className="lab-empty" style={{ fontSize: '0.75rem' }}>
                          No servers available. Add servers in the Servers page first.
                        </div>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {serverCandidates.map(srv => {
                            const access = labServerAccess.find(a => a.server_id === srv.server_id);
                            const linked = !!access;
                            return (
                              <div key={srv.server_id} className="lab-resource-card" style={{ padding: '8px 10px', marginBottom: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 600, fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: 6 }}>
                                      {srv.name}
                                      <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: 3, background: srv.status === 'online' ? 'rgba(34,197,94,0.18)' : 'rgba(239,68,68,0.18)', color: srv.status === 'online' ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{srv.status}</span>
                                    </div>
                                    <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)', marginTop: 2, fontFamily: 'monospace' }}>
                                      {srv.host}
                                    </div>
                                  </div>
                                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                                    <input type="checkbox" checked={linked} onChange={() => handleToggleServerAccess(srv.server_id)} />
                                    Link
                                  </label>
                                </div>
                                {linked && (
                                  <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)' }}>
                                    <span><code>control_server</code></span>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      <div style={{ marginTop: 10, fontSize: '0.7rem', color: 'rgba(255,255,255,0.3)' }}>
                        Linked servers provide the <code>control_server</code> tool to agents.
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

/* ── Agent Edit Form ──────────────────────────── */
/* ── Hermes container panel ──────────────────────
   Shown in the agent edit forms when backend === 'hermes'. Drives the
   per-agent Hermes container (activate pops it, deactivate stops it; the
   ~/.hermes memory volume always survives). Keyed by the library agent id —
   lab agents instantiated from a template share that template's container. */
export function HermesPanel({ agentKey }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!agentKey) return;
    try {
      const r = await hermesStatus(agentKey);
      setStatus(r.data);
      setError('');
    } catch (e) {
      setStatus(null);
      setError(e?.response?.data?.detail || 'Status unavailable');
    }
  }, [agentKey]);

  useEffect(() => { refresh(); }, [refresh]);

  const act = async (fn) => {
    setBusy(true);
    setError('');
    try {
      await fn(agentKey);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Request failed');
    }
    setBusy(false);
    refresh();
  };

  const dot = status?.running
    ? (status?.healthy ? '#34d399' : '#fbbf24')
    : 'rgba(255,255,255,0.25)';
  const label = !status
    ? '…'
    : !status.image_configured
      ? 'Hermes image not configured (set HERMES_IMAGE)'
      : status.running
        ? (status.healthy ? 'Running · healthy' : 'Running · not responding')
        : 'Stopped (starts automatically on first task)';

  return (
    <div className="lab-config-group" style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: 8 }}>
      <label className="lab-form-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot, display: 'inline-block' }} />
        Hermes container
      </label>
      <div style={{ fontSize: '0.68rem', color: 'rgba(255,255,255,0.5)', marginBottom: 6 }}>{label}</div>
      {error && <div style={{ fontSize: '0.68rem', color: '#f87171', marginBottom: 6 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="lab-btn-ghost" style={{ fontSize: '0.68rem' }} disabled={busy || !status?.image_configured}
          onClick={() => act(hermesActivate)}>{busy ? '…' : '▶ Activate'}</button>
        <button className="lab-btn-ghost" style={{ fontSize: '0.68rem' }} disabled={busy || !status?.running}
          onClick={() => act(hermesDeactivate)}>■ Deactivate</button>
        <button className="lab-btn-ghost" style={{ fontSize: '0.68rem' }} disabled={busy}
          onClick={refresh}>↻</button>
      </div>
    </div>
  );
}

export function AgentEditForm({
  agent,
  allModels,
  toolSets,
  promptTemplates = [],
  agents = [],
  availablePipelines = [],
  builtinTools = [],
  onSave,
  onCancel,
  onOpenPromptEditor,
  showShareMemory = true,
  showAntiLoop = false,
}) {
  const [form, setForm] = useState({
    name: agent.name,
    role: agent.role,
    system_prompt: agent.system_prompt,
    prompt_template_id: agent.prompt_template_id || '',
    model_id: agent.model_id || '',
    backend: agent.backend || 'native',
    temperature: agent.temperature,
    max_tokens: agent.max_tokens,
    is_active: agent.is_active,
    share_memory: agent.share_memory || false,
    anti_loop_enabled: agent.anti_loop_enabled || false,
    tools: agent.tools || [],
    tool_set_id: agent.tool_set_id || '',
    tool_set_ids: agent.tool_set_ids || [],
    callable_agents: agent.callable_agents || [],
    cron_expression: agent.cron_expression || '',
    cron_instruction: agent.cron_instruction || '',
  });

  useEffect(() => {
    setForm(prev => ({ ...prev, system_prompt: agent.system_prompt }));
  }, [agent.system_prompt]);

  return (
    <div className="lab-agent-form">
      <input className="lab-input-sm" placeholder="Name" value={form.name}
        onChange={e => setForm({...form, name: e.target.value})} />
      <input className="lab-input-sm" placeholder="Role" value={form.role}
        onChange={e => setForm({...form, role: e.target.value})} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <label className="lab-form-label" style={{ margin: 0 }}>System Prompt</label>
        {onOpenPromptEditor && (
          <button className="lab-btn-ghost" style={{ fontSize: '0.65rem', padding: '2px 6px' }}
            onClick={() => onOpenPromptEditor({ type: 'agent', agentId: agent.id, value: form.system_prompt, dirty: false })}>
            ⛶ Full View
          </button>
        )}
      </div>
      <textarea className="lab-input-sm" placeholder="System prompt" value={form.system_prompt}
        onChange={e => setForm({...form, system_prompt: e.target.value})} rows={3} style={{ resize: 'vertical' }} />
      {promptTemplates.filter(pt => pt.target === 'agent').length > 0 && (
        <select className="lab-select" value={form.prompt_template_id}
          onChange={e => {
            const val = e.target.value;
            setForm(prev => ({ ...prev, prompt_template_id: val }));
            if (val) {
              const pt = promptTemplates.find(p => p.id === val);
              if (pt) setForm(prev => ({ ...prev, system_prompt: pt.content, prompt_template_id: val }));
            }
          }}>
          <option value="">No prompt template</option>
          {promptTemplates.filter(pt => pt.target === 'agent').map(pt => (
            <option key={pt.id} value={pt.id}>{pt.name}</option>
          ))}
        </select>
      )}
      <label className="lab-form-label">Backend</label>
      <select className="lab-select" value={form.backend || 'native'}
        onChange={e => setForm({...form, backend: e.target.value})}>
        <option value="native">Native (Bob Lab loop)</option>
        <option value="hermes">Hermes (external agent)</option>
      </select>
      {(form.backend || 'native') === 'hermes' && (
        <HermesPanel agentKey={agent.library_agent_id || agent.id} />
      )}
      <label className="lab-form-label">
        {(form.backend || 'native') === 'hermes' ? 'Model Hermes uses' : 'Model'}
      </label>
      <select className="lab-select" value={form.model_id}
        onChange={e => setForm({...form, model_id: e.target.value})}>
        <option value="">Default model</option>
        {allModels.filter(m => m.is_available).map(m => (
          <option key={m.id} value={m.id}>{m.model_identifier}</option>
        ))}
      </select>
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <label className="lab-form-label">Temperature</label>
          <input className="lab-input-sm" type="number" step="0.1" min="0" max="2" value={form.temperature}
            onChange={e => setForm({...form, temperature: parseFloat(e.target.value) || 0})} />
        </div>
        <div style={{ flex: 1 }}>
          <label className="lab-form-label">Max Tokens</label>
          <input className="lab-input-sm" type="number" value={form.max_tokens}
            onChange={e => setForm({...form, max_tokens: parseInt(e.target.value) || 4096})} />
        </div>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>
        <input type="checkbox" checked={form.is_active}
          onChange={e => setForm({...form, is_active: e.target.checked})} /> Active
      </label>
      {showShareMemory && (
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>
          <input type="checkbox" checked={form.share_memory}
            onChange={e => setForm({...form, share_memory: e.target.checked})} /> Share memory across all labs
        </label>
      )}
      {showAntiLoop && (
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>
          <input type="checkbox" checked={!!form.anti_loop_enabled}
            onChange={e => setForm({ ...form, anti_loop_enabled: e.target.checked })} /> Anti Loop
        </label>
      )}
      {(form.backend || 'native') === 'hermes' && (
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.45)' }}>
          Hermes runs its own tools inside its container — Bob Lab tools and callable agents don't apply.
        </div>
      )}
      {(form.backend || 'native') !== 'hermes' && (<>
      <div className="lab-config-group">
        <label className="lab-form-label">Tools</label>
        {toolSets.length > 0 && (
          <select className="lab-select" value=""
            onChange={e => {
              const tsId = e.target.value;
              if (tsId && !form.tool_set_ids.includes(tsId)) {
                setForm({...form, tool_set_ids: [...form.tool_set_ids, tsId]});
              }
            }}
            style={{ marginBottom: 4 }}>
            <option value="">+ Add tool set…</option>
            {toolSets.filter(ts => !form.tool_set_ids.includes(ts.id)).map(ts => (
              <option key={ts.id} value={ts.id}>{ts.name} ({ts.tools?.length || 0} tools)</option>
            ))}
          </select>
        )}
        {form.tool_set_ids.length > 0 && (
          <div className="lab-toolset-inherited">
            {form.tool_set_ids.map(tsId => {
              const ts = toolSets.find(s => s.id === tsId);
              if (!ts) return null;
              return (
                <span key={tsId} className="lab-toolset-tag-big">
                  {ts.name}
                  <button className="lab-toolset-tag-delete" onClick={() => {
                    setForm({...form, tool_set_ids: form.tool_set_ids.filter(id => id !== tsId)});
                  }}>×</button>
                </span>
              );
            })}
            {(() => {
              const tsTools = new Set();
              form.tool_set_ids.forEach(tsId => {
                (toolSets.find(s => s.id === tsId)?.tools || []).forEach(t => tsTools.add(t));
              });
              return [...tsTools].sort().map(t => (
                <span key={t} className="lab-toolset-tag">{t}</span>
              ));
            })()}
          </div>
        )}
        <div className="lab-tools-grid">
          {builtinTools.map(t => {
            if (t.expandable) {
              const fromToolSet = form.tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith('media_pipeline:'))
              );
              return <PipelineToolGroup key={t.name} tools={form.tools} pipelines={availablePipelines}
                disabled={fromToolSet} onChange={tools => setForm({...form, tools})} />;
            }
            if (t.subTools) {
              const fromToolSet = form.tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith(t.name + ':'))
              );
              return <SubToolGroup key={t.name} toolDef={t} tools={form.tools}
                disabled={fromToolSet} onChange={tools => setForm({...form, tools})} />;
            }
            const fromToolSet = form.tool_set_ids.some(tsId =>
              (toolSets.find(s => s.id === tsId)?.tools || []).includes(t.name)
            );
            return (
              <label key={t.name} className="lab-tool-checkbox">
                <input type="checkbox"
                  checked={form.tools.includes(t.name) || fromToolSet}
                  disabled={fromToolSet}
                  onChange={e => {
                    const tools = e.target.checked
                      ? [...form.tools, t.name]
                      : form.tools.filter(n => n !== t.name);
                    setForm({...form, tools});
                  }} />
                <span className="lab-tool-info">
                  <span className="lab-tool-name">{t.name}<SensitivePill tool={t} /></span>
                  <span className="lab-tool-desc">{t.description}</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>
      <div className="lab-config-group">
        <label className="lab-form-label">Callable Agents</label>
        <div className="lab-tools-grid">
          {agents.filter(a => a.name !== form.name).map(a => (
            <label key={a.id} className="lab-tool-checkbox">
              <input type="checkbox" checked={form.callable_agents.includes(a.name)}
                onChange={e => {
                  const callable_agents = e.target.checked
                    ? [...form.callable_agents, a.name]
                    : form.callable_agents.filter(n => n !== a.name);
                  setForm({...form, callable_agents});
                }} />
              <span className="lab-tool-info">
                <span className="lab-tool-name">{a.name}</span>
                {a.role && <span className="lab-tool-desc">{a.role}</span>}
              </span>
            </label>
          ))}
          {agents.filter(a => a.name !== form.name).length === 0 && (
            <span style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.3)' }}>No other agents</span>
          )}
        </div>
      </div>
      </>)}
      <div className="lab-config-group">
        <label className="lab-form-label">CRON Schedule</label>
        <input className="lab-input-sm" placeholder="Cron expression (e.g. 0 */6 * * *)" value={form.cron_expression}
          onChange={e => setForm({...form, cron_expression: e.target.value})} />
        <input className="lab-input-sm" placeholder="Cron instruction (task to inject)" value={form.cron_instruction}
          onChange={e => setForm({...form, cron_instruction: e.target.value})} style={{ marginTop: 4 }} />
      </div>
      <div className="lab-create-actions">
        <button className="lab-btn-primary" onClick={() => {
          const data = { ...form };
          if (!data.model_id) delete data.model_id;
          if (!data.tool_set_id) delete data.tool_set_id;
          if (!data.prompt_template_id) data.prompt_template_id = null;
          if (!data.cron_expression) data.cron_expression = null;
          onSave(data);
        }}>Save</button>
        <button className="lab-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/* ── Prompt Template Edit Form ─────────────────── */
/* ── CRON Edit Form ───────────────────────────── */
function CronEditForm({ cron, onSave, onCancel }) {
  const [form, setForm] = useState({
    name: cron.name,
    description: cron.description || '',
    expression: cron.expression || '',
    method: cron.method || 'orchestrator_inject',
    instruction: cron.instruction || '',
  });

  useEffect(() => {
    setForm({
      name: cron.name,
      description: cron.description || '',
      expression: cron.expression || '',
      method: cron.method || 'orchestrator_inject',
      instruction: cron.instruction || '',
    });
  }, [cron.id]);

  return (
    <div className="lab-create-form" style={{ margin: '0 6px 6px' }}>
      <input className="lab-input-sm" placeholder="Name" value={form.name}
        onChange={e => setForm({...form, name: e.target.value})} />
      <input className="lab-input-sm" placeholder="Description (optional)" value={form.description}
        onChange={e => setForm({...form, description: e.target.value})} />
      <input className="lab-input-sm" placeholder="Cron expression (e.g. */5 * * * *)" value={form.expression}
        onChange={e => setForm({...form, expression: e.target.value})} style={{ fontFamily: 'monospace' }} />
      <div className="lab-config-group" style={{ marginTop: 2 }}>
        <label className="lab-form-label">Method</label>
        <select className="lab-select" value={form.method}
          onChange={e => setForm({...form, method: e.target.value})}>
          <option value="orchestrator_inject">Orchestrator Inject</option>
          <option value="direct_cmd_exec">Direct Command Exec</option>
        </select>
      </div>
      <textarea className="lab-textarea-sm"
        placeholder={form.method === 'orchestrator_inject' ? 'Instruction to inject into lab feed...' : 'Command to execute in container...'}
        value={form.instruction}
        onChange={e => setForm({...form, instruction: e.target.value})} rows={4} />
      <div className="lab-create-actions">
        <button className="lab-btn-primary" onClick={() => onSave(form)}>Save</button>
        <button className="lab-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function PromptTemplateEditForm({ template, onSave, onCancel, onOpenFullView }) {
  const [form, setForm] = useState({
    name: template.name,
    description: template.description || '',
    target: template.target || 'agent',
    content: template.content || '',
  });

  useEffect(() => {
    setForm({
      name: template.name,
      description: template.description || '',
      target: template.target || 'agent',
      content: template.content || '',
    });
  }, [template.id, template.content]);

  return (
    <div className="lab-create-form" style={{ margin: '0 6px 6px' }}>
      <input className="lab-input-sm" placeholder="Name" value={form.name}
        onChange={e => setForm({...form, name: e.target.value})} />
      <input className="lab-input-sm" placeholder="Description (optional)" value={form.description}
        onChange={e => setForm({...form, description: e.target.value})} />
      <select className="lab-select-sm" value={form.target}
        onChange={e => setForm({...form, target: e.target.value})}>
        <option value="agent">Agent</option>
        <option value="orchestrator">Orchestrator</option>
      </select>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <label className="lab-form-label" style={{ margin: 0 }}>Content</label>
        {onOpenFullView && (
          <button className="lab-btn-ghost" style={{ fontSize: '0.65rem', padding: '2px 6px' }}
            onClick={() => onOpenFullView(form.content)}>
            ⛶ Full View
          </button>
        )}
      </div>
      <textarea className="lab-textarea-sm" placeholder="Prompt content. Use {{variable}} for placeholders." value={form.content}
        onChange={e => setForm({...form, content: e.target.value})} rows={6} />
      <div className="lab-create-actions">
        <button className="lab-btn-primary" onClick={() => onSave(form)}>Save</button>
        <button className="lab-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/* ── Library Agent Edit Form ──────────────────── */
function LibraryAgentEditForm({ agent, allModels, toolSets, promptTemplates = [], availablePipelines = [], builtinTools = [], onSave, onCancel }) {
  const [form, setForm] = useState({
    name: agent.name,
    role: agent.role || '',
    system_prompt: agent.system_prompt || '',
    prompt_template_id: agent.prompt_template_id || '',
    model_id: agent.model_id || '',
    backend: agent.backend || 'native',
    temperature: agent.temperature ?? 0.7,
    max_tokens: agent.max_tokens ?? 4096,
    tools: agent.tools || [],
    tool_set_ids: agent.tool_set_ids || [],
    share_memory: agent.share_memory || false,
    callable_agents: agent.callable_agents || [],
    cron_expression: agent.cron_expression || '',
    cron_instruction: agent.cron_instruction || '',
  });

  return (
    <div className="lab-create-form" style={{ margin: '0 6px 6px' }}>
      <input className="lab-input-sm" placeholder="Name" value={form.name}
        onChange={e => setForm({...form, name: e.target.value})} />
      <input className="lab-input-sm" placeholder="Role" value={form.role}
        onChange={e => setForm({...form, role: e.target.value})} />
      <label className="lab-form-label">System Prompt</label>
      <textarea className="lab-input-sm" placeholder="System prompt" value={form.system_prompt}
        onChange={e => setForm({...form, system_prompt: e.target.value})} rows={3} style={{ resize: 'vertical' }} />
      {promptTemplates.filter(pt => pt.target === 'agent').length > 0 && (
        <select className="lab-select" value={form.prompt_template_id}
          onChange={e => {
            const val = e.target.value;
            setForm(prev => ({ ...prev, prompt_template_id: val }));
            if (val) {
              const pt = promptTemplates.find(p => p.id === val);
              if (pt) setForm(prev => ({ ...prev, system_prompt: pt.content, prompt_template_id: val }));
            }
          }}>
          <option value="">No prompt template</option>
          {promptTemplates.filter(pt => pt.target === 'agent').map(pt => (
            <option key={pt.id} value={pt.id}>{pt.name}</option>
          ))}
        </select>
      )}
      <label className="lab-form-label">Backend</label>
      <select className="lab-select" value={form.backend || 'native'}
        onChange={e => setForm({...form, backend: e.target.value})}>
        <option value="native">Native (Bob Lab loop)</option>
        <option value="hermes">Hermes (external agent)</option>
      </select>
      {(form.backend || 'native') === 'hermes' && (
        <HermesPanel agentKey={agent.id} />
      )}
      <label className="lab-form-label">
        {(form.backend || 'native') === 'hermes' ? 'Model Hermes uses' : 'Model'}
      </label>
      <select className="lab-select" value={form.model_id}
        onChange={e => setForm({...form, model_id: e.target.value})}>
        <option value="">Default model</option>
        {allModels.filter(m => m.is_available).map(m => (
          <option key={m.id} value={m.id}>{m.model_identifier}</option>
        ))}
      </select>
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <label className="lab-form-label">Temperature</label>
          <input className="lab-input-sm" type="number" step="0.1" min="0" max="2" value={form.temperature}
            onChange={e => setForm({...form, temperature: parseFloat(e.target.value) || 0})} />
        </div>
        <div style={{ flex: 1 }}>
          <label className="lab-form-label">Max Tokens</label>
          <input className="lab-input-sm" type="number" value={form.max_tokens}
            onChange={e => setForm({...form, max_tokens: parseInt(e.target.value) || 4096})} />
        </div>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>
        <input type="checkbox" checked={form.share_memory}
          onChange={e => setForm({...form, share_memory: e.target.checked})} /> Share memory across all labs
      </label>
      {(form.backend || 'native') === 'hermes' && (
        <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.45)' }}>
          Hermes runs its own tools inside its container — Bob Lab tools don't apply.
        </div>
      )}
      {(form.backend || 'native') !== 'hermes' && (<>
      <div className="lab-config-group">
        <label className="lab-form-label">Tools</label>
        {toolSets.length > 0 && (
          <select className="lab-select" value=""
            onChange={e => {
              const tsId = e.target.value;
              if (tsId && !form.tool_set_ids.includes(tsId)) {
                setForm({...form, tool_set_ids: [...form.tool_set_ids, tsId]});
              }
            }}
            style={{ marginBottom: 4 }}>
            <option value="">+ Add tool set…</option>
            {toolSets.filter(ts => !form.tool_set_ids.includes(ts.id)).map(ts => (
              <option key={ts.id} value={ts.id}>{ts.name} ({ts.tools?.length || 0} tools)</option>
            ))}
          </select>
        )}
        {form.tool_set_ids.length > 0 && (
          <div className="lab-toolset-inherited">
            {form.tool_set_ids.map(tsId => {
              const ts = toolSets.find(s => s.id === tsId);
              if (!ts) return null;
              return (
                <span key={tsId} className="lab-toolset-tag-big">
                  {ts.name}
                  <button className="lab-toolset-tag-delete" onClick={() => {
                    setForm({...form, tool_set_ids: form.tool_set_ids.filter(id => id !== tsId)});
                  }}>×</button>
                </span>
              );
            })}
          </div>
        )}
        <div className="lab-tools-grid">
          {builtinTools.map(t => {
            if (t.expandable) {
              const fromToolSet = form.tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith('media_pipeline:'))
              );
              return <PipelineToolGroup key={t.name} tools={form.tools} pipelines={availablePipelines}
                disabled={fromToolSet} onChange={tools => setForm({...form, tools})} />;
            }
            if (t.subTools) {
              const fromToolSet = form.tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith(t.name + ':'))
              );
              return <SubToolGroup key={t.name} toolDef={t} tools={form.tools}
                disabled={fromToolSet} onChange={tools => setForm({...form, tools})} />;
            }
            const fromToolSet = form.tool_set_ids.some(tsId =>
              (toolSets.find(s => s.id === tsId)?.tools || []).includes(t.name)
            );
            return (
              <label key={t.name} className="lab-tool-checkbox">
                <input type="checkbox"
                  checked={form.tools.includes(t.name) || fromToolSet}
                  disabled={fromToolSet}
                  onChange={e => {
                    const tools = e.target.checked
                      ? [...form.tools, t.name]
                      : form.tools.filter(n => n !== t.name);
                    setForm({...form, tools});
                  }} />
                <span className="lab-tool-info">
                  <span className="lab-tool-name">{t.name}</span>
                  <span className="lab-tool-desc">{t.description}</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>
      </>)}
      <div className="lab-config-group">
        <label className="lab-form-label">CRON Schedule</label>
        <input className="lab-input-sm" placeholder="Cron expression (e.g. 0 */6 * * *)" value={form.cron_expression}
          onChange={e => setForm({...form, cron_expression: e.target.value})} />
        <input className="lab-input-sm" placeholder="Cron instruction (task to inject)" value={form.cron_instruction}
          onChange={e => setForm({...form, cron_instruction: e.target.value})} style={{ marginTop: 4 }} />
      </div>
      <div className="lab-create-actions">
        <button className="lab-btn-primary" onClick={() => {
          const data = { ...form };
          if (!data.model_id) delete data.model_id;
          if (!data.prompt_template_id) data.prompt_template_id = null;
          if (!data.cron_expression) data.cron_expression = null;
          onSave(data);
        }}>Save</button>
        <button className="lab-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/* ── Tool Set Edit Form ───────────────────────── */
function ToolSetEditForm({ toolSet, availablePipelines = [], builtinTools = [], onSave, onCancel }) {
  const [form, setForm] = useState({
    name: toolSet.name,
    description: toolSet.description || '',
    tools: toolSet.tools || [],
  });

  return (
    <div className="lab-create-form" style={{ margin: '0 6px 6px' }}>
      <input className="lab-input-sm" placeholder="Name" value={form.name}
        onChange={e => setForm({...form, name: e.target.value})} />
      <input className="lab-input-sm" placeholder="Description (optional)" value={form.description}
        onChange={e => setForm({...form, description: e.target.value})} />
      <div className="lab-config-group" style={{ marginTop: 2 }}>
        <label className="lab-form-label">Tools</label>
        <div className="lab-tools-grid">
          {builtinTools.map(t => t.expandable ? (
            <PipelineToolGroup key={t.name} tools={form.tools} pipelines={availablePipelines}
              onChange={tools => setForm({...form, tools})} />
          ) : t.subTools ? (
            <SubToolGroup key={t.name} toolDef={t} tools={form.tools}
              onChange={tools => setForm({...form, tools})} />
          ) : (
            <label key={t.name} className="lab-tool-checkbox">
              <input type="checkbox" checked={form.tools.includes(t.name)}
                onChange={e => {
                  const tools = e.target.checked
                    ? [...form.tools, t.name]
                    : form.tools.filter(n => n !== t.name);
                  setForm({...form, tools});
                }} />
              <span className="lab-tool-info">
                <span className="lab-tool-name">{t.name}<SensitivePill tool={t} /></span>
                <span className="lab-tool-desc">{t.description}</span>
              </span>
            </label>
          ))}
        </div>
      </div>
      <div className="lab-create-actions">
        <button className="lab-btn-primary" onClick={() => onSave(form)}>Save</button>
        <button className="lab-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/* ── Lab Config Panel ─────────────────────────── */
function LabConfigPanel({ lab, allModels, toolSets, promptTemplates = [], cronJobs = [], availablePipelines = [], builtinTools = [], onSave, onOpenPromptEditor }) {
  const [form, setForm] = useState({
    name: lab.name,
    description: lab.description,
    orchestrator_prompt: lab.orchestrator_prompt,
    orchestrator_prompt_template_id: lab.orchestrator_prompt_template_id || '',
    orchestrator_model_id: lab.orchestrator_model_id || '',
    orchestrator_temperature: lab.orchestrator_temperature,
    orchestrator_max_tokens: lab.orchestrator_max_tokens,
    orchestrator_tools: lab.orchestrator_tools || [],
    orchestrator_tool_set_id: lab.orchestrator_tool_set_id || '',
    orchestrator_tool_set_ids: lab.orchestrator_tool_set_ids || [],
    loop_type: lab.loop_type,
    max_iterations: lab.max_iterations || '',
    max_duration_sec: lab.max_duration_sec || '',
    share_memory_override: lab.share_memory_override == null ? '' : String(lab.share_memory_override),
    auto_sweep_memory: lab.auto_sweep_memory ?? false,
    anti_loop_enabled: lab.anti_loop_enabled ?? false,
    tool_max_calls: lab.tool_max_calls ?? 10,
    tool_timeout_sec: lab.tool_timeout_sec ?? 30,
    tool_max_output_kb: lab.tool_max_output_kb ?? 256,
    tool_container_memory_mb: lab.tool_container_memory_mb ?? 512,
    cron_job_ids: lab.cron_job_ids || [],
  });
  const [dirty, setDirty] = useState(false);
  const [strategies, setStrategies] = useState([]);

  useEffect(() => {
    getLoopStrategies()
      .then(r => setStrategies(r.data?.strategies || []))
      .catch(e => console.error('Failed to load loop strategies', e));
  }, []);

  useEffect(() => {
    setForm({
      name: lab.name,
      description: lab.description,
      orchestrator_prompt: lab.orchestrator_prompt,
      orchestrator_prompt_template_id: lab.orchestrator_prompt_template_id || '',
      orchestrator_model_id: lab.orchestrator_model_id || '',
      orchestrator_temperature: lab.orchestrator_temperature,
      orchestrator_max_tokens: lab.orchestrator_max_tokens,
      orchestrator_tools: lab.orchestrator_tools || [],
      orchestrator_tool_set_id: lab.orchestrator_tool_set_id || '',
      orchestrator_tool_set_ids: lab.orchestrator_tool_set_ids || [],
      loop_type: lab.loop_type,
      max_iterations: lab.max_iterations || '',
      max_duration_sec: lab.max_duration_sec || '',
      share_memory_override: lab.share_memory_override == null ? '' : String(lab.share_memory_override),
      auto_sweep_memory: lab.auto_sweep_memory ?? false,
      anti_loop_enabled: lab.anti_loop_enabled ?? false,
      tool_max_calls: lab.tool_max_calls ?? 10,
      tool_timeout_sec: lab.tool_timeout_sec ?? 30,
      tool_max_output_kb: lab.tool_max_output_kb ?? 256,
      tool_container_memory_mb: lab.tool_container_memory_mb ?? 512,
      cron_job_ids: lab.cron_job_ids || [],
    });
    setDirty(false);
  }, [lab.id, lab.orchestrator_prompt, lab.strategy_prompt_override]);

  function update(key, val) {
    setForm(prev => ({ ...prev, [key]: val }));
    setDirty(true);
  }

  function handleSave() {
    const data = { ...form };
    if (!data.orchestrator_model_id) delete data.orchestrator_model_id;
    if (!data.orchestrator_prompt_template_id) data.orchestrator_prompt_template_id = null;
    if (!data.orchestrator_tool_set_id) data.orchestrator_tool_set_id = null;
    if (data.max_iterations === '') data.max_iterations = null;
    else data.max_iterations = parseInt(data.max_iterations);
    if (data.max_duration_sec === '') data.max_duration_sec = null;
    else data.max_duration_sec = parseInt(data.max_duration_sec);
    if (data.share_memory_override === '') data.share_memory_override = null;
    else data.share_memory_override = data.share_memory_override === 'true';
    data.auto_sweep_memory = !!data.auto_sweep_memory;
    data.anti_loop_enabled = !!data.anti_loop_enabled;
    data.tool_max_calls = parseInt(data.tool_max_calls) || 10;
    data.tool_timeout_sec = parseInt(data.tool_timeout_sec) || 30;
    data.tool_max_output_kb = parseInt(data.tool_max_output_kb) || 256;
    data.tool_container_memory_mb = parseInt(data.tool_container_memory_mb) || 512;
    onSave(data);
    setDirty(false);
  }

  return (
    <div className="lab-config-form">
      <div className="lab-config-group">
        <label className="lab-form-label">Name</label>
        <input className="lab-input-sm" value={form.name} onChange={e => update('name', e.target.value)} />
      </div>
      <div className="lab-config-group">
        <label className="lab-form-label">Description</label>
        <textarea className="lab-input-sm" value={form.description} onChange={e => update('description', e.target.value)} rows={2} style={{ resize: 'vertical' }} />
      </div>
      <div className="lab-config-group">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label className="lab-form-label">Orchestrator Prompt</label>
          {onOpenPromptEditor && (
            <button className="lab-btn-ghost" style={{ fontSize: '0.65rem', padding: '2px 6px' }}
              onClick={() => onOpenPromptEditor({ type: 'orchestrator', value: form.orchestrator_prompt, dirty: false })}>
              ⛶ Full View
            </button>
          )}
        </div>
        <textarea className="lab-input-sm" value={form.orchestrator_prompt} onChange={e => update('orchestrator_prompt', e.target.value)} rows={4} style={{ resize: 'vertical' }} />
      </div>
      {promptTemplates.filter(pt => pt.target === 'orchestrator').length > 0 && (
        <div className="lab-config-group">
          <label className="lab-form-label">Prompt Template</label>
          <select className="lab-select" value={form.orchestrator_prompt_template_id} onChange={e => {
            const val = e.target.value;
            update('orchestrator_prompt_template_id', val);
            if (val) {
              const pt = promptTemplates.find(p => p.id === val);
              if (pt) update('orchestrator_prompt', pt.content);
            }
          }}>
            <option value="">None</option>
            {promptTemplates.filter(pt => pt.target === 'orchestrator').map(pt => (
              <option key={pt.id} value={pt.id}>{pt.name}</option>
            ))}
          </select>
        </div>
      )}
      <div className="lab-config-group">
        <label className="lab-form-label">Orchestrator Model</label>
        <select className="lab-select" value={form.orchestrator_model_id} onChange={e => update('orchestrator_model_id', e.target.value)}>
          <option value="">Default</option>
          {allModels.filter(m => m.is_available).map(m => (
            <option key={m.id} value={m.id}>{m.model_identifier}</option>
          ))}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Temperature</label>
          <input className="lab-input-sm" type="number" step="0.1" min="0" max="2" value={form.orchestrator_temperature}
            onChange={e => update('orchestrator_temperature', parseFloat(e.target.value) || 0)} />
        </div>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Max Tokens</label>
          <input className="lab-input-sm" type="number" value={form.orchestrator_max_tokens}
            onChange={e => update('orchestrator_max_tokens', parseInt(e.target.value) || 4096)} />
        </div>
      </div>
      <div className="lab-config-group">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label className="lab-form-label">Loop Strategy</label>
          {onOpenPromptEditor && (
            <button className="lab-btn-ghost" style={{ fontSize: '0.65rem', padding: '2px 6px' }}
              onClick={async () => {
                try {
                  const res = await getStrategyPrompt(form.loop_type);
                  onOpenPromptEditor({
                    type: 'strategy',
                    value: lab.strategy_prompt_override || res.data.prompt,
                    dirty: false,
                    isOverride: !!lab.strategy_prompt_override,
                  });
                } catch (e) { console.error('Failed to load strategy prompt', e); }
              }}>
              📋 See Prompt
            </button>
          )}
        </div>
        <select className="lab-select" value={form.loop_type} onChange={e => update('loop_type', e.target.value)}>
          {(strategies.length > 0
            ? strategies
            : [{ loop_type: form.loop_type, label: form.loop_type }]
          ).map(s => (
            <option key={s.loop_type} value={s.loop_type} title={s.description || ''}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Max Iterations</label>
          <input className="lab-input-sm" type="number" min="1" placeholder="∞" value={form.max_iterations}
            onChange={e => update('max_iterations', e.target.value)} />
        </div>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Max Duration (s)</label>
          <input className="lab-input-sm" type="number" min="60" placeholder="∞" value={form.max_duration_sec}
            onChange={e => update('max_duration_sec', e.target.value)} />
        </div>
      </div>
      <div className="lab-config-group">
        <label className="lab-form-label">Memory Sharing Override</label>
        <select className="lab-select" value={form.share_memory_override} onChange={e => update('share_memory_override', e.target.value)}>
          <option value="">Use agent defaults</option>
          <option value="true">Force shared (all agents share memory)</option>
          <option value="false">Force isolated (all agents use lab memory only)</option>
        </select>
      </div>
      <div className="lab-config-group">
        <label className="lab-tool-checkbox" style={{ marginTop: 2 }}>
          <input type="checkbox" checked={form.auto_sweep_memory}
            onChange={e => update('auto_sweep_memory', e.target.checked)} />
          <span className="lab-tool-info">
            <span className="lab-tool-name">Auto Sweep Memory</span>
            <span className="lab-tool-desc">Orchestrator periodically reviews &amp; hides outdated agent memories</span>
          </span>
        </label>
      </div>
      <div className="lab-config-group">
        <label className="lab-tool-checkbox" style={{ marginTop: 2 }}>
          <input type="checkbox" checked={form.anti_loop_enabled}
            onChange={e => {
              const next = e.target.checked;
              if (next && !form.anti_loop_enabled) {
                const ok = window.confirm(
                  'Enable Anti-Loop?\n\n' +
                  'When a loop is detected, the lab will be paused, the looping ' +
                  'messages will be removed from memory, and the lab will resume.\n\n' +
                  'The agent may lose information about its recent reasoning, ' +
                  'and in some cases this can cause unexpected behavior.\n\n' +
                  'Continue?'
                );
                if (!ok) return;
              }
              update('anti_loop_enabled', next);
            }} />
          <span className="lab-tool-info">
            <span className="lab-tool-name">Anti Loop</span>
            <span className="lab-tool-desc">Detect repetitive iterations, remove looping messages, then resume the lab automatically</span>
          </span>
        </label>
      </div>

      <div className="lab-section-title" style={{ marginTop: 12 }}>⏰ CRON Jobs</div>
      <div className="lab-config-group">
        {cronJobs.length > 0 && (
          <select className="lab-select" value=""
            onChange={e => {
              const cjId = e.target.value;
              if (cjId && !form.cron_job_ids.includes(cjId)) {
                update('cron_job_ids', [...form.cron_job_ids, cjId]);
              }
            }}
            style={{ marginBottom: 4 }}>
            <option value="">+ Add CRON job…</option>
            {cronJobs.filter(cj => !form.cron_job_ids.includes(cj.id)).map(cj => (
              <option key={cj.id} value={cj.id}>{cj.name} ({cj.expression})</option>
            ))}
          </select>
        )}
        {form.cron_job_ids.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {form.cron_job_ids.map(cjId => {
              const cj = cronJobs.find(c => c.id === cjId);
              if (!cj) return null;
              return (
                <div key={cjId} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(168,85,247,0.1)', borderRadius: 6, padding: '5px 8px', fontSize: '0.72rem' }}>
                  <span style={{ flex: 1 }}>
                    <strong>{cj.name}</strong>
                    <span style={{ opacity: 0.5, marginLeft: 6, fontFamily: 'monospace' }}>{cj.expression}</span>
                    <span style={{ opacity: 0.4, marginLeft: 6 }}>{cj.method === 'orchestrator_inject' ? '🤖 inject' : '⚡ cmd'}</span>
                  </span>
                  <button className="lab-btn-ghost" style={{ padding: '0 4px', fontSize: '0.7rem' }}
                    onClick={() => update('cron_job_ids', form.cron_job_ids.filter(id => id !== cjId))}>×</button>
                </div>
              );
            })}
          </div>
        )}
        {cronJobs.length === 0 && (
          <div style={{ fontSize: '0.68rem', opacity: 0.4 }}>Create CRON jobs in the library first.</div>
        )}
      </div>

      <div className="lab-section-title" style={{ marginTop: 12 }}>Orchestrator Tools</div>
      <div className="lab-config-group">
        {toolSets.length > 0 && (
          <select className="lab-select" value=""
            onChange={e => {
              const tsId = e.target.value;
              if (tsId && !form.orchestrator_tool_set_ids.includes(tsId)) {
                update('orchestrator_tool_set_ids', [...form.orchestrator_tool_set_ids, tsId]);
              }
            }}
            style={{ marginBottom: 4 }}>
            <option value="">+ Add tool set…</option>
            {toolSets.filter(ts => !form.orchestrator_tool_set_ids.includes(ts.id)).map(ts => (
              <option key={ts.id} value={ts.id}>{ts.name} ({ts.tools?.length || 0} tools)</option>
            ))}
          </select>
        )}
        {form.orchestrator_tool_set_ids.length > 0 && (
          <div className="lab-toolset-inherited">
            {form.orchestrator_tool_set_ids.map(tsId => {
              const ts = toolSets.find(s => s.id === tsId);
              if (!ts) return null;
              return (
                <span key={tsId} className="lab-toolset-tag-big">
                  {ts.name}
                  <button className="lab-toolset-tag-delete" onClick={() => {
                    update('orchestrator_tool_set_ids', form.orchestrator_tool_set_ids.filter(id => id !== tsId));
                  }}>×</button>
                </span>
              );
            })}
            {(() => {
              const tsTools = new Set();
              form.orchestrator_tool_set_ids.forEach(tsId => {
                (toolSets.find(s => s.id === tsId)?.tools || []).forEach(t => tsTools.add(t));
              });
              return [...tsTools].sort().map(t => (
                <span key={t} className="lab-toolset-tag">{t}</span>
              ));
            })()}
          </div>
        )}
        <div className="lab-tools-grid">
          {builtinTools.map(t => {
            if (t.expandable) {
              const fromToolSet = form.orchestrator_tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith('media_pipeline:'))
              );
              return <PipelineToolGroup key={t.name} tools={form.orchestrator_tools} pipelines={availablePipelines}
                disabled={fromToolSet} onChange={tools => update('orchestrator_tools', tools)} />;
            }
            if (t.subTools) {
              const fromToolSet = form.orchestrator_tool_set_ids.some(tsId =>
                (toolSets.find(s => s.id === tsId)?.tools || []).some(n => n.startsWith(t.name + ':'))
              );
              return <SubToolGroup key={t.name} toolDef={t} tools={form.orchestrator_tools}
                disabled={fromToolSet} onChange={tools => update('orchestrator_tools', tools)} />;
            }
            const fromToolSet = form.orchestrator_tool_set_ids.some(tsId =>
              (toolSets.find(s => s.id === tsId)?.tools || []).includes(t.name)
            );
            return (
              <label key={t.name} className="lab-tool-checkbox">
                <input type="checkbox"
                  checked={form.orchestrator_tools.includes(t.name) || fromToolSet}
                  disabled={fromToolSet}
                  onChange={e => {
                    const tools = e.target.checked
                      ? [...form.orchestrator_tools, t.name]
                      : form.orchestrator_tools.filter(n => n !== t.name);
                    update('orchestrator_tools', tools);
                  }} />
                <span className="lab-tool-info">
                  <span className="lab-tool-name">{t.name}</span>
                  <span className="lab-tool-desc">{t.description}</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="lab-section-title" style={{ marginTop: 12 }}>Tool Safety Limits</div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Max Calls/Turn</label>
          <input className="lab-input-sm" type="number" min="1" max="100" value={form.tool_max_calls}
            onChange={e => update('tool_max_calls', e.target.value)} />
        </div>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Timeout (s)</label>
          <input className="lab-input-sm" type="number" min="5" max="300" value={form.tool_timeout_sec}
            onChange={e => update('tool_timeout_sec', e.target.value)} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Max Output (KB)</label>
          <input className="lab-input-sm" type="number" min="1" max="10240" value={form.tool_max_output_kb}
            onChange={e => update('tool_max_output_kb', e.target.value)} />
        </div>
        <div className="lab-config-group" style={{ flex: 1 }}>
          <label className="lab-form-label">Container RAM (MB)</label>
          <input className="lab-input-sm" type="number" min="64" max="8192" value={form.tool_container_memory_mb}
            onChange={e => update('tool_container_memory_mb', e.target.value)} />
        </div>
      </div>
      {dirty && (
        <button className="lab-btn-primary" style={{ width: '100%', marginTop: 8 }} onClick={handleSave}>
          Save Changes
        </button>
      )}
    </div>
  );
}
