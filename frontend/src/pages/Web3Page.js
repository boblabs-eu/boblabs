/**
 * Bob Manager — Web3 page.
 * Live crypto prices, wallet tracker with multi-chain balances,
 * transaction history, portfolio value chart, and configurable settings.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  getCryptoPrices, getWallets, addWallet, removeWallet, getWalletBalances,
  getWalletTransactions, getWeb3Settings, updateWeb3Settings,
  getPortfolioHistory, triggerSnapshot,
} from '../services/api';
import { IC } from '../components/common/Icons';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell,
} from 'recharts';

/* ── Helpers ── */

function formatUsd(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD',
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value);
}

function formatMarketCap(value) {
  if (value == null) return '—';
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return formatUsd(value);
}

function shortAddr(addr) {
  if (!addr) return '';
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function timeAgo(stamp) {
  if (!stamp) return '';
  const diff = (Date.now() - new Date(stamp).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text);
}

const COIN_META = {
  bitcoin: { name: 'Bitcoin', symbol: 'BTC', color: '#f7931a' },
  ethereum: { name: 'Ethereum', symbol: 'ETH', color: '#627eea' },
  binancecoin: { name: 'BNB', symbol: 'BNB', color: '#f3ba2f' },
};

const CHAIN_IDS = ['ethereum', 'base', 'bnb'];

const WALLET_COLORS = [
  '#f87171', '#60a5fa', '#34d399', '#fbbf24', '#a78bfa',
  '#f472b6', '#38bdf8', '#4ade80', '#fb923c', '#c084fc',
];

const PIE_COLORS = [
  '#f87171', '#60a5fa', '#34d399', '#fbbf24', '#a78bfa',
  '#f472b6', '#38bdf8', '#4ade80', '#fb923c', '#c084fc',
  '#e879f9', '#22d3ee', '#f59e0b', '#10b981', '#8b5cf6',
];

/* ── Copy Button Component ── */

function CopyBtn({ text, size = 13 }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={(e) => { e.stopPropagation(); copyToClipboard(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      title="Copy address"
      style={{
        background: 'none', border: 'none', cursor: 'pointer', padding: '0.1rem 0.25rem',
        color: copied ? 'var(--success)' : 'var(--text-muted)', transition: 'color 0.15s',
      }}
    >
      {copied ? <IC.check size={size} /> : <IC.copy size={size} />}
    </button>
  );
}

/* ── Mini Pie Chart for token distribution ── */

function TokenPieChart({ tokens, nativeSymbol, nativeValueUsd }) {
  const data = [];
  if (nativeValueUsd > 0) {
    data.push({ name: nativeSymbol, value: nativeValueUsd });
  }
  (tokens || []).forEach((t) => {
    if (t.value_usd > 0) data.push({ name: t.symbol, value: t.value_usd });
  });
  if (data.length < 2) return null;
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <div style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border)', paddingTop: '0.5rem' }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '0.3rem' }}>
        Distribution
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <ResponsiveContainer width="100%" height={120}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={25} outerRadius={48} paddingAngle={2} strokeWidth={0}>
              {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
            </Pie>
            <Tooltip
              contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', fontSize: '0.75rem' }}
              formatter={(v, name) => [`${formatUsd(v)} (${(v / total * 100).toFixed(1)}%)`, name]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}


/* ── Main Page ── */

export default function Web3Page() {
  const [prices, setPrices] = useState({});
  const [wallets, setWallets] = useState([]);
  const [balances, setBalances] = useState({});
  const [loadingPrices, setLoadingPrices] = useState(true);
  const [loadingBalances, setLoadingBalances] = useState(false);
  const [newAddress, setNewAddress] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [addError, setAddError] = useState('');
  const [expandedWallet, setExpandedWallet] = useState(null);

  // Transaction history
  const [txWalletId, setTxWalletId] = useState(null);
  const [txChain, setTxChain] = useState('ethereum');
  const [txData, setTxData] = useState(null);
  const [loadingTx, setLoadingTx] = useState(false);

  // Settings
  const [settings, setSettings] = useState({ refresh_interval: 300, retention_full_hours: 168, retention_step_hours: 1 });
  const [showSettings, setShowSettings] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState({});

  // Portfolio chart
  const [chartData, setChartData] = useState([]);
  const [chartHours, setChartHours] = useState(24);
  const [chartWalletId, setChartWalletId] = useState(null);
  const [loadingChart, setLoadingChart] = useState(false);

  // Clickable legend: hidden series
  const [hiddenSeries, setHiddenSeries] = useState(new Set());

  const refreshRef = useRef(null);

  /* ── Data Loading ── */

  const loadPrices = useCallback(async () => {
    try {
      const res = await getCryptoPrices();
      setPrices(res.data);
    } catch (err) {
      console.error('Failed to load prices:', err);
    }
    setLoadingPrices(false);
  }, []);

  const loadWallets = useCallback(async () => {
    try {
      const res = await getWallets();
      setWallets(res.data);
      return res.data;
    } catch (err) {
      console.error('Failed to load wallets:', err);
      return [];
    }
  }, []);

  // Auto-load ALL wallet balances
  const loadAllBalances = useCallback(async (walletList) => {
    if (!walletList || walletList.length === 0) return;
    setLoadingBalances(true);
    const results = {};
    await Promise.all(
      walletList.map(async (w) => {
        try {
          const res = await getWalletBalances(w.id);
          results[w.id] = res.data;
        } catch (err) {
          console.error(`Failed to load balances for ${w.label || w.address}:`, err);
        }
      })
    );
    setBalances((prev) => ({ ...prev, ...results }));
    setLoadingBalances(false);
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const res = await getWeb3Settings();
      setSettings(res.data);
      setSettingsDraft(res.data);
    } catch (err) {
      console.error('Failed to load settings:', err);
    }
  }, []);

  const loadChart = useCallback(async () => {
    setLoadingChart(true);
    try {
      const res = await getPortfolioHistory(chartWalletId, chartHours);
      setChartData(res.data);
    } catch (err) {
      console.error('Failed to load chart:', err);
    }
    setLoadingChart(false);
  }, [chartWalletId, chartHours]);

  // Initial load: prices, wallets + their balances, settings
  useEffect(() => {
    loadPrices();
    loadSettings();
    loadWallets().then((wList) => {
      if (wList.length > 0) loadAllBalances(wList);
    });
  }, [loadPrices, loadWallets, loadSettings, loadAllBalances]);

  useEffect(() => {
    loadChart();
  }, [loadChart]);

  // Auto-refresh prices AND balances using settings interval
  useEffect(() => {
    if (refreshRef.current) clearInterval(refreshRef.current);
    const interval = Math.max(settings.refresh_interval * 1000, 60000);
    refreshRef.current = setInterval(() => {
      loadPrices();
      loadWallets().then((wList) => {
        if (wList.length > 0) loadAllBalances(wList);
      });
      loadChart();
    }, interval);
    return () => clearInterval(refreshRef.current);
  }, [loadPrices, loadWallets, loadAllBalances, loadChart, settings.refresh_interval]);

  /* ── Handlers ── */

  async function handleAddWallet(e) {
    e.preventDefault();
    setAddError('');
    try {
      await addWallet(newAddress, newLabel);
      setNewAddress('');
      setNewLabel('');
      const wList = await loadWallets();
      loadAllBalances(wList);
    } catch (err) {
      setAddError(err.response?.data?.detail || 'Failed to add wallet');
    }
  }

  async function handleRemoveWallet(id) {
    if (!window.confirm('Remove this wallet?')) return;
    try {
      await removeWallet(id);
      setBalances((prev) => { const n = { ...prev }; delete n[id]; return n; });
      await loadWallets();
    } catch (err) {
      console.error('Failed to remove wallet:', err);
    }
  }

  function toggleWalletExpand(walletId) {
    setExpandedWallet((prev) => prev === walletId ? null : walletId);
  }

  async function handleLoadTransactions(walletId, chain) {
    if (txWalletId === walletId && txChain === chain && txData) {
      setTxWalletId(null);
      setTxData(null);
      return;
    }
    setTxWalletId(walletId);
    setTxChain(chain);
    setLoadingTx(true);
    try {
      const res = await getWalletTransactions(walletId, chain);
      setTxData(res.data);
    } catch (err) {
      console.error('Failed to load transactions:', err);
    }
    setLoadingTx(false);
  }

  async function handleSaveSettings() {
    try {
      const res = await updateWeb3Settings(settingsDraft);
      setSettings(res.data);
      setShowSettings(false);
    } catch (err) {
      console.error('Failed to save settings:', err);
    }
  }

  function totalPortfolioValue() {
    let total = 0;
    for (const wb of Object.values(balances)) {
      for (const chain of Object.values(wb.chains || {})) {
        total += chain.total_value_usd || chain.value_usd || 0;
      }
    }
    return total;
  }

  // Wallet values for pie chart
  function walletValues() {
    return wallets.map((w) => {
      const wb = balances[w.id];
      if (!wb) return { name: w.label || shortAddr(w.address), value: 0 };
      const val = Object.values(wb.chains || {}).reduce((s, c) => s + (c.total_value_usd || c.value_usd || 0), 0);
      return { name: w.label || shortAddr(w.address), value: Math.round(val * 100) / 100 };
    }).filter((d) => d.value > 0);
  }

  /* ── Chart data transform ── */
  const chartPoints = chartData.map((d) => ({
    ts: new Date(d.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
    total: d.total_value_usd,
    ...Object.fromEntries(
      Object.entries(d.wallets || {}).map(([wid, w]) => [w.label || shortAddr(wid), w.value])
    ),
  }));

  // Collect all wallet keys for lines
  const walletKeysSet = new Set();
  chartData.forEach((d) => {
    Object.entries(d.wallets || {}).forEach(([wid, w]) => {
      walletKeysSet.add(w.label || shortAddr(wid));
    });
  });
  const walletKeys = [...walletKeysSet];

  // All series for clickable legend
  const allSeries = [
    { key: 'total', name: 'Total', color: 'var(--accent)' },
    ...walletKeys.map((k, i) => ({ key: k, name: k, color: WALLET_COLORS[i % WALLET_COLORS.length] })),
  ];

  function handleLegendClick(seriesKey) {
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(seriesKey)) next.delete(seriesKey);
      else next.add(seriesKey);
      return next;
    });
  }

  const pieData = walletValues();
  const portfolioTotal = totalPortfolioValue();

  return (
    <div>
      {/* ── Header ── */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <IC.bitcoin size={28} /> Web3 Dashboard
        </h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-outline" onClick={() => setShowSettings(!showSettings)}>
            <IC.settings size={16} /> Settings
          </button>
          <button className="btn btn-outline" onClick={() => {
            setLoadingPrices(true);
            loadPrices();
            loadWallets().then((wList) => loadAllBalances(wList));
            loadChart();
          }}>
            <IC.refresh size={16} /> Refresh
          </button>
        </div>
      </div>

      {/* ── Settings Panel ── */}
      {showSettings && (
        <div className="card" style={{ marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <IC.settings size={18} /> Web3 Settings
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
            <div>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
                Refresh interval (seconds)
              </label>
              <input
                type="number" min={60} step={30}
                value={settingsDraft.refresh_interval || 300}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, refresh_interval: parseInt(e.target.value) || 300 })}
                style={{ width: '100%' }}
              />
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Min: 60s. Controls portfolio snapshot frequency.</span>
            </div>
            <div>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
                Full-res retention (hours)
              </label>
              <input
                type="number" min={1} step={1}
                value={settingsDraft.retention_full_hours || 168}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, retention_full_hours: parseInt(e.target.value) || 168 })}
                style={{ width: '100%' }}
              />
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Keep every snapshot for this period (default: 168 = 7 days).</span>
            </div>
            <div>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
                Downsample step (hours)
              </label>
              <input
                type="number" min={1} step={1}
                value={settingsDraft.retention_step_hours || 1}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, retention_step_hours: parseInt(e.target.value) || 1 })}
                style={{ width: '100%' }}
              />
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>After retention period, keep one snapshot per this many hours.</span>
            </div>
          </div>
          <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-primary" onClick={handleSaveSettings}>
              <IC.save size={14} /> Save
            </button>
            <button className="btn btn-outline" onClick={() => { setSettingsDraft(settings); setShowSettings(false); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Price Cards ── */}
      <div className="grid grid-3" style={{ marginBottom: '1.5rem' }}>
        {Object.entries(COIN_META).map(([id, meta]) => {
          const data = prices[id] || {};
          return (
            <div className="card" key={id}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: '50%',
                    background: `${meta.color}22`, color: meta.color,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontWeight: 700, fontSize: '0.9rem',
                  }}>
                    {meta.symbol}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '1rem' }}>{meta.name}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{meta.symbol}</div>
                  </div>
                </div>
              </div>
              <div style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.5rem', letterSpacing: '-0.02em' }}>
                {loadingPrices ? <IC.loader size={24} /> : formatUsd(data.price)}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.2rem 1rem', marginBottom: '0.5rem' }}>
                {[
                  { label: '24h', key: 'change_24h' },
                  { label: '7d', key: 'change_7d' },
                  { label: '30d', key: 'change_30d' },
                  { label: '1y', key: 'change_1y' },
                ].map(({ label, key }) => {
                  const val = data[key];
                  if (val == null) return <div key={key} />;
                  const pos = val > 0;
                  return (
                    <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', padding: '0.1rem 0' }}>
                      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                      <span style={{ color: pos ? 'var(--success)' : 'var(--error)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.15rem' }}>
                        {pos ? <IC.trendingUp size={12} /> : <IC.trendingDown size={12} />}
                        {pos ? '+' : ''}{val.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                MCap: {formatMarketCap(data.market_cap)}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Portfolio Value + Pie Chart ── */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <IC.activity size={18} /> Portfolio Value
            <span style={{ color: 'var(--accent)', fontWeight: 700, fontSize: '1.4rem', marginLeft: '0.75rem' }}>
              {loadingBalances && portfolioTotal === 0 ? <IC.loader size={18} /> : formatUsd(portfolioTotal)}
            </span>
          </h2>
          <div style={{ display: 'flex', gap: '0.3rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <select
              value={chartWalletId || ''}
              onChange={(e) => setChartWalletId(e.target.value || null)}
              style={{ fontSize: '0.8rem', padding: '0.3rem 0.5rem', background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}
            >
              <option value="">All Wallets</option>
              {wallets.map((w) => (
                <option key={w.id} value={w.id}>{w.label || shortAddr(w.address)}</option>
              ))}
            </select>
            {[24, 168, 720, 2160].map((h) => (
              <button
                key={h}
                className={`btn ${chartHours === h ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
                onClick={() => setChartHours(h)}
              >
                {h <= 24 ? '24H' : h <= 168 ? '7D' : h <= 720 ? '30D' : '90D'}
              </button>
            ))}
          </div>
        </div>

        {loadingChart ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
            <IC.loader size={20} /> Loading chart...
          </div>
        ) : chartPoints.length > 0 ? (
          <>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {/* Line Chart — 75% */}
              <div style={{ flex: 3, minWidth: 0 }}>
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={chartPoints} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="ts" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} interval="preserveStartEnd" />
                    <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickFormatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}`} />
                    <Tooltip
                      contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', fontSize: '0.8rem' }}
                      formatter={(v) => [`$${Number(v).toFixed(2)}`, undefined]}
                    />
                    {!hiddenSeries.has('total') && (
                      <Line type="monotone" dataKey="total" name="Total" stroke="var(--accent)" strokeWidth={2} dot={false} />
                    )}
                    {!chartWalletId && walletKeys.map((k, i) => (
                      !hiddenSeries.has(k) && (
                        <Line key={k} type="monotone" dataKey={k} name={k} stroke={WALLET_COLORS[i % WALLET_COLORS.length]} strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
                      )
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Pie Chart — 25% */}
              {pieData.length > 0 && (
                <div style={{ flex: 1, minWidth: 140, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={75} paddingAngle={2} strokeWidth={0}>
                        {pieData.map((_, i) => <Cell key={i} fill={WALLET_COLORS[i % WALLET_COLORS.length]} />)}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', fontSize: '0.75rem' }}
                        formatter={(v, name) => {
                          const pct = portfolioTotal > 0 ? (v / portfolioTotal * 100).toFixed(1) : 0;
                          return [`${formatUsd(v)} (${pct}%)`, name];
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  {/* Pie legend */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem', fontSize: '0.7rem', width: '100%', padding: '0 0.25rem' }}>
                    {pieData.map((d, i) => (
                      <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.3rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', minWidth: 0 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: WALLET_COLORS[i % WALLET_COLORS.length], flexShrink: 0 }} />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                        </div>
                        <span style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{portfolioTotal > 0 ? `${(d.value / portfolioTotal * 100).toFixed(1)}%` : '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Clickable Legend */}
            {!chartWalletId && (
              <div style={{ display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.75rem' }}>
                {allSeries.map((s) => {
                  const isHidden = hiddenSeries.has(s.key);
                  return (
                    <button
                      key={s.key}
                      onClick={() => handleLegendClick(s.key)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '0.3rem',
                        padding: '0.2rem 0.5rem', fontSize: '0.75rem',
                        background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        cursor: 'pointer', color: isHidden ? 'var(--text-muted)' : 'var(--text-primary)',
                        opacity: isHidden ? 0.4 : 1, transition: 'opacity 0.15s',
                      }}
                    >
                      <div style={{ width: 10, height: 3, background: s.color, borderRadius: 1, opacity: isHidden ? 0.3 : 1 }} />
                      {s.name}
                    </button>
                  );
                })}
              </div>
            )}
          </>
        ) : (
          <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            No snapshot data yet. Data will appear after the first snapshot cycle ({settings.refresh_interval}s).
            <div style={{ marginTop: '0.5rem' }}>
              <button className="btn btn-outline" style={{ fontSize: '0.75rem' }} onClick={async () => { await triggerSnapshot(); loadChart(); }}>
                <IC.play size={12} /> Take Snapshot Now
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Wallet Tracker ── */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <IC.wallet size={20} /> Wallet Tracker
          </h2>
          {loadingBalances && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}><IC.loader size={14} /> Loading balances…</span>}
        </div>

        {/* Add wallet form */}
        <form onSubmit={handleAddWallet} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <input type="text" placeholder="0x... wallet address" value={newAddress} onChange={(e) => setNewAddress(e.target.value)} style={{ flex: 2, minWidth: '250px' }} required />
          <input type="text" placeholder="Label (optional)" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} style={{ flex: 1, minWidth: '120px' }} />
          <button type="submit" className="btn btn-primary"><IC.plus size={16} /> Add Wallet</button>
        </form>
        {addError && (
          <div style={{ color: 'var(--error)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
            <IC.alertTriangle size={14} /> {addError}
          </div>
        )}

        {wallets.length === 0 && (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', fontStyle: 'italic' }}>
            No wallets tracked yet. Add an EVM-compatible address above.
          </p>
        )}

        {wallets.map((w) => {
          const isExpanded = expandedWallet === w.id;
          const wb = balances[w.id];
          const walletTotal = wb ? Object.values(wb.chains || {}).reduce((sum, c) => sum + (c.total_value_usd || c.value_usd || 0), 0) : null;
          return (
            <div key={w.id} style={{ marginBottom: '0.5rem' }}>
              {/* Wallet Row */}
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.7rem 0.85rem',
                  background: 'var(--bg-primary)', borderRadius: 'var(--radius)',
                  border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--border)'}`,
                  cursor: 'pointer', transition: 'border-color 0.15s',
                }}
                onClick={() => toggleWalletExpand(w.id)}
                onMouseEnter={(e) => { if (!isExpanded) e.currentTarget.style.borderColor = 'var(--accent)'; }}
                onMouseLeave={(e) => { if (!isExpanded) e.currentTarget.style.borderColor = 'var(--border)'; }}
              >
                <span style={{ color: 'var(--text-muted)' }}>
                  {isExpanded ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}
                </span>
                <IC.wallet size={18} style={{ color: 'var(--accent)' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{w.label || 'Unnamed'}</span>
                    <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {shortAddr(w.address)}
                    </span>
                    <CopyBtn text={w.address} />
                  </div>
                </div>
                {walletTotal != null ? (
                  <span style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent)', letterSpacing: '-0.01em' }}>
                    {formatUsd(walletTotal)}
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}><IC.loader size={14} /></span>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); handleRemoveWallet(w.id); }}
                  style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', padding: '0.2rem' }}
                  title="Remove wallet"
                >
                  <IC.trash size={15} />
                </button>
              </div>

              {/* Expanded: Balances + Transactions */}
              {isExpanded && (
                <div style={{ padding: '0.85rem', marginTop: '-1px', border: '1px solid var(--accent)', borderTop: 'none', borderRadius: '0 0 var(--radius) var(--radius)', background: 'var(--bg-card)' }}>
                  {!wb ? (
                    <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-muted)' }}>
                      <IC.loader size={18} /> Loading balances…
                    </div>
                  ) : (
                    <>
                      {/* Chain Cards */}
                      <div className="grid grid-3" style={{ gap: '0.75rem' }}>
                        {Object.entries(wb.chains || {}).map(([chainId, chain]) => (
                          <div key={chainId} style={{ padding: '0.85rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg-primary)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                              <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{chain.chain}</span>
                              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{chain.symbol}</span>
                            </div>
                            <div style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.15rem' }}>
                              {chain.balance != null ? `${chain.balance} ${chain.symbol}` : '—'}
                            </div>
                            <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--accent)', marginBottom: '0.3rem' }}>
                              {formatUsd(chain.value_usd)}
                            </div>

                            {/* Tokens */}
                            {chain.tokens && chain.tokens.length > 0 && (
                              <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.5rem', marginTop: '0.3rem' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.3rem', fontWeight: 600 }}>
                                  Tokens ({chain.tokens.length})
                                </div>
                                {chain.tokens.map((token, i) => (
                                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.2rem 0', fontSize: '0.85rem' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', minWidth: 0 }}>
                                      <span style={{ fontWeight: 600 }}>{token.symbol}</span>
                                      <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                                        {token.balance > 1000 ? `${(token.balance / 1000).toFixed(1)}k` : token.balance.toFixed(4)}
                                      </span>
                                      {token.contract && <CopyBtn text={token.contract} size={11} />}
                                    </div>
                                    <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{formatUsd(token.value_usd)}</span>
                                  </div>
                                ))}
                                <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--border)', marginTop: '0.3rem', paddingTop: '0.3rem', fontSize: '0.85rem' }}>
                                  <span style={{ color: 'var(--text-muted)' }}>Tokens total</span>
                                  <span style={{ fontWeight: 700, color: 'var(--accent)', fontSize: '0.95rem' }}>{formatUsd(chain.tokens_value_usd)}</span>
                                </div>
                              </div>
                            )}

                            {chain.total_value_usd != null && chain.total_value_usd !== chain.value_usd && (
                              <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--warning)', marginTop: '0.4rem', borderTop: '1px solid var(--border)', paddingTop: '0.3rem', display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Chain Total</span>
                                {formatUsd(chain.total_value_usd)}
                              </div>
                            )}

                            {/* Per-chain token distribution pie */}
                            <TokenPieChart tokens={chain.tokens} nativeSymbol={chain.symbol} nativeValueUsd={chain.value_usd || 0} />

                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.5rem' }}>
                              <a
                                href={chain.explorer_url} target="_blank" rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}
                              >
                                <IC.externalLink size={12} /> Explorer
                              </a>
                              <button
                                className="btn btn-outline"
                                style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem' }}
                                onClick={(e) => { e.stopPropagation(); handleLoadTransactions(w.id, chainId); }}
                              >
                                <IC.fileText size={12} /> Transactions
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Full address + copy */}
                      <div style={{ marginTop: '0.6rem', display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Full address: <span style={{ fontFamily: 'monospace' }}>{wb.address}</span>
                        <CopyBtn text={wb.address} />
                      </div>
                    </>
                  )}

                  {/* Transaction History Panel */}
                  {txWalletId === w.id && (
                    <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <h3 style={{ margin: 0, fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <IC.fileText size={16} /> Transaction History
                        </h3>
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          {CHAIN_IDS.map((cid) => (
                            <button
                              key={cid}
                              className={`btn ${txChain === cid ? 'btn-primary' : 'btn-outline'}`}
                              style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', textTransform: 'capitalize' }}
                              onClick={(e) => { e.stopPropagation(); handleLoadTransactions(w.id, cid); }}
                            >
                              {cid === 'bnb' ? 'BNB' : cid.charAt(0).toUpperCase() + cid.slice(1)}
                            </button>
                          ))}
                        </div>
                      </div>

                      {loadingTx ? (
                        <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-muted)' }}>
                          <IC.loader size={16} /> Loading transactions…
                        </div>
                      ) : txData ? (
                        <div>
                          {/* Native Transactions */}
                          {txData.transactions && txData.transactions.length > 0 && (
                            <div style={{ marginBottom: '1rem' }}>
                              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '0.4rem' }}>
                                Transactions ({txData.transactions.length})
                              </div>
                              <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                                {txData.transactions.map((tx, i) => (
                                  <div key={i} style={{
                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                    padding: '0.5rem 0.6rem', marginBottom: '0.3rem',
                                    background: 'var(--bg-primary)', borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border)', fontSize: '0.8rem',
                                  }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.15rem' }}>
                                        <span style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                          {shortAddr(tx.hash)}
                                        </span>
                                        <CopyBtn text={tx.hash} size={11} />
                                        {tx.method && (
                                          <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.35rem', background: 'var(--bg-hover)', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                            {tx.method}
                                          </span>
                                        )}
                                        {tx.status === 'error' && (
                                          <span style={{ color: 'var(--error)', fontSize: '0.7rem', fontWeight: 600 }}>Failed</span>
                                        )}
                                      </div>
                                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem' }}>
                                        <span>From: {shortAddr(tx.from)}</span>
                                        <span>→ To: {shortAddr(tx.to)}</span>
                                      </div>
                                    </div>
                                    <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                      <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>
                                        {tx.value > 0 ? `${tx.value} ${tx.symbol}` : '—'}
                                      </div>
                                      <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                                        {tx.fee > 0 && `Fee: ${tx.fee} ${tx.symbol}`}
                                        {tx.timestamp && ` · ${timeAgo(tx.timestamp)}`}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Token Transfers */}
                          {txData.token_transfers && txData.token_transfers.length > 0 && (
                            <div>
                              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '0.4rem' }}>
                                Token Transfers ({txData.token_transfers.length})
                              </div>
                              <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                                {txData.token_transfers.map((t, i) => (
                                  <div key={i} style={{
                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                    padding: '0.4rem 0.6rem', marginBottom: '0.3rem',
                                    background: 'var(--bg-primary)', borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border)', fontSize: '0.8rem',
                                  }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <span style={{ fontFamily: 'monospace', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                          {shortAddr(t.hash)}
                                        </span>
                                        <CopyBtn text={t.hash} size={11} />
                                        {t.method && (
                                          <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.35rem', background: 'var(--bg-hover)', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                                            {t.method}
                                          </span>
                                        )}
                                      </div>
                                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'flex', gap: '0.5rem' }}>
                                        <span>From: {shortAddr(t.from)}</span>
                                        <span>→ To: {shortAddr(t.to)}</span>
                                      </div>
                                    </div>
                                    <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                      <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>
                                        {t.amount} <span style={{ color: 'var(--accent)' }}>{t.token_symbol}</span>
                                      </div>
                                      <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                                        {t.timestamp && timeAgo(t.timestamp)}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {(!txData.transactions || txData.transactions.length === 0) &&
                           (!txData.token_transfers || txData.token_transfers.length === 0) && (
                            <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                              No transactions found on this chain.
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
