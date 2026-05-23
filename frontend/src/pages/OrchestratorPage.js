/**
 * Bob Manager —  AI Orchestrator Page
 *
 * ChatGPT-style conversation interface with:
 * - Left panel: conversation list
 * - Center: chat messages with streaming
 * - Right panel: activity feed (collapsible)
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  getConversations,
  createConversation,
  updateConversation,
  deleteConversation,
  getMessages,
  sendMessage,
  getActivity,
  getOrchestratorSettings,
  updateOrchestratorSettings,
  getAIProviders,
  getAIProviderTypes,
  createAIProvider,
  deleteAIProvider,
  testAIProvider,
  getLiveModels,
  getAIModels,
  getUniqueModels,
  syncAllModels,
  getLlmEvents,
  getLlmEventStats,
  getLlmEventDetail,
  getAIAgents,
  getToolSets,
  getBuiltinTools,
} from '../services/api';
import wsService from '../services/websocket';
import LabsView from '../components/labs/LabsView';
import AgentsView from '../components/agents/AgentsView';
import OutreachView from '../components/outreach/OutreachView';

/* ── Markdown-lite renderer ─────────────────────── */
function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre class="orch-code"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="orch-inline-code">$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/\n/g, '<br/>');
  return html;
}

/* ── Icons ──────────────────────────────────────── */
const IC = {
  plus: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
  ),
  send: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
  ),
  trash: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
  ),
  activity: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
  ),
  bot: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><line x1="12" y1="7" x2="12" y2="11"/><circle cx="8" cy="16" r="1"/><circle cx="16" cy="16" r="1"/></svg>
  ),
  user: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
  ),
  chevronRight: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="9 18 15 12 9 6"/></svg>
  ),
  chevronLeft: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="15 18 9 12 15 6"/></svg>
  ),
  loader: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="orch-spinner"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
  ),
  settings: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
  ),
  server: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
  ),
  check: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
  ),
  refresh: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
  ),
  chip: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
  ),
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

