/**
 * Bob Labs — Admin panel.
 * Admin authenticates with ADMIN_SECRET, then manages trial requests and tokens.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  getTrialRequests,
  getAccessTokens,
  createAccessToken,
  revokeAccessToken,
  updateTrialRequestStatus,
  adminLogin,
  getInfraWhitelist,
  updateInfraWhitelist,
  getQuoteRequests,
  updateQuoteRequestStatus,
  getBlogTokens,
  createBlogToken,
  revokeBlogToken,
  getBlogPostsAdmin,
  deleteBlogPost,
  getConsumerApps,
  createConsumerApp,
  revokeConsumerApp,
  deleteConsumerApp,
  adminListLabs,
  adminSetLabVisibility,
} from '../services/api';
import AdminLogs from '../components/admin/AdminLogs';

/* ─── Admin Login ──────────────────────────────────── */
function AdminLogin({ onAuth }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!password.trim()) return;
    setError('');
    setLoading(true);
    try {
      const res = await adminLogin(password.trim());
      onAuth(res.data.access_token);
    } catch {
      setError('Invalid admin credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <Link to="/" className="login-brand">Bob Labs</Link>
        <h1>Admin Access</h1>
        <p className="login-subtitle">Enter the admin password to manage the platform.</p>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Admin password"
            className="login-input"
            autoFocus
          />
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? 'Authenticating…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}

/* ─── Generate Token Modal ─────────────────────────── */
function GenerateTokenModal({ request, onClose, onCreated }) {
  const [days, setDays] = useState(30);
  const [label, setLabel] = useState(request ? `Trial — ${request.name}` : '');
  const [sendEmail, setSendEmail] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const expires = new Date();
      expires.setDate(expires.getDate() + days);
      const res = await createAccessToken({
        label,
        email: request?.email || '',
        expires_at: expires.toISOString(),
        send_email: sendEmail,
      });
      setResult(res.data);
      if (request) {
        await updateTrialRequestStatus(request.id, 'approved');
      }
      onCreated();
    } catch {
      setResult({ error: true });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-modal-overlay" onClick={onClose}>
      <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Generate Access Token</h2>
        {result ? (
          result.error ? (
            <p className="login-error">Failed to create token.</p>
          ) : (
            <div>
              <p style={{ color: '#059669', fontWeight: 600 }}>Token created successfully!</p>
              <div className="admin-token-display">{result.token}</div>
              <p style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                Expires: {new Date(result.expires_at).toLocaleDateString()}
                {sendEmail && request?.email && <><br />Email sent to {request.email}</>}
              </p>
              <button className="login-btn" onClick={onClose} style={{ marginTop: '1rem' }}>Close</button>
            </div>
          )
        ) : (
          <>
            {request && (
              <p style={{ margin: '0 0 1rem', color: '#6b7280' }}>
                For: <strong>{request.name}</strong> ({request.email})
              </p>
            )}
            <label className="admin-label">Label</label>
            <input
              className="login-input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Token label"
            />
            <label className="admin-label">Expires in (days)</label>
            <input
              className="login-input"
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
            {request?.email && (
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={sendEmail}
                  onChange={(e) => setSendEmail(e.target.checked)}
                />
                Send token to {request.email} by email
              </label>
            )}
            <button className="login-btn" onClick={handleGenerate} disabled={loading} style={{ marginTop: '1rem' }}>
              {loading ? 'Generating…' : 'Generate Token'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/* ─── Main Admin Dashboard ─────────────────────────── */
function AdminDashboard({ jwt, onLogout }) {
  const [tab, setTab] = useState('requests');
  const [requests, setRequests] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [modalRequest, setModalRequest] = useState(null);
  const [showNewToken, setShowNewToken] = useState(false);
  const [infraEmails, setInfraEmails] = useState([]);
  const [infraInput, setInfraInput] = useState('');
  const [infraSaving, setInfraSaving] = useState(false);
  const [quotes, setQuotes] = useState([]);
  const [blogTokens, setBlogTokens] = useState([]);
  const [blogPosts, setBlogPosts] = useState([]);
  const [newBlogLabel, setNewBlogLabel] = useState('');
  const [visibleTokens, setVisibleTokens] = useState({});
  const [copiedToken, setCopiedToken] = useState(null);
  const [consumerApps, setConsumerApps] = useState([]);
  const [consumerAppError, setConsumerAppError] = useState('');
  const [newConsumerApp, setNewConsumerApp] = useState({ app_id: '', name: '', notes: '' });
  const [createdConsumerApp, setCreatedConsumerApp] = useState(null); // holds one-time secret
  const [labs, setLabs] = useState([]);
  const [labsError, setLabsError] = useState('');
  const [labsBusy, setLabsBusy] = useState({}); // {labId: true} while toggling

  const toggleTokenVisibility = (id) => setVisibleTokens((v) => ({ ...v, [id]: !v[id] }));
  const copyToken = async (id, token) => {
    try { await navigator.clipboard.writeText(token); setCopiedToken(id); setTimeout(() => setCopiedToken(null), 2000); } catch { /* ignore */ }
  };

  // Temporarily set JWT for admin API calls
  const withAdminJwt = useCallback((fn) => {
    const prev = localStorage.getItem('bob_token');
    localStorage.setItem('bob_token', jwt);
    return fn().finally(() => {
      if (prev) localStorage.setItem('bob_token', prev);
      else localStorage.removeItem('bob_token');
    });
  }, [jwt]);

  const loadRequests = useCallback(() => withAdminJwt(() =>
    getTrialRequests().then((r) => setRequests(r.data))
  ), [withAdminJwt]);

  const loadTokens = useCallback(() => withAdminJwt(() =>
    getAccessTokens().then((r) => setTokens(r.data))
  ), [withAdminJwt]);

  const loadInfra = useCallback(() => withAdminJwt(() =>
    getInfraWhitelist().then((r) => {
      const emails = r.data.emails || [];
      setInfraEmails(emails);
      setInfraInput(emails.join(', '));
    })
  ), [withAdminJwt]);

  const loadQuotes = useCallback(() => withAdminJwt(() =>
    getQuoteRequests().then((r) => setQuotes(r.data))
  ), [withAdminJwt]);

  const loadBlogTokens = useCallback(() => withAdminJwt(() =>
    getBlogTokens().then((r) => setBlogTokens(r.data))
  ), [withAdminJwt]);

  const loadBlogPosts = useCallback(() => withAdminJwt(() =>
    getBlogPostsAdmin().then((r) => setBlogPosts(r.data))
  ), [withAdminJwt]);

  const loadConsumerApps = useCallback(() => withAdminJwt(() =>
    getConsumerApps()
      .then((r) => { setConsumerApps(r.data || []); setConsumerAppError(''); })
      .catch((e) => setConsumerAppError(e?.response?.data?.detail || e.message || 'Failed to load consumer apps'))
  ), [withAdminJwt]);

  const loadLabs = useCallback(() => withAdminJwt(() =>
    adminListLabs()
      .then((r) => { setLabs(r.data || []); setLabsError(''); })
      .catch((e) => setLabsError(e?.response?.data?.detail || e.message || 'Failed to load labs'))
  ), [withAdminJwt]);

  const toggleLabVisibility = useCallback(async (labId, nextValue) => {
    setLabsBusy((b) => ({ ...b, [labId]: true }));
    // Optimistic update with rollback on failure
    const prev = labs;
    setLabs((all) => all.map((l) => (l.id === labId ? { ...l, is_public: nextValue } : l)));
    try {
      await withAdminJwt(() => adminSetLabVisibility(labId, nextValue));
    } catch (e) {
      setLabs(prev);
      setLabsError(e?.response?.data?.detail || e.message || 'Failed to toggle visibility');
    } finally {
      setLabsBusy((b) => {
        const { [labId]: _, ...rest } = b;
        return rest;
      });
    }
  }, [labs, withAdminJwt]);

  useEffect(() => {
    loadRequests();
    loadTokens();
    loadInfra();
    loadQuotes();
    loadBlogTokens();
    loadBlogPosts();
    loadConsumerApps();
    loadLabs();
  }, [loadRequests, loadTokens, loadInfra, loadQuotes, loadBlogTokens, loadBlogPosts, loadConsumerApps, loadLabs]);

  const handleCreateConsumerApp = async (e) => {
    e.preventDefault();
    const payload = {
      app_id: newConsumerApp.app_id.trim().toLowerCase(),
      name: newConsumerApp.name.trim(),
      notes: newConsumerApp.notes.trim(),
    };
    if (!payload.app_id) return;
    try {
      const res = await withAdminJwt(() => createConsumerApp(payload));
      setCreatedConsumerApp(res.data);
      setNewConsumerApp({ app_id: '', name: '', notes: '' });
      setConsumerAppError('');
      await loadConsumerApps();
    } catch (err) {
      setConsumerAppError(err?.response?.data?.detail || err.message || 'Failed to create app');
    }
  };

  const handleRevokeConsumerApp = async (id) => {
    if (!window.confirm('Revoke this consumer app? Any deployment using its secret will get 401s.')) return;
    try {
      await withAdminJwt(() => revokeConsumerApp(id));
      await loadConsumerApps();
    } catch (err) {
      setConsumerAppError(err?.response?.data?.detail || err.message || 'Failed to revoke');
    }
  };

  const handleDeleteConsumerApp = async (id, appId) => {
    if (!window.confirm(
      `Permanently delete '${appId}'? This frees the slug for reuse and is irreversible. ` +
      `Any deployment still holding its secret will get 401s.`
    )) return;
    try {
      await withAdminJwt(() => deleteConsumerApp(id));
      await loadConsumerApps();
    } catch (err) {
      setConsumerAppError(err?.response?.data?.detail || err.message || 'Failed to delete');
    }
  };

  const handleSaveInfra = async () => {
    setInfraSaving(true);
    try {
      const emails = infraInput.split(/[,\n]/).map((e) => e.trim()).filter(Boolean);
      await withAdminJwt(() => updateInfraWhitelist(emails));
      setInfraEmails(emails);
    } catch {
      // ignore
    } finally {
      setInfraSaving(false);
    }
  };

  const handleRevoke = async (id) => {
    await withAdminJwt(() => revokeAccessToken(id));
    loadTokens();
  };

  const handleCreateBlogToken = async () => {
    if (!newBlogLabel.trim()) return;
    await withAdminJwt(() => createBlogToken(newBlogLabel.trim()));
    setNewBlogLabel('');
    loadBlogTokens();
  };

  const handleRevokeBlogToken = async (id) => {
    await withAdminJwt(() => revokeBlogToken(id));
    loadBlogTokens();
  };

  const handleDeleteBlogPost = async (id) => {
    await withAdminJwt(() => deleteBlogPost(id));
    loadBlogPosts();
  };

  const handleReject = async (id) => {
    await withAdminJwt(() => updateTrialRequestStatus(id, 'rejected'));
    loadRequests();
  };

  return (
    <div className="admin-page">
      <header className="admin-header">
        <Link to="/" className="login-brand">Bob Labs</Link>
        <span className="admin-badge">Admin Panel</span>
        <button className="lp-btn-ghost" onClick={onLogout}>Sign out</button>
      </header>

      <div className="admin-tabs">
        <button className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}>
          Requests {(requests.filter((r) => r.status === 'pending').length
            + quotes.filter((q) => q.status === 'pending').length) > 0 &&
            <span className="admin-count">{requests.filter((r) => r.status === 'pending').length
              + quotes.filter((q) => q.status === 'pending').length}</span>}
        </button>
        <button className={tab === 'tokens' ? 'active' : ''} onClick={() => setTab('tokens')}>
          Access Tokens <span className="admin-count">{tokens.filter((t) => !t.revoked).length}</span>
        </button>
        <button className={tab === 'infra' ? 'active' : ''} onClick={() => setTab('infra')}>
          Infra Access <span className="admin-count">{infraEmails.length}</span>
        </button>
        <button className={tab === 'blog' ? 'active' : ''} onClick={() => setTab('blog')}>
          Blog <span className="admin-count">{blogTokens.filter((t) => !t.revoked).length}</span>
        </button>
        <button className={tab === 'consumer-apps' ? 'active' : ''} onClick={() => setTab('consumer-apps')}>
          Consumer Apps <span className="admin-count">{consumerApps.filter((a) => !a.revoked_at).length}</span>
        </button>
        <button className={tab === 'labs' ? 'active' : ''} onClick={() => setTab('labs')}>
          Labs <span className="admin-count">{labs.filter((l) => l.is_public).length}/{labs.length}</span>
        </button>
        <button className={tab === 'logs' ? 'active' : ''} onClick={() => setTab('logs')}>
          Logs
        </button>
      </div>

      <div className="admin-content">
        {tab === 'requests' && (
          <>
            {/* ── Trial Requests ── */}
            <div className="admin-toolbar">
              <h2>Trial Requests</h2>
              <button className="lp-btn-primary-sm" onClick={loadRequests}>Refresh</button>
            </div>
            {requests.length === 0 ? (
              <p className="admin-empty">No trial requests yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Name</th><th>Email</th><th>Company</th><th>Role</th><th>Status</th><th>Date</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {requests.map((r) => (
                    <tr key={r.id}>
                      <td>{r.name}</td>
                      <td>{r.email}</td>
                      <td>{r.enterprise || '—'}</td>
                      <td>{r.role || '—'}</td>
                      <td><span className={`admin-status admin-status-${r.status}`}>{r.status}</span></td>
                      <td>{new Date(r.created_at).toLocaleDateString()}</td>
                      <td className="admin-actions">
                        {r.status === 'pending' && (
                          <>
                            <button className="admin-btn-approve" onClick={() => setModalRequest(r)}>
                              Generate Token
                            </button>
                            <button className="admin-btn-reject" onClick={() => handleReject(r.id)}>
                              Reject
                            </button>
                          </>
                        )}
                        {r.status === 'approved' && <span style={{ color: '#059669' }}>Approved</span>}
                        {r.status === 'rejected' && <span style={{ color: '#dc2626' }}>Rejected</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* ── Quote Requests ── */}
            <div className="admin-toolbar" style={{ marginTop: '2rem' }}>
              <h2>Quote Requests</h2>
              <button className="lp-btn-primary-sm" onClick={loadQuotes}>Refresh</button>
            </div>
            {quotes.length === 0 ? (
              <p className="admin-empty">No quote requests yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Name</th><th>Email</th><th>Company</th><th>Phone</th><th>Plan</th><th>Description</th><th>Status</th><th>Date</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {quotes.map((q) => (
                    <tr key={q.id}>
                      <td>{q.name}</td>
                      <td>{q.email}</td>
                      <td>{q.company || '—'}</td>
                      <td>{q.phone || '—'}</td>
                      <td>{q.plan || '—'}</td>
                      <td style={{ maxWidth: 200, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{q.description || '—'}</td>
                      <td><span className={`admin-status admin-status-${q.status}`}>{q.status}</span></td>
                      <td>{new Date(q.created_at).toLocaleDateString()}</td>
                      <td className="admin-actions">
                        {q.status === 'pending' && (
                          <>
                            <button className="admin-btn-approve" onClick={async () => {
                              await withAdminJwt(() => updateQuoteRequestStatus(q.id, 'contacted'));
                              loadQuotes();
                            }}>Contacted</button>
                            <button className="admin-btn-reject" onClick={async () => {
                              await withAdminJwt(() => updateQuoteRequestStatus(q.id, 'closed'));
                              loadQuotes();
                            }}>Close</button>
                          </>
                        )}
                        {q.status === 'contacted' && (
                          <button className="admin-btn-reject" onClick={async () => {
                            await withAdminJwt(() => updateQuoteRequestStatus(q.id, 'closed'));
                            loadQuotes();
                          }}>Close</button>
                        )}
                        {q.status === 'closed' && <span style={{ color: '#6b7280' }}>Closed</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

          </>
        )}

        {tab === 'tokens' && (
          <>
            <div className="admin-toolbar">
              <h2>Access Tokens</h2>
              <div>
                <button className="lp-btn-primary-sm" onClick={() => setShowNewToken(true)} style={{ marginRight: 8 }}>
                  New Token
                </button>
                <button className="lp-btn-ghost" onClick={loadTokens}>Refresh</button>
              </div>
            </div>
            {tokens.length === 0 ? (
              <p className="admin-empty">No tokens generated yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Token</th><th>Label</th><th>Email</th><th>Expires</th><th>Status</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.map((t) => (
                    <tr key={t.id} className={t.revoked ? 'admin-row-revoked' : ''}>
                      <td className="admin-token-cell">
                        <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                          {visibleTokens[t.id] ? t.token : t.token.slice(0, 10) + '••••••••'}
                        </span>
                        <button className="admin-btn-mini" onClick={() => toggleTokenVisibility(t.id)} title={visibleTokens[t.id] ? 'Hide' : 'Show'}>
                          {visibleTokens[t.id] ? '🙈' : '👁'}
                        </button>
                        <button className="admin-btn-mini" onClick={() => copyToken(t.id, t.token)} title="Copy">
                          {copiedToken === t.id ? '✓' : '📋'}
                        </button>
                      </td>
                      <td>{t.label || '—'}</td>
                      <td>{t.email || '—'}</td>
                      <td>{new Date(t.expires_at).toLocaleDateString()}</td>
                      <td>
                        {t.revoked
                          ? <span className="admin-status admin-status-rejected">revoked</span>
                          : new Date(t.expires_at) < new Date()
                            ? <span className="admin-status admin-status-rejected">expired</span>
                            : <span className="admin-status admin-status-approved">active</span>}
                      </td>
                      <td>
                        {!t.revoked && (
                          <button className="admin-btn-reject" onClick={() => handleRevoke(t.id)}>
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab === 'infra' && (
          <>
            <div className="admin-toolbar">
              <h2>Infrastructure Access Whitelist</h2>
              <button className="lp-btn-ghost" onClick={loadInfra}>Refresh</button>
            </div>
            <p style={{ color: '#6b7280', margin: '0 0 1rem' }}>
              Only the emails listed below can access Servers, Workflows, Commands, Terminal, and Logs pages.
              Admins always have access regardless of this list.
            </p>
            <label className="admin-label">Whitelisted emails (comma or newline separated)</label>
            <textarea
              className="login-input"
              rows={6}
              value={infraInput}
              onChange={(e) => setInfraInput(e.target.value)}
              placeholder="user@example.com, another@example.com"
              style={{ fontFamily: 'monospace', fontSize: '0.85rem', resize: 'vertical' }}
            />
            <button
              className="lp-btn-primary-sm"
              onClick={handleSaveInfra}
              disabled={infraSaving}
              style={{ marginTop: '0.75rem' }}
            >
              {infraSaving ? 'Saving…' : 'Save Whitelist'}
            </button>
          </>
        )}

        {tab === 'blog' && (
          <>
            <div className="admin-toolbar">
              <h2>Blog Tokens</h2>
              <button className="lp-btn-primary-sm" onClick={() => { loadBlogTokens(); loadBlogPosts(); }}>Refresh</button>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' }}>
              <input
                className="login-input"
                type="text"
                placeholder="Token label (e.g. agent-researcher)"
                value={newBlogLabel}
                onChange={(e) => setNewBlogLabel(e.target.value)}
                style={{ flex: 1, margin: 0 }}
              />
              <button className="lp-btn-primary-sm" onClick={handleCreateBlogToken}>Create Token</button>
            </div>

            {blogTokens.length === 0 ? (
              <p className="admin-empty">No blog tokens yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Label</th><th>Token</th><th>Status</th><th>Date</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {blogTokens.map((t) => (
                    <tr key={t.id}>
                      <td>{t.label || '—'}</td>
                      <td>
                        <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                          {visibleTokens[`blog-${t.id}`] ? t.token : t.token.slice(0, 10) + '••••••••'}
                        </span>
                        <button className="admin-btn-mini" onClick={() => toggleTokenVisibility(`blog-${t.id}`)} title={visibleTokens[`blog-${t.id}`] ? 'Hide' : 'Show'}>
                          {visibleTokens[`blog-${t.id}`] ? '🙈' : '👁'}
                        </button>
                        <button className="admin-btn-mini" onClick={() => copyToken(`blog-${t.id}`, t.token)} title="Copy">
                          {copiedToken === `blog-${t.id}` ? '✓' : '📋'}
                        </button>
                      </td>
                      <td>
                        <span className={`admin-status admin-status-${t.revoked ? 'rejected' : 'approved'}`}>
                          {t.revoked ? 'revoked' : 'active'}
                        </span>
                      </td>
                      <td>{new Date(t.created_at).toLocaleDateString()}</td>
                      <td className="admin-actions">
                        {!t.revoked && (
                          <button className="admin-btn-reject" onClick={() => handleRevokeBlogToken(t.id)}>Revoke</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="admin-toolbar" style={{ marginTop: '2rem' }}>
              <h2>Blog Posts</h2>
            </div>

            {blogPosts.length === 0 ? (
              <p className="admin-empty">No blog posts yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Title</th><th>Identity</th><th>Tags</th><th>Date</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {blogPosts.map((p) => (
                    <tr key={p.id}>
                      <td>{p.title}</td>
                      <td>{p.identity}</td>
                      <td>{(p.tags || []).join(', ') || '—'}</td>
                      <td>{new Date(p.created_at).toLocaleDateString()}</td>
                      <td className="admin-actions">
                        <button className="admin-btn-reject" onClick={() => handleDeleteBlogPost(p.id)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab === 'consumer-apps' && (
          <>
            <div className="admin-toolbar">
              <h2>Consumer Apps</h2>
              <button className="lp-btn-primary-sm" onClick={loadConsumerApps}>Refresh</button>
            </div>
            <p style={{ opacity: 0.7, fontSize: '0.9rem', marginTop: 0 }}>
              HMAC-authenticated private apps that drive bob-api over the
              internal channel. Creating a new app shows the secret{' '}
              <strong>once</strong> — copy it into the consumer app's{' '}
              <code>BOB_APP_SECRET</code> env var immediately. See{' '}
              <a href="/docs#consumer-apps" target="_blank" rel="noreferrer">
                docs/CONSUMER_APPS.md
              </a>{' '}
              for the integration contract.
            </p>

            <form className="admin-form-inline" onSubmit={handleCreateConsumerApp}>
              <input
                placeholder="app_id (slug, lowercase)"
                value={newConsumerApp.app_id}
                onChange={(e) => setNewConsumerApp((s) => ({ ...s, app_id: e.target.value }))}
                required
              />
              <input
                placeholder="display name"
                value={newConsumerApp.name}
                onChange={(e) => setNewConsumerApp((s) => ({ ...s, name: e.target.value }))}
              />
              <input
                placeholder="notes (optional)"
                value={newConsumerApp.notes}
                onChange={(e) => setNewConsumerApp((s) => ({ ...s, notes: e.target.value }))}
              />
              <button type="submit" className="lp-btn-primary-sm">Create</button>
            </form>

            {consumerAppError && (
              <div
                style={{
                  marginTop: 12,
                  padding: '10px 12px',
                  background: '#3a1a1a',
                  border: '1px solid #d66',
                  color: '#ffd0d0',
                  borderRadius: 4,
                  fontSize: '0.9rem',
                }}
              >
                ⚠ {consumerAppError}
              </div>
            )}

            {createdConsumerApp && (
              <div
                style={{
                  background: '#1a2a4a',
                  border: '1px solid #4a8',
                  color: '#fff',
                  padding: 16,
                  borderRadius: 6,
                  marginTop: 12,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                }}
              >
                <div style={{ color: '#7fe3a4', fontWeight: 600, fontSize: '0.95rem' }}>
                  ✓ Secret for <code style={{ color: '#fff', background: 'rgba(255,255,255,0.08)', padding: '2px 6px', borderRadius: 3 }}>{createdConsumerApp.app_id}</code> — copy it now
                </div>

                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10 }}>
                  <code
                    style={{
                      flex: 1,
                      display: 'block',
                      padding: '10px 12px',
                      background: '#0b1220',
                      color: '#fff',
                      border: '1px solid rgba(255,255,255,0.12)',
                      borderRadius: 4,
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                      fontSize: '0.9rem',
                      wordBreak: 'break-all',
                      userSelect: 'all',
                    }}
                  >
                    {createdConsumerApp.secret}
                  </code>
                  <button
                    className="lp-btn-primary-sm"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(createdConsumerApp.secret);
                        setCopiedToken('consumer-app-secret');
                        setTimeout(() => setCopiedToken(null), 1500);
                      } catch { /* ignore */ }
                    }}
                  >
                    {copiedToken === 'consumer-app-secret' ? 'Copied' : 'Copy'}
                  </button>
                </div>

                <p style={{ margin: '12px 0 0', fontSize: '0.85rem', color: '#cdd6f4' }}>
                  Bob-api stores this same value to verify HMAC signatures, but
                  it will not be retrievable again. If you lose it, revoke the
                  app and create a new one.
                </p>
                <button
                  className="lp-btn-ghost-sm"
                  style={{ marginTop: 12 }}
                  onClick={() => setCreatedConsumerApp(null)}
                >Dismiss</button>
              </div>
            )}

            <table className="admin-table" style={{ marginTop: 16 }}>
              <thead>
                <tr>
                  <th>app_id</th>
                  <th>Name</th>
                  <th>Created</th>
                  <th>Last used</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {consumerApps.length === 0 && (
                  <tr><td colSpan={6} style={{ opacity: 0.6 }}>No consumer apps registered yet.</td></tr>
                )}
                {consumerApps.map((a) => (
                  <tr key={a.id}>
                    <td><code>{a.app_id}</code></td>
                    <td>{a.name || <span style={{ opacity: 0.5 }}>—</span>}</td>
                    <td>{new Date(a.created_at).toLocaleString()}</td>
                    <td>{a.last_used_at ? new Date(a.last_used_at).toLocaleString() : <span style={{ opacity: 0.5 }}>never</span>}</td>
                    <td>
                      {a.revoked_at
                        ? <span style={{ color: '#f88' }}>revoked</span>
                        : <span style={{ color: '#8f8' }}>active</span>}
                    </td>
                    <td>
                      {!a.revoked_at && (
                        <button
                          className="lp-btn-ghost-sm"
                          onClick={() => handleRevokeConsumerApp(a.id)}
                        >Revoke</button>
                      )}
                      <button
                        className="lp-btn-ghost-sm"
                        style={{ marginLeft: 6, color: '#f88' }}
                        onClick={() => handleDeleteConsumerApp(a.id, a.app_id)}
                      >Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {tab === 'labs' && (
          <>
            <div className="admin-toolbar">
              <h2>Labs visibility on /live</h2>
              <button className="lp-btn-primary-sm" onClick={loadLabs}>Refresh</button>
            </div>

            {labsError && <p className="admin-empty" style={{ color: '#dc2626' }}>{labsError}</p>}

            {labs.length === 0 ? (
              <p className="admin-empty">No labs yet.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Owner</th>
                    <th>Editors</th>
                    <th>Viewers</th>
                    <th>Visibility</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {labs.map((l) => (
                    <tr key={l.id}>
                      <td>{l.name}</td>
                      <td>
                        <span className={`admin-status admin-status-${l.status === 'running' ? 'approved' : l.status === 'failed' ? 'rejected' : 'pending'}`}>
                          {l.status || '—'}
                        </span>
                      </td>
                      <td>{l.acl?.owner || '—'}</td>
                      <td title={(l.acl?.editors || []).join(', ')}>{(l.acl?.editors || []).length}</td>
                      <td title={(l.acl?.viewers || []).join(', ')}>{(l.acl?.viewers || []).length}</td>
                      <td>
                        <div className="admin-actions">
                          {l.is_public ? (
                            <>
                              <button
                                type="button"
                                className="admin-btn-approve"
                                disabled={!!labsBusy[l.id]}
                                onClick={() => toggleLabVisibility(l.id, false)}
                              >
                                {labsBusy[l.id] ? '…' : 'Public'}
                              </button>
                              <span className="admin-status admin-status-active">live</span>
                            </>
                          ) : (
                            <button
                              type="button"
                              className="admin-btn-reject"
                              disabled={!!labsBusy[l.id]}
                              onClick={() => toggleLabVisibility(l.id, true)}
                            >
                              {labsBusy[l.id] ? '…' : 'Private'}
                            </button>
                          )}
                        </div>
                      </td>
                      <td>{l.updated_at ? new Date(l.updated_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab === 'logs' && (
          <AdminLogs withAdminJwt={withAdminJwt} />
        )}
      </div>

      {modalRequest && (
        <GenerateTokenModal
          request={modalRequest}
          onClose={() => { setModalRequest(null); loadRequests(); loadTokens(); }}
          onCreated={() => { loadRequests(); loadTokens(); }}
        />
      )}
      {showNewToken && (
        <GenerateTokenModal
          request={null}
          onClose={() => { setShowNewToken(false); loadTokens(); }}
          onCreated={loadTokens}
        />
      )}
    </div>
  );
}

/* ─── Wrapper: login gate + dashboard ──────────────── */
export default function AdminPage() {
  const [jwt, setJwt] = useState(() => sessionStorage.getItem('bob_admin_token'));

  const handleAuth = (token) => {
    sessionStorage.setItem('bob_admin_token', token);
    setJwt(token);
  };

  const handleLogout = () => {
    sessionStorage.removeItem('bob_admin_token');
    setJwt(null);
  };

  if (!jwt) return <AdminLogin onAuth={handleAuth} />;
  return <AdminDashboard jwt={jwt} onLogout={handleLogout} />;
}
