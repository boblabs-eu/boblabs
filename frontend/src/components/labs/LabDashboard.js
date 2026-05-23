/**
 * LabDashboard — central dashboard shown when no lab is selected.
 * Displays KPIs and a list of all labs with quick run/pause/stop controls.
 */
import React, { useMemo, useState } from 'react';
import { runLab, pauseLab, resumeLab, stopLab } from '../../services/api';
import './LabDashboard.css';

function statusClass(s) {
  if (s === 'running') return 'lab-dash-status running';
  if (s === 'paused') return 'lab-dash-status paused';
  if (s === 'completed') return 'lab-dash-status completed';
  if (s === 'failed' || s === 'error') return 'lab-dash-status failed';
  if (s === 'scheduled') return 'lab-dash-status scheduled';
  return 'lab-dash-status created';
}

function timeAgo(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return sec + 's ago';
  if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
  if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
  return Math.floor(sec / 86400) + 'd ago';
}

const IC = {
  play: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20"/></svg>,
  pause: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>,
  stop: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="1"/></svg>,
  resume: <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20"/></svg>,
  search: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  shield: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6z"/></svg>,
  database: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
  trend: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="14 7 21 7 21 14"/></svg>,
  clock: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 16 14"/></svg>,
  bot: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><line x1="12" y1="7" x2="12" y2="11"/></svg>,
  msg: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  arrow: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="9 6 15 12 9 18"/></svg>,
};

function KpiCard({ label, value, hint, accent, icon, trend }) {
  return (
    <div className="lab-dash-kpi" style={{ '--kpi-accent': accent }}>
      <div className="lab-dash-kpi-top">
        <span className="lab-dash-kpi-icon">{icon}</span>
        {trend != null && (
          <span className={`lab-dash-kpi-trend ${trend >= 0 ? 'up' : 'down'}`}>
            {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}%
          </span>
        )}
      </div>
      <div className="lab-dash-kpi-value">{value}</div>
      <div className="lab-dash-kpi-label">{label}</div>
      {hint && <div className="lab-dash-kpi-hint">{hint}</div>}
    </div>
  );
}

function LabRow({ lab, onSelect, onAction, busyId }) {
  const isBusy = busyId === lab.id;
  const canRun = lab.status === 'created' || lab.status === 'completed' || lab.status === 'failed';
  const isRunning = lab.status === 'running';
  const isPaused = lab.status === 'paused';

  return (
    <div className="lab-dash-row" onClick={() => onSelect(lab)}>
      <div className="lab-dash-row-status">
        <span className={statusClass(lab.status)}>
          {isRunning && <span className="lab-dash-pulse" />}
          {lab.status}
        </span>
      </div>
      <div className="lab-dash-row-name">
        <strong>{lab.name}</strong>
        {lab.description && <span className="lab-dash-row-desc">{lab.description}</span>}
      </div>
      <div className="lab-dash-row-stat">
        <span>{IC.bot}</span>
        <span>{lab.agent_count ?? 0}</span>
      </div>
      <div className="lab-dash-row-stat">
        <span>{IC.msg}</span>
        <span>{lab.message_count ?? 0}</span>
      </div>
      <div className="lab-dash-row-stat lab-dash-row-iter">
        iter {lab.current_iteration ?? 0}
        {lab.max_iterations ? <span className="dim">/{lab.max_iterations}</span> : null}
      </div>
      <div className="lab-dash-row-time">{timeAgo(lab.updated_at || lab.created_at)}</div>
      <div className="lab-dash-row-actions" onClick={(e) => e.stopPropagation()}>
        {canRun && (
          <button
            className="lab-dash-act run"
            disabled={isBusy}
            onClick={() => onAction('run', lab)}
            title="Run"
          >{IC.play}</button>
        )}
        {isRunning && (
          <button
            className="lab-dash-act pause"
            disabled={isBusy}
            onClick={() => onAction('pause', lab)}
            title="Pause"
          >{IC.pause}</button>
        )}
        {isPaused && (
          <button
            className="lab-dash-act run"
            disabled={isBusy}
            onClick={() => onAction('resume', lab)}
            title="Resume"
          >{IC.resume}</button>
        )}
        {(isRunning || isPaused) && (
          <button
            className="lab-dash-act stop"
            disabled={isBusy}
            onClick={() => onAction('stop', lab)}
            title="Stop"
          >{IC.stop}</button>
        )}
        <button
          className="lab-dash-act open"
          onClick={() => onSelect(lab)}
          title="Open lab"
        >{IC.arrow}</button>
      </div>
    </div>
  );
}

