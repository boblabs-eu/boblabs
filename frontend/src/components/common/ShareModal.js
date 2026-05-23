/**
 * Bob Manager — ShareModal component.
 * Allows owners/admins to manage ACL (editors, viewers) on a resource.
 */

import React, { useState } from 'react';
import { updateResourceAcl } from '../../services/api';

export default function ShareModal({ resourceType, resourceId, acl, isPublic, onClose, onUpdated }) {
  const [editors, setEditors] = useState((acl?.editors || []).join(', '));
  const [viewers, setViewers] = useState((acl?.viewers || []).join(', '));
  const [owner, setOwner] = useState(acl?.owner || '');
  const [publicOnLive, setPublicOnLive] = useState(!!isPublic);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // The Public-on-/live toggle only applies to resource types that carry the
  // is_public column. Today: labs. The backend silently ignores the field on
  // others, but we hide the UI to avoid confusing the operator.
  const supportsPublic = resourceType === 'lab';

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const newAcl = {
        owner: owner.trim(),
        editors: editors.split(',').map(e => e.trim()).filter(Boolean),
        viewers: viewers.split(',').map(e => e.trim()).filter(Boolean),
      };
      const nextIsPublic = supportsPublic ? publicOnLive : undefined;
      await updateResourceAcl(resourceType, resourceId, newAcl, nextIsPublic);
      onUpdated?.(newAcl, nextIsPublic);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update permissions');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="share-modal-overlay" onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg-secondary, #1e1e2e)', borderRadius: 12, padding: '1.5rem', width: 440,
        boxShadow: '0 10px 40px rgba(0,0,0,0.4)', color: 'var(--text-primary, #e2e8f0)',
      }}>
        <h3 style={{ margin: '0 0 1rem', fontSize: '1.1rem', fontWeight: 600 }}>
          Share — Manage Access
        </h3>

        <label style={labelStyle}>Owner (email)</label>
        <input
          style={inputStyle}
          value={owner}
          onChange={e => setOwner(e.target.value)}
          placeholder="owner@example.com"
        />

        <label style={labelStyle}>Editors (comma-separated emails)</label>
        <input
          style={inputStyle}
          value={editors}
          onChange={e => setEditors(e.target.value)}
          placeholder="editor1@example.com, editor2@example.com"
        />

        <label style={labelStyle}>Viewers (comma-separated emails)</label>
        <input
          style={inputStyle}
          value={viewers}
          onChange={e => setViewers(e.target.value)}
          placeholder="viewer@example.com"
        />

        {supportsPublic && (
          <div
            onClick={() => setPublicOnLive((v) => !v)}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.6rem',
              marginTop: '1rem', padding: '0.65rem 0.75rem',
              borderRadius: 8, border: '1px solid var(--border, #334155)',
              background: 'var(--bg-primary, #0f172a)', cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              id="share-modal-is-public"
              type="checkbox"
              checked={publicOnLive}
              onChange={(e) => setPublicOnLive(e.target.checked)}
              onClick={(e) => e.stopPropagation()}
              style={{ flexShrink: 0, width: 16, height: 16, cursor: 'pointer' }}
            />
            <span style={{
              fontSize: '0.88rem',
              fontWeight: 500,
              color: 'var(--text-primary, #e2e8f0)',
              textTransform: 'none',
              letterSpacing: 0,
              lineHeight: 1.3,
            }}>
              Public on <code style={{ fontFamily: 'ui-monospace, monospace', background: 'rgba(124,58,237,0.12)', padding: '0 0.25rem', borderRadius: 3 }}>/live</code>
              <span style={{ color: 'var(--text-muted, #94a3b8)', fontWeight: 400, marginLeft: '0.4rem' }}>
                · surface anonymously (default: private)
              </span>
            </span>
          </div>
        )}

        {error && <p style={{ color: '#ef4444', fontSize: '0.85rem', margin: '0.5rem 0' }}>{error}</p>}

        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
          <button onClick={onClose} style={btnSecondary}>Cancel</button>
          <button onClick={handleSave} disabled={saving} style={btnPrimary}>
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

const labelStyle = { display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted, #94a3b8)', margin: '0.75rem 0 0.25rem' };
const inputStyle = { width: '100%', padding: '0.5rem', borderRadius: 6, border: '1px solid var(--border, #334155)', background: 'var(--bg-primary, #0f172a)', color: 'var(--text-primary, #e2e8f0)', fontSize: '0.9rem', boxSizing: 'border-box' };
const btnPrimary = { padding: '0.5rem 1rem', borderRadius: 6, border: 'none', background: 'var(--accent, #7c3aed)', color: '#fff', fontWeight: 600, cursor: 'pointer' };
const btnSecondary = { padding: '0.5rem 1rem', borderRadius: 6, border: '1px solid var(--border, #334155)', background: 'transparent', color: 'var(--text-primary, #e2e8f0)', fontWeight: 600, cursor: 'pointer' };