/* ── Sub-tool selection for conversations (trading, defi_data, etc.) ── */
function OrchSubToolGroup({ toolDef, tools, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const prefix = toolDef.name + ':';
  const subEntries = tools.filter(t => t.startsWith(prefix));
  const selectedSubs = subEntries.map(t => t.split(':')[1]);
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
      <label className="orch-tool-toggle" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" ref={checkboxRef} checked={someSelected} onChange={toggleAll} />
        <span className="orch-tool-toggle-info" style={{ flex: 1 }}>
          <span className="orch-tool-toggle-name">{toolDef.name}<SensitiveToolTag tool={toolDef} /></span>
          <span className="orch-tool-toggle-desc">{toolDef.description}</span>
        </span>
        <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
          style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 4px' }}>
          {expanded ? '▾' : '▸'} {selectedSubs.length}/{toolDef.subTools.length}
        </button>
      </label>
      {expanded && (
        <div style={{ marginLeft: 22, marginTop: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          {toolDef.subTools.map(s => (
            <label key={s.name} className="orch-tool-toggle" style={{ fontSize: '0.65rem' }}>
              <input type="checkbox" checked={selectedSubs.includes(s.name)} onChange={() => toggleOne(s.name)} />
              <span className="orch-tool-toggle-info">
                <span className="orch-tool-toggle-name">{s.name}{s.sensitive ? <SensitiveToolTag tool={s} /> : null}</span>
                <span className="orch-tool-toggle-desc">{s.desc}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OrchestratorPage() {
  // Conversations
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);

  // Messages
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [streamingAudio, setStreamingAudio] = useState(null);

  // Activity
  const [activity, setActivity] = useState([]);
  const [showActivity, setShowActivity] = useState(true);
  const [activityFilter, setActivityFilter] = useState('all'); // 'all' or 'conversation'

  // Settings
  const [settings, setSettings] = useState(null);

  // Providers & Models
  const [providers, setProviders] = useState([]);
  const [liveModels, setLiveModels] = useState([]);
  const [dbModels, setDbModels] = useState([]);
  const [uniqueModels, setUniqueModels] = useState([]);
  // 'conversations' | 'models' | 'agents' | 'labs' | 'outreach'.
  // Honors a ?tab= query param so other pages (e.g. the Dashboard) can deep-link a tab.
  const [sidebarTab, setSidebarTab] = useState(() => {
    const t = new URLSearchParams(window.location.search).get('tab');
    return ['conversations', 'models', 'agents', 'labs', 'outreach'].includes(t)
      ? t
      : 'conversations';
  });
  const [providerTestStatus, setProviderTestStatus] = useState({}); // id -> 'testing' | 'ok' | 'fail'
  const [syncing, setSyncing] = useState(false);

  // New provider form
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [newProvider, setNewProvider] = useState({ name: '', provider_type: 'ollama', base_url: '', api_key: '' });
  const [newProviderError, setNewProviderError] = useState('');

  // Chat model selector
  const [selectedModel, setSelectedModel] = useState('');

  // Agent selector for conversations
  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null); // agent object or null

  // Tool events during streaming
  const [toolEvents, setToolEvents] = useState([]); // [{type: 'call'|'result', ...}]

  // Ad-hoc tools for conversation (without agent)
  const [showToolsPanel, setShowToolsPanel] = useState(false);
  const [conversationTools, setConversationTools] = useState([]); // list of tool names
  const [toolSets, setToolSets] = useState([]);
  const [builtinTools, setBuiltinTools] = useState([]);

  // Image attachments for chat
  const [attachedImages, setAttachedImages] = useState([]); // [{dataUrl, name}]
  const fileInputRef = useRef(null);

  // Image context mode: 'minimal' = only current images, 'full' = include history images
  const [contextMode, setContextMode] = useState('minimal');

  // Expandable providers in Models tab
  const [expandedProviders, setExpandedProviders] = useState({});
  const [providerTypes, setProviderTypes] = useState([]);

  // LB Activity Feed
  const [lbEvents, setLbEvents] = useState([]);
  const [lbStats, setLbStats] = useState(null);
  const [lbPeriod, setLbPeriod] = useState('1h');
  const [lbFilter, setLbFilter] = useState({ model: '', server: '', event_type: '' });
  const [lbTab, setLbTab] = useState('feed'); // 'feed' | 'stats' | 'diagram'
  const [lbView, setLbView] = useState('grouped'); // 'flat' | 'grouped'
  const [expandedRequests, setExpandedRequests] = useState({}); // request_id -> bool
  const [eventDetails, setEventDetails] = useState({}); // event_id -> full detail
  const [expandedIO, setExpandedIO] = useState({}); // event_id -> bool
  const [fullViewCard, setFullViewCard] = useState(null); // { groupKey, group, displayName } for center panel

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Build model_identifier → context_length lookup
  const contextLengthMap = React.useMemo(() => {
    const map = {};
    for (const m of dbModels) {
      if (m.parameters?.context_length && !map[m.model_identifier]) {
        map[m.model_identifier] = m.parameters.context_length;
      }
    }
    return map;
  }, [dbModels]);

  // ── Load conversations on mount ────────────────
  useEffect(() => {
    loadConversations();
    loadSettings();
    loadProviders();
    getAIProviderTypes()
      .then(r => setProviderTypes(r.data?.provider_types || []))
      .catch(e => console.error('Failed to load provider types', e));
    loadModels();
    loadAgents();
    getToolSets().then(r => setToolSets(r.data || [])).catch(() => {});
    getBuiltinTools().then(r => setBuiltinTools(r.data || [])).catch(() => {});
  }, []);

  // ── Poll live models from agents (only when Models tab is active) ──
  useEffect(() => {
    if (sidebarTab !== 'models') return;
    loadLiveModels();
    const interval = setInterval(loadLiveModels, 30000);
    return () => clearInterval(interval);
  }, [sidebarTab]);

  // ── Load messages when active conversation changes ─
  useEffect(() => {
    if (activeConvId) {
      loadMessages(activeConvId);
      // Restore agent selection and tools from conversation
      const conv = conversations.find(c => c.id === activeConvId);
      if (conv?.agent_id) {
        const ag = agents.find(a => a.id === conv.agent_id);
        setSelectedAgent(ag || null);
      }
      setConversationTools(conv?.tools || []);
      setShowToolsPanel(false);
    } else {
      setMessages([]);
    }
  }, [activeConvId]);

  // ── Load activity feed ─────────────────────────
  useEffect(() => {
    loadActivity();
    const interval = setInterval(loadActivity, 5000);
    return () => clearInterval(interval);
  }, [activeConvId, activityFilter]);

  // ── Poll LB events when Models tab is active ──
  useEffect(() => {
    if (sidebarTab !== 'models') return;
    loadLbEvents();
    loadLbStats();
    const interval = setInterval(() => { loadLbEvents(); loadLbStats(); }, 3000);
    return () => clearInterval(interval);
  }, [sidebarTab, lbPeriod, lbFilter]);

  // ── WebSocket subscription for real-time updates ─
  useEffect(() => {
    const unsubMsg = wsService.on('orchestrator.message', (data) => {
      if (data.conversation_id === activeConvId) {
        if (data.role === 'assistant') {
          setMessages(prev => {
            const exists = prev.some(m => m.id === data.message_id);
            if (exists) return prev;
            return [...prev, {
              id: data.message_id,
              role: 'assistant',
              content: data.content,
              model_used: data.model_used,
              tokens_in: data.tokens_in,
              tokens_out: data.tokens_out,
              duration_ms: data.duration_ms,
              created_at: new Date().toISOString(),
            }];
          });
        }
      }
      // Refresh conversation list for title updates
      loadConversations();
    });

    return () => unsubMsg();
  }, [activeConvId]);

  // ── Auto-scroll to bottom ──────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingText]);

  // ── Data loaders ───────────────────────────────

  async function loadConversations() {
    try {
      const res = await getConversations();
      setConversations(res.data);
    } catch (e) {
      console.error('Failed to load conversations', e);
    }
  }

  async function loadMessages(convId) {
    try {
      const res = await getMessages(convId);
      setMessages(res.data);
      // Set model selector to the model used in the last assistant message
      const lastAssistant = [...res.data].reverse().find(m => m.role === 'assistant' && m.model_used);
      if (lastAssistant) {
        setSelectedModel(lastAssistant.model_used);
      }
    } catch (e) {
      console.error('Failed to load messages', e);
    }
  }

  async function loadActivity() {
    try {
      const convId = activityFilter === 'conversation' ? activeConvId : undefined;
      const res = await getActivity(convId);
      setActivity(res.data);
    } catch (e) {
      console.error('Failed to load activity', e);
    }
  }

  async function loadSettings() {
    try {
      const res = await getOrchestratorSettings();
      setSettings(res.data);
    } catch { /* settings may not exist yet */ }
  }

  async function loadProviders() {
    try {
      const res = await getAIProviders();
      setProviders(res.data);
    } catch (e) { console.error('Failed to load providers', e); }
  }

  async function loadLiveModels() {
    try {
      const res = await getLiveModels();
      setLiveModels(res.data);
    } catch (e) { console.error('Failed to load live models', e); }
  }

  async function loadModels() {
    try {
      const [rawRes, uniqRes] = await Promise.all([getAIModels(), getUniqueModels()]);
      setDbModels(rawRes.data);
      setUniqueModels(uniqRes.data);
    } catch (e) { console.error('Failed to load models', e); }
  }

  async function loadAgents() {
    try {
      const res = await getAIAgents();
      setAgents(res.data || []);
    } catch (e) { console.error('Failed to load agents', e); }
  }

  async function loadLbEvents() {
    try {
      const params = { limit: 100, since: lbPeriod };
      if (lbFilter.model) params.model = lbFilter.model;
      if (lbFilter.server) params.server = lbFilter.server;
      if (lbFilter.event_type) params.event_type = lbFilter.event_type;
      const res = await getLlmEvents(params);
      setLbEvents(res.data);
    } catch (e) { console.error('Failed to load LB events', e); }
  }

  async function loadLbStats() {
    try {
      const params = { period: lbPeriod };
      if (lbFilter.model) params.model = lbFilter.model;
      if (lbFilter.server) params.server = lbFilter.server;
      const res = await getLlmEventStats(params);
      setLbStats(res.data);
    } catch (e) { console.error('Failed to load LB stats', e); }
  }

  async function toggleEventIO(eventId) {
    const isExpanding = !expandedIO[eventId];
    setExpandedIO(prev => ({ ...prev, [eventId]: isExpanding }));
    if (isExpanding && !eventDetails[eventId]) {
      try {
        const res = await getLlmEventDetail(eventId);
        setEventDetails(prev => ({ ...prev, [eventId]: res.data }));
      } catch (e) { console.error('Failed to load event detail', e); }
    }
  }

  // ── Actions ────────────────────────────────────

  async function handleAddProvider() {
    setNewProviderError('');
    if (!newProvider.name.trim()) { setNewProviderError('Name is required.'); return; }
    if (!newProvider.base_url.trim()) { setNewProviderError('Base URL is required.'); return; }
    // Auto-prepend http:// if no protocol given
    let url = newProvider.base_url.trim();
    if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
    try {
      await createAIProvider({ ...newProvider, base_url: url });
      setNewProvider({ name: '', provider_type: 'ollama', base_url: '', api_key: '' });
      setNewProviderError('');
      setShowAddProvider(false);
      loadProviders();
    } catch (e) {
      console.error('Failed to create provider', e);
      setNewProviderError(e?.response?.data?.detail || 'Failed to add provider.');
    }
  }

  async function handleDeleteProvider(id, e) {
    e.stopPropagation();
    try {
      await deleteAIProvider(id);
      loadProviders();
    } catch (e) { console.error('Failed to delete provider', e); }
  }

  async function handleTestProvider(id) {
    setProviderTestStatus(prev => ({ ...prev, [id]: 'testing' }));
    try {
      const res = await testAIProvider(id);
      // Backend returns 200 with {healthy: bool} — the boolean is the actual result.
      // Treating any non-throw as "ok" was the bug: an unreachable upstream still
      // returns 200 from the /test route with healthy=false.
      const ok = res?.data?.healthy === true;
      setProviderTestStatus(prev => ({ ...prev, [id]: ok ? 'ok' : 'fail' }));
    } catch (e) {
      setProviderTestStatus(prev => ({ ...prev, [id]: 'fail' }));
    } finally {
      setTimeout(() => setProviderTestStatus(prev => { const n = {...prev}; delete n[id]; return n; }), 3000);
    }
  }

  async function handleUpdateSettings(key, value) {
    try {
      const res = await updateOrchestratorSettings({ [key]: value });
      setSettings(res.data);
    } catch (e) { console.error('Failed to update settings', e); }
  }

  async function handleSyncAll() {
    setSyncing(true);
    try {
      const res = await syncAllModels();
      loadProviders();
      loadModels();
      loadLiveModels();
    } catch (e) { console.error('Failed to sync models', e); }
    setSyncing(false);
  }

  async function handleNewConversation() {
    try {
      const payload = { title: 'New Conversation' };
      if (selectedAgent) payload.agent_id = selectedAgent.id;
      const res = await createConversation(payload);
      setConversations(prev => [res.data, ...prev]);
      setActiveConvId(res.data.id);
      setMessages([]);
    } catch (e) {
      console.error('Failed to create conversation', e);
    }
  }

  async function handleDeleteConversation(convId, e) {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      setConversations(prev => prev.filter(c => c.id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error('Failed to delete conversation', err);
    }
  }

  function handleImageAttach(e) {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      if (!file.type.startsWith('image/')) continue;
      const reader = new FileReader();
      reader.onload = () => {
        setAttachedImages(prev => [...prev, { dataUrl: reader.result, name: file.name }]);
      };
      reader.readAsDataURL(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  function removeAttachedImage(idx) {
    setAttachedImages(prev => prev.filter((_, i) => i !== idx));
  }

  async function handleSend() {
    if ((!input.trim() && !attachedImages.length) || streaming) return;
    const images = attachedImages.map(img => img.dataUrl);
    setAttachedImages([]);
    if (!activeConvId) {
      // Auto-create conversation
      try {
        const payload = { title: 'New Conversation' };
        if (selectedAgent) payload.agent_id = selectedAgent.id;
        const res = await createConversation(payload);
        setConversations(prev => [res.data, ...prev]);
        setActiveConvId(res.data.id);
        sendToConversation(res.data.id, input.trim(), images);
      } catch (e) {
        console.error(e);
      }
      return;
    }
    sendToConversation(activeConvId, input.trim(), images);
  }

  function sendToConversation(convId, content, images = []) {
    // Add user message optimistically
    const userMsg = {
      id: 'tmp-' + Date.now(),
      conversation_id: convId,
      role: 'user',
      content,
      extra: images.length ? { images } : {},
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setStreaming(true);
    setStreamingText('');
    setStreamingAudio(null);
    setToolEvents([]);

    sendMessage(
      convId,
      content,
      // onToken
      (token) => {
        setStreamingText(prev => prev + token);
      },
      // onDone
      (data) => {
        setStreaming(false);
        setStreamingText('');
        setStreamingAudio(null);
        setToolEvents([]);
        // Reload messages to get the complete saved assistant message
        loadMessages(convId);
        loadConversations();
        loadActivity();
      },
      // onError
      (err) => {
        setStreaming(false);
        setStreamingText('');
        setStreamingAudio(null);
        setToolEvents([]);
        console.error('Streaming error:', err);
        setMessages(prev => [...prev, {
          id: 'err-' + Date.now(),
          role: 'assistant',
          content: `⚠️ Error: ${err.message}`,
          created_at: new Date().toISOString(),
        }]);
      },
      // model override
      selectedModel || undefined,
      // images
      images.length ? images : undefined,
      // context mode
      contextMode,
      // onAudio (riffusion)
      (audioData) => {
        setStreamingAudio(audioData);
      },
      // agentId
      selectedAgent?.id || undefined,
      // onToolEvent
      (data) => {
        setToolEvents(prev => [...prev, data]);
      },
      // ad-hoc tools
      conversationTools.length ? conversationTools : undefined,
    );
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString();
  }

  // ── Render ─────────────────────────────────────

  // Group conversations by date
  const grouped = {};
  conversations.forEach(c => {
    const key = formatDate(c.updated_at || c.created_at);
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(c);
  });

  // Total live models across all servers
  const totalLiveModels = liveModels.reduce((acc, s) => acc + s.models.length, 0);

  // Available models for orchestrator model selector (deduplicated)
  const allModelNames = [...new Set([
    ...uniqueModels.filter(m => m.any_available).map(m => m.model_identifier),
    ...liveModels.flatMap(s => s.models.map(m => m.name)),
  ])];

  function formatSize(bytes) {
    if (!bytes) return '';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    return (bytes / (1024 * 1024)).toFixed(0) + ' MB';
  }

  function toggleProviderExpanded(id) {
    setExpandedProviders(prev => ({ ...prev, [id]: !prev[id] }));
  }

  // Check if a provider's server is online (has live models)
  function isProviderOnline(provider) {
    return liveModels.some(s =>
      s.models && s.models.length > 0 &&
      (s.provider_id === provider.id || s.server === provider.name || s.provider_name === provider.name)
    );
  }

  // Get models for a provider from liveModels
  function getProviderModels(provider) {
    const srv = liveModels.find(s =>
      s.provider_id === provider.id || s.server === provider.name || s.provider_name === provider.name
    );
    return srv ? srv.models : [];
  }

  // ── Outreach expanded view ──────────────────────
  if (sidebarTab === 'outreach') {
    return (
      <div className="orch-layout orch-layout-fullwidth">
        <div className="orch-topbar">
          <button className={`orch-tab`} onClick={() => setSidebarTab('conversations')}>Chat</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('models')}>Models</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('agents')}>🤖 Agents</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('labs')}>{IC.chip} Labs</button>
          <button className={`orch-tab active`}>📨 Outreach</button>
        </div>
        <div className="orch-topbar-body">
          <OutreachView />
        </div>
        <style>{orchStyles}</style>
      </div>
    );
  }

  // ── Labs expanded view ──────────────────────────
  if (sidebarTab === 'labs') {
    return (
      <div className="orch-layout orch-layout-fullwidth">
        <div className="orch-topbar">
          <button className={`orch-tab`} onClick={() => setSidebarTab('conversations')}>Chat</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('models')}>Models</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('agents')}>🤖 Agents</button>
          <button className={`orch-tab active`}>{IC.chip} Labs</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('outreach')}>📨 Outreach</button>
        </div>
        <div className="orch-topbar-body">
          <LabsView />
        </div>
        <style>{orchStyles}</style>
      </div>
    );
  }

  // ── Agents expanded view ─────────────────────────
  if (sidebarTab === 'agents') {
    return (
      <div className="orch-layout orch-layout-fullwidth">
        <div className="orch-topbar">
          <button className={`orch-tab`} onClick={() => setSidebarTab('conversations')}>Chat</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('models')}>Models</button>
          <button className={`orch-tab active`}>🤖 Agents</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('labs')}>{IC.chip} Labs</button>
          <button className={`orch-tab`} onClick={() => setSidebarTab('outreach')}>📨 Outreach</button>
        </div>
        <div className="orch-topbar-body">
          <AgentsView allModels={dbModels} />
        </div>
        <style>{orchStyles}</style>
      </div>
    );
  }

  return (
    <div className="orch-layout orch-layout-fullwidth">
      <div className="orch-topbar">
        <button className={`orch-tab ${sidebarTab === 'conversations' ? 'active' : ''}`} onClick={() => setSidebarTab('conversations')}>
          Chat
        </button>
        <button className={`orch-tab ${sidebarTab === 'models' ? 'active' : ''}`} onClick={() => setSidebarTab('models')}>
          Models {totalLiveModels > 0 && <span className="orch-tab-badge">{totalLiveModels}</span>}
        </button>
        <button className={`orch-tab`} onClick={() => setSidebarTab('agents')}>
          🤖 Agents
        </button>
        <button className={`orch-tab`} onClick={() => setSidebarTab('labs')}>
          {IC.chip} Labs
        </button>
        <button className={`orch-tab`} onClick={() => setSidebarTab('outreach')}>
          📨 Outreach
        </button>
      </div>
      <div className="orch-topbar-body">
      {/* ── Left Panel: Tabbed Sidebar ────────── */}
      <aside className="orch-sidebar">

        {/* ── Conversations Tab ─── */}
        {sidebarTab === 'conversations' && (
          <>
            <div className="orch-sidebar-header">
              <h2>Conversations</h2>
              <button className="orch-btn-icon" onClick={handleNewConversation} title="New conversation">
                {IC.plus}
              </button>
            </div>
            <div className="orch-conv-list">
              {Object.entries(grouped).map(([dateLabel, convs]) => (
                <div key={dateLabel}>
                  <div className="orch-date-label">{dateLabel}</div>
                  {convs.map(c => (
                    <div
                      key={c.id}
                      className={`orch-conv-item ${c.id === activeConvId ? 'active' : ''}`}
                      onClick={() => setActiveConvId(c.id)}
                    >
                      <div className="orch-conv-title">{c.title}</div>
                      {c.last_message && (
                        <div className="orch-conv-preview">{c.last_message}</div>
                      )}
                      <button
                        className="orch-conv-delete"
                        onClick={(e) => handleDeleteConversation(c.id, e)}
                        title="Delete"
                      >
                        {IC.trash}
                      </button>
                    </div>
                  ))}
                </div>
              ))}
              {conversations.length === 0 && (
                <div className="orch-empty">No conversations yet. Click + to start.</div>
              )}
            </div>
          </>
        )}

        {/* ── Models Tab ─── */}
        {sidebarTab === 'models' && (
          <div className="orch-panel-scroll">
            {/* Default Model Selector */}
            {allModelNames.length > 0 && settings && (
              <div className="orch-default-model-section">
                <div className="orch-section-title">Default Model</div>
                <select
                  className="orch-select orch-default-model-select"
                  value={settings.orchestrator_model || ''}
                  onChange={e => handleUpdateSettings('orchestrator_model', e.target.value)}
                >
                  {allModelNames.map(n => (
                    <option key={n} value={n}>{n}{n === settings.orchestrator_model ? ' ★' : ''}</option>
                  ))}
                </select>
                <div className="orch-default-model-hint">
                  Used when no model is selected per-message
                </div>
              </div>
            )}

            {/* AI Providers */}
            <div className="orch-section-title">
              AI Providers
              <button className="orch-btn-sm" onClick={() => setShowAddProvider(!showAddProvider)}>
                {IC.plus}
              </button>
            </div>

            {showAddProvider && (
              <div className="orch-add-provider">
                <input
                  className="orch-input-sm"
                  placeholder="Name (e.g. my-ollama)"
                  value={newProvider.name}
                  onChange={e => setNewProvider({...newProvider, name: e.target.value})}
                />
                <select
                  className="orch-select"
                  value={newProvider.provider_type}
                  onChange={e => {
                    const type = e.target.value;
                    const presets = {
                      anthropic: 'https://api.anthropic.com',
                      openai_cloud: 'https://api.openai.com',
                      xai: 'https://api.x.ai',
                      groq: 'https://api.groq.com/openai',
                      deepseek: 'https://api.deepseek.com',
                    };
                    setNewProvider({
                      ...newProvider,
                      provider_type: type,
                      base_url: presets[type] || newProvider.base_url,
                    });
                  }}
                >
                  {(providerTypes.length > 0
                    ? providerTypes
                    : [{ type: 'ollama', label: 'Ollama (Local)' }]
                  ).map(p => (
                    <option key={p.type} value={p.type}>{p.label}</option>
                  ))}
                </select>
                <input
                  className="orch-input-sm"
                  placeholder="Base URL (e.g. http://192.168.1.100:11434)"
                  value={newProvider.base_url}
                  onChange={e => setNewProvider({...newProvider, base_url: e.target.value})}
                />
                {newProvider.provider_type !== 'ollama' && (
                  <input
                    className="orch-input-sm"
                    placeholder={['anthropic','openai_cloud','xai','groq','deepseek'].includes(newProvider.provider_type) ? 'API Key (required)' : 'API Key (optional)'}
                    type="password"
                    value={newProvider.api_key}
                    onChange={e => setNewProvider({...newProvider, api_key: e.target.value})}
                  />
                )}
                {newProviderError && <div style={{color:'#f87171',fontSize:'0.72rem',padding:'2px 0'}}>{newProviderError}</div>}
                <div className="orch-add-provider-actions">
                  <button className="orch-btn-primary" onClick={handleAddProvider}>Add</button>
                  <button className="orch-btn-ghost" onClick={() => { setShowAddProvider(false); setNewProviderError(''); }}>Cancel</button>
                </div>
              </div>
            )}

            {(() => {
              // Group providers by server_id — providers on the same server share one card
              const serverGroups = {};
              const standalone = [];
              providers.forEach(p => {
                if (p.server_id) {
                  if (!serverGroups[p.server_id]) serverGroups[p.server_id] = [];
                  serverGroups[p.server_id].push(p);
                } else {
                  standalone.push(p);
                }
              });

              // Inject ToolAI entries from liveModels into matching server groups
              const toolEntries = liveModels.filter(s => s.provider_type === 'toolai' && s.models && s.models.length > 0);
              const unmatchedToolEntries = [];
              toolEntries.forEach(entry => {
                // Find a serverGroup where a provider's server_name matches entry.server
                let matched = false;
                for (const [sid, group] of Object.entries(serverGroups)) {
                  if (group.some(p => p.server_name === entry.server)) {
                    // Add synthetic provider to this group
                    serverGroups[sid].push({
                      id: `toolai-${entry.server}`,
                      provider_type: 'toolai',
                      name: entry.provider_name,
                      base_url: 'Script Runner',
                      server_name: entry.server,
                      server_id: sid,
                      _synthetic: true,
                    });
                    matched = true;
                    break;
                  }
                }
                if (!matched) unmatchedToolEntries.push(entry);
              });

              // Determine display name for a server group (prefer server_name from DB)
              const getServerDisplayName = (group) => {
                const withServerName = group.find(p => p.server_name);
                if (withServerName) return withServerName.server_name;
                const ollama = group.find(p => p.provider_type === 'ollama');
                if (ollama) return ollama.name;
                return group[0].name;
              };

              const renderServerCard = (groupKey, group) => {
                const displayName = getServerDisplayName(group);
                const expanded = expandedProviders[groupKey];
                const allModels = group.flatMap(p => {
                  const models = getProviderModels(p);
                  return models.map(m => ({ ...m, _providerType: p.provider_type, _providerId: p.id }));
                });
                const totalModels = allModels.length;
                const providerTypes = [...new Set(group.map(p => p.provider_type))];

                return (
                  <div key={groupKey} className="orch-provider-card">
                    <div
                      className="orch-provider-header"
                      onClick={() => toggleProviderExpanded(groupKey)}
                      style={{ cursor: 'pointer' }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                        <span className={`orch-expand-arrow ${expanded ? 'expanded' : ''}`}>{IC.chevronRight}</span>
                        <span className="orch-provider-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{displayName}</span>
                        {totalModels > 0 && <span className="orch-model-count">{totalModels}</span>}
                      </div>
                      <button
                        className="orch-btn-fullview"
                        onClick={(e) => { e.stopPropagation(); setFullViewCard({ groupKey, group, displayName }); }}
                        title="Full view"
                      >⛶</button>
                    </div>
                    <div className="orch-provider-badges">
                      {providerTypes.map(pt => {
                        const ptProviders = group.filter(p => p.provider_type === pt);
                        const ptOnline = ptProviders.some(p => isProviderOnline(p));
                        return (
                          <span key={pt} className="orch-provider-tag-group">
                            <span className={`orch-provider-type ${pt}`}>{pt}</span>
                            <span className={`orch-status-dot-sm ${ptOnline ? 'online' : 'offline'}`} />
                          </span>
                        );
                      })}
                    </div>

                    {expanded && (
                      <div className="orch-provider-expanded">
                        {group.map(p => (
                          <div key={p.id} className="orch-sub-provider">
                            <div className="orch-sub-provider-header">
                              <span className={`orch-provider-type ${p.provider_type}`}>{p.provider_type}</span>
                              <span className="orch-provider-url" style={{ marginBottom: 0, flex: 1 }}>{p.base_url}</span>
                            </div>
                            {!p._synthetic && (
                            <div className="orch-provider-actions">
                              <button
                                className="orch-btn-sm"
                                onClick={() => handleTestProvider(p.id)}
                                disabled={providerTestStatus[p.id] === 'testing'}
                                title="Test connection"
                              >
                                {providerTestStatus[p.id] === 'testing' ? IC.loader :
                                 providerTestStatus[p.id] === 'ok' ? <span style={{color:'var(--success)'}}>OK</span> :
                                 providerTestStatus[p.id] === 'fail' ? <span style={{color:'var(--error)'}}>FAIL</span> :
                                 'Test'}
                              </button>
                              <button
                                className="orch-btn-sm orch-btn-danger"
                                onClick={(e) => handleDeleteProvider(p.id, e)}
                                title="Delete"
                              >
                                {IC.trash}
                              </button>
                            </div>
                            )}

                            {/* Live models for this sub-provider */}
                            {(() => {
                              const pModels = getProviderModels(p);
                              if (pModels.length === 0) return null;
                              return (
                                <div className="orch-provider-models">
                                  {pModels.map(m => (
                                    <div key={m.name} className="orch-model-row">
                                      <span className="orch-model-name">{m.name}</span>
                                      <span className="orch-model-info">
                                        {m.parameter_size && <span>{m.parameter_size}</span>}
                                        {m.quantization && <span>{m.quantization}</span>}
                                        {m.size > 0 && <span>{formatSize(m.size)}</span>}
                                      </span>
                                      <span className="orch-model-available">{IC.check}</span>
                                    </div>
                                  ))}
                                </div>
                              );
                            })()}
                          </div>
                        ))}
                        {totalModels === 0 && (
                          <div className="orch-empty" style={{ padding: '8px 0', fontSize: '0.7rem' }}>
                            No live models — try Discover or check connection
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              };

              return (
                <>
                  {Object.entries(serverGroups).map(([sid, group]) => renderServerCard(sid, group))}
                  {standalone.map(p => renderServerCard(p.id, [p]))}
                  {unmatchedToolEntries.map(entry => {
                    const synth = {
                      id: `toolai-${entry.server}`,
                      provider_type: 'toolai',
                      name: entry.provider_name,
                      base_url: 'Script Runner',
                      server_name: entry.server,
                      _synthetic: true,
                    };
                    return renderServerCard(synth.id, [synth]);
                  })}
                </>
              );
            })()}

            {providers.length === 0 && !showAddProvider && (
              <div className="orch-empty" style={{ padding: '12px 0' }}>
                No providers configured. Providers are auto-created when agents report Ollama.
              </div>
            )}

            {uniqueModels.length > 0 && (
              <>
                <div className="orch-section-title" style={{ marginTop: 16 }}>
                  Synced to Database
                  <button className="orch-btn-sm" onClick={handleSyncAll} disabled={syncing} title="Discover & sync all models to DB">
                    {syncing ? IC.loader : IC.refresh} {syncing ? 'Syncing...' : 'Sync All'}
                  </button>
                </div>
                {uniqueModels.map(m => (
                  <div key={m.model_identifier} className="orch-model-row">
                    <span className="orch-model-name">{m.model_identifier}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {m.total_providers > 1 && (
                        <span className={`orch-server-count-tag ${m.available_providers === m.total_providers ? 'all-up' : m.available_providers > 0 ? 'partial' : 'all-down'}`}>
                          {m.available_providers}/{m.total_providers}
                        </span>
                      )}
                      <span className={`orch-model-status ${m.any_available ? 'available' : 'unavailable'}`}>
                        {m.any_available ? 'available' : 'offline'}
                      </span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        )}


      </aside>

      {/* ── Center: Chat or LB Feed ──────────────────────── */}
      {sidebarTab === 'models' && fullViewCard ? (
        <main className="orch-chat">
          <div className="orch-chat-header">
            <div className="orch-chat-title">
              {IC.server}
              <span>{fullViewCard.displayName}</span>
            </div>
            <button className="orch-btn-sm" onClick={() => setFullViewCard(null)}>✕ Close</button>
          </div>
          <div className="orch-fullview-body">
            {fullViewCard.group.map(p => {
              const pModels = getProviderModels(p);
              const online = isProviderOnline(p);
              return (
                <div key={p.id} className="orch-fullview-provider">
                  <div className="orch-fullview-provider-header">
                    <span className={`orch-provider-type ${p.provider_type}`}>{p.provider_type}</span>
                    <span className={`orch-status-dot-sm ${online ? 'online' : 'offline'}`} />
                    <span className="orch-fullview-url">{p.base_url}</span>
                  </div>
                  {!p._synthetic && (
                    <div className="orch-provider-actions" style={{ marginBottom: 8 }}>
                      <button className="orch-btn-sm" onClick={() => handleTestProvider(p.id)} disabled={providerTestStatus[p.id] === 'testing'} title="Test connection">
                        {providerTestStatus[p.id] === 'testing' ? IC.loader : providerTestStatus[p.id] === 'ok' ? <span style={{color:'var(--success)'}}>OK</span> : providerTestStatus[p.id] === 'fail' ? <span style={{color:'var(--error)'}}>FAIL</span> : 'Test'}
                      </button>
                    </div>
                  )}
                  {pModels.length > 0 ? (
                    <div className="orch-fullview-models">
                      {pModels.map(m => (
                        <div key={m.name} className="orch-fullview-model-row">
                          <span className="orch-model-name">{m.name}</span>
                          <span className="orch-model-info">
                            {m.parameter_size && <span>{m.parameter_size}</span>}
                            {m.quantization && <span>{m.quantization}</span>}
                            {m.family && <span>{m.family}</span>}
                            {m.size > 0 && <span>{formatSize(m.size)}</span>}
                          </span>
                          <span className="orch-model-available">{IC.check}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="orch-empty" style={{ padding: '8px 0', fontSize: '0.75rem' }}>No live models</div>
                  )}
                </div>
              );
            })}
          </div>
        </main>
      ) : sidebarTab === 'models' ? (
        <main className="orch-chat">
          <div className="orch-chat-header">
            <div className="orch-chat-title">
              {IC.activity}
              <span>Load Balancer</span>
              <div className="orch-lb-tabs">
                <button className={`orch-lb-tab ${lbTab === 'feed' ? 'active' : ''}`} onClick={() => setLbTab('feed')}>Feed</button>
                <button className={`orch-lb-tab ${lbTab === 'stats' ? 'active' : ''}`} onClick={() => setLbTab('stats')}>Stats</button>
                <button className={`orch-lb-tab ${lbTab === 'diagram' ? 'active' : ''}`} onClick={() => setLbTab('diagram')}>Live</button>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {lbTab === 'feed' && (
                <div className="orch-lb-view-toggle">
                  <button className={lbView === 'grouped' ? 'active' : ''} onClick={() => setLbView('grouped')} title="Group by request">⊞</button>
                  <button className={lbView === 'flat' ? 'active' : ''} onClick={() => setLbView('flat')} title="Flat list">☰</button>
                </div>
              )}
              <select className="orch-activity-filter" value={lbPeriod} onChange={e => setLbPeriod(e.target.value)}>
                <option value="1h">Last 1h</option>
                <option value="1d">Last 24h</option>
                <option value="1w">Last 7d</option>
                <option value="1m">Last 30d</option>
              </select>
              {lbTab === 'feed' && (
                <select className="orch-activity-filter" value={lbFilter.event_type} onChange={e => setLbFilter(f => ({...f, event_type: e.target.value}))}>
                  <option value="">All Events</option>
                  <option value="queue">Queue</option>
                  <option value="dispatch">Dispatch</option>
                  <option value="response">Response</option>
                  <option value="failed">Failed</option>
                </select>
              )}
            </div>
          </div>

          {lbTab === 'feed' ? (
            <div className="orch-lb-feed">
              {lbEvents.length === 0 && (
                <div className="orch-empty">No load balancer events yet. Send a message to a model to see activity here.</div>
              )}
              {lbView === 'flat' ? (
                /* ── Flat view (original) ── */
                lbEvents.map((ev, i) => (
                  <div key={ev.id || i} className={`orch-lb-event-wrap`}>
                    <div className={`orch-lb-event orch-lb-event-${ev.event_type} ${(ev.has_input || ev.has_output) ? 'has-io' : ''}`}
                         onClick={() => (ev.has_input || ev.has_output) && toggleEventIO(ev.id)}
                         style={(ev.has_input || ev.has_output) ? { cursor: 'pointer' } : {}}>
                      <span className="orch-lb-event-time">{new Date(ev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                      <span className={`orch-lb-event-type ${ev.event_type}`}>{ev.event_type}</span>
                      <span className="orch-lb-event-caller">{ev.caller_type === 'lab_orchestrator' && ev.lab_name ? `Orchestrator · ${ev.lab_name}` : (ev.caller_name || ev.caller_type || '—')}</span>
                      <span className="orch-lb-event-model" title={ev.model_identifier}>{ev.model_identifier || '—'}</span>
                      {ev.server_name && <span className="orch-lb-event-server">{ev.server_name}</span>}
                      {ev.provider_name && <span className="orch-lb-event-provider">{ev.provider_name}</span>}
                      {ev.tokens_out > 0 && <span className="orch-lb-event-tokens">{ev.tokens_in}→{ev.tokens_out}tok</span>}
                      {ev.duration_ms > 0 && <span className="orch-lb-event-duration">{ev.duration_ms}ms</span>}
                      {ev.tokens_in > 0 && contextLengthMap[ev.model_identifier] && (() => {
                        const ctx = contextLengthMap[ev.model_identifier];
                        const pct = Math.min((ev.tokens_in / ctx) * 100, 100);
                        const color = pct > 90 ? '#ef4444' : pct > 70 ? '#f59e0b' : '#22c55e';
                        return <span className="ctx-bar" title={`Context: ${ev.tokens_in.toLocaleString()} / ${ctx.toLocaleString()} (${pct.toFixed(1)}%)`}>
                          <span className="ctx-bar-fill" style={{ width: `${pct}%`, background: color }} />
                          <span className="ctx-bar-label">{pct.toFixed(0)}%</span>
                        </span>;
                      })()}
                      {ev.error && <span className="orch-lb-event-error" title={ev.error}>⚠ {ev.error.slice(0, 60)}</span>}
                      {(ev.has_input || ev.has_output) && <span className="orch-lb-io-badge">{expandedIO[ev.id] ? '▾' : '▸'} I/O</span>}
                    </div>
                    {expandedIO[ev.id] && (
                      <div className="orch-lb-io-detail">
                        {eventDetails[ev.id] ? (
                          <>
                            {eventDetails[ev.id].input_messages && (
                              <div className="orch-lb-io-section">
                                <div className="orch-lb-io-label">Prompt ({eventDetails[ev.id].input_messages.length} messages)</div>
                                <div className="orch-lb-io-messages">
                                  {eventDetails[ev.id].input_messages.map((msg, mi) => (
                                    <div key={mi} className={`orch-lb-io-msg orch-lb-io-msg-${msg.role}`}>
                                      <span className={`orch-lb-io-role ${msg.role}`}>{msg.role}</span>
                                      <pre className="orch-lb-io-content">{typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}</pre>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {eventDetails[ev.id].output_content && (
                              <div className="orch-lb-io-section">
                                <div className="orch-lb-io-label">Response</div>
                                <pre className="orch-lb-io-content orch-lb-io-response">{eventDetails[ev.id].output_content}</pre>
                              </div>
                            )}
                            {!eventDetails[ev.id].input_messages && !eventDetails[ev.id].output_content && (
                              <div className="orch-empty" style={{ padding: 8 }}>No I/O data recorded for this event</div>
                            )}
                          </>
                        ) : (
                          <div className="orch-empty" style={{ padding: 8 }}>Loading...</div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              ) : (
                /* ── Grouped by request_id ── */
                (() => {
                  // Group events by request_id
                  const groups = {};
                  lbEvents.forEach(ev => {
                    const rid = ev.request_id || ev.id;
                    if (!groups[rid]) groups[rid] = [];
                    groups[rid].push(ev);
                  });
                  // Sort groups by most recent event
                  const sorted = Object.entries(groups).sort((a, b) => {
                    const aTime = Math.max(...a[1].map(e => new Date(e.created_at).getTime()));
                    const bTime = Math.max(...b[1].map(e => new Date(e.created_at).getTime()));
                    return bTime - aTime;
                  });
                  return sorted.map(([rid, events]) => {
                    const types = new Set(events.map(e => e.event_type));
                    let status = 'queued';
                    if (types.has('response')) status = 'succeeded';
                    else if (types.has('failed') && !types.has('dispatch')) status = 'failed';
                    else if (types.has('failed') && types.has('dispatch')) status = 'retrying';
                    else if (types.has('dispatch')) status = 'running';
                    const first = events.reduce((a, b) => new Date(a.created_at) < new Date(b.created_at) ? a : b);
                    const last = events.reduce((a, b) => new Date(a.created_at) > new Date(b.created_at) ? a : b);
                    const respEv = events.find(e => e.event_type === 'response');
                    const failEv = events.find(e => e.event_type === 'failed');
                    const model = events.find(e => e.model_identifier)?.model_identifier || '—';
                    const server = events.find(e => e.server_name)?.server_name || '';
                    const labName = first.lab_name;
                    let caller = first.caller_name || first.caller_type || '—';
                    if (first.caller_type === 'lab_orchestrator' && labName) caller = `Orchestrator · ${labName}`;
                    const isExpanded = expandedRequests[rid];
                    const totalDur = respEv?.duration_ms || failEv?.duration_ms || (status === 'running' ? Math.round(Date.now() - new Date(first.created_at).getTime()) : 0);
                    return (
                      <div key={rid} className={`orch-lb-request orch-lb-request-${status}`}>
                        <div className="orch-lb-request-row" onClick={() => setExpandedRequests(p => ({...p, [rid]: !p[rid]}))}>
                          <span className="orch-lb-req-expand">{isExpanded ? '▾' : '▸'}</span>
                          <span className="orch-lb-event-time">{new Date(first.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                          <span className={`orch-lb-req-status ${status}`}>
                            {status === 'running' && <span className="orch-lb-pulse" />}
                            {status}
                          </span>
                          <span className="orch-lb-event-caller">{caller}</span>
                          <span className="orch-lb-event-model" title={model}>{model}</span>
                          {server && <span className="orch-lb-event-server">{server}</span>}
                          {respEv && respEv.tokens_out > 0 && <span className="orch-lb-event-tokens">{respEv.tokens_in}→{respEv.tokens_out}tok</span>}
                          {totalDur > 0 && <span className="orch-lb-event-duration">{totalDur >= 1000 ? (totalDur/1000).toFixed(1) + 's' : totalDur + 'ms'}</span>}
                          {respEv && respEv.tokens_in > 0 && contextLengthMap[model] && (() => {
                            const ctx = contextLengthMap[model];
                            const pct = Math.min((respEv.tokens_in / ctx) * 100, 100);
                            const color = pct > 90 ? '#ef4444' : pct > 70 ? '#f59e0b' : '#22c55e';
                            return <span className="ctx-bar" title={`Context: ${respEv.tokens_in.toLocaleString()} / ${ctx.toLocaleString()} (${pct.toFixed(1)}%)`}>
                              <span className="ctx-bar-fill" style={{ width: `${pct}%`, background: color }} />
                              <span className="ctx-bar-label">{pct.toFixed(0)}%</span>
                            </span>;
                          })()}
                          {failEv && <span className="orch-lb-event-error" title={failEv.error}>⚠ {(failEv.error || '').slice(0, 40)}</span>}
                          <span className="orch-lb-req-id">{rid.slice(0, 8)}</span>
                        </div>
                        {isExpanded && (
                          <div className="orch-lb-request-events">
                            {events.sort((a,b) => new Date(a.created_at) - new Date(b.created_at)).map((ev, i) => (
                              <div key={ev.id || i} className={`orch-lb-event orch-lb-event-${ev.event_type} orch-lb-event-nested`}>
                                <span className="orch-lb-event-time">{new Date(ev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })}</span>
                                <span className={`orch-lb-event-type ${ev.event_type}`}>{ev.event_type}</span>
                                {ev.server_name && <span className="orch-lb-event-server">{ev.server_name}</span>}
                                {ev.tokens_out > 0 && <span className="orch-lb-event-tokens">{ev.tokens_in}→{ev.tokens_out}tok</span>}
                                {ev.duration_ms > 0 && <span className="orch-lb-event-duration">{ev.duration_ms}ms</span>}
                                {ev.tokens_in > 0 && contextLengthMap[ev.model_identifier] && (() => {
                                  const ctx = contextLengthMap[ev.model_identifier];
                                  const pct = Math.min((ev.tokens_in / ctx) * 100, 100);
                                  const color = pct > 90 ? '#ef4444' : pct > 70 ? '#f59e0b' : '#22c55e';
                                  return <span className="ctx-bar" title={`Context: ${ev.tokens_in.toLocaleString()} / ${ctx.toLocaleString()} (${pct.toFixed(1)}%)`}>
                                    <span className="ctx-bar-fill" style={{ width: `${pct}%`, background: color }} />
                                    <span className="ctx-bar-label">{pct.toFixed(0)}%</span>
                                  </span>;
                                })()}
                                {ev.attempt > 1 && <span className="orch-lb-event-attempt">attempt {ev.attempt}/{ev.max_attempts}</span>}
                                {ev.error && <span className="orch-lb-event-error" title={ev.error}>⚠ {ev.error.slice(0, 60)}</span>}
                                {(ev.has_input || ev.has_output) && (
                                  <span className="orch-lb-io-badge" onClick={(e) => { e.stopPropagation(); toggleEventIO(ev.id); }}>{expandedIO[ev.id] ? '▾' : '▸'} I/O</span>
                                )}
                              </div>
                            ))}
                            {/* I/O detail: show for the first event in the group that has I/O */}
                            {(() => {
                              const ioEvents = events.filter(e => e.has_input || e.has_output);
                              const dispatchEv = ioEvents.find(e => e.event_type === 'dispatch') || ioEvents[0];
                              const responseEv = ioEvents.find(e => e.event_type === 'response');
                              if (!dispatchEv && !responseEv) return null;
                              // Auto-load when expanded
                              const ioId = dispatchEv?.id || responseEv?.id;
                              const respId = responseEv?.id;
                              return (expandedIO[ioId] || expandedIO[respId]) ? (
                                <div className="orch-lb-io-detail">
                                  {dispatchEv && eventDetails[dispatchEv.id]?.input_messages && (
                                    <div className="orch-lb-io-section">
                                      <div className="orch-lb-io-label">Prompt ({eventDetails[dispatchEv.id].input_messages.length} messages)</div>
                                      <div className="orch-lb-io-messages">
                                        {eventDetails[dispatchEv.id].input_messages.map((msg, mi) => (
                                          <div key={mi} className={`orch-lb-io-msg orch-lb-io-msg-${msg.role}`}>
                                            <span className={`orch-lb-io-role ${msg.role}`}>{msg.role}</span>
                                            <pre className="orch-lb-io-content">{typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}</pre>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {responseEv && eventDetails[responseEv.id]?.output_content && (
                                    <div className="orch-lb-io-section">
                                      <div className="orch-lb-io-label">Response</div>
                                      <pre className="orch-lb-io-content orch-lb-io-response">{eventDetails[responseEv.id].output_content}</pre>
                                    </div>
                                  )}
                                  {(!eventDetails[dispatchEv?.id] && !eventDetails[responseEv?.id]) && (
                                    <div className="orch-empty" style={{ padding: 8 }}>Loading...</div>
                                  )}
                                </div>
                              ) : null;
                            })()}
                          </div>
                        )}
                      </div>
                    );
                  });
                })()
              )}
            </div>
          ) : lbTab === 'stats' ? (
            <div className="orch-lb-stats">
              {lbStats ? (
                <>
                  {/* Summary Cards */}
                  <div className="orch-lb-summary">
                    <div className="orch-lb-stat-card">
                      <div className="orch-lb-stat-value">{lbStats.summary?.total || 0}</div>
                      <div className="orch-lb-stat-label">Total Requests</div>
                    </div>
                    <div className="orch-lb-stat-card success">
                      <div className="orch-lb-stat-value">{lbStats.summary?.succeeded || 0}</div>
                      <div className="orch-lb-stat-label">Succeeded</div>
                    </div>
                    <div className="orch-lb-stat-card error">
                      <div className="orch-lb-stat-value">{lbStats.summary?.failed || 0}</div>
                      <div className="orch-lb-stat-label">Failed</div>
                    </div>
                    <div className="orch-lb-stat-card info">
                      <div className="orch-lb-stat-value">{lbStats.summary?.queued || 0}</div>
                      <div className="orch-lb-stat-label">In Queue</div>
                    </div>
                  </div>

                  {/* Timeline Chart — stacked bars */}
                  {lbStats.timeline && lbStats.timeline.length > 0 && (
                    <div className="orch-lb-chart-section">
                      <h4 className="orch-lb-chart-title">Requests Over Time</h4>
                      <div className="orch-lb-chart">
                        {(() => {
                          const maxCount = Math.max(...lbStats.timeline.map(t => (t.succeeded || 0) + (t.failed || 0) + (t.dispatched || 0)), 1);
                          return lbStats.timeline.map((t, i) => {
                            const total = (t.succeeded || 0) + (t.failed || 0) + (t.dispatched || 0);
                            const sPct = total > 0 ? (t.succeeded / total) * 100 : 0;
                            const fPct = total > 0 ? (t.failed / total) * 100 : 0;
                            const dPct = total > 0 ? (t.dispatched / total) * 100 : 0;
                            return (
                              <div key={i} className="orch-lb-chart-bar-wrap" title={`${new Date(t.time).toLocaleString()}: ${t.succeeded || 0} ok / ${t.failed || 0} fail / ${t.dispatched || 0} dispatched`}>
                                <div className="orch-lb-chart-bar-stack" style={{ height: `${(total / maxCount) * 100}%` }}>
                                  {t.succeeded > 0 && <div className="orch-lb-bar-segment bar-succeeded" style={{ flex: sPct }} />}
                                  {t.dispatched > 0 && <div className="orch-lb-bar-segment bar-dispatched" style={{ flex: dPct }} />}
                                  {t.failed > 0 && <div className="orch-lb-bar-segment bar-failed" style={{ flex: fPct }} />}
                                </div>
                                <div className="orch-lb-chart-label">
                                  {new Date(t.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </div>
                              </div>
                            );
                          });
                        })()}
                      </div>
                      <div className="orch-lb-chart-legend">
                        <span><span className="orch-lb-legend-dot" style={{background:'#22c55e'}}/> Succeeded</span>
                        <span><span className="orch-lb-legend-dot" style={{background:'#3b82f6'}}/> Dispatched</span>
                        <span><span className="orch-lb-legend-dot" style={{background:'#ef4444'}}/> Failed</span>
                      </div>
                    </div>
                  )}

                  {/* By Model */}
                  {lbStats.by_model && lbStats.by_model.length > 0 && (
                    <div className="orch-lb-breakdown">
                      <h4 className="orch-lb-chart-title">By Model</h4>
                      {lbStats.by_model.map((m, i) => {
                        const maxTotal = Math.max(...lbStats.by_model.map(x => x.total), 1);
                        return (
                          <div key={i} className="orch-lb-breakdown-row">
                            <span className="orch-lb-breakdown-name">{m.model}</span>
                            <div className="orch-lb-breakdown-bar-bg">
                              <div className="orch-lb-breakdown-bar bar-succeeded" style={{ width: `${(m.succeeded / maxTotal) * 100}%` }} />
                              <div className="orch-lb-breakdown-bar bar-failed" style={{ width: `${(m.failed / maxTotal) * 100}%`, position: 'absolute', left: `${(m.succeeded / maxTotal) * 100}%` }} />
                            </div>
                            <span className="orch-lb-breakdown-count">{m.total}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* By Server */}
                  {lbStats.by_server && lbStats.by_server.length > 0 && (
                    <div className="orch-lb-breakdown">
                      <h4 className="orch-lb-chart-title">By Server</h4>
                      {lbStats.by_server.map((s, i) => {
                        const maxTotal = Math.max(...lbStats.by_server.map(x => x.total), 1);
                        return (
                          <div key={i} className="orch-lb-breakdown-row">
                            <span className="orch-lb-breakdown-name">{s.server || '—'}</span>
                            <div className="orch-lb-breakdown-bar-bg">
                              <div className="orch-lb-breakdown-bar bar-succeeded" style={{ width: `${(s.succeeded / maxTotal) * 100}%` }} />
                              <div className="orch-lb-breakdown-bar bar-failed" style={{ width: `${(s.failed / maxTotal) * 100}%`, position: 'absolute', left: `${(s.succeeded / maxTotal) * 100}%` }} />
                            </div>
                            <span className="orch-lb-breakdown-count">{s.total}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              ) : (
                <div className="orch-empty">Loading stats...</div>
              )}
            </div>
          ) : (
            /* ── Live Animated Diagram ── */
            <div className="orch-lb-diagram">
              {(() => {
                // Build origin, dispatcher, server data from recent events
                const origins = {};
                const servers = {};
                const recentEvents = lbEvents.slice(0, 200);
                recentEvents.forEach(ev => {
                  // For orchestrator calls, differentiate by lab name
                  let oKey = ev.caller_name || ev.caller_type || 'unknown';
                  let oName = oKey;
                  if (ev.caller_type === 'lab_orchestrator' && ev.lab_name) {
                    oKey = `orch-${ev.lab_id}`;
                    oName = `Orch · ${ev.lab_name}`;
                  } else if (ev.caller_type === 'lab_agent' && ev.lab_name) {
                    oName = `${ev.caller_name || 'Agent'}`;
                  }
                  if (!origins[oKey]) origins[oKey] = { name: oName, type: ev.caller_type, count: 0, lastActive: 0 };
                  origins[oKey].count++;
                  origins[oKey].lastActive = Math.max(origins[oKey].lastActive, new Date(ev.created_at).getTime());
                  if (ev.server_name) {
                    if (!servers[ev.server_name]) servers[ev.server_name] = { name: ev.server_name, provider: ev.provider_name || '', count: 0, lastActive: 0, totalDur: 0, durCount: 0 };
                    servers[ev.server_name].count++;
                    servers[ev.server_name].lastActive = Math.max(servers[ev.server_name].lastActive, new Date(ev.created_at).getTime());
                    if (ev.duration_ms > 0) { servers[ev.server_name].totalDur += ev.duration_ms; servers[ev.server_name].durCount++; }
                  }
                });
                const originList = Object.values(origins).sort((a, b) => b.lastActive - a.lastActive).slice(0, 8);
                const serverList = Object.values(servers).sort((a, b) => b.count - a.count).slice(0, 8);

                // Find "active" requests (dispatched but not yet responded in last 30s)
                const now = Date.now();
                const activeGroups = {};
                recentEvents.forEach(ev => {
                  const rid = ev.request_id || ev.id;
                  let originKey = ev.caller_name || ev.caller_type;
                  if (ev.caller_type === 'lab_orchestrator' && ev.lab_id) originKey = `orch-${ev.lab_id}`;
                  if (!activeGroups[rid]) activeGroups[rid] = { types: new Set(), origin: originKey, server: ev.server_name, time: new Date(ev.created_at).getTime() };
                  activeGroups[rid].types.add(ev.event_type);
                  if (ev.server_name) activeGroups[rid].server = ev.server_name;
                });
                const activeDots = Object.entries(activeGroups)
                  .filter(([, g]) => (now - g.time) < 30000)
                  .map(([rid, g]) => {
                    let phase = 'queue'; // at origin
                    if (g.types.has('response')) phase = 'response';
                    else if (g.types.has('failed')) phase = 'failed';
                    else if (g.types.has('dispatch')) phase = 'running';
                    return { rid, phase, origin: g.origin, server: g.server, age: now - g.time };
                  })
                  .filter(d => d.phase === 'running' || d.phase === 'queue' || d.age < 5000);

                const svgW = 800, svgH = Math.max(300, Math.max(originList.length, serverList.length) * 56 + 60);
                const dispX = svgW / 2, dispY = svgH / 2;
                const oX = 80, sX = svgW - 80;
                const oStartY = Math.max(40, (svgH - originList.length * 52) / 2);
                const sStartY = Math.max(40, (svgH - serverList.length * 52) / 2);

                return (
                  <svg viewBox={`0 0 ${svgW} ${svgH}`} className="orch-lb-diagram-svg" preserveAspectRatio="xMidYMid meet">
                    <defs>
                      <filter id="glow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
                      <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="rgba(255,255,255,0.08)"/><stop offset="50%" stopColor="rgba(255,255,255,0.15)"/><stop offset="100%" stopColor="rgba(255,255,255,0.08)"/></linearGradient>
                    </defs>

                    {/* Connection lines: origins → dispatcher */}
                    {originList.map((o, i) => {
                      const oy = oStartY + i * 52 + 20;
                      return <path key={`ol-${i}`} d={`M ${oX + 60} ${oy} C ${oX + 140} ${oy}, ${dispX - 80} ${dispY}, ${dispX - 40} ${dispY}`} fill="none" stroke="url(#lineGrad)" strokeWidth="1.5" />;
                    })}
                    {/* Connection lines: dispatcher → servers */}
                    {serverList.map((s, i) => {
                      const sy = sStartY + i * 52 + 20;
                      return <path key={`sl-${i}`} d={`M ${dispX + 40} ${dispY} C ${dispX + 80} ${dispY}, ${sX - 140} ${sy}, ${sX - 60} ${sy}`} fill="none" stroke="url(#lineGrad)" strokeWidth="1.5" />;
                    })}

                    {/* Animated dots for active requests */}
                    {activeDots.map((dot, di) => {
                      const oIdx = originList.findIndex(o => o.name === dot.origin);
                      const sIdx = serverList.findIndex(s => s.name === dot.server);
                      if (oIdx < 0) return null;
                      const oy = oStartY + oIdx * 52 + 20;
                      const sy = sIdx >= 0 ? sStartY + sIdx * 52 + 20 : dispY;
                      const color = dot.phase === 'response' ? '#22c55e' : dot.phase === 'failed' ? '#ef4444' : dot.phase === 'running' ? '#3b82f6' : '#fbbf24';
                      const dur = dot.phase === 'running' ? '2s' : dot.phase === 'response' ? '1.5s' : '1s';
                      if (dot.phase === 'queue') {
                        return (
                          <circle key={`dot-${di}`} r="4" fill={color} filter="url(#glow)" opacity="0.9">
                            <animateMotion dur="1.5s" repeatCount="1" fill="freeze" path={`M ${oX + 60} ${oy} C ${oX + 140} ${oy}, ${dispX - 80} ${dispY}, ${dispX - 40} ${dispY}`} />
                          </circle>
                        );
                      }
                      if (dot.phase === 'running' && sIdx >= 0) {
                        return (
                          <circle key={`dot-${di}`} r="4" fill={color} filter="url(#glow)" opacity="0.9">
                            <animateMotion dur={dur} repeatCount="indefinite" path={`M ${dispX + 40} ${dispY} C ${dispX + 80} ${dispY}, ${sX - 140} ${sy}, ${sX - 60} ${sy}`} />
                          </circle>
                        );
                      }
                      if (dot.phase === 'response' && sIdx >= 0) {
                        return (
                          <circle key={`dot-${di}`} r="4" fill={color} filter="url(#glow)" opacity="0.8">
                            <animateMotion dur="1.5s" repeatCount="1" fill="freeze" path={`M ${sX - 60} ${sy} C ${sX - 140} ${sy}, ${dispX + 80} ${dispY}, ${dispX - 40} ${dispY} C ${dispX - 80} ${dispY}, ${oX + 140} ${oy}, ${oX + 60} ${oy}`} />
                          </circle>
                        );
                      }
                      if (dot.phase === 'failed') {
                        const fx = sIdx >= 0 ? sX - 60 : dispX;
                        const fy = sIdx >= 0 ? sy : dispY;
                        return <circle key={`dot-${di}`} cx={fx} cy={fy} r="5" fill={color} filter="url(#glow)"><animate attributeName="r" values="4;7;4" dur="0.6s" repeatCount="3" /><animate attributeName="opacity" values="1;0.4;1" dur="0.6s" repeatCount="3" /></circle>;
                      }
                      return null;
                    })}

                    {/* Dispatcher (center) */}
                    <rect x={dispX - 40} y={dispY - 28} width="80" height="56" rx="10" fill="rgba(185,28,28,0.15)" stroke="rgba(185,28,28,0.4)" strokeWidth="1.5" />
                    <text x={dispX} y={dispY - 6} textAnchor="middle" fill="rgba(255,255,255,0.8)" fontSize="10" fontWeight="600">Dispatcher</text>
                    <text x={dispX} y={dispY + 10} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="8">LB Engine</text>
                    {lbStats?.summary?.queued > 0 && (
                      <g>
                        <circle cx={dispX + 30} cy={dispY - 22} r="9" fill="#b91c1c" />
                        <text x={dispX + 30} y={dispY - 18} textAnchor="middle" fill="white" fontSize="8" fontWeight="700">{lbStats.summary.queued}</text>
                      </g>
                    )}

                    {/* Origins (left) */}
                    {originList.map((o, i) => {
                      const y = oStartY + i * 52;
                      const isActive = (now - o.lastActive) < 10000;
                      return (
                        <g key={`o-${i}`}>
                          <rect x={oX - 55} y={y} width="115" height="40" rx="6" fill={isActive ? 'rgba(251,191,36,0.08)' : 'rgba(255,255,255,0.03)'} stroke={isActive ? 'rgba(251,191,36,0.25)' : 'rgba(255,255,255,0.08)'} strokeWidth="1" />
                          {isActive && <circle cx={oX - 45} cy={y + 20} r="3" fill="#fbbf24"><animate attributeName="opacity" values="1;0.3;1" dur="1.5s" repeatCount="indefinite"/></circle>}
                          <text x={oX} y={y + 17} textAnchor="middle" fill="rgba(255,255,255,0.75)" fontSize="9" fontWeight="500">{o.name.length > 16 ? o.name.slice(0, 14) + '…' : o.name}</text>
                          <text x={oX} y={y + 30} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="7">{o.count} reqs</text>
                        </g>
                      );
                    })}

                    {/* Servers (right) */}
                    {serverList.map((s, i) => {
                      const y = sStartY + i * 52;
                      const isActive = (now - s.lastActive) < 10000;
                      const avgMs = s.durCount > 0 ? Math.round(s.totalDur / s.durCount) : 0;
                      return (
                        <g key={`s-${i}`}>
                          <rect x={sX - 60} y={y} width="120" height="40" rx="6" fill={isActive ? 'rgba(34,197,94,0.06)' : 'rgba(255,255,255,0.03)'} stroke={isActive ? 'rgba(34,197,94,0.2)' : 'rgba(255,255,255,0.08)'} strokeWidth="1" />
                          {isActive && <circle cx={sX + 50} cy={y + 20} r="3" fill="#22c55e"><animate attributeName="opacity" values="1;0.3;1" dur="1.5s" repeatCount="indefinite"/></circle>}
                          <text x={sX} y={y + 16} textAnchor="middle" fill="rgba(255,255,255,0.75)" fontSize="9" fontWeight="500">{s.name.length > 16 ? s.name.slice(0, 14) + '…' : s.name}</text>
                          <text x={sX} y={y + 29} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="7">{s.provider} · {s.count} reqs{avgMs > 0 ? ` · ~${avgMs}ms` : ''}</text>
                        </g>
                      );
                    })}

                    {originList.length === 0 && serverList.length === 0 && (
                      <text x={svgW/2} y={svgH/2} textAnchor="middle" fill="rgba(255,255,255,0.25)" fontSize="12">No recent activity. Send a request to see the live diagram.</text>
                    )}
                  </svg>
                );
              })()}
            </div>
          )}
        </main>
      ) : (
      <main className="orch-chat">
        <div className="orch-chat-header">
          <div className="orch-chat-title">
            {IC.bot}
            <span>Chat</span>
            {allModelNames.length > 0 ? (
              <select
                className="orch-model-select"
                value={selectedModel || settings?.orchestrator_model || ''}
                onChange={e => setSelectedModel(e.target.value)}
              >
                {allModelNames.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            ) : settings ? (
              <span className="orch-model-badge">
                {settings.orchestrator_model} · {settings.orchestrator_provider}
              </span>
            ) : null}
            {agents.length > 0 && (
              <select
                className="orch-model-select"
                value={selectedAgent?.id || ''}
                onChange={e => {
                  const ag = agents.find(a => a.id === e.target.value);
                  setSelectedAgent(ag || null);
                }}
                title="Select an agent (optional)"
              >
                <option value="">No Agent</option>
                {agents.filter(a => a.is_active).map(a => (
                  <option key={a.id} value={a.id}>🤖 {a.name}{a.tools?.length ? ` (${a.tools.length} tools)` : ''}</option>
                ))}
              </select>
            )}
            <button
              className={`orch-context-toggle ${contextMode === 'full' ? 'active' : ''}`}
              onClick={() => setContextMode(prev => prev === 'minimal' ? 'full' : 'minimal')}
              title={contextMode === 'full'
                ? 'Full Context: history images included (for multi-image models)'
                : 'Minimal Context: only current images sent (safe for single-image models)'}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
                <circle cx="8.5" cy="8.5" r="1.5"/>
                <path d="M21 15l-5-5L5 21"/>
              </svg>
              {contextMode === 'full' ? 'Full Ctx' : 'Min Ctx'}
            </button>
          </div>
          <button
            className={`orch-btn-icon ${showActivity ? 'active' : ''}`}
            onClick={() => setShowActivity(!showActivity)}
            title="Toggle activity feed"
          >
            {IC.activity}
          </button>
        </div>

        <div className="orch-messages">
          {!activeConvId && (
            <div className="orch-welcome">
              <div className="orch-welcome-icon">{IC.bot}</div>
              <h2>Chat</h2>
              <p>AI Orchestrator — your command center for distributed AI tasks.</p>
              {providers.length === 0 && totalLiveModels === 0 ? (
                <p style={{marginTop:12, color:'rgba(255,255,255,0.4)'}}>
                  Waiting for agents to report Ollama models...<br/>
                  Or go to the <button style={{background:'none',border:'none',color:'var(--accent)',cursor:'pointer',textDecoration:'underline',fontSize:'inherit'}} onClick={() => setSidebarTab('models')}>Models tab</button> to add a provider manually.
                </p>
              ) : totalLiveModels > 0 && providers.length === 0 ? (
                <p style={{marginTop:12, color:'var(--success)'}}>
                  {totalLiveModels} model{totalLiveModels > 1 ? 's' : ''} detected! Providers will auto-sync shortly.
                </p>
              ) : (
                <p>Create a conversation and start asking.</p>
              )}
            </div>
          )}

          {messages.map(m => (
            <div key={m.id} className={`orch-msg orch-msg-${m.role}`}>
              <div className="orch-msg-avatar">
                {m.role === 'user' ? IC.user : IC.bot}
              </div>
              <div className="orch-msg-body">
                <div className="orch-msg-meta">
                  <span className="orch-msg-role">
                    {m.role === 'user' ? 'You' : m.agent_name || 'Orchestrator'}
                  </span>
                  <span className="orch-msg-time">{formatTime(m.created_at)}</span>
                  {m.model_used && (
                    <span className="orch-msg-model">{m.model_used}</span>
                  )}
                  {m.tokens_out > 0 && (
                    <span className="orch-msg-tokens">
                      {m.tokens_in}→{m.tokens_out} tokens · {m.duration_ms}ms
                    </span>
                  )}
                </div>
                <div
                  className="orch-msg-content"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                />
                {/* Show attached images in user messages */}
                {m.extra?.images?.length > 0 && (
                  <div className="orch-msg-images">
                    {m.extra.images.map((img, i) => (
                      <img key={i} src={img} alt={`attachment ${i + 1}`} className="orch-msg-image" />
                    ))}
                  </div>
                )}
                {/* Audio player (riffusion / media pipeline) */}
                {(m.extra?.audio || m.extra?.riffusion?.audio) && (
                  <div className="orch-msg-audio">
                    {(m.extra.image || m.extra.riffusion?.image) && (
                      <img src={m.extra.image || m.extra.riffusion.image} alt="spectrogram" className="orch-audio-spectrogram" />
                    )}
                    <audio controls src={m.extra.audio || m.extra.riffusion.audio} />
                  </div>
                )}
                {/* Video player (LTX / Wan video pipeline) */}
                {m.extra?.video && (
                  <div className="orch-msg-video">
                    <video controls width="100%" style={{ maxWidth: 640, borderRadius: 8 }}
                      src={`data:video/mp4;base64,${m.extra.video}`} />
                  </div>
                )}
                {/* Tool calls display in stored messages */}
                {m.extra?.tool_calls?.length > 0 && (
                  <div className="orch-tool-calls">
                    {m.extra.tool_calls.map((tc, i) => (
                      <div key={i} className="orch-tool-call-item">
                        <span className="orch-tool-name">🔧 {tc.name}</span>
                        <code className="orch-tool-args">{JSON.stringify(tc.arguments || {}, null, 0).slice(0, 200)}</code>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Streaming indicator */}
          {streaming && (
            <div className="orch-msg orch-msg-assistant">
              <div className="orch-msg-avatar">{IC.bot}</div>
              <div className="orch-msg-body">
                <div className="orch-msg-meta">
                  <span className="orch-msg-role">{selectedAgent?.name || 'Orchestrator'}</span>
                  {IC.loader}
                </div>
                {/* Live tool events */}
                {toolEvents.length > 0 && (
                  <div className="orch-tool-calls">
                    {toolEvents.map((evt, i) => (
                      <div key={i} className="orch-tool-call-item">
                        {evt.tool_call && (
                          <>
                            <span className="orch-tool-name">🔧 {evt.tool_call.name}</span>
                            <code className="orch-tool-args">{JSON.stringify(evt.tool_call.arguments || {}, null, 0).slice(0, 200)}</code>
                          </>
                        )}
                        {evt.tool_result && (
                          <>
                            <span className={`orch-tool-result ${evt.tool_result.success ? 'success' : 'fail'}`}>
                              {evt.tool_result.success ? '✅' : '❌'} {evt.tool_result.name}
                            </span>
                            <code className="orch-tool-output">{(evt.tool_result.output || '').slice(0, 300)}</code>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <div
                  className="orch-msg-content"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingText || '▊') }}
                />
                {/* Streaming audio player (riffusion) */}
                {streamingAudio?.audio && (
                  <div className="orch-msg-audio">
                    {streamingAudio.image && (
                      <img src={streamingAudio.image} alt="spectrogram" className="orch-audio-spectrogram" />
                    )}
                    <audio controls src={streamingAudio.audio} />
                  </div>
                )}
                {/* Streaming video player (LTX / Wan) */}
                {streamingAudio?.video && (
                  <div className="orch-msg-video">
                    <video controls width="100%" style={{ maxWidth: 640, borderRadius: 8 }}
                      src={`data:video/mp4;base64,${streamingAudio.video}`} />
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="orch-input-area">
          {/* Tools selection panel */}
          {showToolsPanel && (
            <div className="orch-tools-panel">
              <div className="orch-tools-panel-header">
                <span>🔧 Tools</span>
                <span className="orch-tools-count">{conversationTools.length} selected</span>
                <button className="orch-tools-panel-close" onClick={() => setShowToolsPanel(false)}>&times;</button>
              </div>
              {toolSets.length > 0 && (
                <div className="orch-tools-panel-sets">
                  <select defaultValue="" onChange={e => {
                    if (!e.target.value) return;
                    const ts = toolSets.find(t => t.id === e.target.value);
                    if (ts) {
                      const merged = [...new Set([...conversationTools, ...(ts.tools || [])])];
                      setConversationTools(merged);
                      if (activeConvId) updateConversation(activeConvId, { tools: merged }).catch(() => {});
                    }
                    e.target.value = '';
                  }}>
                    <option value="">+ Add tool set…</option>
                    {toolSets.map(ts => (
                      <option key={ts.id} value={ts.id}>{ts.name} ({(ts.tools || []).length} tools)</option>
                    ))}
                  </select>
                  {conversationTools.length > 0 && (
                    <button className="orch-tools-clear" onClick={() => {
                      setConversationTools([]);
                      if (activeConvId) updateConversation(activeConvId, { tools: [] }).catch(() => {});
                    }}>Clear all</button>
                  )}
                </div>
              )}
              <div className="orch-tools-grid">
                {builtinTools.map(t => {
                  if (t.subTools) {
                    return <OrchSubToolGroup key={t.name} toolDef={t} tools={conversationTools}
                      onChange={next => {
                        setConversationTools(next);
                        if (activeConvId) updateConversation(activeConvId, { tools: next }).catch(() => {});
                      }} />;
                  }
                  return (
                  <label key={t.name} className="orch-tool-toggle">
                    <input
                      type="checkbox"
                      checked={conversationTools.includes(t.name)}
                      onChange={() => {
                        const next = conversationTools.includes(t.name)
                          ? conversationTools.filter(x => x !== t.name)
                          : [...conversationTools, t.name];
                        setConversationTools(next);
                        if (activeConvId) updateConversation(activeConvId, { tools: next }).catch(() => {});
                      }}
                    />
                    <span className="orch-tool-toggle-info">
                      <span className="orch-tool-toggle-name">{t.name}<SensitiveToolTag tool={t} /></span>
                      <span className="orch-tool-toggle-desc">{t.description}</span>
                    </span>
                  </label>
                  );
                })}
              </div>
            </div>
          )}
          {/* Image preview strip */}
          {attachedImages.length > 0 && (
            <div className="orch-attach-preview">
              {attachedImages.map((img, i) => (
                <div key={i} className="orch-attach-thumb">
                  <img src={img.dataUrl} alt={img.name} />
                  <button className="orch-attach-remove" onClick={() => removeAttachedImage(i)}>&times;</button>
                </div>
              ))}
            </div>
          )}
          <div className="orch-input-row">
            <input
              type="file"
              ref={fileInputRef}
              accept="image/*"
              multiple
              style={{ display: 'none' }}
              onChange={handleImageAttach}
            />
            <button
              className="orch-attach-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={streaming}
              title="Attach images"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            </button>
            <button
              className={`orch-attach-btn ${conversationTools.length > 0 ? 'orch-tools-active' : ''}`}
              onClick={() => setShowToolsPanel(p => !p)}
              disabled={streaming}
              title={`Tools${conversationTools.length ? ` (${conversationTools.length})` : ''}`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              {conversationTools.length > 0 && <span className="orch-tools-badge">{conversationTools.length}</span>}
            </button>
            <textarea
              ref={inputRef}
              className="orch-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeConvId ? "Type your message... (Enter to send, Shift+Enter for new line)" : "Create a conversation first..."}
              rows={1}
              disabled={streaming}
            />
            <button
              className="orch-send-btn"
              onClick={handleSend}
              disabled={streaming || (!input.trim() && !attachedImages.length)}
            >
              {streaming ? IC.loader : IC.send}
            </button>
          </div>
        </div>
      </main>
      )}

      {/* ── Right Panel: Activity Feed / I/O Log ────────── */}
      {showActivity && (
        <aside className="orch-activity">
          {sidebarTab === 'models' ? (
            <>
              <div className="orch-activity-header">
                <h3>I/O Log</h3>
              </div>
              <div className="orch-activity-list orch-io-log">
                {(() => {
                  // Show dispatch (input) and response (output) events that have I/O data
                  const ioEvents = lbEvents
                    .filter(ev => (ev.has_input && ev.event_type === 'dispatch') || (ev.has_output && ev.event_type === 'response'))
                    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
                  if (ioEvents.length === 0) return <div className="orch-empty">No I/O events yet. Run a model to see prompts and responses here.</div>;
                  return ioEvents.map((ev, i) => {
                    const isInput = ev.event_type === 'dispatch';
                    const detail = eventDetails[ev.id];
                    const isOpen = expandedIO[ev.id];
                    return (
                      <div key={ev.id || i} className={`orch-io-entry ${isInput ? 'orch-io-input' : 'orch-io-output'}`}>
                        <div className="orch-io-entry-header" onClick={() => toggleEventIO(ev.id)}>
                          <span className={`orch-io-direction ${isInput ? 'input' : 'output'}`}>
                            {isInput ? 'Input' : 'Output'}
                          </span>
                          <span className="orch-io-model">{ev.model_identifier || '—'}</span>
                          <span className="orch-io-time">{new Date(ev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                          <span className="orch-io-toggle">{isOpen ? '▾' : '▸'}</span>
                        </div>
                        {isOpen && (
                          <div className="orch-io-entry-body">
                            {detail ? (
                              isInput && detail.input_messages ? (
                                <div className="orch-io-messages-list">
                                  <div className="orch-io-msg-count">Prompt ({detail.input_messages.length} messages)</div>
                                  {detail.input_messages.map((msg, mi) => (
                                    <div key={mi} className={`orch-io-msg-item orch-io-msg-${msg.role}`}>
                                      <span className={`orch-io-msg-role ${msg.role}`}>{msg.role}</span>
                                      <pre className="orch-io-msg-text">{typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}</pre>
                                    </div>
                                  ))}
                                </div>
                              ) : !isInput && detail.output_content ? (
                                <pre className="orch-io-response-text">{detail.output_content}</pre>
                              ) : (
                                <div className="orch-empty" style={{ padding: 6, fontSize: '0.68rem' }}>No data</div>
                              )
                            ) : (
                              <div className="orch-empty" style={{ padding: 6, fontSize: '0.68rem' }}>Loading...</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  });
                })()}
              </div>
            </>
          ) : (
            <>
          <div className="orch-activity-header">
            <h3>Activity Feed</h3>
            <select
              className="orch-activity-filter"
              value={activityFilter}
              onChange={e => setActivityFilter(e.target.value)}
            >
              <option value="all">All Conversations</option>
              {activeConvId && <option value="conversation">Current Only</option>}
            </select>
          </div>
          <div className="orch-activity-list">
            {activity.map(item => (
              <div key={item.id} className={`orch-activity-item orch-activity-${item.type}`}>
                <div className="orch-activity-time">{formatTime(item.timestamp)}</div>
                {item.type === 'message' ? (
                  <div className="orch-activity-body">
                    <span className={`orch-activity-role ${item.role}`}>{item.role}</span>
                    <span className="orch-activity-text">{item.content}</span>
                  </div>
                ) : (
                  <div className="orch-activity-body">
                    <span className={`orch-activity-status ${item.task_status}`}>
                      {item.task_type}
                    </span>
                    <span className={`orch-activity-badge ${item.task_status}`}>
                      {item.task_status}
                    </span>
                    {item.task_error && (
                      <span className="orch-activity-error">{item.task_error}</span>
                    )}
                  </div>
                )}
              </div>
            ))}
            {activity.length === 0 && (
              <div className="orch-empty">No activity yet.</div>
            )}
          </div>
            </>
          )}
        </aside>
      )}

      <style>{orchStyles}</style>
      </div>
    </div>
  );
}

/* ── Orchestrator page styles ─────────────────── */
const orchStyles = `
        .orch-layout {
          display: flex;
          height: 100vh;
          margin: -1.5rem -2rem;
          background: var(--bg-primary, #1c1917);
          color: var(--text-primary, #f5f5f4);
          overflow: hidden;
          position: relative;
        }
        .orch-layout.orch-layout-fullwidth {
          flex-direction: column;
        }

        /* ── Unified Top Tab Bar ─── */
        .orch-topbar {
          display: flex;
          background: var(--bg-card, #292524);
          border-bottom: 1px solid rgba(255,255,255,0.06);
          flex-shrink: 0;
        }
        .orch-topbar-body {
          flex: 1;
          display: flex;
          overflow: hidden;
        }

        /* ── Scrollbar (webkit / Chrome / Brave) ─── */
        * {
          scrollbar-width: thin;
          scrollbar-color: rgba(255,255,255,0.15) transparent;
        }
        *::-webkit-scrollbar {
          width: 6px;
          height: 6px;
        }
        *::-webkit-scrollbar-track {
          background: transparent;
        }
        *::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.15);
          border-radius: 3px;
        }
        *::-webkit-scrollbar-thumb:hover {
          background: rgba(255,255,255,0.25);
        }

        /* ── Left Sidebar ─── */
        .orch-sidebar {
          width: 300px;
          min-width: 300px;
          background: var(--bg-card, #292524);
          border-right: 1px solid rgba(255,255,255,0.06);
          display: flex;
          flex-direction: column;
        }
        .orch-tab {
          flex: none;
          padding: 10px 20px;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          color: rgba(255,255,255,0.4);
          cursor: pointer;
          font-size: 0.78rem;
          font-weight: 500;
          transition: all 0.15s;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 4px;
        }
        .orch-tab:hover { color: rgba(255,255,255,0.7); }
        .orch-tab.active {
          color: var(--accent, #b91c1c);
          border-bottom-color: var(--accent, #b91c1c);
        }
        .orch-tab-badge {
          background: var(--accent, #b91c1c);
          color: white;
          font-size: 0.6rem;
          padding: 1px 5px;
          border-radius: 8px;
          font-weight: 700;
        }
        .orch-sidebar-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .orch-sidebar-header h2 {
          font-size: 0.95rem;
          font-weight: 600;
          margin: 0;
        }
        .orch-conv-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        .orch-date-label {
          font-size: 0.7rem;
          text-transform: uppercase;
          color: rgba(255,255,255,0.35);
          padding: 12px 8px 4px;
          letter-spacing: 0.05em;
        }
        .orch-conv-item {
          padding: 10px 12px;
          border-radius: var(--radius, 8px);
          cursor: pointer;
          position: relative;
          margin-bottom: 2px;
          transition: background 0.15s;
        }
        .orch-conv-item:hover {
          background: rgba(255,255,255,0.05);
        }
        .orch-conv-item.active {
          background: rgba(185, 28, 28, 0.15);
          border-left: 3px solid var(--accent, #b91c1c);
        }
        .orch-conv-title {
          font-size: 0.85rem;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          padding-right: 24px;
        }
        .orch-conv-preview {
          font-size: 0.72rem;
          color: rgba(255,255,255,0.4);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          margin-top: 2px;
        }
        .orch-conv-delete {
          position: absolute;
          right: 8px;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          color: rgba(255,255,255,0.2);
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
          opacity: 0;
          transition: all 0.15s;
        }
        .orch-conv-item:hover .orch-conv-delete {
          opacity: 1;
        }
        .orch-conv-delete:hover {
          color: var(--error, #ef4444);
          background: rgba(239,68,68,0.1);
        }

        /* ── Panel scroll (models + config tabs) ─── */
        .orch-panel-scroll {
          flex: 1;
          overflow-y: auto;
          padding: 12px;
        }
        .orch-section-title {
          font-size: 0.72rem;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: rgba(255,255,255,0.4);
          padding: 8px 4px 6px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .orch-default-model-section {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px;
          padding: 10px 12px 8px;
          margin-bottom: 12px;
        }
        .orch-default-model-section .orch-section-title { padding: 0 0 6px; }
        .orch-default-model-select { width: 100%; }
        .orch-default-model-hint {
          font-size: 0.65rem;
          color: rgba(255,255,255,0.3);
          margin-top: 4px;
        }
        .orch-model-server {
          margin-bottom: 12px;
        }
        .orch-model-server-name {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.78rem;
          font-weight: 600;
          padding: 4px 0;
          color: rgba(255,255,255,0.7);
        }
        .orch-model-row {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 5px 8px;
          border-radius: 4px;
          font-size: 0.75rem;
          background: rgba(255,255,255,0.03);
          margin-bottom: 2px;
        }
        .orch-model-row:hover {
          background: rgba(255,255,255,0.06);
        }
        .orch-model-name {
          flex: 1;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .orch-model-info {
          display: flex;
          gap: 6px;
          font-size: 0.65rem;
          color: rgba(255,255,255,0.35);
        }
        .orch-model-available {
          color: var(--success, #22c55e);
          flex-shrink: 0;
        }
        .orch-model-status {
          font-size: 0.65rem;
          font-weight: 500;
          padding: 1px 5px;
          border-radius: 6px;
        }
        .orch-model-status.available {
          background: rgba(34,197,94,0.15);
          color: var(--success, #22c55e);
        }
        .orch-model-status.unavailable {
          background: rgba(255,255,255,0.06);
          color: rgba(255,255,255,0.3);
        }
        .orch-server-count-tag {
          font-size: 0.6rem;
          font-weight: 600;
          padding: 1px 6px;
          border-radius: 8px;
          letter-spacing: 0.5px;
        }
        .orch-server-count-tag.all-up {
          background: rgba(34,197,94,0.15);
          color: #22c55e;
        }
        .orch-server-count-tag.partial {
          background: rgba(251,191,36,0.15);
          color: #fbbf24;
        }
        .orch-server-count-tag.all-down {
          background: rgba(239,68,68,0.15);
          color: #ef4444;
        }

        /* ── Config panel ─── */
        .orch-config-group {
          margin-bottom: 10px;
        }
        .orch-config-group label {
          display: block;
          font-size: 0.7rem;
          color: rgba(255,255,255,0.45);
          margin-bottom: 3px;
          font-weight: 500;
        }
        .orch-select, .orch-input-sm {
          width: 100%;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: var(--text-primary);
          font-size: 0.78rem;
          padding: 6px 8px;
          border-radius: 4px;
          outline: none;
          font-family: inherit;
          box-sizing: border-box;
        }
        .orch-select:focus, .orch-input-sm:focus {
          border-color: var(--accent, #b91c1c);
        }
        .orch-add-provider {
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 10px;
          background: rgba(255,255,255,0.03);
          border-radius: 6px;
          margin-bottom: 10px;
        }
        .orch-add-provider-actions {
          display: flex;
          gap: 6px;
        }
        .orch-btn-primary {
          background: var(--accent, #b91c1c);
          color: white;
          border: none;
          padding: 5px 12px;
          border-radius: 4px;
          font-size: 0.75rem;
          cursor: pointer;
          font-weight: 500;
        }
        .orch-btn-primary:hover { opacity: 0.85; }
        .orch-btn-ghost {
          background: none;
          color: rgba(255,255,255,0.5);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 5px 12px;
          border-radius: 4px;
          font-size: 0.75rem;
          cursor: pointer;
        }
        .orch-btn-ghost:hover { background: rgba(255,255,255,0.05); }
        .orch-btn-sm {
          background: none;
          border: 1px solid rgba(255,255,255,0.1);
          color: rgba(255,255,255,0.6);
          padding: 3px 8px;
          border-radius: 4px;
          font-size: 0.68rem;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 3px;
          transition: all 0.15s;
        }
        .orch-btn-sm:hover { background: rgba(255,255,255,0.06); }
        .orch-btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
        .orch-btn-danger:hover {
          border-color: var(--error, #ef4444);
          color: var(--error, #ef4444);
          background: rgba(239,68,68,0.1);
        }
        .orch-provider-card {
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 6px;
          padding: 10px;
          margin-bottom: 6px;
        }
        .orch-provider-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 2px;
        }
        .orch-provider-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          padding-left: 20px;
          margin-bottom: 2px;
        }
        .orch-provider-name {
          font-size: 0.8rem;
          font-weight: 600;
        }
        .orch-provider-type {
          font-size: 0.62rem;
          padding: 1px 6px;
          border-radius: 8px;
          font-weight: 600;
          text-transform: uppercase;
        }
        .orch-provider-type.ollama { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-provider-type.huggingface { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .orch-provider-type.openai { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-provider-type.toolai { background: rgba(168,85,247,0.15); color: #a855f7; }
        .orch-provider-type.riffusion { background: rgba(236,72,153,0.15); color: #ec4899; }
        .orch-provider-type.musicgen { background: rgba(251,146,60,0.15); color: #fb923c; }
        .orch-provider-type.comfyui { background: rgba(99,179,237,0.15); color: #63b3ed; }
        .orch-provider-type.bark { background: rgba(52,211,153,0.15); color: #34d399; }
        .orch-provider-type.rvc { background: rgba(129,140,248,0.15); color: #818cf8; }
        .orch-provider-type.coqui_tts { background: rgba(244,114,182,0.15); color: #f472b6; }
        .orch-provider-url {
          font-size: 0.68rem;
          color: rgba(255,255,255,0.35);
          margin-bottom: 8px;
          word-break: break-all;
        }
        .orch-provider-actions {
          display: flex;
          gap: 4px;
          flex-wrap: wrap;
        }

        /* ── Provider expand/status ─── */
        .orch-expand-arrow {
          display: inline-flex;
          transition: transform 0.15s;
          color: rgba(255,255,255,0.35);
          flex-shrink: 0;
        }
        .orch-expand-arrow.expanded {
          transform: rotate(90deg);
        }
        .orch-status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .orch-status-dot.online {
          background: var(--success, #22c55e);
          box-shadow: 0 0 4px rgba(34,197,94,0.5);
        }
        .orch-status-dot.offline {
          background: rgba(255,255,255,0.2);
        }
        .orch-provider-expanded {
          padding-top: 8px;
          border-top: 1px solid rgba(255,255,255,0.06);
          margin-top: 8px;
        }
        .orch-model-count {
          font-size: 0.58rem;
          background: rgba(255,255,255,0.1);
          color: rgba(255,255,255,0.6);
          padding: 0 5px;
          border-radius: 8px;
          font-weight: 600;
          line-height: 1.5;
          flex-shrink: 0;
        }
        .orch-provider-server {
          font-size: 0.66rem;
          color: rgba(255,255,255,0.4);
          margin-bottom: 6px;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .orch-provider-models {
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid rgba(255,255,255,0.04);
        }
        .orch-provider-models-title {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.4);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          font-weight: 600;
          margin-bottom: 4px;
        }
        .orch-provider-tag-group {
          display: inline-flex;
          align-items: center;
          gap: 3px;
        }
        .orch-status-dot-sm {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .orch-status-dot-sm.online {
          background: var(--success, #22c55e);
          box-shadow: 0 0 3px rgba(34,197,94,0.5);
        }
        .orch-status-dot-sm.offline {
          background: rgba(255,255,255,0.2);
        }
        .orch-sub-provider {
          padding: 8px 0;
          border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .orch-sub-provider:last-child {
          border-bottom: none;
        }
        .orch-sub-provider-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
        }

        /* ── Model selector in chat header ─── */
        .orch-model-select {
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
          border: 1px solid rgba(185,28,28,0.3);
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 0.7rem;
          font-weight: 500;
          cursor: pointer;
          outline: none;
          max-width: 220px;
        }
        .orch-model-select:focus {
          border-color: var(--accent, #b91c1c);
        }
        .orch-model-select option {
          background: var(--bg-card, #292524);
          color: var(--text-primary);
        }

        /* ── Context mode toggle ─── */
        .orch-context-toggle {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(255,255,255,0.06);
          color: var(--text-secondary, #a8a29e);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 0.65rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
          white-space: nowrap;
        }
        .orch-context-toggle:hover {
          border-color: rgba(255,255,255,0.2);
          color: var(--text-primary);
        }
        .orch-context-toggle.active {
          background: rgba(59,130,246,0.2);
          color: #60a5fa;
          border-color: rgba(59,130,246,0.4);
        }

        /* ── Chat Area ─── */
        .orch-chat {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
        }
        .orch-chat-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 20px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
          background: var(--bg-card, #292524);
        }
        .orch-chat-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-weight: 600;
          font-size: 1rem;
        }
        .orch-model-badge {
          font-size: 0.7rem;
          font-weight: 400;
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
          padding: 2px 8px;
          border-radius: 12px;
        }
        .orch-messages {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .orch-welcome {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          flex: 1;
          opacity: 0.5;
          text-align: center;
        }
        .orch-welcome-icon {
          margin-bottom: 12px;
          opacity: 0.6;
        }
        .orch-welcome-icon svg {
          width: 48px;
          height: 48px;
        }
        .orch-welcome h2 {
          margin: 0 0 8px;
          font-size: 1.3rem;
        }
        .orch-welcome p {
          margin: 2px 0;
          font-size: 0.85rem;
        }

        /* ── Messages ─── */
        .orch-msg {
          display: flex;
          gap: 12px;
          max-width: 85%;
          animation: orchFadeIn 0.2s ease;
        }
        .orch-msg-user {
          align-self: flex-end;
          flex-direction: row-reverse;
        }
        .orch-msg-avatar {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .orch-msg-user .orch-msg-avatar {
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
        }
        .orch-msg-assistant .orch-msg-avatar,
        .orch-msg-system .orch-msg-avatar {
          background: rgba(255,255,255,0.1);
          color: var(--text-primary);
        }
        .orch-msg-body {
          background: var(--bg-card, #292524);
          border-radius: var(--radius, 8px);
          padding: 10px 14px;
          min-width: 80px;
        }
        .orch-msg-user .orch-msg-body {
          background: rgba(185,28,28,0.15);
        }
        .orch-msg-meta {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
          flex-wrap: wrap;
        }
        .orch-msg-role {
          font-size: 0.72rem;
          font-weight: 600;
          text-transform: uppercase;
          color: rgba(255,255,255,0.5);
        }
        .orch-msg-time {
          font-size: 0.65rem;
          color: rgba(255,255,255,0.25);
        }
        .orch-msg-model {
          font-size: 0.62rem;
          background: rgba(255,255,255,0.08);
          padding: 1px 6px;
          border-radius: 8px;
          color: rgba(255,255,255,0.4);
        }
        .orch-msg-tokens {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.25);
        }
        .orch-msg-content {
          font-size: 0.88rem;
          line-height: 1.55;
          word-break: break-word;
        }
        .orch-msg-content h2, .orch-msg-content h3, .orch-msg-content h4 {
          margin: 8px 0 4px;
          font-size: 0.95rem;
        }
        .orch-msg-content ul {
          margin: 4px 0;
          padding-left: 20px;
        }
        .orch-msg-content li {
          margin: 2px 0;
        }
        .orch-code {
          background: rgba(0,0,0,0.3);
          border-radius: 6px;
          padding: 10px 12px;
          font-size: 0.8rem;
          overflow-x: auto;
          margin: 6px 0;
        }
        .orch-inline-code {
          background: rgba(0,0,0,0.25);
          padding: 1px 5px;
          border-radius: 4px;
          font-size: 0.82rem;
        }

        /* ── Tool Calls ─── */
        .orch-tool-calls {
          margin-top: 6px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .orch-tool-call-item {
          background: rgba(0,0,0,0.25);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 6px;
          padding: 6px 10px;
          font-size: 0.78rem;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .orch-tool-name {
          font-weight: 600;
          color: var(--accent, #b91c1c);
        }
        .orch-tool-args {
          font-size: 0.72rem;
          color: rgba(255,255,255,0.4);
          word-break: break-all;
          background: none;
          padding: 0;
        }
        .orch-tool-result {
          font-weight: 600;
        }
        .orch-tool-result.success { color: var(--success, #22c55e); }
        .orch-tool-result.fail { color: var(--danger, #ef4444); }
        .orch-tool-output {
          font-size: 0.7rem;
          color: rgba(255,255,255,0.35);
          word-break: break-all;
          white-space: pre-wrap;
          max-height: 120px;
          overflow-y: auto;
          background: none;
          padding: 0;
        }

        /* ── Tools panel ── */
        .orch-tools-panel {
          background: rgba(0,0,0,0.4);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 10px;
          padding: 10px 14px;
          margin-bottom: 8px;
          max-height: 300px;
          overflow-y: auto;
        }
        .orch-tools-panel-header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.78rem;
          font-weight: 600;
          margin-bottom: 8px;
        }
        .orch-tools-count {
          font-weight: 400;
          color: var(--accent, #b91c1c);
          font-size: 0.7rem;
        }
        .orch-tools-panel-close {
          margin-left: auto;
          background: none;
          border: none;
          color: rgba(255,255,255,0.4);
          font-size: 1rem;
          cursor: pointer;
        }
        .orch-tools-panel-close:hover { color: #fff; }
        .orch-tools-panel-sets {
          display: flex;
          gap: 8px;
          align-items: center;
          margin-bottom: 8px;
        }
        .orch-tools-panel-sets select {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 6px;
          color: #e0e0e0;
          padding: 4px 8px;
          font-size: 0.72rem;
          cursor: pointer;
        }
        .orch-tools-clear {
          background: none;
          border: none;
          color: rgba(255,255,255,0.3);
          font-size: 0.68rem;
          cursor: pointer;
          text-decoration: underline;
        }
        .orch-tools-clear:hover { color: #fff; }
        .orch-tools-grid {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .orch-tool-toggle {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 4px 0;
          cursor: pointer;
          font-size: 0.72rem;
          color: rgba(255,255,255,0.6);
        }
        .orch-tool-toggle:hover { background: rgba(255,255,255,0.04); border-radius: 4px; }
        .orch-tool-toggle input[type="checkbox"] { accent-color: var(--accent, #b91c1c); margin-top: 2px; flex-shrink: 0; width: 14px; height: 14px; }
        .orch-tool-toggle-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
        .orch-tool-toggle-name { font-weight: 600; font-size: 0.72rem; color: rgba(255,255,255,0.8); }
        .orch-tool-toggle-desc { font-size: 0.62rem; color: rgba(255,255,255,0.35); line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .orch-tools-active {
          border-color: var(--accent, #b91c1c) !important;
          color: var(--accent, #b91c1c) !important;
          position: relative;
        }
        .orch-tools-badge {
          position: absolute;
          top: -4px;
          right: -4px;
          background: var(--accent, #b91c1c);
          color: white;
          font-size: 0.55rem;
          min-width: 14px;
          height: 14px;
          border-radius: 7px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
        }

        /* ── Input ─── */
        .orch-input-area {
          display: flex;
          flex-direction: column;
          gap: 0;
          padding: 12px 20px 16px;
          border-top: 1px solid rgba(255,255,255,0.06);
          background: var(--bg-card, #292524);
        }
        .orch-input-row {
          display: flex;
          align-items: flex-end;
          gap: 8px;
        }
        .orch-attach-btn {
          background: none;
          border: 1px solid rgba(255,255,255,0.12);
          border-radius: var(--radius, 8px);
          color: var(--text-secondary, #a8a29e);
          width: 42px;
          height: 42px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: border-color 0.15s, color 0.15s;
          flex-shrink: 0;
        }
        .orch-attach-btn:hover:not(:disabled) {
          border-color: var(--accent, #b91c1c);
          color: var(--text-primary);
        }
        .orch-attach-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .orch-attach-preview {
          display: flex;
          gap: 8px;
          padding: 8px 0;
          overflow-x: auto;
        }
        .orch-attach-thumb {
          position: relative;
          flex-shrink: 0;
        }
        .orch-attach-thumb img {
          width: 64px;
          height: 64px;
          object-fit: cover;
          border-radius: 6px;
          border: 1px solid rgba(255,255,255,0.1);
        }
        .orch-attach-remove {
          position: absolute;
          top: -4px;
          right: -4px;
          background: var(--accent, #b91c1c);
          border: none;
          border-radius: 50%;
          color: white;
          width: 18px;
          height: 18px;
          font-size: 12px;
          line-height: 1;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .orch-msg-images {
          display: flex;
          gap: 8px;
          margin-top: 8px;
          flex-wrap: wrap;
        }
        .orch-msg-image {
          max-width: 200px;
          max-height: 200px;
          object-fit: contain;
          border-radius: 6px;
          border: 1px solid rgba(255,255,255,0.1);
          cursor: pointer;
        }
        .orch-msg-image:hover {
          border-color: var(--accent, #b91c1c);
        }
        .orch-msg-audio {
          margin-top: 10px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .orch-audio-spectrogram {
          max-width: 400px;
          height: 80px;
          object-fit: cover;
          border-radius: 6px;
          border: 1px solid rgba(255,255,255,0.1);
        }
        .orch-msg-audio audio {
          width: 100%;
          max-width: 400px;
          height: 36px;
        }
        .orch-input {
          flex: 1;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: var(--radius, 8px);
          padding: 10px 14px;
          color: var(--text-primary);
          font-size: 0.88rem;
          resize: none;
          min-height: 42px;
          max-height: 120px;
          font-family: inherit;
          outline: none;
          transition: border-color 0.15s;
        }
        .orch-input:focus {
          border-color: var(--accent, #b91c1c);
        }
        .orch-send-btn {
          background: var(--accent, #b91c1c);
          border: none;
          border-radius: var(--radius, 8px);
          color: white;
          width: 42px;
          height: 42px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: opacity 0.15s;
          flex-shrink: 0;
        }
        .orch-send-btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .orch-send-btn:not(:disabled):hover {
          opacity: 0.85;
        }

        /* ── Activity Panel ─── */
        .orch-activity {
          width: 300px;
          min-width: 300px;
          background: var(--bg-card, #292524);
          border-left: 1px solid rgba(255,255,255,0.06);
          display: flex;
          flex-direction: column;
        }
        .orch-activity-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 14px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .orch-activity-header h3 {
          font-size: 0.85rem;
          font-weight: 600;
          margin: 0;
        }
        .orch-activity-filter {
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: var(--text-primary);
          font-size: 0.7rem;
          padding: 3px 6px;
          border-radius: 4px;
          cursor: pointer;
        }
        .orch-activity-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }
        .orch-activity-item {
          padding: 8px 10px;
          border-radius: 6px;
          margin-bottom: 4px;
          border-left: 3px solid transparent;
        }
        .orch-activity-message {
          border-left-color: rgba(255,255,255,0.15);
        }
        .orch-activity-task {
          border-left-color: var(--accent, #b91c1c);
        }
        .orch-activity-time {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.25);
          margin-bottom: 2px;
        }
        .orch-activity-body {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }
        .orch-activity-role {
          font-size: 0.68rem;
          font-weight: 600;
          text-transform: uppercase;
        }
        .orch-activity-role.user { color: var(--accent); }
        .orch-activity-role.assistant { color: var(--success, #22c55e); }
        .orch-activity-text {
          font-size: 0.72rem;
          color: rgba(255,255,255,0.5);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 200px;
        }
        .orch-activity-status {
          font-size: 0.68rem;
          font-weight: 500;
        }
        .orch-activity-badge {
          font-size: 0.6rem;
          padding: 1px 5px;
          border-radius: 8px;
          font-weight: 600;
        }
        .orch-activity-badge.queued { background: rgba(251,191,36,0.15); color: var(--warning, #fbbf24); }
        .orch-activity-badge.running { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-activity-badge.completed { background: rgba(34,197,94,0.15); color: var(--success, #22c55e); }
        .orch-activity-badge.failed { background: rgba(239,68,68,0.15); color: var(--error, #ef4444); }
        .orch-activity-error {
          font-size: 0.65rem;
          color: var(--error, #ef4444);
          width: 100%;
        }

        /* ── I/O Log (Models tab right panel) ─── */
        .orch-io-log {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .orch-io-entry {
          border-radius: 6px;
          border-left: 3px solid transparent;
          overflow: hidden;
        }
        .orch-io-entry.orch-io-input { border-left-color: #3b82f6; }
        .orch-io-entry.orch-io-output { border-left-color: #22c55e; }
        .orch-io-entry-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 8px;
          cursor: pointer;
          transition: background 0.15s;
        }
        .orch-io-entry-header:hover { background: rgba(255,255,255,0.04); }
        .orch-io-direction {
          font-size: 0.6rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 1px 6px;
          border-radius: 6px;
          flex-shrink: 0;
          min-width: 44px;
          text-align: center;
        }
        .orch-io-direction.input { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-io-direction.output { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-io-model {
          font-size: 0.68rem;
          color: var(--accent, #b91c1c);
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex: 1;
        }
        .orch-io-time {
          font-size: 0.58rem;
          color: rgba(255,255,255,0.25);
          font-family: monospace;
          flex-shrink: 0;
        }
        .orch-io-toggle {
          font-size: 0.6rem;
          color: rgba(255,255,255,0.3);
          flex-shrink: 0;
        }
        .orch-io-entry-body {
          padding: 4px 8px 8px;
          animation: orchFadeIn 0.15s ease;
        }
        .orch-io-messages-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .orch-io-msg-count {
          font-size: 0.6rem;
          font-weight: 700;
          text-transform: uppercase;
          color: rgba(255,255,255,0.35);
          margin-bottom: 4px;
          letter-spacing: 0.03em;
        }
        .orch-io-msg-item {
          display: flex;
          gap: 6px;
          align-items: flex-start;
        }
        .orch-io-msg-role {
          font-size: 0.55rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 1px 5px;
          border-radius: 4px;
          flex-shrink: 0;
          min-width: 46px;
          text-align: center;
          margin-top: 2px;
        }
        .orch-io-msg-role.system { background: rgba(168,85,247,0.15); color: #a855f7; }
        .orch-io-msg-role.user { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-io-msg-role.assistant { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-io-msg-role.tool { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .orch-io-msg-text {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.6);
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          white-space: pre-wrap;
          word-break: break-word;
          margin: 0;
          line-height: 1.4;
          max-height: 150px;
          overflow-y: auto;
          flex: 1;
        }
        .orch-io-response-text {
          font-size: 0.65rem;
          color: rgba(255,255,255,0.65);
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          white-space: pre-wrap;
          word-break: break-word;
          margin: 0;
          line-height: 1.4;
          max-height: 200px;
          overflow-y: auto;
          padding: 6px 8px;
          background: rgba(0,0,0,0.2);
          border-radius: 4px;
          border-left: 2px solid rgba(34,197,94,0.3);
        }

        /* ── Shared ─── */
        .orch-btn-icon {
          background: none;
          border: 1px solid rgba(255,255,255,0.1);
          color: var(--text-primary);
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.15s;
        }
        .orch-btn-icon:hover {
          background: rgba(255,255,255,0.08);
        }
        .orch-btn-icon.active {
          background: rgba(185,28,28,0.15);
          border-color: var(--accent, #b91c1c);
          color: var(--accent, #b91c1c);
        }
        .orch-empty {
          text-align: center;
          padding: 32px 16px;
          font-size: 0.8rem;
          color: rgba(255,255,255,0.3);
        }

        @keyframes orchFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes orchSpin {
          to { transform: rotate(360deg); }
        }
        .orch-spinner {
          animation: orchSpin 1s linear infinite;
        }

        /* ── Labs expanded mode ─── */

        /* ── LB Activity Feed ─── */
        .orch-lb-tabs {
          display: flex;
          gap: 2px;
          margin-left: 8px;
        }
        .orch-lb-tab {
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: rgba(255,255,255,0.5);
          padding: 2px 10px;
          border-radius: 10px;
          font-size: 0.68rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
        }
        .orch-lb-tab:hover { background: rgba(255,255,255,0.1); }
        .orch-lb-tab.active {
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
          border-color: rgba(185,28,28,0.3);
        }
        .orch-lb-feed {
          flex: 1;
          overflow-y: auto;
          padding: 12px 20px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .orch-lb-event {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 10px;
          border-radius: 4px;
          font-size: 0.75rem;
          background: rgba(255,255,255,0.02);
          border-left: 3px solid transparent;
          animation: orchFadeIn 0.15s ease;
        }
        .orch-lb-event-queue { border-left-color: #fbbf24; }
        .orch-lb-event-dispatch { border-left-color: #3b82f6; }
        .orch-lb-event-response { border-left-color: #22c55e; }
        .orch-lb-event-failed { border-left-color: #ef4444; }
        .orch-lb-event:hover { background: rgba(255,255,255,0.05); }
        .orch-lb-event-time {
          font-size: 0.65rem;
          color: rgba(255,255,255,0.3);
          flex-shrink: 0;
          font-family: monospace;
          min-width: 70px;
        }
        .orch-lb-event-type {
          font-size: 0.6rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 1px 6px;
          border-radius: 6px;
          flex-shrink: 0;
          min-width: 60px;
          text-align: center;
        }
        .orch-lb-event-type.queue { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .orch-lb-event-type.dispatch { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-lb-event-type.response { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-lb-event-type.failed { background: rgba(239,68,68,0.15); color: #ef4444; }
        .orch-lb-event-caller {
          color: rgba(255,255,255,0.5);
          font-size: 0.7rem;
          max-width: 120px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .orch-lb-event-model {
          color: var(--accent, #b91c1c);
          font-weight: 500;
          font-size: 0.72rem;
          max-width: 180px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .orch-lb-event-server {
          font-size: 0.65rem;
          background: rgba(255,255,255,0.06);
          padding: 1px 6px;
          border-radius: 6px;
          color: rgba(255,255,255,0.5);
          flex-shrink: 0;
        }
        .orch-lb-event-provider {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.3);
          flex-shrink: 0;
        }
        .orch-lb-event-tokens {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.3);
          font-family: monospace;
          flex-shrink: 0;
        }
        .orch-lb-event-duration {
          font-size: 0.62rem;
          color: rgba(255,255,255,0.25);
          font-family: monospace;
          flex-shrink: 0;
        }
        .ctx-bar {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          width: 48px;
          height: 10px;
          background: rgba(255,255,255,0.08);
          border-radius: 3px;
          overflow: hidden;
          position: relative;
          flex-shrink: 0;
        }
        .ctx-bar-fill {
          position: absolute;
          left: 0; top: 0; bottom: 0;
          border-radius: 3px;
          transition: width 0.3s;
        }
        .ctx-bar-label {
          position: relative;
          z-index: 1;
          font-size: 0.5rem;
          font-family: monospace;
          color: rgba(255,255,255,0.7);
          width: 100%;
          text-align: center;
          line-height: 10px;
        }
        .orch-lb-event-error {
          font-size: 0.62rem;
          color: var(--error, #ef4444);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 200px;
        }

        /* ── LB I/O Detail ─── */
        .orch-lb-event-wrap {
          display: flex;
          flex-direction: column;
        }
        .orch-lb-event.has-io:hover {
          background: rgba(255,255,255,0.06);
        }
        .orch-lb-io-badge {
          font-size: 0.6rem;
          font-weight: 600;
          color: var(--accent, #b91c1c);
          background: rgba(185,28,28,0.12);
          padding: 1px 6px;
          border-radius: 6px;
          cursor: pointer;
          flex-shrink: 0;
          margin-left: auto;
        }
        .orch-lb-io-badge:hover {
          background: rgba(185,28,28,0.25);
        }
        .orch-lb-io-detail {
          background: rgba(0,0,0,0.3);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 6px;
          margin: 4px 0 8px 12px;
          padding: 10px;
          animation: orchFadeIn 0.15s ease;
        }
        .orch-lb-io-section {
          margin-bottom: 10px;
        }
        .orch-lb-io-section:last-child {
          margin-bottom: 0;
        }
        .orch-lb-io-label {
          font-size: 0.65rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: rgba(255,255,255,0.4);
          margin-bottom: 6px;
          padding-bottom: 4px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .orch-lb-io-messages {
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 400px;
          overflow-y: auto;
        }
        .orch-lb-io-msg {
          display: flex;
          gap: 8px;
          align-items: flex-start;
        }
        .orch-lb-io-role {
          font-size: 0.58rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 2px 6px;
          border-radius: 4px;
          flex-shrink: 0;
          min-width: 52px;
          text-align: center;
          margin-top: 2px;
        }
        .orch-lb-io-role.system { background: rgba(168,85,247,0.15); color: #a855f7; }
        .orch-lb-io-role.user { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-lb-io-role.assistant { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-lb-io-role.tool { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .orch-lb-io-content {
          font-size: 0.68rem;
          color: rgba(255,255,255,0.7);
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          white-space: pre-wrap;
          word-break: break-word;
          margin: 0;
          line-height: 1.45;
          background: rgba(255,255,255,0.02);
          padding: 6px 8px;
          border-radius: 4px;
          flex: 1;
          max-height: 300px;
          overflow-y: auto;
        }
        .orch-lb-io-response {
          border-left: 2px solid rgba(34,197,94,0.3);
        }

        /* ── LB Stats ─── */
        .orch-lb-stats {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
        }
        .orch-lb-summary {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
          margin-bottom: 24px;
        }
        .orch-lb-stat-card {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 8px;
          padding: 16px;
          text-align: center;
        }
        .orch-lb-stat-card.success { border-color: rgba(34,197,94,0.2); }
        .orch-lb-stat-card.error { border-color: rgba(239,68,68,0.2); }
        .orch-lb-stat-card.info { border-color: rgba(59,130,246,0.2); }
        .orch-lb-stat-value {
          font-size: 1.8rem;
          font-weight: 700;
          line-height: 1.2;
        }
        .orch-lb-stat-card.success .orch-lb-stat-value { color: #22c55e; }
        .orch-lb-stat-card.error .orch-lb-stat-value { color: #ef4444; }
        .orch-lb-stat-card.info .orch-lb-stat-value { color: #3b82f6; }
        .orch-lb-stat-label {
          font-size: 0.7rem;
          color: rgba(255,255,255,0.4);
          margin-top: 4px;
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .orch-lb-chart-section {
          margin-bottom: 24px;
        }
        .orch-lb-chart-title {
          font-size: 0.78rem;
          font-weight: 600;
          color: rgba(255,255,255,0.5);
          margin: 0 0 12px;
        }
        .orch-lb-chart {
          display: flex;
          align-items: flex-end;
          gap: 2px;
          height: 120px;
          background: rgba(255,255,255,0.02);
          border-radius: 6px;
          padding: 8px 4px 20px;
          border: 1px solid rgba(255,255,255,0.04);
        }
        .orch-lb-chart-bar-wrap {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
          position: relative;
        }
        .orch-lb-chart-bar {
          width: 100%;
          max-width: 24px;
          min-height: 2px;
          background: var(--accent, #b91c1c);
          border-radius: 2px 2px 0 0;
          transition: height 0.3s ease;
        }
        .orch-lb-chart-label {
          font-size: 0.5rem;
          color: rgba(255,255,255,0.25);
          position: absolute;
          bottom: -16px;
          white-space: nowrap;
        }
        .orch-lb-breakdown {
          margin-bottom: 20px;
        }
        .orch-lb-breakdown-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 4px 0;
        }
        .orch-lb-breakdown-name {
          font-size: 0.72rem;
          color: rgba(255,255,255,0.6);
          min-width: 150px;
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .orch-lb-breakdown-bar-bg {
          flex: 1;
          height: 6px;
          background: rgba(255,255,255,0.06);
          border-radius: 3px;
          overflow: hidden;
        }
        .orch-lb-breakdown-bar {
          height: 100%;
          background: var(--accent, #b91c1c);
          border-radius: 3px;
          transition: width 0.3s ease;
          min-width: 2px;
        }
        .orch-lb-breakdown-count {
          font-size: 0.68rem;
          color: rgba(255,255,255,0.4);
          min-width: 30px;
          text-align: right;
          font-family: monospace;
        }

        /* ── View Toggle ─── */
        .orch-lb-view-toggle {
          display: flex;
          gap: 1px;
          background: rgba(255,255,255,0.06);
          border-radius: 6px;
          overflow: hidden;
        }
        .orch-lb-view-toggle button {
          background: transparent;
          border: none;
          color: rgba(255,255,255,0.35);
          padding: 3px 8px;
          font-size: 0.72rem;
          cursor: pointer;
          transition: all 0.15s;
        }
        .orch-lb-view-toggle button:hover { color: rgba(255,255,255,0.6); }
        .orch-lb-view-toggle button.active {
          background: rgba(185,28,28,0.2);
          color: var(--accent, #b91c1c);
        }

        /* ── Grouped Request View ─── */
        .orch-lb-request {
          border-radius: 6px;
          background: rgba(255,255,255,0.02);
          border-left: 3px solid transparent;
          animation: orchFadeIn 0.15s ease;
          margin-bottom: 2px;
        }
        .orch-lb-request-succeeded { border-left-color: #22c55e; }
        .orch-lb-request-failed { border-left-color: #ef4444; }
        .orch-lb-request-running { border-left-color: #3b82f6; background: rgba(59,130,246,0.04); }
        .orch-lb-request-queued { border-left-color: #fbbf24; }
        .orch-lb-request-retrying { border-left-color: #f97316; background: rgba(249,115,22,0.04); }
        .orch-lb-request-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 10px;
          cursor: pointer;
          font-size: 0.75rem;
        }
        .orch-lb-request-row:hover { background: rgba(255,255,255,0.04); }
        .orch-lb-req-expand {
          font-size: 0.6rem;
          color: rgba(255,255,255,0.25);
          width: 12px;
          flex-shrink: 0;
        }
        .orch-lb-req-status {
          font-size: 0.6rem;
          font-weight: 700;
          text-transform: uppercase;
          padding: 1px 6px;
          border-radius: 6px;
          flex-shrink: 0;
          min-width: 68px;
          text-align: center;
          display: flex;
          align-items: center;
          gap: 4px;
          justify-content: center;
        }
        .orch-lb-req-status.queued { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .orch-lb-req-status.running { background: rgba(59,130,246,0.15); color: #3b82f6; }
        .orch-lb-req-status.succeeded { background: rgba(34,197,94,0.15); color: #22c55e; }
        .orch-lb-req-status.failed { background: rgba(239,68,68,0.15); color: #ef4444; }
        .orch-lb-req-status.retrying { background: rgba(249,115,22,0.15); color: #f97316; }
        .orch-lb-pulse {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: currentColor;
          animation: orchPulse 1s ease-in-out infinite;
        }
        @keyframes orchPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.7); }
        }
        .orch-lb-req-id {
          font-family: monospace;
          font-size: 0.58rem;
          color: rgba(255,255,255,0.18);
          margin-left: auto;
          flex-shrink: 0;
        }
        .orch-lb-request-events {
          padding: 0 10px 6px 30px;
          border-top: 1px solid rgba(255,255,255,0.04);
        }
        .orch-lb-event-nested {
          background: transparent;
          border-left: none;
          padding: 3px 8px;
          font-size: 0.68rem;
          opacity: 0.7;
        }
        .orch-lb-event-attempt {
          font-size: 0.58rem;
          color: rgba(255,255,255,0.3);
          font-family: monospace;
        }

        /* ── Stacked Bar Chart ─── */
        .orch-lb-chart-bar-stack {
          width: 100%;
          max-width: 24px;
          min-height: 2px;
          display: flex;
          flex-direction: column;
          border-radius: 2px 2px 0 0;
          overflow: hidden;
          transition: height 0.3s ease;
        }
        .orch-lb-bar-segment { min-height: 1px; }
        .orch-lb-bar-segment.bar-succeeded { background: #22c55e; }
        .orch-lb-bar-segment.bar-dispatched { background: #3b82f6; }
        .orch-lb-bar-segment.bar-failed { background: #ef4444; }
        .orch-lb-chart-legend {
          display: flex;
          gap: 16px;
          justify-content: center;
          margin-top: 8px;
          font-size: 0.62rem;
          color: rgba(255,255,255,0.35);
        }
        .orch-lb-legend-dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 2px;
          margin-right: 4px;
          vertical-align: middle;
        }
        .orch-lb-breakdown-bar-bg { position: relative; }
        .bar-succeeded { background: #22c55e; }
        .bar-failed { background: #ef4444; }

        /* ── Live Diagram ─── */
        .orch-lb-diagram {
          flex: 1;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
          background: rgba(0,0,0,0.15);
        }
        .orch-lb-diagram-svg {
          width: 100%;
          height: 100%;
          max-height: 100%;
        }

        /* ── Full View button ─── */
        .orch-btn-fullview {
          background: none;
          border: 1px solid rgba(255,255,255,0.12);
          color: rgba(255,255,255,0.5);
          cursor: pointer;
          font-size: 0.7rem;
          padding: 1px 5px;
          border-radius: 4px;
          line-height: 1;
          transition: all 0.15s;
        }
        .orch-btn-fullview:hover {
          background: rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.8);
          border-color: rgba(255,255,255,0.25);
        }

        /* ── Full View Center Panel ─── */
        .orch-fullview-body {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .orch-fullview-provider {
          background: var(--bg-card, #292524);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 8px;
          padding: 16px;
        }
        .orch-fullview-provider-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
          font-size: 0.85rem;
        }
        .orch-fullview-url {
          color: rgba(255,255,255,0.4);
          font-size: 0.75rem;
          word-break: break-all;
        }
        .orch-fullview-models {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .orch-fullview-model-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 10px;
          background: rgba(255,255,255,0.03);
          border-radius: 6px;
          font-size: 0.78rem;
        }
        .orch-fullview-model-row .orch-model-name {
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
`;