export default function LabDashboard({ labs, onSelect, onRefresh }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [busyId, setBusyId] = useState(null);

  const stats = useMemo(() => {
    const total = labs.length;
    const running = labs.filter(l => l.status === 'running').length;
    const paused = labs.filter(l => l.status === 'paused').length;
    const failed = labs.filter(l => l.status === 'failed' || l.status === 'error').length;
    const completed = labs.filter(l => l.status === 'completed').length;
    const totalIters = labs.reduce((s, l) => s + (l.current_iteration || 0), 0);
    const totalMsgs = labs.reduce((s, l) => s + (l.message_count || 0), 0);
    return { total, running, paused, failed, completed, totalIters, totalMsgs };
  }, [labs]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return labs.filter(l => {
      if (filter !== 'all' && l.status !== filter) return false;
      if (!q) return true;
      return (l.name || '').toLowerCase().includes(q) ||
             (l.description || '').toLowerCase().includes(q);
    });
  }, [labs, search, filter]);

  async function handleAction(action, lab) {
    setBusyId(lab.id);
    try {
      if (action === 'run') await runLab(lab.id, { reset: false });
      else if (action === 'pause') await pauseLab(lab.id);
      else if (action === 'resume') await resumeLab(lab.id);
      else if (action === 'stop') await stopLab(lab.id);
      onRefresh && onRefresh();
    } catch (e) {
      console.error(`Failed to ${action} lab`, e);
    } finally {
      setBusyId(null);
    }
  }

  const filters = [
    { id: 'all', label: 'All', count: stats.total },
    { id: 'running', label: 'Running', count: stats.running },
    { id: 'paused', label: 'Paused', count: stats.paused },
    { id: 'completed', label: 'Completed', count: stats.completed },
    { id: 'failed', label: 'Failed', count: stats.failed },
  ];

  return (
    <div className="lab-dashboard">
      <div className="lab-dash-header">
        <div>
          <h1 className="lab-dash-title">Overview</h1>
          <p className="lab-dash-subtitle">Select a lab on the left to open it, or run quick actions from here.</p>
        </div>
        <div className="lab-dash-search">
          <span className="lab-dash-search-icon">{IC.search}</span>
          <input
            type="text"
            placeholder="Search labs…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <span className="lab-dash-search-kbd">⌘K</span>
        </div>
      </div>

      <div className="lab-dash-kpis">
        <KpiCard
          icon={IC.shield}
          label="Active labs"
          value={stats.running}
          hint={stats.paused ? `${stats.paused} paused` : 'all idle'}
          accent="#34d399"
        />
        <KpiCard
          icon={IC.database}
          label="Total labs"
          value={stats.total}
          hint={`${stats.completed} completed`}
          accent="#fb923c"
        />
        <KpiCard
          icon={IC.trend}
          label="Total iterations"
          value={stats.totalIters}
          hint={`${stats.totalMsgs} messages`}
          accent="#22d3ee"
        />
        <KpiCard
          icon={IC.clock}
          label="Failed"
          value={stats.failed}
          hint={stats.failed === 0 ? 'all clear' : 'needs review'}
          accent={stats.failed > 0 ? '#f87171' : '#7c5cff'}
        />
      </div>

      <div className="lab-dash-section">
        <div className="lab-dash-section-head">
          <div className="lab-dash-section-title">
            <span className="lab-dash-section-icon">{IC.database}</span>
            LABS
          </div>
          <div className="lab-dash-filters">
            {filters.map(f => (
              <button
                key={f.id}
                className={`lab-dash-filter${filter === f.id ? ' active' : ''}`}
                onClick={() => setFilter(f.id)}
              >
                {f.label} <span className="lab-dash-filter-count">{f.count}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="lab-dash-table">
          <div className="lab-dash-table-head">
            <div>STATUS</div>
            <div>LAB</div>
            <div>AGENTS</div>
            <div>MSGS</div>
            <div>ITER</div>
            <div>UPDATED</div>
            <div>ACTIONS</div>
          </div>
          <div className="lab-dash-table-body">
            {filtered.length === 0 ? (
              <div className="lab-dash-empty">
                {labs.length === 0
                  ? 'No labs yet — create one from the sidebar.'
                  : 'No labs match the current filter.'}
              </div>
            ) : filtered.map(lab => (
              <LabRow
                key={lab.id}
                lab={lab}
                onSelect={onSelect}
                onAction={handleAction}
                busyId={busyId}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
