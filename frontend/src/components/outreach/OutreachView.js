import React, { useEffect, useState, useCallback } from 'react';
import {
  listOutreachDrafts,
  getOutreachDraft,
  editOutreachDraft,
  sendOutreachDraft,
  rejectOutreachDraft,
} from '../../services/api';

/**
 * Outreach approval queue — surfaces email drafts produced by ANY lab or
 * solo agent (anything that writes output/drafts/*.md with valid YAML
 * frontmatter). Operator can preview, edit, approve+send, or reject.
 */
export default function OutreachView() {
  const [statusFilter, setStatusFilter] = useState('pending');
  const [drafts, setDrafts] = useState([]);
  const [selected, setSelected] = useState(null); // {lab_id, filename, ...full detail}
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({ to: '', subject: '', body: '' });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await listOutreachDrafts(statusFilter);
      setDrafts(data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { refresh(); }, [refresh]);

  const openDraft = async (d) => {
    setSelected({ ...d, body: '', _loading: true });
    setEditing(false);
    try {
      const { data } = await getOutreachDraft(d.lab_id, d.filename);
      setSelected(data);
      setEditForm({ to: data.to || '', subject: data.subject || '', body: data.body || '' });
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
      setSelected(null);
    }
  };

  const handleSend = async () => {
    if (!selected) return;
    if (!window.confirm(`Send this email to ${selected.to}?`)) return;
    setBusy(true);
    try {
      await sendOutreachDraft(selected.lab_id, selected.filename);
      setSelected(null);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const handleReject = async () => {
    if (!selected) return;
    if (!window.confirm('Reject this draft and add the recipient to the suppression list?')) return;
    setBusy(true);
    try {
      await rejectOutreachDraft(selected.lab_id, selected.filename);
      setSelected(null);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const handleSaveEdit = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const { data } = await editOutreachDraft(selected.lab_id, selected.filename, editForm);
      setSelected(data);
      setEditing(false);
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  // Group by lab
  const groups = drafts.reduce((acc, d) => {
    (acc[d.lab_name] ||= []).push(d);
    return acc;
  }, {});

  return (
    <div style={S.wrap}>
      <div style={S.header}>
        <h2 style={{ margin: 0 }}>📨 Outreach approval queue</h2>
        <div style={S.filters}>
          {['pending', 'sent', 'rejected', 'all'].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              style={{ ...S.filterBtn, ...(statusFilter === s ? S.filterBtnActive : {}) }}
            >
              {s}
            </button>
          ))}
          <button onClick={refresh} style={S.filterBtn} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {error && <div style={S.error}>{error}</div>}

      <div style={S.layout}>
        {/* Left list */}
        <div style={S.list}>
          {drafts.length === 0 && !loading && (
            <div style={S.empty}>
              No {statusFilter} drafts. Drafts appear here when a Lab or solo agent writes
              <code> output/drafts/*.md </code>with valid YAML frontmatter (e.g. the Prospecting Lab).
            </div>
          )}
          {Object.entries(groups).map(([labName, items]) => (
            <div key={labName} style={S.group}>
              <div style={S.groupHeader}>
                {labName} <span style={S.count}>{items.length}</span>
              </div>
              {items.map((d) => (
                <div
                  key={d.id}
                  onClick={() => openDraft(d)}
                  style={{
                    ...S.item,
                    ...(selected?.id === d.id ? S.itemActive : {}),
                  }}
                >
                  <div style={S.itemTo}>{d.to || '(no recipient)'}</div>
                  <div style={S.itemSubject}>{d.subject || '(no subject)'}</div>
                  <div style={S.itemMeta}>
                    {d.company || ''} {d.confidence ? `· conf ${d.confidence}/5` : ''}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Right detail */}
        <div style={S.detail}>
          {!selected && <div style={S.empty}>Select a draft to preview, edit, approve or reject.</div>}
          {selected && selected._loading && <div style={S.empty}>Loading…</div>}
          {selected && !selected._loading && (
            <>
              <div style={S.detailHeader}>
                <div style={{ flex: 1 }}>
                  <div style={S.label}>From lab</div>
                  <div style={S.value}>{selected.lab_name}</div>
                </div>
                <div style={{ ...S.statusPill, ...S[`status_${selected.status}`] }}>
                  {selected.status}
                </div>
              </div>

              {!editing ? (
                <div style={S.previewBox}>
                  <div style={S.row}><b>To:</b> {selected.to}</div>
                  <div style={S.row}><b>Subject:</b> {selected.subject}</div>
                  {selected.from_name && <div style={S.row}><b>From:</b> {selected.from_name}</div>}
                  {selected.evidence_url && (
                    <div style={S.row}>
                      <b>Evidence:</b>{' '}
                      <a href={selected.evidence_url} target="_blank" rel="noreferrer">
                        {selected.evidence_url}
                      </a>
                    </div>
                  )}
                  <hr style={S.hr} />
                  <pre style={S.body}>{selected.body}</pre>
                </div>
              ) : (
                <div style={S.previewBox}>
                  <div style={S.row}>
                    <b>To:</b>{' '}
                    <input
                      style={S.input}
                      value={editForm.to}
                      onChange={(e) => setEditForm({ ...editForm, to: e.target.value })}
                    />
                  </div>
                  <div style={S.row}>
                    <b>Subject:</b>{' '}
                    <input
                      style={S.input}
                      value={editForm.subject}
                      onChange={(e) => setEditForm({ ...editForm, subject: e.target.value })}
                    />
                  </div>
                  <hr style={S.hr} />
                  <textarea
                    style={S.textarea}
                    rows={18}
                    value={editForm.body}
                    onChange={(e) => setEditForm({ ...editForm, body: e.target.value })}
                  />
                </div>
              )}

              {selected.status === 'pending' && (
                <div style={S.actions}>
                  {!editing ? (
                    <>
                      <button style={S.btnSecondary} onClick={() => setEditing(true)}>✏️ Edit</button>
                      <button style={S.btnDanger} onClick={handleReject} disabled={busy}>✖ Reject</button>
                      <button style={S.btnPrimary} onClick={handleSend} disabled={busy}>
                        {busy ? 'Sending…' : '✓ Approve & Send'}
                      </button>
                    </>
                  ) : (
                    <>
                      <button style={S.btnSecondary} onClick={() => setEditing(false)}>Cancel</button>
                      <button style={S.btnPrimary} onClick={handleSaveEdit} disabled={busy}>
                        {busy ? 'Saving…' : 'Save changes'}
                      </button>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const S = {
  wrap: { padding: '16px 24px', display: 'flex', flexDirection: 'column', height: '100%', boxSizing: 'border-box' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  filters: { display: 'flex', gap: 6 },
  filterBtn: { background: 'var(--bg-2,#2a2a2a)', color: 'var(--text,#eee)', border: '1px solid var(--border,#444)', padding: '4px 10px', borderRadius: 4, cursor: 'pointer', fontSize: 12 },
  filterBtnActive: { background: 'var(--accent,#0d6efd)', color: '#fff', borderColor: 'var(--accent,#0d6efd)' },
  layout: { display: 'grid', gridTemplateColumns: '340px 1fr', gap: 12, flex: 1, minHeight: 0 },
  list: { overflowY: 'auto', borderRight: '1px solid var(--border,#333)', paddingRight: 8 },
  detail: { overflowY: 'auto', display: 'flex', flexDirection: 'column' },
  group: { marginBottom: 16 },
  groupHeader: { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-dim,#999)', padding: '4px 6px', display: 'flex', justifyContent: 'space-between' },
  count: { background: 'var(--bg-2,#2a2a2a)', borderRadius: 10, padding: '0 8px', fontSize: 11 },
  item: { padding: '8px 10px', borderRadius: 4, cursor: 'pointer', marginBottom: 4, border: '1px solid transparent' },
  itemActive: { background: 'var(--bg-2,#2a2a2a)', borderColor: 'var(--accent,#0d6efd)' },
  itemTo: { fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  itemSubject: { fontSize: 13, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  itemMeta: { fontSize: 11, color: 'var(--text-dim,#999)', marginTop: 2 },
  empty: { color: 'var(--text-dim,#999)', padding: 24, textAlign: 'center', fontSize: 13 },
  detailHeader: { display: 'flex', alignItems: 'center', marginBottom: 12 },
  statusPill: { padding: '4px 10px', borderRadius: 12, fontSize: 11, textTransform: 'uppercase', fontWeight: 600 },
  status_pending: { background: '#a06400', color: '#fff' },
  status_sent: { background: '#1e7d32', color: '#fff' },
  status_rejected: { background: '#7d1e1e', color: '#fff' },
  label: { fontSize: 11, color: 'var(--text-dim,#999)', textTransform: 'uppercase' },
  value: { fontSize: 14 },
  previewBox: { background: 'var(--bg-2,#1e1e1e)', border: '1px solid var(--border,#333)', borderRadius: 6, padding: 16, flex: 1, minHeight: 0, overflow: 'auto' },
  row: { padding: '4px 0', fontSize: 13 },
  hr: { border: 'none', borderTop: '1px solid var(--border,#333)', margin: '12px 0' },
  body: { whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 13, margin: 0 },
  input: { background: 'var(--bg-1,#111)', color: 'var(--text,#eee)', border: '1px solid var(--border,#444)', padding: '4px 8px', borderRadius: 4, width: '70%', fontSize: 13 },
  textarea: { width: '100%', background: 'var(--bg-1,#111)', color: 'var(--text,#eee)', border: '1px solid var(--border,#444)', padding: 8, borderRadius: 4, fontFamily: 'inherit', fontSize: 13, boxSizing: 'border-box' },
  actions: { display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 },
  btnPrimary: { background: 'var(--accent,#0d6efd)', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: 4, cursor: 'pointer', fontWeight: 600 },
  btnSecondary: { background: 'var(--bg-2,#2a2a2a)', color: 'var(--text,#eee)', border: '1px solid var(--border,#444)', padding: '8px 16px', borderRadius: 4, cursor: 'pointer' },
  btnDanger: { background: '#7d1e1e', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: 4, cursor: 'pointer' },
};
