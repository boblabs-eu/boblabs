/**
 * Bob Labs — MCP (Model Context Protocol) server management.
 *
 * A standalone catalog of external MCP servers the operator can enable/disable
 * and extend with custom entries. Enabled servers expose their tools to agents
 * as `mcp__<slug>__<tool>` (selectable in the agent tool picker, or as a whole
 * server via the `mcp:<slug>` token).
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  getMcpCatalog,
  getMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  testMcpServer,
} from '../services/api';

function errText(e) {
  return e?.response?.data?.detail || e?.message || 'Request failed';
}

const EMPTY_CUSTOM = {
  name: '',
  transport: 'http',
  url: '',
  command: '',
  args: '',
  auth_token: '',
};

export default function McpPage() {
  const [catalog, setCatalog] = useState([]);
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(null);
  const [tests, setTests] = useState({});
  const [tokenDrafts, setTokenDrafts] = useState({});
  const [showCustom, setShowCustom] = useState(false);
  const [custom, setCustom] = useState(EMPTY_CUSTOM);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, s] = await Promise.all([getMcpCatalog(), getMcpServers()]);
      setCatalog(c.data || []);
      setServers(s.data || []);
      setError('');
    } catch (e) {
      setError(errText(e));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const serverByCatalogKey = {};
  servers.forEach((s) => {
    if (s.catalog_key) serverByCatalogKey[s.catalog_key] = s;
  });

  async function enableCatalog(entry) {
    setBusy(`cat:${entry.key}`);
    try {
      await createMcpServer({
        catalog_key: entry.key,
        auth_token: tokenDrafts[entry.key] || null,
        enabled: true,
      });
      setTokenDrafts((d) => ({ ...d, [entry.key]: '' }));
      await load();
    } catch (e) {
      setError(errText(e));
    }
    setBusy(null);
  }

  async function toggleEnabled(s) {
    setBusy(s.id);
    try {
      await updateMcpServer(s.id, { enabled: !s.enabled });
      await load();
    } catch (e) {
      setError(errText(e));
    }
    setBusy(null);
  }

  async function removeServer(s) {
    if (!window.confirm(`Remove MCP server "${s.name}"? Its tools will be unregistered.`)) return;
    setBusy(s.id);
    try {
      await deleteMcpServer(s.id);
      setTests((t) => {
        const next = { ...t };
        delete next[s.id];
        return next;
      });
      await load();
    } catch (e) {
      setError(errText(e));
    }
    setBusy(null);
  }

  async function runTest(s) {
    setBusy(s.id);
    setTests((t) => ({ ...t, [s.id]: { loading: true } }));
    try {
      const r = await testMcpServer(s.id);
      setTests((t) => ({ ...t, [s.id]: r.data }));
    } catch (e) {
      setTests((t) => ({ ...t, [s.id]: { healthy: false, error: errText(e) } }));
    }
    setBusy(null);
  }

  async function addCustom(e) {
    e.preventDefault();
    setBusy('add');
    try {
      const isStdio = custom.transport === 'stdio';
      await createMcpServer({
        name: custom.name.trim(),
        transport: custom.transport,
        url: isStdio ? null : custom.url.trim(),
        command: isStdio ? custom.command.trim() : null,
        args: isStdio ? custom.args.split(' ').filter(Boolean) : [],
        auth_token: custom.auth_token.trim() || null,
        enabled: true,
      });
      setCustom(EMPTY_CUSTOM);
      setShowCustom(false);
      await load();
    } catch (err) {
      setError(errText(err));
    }
    setBusy(null);
  }

  return (
    <div className="mcp-page">
      <div className="mcp-page-head">
        <div>
          <h1>MCP Servers</h1>
          <p className="mcp-sub">
            Connect external Model Context Protocol servers. Enabled servers expose their
            tools to agents as <code>mcp__&lt;slug&gt;__&lt;tool&gt;</code> — selectable in the
            agent tool picker, or as a whole server via <code>mcp:&lt;slug&gt;</code>.
          </p>
        </div>
        <button className="mcp-btn" onClick={load} disabled={loading}>
          ↻ Refresh
        </button>
      </div>

      {error && (
        <div className="mcp-error" onClick={() => setError('')}>
          {error} <span className="mcp-error-dismiss">✕</span>
        </div>
      )}

      {/* ── Catalog ─────────────────────────── */}
      <h2 className="mcp-section-title">Available MCPs</h2>
      <div className="mcp-grid">
        {catalog.map((entry) => {
          const existing = serverByCatalogKey[entry.key];
          const isBusy = busy === `cat:${entry.key}`;
          return (
            <div key={entry.key} className="mcp-card">
              <div className="mcp-card-head">
                <span className="mcp-card-name">{entry.name}</span>
                {entry.auth === 'bearer' && <span className="mcp-tag">token</span>}
                <span className="mcp-tag mcp-tag-transport">{entry.transport}</span>
              </div>
              <p className="mcp-card-desc">{entry.description}</p>
              {existing ? (
                <div className="mcp-card-state">
                  <span className={existing.enabled ? 'mcp-on' : 'mcp-off'}>
                    {existing.enabled ? '● Enabled' : '○ Disabled'}
                  </span>
                  <span className="mcp-slug">added below</span>
                </div>
              ) : (
                <div className="mcp-card-enable">
                  {entry.auth === 'bearer' && (
                    <input
                      className="mcp-input"
                      type="password"
                      placeholder="API token"
                      value={tokenDrafts[entry.key] || ''}
                      onChange={(ev) =>
                        setTokenDrafts((d) => ({ ...d, [entry.key]: ev.target.value }))
                      }
                    />
                  )}
                  <button
                    className="mcp-btn mcp-btn-primary"
                    onClick={() => enableCatalog(entry)}
                    disabled={isBusy}
                  >
                    {isBusy ? 'Enabling…' : 'Enable'}
                  </button>
                </div>
              )}
              {entry.docs_url && (
                <a className="mcp-docs" href={entry.docs_url} target="_blank" rel="noopener noreferrer">
                  docs ↗
                </a>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Configured servers ───────────────── */}
      <div className="mcp-section-title-row">
        <h2 className="mcp-section-title">Your MCP servers</h2>
        <button className="mcp-btn" onClick={() => setShowCustom((v) => !v)}>
          {showCustom ? 'Cancel' : '+ Add MCP'}
        </button>
      </div>

      {showCustom && (
        <form className="mcp-custom-form" onSubmit={addCustom}>
          <div className="mcp-form-row">
            <input
              className="mcp-input"
              placeholder="Name (e.g. My Server)"
              value={custom.name}
              onChange={(e) => setCustom({ ...custom, name: e.target.value })}
              required
            />
            <select
              className="mcp-input"
              value={custom.transport}
              onChange={(e) => setCustom({ ...custom, transport: e.target.value })}
            >
              <option value="http">http (streamable)</option>
              <option value="sse">sse</option>
              <option value="stdio">stdio (local subprocess)</option>
            </select>
          </div>
          {custom.transport === 'stdio' ? (
            <div className="mcp-form-row">
              <input
                className="mcp-input"
                placeholder="command (e.g. npx)"
                value={custom.command}
                onChange={(e) => setCustom({ ...custom, command: e.target.value })}
                required
              />
              <input
                className="mcp-input"
                placeholder="args (space-separated)"
                value={custom.args}
                onChange={(e) => setCustom({ ...custom, args: e.target.value })}
              />
            </div>
          ) : (
            <div className="mcp-form-row">
              <input
                className="mcp-input mcp-input-wide"
                placeholder="https://mcp.example.com/mcp"
                value={custom.url}
                onChange={(e) => setCustom({ ...custom, url: e.target.value })}
                required
              />
              <input
                className="mcp-input"
                type="password"
                placeholder="auth token (optional)"
                value={custom.auth_token}
                onChange={(e) => setCustom({ ...custom, auth_token: e.target.value })}
              />
            </div>
          )}
          {custom.transport === 'stdio' && (
            <p className="mcp-warn">
              ⚠ stdio spawns a subprocess on the control-plane host. Requires
              <code> MCP_ENABLE_STDIO=true</code> on the server to actually connect.
            </p>
          )}
          <button className="mcp-btn mcp-btn-primary" type="submit" disabled={busy === 'add'}>
            {busy === 'add' ? 'Adding…' : 'Add & enable'}
          </button>
        </form>
      )}

      {loading ? (
        <div className="mcp-empty">Loading…</div>
      ) : servers.length === 0 ? (
        <div className="mcp-empty">No MCP servers yet. Enable one from the catalog above.</div>
      ) : (
        <div className="mcp-list">
          {servers.map((s) => {
            const test = tests[s.id];
            return (
              <div key={s.id} className="mcp-row">
                <div className="mcp-row-main">
                  <span className="mcp-row-name">{s.name}</span>
                  <code className="mcp-slug">mcp:{s.slug}</code>
                  <span className="mcp-tag mcp-tag-transport">{s.transport}</span>
                  {s.source === 'catalog' && <span className="mcp-tag">catalog</span>}
                  {s.url && <span className="mcp-url">{s.url}</span>}
                </div>
                <div className="mcp-row-actions">
                  <label className="mcp-switch" title={s.enabled ? 'Enabled' : 'Disabled'}>
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      disabled={busy === s.id}
                      onChange={() => toggleEnabled(s)}
                    />
                    <span className="mcp-switch-track" />
                  </label>
                  <button className="mcp-btn" onClick={() => runTest(s)} disabled={busy === s.id}>
                    Test
                  </button>
                  <button
                    className="mcp-btn mcp-btn-danger"
                    onClick={() => removeServer(s)}
                    disabled={busy === s.id}
                  >
                    Delete
                  </button>
                </div>
                {test && (
                  <div className="mcp-test">
                    {test.loading ? (
                      'Connecting…'
                    ) : test.healthy ? (
                      <>
                        <span className="mcp-on">✓ {test.tool_count} tools</span>
                        <span className="mcp-test-tools">
                          {test.tools.map((t) => t.name).join(', ')}
                        </span>
                      </>
                    ) : (
                      <span className="mcp-off">✕ {test.error || 'Unreachable'}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
