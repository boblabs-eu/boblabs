/**
 * Bob Manager — Metrics Servers page (merged with the old Servers page).
 *
 * Combines server CRUD (add / remove) with live per-server metrics. Compact
 * rows show CPU/GPU %/°C, RAM %, Disk %. Expanding a server reveals its host
 * info + heartbeat + full metrics breakdown (temps, GPUs, disks, docker,
 * services, processes, listening ports).
 */

import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getServers, getAllMetrics, createServer, deleteServer } from '../services/api';
import { IC } from '../components/common/Icons';
import ProgressBar from '../components/common/ProgressBar';
import StatusBadge from '../components/common/StatusBadge';
import wsService from '../services/websocket';
import { InfraRestrictedMessage, isInfraRestricted } from '../components/common/InfraRestricted';
import './DashboardPage.css'; // shared `.dash-*` utilities (cards, status pills, color modifiers)
import './MetricsPage.css';

export default function MetricsPage() {
  const [searchParams] = useSearchParams();
  const [servers, setServers] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [expandedServers, setExpandedServers] = useState({});
  const [expandedSections, setExpandedSections] = useState({});
  const [restricted, setRestricted] = useState(false);

  // Add-server inline form
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState({ name: '', host: '', port: 9100 });

  useEffect(() => {
    loadData();
    const unsub = wsService.on('metrics.update', (data) => {
      setMetrics((prev) => ({ ...prev, [data.server]: data.metrics }));
    });
    return () => unsub();
  }, []);

  useEffect(() => {
    const expandId = searchParams.get('expand');
    if (expandId) {
      setExpandedServers((prev) => ({ ...prev, [expandId]: true }));
    }
  }, [searchParams]);

  async function loadData() {
    try {
      const [srvRes, metRes] = await Promise.all([getServers(), getAllMetrics()]);
      setServers(srvRes.data);
      setMetrics(metRes.data);
    } catch (err) {
      if (isInfraRestricted(err)) { setRestricted(true); return; }
      console.error('Failed to load metrics:', err);
    }
  }

  if (restricted) return <InfraRestrictedMessage />;

  async function handleAddServer(e) {
    e.preventDefault();
    try {
      await createServer(addForm);
      setAddForm({ name: '', host: '', port: 9100 });
      setShowAddForm(false);
      loadData();
    } catch (err) {
      alert('Failed to create server: ' + (err.response?.data?.detail || err.message));
    }
  }

  async function handleDeleteServer(id, name) {
    if (!window.confirm(`Remove server "${name}"?`)) return;
    try {
      await deleteServer(id);
      loadData();
    } catch (err) {
      alert('Failed to delete server');
    }
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`;
  }

  function tempClass(temp) {
    if (temp == null) return 'met-use-muted';
    if (temp >= 80) return 'met-temp-high';
    if (temp >= 60) return 'met-temp-mid';
    return 'met-temp-low';
  }

  function usageClass(pct) {
    if (pct == null) return 'met-use-muted';
    if (pct >= 90) return 'met-use-high';
    if (pct >= 70) return 'met-use-mid';
    return 'met-use-ok';
  }

  function toggleServer(serverId) {
    setExpandedServers((prev) => ({ ...prev, [serverId]: !prev[serverId] }));
  }

  function toggleSection(serverId, section) {
    const key = `${serverId}-${section}`;
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function isSectionOpen(serverId, section) {
    return expandedSections[`${serverId}-${section}`] ?? false;
  }

  function expandAll() {
    const all = {};
    servers.forEach((s) => { all[s.id] = true; });
    setExpandedServers(all);
  }

  function collapseAll() {
    setExpandedServers({});
  }

  /* ── Compact summary row (collapsed) ── */
  function renderCompactCells(server, m) {
    const gpuMetrics = m.gpu_metrics || [];
    const disks = m.disks || [];
    const primaryDisk = disks.find((d) => d.mountpoint === '/') || disks[0];
    const cpuPct = m.cpu_usage ?? null;
    const cpuTemp = m.cpu_temperature ?? null;
    const ramPct = m.ram_percent ?? null;
    const diskPct = primaryDisk?.percent ?? null;

    return (
      <>
        <div className="met-cell">
          <div className="met-cell-label">CPU</div>
          <div className={`met-cell-value ${cpuTemp != null ? tempClass(cpuTemp) : usageClass(cpuPct)}`}>
            {cpuPct != null ? `${cpuPct.toFixed(0)}%` : '—'}
            {cpuTemp != null && (
              <span className={`met-temp-suffix ${tempClass(cpuTemp)}`}>{cpuTemp.toFixed(0)}°</span>
            )}
          </div>
        </div>

        {gpuMetrics.slice(0, 4).map((gpu, i) => (
          <div key={i} className="met-cell">
            <div className="met-cell-label">GPU{gpu.index}</div>
            <div className={`met-cell-value ${gpu.temperature_c != null ? tempClass(gpu.temperature_c) : usageClass(gpu.gpu_usage_percent)}`}>
              {gpu.gpu_usage_percent != null ? `${gpu.gpu_usage_percent.toFixed(0)}%` : '—'}
              {gpu.temperature_c != null && (
                <span className={`met-temp-suffix ${tempClass(gpu.temperature_c)}`}>{gpu.temperature_c.toFixed(0)}°</span>
              )}
            </div>
          </div>
        ))}

        <div className="met-cell">
          <div className="met-cell-label">RAM</div>
          <div className={`met-cell-value ${usageClass(ramPct)}`}>
            {ramPct != null ? `${ramPct.toFixed(0)}%` : '—'}
          </div>
        </div>

        <div className="met-cell">
          <div className="met-cell-label">Disk</div>
          <div className={`met-cell-value ${usageClass(diskPct)}`}>
            {diskPct != null ? `${diskPct.toFixed(0)}%` : '—'}
          </div>
        </div>
      </>
    );
  }

  /* ── Expanded detail view ── */
  function renderExpandedDetail(server, m) {
    const gpuMetrics = m.gpu_metrics || [];
    const disks = m.disks || [];
    const topProcs = m.top_processes || [];
    const dockerContainers = m.docker_containers || [];
    const runningServices = m.running_services || [];
    const failedServices = m.failed_services || [];
    const ports = m.listening_ports || [];

    const gpuList = server.gpu_info?.gpus?.length
      ? server.gpu_info.gpus.map((g) => g.name).join(', ')
      : '—';
    const osLabel = server.os_info?.linux_distro || server.os_info?.system || '—';

    return (
      <div className="met-expanded">
        {/* ── Server info (formerly the Servers page) ── */}
        <div className="met-info-grid">
          <div className="met-info-item">
            <span className="met-info-label">Host</span>
            <span className="met-info-value">{server.host}:{server.port}</span>
          </div>
          <div className="met-info-item">
            <span className="met-info-label">OS</span>
            <span className="met-info-value">{osLabel}</span>
          </div>
          <div className="met-info-item">
            <span className="met-info-label">GPUs</span>
            <span className="met-info-value">{gpuList}</span>
          </div>
          <div className="met-info-item">
            <span className="met-info-label">Last Heartbeat</span>
            <span className="met-info-value">
              {server.last_heartbeat ? new Date(server.last_heartbeat).toLocaleString() : '—'}
            </span>
          </div>
          <div className="met-info-actions">
            <button
              className="met-btn-remove"
              onClick={(e) => { e.stopPropagation(); handleDeleteServer(server.id, server.name); }}
              title="Remove this server"
            >
              <IC.trash size={13} /> Remove
            </button>
          </div>
        </div>

        {/* ── Temperatures ── */}
        <div className="met-temp-row">
          <div className="met-temp-tile">
            <div className="met-temp-tile-label">CPU Temp</div>
            <div className={`met-temp-tile-value ${tempClass(m.cpu_temperature)}`}>
              {m.cpu_temperature != null ? `${m.cpu_temperature.toFixed(0)}°C` : '—'}
            </div>
          </div>
          {gpuMetrics.map((gpu, i) => (
            <div key={i} className="met-temp-tile">
              <div className="met-temp-tile-label">GPU {gpu.index} Temp</div>
              <div className={`met-temp-tile-value ${tempClass(gpu.temperature_c)}`}>
                {gpu.temperature_c != null ? `${gpu.temperature_c.toFixed(0)}°C` : '—'}
              </div>
            </div>
          ))}
        </div>

        {/* ── CPU / RAM / Network Stats ── */}
        <div className="met-stat-strip">
          <div className="met-stat">
            <div className="met-stat-label">CPU Usage</div>
            <div className="met-stat-value">{(m.cpu_usage || 0).toFixed(1)}%</div>
          </div>
          <div className="met-stat">
            <div className="met-stat-label">RAM</div>
            <div className="met-stat-value">{(m.ram_percent || 0).toFixed(1)}%</div>
            <div className="met-stat-sub">
              {formatBytes(m.ram_used)} / {formatBytes(m.ram_total)}
            </div>
          </div>
          <div className="met-stat">
            <div className="met-stat-label">Net Sent</div>
            <div className="met-stat-value" style={{ fontSize: '1.2rem' }}>{formatBytes(m.network_bytes_sent)}</div>
          </div>
          <div className="met-stat">
            <div className="met-stat-label">Net Recv</div>
            <div className="met-stat-value" style={{ fontSize: '1.2rem' }}>{formatBytes(m.network_bytes_recv)}</div>
          </div>
        </div>

        {/* ── Progress Bars ── */}
        <div className="met-bars">
          <ProgressBar value={m.cpu_usage || 0} label="CPU Usage" color="blue" />
          <ProgressBar value={m.ram_percent || 0} label="RAM Usage" color="green" />
        </div>

        {/* ── GPUs ── */}
        {gpuMetrics.length > 0 && (
          <div className="met-gpu-grid">
            {gpuMetrics.map((gpu, i) => (
              <div key={i} className="met-gpu-card">
                <div className="met-gpu-card-header">
                  <span className="met-gpu-card-name">GPU {gpu.index} {gpu.name ? `— ${gpu.name}` : ''}</span>
                  <span className={`met-gpu-card-temp ${tempClass(gpu.temperature_c)}`}>
                    {gpu.temperature_c != null ? `${gpu.temperature_c.toFixed(0)}°C` : ''}
                  </span>
                </div>
                <ProgressBar value={gpu.gpu_usage_percent || 0} label="Compute" />
                {gpu.memory_total_mb && (
                  <div style={{ marginTop: '0.35rem' }}>
                    <ProgressBar
                      value={gpu.memory_total_mb ? ((gpu.memory_used_mb || 0) / gpu.memory_total_mb * 100) : 0}
                      label={`VRAM — ${gpu.memory_used_mb || 0} MB / ${gpu.memory_total_mb} MB`}
                      color="blue"
                    />
                  </div>
                )}
                <div className="met-gpu-card-power">
                  Power: {gpu.power_draw_w != null ? `${gpu.power_draw_w}W` : '—'} / {gpu.power_limit_w != null ? `${gpu.power_limit_w}W` : '—'}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Disks ── */}
        <div className="met-sub-header" onClick={() => toggleSection(server.id, 'disks')}>
          <span className="met-sub-title"><IC.hardDrive size={14} /> Disks ({disks.length})</span>
          <span className="met-sub-chevron">
            {isSectionOpen(server.id, 'disks') ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
          </span>
        </div>
        {isSectionOpen(server.id, 'disks') && disks.length > 0 && (
          <div className="met-bars">
            {disks.map((d, i) => (
              <ProgressBar
                key={i}
                value={d.percent || 0}
                label={`${d.device} (${d.mountpoint}) — ${formatBytes(d.used)} / ${formatBytes(d.total)}`}
                color="yellow"
              />
            ))}
          </div>
        )}

        {/* ── Docker Containers ── */}
        <div className="met-sub-header" onClick={() => toggleSection(server.id, 'docker')}>
          <span className="met-sub-title">
            <IC.docker size={14} /> Docker ({m.docker_running_count || 0} running / {m.docker_total_count || 0} total)
          </span>
          <span className="met-sub-chevron">
            {isSectionOpen(server.id, 'docker') ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
          </span>
        </div>
        {isSectionOpen(server.id, 'docker') && dockerContainers.length > 0 && (
          <div className="table-container">
            <table>
              <thead>
                <tr><th>Name</th><th>Image</th><th>Status</th><th>Ports</th></tr>
              </thead>
              <tbody>
                {dockerContainers.map((c, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{c.name}</td>
                    <td>{c.image}</td>
                    <td>
                      <span className={`dash-status-pill ${c.state === 'running' ? 'is-success' : 'is-error'}`}>
                        <span className="dash-dot" /> {c.status}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.75rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.ports || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Services ── */}
        <div className="met-sub-header" onClick={() => toggleSection(server.id, 'services')}>
          <span className="met-sub-title">
            <IC.settings size={14} /> Services ({m.services_running_count || 0} running
            {m.services_failed_count > 0 && <>, <span className="met-use-high">{m.services_failed_count} failed</span></>})
          </span>
          <span className="met-sub-chevron">
            {isSectionOpen(server.id, 'services') ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
          </span>
        </div>
        {isSectionOpen(server.id, 'services') && (
          <div>
            {failedServices.length > 0 && (
              <div style={{ marginBottom: '0.55rem' }}>
                <div className="met-service-failed-label">Failed:</div>
                <div className="met-service-pills">
                  {failedServices.map((s, i) => (
                    <span key={i} className="met-service-pill is-failed">{s.name}</span>
                  ))}
                </div>
              </div>
            )}
            <div className="met-service-pills">
              {runningServices.map((s, i) => (
                <span key={i} className="met-service-pill">{s.name}</span>
              ))}
            </div>
          </div>
        )}

        {/* ── Top Processes ── */}
        <div className="met-sub-header" onClick={() => toggleSection(server.id, 'procs')}>
          <span className="met-sub-title"><IC.activity size={14} /> Top Processes ({topProcs.length})</span>
          <span className="met-sub-chevron">
            {isSectionOpen(server.id, 'procs') ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
          </span>
        </div>
        {isSectionOpen(server.id, 'procs') && topProcs.length > 0 && (
          <div className="table-container">
            <table>
              <thead>
                <tr><th>PID</th><th>Name</th><th>CPU %</th><th>RAM %</th><th>User</th></tr>
              </thead>
              <tbody>
                {topProcs.map((p, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{p.pid}</td>
                    <td style={{ fontWeight: 500, color: 'var(--text-primary)', maxWidth: '250px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</td>
                    <td className={usageClass(p.cpu_percent)}>{p.cpu_percent?.toFixed(1)}%</td>
                    <td>{p.memory_percent?.toFixed(1)}%</td>
                    <td style={{ fontSize: '0.75rem' }}>{p.username}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Listening Ports ── */}
        <div className="met-sub-header" onClick={() => toggleSection(server.id, 'ports')}>
          <span className="met-sub-title"><IC.plug size={14} /> Listening Ports ({ports.length})</span>
          <span className="met-sub-chevron">
            {isSectionOpen(server.id, 'ports') ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
          </span>
        </div>
        {isSectionOpen(server.id, 'ports') && ports.length > 0 && (
          <div className="table-container">
            <table>
              <thead>
                <tr><th>Port</th><th>Address</th><th>Process</th><th>PID</th></tr>
              </thead>
              <tbody>
                {ports.map((p, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 600, color: 'var(--accent)', fontFamily: 'monospace' }}>{p.port}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{p.address}</td>
                    <td>{p.process}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{p.pid}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Metrics Servers</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-primary" onClick={() => setShowAddForm((v) => !v)}>
            {showAddForm ? 'Cancel' : <><IC.plus size={14} /> Add Server</>}
          </button>
          <button className="btn btn-outline" onClick={expandAll}>Expand All</button>
          <button className="btn btn-outline" onClick={collapseAll}>Collapse All</button>
          <button className="btn btn-outline" onClick={loadData}><IC.refresh size={16} /> Refresh</button>
        </div>
      </div>

      {showAddForm && (
        <div className="dash-card" style={{ marginBottom: '1rem' }}>
          <form onSubmit={handleAddServer} className="met-add-form">
            <div className="met-field met-field-name">
              <label>Name</label>
              <input value={addForm.name} onChange={(e) => setAddForm({ ...addForm, name: e.target.value })} required />
            </div>
            <div className="met-field met-field-host">
              <label>Host</label>
              <input value={addForm.host} onChange={(e) => setAddForm({ ...addForm, host: e.target.value })} required />
            </div>
            <div className="met-field met-field-port">
              <label>Port</label>
              <input type="number" value={addForm.port} onChange={(e) => setAddForm({ ...addForm, port: Number(e.target.value) })} />
            </div>
            <button className="btn btn-primary" type="submit">Add</button>
          </form>
        </div>
      )}

      {servers.map((server) => {
        const m = metrics[server.name] || {};
        const isExpanded = expandedServers[server.id] ?? false;

        return (
          <div key={server.id} className={`met-row ${isExpanded ? 'met-row-open' : ''}`}>
            <div className="met-row-header" onClick={() => toggleServer(server.id)}>
              <span className="met-row-chevron">
                {isExpanded ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
              </span>
              <span className="met-row-name">{server.name}</span>
              <StatusBadge status={server.status} />

              {!isExpanded && renderCompactCells(server, m)}

              <span className="met-row-tail">
                {isExpanded && <>{server.host} — </>}
                {m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''}
              </span>
            </div>

            {isExpanded && renderExpandedDetail(server, m)}
          </div>
        );
      })}

      {servers.length === 0 && (
        <div className="dash-card met-empty">
          No servers registered. Click <strong>+ Add Server</strong> above, or start an agent to auto-register.
        </div>
      )}
    </div>
  );
}
