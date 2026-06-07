/**
 * Bob Manager — Public Live Demo Page.
 * Terminal-aesthetic page showcasing running labs in real-time.
 * Accessible without authentication.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  getLiveLabs,
  getLiveLabDetail,
  getLiveLabMessages,
  getLiveLabResources,
  getLiveServers,
  getPublicLiveModels,
  getLiveResourceContent,
  getLiveResourceDownloadUrl,
  getLiveOutputContent,
  getLiveOutputDownloadUrl,
  getLiveFileBlob,
} from '../services/api';
import wsService from '../services/websocket';
import './LivePage.css';

/* ─── tiny helpers ─────────────────────────────── */

/**
 * U07 — Single source of truth for "is this lab a consumer-app / showroom
 * template that should be hidden from the public Live page?". Pre-fix
 * the same lowercased-name prefix check lived in two places (the
 * initial loader at L864 and the right-sidebar renderer at L1162); a
 * drift between the two would have leaked app rows into the sidebar.
 */
function isHiddenAppLab(lab) {
  const n = (lab.name || '').toLowerCase();
  return n.startsWith('app:')
      || n.startsWith('showroom:')
      || n.startsWith('showroom_template_');
}

function formatBytes(b) {
  if (!b) return '0 B';
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
  return (b / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatTokens(n) {
  if (!n) return '0';
  if (n < 1000) return String(n);
  return (n / 1000).toFixed(1) + 'k';
}

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return sec + 's ago';
  if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
  if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
  return Math.floor(sec / 86400) + 'd ago';
}

function statusColor(s) {
  if (s === 'running') return '#22c55e';
  if (s === 'paused') return '#f59e0b';
  if (s === 'completed') return '#3b82f6';
  if (s === 'error' || s === 'failed') return '#ef4444';
  return '#6b7280';
}

function fileIcon(ct) {
  if (!ct) return '📄';
  if (ct.startsWith('image/')) return '🖼';
  if (ct.startsWith('audio/')) return '🎵';
  if (ct.startsWith('video/')) return '🎬';
  if (ct.includes('pdf')) return '📕';
  if (ct.includes('json') || ct.includes('javascript') || ct.includes('python')) return '📝';
  return '📄';
}

function msgTypeLabel(t) {
  const m = {
    message: 'MSG', task: 'TASK', result: 'RES', error: 'ERR',
    tool_call: 'TOOL', tool_result: 'T-RES', inject: 'INJ',
    summary: 'SUM', file_event: 'FILE',
  };
  return m[t] || t?.toUpperCase() || '';
}

function msgTypeColor(t) {
  const m = {
    message: '#22c55e', task: '#a78bfa', result: '#3b82f6', error: '#ef4444',
    tool_call: '#f59e0b', tool_result: '#facc15', inject: '#ec4899',
    summary: '#06b6d4', file_event: '#8b5cf6',
  };
  return m[t] || '#6b7280';
}

/* ─── styles object ────────────────────────────── */

const S = {
  page: {
    position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
    background: '#0a0a0a', color: '#d4d4d4', fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace",
    fontSize: '13px', overflow: 'hidden',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 20px', borderBottom: '1px solid #1a1a2e',
    background: '#0d0d14', flexShrink: 0,
  },
  brand: {
    color: '#22c55e', fontSize: '16px', fontWeight: 700, textDecoration: 'none',
    display: 'flex', alignItems: 'center', gap: '8px',
  },
  backLink: {
    color: '#6b7280', fontSize: '12px', textDecoration: 'none',
    border: '1px solid #1a1a2e', padding: '4px 12px', borderRadius: '4px',
  },
  body: {
    display: 'flex', flex: 1, overflow: 'hidden',
  },
  sidebar: {
    width: '240px', flexShrink: 0, borderRight: '1px solid #1a1a2e',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  sidebarRight: {
    width: '220px', flexShrink: 0, borderLeft: '1px solid #1a1a2e',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  sidebarTitle: {
    padding: '12px 16px 8px', fontSize: '10px', fontWeight: 700,
    color: '#4a4a5a', letterSpacing: '1.5px', textTransform: 'uppercase',
    borderBottom: '1px solid #1a1a2e',
  },
  sidebarList: {
    flex: 1, overflowY: 'auto', padding: '4px 0',
  },
  center: {
    flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden',
    padding: '16px', gap: '12px',
  },
  cardsArea: {
    flex: 1, display: 'grid', gap: '16px', overflow: 'hidden',
    gridTemplateColumns: '1fr 1fr',
    gridTemplateRows: '1fr',
  },
  orchColumn: {
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  agentColumn: {
    display: 'flex', flexDirection: 'column', gap: '16px', overflow: 'auto',
  },
  card: (isOrch) => ({
    flex: isOrch ? '1 1 auto' : '0 0 auto',
    border: '1px solid #1a1a2e', borderRadius: '6px', background: '#0d0d14',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
    minHeight: isOrch ? 0 : '120px',
    maxHeight: isOrch ? 'none' : 'calc(50vh - 80px)',
  }),
  cardHeader: {
    padding: '10px 14px', borderBottom: '1px solid #1a1a2e',
    display: 'flex', flexDirection: 'column', gap: '6px', flexShrink: 0,
  },
  cardHeaderRow: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  },
  cardName: {
    fontSize: '13px', fontWeight: 700, color: '#e2e8f0',
  },
  cardModel: {
    fontSize: '11px', color: '#6b7280',
  },
  statsRow: {
    display: 'flex', gap: '12px', fontSize: '11px', color: '#6b7280',
  },
  statItem: {
    display: 'flex', alignItems: 'center', gap: '4px',
  },
  feed: {
    flex: 1, overflowY: 'auto', padding: '8px 12px', display: 'flex',
    flexDirection: 'column', gap: '4px',
  },
  feedMsg: {
    padding: '4px 0', borderBottom: '1px solid #111118', lineHeight: 1.4,
    fontSize: '12px', animation: 'live-fadein .4s ease',
  },
  filesSection: {
    flexShrink: 0, maxHeight: '180px', borderTop: '1px solid #1a1a2e',
    overflow: 'hidden', display: 'flex', flexDirection: 'column',
  },
  filesSectionTitle: {
    padding: '8px 14px', fontSize: '10px', fontWeight: 700,
    color: '#4a4a5a', letterSpacing: '1.5px', textTransform: 'uppercase',
    borderBottom: '1px solid #1a1a2e', flexShrink: 0,
  },
  filesList: {
    overflowY: 'auto', padding: '4px 14px', flex: 1,
  },
  fileItem: {
    display: 'flex', alignItems: 'center', gap: '8px',
    padding: '3px 0', fontSize: '12px', color: '#9ca3af',
  },
  /* server item */
  serverItem: {
    padding: '8px 16px', cursor: 'default',
    borderBottom: '1px solid #111118',
  },
  serverName: {
    display: 'flex', alignItems: 'center', gap: '6px',
    fontSize: '12px', fontWeight: 600, color: '#d4d4d4',
  },
  serverMeta: {
    display: 'flex', gap: '10px', marginTop: '4px', fontSize: '11px', color: '#6b7280',
  },
  /* provider */
  providerItem: {
    padding: '6px 16px', display: 'flex', alignItems: 'center', gap: '8px',
    fontSize: '12px', color: '#9ca3af', borderBottom: '1px solid #111118',
  },
  /* lab item */
  labItem: (active) => ({
    padding: '8px 16px', cursor: 'pointer',
    background: active ? '#131320' : 'transparent',
    borderLeft: active ? '2px solid #22c55e' : '2px solid transparent',
    borderBottom: '1px solid #111118',
    transition: 'background .15s',
  }),
  labName: {
    fontSize: '12px', fontWeight: 600, color: '#e2e8f0',
    display: 'flex', alignItems: 'center', gap: '6px',
  },
  labMeta: {
    fontSize: '11px', color: '#6b7280', marginTop: '2px',
  },
  connectionLine: {
    display: 'flex', alignItems: 'center', color: '#22c55e',
    fontSize: '14px', alignSelf: 'center', flexShrink: 0, padding: '0 4px',
    opacity: 0.5,
  },
  connectionLineActive: {
    animation: 'live-arrow-pulse 1.5s ease-in-out infinite',
    opacity: 1,
  },
  empty: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: '100%', color: '#4a4a5a', fontSize: '13px', fontStyle: 'italic',
  },
  ctxBar: {
    height: '4px', borderRadius: '2px', background: '#1a1a2e', overflow: 'hidden',
    marginTop: '2px', width: '100%',
  },
  ctxFill: (pct) => ({
    height: '100%', width: `${Math.min(100, pct)}%`,
    background: pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#22c55e',
    transition: 'width .3s',
  }),
  dot: (color, blink) => ({
    display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%',
    background: color,
    animation: blink ? 'live-server-blink 2s ease-in-out infinite' : 'none',
    flexShrink: 0,
  }),
  noSelect: { padding: '40px', textAlign: 'center', color: '#4a4a5a', fontSize: '13px' },
};

/* inject global keyframes */
const KEYFRAMES_ID = 'live-page-keyframes';
function ensureKeyframes() {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const style = document.createElement('style');
  style.id = KEYFRAMES_ID;
  style.textContent = `
    @keyframes live-fadein { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
    @keyframes live-server-blink { 0%,100% { opacity:1; } 50% { opacity:.35; } }
    @keyframes live-arrow-pulse { 0%,100% { opacity:1; } 50% { opacity:.3; } }
    @keyframes live-card-pulse { 0% { background-color: #0d0d14; } 50% { background-color: #0d1a12; } 100% { background-color: #0d0d14; } }
    .live-scroll::-webkit-scrollbar { width: 4px; }
    .live-scroll::-webkit-scrollbar-thumb { background: #1a1a2e; border-radius: 2px; }
    .live-scroll::-webkit-scrollbar-track { background: transparent; }
  `;
  document.head.appendChild(style);
}

/* ─── Scanline overlay (very subtle) ───────────── */

function Scanlines() {
  return <div className="lp-live-scanlines" />;
}

/* ─── Server sidebar item ──────────────────────── */

function ServerItem({ server, metrics }) {
  const online = server.status === 'online';
  const gpuStatic = server.gpu_info?.gpus?.[0];
  const gpuLive = metrics?.gpu_metrics?.[0];
  const isActive = metrics?.cpu_usage > 30 || (gpuLive?.gpu_usage_percent > 20);
  const vramUsed = gpuLive?.memory_used_mb ?? gpuStatic?.memory_used_mb;
  const vramTotal = gpuLive?.memory_total_mb ?? gpuStatic?.memory_total_mb;
  const gpuName = gpuLive?.name || gpuStatic?.name;
  const ramPct = metrics?.ram_percent;

  return (
    <div className="lp-server-item">
      <div className="lp-server-name">
        <span className={`lp-dot${online && isActive ? ' blink' : ''}`} style={{ background: online ? '#34d399' : '#4a5263' }} />
        {server.name}
      </div>
      <div className="lp-server-meta">
        {gpuName && (
          <span title="GPU">{gpuName.split(' ').slice(-1)[0]}</span>
        )}
        {vramUsed != null && vramTotal != null && (
          <span title="VRAM">🎮 {vramUsed}/{vramTotal}MB</span>
        )}
        {ramPct != null && (
          <span title="RAM">💾 {ramPct.toFixed(0)}%</span>
        )}
      </div>
    </div>
  );
}

/* ─── Model sidebar item ───────────────────────── */

function ModelItem({ model }) {
  const count = model.available_providers;
  return (
    <div className="lp-provider-item">
      <span className="lp-dot" style={{ background: '#34d399' }} />
      <span className="lp-provider-name">{model.model_identifier}</span>
      {count > 1 && (
        <span className="lp-provider-badge count">{count}/{count}</span>
      )}
      <span className="lp-provider-badge">available</span>
    </div>
  );
}

/* ─── Lab sidebar item ─────────────────────────── */

function LabItem({ lab, active, onSelect }) {
  return (
    <div className={`lp-lab-item${active ? ' active' : ''}`} onClick={onSelect}>
      <div className="lp-lab-name">
        <span className={`lp-dot${lab.status === 'running' ? ' blink' : ''}`} style={{ background: statusColor(lab.status) }} />
        {lab.name}
      </div>
      <div className="lp-lab-meta">
        {lab.status} · {lab.agent_count} agent{lab.agent_count !== 1 ? 's' : ''} · iter {lab.current_iteration}/{lab.max_iterations}
      </div>
    </div>
  );
}

/* ─── Agent / Orchestrator card ────────────────── */

function ActorCard({ name, modelName, isOrchestrator, messages, tokensIn, tokensOut }) {
  const feedRef = useRef(null);
  const prevCount = useRef(0);
  const [pulsing, setPulsing] = useState(false);

  useEffect(() => {
    if (messages.length > prevCount.current) {
      setPulsing(true);
      const t = setTimeout(() => setPulsing(false), 1000);
      prevCount.current = messages.length;
      return () => clearTimeout(t);
    }
    prevCount.current = messages.length;
  }, [messages.length]);

  const totalIn = tokensIn || messages.reduce((s, m) => s + (m.tokens_in || 0), 0);
  const totalOut = tokensOut || messages.reduce((s, m) => s + (m.tokens_out || 0), 0);

  // rough context % estimate (assume 128k context)
  const ctxPct = Math.min(100, ((totalIn + totalOut) / 128000) * 100);

  const ctxClass = ctxPct > 80 ? 'crit' : ctxPct > 50 ? 'warn' : '';

  return (
    <div className={`lp-term-card ${isOrchestrator ? 'orchestrator' : 'agent'}${pulsing ? ' pulsing' : ''}`}>
      <div className="lp-term-header">
        <div className="lp-term-header-row">
          <div className="lp-term-title-group">
            <div className="lp-term-traffic">
              <span className="red" />
              <span className="yellow" />
              <span className="green" />
            </div>
            <span className="lp-term-name">
              <span className="icon">{isOrchestrator ? '⚙' : '◇'}</span>{name}
            </span>
          </div>
          <span className="lp-term-model">{modelName || 'no model'}</span>
        </div>
        <div className="lp-term-stats">
          <span className="lp-term-stat"><span className="in">▼</span>{formatTokens(totalIn)}</span>
          <span className="lp-term-stat"><span className="out">▲</span>{formatTokens(totalOut)}</span>
          <span className="lp-term-stat" style={{ marginLeft: 'auto', opacity: 0.7 }}>ctx {ctxPct.toFixed(0)}%</span>
        </div>
        <div className="lp-term-ctxbar">
          <div className={`lp-term-ctxfill ${ctxClass}`} style={{ width: `${Math.min(100, ctxPct)}%` }} />
        </div>
      </div>
      <div ref={feedRef} className="lp-term-feed">
        {messages.length === 0 && (
          <div className="lp-term-feed-empty">Waiting for activity</div>
        )}
        {[...messages].reverse().map((m, i) => (
          <div key={m.id || i} className="lp-term-msg">
            <span className="lp-term-msg-tag" style={{ background: msgTypeColor(m.message_type) }}>
              {msgTypeLabel(m.message_type)}
            </span>
            {m.tool_name && (
              <span className="lp-term-msg-tool">[{m.tool_name}]</span>
            )}
            <span className="lp-term-msg-content">
              {(m.content || '').slice(0, 200)}
              {(m.content || '').length > 200 ? '…' : ''}
            </span>
            {(m.tokens_in > 0 || m.tokens_out > 0) && (
              <span className="lp-term-msg-tokens">[{m.tokens_in}→{m.tokens_out}]</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Connection arrow ─────────────────────────── */

function Arrow({ active }) {
  return (
    <div style={{
      ...S.connectionLine,
      ...(active ? S.connectionLineActive : {}),
    }}>
      ─→
    </div>
  );
}

/* ─── Terminal File Viewer Modal ────────────────── */

function TerminalFileViewer({ file, labId, onClose }) {
  const [phase, setPhase] = useState('blink'); // 'blink' | 'loading' | 'ready'
  const [blinkCount, setBlinkCount] = useState(0);
  const [fileData, setFileData] = useState(null);
  const [blobUrl, setBlobUrl] = useState(null);
  const [error, setError] = useState(null);

  // Blink cursor 3 times, then load
  useEffect(() => {
    if (phase !== 'blink') return;
    const t = setInterval(() => {
      setBlinkCount(c => {
        if (c >= 5) { // 3 full blinks = 6 ticks, but 5 is fine
          clearInterval(t);
          setPhase('loading');
          return c;
        }
        return c + 1;
      });
    }, 300);
    return () => clearInterval(t);
  }, [phase]);

  // Load file content
  useEffect(() => {
    if (phase !== 'loading') return;
    let cancelled = false;

    async function load() {
      try {
        let data, downloadUrl;
        if (file.resource_type === 'output' && file.filename) {
          // Output file - use path-based endpoint
          const path = file.filename;
          const res = await getLiveOutputContent(labId, path);
          data = res.data;
          downloadUrl = getLiveOutputDownloadUrl(labId, path);
        } else if (file.id && !file.id.startsWith('fe-')) {
          // Uploaded resource - use resource ID endpoint
          const res = await getLiveResourceContent(labId, file.id);
          data = res.data;
          downloadUrl = getLiveResourceDownloadUrl(labId, file.id);
        } else {
          setError('File not available for preview');
          setPhase('ready');
          return;
        }

        if (cancelled) return;
        data._downloadUrl = downloadUrl;
        setFileData(data);

        // For media files, fetch blob
        if ((data.is_image || data.is_audio || data.is_video) && downloadUrl) {
          try {
            const blobRes = await getLiveFileBlob(downloadUrl);
            if (!cancelled) {
              setBlobUrl(URL.createObjectURL(blobRes.data));
            }
          } catch { /* blob fetch failed, show text fallback */ }
        }
        setPhase('ready');
      } catch (e) {
        if (!cancelled) {
          setError('Failed to load file');
          setPhase('ready');
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, [phase, file, labId]);

  // Cleanup blob URL
  useEffect(() => {
    return () => { if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [blobUrl]);

  // Close on Escape
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const fileName = file.original_name || file.filename || 'unknown';

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 10000, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(4px)',
    }} onClick={onClose}>
      <div style={{
        width: '80vw', maxWidth: '900px', maxHeight: '80vh',
        background: '#0d0d14', border: '1px solid #1a1a2e', borderRadius: '8px',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        boxShadow: '0 0 40px rgba(34,197,94,0.1)',
      }} onClick={e => e.stopPropagation()}>
        {/* Title bar */}
        <div style={{
          padding: '10px 16px', borderBottom: '1px solid #1a1a2e',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: '#22c55e', fontSize: '10px' }}>●</span>
            <span style={{ color: '#f59e0b', fontSize: '10px' }}>●</span>
            <span style={{ color: '#ef4444', fontSize: '10px' }}>●</span>
            <span style={{ color: '#e2e8f0', fontWeight: 600, fontSize: '12px', marginLeft: '8px' }}>
              {fileName}
            </span>
            <span style={{ color: '#4a4a5a', fontSize: '11px' }}>
              ({formatBytes(file.size_bytes)})
            </span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {fileData?._downloadUrl && (
              <a
                href={fileData._downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: '#6b7280', fontSize: '11px', textDecoration: 'none',
                  border: '1px solid #1a1a2e', padding: '2px 10px', borderRadius: '3px',
                }}
              >
                ↓ Download
              </a>
            )}
            <button onClick={onClose} style={{
              background: 'none', border: '1px solid #1a1a2e', color: '#6b7280',
              cursor: 'pointer', fontSize: '14px', padding: '2px 8px', borderRadius: '3px',
              fontFamily: 'inherit',
            }}>✕</button>
          </div>
        </div>

        {/* Terminal content */}
        <div className="live-scroll" style={{
          flex: 1, overflow: 'auto', padding: '16px', fontFamily: 'inherit',
          fontSize: '12px', lineHeight: 1.6, color: '#d4d4d4',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          minHeight: '200px',
        }}>
          {phase === 'blink' && (
            <span style={{
              color: '#22c55e', fontSize: '16px',
              opacity: blinkCount % 2 === 0 ? 1 : 0,
              transition: 'opacity 0.15s',
            }}>▌</span>
          )}
          {phase === 'loading' && (
            <span style={{ color: '#22c55e', fontSize: '12px' }}>
              Loading {fileName}...
            </span>
          )}
          {phase === 'ready' && error && (
            <span style={{ color: '#ef4444' }}>{error}</span>
          )}
          {phase === 'ready' && fileData && (
            <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
              {fileData.is_image && blobUrl ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <img
                    src={blobUrl}
                    alt={fileName}
                    style={{ maxWidth: '100%', maxHeight: '60vh', objectFit: 'contain', borderRadius: '4px' }}
                  />
                </div>
              ) : fileData.is_audio && blobUrl ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <audio controls src={blobUrl} style={{ width: '100%', maxWidth: '500px' }} />
                </div>
              ) : fileData.is_video && blobUrl ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <video
                    controls
                    src={blobUrl}
                    style={{ maxWidth: '100%', maxHeight: '60vh', borderRadius: '4px' }}
                  />
                </div>
              ) : fileData.is_text && fileData.content != null ? (
                <pre style={{
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
                  color: '#b0b0b0', fontFamily: 'inherit', fontSize: '12px',
                }}>
                  <span style={{ color: '#22c55e' }}>$ cat {fileName}</span>{'\n'}
                  {fileData.content}
                </pre>
              ) : (
                <div style={{ textAlign: 'center', color: '#6b7280' }}>
                  Binary file — cannot preview inline.
                  {fileData._downloadUrl && (
                    <div style={{ marginTop: '12px' }}>
                      <a
                        href={fileData._downloadUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: '#22c55e', textDecoration: 'underline' }}
                      >
                        Download file
                      </a>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Files section ────────────────────────────── */

function FilesSection({ resources, messages, labId, onFileClick }) {
  // Merge uploaded resources + output files extracted from file_event messages
  const fileEvents = (messages || []).filter(m => m.message_type === 'file_event' && m.content);
  const outputsFromMsgs = fileEvents.map((m, i) => {
    const match = m.content.match(/\*\*(.+?)\*\*.*?\((\d+).*?bytes?\)/i);
    return {
      id: 'fe-' + i,
      filename: match?.[1] || m.content.slice(0, 60),
      original_name: match?.[1]?.split('/').pop() || m.content.slice(0, 40),
      content_type: '',
      size_bytes: match?.[2] ? parseInt(match[2]) : 0,
      resource_type: 'output',
    };
  });

  const allResources = [...(resources || []), ...outputsFromMsgs];
  if (allResources.length === 0) return null;

  const inputs = allResources.filter(r => r.resource_type !== 'output');
  const outputs = allResources.filter(r => r.resource_type === 'output');

  return (
    <div className="lp-files-section">
      <div className="lp-files-title">Input / Output Files</div>
      <div className="lp-files-list">
        {inputs.length > 0 && inputs.map(f => (
          <div key={f.id} className="lp-file-item" onClick={() => onFileClick(f)}>
            <span>{fileIcon(f.content_type)}</span>
            <span style={{ color: '#d4d4d4' }}>{f.original_name}</span>
            <span style={{ marginLeft: 'auto' }}>{formatBytes(f.size_bytes)}</span>
          </div>
        ))}
        {outputs.length > 0 && (
          <>
            <div style={{ fontSize: '10px', color: '#4a5263', padding: '6px 0 2px', marginTop: '4px', letterSpacing: '1.5px' }}>
              OUTPUT
            </div>
            {outputs.map(f => (
              <div key={f.id} className="lp-file-item" onClick={() => onFileClick(f)}>
                <span>{fileIcon(f.content_type)}</span>
                <span style={{ color: '#34d399' }}>{f.original_name}</span>
                <span style={{ marginLeft: 'auto' }}>{formatBytes(f.size_bytes)}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

/* ─── Unified Feed (single terminal) ───────────── */

function UnifiedFeed({ messages, labDetail }) {
  const feedRef = useRef(null);
  const prevCount = useRef(0);
  const [pulsing, setPulsing] = useState(false);

  useEffect(() => {
    if (messages.length > prevCount.current) {
      setPulsing(true);
      const t = setTimeout(() => setPulsing(false), 1000);
      prevCount.current = messages.length;
      return () => clearTimeout(t);
    }
    prevCount.current = messages.length;
  }, [messages.length]);

  // Build a name→model lookup
  const modelMap = {};
  if (labDetail) {
    modelMap['Orchestrator'] = labDetail.orchestrator_model_name;
    labDetail.agents?.forEach(a => { modelMap[a.name] = a.model_name; });
  }

  const senderColor = (type, name) => {
    if (type === 'orchestrator' || type === 'system') return '#a78bfa';
    // Stable color per agent name
    const colors = ['#22c55e', '#f59e0b', '#3b82f6', '#ec4899', '#06b6d4', '#f97316', '#8b5cf6', '#14b8a6'];
    let h = 0;
    for (let i = 0; i < (name || '').length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
    return colors[Math.abs(h) % colors.length];
  };

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden',
      border: '1px solid #1a1a2e', borderRadius: '6px', background: '#0d0d14',
      animation: pulsing ? 'live-card-pulse 1s ease' : 'none',
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid #1a1a2e', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>
          ▸ Lab Feed
        </span>
        <span style={{ fontSize: '11px', color: '#4a4a5a' }}>
          {messages.length} messages
        </span>
      </div>
      <div ref={feedRef} className="live-scroll" style={{
        flex: 1, overflowY: 'auto', padding: '8px 14px', display: 'flex',
        flexDirection: 'column', gap: '2px',
      }}>
        {messages.length === 0 && (
          <div style={{ color: '#4a4a5a', padding: '40px 0', textAlign: 'center', fontSize: '11px' }}>
            Waiting for activity…
          </div>
        )}
        {[...messages].reverse().map((m, i) => {
          const sender = m.sender_name || m.sender_type || '?';
          const isOrch = m.sender_type === 'orchestrator' || m.sender_type === 'system';
          const model = modelMap[sender] || m.model_used;
          const time = m.created_at ? new Date(m.created_at).toLocaleTimeString() : '';
          const color = senderColor(m.sender_type, sender);

          return (
            <div key={m.id || i} style={{
              padding: '5px 0', borderBottom: '1px solid #111118', lineHeight: 1.5,
              fontSize: '12px', animation: 'live-fadein .4s ease',
            }}>
              {/* Row 1: sender + type badge + timestamp + model + tokens */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ color: isOrch ? '#a78bfa' : '#22c55e', fontSize: '10px' }}>
                  {isOrch ? '⚙' : '▸'}
                </span>
                <span style={{ fontWeight: 700, color, textTransform: 'uppercase', fontSize: '11px' }}>
                  {sender}
                </span>
                <span style={{
                  fontSize: '9px', fontWeight: 700, padding: '1px 4px', borderRadius: '2px',
                  color: '#0a0a0a', background: msgTypeColor(m.message_type),
                }}>
                  {msgTypeLabel(m.message_type)}
                </span>
                <span style={{ fontSize: '10px', color: '#4a4a5a' }}>{time}</span>
                {model && (
                  <span style={{
                    fontSize: '9px', color: '#6b7280', background: '#141420',
                    padding: '1px 6px', borderRadius: '3px',
                  }}>
                    {model}
                  </span>
                )}
                {(m.tokens_in > 0 || m.tokens_out > 0) && (
                  <span style={{ fontSize: '10px', color: '#4a4a5a' }}>
                    {m.tokens_in}→{m.tokens_out}
                  </span>
                )}
                {m.duration_ms > 0 && (
                  <span style={{ fontSize: '10px', color: '#4a4a5a' }}>
                    {(m.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              {/* Row 2: content */}
              {m.tool_name && (
                <span style={{ color: '#f59e0b', fontSize: '11px', marginRight: '6px' }}>
                  [{m.tool_name}]
                </span>
              )}
              <div style={{ color: '#b0b0b0', marginTop: '2px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {(m.content || '').slice(0, 500)}
                {(m.content || '').length > 500 ? '…' : ''}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════════
   MAIN COMPONENT
   ═════════════════════════════════════════════════ */

export default function LivePage() {
  const [labs, setLabs] = useState([]);
  const [selectedLabId, setSelectedLabId] = useState(null);
  const [labDetail, setLabDetail] = useState(null);
  const [messages, setMessages] = useState([]);
  const [resources, setResources] = useState([]);
  const [servers, setServers] = useState([]);
  const [models, setModels] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [activeAgents, setActiveAgents] = useState(new Set());
  const [viewMode, setViewMode] = useState('cards'); // 'cards' | 'feed'
  const [viewingFile, setViewingFile] = useState(null); // file object for viewer
  const wsConnected = useRef(false);

  // Insert keyframes on mount
  useEffect(() => { ensureKeyframes(); }, []);

  // Connect WS (it's unauthenticated) — small delay so App.js effect runs first
  useEffect(() => {
    const t = setTimeout(() => {
      wsService.connect();
      wsConnected.current = true;
    }, 100);
    return () => {
      clearTimeout(t);
      wsService.disconnect();
      wsConnected.current = false;
    };
  }, []);

  // Load initial data — each independent so one failure doesn't break all
  const loadData = useCallback(async () => {
    try {
      const r = await getLiveLabs();
      setLabs(r.data);
      const visible = r.data.filter(l => !isHiddenAppLab(l));
      setSelectedLabId(prev => {
        if (prev) return prev;
        const running = visible.find(l => l.status === 'running');
        return (running || visible[0])?.id || null;
      });
    } catch (e) { console.warn('[Live] labs:', e); }
    try { const r = await getLiveServers(); setServers(r.data); } catch (e) { console.warn('[Live] servers:', e); }
    try { const r = await getPublicLiveModels(); setModels(r.data); } catch (e) { console.warn('[Live] models:', e); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Refresh labs list periodically
  useEffect(() => {
    const iv = setInterval(async () => {
      try {
        const r = await getLiveLabs();
        setLabs(r.data);
      } catch {}
    }, 10000);
    return () => clearInterval(iv);
  }, []);

  // Load selected lab detail + messages + resources
  useEffect(() => {
    if (!selectedLabId) return;
    let cancelled = false;

    async function load() {
      try {
        const [detailRes, msgsRes, resRes] = await Promise.all([
          getLiveLabDetail(selectedLabId),
          getLiveLabMessages(selectedLabId, 200),
          getLiveLabResources(selectedLabId),
        ]);
        if (cancelled) return;
        setLabDetail(detailRes.data);
        setMessages(msgsRes.data);
        setResources(resRes.data);
      } catch (e) {
        console.warn('[Live] Failed to load lab:', e);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [selectedLabId]);

  // WebSocket: lab events
  useEffect(() => {
    const handlers = [];

    // Lab message events → append to feed
    const onMsg = (p) => {
      if (!p || p.lab_id !== selectedLabId) return;
      if (p.content || p.message_type) {
        setMessages(prev => [...prev.slice(-300), {
          id: p.id || Date.now().toString(),
          iteration: p.iteration || 0,
          sender_type: p.sender_type || '',
          sender_name: p.sender_name || p.agent || '',
          content: p.content || '',
          message_type: p.message_type || 'message',
          model_used: p.model_used,
          provider_used: p.provider_used,
          tokens_in: p.tokens_in || 0,
          tokens_out: p.tokens_out || 0,
          duration_ms: p.duration_ms || 0,
          tool_name: p.tool_name,
          created_at: p.created_at || new Date().toISOString(),
        }]);
      }
    };

    // Track active agents
    const onTaskStart = (p) => {
      if (p?.lab_id !== selectedLabId) return;
      if (p.agent) setActiveAgents(prev => new Set(prev).add(p.agent));
    };
    const onTaskEnd = (p) => {
      if (p?.lab_id !== selectedLabId) return;
      if (p.agent) setActiveAgents(prev => { const s = new Set(prev); s.delete(p.agent); return s; });
    };

    // Lab status changes
    const onLabStatus = (p) => {
      if (!p?.lab_id) return;
      setLabs(prev => prev.map(l => l.id === p.lab_id ? { ...l, status: p.status || l.status } : l));
    };

    // File events
    const onFile = (p) => {
      if (p?.lab_id !== selectedLabId) return;
      setResources(prev => [...prev, {
        id: Date.now().toString(),
        filename: p.path || '',
        original_name: (p.path || '').split('/').pop(),
        content_type: '',
        size_bytes: p.size_bytes || 0,
        resource_type: 'output',
      }]);
      // Also add as message
      onMsg({ ...p, message_type: 'file_event', content: `File ${p.action}: ${p.path} (${formatBytes(p.size_bytes)})` });
    };

    // Metrics update
    const onMetrics = (p) => {
      if (p?.server) {
        setMetrics(prev => ({ ...prev, [p.server]: p.metrics || p }));
      }
    };

    // Server status
    const onServerStatus = (p) => {
      if (!p?.server) return;
      setServers(prev => prev.map(s => s.name === p.server ? { ...s, status: p.status || s.status } : s));
    };

    const events = [
      ['lab.orchestrator.message', onMsg],
      ['lab.agent.message', onMsg],
      ['lab.task.start', onMsg],
      ['lab.task.complete', onMsg],
      ['lab.task.error', onTaskEnd],
      ['lab.tool.result', onMsg],
      ['lab.file.event', onFile],
      ['lab.started', onLabStatus],
      ['lab.completed', onLabStatus],
      ['lab.paused', onLabStatus],
      ['lab.resumed', onLabStatus],
      ['lab.error', onLabStatus],
      ['lab.iteration', (p) => {
        if (p?.lab_id === selectedLabId) {
          setLabs(prev => prev.map(l => l.id === p.lab_id ? { ...l, current_iteration: p.iteration } : l));
        }
      }],
      ['metrics.update', onMetrics],
      ['server.status', onServerStatus],
    ];

    // Also catch generic lab.agent.call / message events
    const onGenericLab = (data) => {
      if (!data?.payload || data.payload.lab_id !== selectedLabId) return;
      const p = data.payload;
      if (data.type?.startsWith('lab.') && p.content) {
        onMsg({ ...p, message_type: data.type.replace('lab.', '') });
      }
    };
    handlers.push(wsService.on('message', onGenericLab));

    events.forEach(([evt, fn]) => {
      handlers.push(wsService.on(evt, fn));
    });

    return () => handlers.forEach(unsub => unsub());
  }, [selectedLabId]);

  // Derive messages per actor
  const orchMessages = messages.filter(m => m.sender_type === 'orchestrator' || m.sender_type === 'system');
  const agentMsgMap = {};
  if (labDetail?.agents) {
    labDetail.agents.forEach(a => { agentMsgMap[a.name] = []; });
  }
  messages.forEach(m => {
    if (m.sender_name && agentMsgMap[m.sender_name] !== undefined) {
      agentMsgMap[m.sender_name].push(m);
    } else if (m.sender_type === 'agent' && m.sender_name) {
      if (!agentMsgMap[m.sender_name]) agentMsgMap[m.sender_name] = [];
      agentMsgMap[m.sender_name].push(m);
    }
  });

  // Sort agents: most recently active first
  const agentEntries = Object.entries(agentMsgMap).sort((a, b) => {
    const lastA = a[1].length ? Math.max(...a[1].map(m => new Date(m.created_at).getTime())) : 0;
    const lastB = b[1].length ? Math.max(...b[1].map(m => new Date(m.created_at).getTime())) : 0;
    return lastB - lastA;
  });
  const selectedLab = labs.find(l => l.id === selectedLabId);
  const isRunning = selectedLab?.status === 'running';

  return (
    <div className="lp-live-page">
      <Scanlines />

      {/* ── Header ──────────────────────────── */}
      <div className="lp-live-header">
        <Link to="/" className="lp-live-brand">
          <span className="lp-live-brand-glyph">◆</span> Bob Labs Live
        </Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {selectedLab && (
            <span className="lp-live-headinfo">
              Viewing: <span className="accent" style={{ color: statusColor(selectedLab.status) }}>{selectedLab.name}</span>
              {' '}· {selectedLab.status}
            </span>
          )}
          <Link to="/" className="lp-live-back">← Back to site</Link>
        </div>
      </div>

      {/* ── View toggle ─────────────────────── */}
      <div className="lp-live-viewtoggle">
        <button onClick={() => setViewMode('cards')} className={`lp-live-vtbtn${viewMode === 'cards' ? ' active' : ''}`}>
          ◫ Cards
        </button>
        <button onClick={() => setViewMode('feed')} className={`lp-live-vtbtn${viewMode === 'feed' ? ' active' : ''}`}>
          ▤ Feed
        </button>
      </div>

      {/* ── Body ────────────────────────────── */}
      <div className="lp-live-body">

        {/* ── LEFT SIDEBAR: Servers & Providers ── */}
        <div className="lp-live-sidebar">
          <div className="lp-live-sidebartitle">Servers</div>
          <div className="lp-live-sidebarlist">
            {servers.length === 0 && (
              <div style={{ padding: '16px', color: '#4a5263', fontSize: '11px' }}>No servers</div>
            )}
            {servers.map(s => (
              <ServerItem key={s.id} server={s} metrics={metrics[s.name]} />
            ))}
          </div>

          <div className="lp-live-sidebartitle">Models ({models.length})</div>
          <div className="lp-live-sidebarlist">
            {models.length === 0 && (
              <div style={{ padding: '16px', color: '#4a5263', fontSize: '11px' }}>No models</div>
            )}
            {models.map(m => (
              <ModelItem key={m.model_identifier} model={m} />
            ))}
          </div>
        </div>

        {/* ── CENTER: Cards & Files ────────── */}
        <div className="lp-live-center">
          {!selectedLabId ? (
            <div className="lp-empty">Select a lab from the right panel</div>
          ) : !labDetail ? (
            <div className="lp-empty">Loading</div>
          ) : viewMode === 'feed' ? (
            <UnifiedFeed messages={messages} labDetail={labDetail} />
          ) : (
            <>
              {/* Cards grid: orchestrator left, agents right */}
              <div className="lp-live-cards-area">
                {/* Orchestrator column */}
                <div className="lp-live-orch-col">
                  <ActorCard
                    name="Orchestrator"
                    modelName={labDetail.orchestrator_model_name}
                    isOrchestrator
                    messages={orchMessages}
                  />
                </div>

                {/* Agent column */}
                <div className="lp-live-agent-col">
                  {agentEntries.length > 0 ? agentEntries.map(([agentName, agentMsgs]) => {
                    const agentInfo = labDetail.agents?.find(a => a.name === agentName);
                    return (
                      <ActorCard
                        key={agentName}
                        name={agentName}
                        modelName={agentInfo?.model_name}
                        isOrchestrator={false}
                        messages={agentMsgs}
                      />
                    );
                  }) : labDetail.agents?.map(a => (
                    <ActorCard
                      key={a.id}
                      name={a.name}
                      modelName={a.model_name}
                      isOrchestrator={false}
                      messages={[]}
                    />
                  ))}
                </div>
              </div>

              {/* Files section */}
              <FilesSection resources={resources} messages={messages} labId={selectedLabId} onFileClick={setViewingFile} />
            </>
          )}
        </div>

        {/* ── RIGHT SIDEBAR: Labs ────────── */}
        {(() => {
          const visibleLabs = labs.filter(l => !isHiddenAppLab(l));
          return (
            <div className="lp-live-sidebar right">
              <div className="lp-live-sidebartitle">Labs</div>
              <div className="lp-live-sidebarlist">
                {visibleLabs.length === 0 && (
                  <div style={{ padding: '16px', color: '#4a5263', fontSize: '11px' }}>No labs available</div>
                )}
                {visibleLabs.map(l => (
                  <LabItem
                    key={l.id}
                    lab={l}
                    active={l.id === selectedLabId}
                    onSelect={() => setSelectedLabId(l.id)}
                  />
                ))}
              </div>
            </div>
          );
        })()}
      </div>

      {/* ── File Viewer Modal ────────── */}
      {viewingFile && selectedLabId && (
        <TerminalFileViewer
          file={viewingFile}
          labId={selectedLabId}
          onClose={() => setViewingFile(null)}
        />
      )}
    </div>
  );
}
