/**
 * Bob Manager — Logs viewer page.
 */

import React, { useState, useEffect, useRef } from 'react';
import wsService from '../services/websocket';
import { getServers } from '../services/api';
import { InfraRestrictedMessage, isInfraRestricted } from '../components/common/InfraRestricted';

export default function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState('all');
  const [restricted, setRestricted] = useState(false);
  const terminalRef = useRef(null);

  useEffect(() => {
    getServers().catch((err) => {
      if (isInfraRestricted(err)) setRestricted(true);
    });

    const unsubMessage = wsService.on('message', (data) => {
      setLogs((prev) => [
        ...prev.slice(-500), // Keep last 500 entries
        {
          type: data.type,
          timestamp: new Date().toISOString(),
          payload: data.payload,
        },
      ]);
    });

    return () => unsubMessage();
  }, []);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  const filtered = filter === 'all'
    ? logs
    : logs.filter((l) => l.type.includes(filter));

  if (restricted) return <InfraRestrictedMessage />;

  return (
    <div>
      <div className="page-header">
        <h1>Live Logs</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }}>
            <option value="all">All Events</option>
            <option value="metrics">Metrics</option>
            <option value="command">Commands</option>
            <option value="workflow">Workflows</option>
            <option value="server">Server Status</option>
          </select>
          <button className="btn btn-outline" onClick={() => setLogs([])}>Clear</button>
        </div>
      </div>

      <div className="card">
        <div className="terminal" ref={terminalRef} style={{ maxHeight: '70vh', minHeight: '400px' }}>
          {filtered.length === 0 && (
            <span style={{ color: 'var(--text-muted)' }}>
              Waiting for events… Connect agents to see live logs.
            </span>
          )}
          {filtered.map((log, i) => (
            <div key={i} style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
              <span style={{ color: '#64748b' }}>
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              {' '}
              <span style={{ color: '#fbbf24', fontWeight: 600 }}>[{log.type}]</span>
              {' '}
              <span style={{ color: '#e2e8f0' }}>
                {JSON.stringify(log.payload).substring(0, 200)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
