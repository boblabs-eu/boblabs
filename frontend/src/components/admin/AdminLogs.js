/**
 * Bob Labs — Admin observability panel.
 * Dashboard + filterable tables for HTTP requests, LLM dispatch events,
 * orchestrator tasks and lab anti-loop events.
 *
 * Mounted from AdminPage (Logs tab). Receives `adminApi` from the parent
 * (built by createAdminApiClient(jwt) in services/api.js, A07) so every
 * call goes through the per-instance admin axios with the admin JWT
 * baked into its Authorization header. No localStorage swap.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
  BarChart, Bar,
} from 'recharts';

const SINCE_OPTIONS = [
  { value: '15m', label: 'Last 15 min' },
  { value: '1h',  label: 'Last 1 h' },
  { value: '6h',  label: 'Last 6 h' },
  { value: '24h', label: 'Last 24 h' },
  { value: '7d',  label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

const REFRESH_OPTIONS = [
  { value: 0,    label: 'Off' },
  { value: 5,    label: '5 s' },
  { value: 15,   label: '15 s' },
  { value: 60,   label: '1 min' },
];

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString();
}

function shortPath(p) {
  if (!p) return '';
  return p.length > 80 ? p.slice(0, 77) + '…' : p;
}

function MetricCard({ label, value, sub }) {
  return (
    <div className="admin-logs-card">
      <div className="admin-logs-card-label">{label}</div>
      <div className="admin-logs-card-value">{value}</div>
      {sub && <div className="admin-logs-card-sub">{sub}</div>}
    </div>
  );
}

/* ─── Dashboard ────────────────────────────────────── */
function Dashboard({ metrics }) {
  if (!metrics) return <p className="admin-empty">Loading metrics…</p>;
  const t = metrics.totals || {};
  return (
    <>
      <div className="admin-logs-cards">
        <MetricCard label="Requests"     value={t.total ?? 0} />
        <MetricCard label="Errors (5xx)" value={t.errors ?? 0}
                    sub={t.total ? `${((t.errors / t.total) * 100).toFixed(1)} %` : null} />
        <MetricCard label="Warnings (4xx)" value={t.warns ?? 0} />
        <MetricCard label="Unique IPs"   value={t.unique_ips ?? 0} />
        <MetricCard label="Unique users" value={t.unique_users ?? 0} />
        <MetricCard label="Latency p50"  value={`${t.p50_ms ?? 0} ms`} />
        <MetricCard label="Latency p95"  value={`${t.p95_ms ?? 0} ms`} />
        <MetricCard label="Avg latency"  value={`${(t.avg_ms ?? 0).toFixed?.(0) ?? t.avg_ms} ms`} />
      </div>

      <div className="admin-logs-charts">
        <div className="admin-logs-chart">
          <h3>Traffic over time</h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={metrics.timeseries || []}>
              <defs>
                <linearGradient id="g-total" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#7c3aed" stopOpacity={0.5}/>
                  <stop offset="95%" stopColor="#7c3aed" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="bucket" tickFormatter={(b) => new Date(b).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip labelFormatter={fmtTime} />
              <Area type="monotone" dataKey="total"  stroke="#7c3aed" fill="url(#g-total)" name="Requests" />
              <Area type="monotone" dataKey="errors" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} name="Errors" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="admin-logs-chart">
          <h3>By status code</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={(metrics.by_status || []).map((b) => ({ ...b, label: `${b.bucket}xx` }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="label" fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip />
              <Bar dataKey="count" fill="#7c3aed" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="admin-logs-chart">
          <h3>By module</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={metrics.by_module || []} layout="vertical" margin={{ left: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis type="number" fontSize={11} />
              <YAxis dataKey="module" type="category" fontSize={11} width={100} />
              <Tooltip />
              <Bar dataKey="count" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="admin-logs-tops">
        <div className="admin-logs-top">
          <h3>Top users</h3>
          <table className="admin-table"><tbody>
            {(metrics.top_users || []).map((u) => (
              <tr key={u.user_email}><td>{u.user_email}</td><td style={{ textAlign: 'right' }}>{u.count}</td></tr>
            ))}
            {(metrics.top_users || []).length === 0 && <tr><td className="admin-empty">No data</td></tr>}
          </tbody></table>
        </div>
        <div className="admin-logs-top">
          <h3>Top IPs</h3>
          <table className="admin-table"><tbody>
            {(metrics.top_ips || []).map((u) => (
              <tr key={u.ip}><td>{u.ip}</td><td style={{ textAlign: 'right' }}>{u.count}</td></tr>
            ))}
            {(metrics.top_ips || []).length === 0 && <tr><td className="admin-empty">No data</td></tr>}
          </tbody></table>
        </div>
        <div className="admin-logs-top">
          <h3>Top paths</h3>
          <table className="admin-table"><tbody>
            {(metrics.top_paths || []).map((u) => (
              <tr key={u.path}><td title={u.path}>{shortPath(u.path)}</td><td style={{ textAlign: 'right' }}>{u.count}</td></tr>
            ))}
            {(metrics.top_paths || []).length === 0 && <tr><td className="admin-empty">No data</td></tr>}
          </tbody></table>
        </div>
      </div>

      {(metrics.recent_errors || []).length > 0 && (
        <div className="admin-logs-recent-errors">
          <h3>Recent errors</h3>
          <table className="admin-table">
            <thead><tr><th>Time</th><th>Status</th><th>Method</th><th>Path</th><th>User</th><th>IP</th><th>Error</th></tr></thead>
            <tbody>
              {metrics.recent_errors.map((e, i) => (
                <tr key={i}>
                  <td>{fmtTime(e.timestamp)}</td>
                  <td><span className="admin-logs-badge admin-logs-badge-error">{e.status}</span></td>
                  <td>{e.method}</td>
                  <td title={e.path}>{shortPath(e.path)}</td>
                  <td>{e.user_email || '—'}</td>
                  <td>{e.ip || '—'}</td>
                  <td className="admin-logs-error-cell" title={e.error_msg || ''}>{e.error_msg || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* ─── Requests sub-tab ─────────────────────────────── */
function RequestsTable({ since, adminApi }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [facets, setFacets] = useState({ modules: [], users: [], ips: [] });
  const [filters, setFilters] = useState({
    module: '', severity: '', user_email: '', ip: '', method: '', status: '', search: '',
  });
  const [offset, setOffset] = useState(0);
  const limit = 100;

  const load = useCallback(() => {
    setLoading(true);
    const params = { since, limit, offset };
    Object.entries(filters).forEach(([k, v]) => { if (v !== '' && v !== null) params[k] = v; });
    return adminApi.getAdminLogRequests(params)
      .then((r) => { setItems(r.data.items); setTotal(r.data.total); })
      .finally(() => setLoading(false));
  }, [since, offset, filters, adminApi]);

  const loadFacets = useCallback(() =>
    adminApi.getAdminLogFacets({ since }).then((r) => setFacets(r.data)),
  [since, adminApi]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadFacets(); }, [loadFacets]);

  const setFilter = (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setOffset(0); };

  return (
    <>
      <div className="admin-logs-filters">
        <select value={filters.module} onChange={(e) => setFilter('module', e.target.value)}>
          <option value="">All modules</option>
          {facets.modules.map((m) => <option key={m.value} value={m.value}>{m.value} ({m.count})</option>)}
        </select>
        <select value={filters.severity} onChange={(e) => setFilter('severity', e.target.value)}>
          <option value="">All severities</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
        <select value={filters.user_email} onChange={(e) => setFilter('user_email', e.target.value)}>
          <option value="">All users</option>
          {facets.users.map((u) => <option key={u.value} value={u.value}>{u.value} ({u.count})</option>)}
        </select>
        <select value={filters.ip} onChange={(e) => setFilter('ip', e.target.value)}>
          <option value="">All IPs</option>
          {facets.ips.map((u) => <option key={u.value} value={u.value}>{u.value} ({u.count})</option>)}
        </select>
        <select value={filters.method} onChange={(e) => setFilter('method', e.target.value)}>
          <option value="">All methods</option>
          {['GET','POST','PUT','PATCH','DELETE'].map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <input type="number" min={100} max={599} placeholder="Status" value={filters.status}
               onChange={(e) => setFilter('status', e.target.value)} style={{ width: 80 }} />
        <input type="text" placeholder="Search path / query / error" value={filters.search}
               onChange={(e) => setFilter('search', e.target.value)} style={{ flex: 1, minWidth: 200 }} />
      </div>

      <p style={{ color: '#6b7280', fontSize: '0.85rem', margin: '0.25rem 0 0.75rem' }}>
        {loading ? 'Loading…' : `${total.toLocaleString()} request${total === 1 ? '' : 's'} match`}
      </p>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Time</th><th>Sev</th><th>Status</th><th>Method</th><th>Path</th>
            <th>Module</th><th>User</th><th>IP</th><th>ms</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td>{fmtTime(r.timestamp)}</td>
              <td><span className={`admin-logs-badge admin-logs-badge-${r.severity}`}>{r.severity}</span></td>
              <td>{r.status}</td>
              <td>{r.method}</td>
              <td title={r.query ? `${r.path}?${r.query}` : r.path}>{shortPath(r.path)}</td>
              <td>{r.module}</td>
              <td>{r.user_email || '—'}</td>
              <td>{r.ip || '—'}</td>
              <td>{r.duration_ms}</td>
            </tr>
          ))}
          {items.length === 0 && !loading && <tr><td colSpan={9} className="admin-empty">No requests</td></tr>}
        </tbody>
      </table>

      <div className="admin-logs-pager">
        <button className="lp-btn-ghost" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}>← Previous</button>
        <span style={{ fontSize: '0.85rem', color: '#6b7280' }}>
          {offset + 1}–{Math.min(offset + limit, total)} of {total}
        </span>
        <button className="lp-btn-ghost" disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}>Next →</button>
      </div>
    </>
  );
}

/* ─── LLM Events sub-tab ───────────────────────────── */
function LlmEventsTable({ since, adminApi }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [eventType, setEventType] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    const params = { limit: 200, since };
    if (eventType) params.event_type = eventType;
    return adminApi.getAdminLogLlmEvents(params)
      .then((r) => setItems(r.data))
      .finally(() => setLoading(false));
  }, [since, eventType, adminApi]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <div className="admin-logs-filters">
        <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
          <option value="">All event types</option>
          <option value="queued">queued</option>
          <option value="dispatched">dispatched</option>
          <option value="response">response</option>
          <option value="failed">failed</option>
        </select>
      </div>
      <p style={{ color: '#6b7280', fontSize: '0.85rem', margin: '0.25rem 0 0.75rem' }}>
        {loading ? 'Loading…' : `${items.length} event${items.length === 1 ? '' : 's'}`}
      </p>
      <table className="admin-table">
        <thead>
          <tr>
            <th>Time</th><th>Event</th><th>Model</th><th>Provider</th><th>Server</th>
            <th>Caller</th><th>Lab</th><th>Tokens in/out</th><th>Duration</th><th>Error</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>{fmtTime(e.created_at)}</td>
              <td><span className={`admin-logs-badge ${e.event_type === 'failed' ? 'admin-logs-badge-error' : 'admin-logs-badge-info'}`}>{e.event_type}</span></td>
              <td title={e.model_identifier}>{e.model_identifier || '—'}</td>
              <td>{e.provider_name || '—'}</td>
              <td>{e.server_name || '—'}</td>
              <td>{e.caller_type || '—'}</td>
              <td title={e.lab_id || ''}>{e.lab_name || (e.lab_id ? e.lab_id.slice(0, 8) : '—')}</td>
              <td>{e.tokens_in ?? 0} / {e.tokens_out ?? 0}</td>
              <td>{e.duration_ms != null ? `${e.duration_ms} ms` : '—'}</td>
              <td className="admin-logs-error-cell" title={e.error || ''}>{e.error || ''}</td>
            </tr>
          ))}
          {items.length === 0 && !loading && <tr><td colSpan={10} className="admin-empty">No events</td></tr>}
        </tbody>
      </table>
    </>
  );
}

/* ─── Tasks sub-tab ────────────────────────────────── */
function TasksTable({ adminApi }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    const params = { limit: 200 };
    if (statusFilter) params.status = statusFilter;
    return adminApi.getAdminLogTasks(params)
      .then((r) => setItems(r.data))
      .finally(() => setLoading(false));
  }, [statusFilter, adminApi]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <div className="admin-logs-filters">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="completed">completed</option>
          <option value="failed">failed</option>
        </select>
      </div>
      <p style={{ color: '#6b7280', fontSize: '0.85rem', margin: '0.25rem 0 0.75rem' }}>
        {loading ? 'Loading…' : `${items.length} task${items.length === 1 ? '' : 's'}`}
      </p>
      <table className="admin-table">
        <thead>
          <tr><th>Queued</th><th>Type</th><th>Status</th><th>Priority</th><th>Started</th><th>Completed</th><th>Error</th></tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.id}>
              <td>{fmtTime(t.queued_at)}</td>
              <td>{t.task_type}</td>
              <td><span className={`admin-logs-badge admin-logs-badge-${t.status === 'failed' ? 'error' : t.status === 'running' ? 'warn' : 'info'}`}>{t.status}</span></td>
              <td>{t.priority ?? '—'}</td>
              <td>{fmtTime(t.started_at)}</td>
              <td>{fmtTime(t.completed_at)}</td>
              <td className="admin-logs-error-cell" title={t.error || ''}>{t.error || ''}</td>
            </tr>
          ))}
          {items.length === 0 && !loading && <tr><td colSpan={7} className="admin-empty">No tasks</td></tr>}
        </tbody>
      </table>
    </>
  );
}

