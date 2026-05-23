/**
 * Bob Manager — Commands page for remote execution.
 */

import React, { useState, useEffect, useRef } from 'react';
import { getServers, executeCommand, executeBatchCommand } from '../services/api';
import StatusBadge from '../components/common/StatusBadge';
import { IC } from '../components/common/Icons';
import { InfraRestrictedMessage, isInfraRestricted } from '../components/common/InfraRestricted';
import wsService from '../services/websocket';

export default function CommandsPage() {
  const [servers, setServers] = useState([]);
  const [command, setCommand] = useState('');
  const [selectedServers, setSelectedServers] = useState([]);
  const [output, setOutput] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [restricted, setRestricted] = useState(false);
  const terminalRef = useRef(null);

  useEffect(() => {
    loadServers();

    const unsubOutput = wsService.on('command.output', (data) => {
      setOutput((prev) => [
        ...prev,
        {
          server: data.server,
          stream: data.stream,
          line: data.line,
        },
      ]);
    });

    const unsubComplete = wsService.on('command.complete', (data) => {
      setOutput((prev) => [
        ...prev,
        {
          server: data.server,
          stream: 'info',
          line: `[${data.server}] Command completed with exit code ${data.exit_code}`,
        },
      ]);
      setIsRunning(false);
    });

    return () => { unsubOutput(); unsubComplete(); };
  }, []);

  useEffect(() => {
    // Auto-scroll terminal
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [output]);

  async function loadServers() {
    try {
      const res = await getServers();
      setServers(res.data);
    } catch (err) {
      if (isInfraRestricted(err)) { setRestricted(true); return; }
      console.error('Failed to load servers:', err);
    }
  }

  if (restricted) return <InfraRestrictedMessage />;

  async function handleExecute(e) {
    e.preventDefault();
    if (!command.trim() || selectedServers.length === 0) return;

    setIsRunning(true);
    setOutput((prev) => [
      ...prev,
      { stream: 'info', line: `$ ${command}  →  [${selectedServers.length} server(s)]` },
    ]);

    try {
      let res;
      if (selectedServers.length === 1) {
        const srv = servers.find((s) => s.id === selectedServers[0]);
        const label = srv ? srv.name : selectedServers[0];
        res = await executeCommand(selectedServers[0], command);
        const r = res.data;
        if (r.stdout) {
          r.stdout.split('\n').filter(Boolean).forEach((line) => {
            setOutput((prev) => [...prev, { server: label, stream: 'stdout', line }]);
          });
        }
        if (r.stderr) {
          r.stderr.split('\n').filter(Boolean).forEach((line) => {
            setOutput((prev) => [...prev, { server: label, stream: 'stderr', line }]);
          });
        }
        setOutput((prev) => [...prev, { server: label, stream: 'info', line: `Exit code: ${r.exit_code}` }]);
        setIsRunning(false);
      } else {
        res = await executeBatchCommand(selectedServers, command);
        (res.data || []).forEach((r) => {
          const label = r.server_name || '?';
          if (r.stdout) {
            r.stdout.split('\n').filter(Boolean).forEach((line) => {
              setOutput((prev) => [...prev, { server: label, stream: 'stdout', line }]);
            });
          }
          if (r.stderr) {
            r.stderr.split('\n').filter(Boolean).forEach((line) => {
              setOutput((prev) => [...prev, { server: label, stream: 'stderr', line }]);
            });
          }
          setOutput((prev) => [...prev, { server: label, stream: 'info', line: `Exit code: ${r.exit_code}` }]);
        });
        setIsRunning(false);
      }
    } catch (err) {
      setOutput((prev) => [
        ...prev,
        { stream: 'stderr', line: `Error: ${err.response?.data?.detail || err.message}` },
      ]);
      setIsRunning(false);
    }
  }

  function toggleServer(id) {
    setSelectedServers((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  }

  function selectAll() {
    setSelectedServers(servers.map((s) => s.id));
  }

  return (
    <div>
      <div className="page-header">
        <h1>Remote Commands</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-outline" onClick={selectAll}>Select All</button>
          <button className="btn btn-outline" onClick={() => setSelectedServers([])}>Deselect All</button>
          <button className="btn btn-outline" onClick={() => setOutput([])}>Clear Output</button>
        </div>
      </div>

      {/* Server selector */}
      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '0.875rem', marginBottom: '0.5rem' }}>Target Servers</h3>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          {servers.map((s) => (
            <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.875rem' }}>
              <input
                type="checkbox"
                checked={selectedServers.includes(s.id)}
                onChange={() => toggleServer(s.id)}
                style={{ width: 'auto' }}
              />
              {s.name}
              <StatusBadge status={s.status} />
            </label>
          ))}
          {servers.length === 0 && (
            <span style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>No servers available</span>
          )}
        </div>
      </div>

      {/* Command input */}
      <div className="card" style={{ marginBottom: '1rem' }}>
        <form onSubmit={handleExecute} style={{ display: 'flex', gap: '0.75rem' }}>
          <input
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="Enter command (e.g., nvidia-smi, df -h, uptime)"
            style={{ flex: 1, fontFamily: 'monospace' }}
            disabled={isRunning}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isRunning || !command.trim() || selectedServers.length === 0}
          >
            {isRunning ? <><IC.loader size={14} /> Running…</> : <><IC.play size={14} /> Execute</>}
          </button>
        </form>
      </div>

      {/* Output terminal */}
      <div className="card">
        <div className="card-header">
          <h3>Output</h3>
        </div>
        <div className="terminal" ref={terminalRef}>
          {output.length === 0 && (
            <span style={{ color: 'var(--text-muted)' }}>Command output will appear here…</span>
          )}
          {output.map((line, i) => (
            <div key={i} className={line.stream || 'stdout'}>
              {line.server && <span style={{ color: '#fbbf24' }}>[{line.server}] </span>}
              {line.line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
