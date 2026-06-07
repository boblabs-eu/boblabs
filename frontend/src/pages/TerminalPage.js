/**
 * Bob Manager — Multi-Terminal page.
 * Grid of terminals (2 per row). Each can connect to a different server.
 * Lock/sync mode: when locked, keystrokes are sent to ALL connected terminals.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { getServers } from '../services/api';
import StatusBadge from '../components/common/StatusBadge';
import { IC } from '../components/common/Icons';
import { InfraRestrictedMessage, isInfraRestricted } from '../components/common/InfraRestricted';
import wsService from '../services/websocket';

const XTERM_THEME = {
  background: '#1c1917',
  foreground: '#f5f5f4',
  cursor: '#f87171',
  selectionBackground: '#44403c',
  black: '#1c1917', red: '#ef4444', green: '#22c55e', yellow: '#fbbf24',
  blue: '#f87171', magenta: '#a855f7', cyan: '#f59e0b', white: '#f5f5f4',
  brightBlack: '#78716c', brightRed: '#f87171', brightGreen: '#4ade80', brightYellow: '#fbbf24',
  brightBlue: '#fca5a5', brightMagenta: '#c084fc', brightCyan: '#fbbf24', brightWhite: '#fafaf9',
};

// U06 — `termIdCounter` used to live at module scope. Under React 18
// StrictMode the component mounts twice on dev; the module-level
// counter persisted across remounts and produced colliding ids on
// fast HMR cycles. Moving it into a component-scoped ref keeps each
// TerminalPage instance isolated.
export default function TerminalPage() {
  const [servers, setServers] = useState([]);
  const [locked, setLocked] = useState(false);
  const [terminals, setTerminals] = useState([]);
  const [restricted, setRestricted] = useState(false);
  const [loading, setLoading] = useState(true);
  const termsRef = useRef({}); // termId -> { xterm, fitAddon, sessionId, serverId, ro, disposed }
  const termIdRef = useRef(0); // U06 — per-instance, replaces module-level counter
  const lockedRef = useRef(false);
  const termsRefForLock = useRef(termsRef); // alias for closure
  termsRefForLock.current = termsRef;

  useEffect(() => { lockedRef.current = locked; }, [locked]);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        const res = await getServers();
        if (cancelled) return;
        setServers(res.data);
      } catch (err) {
        if (cancelled) return;
        if (isInfraRestricted(err)) { setRestricted(true); setLoading(false); return; }
        console.error(err);
      }
      setLoading(false);
      addTerminalSlot();
    }

    init();

    // WS listeners
    const unsubSessionId = wsService.on('terminal.session_id', (data) => {
      const entry = Object.values(termsRef.current).find((t) => t._pendingServer === data.server_name || (!t.sessionId && t._connecting));
      if (entry) {
        entry.sessionId = data.session_id;
        entry._connecting = false;
      }
    });

    const unsubOpened = wsService.on('terminal.opened', (data) => {
      // Find the terminal entry that matches
      const entry = Object.values(termsRef.current).find((t) => t.sessionId === data.session_id || t._pendingServer);
      if (entry && entry.xterm) {
        entry._connecting = false;
        entry._pendingServer = null;
        entry.xterm.writeln('\r\n\x1b[32mTerminal session connected.\x1b[0m\r\n');
        entry.xterm.focus();
        if (entry.fitAddon) try { entry.fitAddon.fit(); } catch (_) {}
        // Force react re-render
        setTerminals((prev) => [...prev]);
      }
    });

    const unsubOutput = wsService.on('terminal.output', (data) => {
      const entry = Object.values(termsRef.current).find((t) => t.sessionId === data.session_id);
      if (entry && entry.xterm) {
        entry.xterm.write(data.data);
      }
    });

    const unsubError = wsService.on('terminal.error', (data) => {
      const entry = Object.values(termsRef.current).find((t) => t._connecting);
      if (entry && entry.xterm) {
        entry._connecting = false;
        entry.xterm.writeln(`\r\n\x1b[31mError: ${data.error}\x1b[0m\r\n`);
        setTerminals((prev) => [...prev]);
      }
    });

    return () => {
      cancelled = true;
      unsubSessionId(); unsubOpened(); unsubOutput(); unsubError();
      // Cleanup all terminals
      Object.values(termsRef.current).forEach((t) => {
        if (t.sessionId) wsService.send({ type: 'terminal.close', payload: { session_id: t.sessionId } });
        if (t.ro) t.ro.disconnect();
        if (t.xterm && !t.disposed) { t.xterm.dispose(); t.disposed = true; }
      });
      termsRef.current = {};
    };
  }, []);

  const initTerminal = useCallback((termId, containerEl) => {
    if (!containerEl || termsRef.current[termId]?.xterm) return;
    const entry = termsRef.current[termId];
    if (!entry) return;

    const term = new Terminal({
      cursorBlink: true, fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      theme: XTERM_THEME, scrollback: 10000, allowProposedApi: true,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.open(containerEl);
    fitAddon.fit();

    const ro = new ResizeObserver(() => {
      try { fitAddon.fit(); } catch (_) {}
    });
    ro.observe(containerEl);

    term.writeln('\x1b[36m── Bob Terminal ──\x1b[0m');
    term.writeln('Select a server and click Connect.');
    term.writeln('');

    term.onData((data) => {
      if (lockedRef.current) {
        // Send to ALL connected terminals
        Object.values(termsRef.current).forEach((t) => {
          if (t.sessionId) {
            wsService.send({ type: 'terminal.input', payload: { session_id: t.sessionId, data } });
          }
        });
      } else {
        if (entry.sessionId) {
          wsService.send({ type: 'terminal.input', payload: { session_id: entry.sessionId, data } });
        }
      }
    });

    entry.xterm = term;
    entry.fitAddon = fitAddon;
    entry.ro = ro;
  }, []);

  if (restricted) return <InfraRestrictedMessage />;
  if (loading) return <div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Loading…</div>;

  function addTerminalSlot() {
    termIdRef.current += 1;
    const id = termIdRef.current;
    setTerminals((prev) => [...prev, { id, serverId: null }]);
    termsRef.current[id] = { xterm: null, fitAddon: null, sessionId: null, serverId: null, ro: null, disposed: false, _connecting: false, _pendingServer: null };
    return id;
  }

  function removeTerminal(termId) {
    const entry = termsRef.current[termId];
    if (entry) {
      if (entry.sessionId) wsService.send({ type: 'terminal.close', payload: { session_id: entry.sessionId } });
      if (entry.ro) entry.ro.disconnect();
      if (entry.xterm && !entry.disposed) { entry.xterm.dispose(); entry.disposed = true; }
      delete termsRef.current[termId];
    }
    setTerminals((prev) => prev.filter((t) => t.id !== termId));
  }

  function connectTerminal(termId) {
    const entry = termsRef.current[termId];
    const termState = terminals.find((t) => t.id === termId);
    if (!entry || !termState || !termState.serverId) return;
    const server = servers.find((s) => s.id === termState.serverId);
    if (!server) return;

    // Close existing session
    if (entry.sessionId) {
      wsService.send({ type: 'terminal.close', payload: { session_id: entry.sessionId } });
      entry.sessionId = null;
    }

    entry._connecting = true;
    entry._pendingServer = server.name;
    entry.serverId = termState.serverId;

    if (entry.xterm) {
      entry.xterm.clear();
      entry.xterm.writeln(`\x1b[33mConnecting to ${server.name}...\x1b[0m\r\n`);
    }

    const cols = entry.xterm?.cols || 120;
    const rows = entry.xterm?.rows || 30;

    wsService.send({
      type: 'terminal.open',
      payload: { server_name: server.name, cols, rows },
    });

    setTerminals((prev) => [...prev]);
  }

  function disconnectTerminal(termId) {
    const entry = termsRef.current[termId];
    if (entry && entry.sessionId) {
      wsService.send({ type: 'terminal.close', payload: { session_id: entry.sessionId } });
      entry.sessionId = null;
      entry._connecting = false;
      if (entry.xterm) entry.xterm.writeln('\r\n\x1b[31mSession closed.\x1b[0m');
      setTerminals((prev) => [...prev]);
    }
  }

  function setTerminalServer(termId, serverId) {
    setTerminals((prev) => prev.map((t) => t.id === termId ? { ...t, serverId } : t));
  }

  const onlineServers = servers.filter((s) => s.status === 'online');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 1rem)', maxHeight: 'calc(100vh - 1rem)' }}>
      <div className="page-header" style={{ flexShrink: 0 }}>
        <h1>Terminal</h1>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button
            className={locked ? 'btn btn-primary' : 'btn btn-outline'}
            onClick={() => setLocked(!locked)}
            title={locked ? 'Input is synced to ALL connected terminals (mass-administration mode — see the banner below)' : 'Input goes to focused terminal only'}
          >
            {locked ? <><IC.lock size={14} /> Synced</> : <><IC.unlock size={14} /> Independent</>}
          </button>
          <button className="btn btn-outline" onClick={() => addTerminalSlot()}>+ Add Terminal</button>
        </div>
      </div>
      {/* U05 — when lock mode is on and connected terminals span more
          than one server, render a prominent banner. The behaviour is
          intentional ("mass-administration mode") but the audit flagged
          that a user hitting `rm -rf /` while locked could hit several
          servers without realising. The banner makes the blast radius
          visible. */}
      {locked && (() => {
        const connectedServers = new Set(
          terminals
            .map((t) => termsRef.current[t.id]?.serverId)
            .filter((sid) => sid != null),
        );
        if (connectedServers.size < 2) return null;
        return (
          <div style={{
            margin: '0.25rem 0', padding: '0.5rem 0.75rem',
            background: 'rgba(248, 113, 113, 0.12)',
            border: '1px solid rgba(248, 113, 113, 0.45)',
            borderRadius: 'var(--radius)', color: 'var(--text)',
            fontSize: '0.85rem',
          }}>
            <strong>⚠ Mass-administration mode</strong> — keystrokes go to
            all <strong>{connectedServers.size}</strong> connected servers.
            Destructive commands hit every one. Toggle <em>Independent</em>
            to scope to the focused pane.
          </div>
        );
      })()}

      <div style={{
        flex: 1, minHeight: 0, overflowY: 'auto',
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem',
      }}>
        {terminals.map((t) => {
          const entry = termsRef.current[t.id];
          const isConnected = entry?.sessionId != null;
          const isConnecting = entry?._connecting;
          return (
            <div key={t.id} style={{
              display: 'flex', flexDirection: 'column',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              overflow: 'hidden', minHeight: '250px',
            }}>
              {/* Terminal toolbar */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.3rem 0.5rem',
                background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)', flexShrink: 0,
              }}>
                <select
                  value={t.serverId || ''}
                  onChange={(e) => setTerminalServer(t.id, e.target.value || null)}
                  style={{ width: 150, fontSize: '0.8rem', padding: '0.25rem 0.4rem' }}
                >
                  <option value="">Server…</option>
                  {onlineServers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                {!isConnected ? (
                  <button className="btn btn-primary" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                    onClick={() => connectTerminal(t.id)} disabled={!t.serverId || isConnecting}>
                    {isConnecting ? '⏳' : '▶'} Connect
                  </button>
                ) : (
                  <button className="btn btn-danger" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                    onClick={() => disconnectTerminal(t.id)}>
                    <IC.close size={14} /> Disconnect
                  </button>
                )}
                {isConnected && <StatusBadge status="online" />}
                <div style={{ flex: 1 }} />
                {terminals.length > 1 && (
                  <button onClick={() => removeTerminal(t.id)}
                    style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.85rem' }}
                    title="Remove terminal"><IC.trash size={14} /></button>
                )}
              </div>
              {/* Terminal container */}
              <div
                ref={(el) => initTerminal(t.id, el)}
                onClick={() => termsRef.current[t.id]?.xterm?.focus()}
                style={{
                  flex: 1, minHeight: 0, backgroundColor: '#0f172a',
                  padding: '0.25rem', overflow: 'hidden',
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