/* ─── Lab loop events sub-tab ──────────────────────── */
function LabLoopsTable({ adminApi }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [severity, setSeverity] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    const params = { limit: 200 };
    if (severity) params.severity = severity;
    return adminApi.getAdminLogLabLoops(params)
      .then((r) => setItems(r.data))
      .finally(() => setLoading(false));
  }, [severity, adminApi]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <div className="admin-logs-filters">
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          <option value="yellow">yellow</option>
          <option value="orange">orange</option>
          <option value="red">red</option>
        </select>
      </div>
      <p style={{ color: '#6b7280', fontSize: '0.85rem', margin: '0.25rem 0 0.75rem' }}>
        {loading ? 'Loading…' : `${items.length} event${items.length === 1 ? '' : 's'}`}
      </p>
      <table className="admin-table">
        <thead>
          <tr><th>Detected</th><th>Severity</th><th>Score</th><th>Lab</th><th>Removed</th><th>Recovered</th><th>Signals</th></tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>{fmtTime(e.detected_at)}</td>
              <td><span className="admin-logs-badge" style={{ background: e.severity, color: '#fff' }}>{e.severity}</span></td>
              <td>{e.score}</td>
              <td title={e.lab_id}>{e.lab_id.slice(0, 8)}…</td>
              <td>{e.removed_count}</td>
              <td>{e.recovered ? 'yes' : 'no'}</td>
              <td className="admin-logs-error-cell" title={JSON.stringify(e.signals)}>{JSON.stringify(e.signals).slice(0, 100)}</td>
            </tr>
          ))}
          {items.length === 0 && !loading && <tr><td colSpan={7} className="admin-empty">No loop events</td></tr>}
        </tbody>
      </table>
    </>
  );
}

