/**
 * Bob Manager — Dashboard page (overview).
 *
 * Release layout: the Orchestrator section leads (labs / agents / load-balancer
 * traffic), then Hardware (GPU servers), then Projects & Resources and News.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getServers, getAllMetrics, getProjects, getResources, getProjectThemes,
  getNews, getCryptoPrices, getPortfolioValue,
  getLabs, getAgentInstances, getLlmEventStats,
} from '../services/api';
import { IC } from '../components/common/Icons';
import StatusBadge from '../components/common/StatusBadge';
import ProgressBar from '../components/common/ProgressBar';
import wsService from '../services/websocket';
import './DashboardPage.css';

/* Dashboard label -> llm-events/stats period code. */
const LB_PERIODS = [
  { label: '24h', code: '1d' },
  { label: '7d', code: '1w' },
  { label: '30d', code: '1m' },
  { label: 'All', code: 'all' },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const [servers, setServers] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [projects, setProjects] = useState([]);
  const [resources, setResources] = useState([]);
  const [allThemes, setAllThemes] = useState([]);
  const [newsArticles, setNewsArticles] = useState([]);
  const [cryptoPrices, setCryptoPrices] = useState({});
  const [portfolio, setPortfolio] = useState(null);

  // Orchestrator section
  const [labs, setLabs] = useState([]);
  const [agentInstances, setAgentInstances] = useState([]);
  const [lbStats, setLbStats] = useState(null);
  const [lbPeriod, setLbPeriod] = useState('24h');

  useEffect(() => {
    loadData();

    const unsubMetrics = wsService.on('metrics.update', (data) => {
      setMetrics((prev) => ({ ...prev, [data.server]: data.metrics }));
    });

    const unsubStatus = wsService.on('server.status', (data) => {
      setServers((prev) =>
        prev.map((s) => (s.name === data.name ? { ...s, status: data.status } : s))
      );
    });

    return () => { unsubMetrics(); unsubStatus(); };
  }, []);

  async function loadData() {
    try {
      const [srvRes, metRes, projRes, resRes, tRes, labsRes, agentsRes] = await Promise.all([
        getServers(), getAllMetrics(), getProjects(), getResources(), getProjectThemes(),
        getLabs(), getAgentInstances(),
      ]);
      setServers(srvRes.data);
      setMetrics(metRes.data);
      setProjects(projRes.data);
      setResources(resRes.data);
      setAllThemes(tRes.data);
      setLabs(labsRes.data || []);
      setAgentInstances(agentsRes.data || []);
      // News & Prices (non-blocking)
      getNews(undefined, 5).then((r) => setNewsArticles(r.data)).catch(() => {});
      getCryptoPrices().then((r) => setCryptoPrices(r.data)).catch(() => {});
      getPortfolioValue().then((r) => setPortfolio(r.data)).catch(() => {});
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    }
  }

  // Load-balancer stats — re-fetched whenever the period toggle changes.
  const loadLbStats = useCallback(() => {
    const code = LB_PERIODS.find((p) => p.label === lbPeriod)?.code || '1d';
    getLlmEventStats({ period: code })
      .then((r) => setLbStats(r.data?.summary || null))
      .catch(() => setLbStats(null));
  }, [lbPeriod]);

  useEffect(() => { loadLbStats(); }, [loadLbStats]);

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`;
  }

  function tempColorClass(temp) {
    if (temp == null) return 'is-muted';
    if (temp >= 80) return 'is-error';
    if (temp >= 60) return 'is-warning';
    return 'is-success';
  }

  const onlineCount = servers.filter((s) => s.status === 'online').length;
  const totalGpus = servers.reduce((acc, s) => acc + (s.gpu_info?.gpus?.length || 0), 0);
  const totalDocker = Object.values(metrics).reduce((acc, m) => acc + (m.docker_running_count || 0), 0);
  const totalServices = Object.values(metrics).reduce((acc, m) => acc + (m.services_running_count || 0), 0);

  const labsRunning = labs.filter((l) => l.status === 'running').length;
  const labsCompleted = labs.filter((l) => l.status === 'completed').length;
  const agentsRunning = agentInstances.filter((a) => a.status === 'running').length;

  function getThemeColor(name) {
    const t = allThemes.find((th) => th.name === name);
    return t ? t.color : '#a855f7';
  }
  function hexToRgba(hex, alpha = 0.15) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  const lastUpdatedProjects = [...projects].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)).slice(0, 3);
  const lastCreatedResources = [...resources].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 3);

  return (
    <div>
      <div className="page-header">
        <h1>Dashboard</h1>
        <button className="btn btn-outline" onClick={() => { loadData(); loadLbStats(); }}>
          <IC.refresh size={16} /> Refresh
        </button>
      </div>

      {/* ── Console Section (formerly "Orchestrator" — the AI control center) ── */}
      <div className="dash-section">
        <h2 className="dash-section-header"><IC.activity size={16} /> Console</h2>
        <div className="dash-grid dash-grid-3">
          {/* Labs */}
          <div className="dash-card dash-clickable" onClick={() => navigate('/orchestrator?tab=labs')}>
            <div className="dash-card-title"><IC.layers size={15} /> Labs</div>
            <div className="dash-stat-row">
              <div className="dash-substat">
                <span className="dash-substat-value">{labs.length}</span>
                <span className="dash-substat-label">Total</span>
              </div>
              <div className="dash-substat">
                <span className="dash-substat-value is-info">{labsRunning}</span>
                <span className="dash-substat-label">Running</span>
              </div>
              <div className="dash-substat">
                <span className="dash-substat-value is-success">{labsCompleted}</span>
                <span className="dash-substat-label">Completed</span>
              </div>
            </div>
          </div>

          {/* Agents */}
          <div className="dash-card dash-clickable" onClick={() => navigate('/orchestrator?tab=agents')}>
            <div className="dash-card-title"><IC.cpu size={15} /> Agents</div>
            <div className="dash-stat-row">
              <div className="dash-substat">
                <span className="dash-substat-value">{agentInstances.length}</span>
                <span className="dash-substat-label">Total</span>
              </div>
              <div className="dash-substat">
                <span className="dash-substat-value is-info">{agentsRunning}</span>
                <span className="dash-substat-label">Running</span>
              </div>
            </div>
          </div>

          {/* Load Balancer requests */}
          <div className="dash-card">
            <div className="dash-card-title">
              <IC.arrowUpDown size={15} /> Load Balancer
              <span className="dash-card-title-spacer" />
              <span className="dash-period-toggle">
                {LB_PERIODS.map((p) => (
                  <button
                    key={p.label}
                    className={lbPeriod === p.label ? 'active' : ''}
                    onClick={() => setLbPeriod(p.label)}
                  >
                    {p.label}
                  </button>
                ))}
              </span>
            </div>
            <div className="dash-stat-value is-accent" style={{ marginBottom: '0.5rem' }}>
              {lbStats ? lbStats.total : '—'}
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '0.4rem' }}>
                requests
              </span>
            </div>
            <div className="dash-status-row">
              <span className="dash-status-pill is-success">
                <span className="dash-dot" /> {lbStats ? lbStats.succeeded : 0} success
              </span>
              <span className="dash-status-pill is-warning">
                <span className="dash-dot" /> {lbStats ? lbStats.queued : 0} pending
              </span>
              <span className="dash-status-pill is-error">
                <span className="dash-dot" /> {lbStats ? lbStats.failed : 0} failed
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Hardware Section ── */}
      <div className="dash-section">
        <h2 className="dash-section-header"><IC.monitor size={16} /> Hardware</h2>

        {/* Summary Stats */}
        <div className="dash-grid dash-grid-4" style={{ marginBottom: '0.85rem' }}>
          <div className="dash-card dash-clickable" onClick={() => navigate('/metrics')}>
            <div className="dash-stat-label">Total Servers</div>
            <div className="dash-stat-value">{servers.length}</div>
            <div className="dash-stat-sub is-success">{onlineCount} online</div>
          </div>
          <div className="dash-card">
            <div className="dash-stat-label">Total GPUs</div>
            <div className="dash-stat-value">{totalGpus}</div>
          </div>
          <div className="dash-card">
            <div className="dash-stat-label">Docker Containers</div>
            <div className="dash-stat-value is-accent">{totalDocker}</div>
            <div className="dash-stat-sub">running</div>
          </div>
          <div className="dash-card">
            <div className="dash-stat-label">Services Running</div>
            <div className="dash-stat-value is-success">{totalServices}</div>
          </div>
        </div>

        {/* Server Cards */}
        <div className="dash-grid dash-grid-2">
          {servers.map((server) => {
            const m = metrics[server.name] || {};
            const gpuMetrics = m.gpu_metrics || [];

            return (
              <div
                className="dash-card dash-clickable"
                key={server.id}
                onClick={() => navigate(`/metrics?expand=${server.id}`)}
              >
                <div className="dash-card-header">
                  <span className="dash-server-name">{server.name}</span>
                  <StatusBadge status={server.status} />
                </div>
                <p className="dash-server-host">{server.host}:{server.port}</p>

                {/* Temperatures */}
                <div className="dash-temp-row">
                  <div className="dash-temp">
                    <div className="dash-temp-label">CPU</div>
                    <div className={`dash-temp-value ${tempColorClass(m.cpu_temperature)}`}>
                      {m.cpu_temperature != null ? `${m.cpu_temperature.toFixed(0)}°` : '—'}
                    </div>
                  </div>
                  {gpuMetrics.slice(0, 2).map((gpu, i) => (
                    <div key={i} className="dash-temp">
                      <div className="dash-temp-label">GPU{gpu.index}</div>
                      <div className={`dash-temp-value ${tempColorClass(gpu.temperature_c)}`}>
                        {gpu.temperature_c != null ? `${gpu.temperature_c.toFixed(0)}°` : '—'}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Bars */}
                <div className="dash-bars">
                  <ProgressBar value={m.cpu_usage || 0} label="CPU" color="blue" />
                  <ProgressBar value={m.ram_percent || 0} label={`RAM — ${formatBytes(m.ram_used)} / ${formatBytes(m.ram_total)}`} color="green" />
                  {gpuMetrics.length > 0 && (
                    <ProgressBar value={gpuMetrics[0].gpu_usage_percent || 0} label={`GPU — ${gpuMetrics[0].name || ''}`} color="blue" />
                  )}
                  <ProgressBar
                    value={m.disk_percent || 0}
                    label={`Disk — ${formatBytes(m.disk_used)} / ${formatBytes(m.disk_total)}`}
                    color="yellow"
                  />
                </div>

                {/* Counts row */}
                <div className="dash-counts-row">
                  {m.docker_running_count != null && (
                    <span><IC.docker size={14} /> {m.docker_running_count} containers</span>
                  )}
                  {m.services_running_count != null && (
                    <span><IC.settings size={14} /> {m.services_running_count} services</span>
                  )}
                  {m.services_failed_count > 0 && (
                    <span className="is-error"><IC.xCircle size={14} /> {m.services_failed_count} failed</span>
                  )}
                  {m.listening_ports?.length > 0 && (
                    <span><IC.plug size={14} /> {m.listening_ports.length} ports</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {servers.length === 0 && (
          <div className="dash-card dash-empty-card">
            <p className="dash-empty">No servers registered. Start an agent to auto-register.</p>
          </div>
        )}
      </div>

      {/* ── Projects & Resources Section ── */}
      <div className="dash-section">
        <h2 className="dash-section-header"><IC.folder size={16} /> Projects &amp; Resources</h2>
        <div className="dash-grid dash-grid-4" style={{ marginBottom: '0.85rem' }}>
          <div className="dash-card dash-clickable" onClick={() => navigate('/projects')}>
            <div className="dash-stat-label">Total Projects</div>
            <div className="dash-stat-value is-accent">{projects.length}</div>
          </div>
          <div className="dash-card dash-clickable" onClick={() => navigate('/resources')}>
            <div className="dash-stat-label">Total Resources</div>
            <div className="dash-stat-value is-accent">{resources.length}</div>
          </div>
        </div>

        <div className="dash-grid dash-grid-2">
          {/* Last 3 updated projects */}
          <div className="dash-card">
            <div className="dash-card-title"><IC.clock size={15} /> Last Updated Projects</div>
            {lastUpdatedProjects.length === 0 && <p className="dash-empty">No projects yet</p>}
            {lastUpdatedProjects.map((p) => (
              <div key={p.id} className="dash-list-row" onClick={() => navigate(`/projects/${p.id}`)}>
                <div className="dash-list-row-main">
                  <span className="dash-list-row-name">{p.name}</span>
                  {(Array.isArray(p.themes) ? p.themes : []).slice(0, 3).map((t, i) => {
                    const c = getThemeColor(t);
                    return <span key={i} className="dash-tag" style={{ background: hexToRgba(c), color: c }}>{t}</span>;
                  })}
                </div>
                <span className="dash-list-row-date">{new Date(p.updated_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>

          {/* Last 3 created resources */}
          <div className="dash-card">
            <div className="dash-card-title"><IC.plusCircle size={15} /> Last Created Resources</div>
            {lastCreatedResources.length === 0 && <p className="dash-empty">No resources yet</p>}
            {lastCreatedResources.map((r) => (
              <div key={r.id} className="dash-list-row" onClick={() => navigate(`/resources/${r.id}`)}>
                <div className="dash-list-row-main">
                  <span className="dash-list-row-name">{r.name}</span>
                  {(Array.isArray(r.themes) ? r.themes : []).slice(0, 3).map((t, i) => {
                    const c = getThemeColor(t);
                    return <span key={i} className="dash-tag" style={{ background: hexToRgba(c), color: c }}>{t}</span>;
                  })}
                </div>
                <span className="dash-list-row-date">{new Date(r.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── News & Markets Section ── */}
      <div className="dash-section">
        <h2 className="dash-section-header"><IC.globe size={16} /> News &amp; Markets</h2>
        <div className="dash-grid dash-grid-2">
          {/* News Preview */}
          <div className="dash-card dash-clickable" onClick={() => navigate('/news')}>
            <div className="dash-card-title"><IC.newspaper size={15} /> Latest News</div>
            {newsArticles.length === 0 && <p className="dash-empty">Loading news…</p>}
            {newsArticles.slice(0, 4).map((a, i) => (
              <div key={i} className="dash-news-row">
                <div className="dash-news-title">{a.title}</div>
                <div className="dash-news-source">{a.source}</div>
              </div>
            ))}
          </div>

          {/* Web3 Preview */}
          <div className="dash-card dash-clickable" onClick={() => navigate('/web3')}>
            <div className="dash-card-title"><IC.bitcoin size={15} /> Crypto Prices</div>
            <div className="dash-crypto-row">
              {[
                { id: 'bitcoin', symbol: 'BTC', color: '#f7931a' },
                { id: 'ethereum', symbol: 'ETH', color: '#627eea' },
                { id: 'binancecoin', symbol: 'BNB', color: '#f3ba2f' },
              ].map((coin) => {
                const data = cryptoPrices[coin.id] || {};
                const changePos = data.change_24h > 0;
                return (
                  <div key={coin.id} className="dash-crypto">
                    <div className="dash-crypto-symbol" style={{ color: coin.color }}>{coin.symbol}</div>
                    <div className="dash-crypto-price">
                      {data.price ? `$${data.price >= 1000 ? Math.round(data.price).toLocaleString() : data.price.toFixed(2)}` : '—'}
                    </div>
                    {data.change_24h != null && (
                      <div className={`dash-crypto-change ${changePos ? 'is-success' : 'is-error'}`}>
                        {changePos ? '+' : ''}{data.change_24h.toFixed(2)}%
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {portfolio && portfolio.wallet_count > 0 && (
              <div className="dash-portfolio">
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  <IC.wallet size={12} /> Portfolio ({portfolio.wallet_count} wallet{portfolio.wallet_count > 1 ? 's' : ''})
                </span>
                <span className="is-accent" style={{ fontSize: '1rem', fontWeight: 700 }}>
                  ${portfolio.total_value_usd?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