/* ─── Main entry ───────────────────────────────────── */
export default function AdminLogs({ adminApi }) {
  const [since, setSince] = useState('24h');
  const [refreshSec, setRefreshSec] = useState(0);
  const [subTab, setSubTab] = useState('requests');
  const [metrics, setMetrics] = useState(null);
  const [tick, setTick] = useState(0);

  const loadMetrics = useCallback(() =>
    adminApi.getAdminLogMetrics({ since }).then((r) => setMetrics(r.data)),
  [since, adminApi]);

  useEffect(() => { loadMetrics(); }, [loadMetrics, tick]);

  useEffect(() => {
    if (!refreshSec) return undefined;
    const id = setInterval(() => setTick((n) => n + 1), refreshSec * 1000);
    return () => clearInterval(id);
  }, [refreshSec]);

  const refresh = () => setTick((n) => n + 1);

  const subTabKey = useMemo(() => `${subTab}-${tick}`, [subTab, tick]);

  return (
    <div className="admin-logs">
      <div className="admin-toolbar">
        <h2>Logs &amp; Observability</h2>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <select value={since} onChange={(e) => setSince(e.target.value)}>
            {SINCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select value={refreshSec} onChange={(e) => setRefreshSec(Number(e.target.value))}>
            {REFRESH_OPTIONS.map((o) => <option key={o.value} value={o.value}>Auto-refresh {o.label}</option>)}
          </select>
          <button className="lp-btn-primary-sm" onClick={refresh}>Refresh</button>
        </div>
      </div>

      <Dashboard metrics={metrics} />

      <div className="admin-logs-subtabs">
        {[
          ['requests', `HTTP Requests`],
          ['llm',      `LLM Dispatcher`],
          ['tasks',    `Orchestrator Tasks`],
          ['loops',    `Lab Anti-Loop`],
        ].map(([k, label]) => (
          <button key={k} className={subTab === k ? 'active' : ''} onClick={() => setSubTab(k)}>
            {label}
          </button>
        ))}
      </div>

      <div className="admin-logs-table-wrap" key={subTabKey}>
        {subTab === 'requests' && <RequestsTable since={since} adminApi={adminApi} />}
        {subTab === 'llm'      && <LlmEventsTable since={since} adminApi={adminApi} />}
        {subTab === 'tasks'    && <TasksTable    adminApi={adminApi} />}
        {subTab === 'loops'    && <LabLoopsTable adminApi={adminApi} />}
      </div>
    </div>
  );
}
