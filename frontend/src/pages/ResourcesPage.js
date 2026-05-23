/**
 * Bob Manager — Resources list page.
 * One-line per resource with link icons. Sorting by name, created, updated, theme.
 * Multi-theme support with autocomplete. Notes as array of {title, content}.
 * Editable links. Similar layout to ProjectsPage.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { getResources, createResource, getProjectThemes } from '../services/api';
import ShareModal from '../components/common/ShareModal';

const DEFAULT_THEME_COLOR = '#a855f7';

function hexToRgba(hex, alpha = 0.15) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function ThemePill({ name, color, size = 'normal', onRemove }) {
  const c = color || DEFAULT_THEME_COLOR;
  const fontSize = size === 'small' ? '0.7rem' : '0.8rem';
  const padding = size === 'small' ? '0.05rem 0.35rem' : '0.15rem 0.5rem';
  return (
    <span style={{ fontSize, padding, borderRadius: '9999px', background: hexToRgba(c), color: c, display: 'inline-flex', alignItems: 'center', gap: '0.3rem', whiteSpace: 'nowrap' }}>
      {name}
      {onRemove && (
        <button type="button" onClick={onRemove} style={{ background: 'none', border: 'none', color: c, cursor: 'pointer', fontSize: '0.7rem', padding: 0, lineHeight: 1 }}>✕</button>
      )}
    </span>
  );
}

const LINK_ICONS = {
  github: '🐙', website: '🌐', discord: '💬', telegram: '✈️',
  x: '𝕏', explorer: '🔍', pool: '🏊', custom: '🔗',
};

const LINK_TYPES = [
  { value: 'github',   label: 'GitHub',   icon: '🐙', placeholder: 'https://github.com/...' },
  { value: 'website',  label: 'Website',  icon: '🌐', placeholder: 'https://...' },
  { value: 'discord',  label: 'Discord',  icon: '💬', placeholder: 'https://discord.gg/...' },
  { value: 'telegram', label: 'Telegram', icon: '✈️', placeholder: 'https://t.me/...' },
  { value: 'x',        label: 'X',        icon: '𝕏',  placeholder: 'https://x.com/...' },
  { value: 'explorer', label: 'Explorer', icon: '🔍', placeholder: 'https://...' },
  { value: 'pool',     label: 'Pool',     icon: '🏊', placeholder: 'https://...' },
  { value: 'custom',   label: 'Custom',   icon: '🔗', placeholder: 'https://...' },
];

function getLinkMeta(type) {
  return LINK_TYPES.find((t) => t.value === type) || LINK_TYPES[LINK_TYPES.length - 1];
}

export default function ResourcesPage() {
  const navigate = useNavigate();
  const [resources, setResources] = useState([]);
  const [shareTarget, setShareTarget] = useState(null);
  const [allThemes, setAllThemes] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [sortBy, setSortBy] = useState('name');
  const [sortDir, setSortDir] = useState('asc');
  const [form, setForm] = useState({ name: '', description: '', links: [], themes: [], notes: [] });
  const [newLink, setNewLink] = useState({ type: 'website', url: '', label: '' });
  const [newNote, setNewNote] = useState({ title: '', content: '' });
  const [themeInput, setThemeInput] = useState('');
  const [showThemeSuggestions, setShowThemeSuggestions] = useState(false);
  const themeInputRef = useRef(null);

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    try {
      const [rRes, tRes] = await Promise.all([getResources(), getProjectThemes()]);
      setResources(rRes.data);
      setAllThemes(tRes.data);
    } catch (err) { console.error('Failed to load:', err); }
  }

  function getThemeColor(name) {
    const t = allThemes.find((th) => th.name === name);
    return t ? t.color : DEFAULT_THEME_COLOR;
  }

  function getThemesArray(r) {
    if (Array.isArray(r.themes)) return r.themes;
    return [];
  }

  function sortedResources() {
    const sorted = [...resources].sort((a, b) => {
      let cmp = 0;
      if (sortBy === 'name') cmp = (a.name || '').localeCompare(b.name || '');
      else if (sortBy === 'theme') cmp = (getThemesArray(a).join(',') || '').localeCompare(getThemesArray(b).join(',') || '');
      else if (sortBy === 'created') cmp = new Date(a.created_at) - new Date(b.created_at);
      else if (sortBy === 'updated') cmp = new Date(a.updated_at) - new Date(b.updated_at);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }

  function toggleSort(field) {
    if (sortBy === field) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortBy(field); setSortDir('asc'); }
  }

  function sortIcon(field) {
    if (sortBy !== field) return '⇅';
    return sortDir === 'asc' ? '↑' : '↓';
  }

  async function handleCreate(e) {
    e.preventDefault();
    try {
      await createResource(form);
      setForm({ name: '', description: '', links: [], themes: [], notes: [] });
      setShowCreate(false);
      loadData();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  /* Link management */
  function addLink() {
    if (!newLink.url.trim()) return;
    const link = { type: newLink.type, url: newLink.url.trim() };
    if (newLink.type === 'custom' && newLink.label.trim()) link.label = newLink.label.trim();
    setForm({ ...form, links: [...form.links, link] });
    setNewLink({ type: 'website', url: '', label: '' });
  }
  function removeLink(index) { setForm({ ...form, links: form.links.filter((_, i) => i !== index) }); }
  function updateLink(index, field, value) {
    const links = [...form.links];
    links[index] = { ...links[index], [field]: value };
    setForm({ ...form, links });
  }

  /* Notes management */
  function addNote() {
    if (!newNote.content.trim()) return;
    setForm({ ...form, notes: [...form.notes, { title: newNote.title.trim(), content: newNote.content.trim() }] });
    setNewNote({ title: '', content: '' });
  }
  function removeNote(index) { setForm({ ...form, notes: form.notes.filter((_, i) => i !== index) }); }

  /* Theme management */
  function addTheme(themeName) {
    const name = themeName.trim();
    if (!name || form.themes.includes(name)) return;
    setForm({ ...form, themes: [...form.themes, name] });
    setThemeInput('');
    setShowThemeSuggestions(false);
  }
  function removeTheme(index) { setForm({ ...form, themes: form.themes.filter((_, i) => i !== index) }); }

  function filteredThemeSuggestions() {
    const input = themeInput.toLowerCase();
    return allThemes.filter((t) => t.name.toLowerCase().includes(input) && !form.themes.includes(t.name));
  }

  /* Render links editor */
  function renderLinksEditor() {
    return (
      <div style={{ marginBottom: '0.75rem' }}>
        <label>Links</label>
        {form.links.map((link, i) => {
          const meta = getLinkMeta(link.type);
          return (
            <div key={i} style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.3rem', alignItems: 'center' }}>
              <select value={link.type} onChange={(e) => updateLink(i, 'type', e.target.value)} style={{ width: 110, fontSize: '0.8rem', padding: '0.25rem' }}>
                {LINK_TYPES.map((t) => <option key={t.value} value={t.value}>{t.icon} {t.label}</option>)}
              </select>
              {link.type === 'custom' && (
                <input value={link.label || ''} onChange={(e) => updateLink(i, 'label', e.target.value)} placeholder="Tag" style={{ width: 80, fontSize: '0.8rem' }} />
              )}
              <input value={link.url} onChange={(e) => updateLink(i, 'url', e.target.value)} placeholder={meta.placeholder} style={{ flex: 1, fontSize: '0.8rem' }} />
              <button type="button" onClick={() => removeLink(i)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer' }}>✕</button>
            </div>
          );
        })}
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.4rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <select value={newLink.type} onChange={(e) => setNewLink({ ...newLink, type: e.target.value })} style={{ width: 120 }}>
            {LINK_TYPES.map((t) => <option key={t.value} value={t.value}>{t.icon} {t.label}</option>)}
          </select>
          {newLink.type === 'custom' && <input placeholder="Tag name" value={newLink.label} onChange={(e) => setNewLink({ ...newLink, label: e.target.value })} style={{ width: 100 }} />}
          <input placeholder={getLinkMeta(newLink.type).placeholder} value={newLink.url} onChange={(e) => setNewLink({ ...newLink, url: e.target.value })} style={{ flex: 1, minWidth: 180 }} />
          <button type="button" className="btn btn-outline" onClick={addLink}>+ Add</button>
        </div>
      </div>
    );
  }

  /* Render themes editor with autocomplete */
  function renderThemesEditor() {
    const suggestions = filteredThemeSuggestions();
    return (
      <div style={{ marginBottom: '0.75rem', position: 'relative' }}>
        <label>Themes</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginBottom: '0.4rem' }}>
          {form.themes.map((t, i) => (
            <ThemePill key={i} name={t} color={getThemeColor(t)} onRemove={() => removeTheme(i)} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <input
              ref={themeInputRef}
              value={themeInput}
              onChange={(e) => { setThemeInput(e.target.value); setShowThemeSuggestions(true); }}
              onFocus={() => setShowThemeSuggestions(true)}
              onBlur={() => setTimeout(() => setShowThemeSuggestions(false), 150)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTheme(themeInput); } }}
              placeholder="Type to search or add…"
            />
            {showThemeSuggestions && suggestions.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', maxHeight: 150, overflowY: 'auto' }}>
                {suggestions.map((t) => (
                  <div key={t.name} onMouseDown={() => addTheme(t.name)} style={{ padding: '0.35rem 0.75rem', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', background: t.color || DEFAULT_THEME_COLOR, flexShrink: 0 }} />
                    {t.name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button type="button" className="btn btn-outline" onClick={() => addTheme(themeInput)}>+ Add</button>
        </div>
      </div>
    );
  }

  /* Notes editor */
  function renderNotesEditor() {
    return (
      <div style={{ marginBottom: '0.75rem' }}>
        <label>Notes</label>
        {form.notes.map((note, i) => (
          <div key={i} style={{ marginBottom: '0.5rem', padding: '0.5rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg-primary)' }}>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.3rem', alignItems: 'center' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, flex: 1 }}>{note.title || 'Untitled'}</span>
              <button type="button" onClick={() => removeNote(i)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer' }}>✕</button>
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{note.content}</div>
          </div>
        ))}
        <div style={{ padding: '0.5rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
          <input value={newNote.title} onChange={(e) => setNewNote({ ...newNote, title: e.target.value })} placeholder="Title (optional)" style={{ marginBottom: '0.3rem', fontSize: '0.85rem' }} />
          <textarea value={newNote.content} onChange={(e) => setNewNote({ ...newNote, content: e.target.value })} placeholder="Note content…" rows="2" style={{ fontSize: '0.85rem' }} />
          <button type="button" className="btn btn-outline" style={{ marginTop: '0.3rem' }} onClick={addNote}>+ Add Note</button>
        </div>
      </div>
    );
  }

  const thStyle = { cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' };

  return (
    <div>
      <div className="page-header">
        <h1>Resources</h1>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? 'Cancel' : '+ New Resource'}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <form onSubmit={handleCreate}>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Description</label>
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows="2" />
            </div>
            {renderThemesEditor()}
            {renderLinksEditor()}
            {renderNotesEditor()}
            <button type="submit" className="btn btn-primary">Create Resource</button>
          </form>
        </div>
      )}

      {/* Compact resource table */}
      {resources.length > 0 ? (
        <div className="card" style={{ padding: '0' }}>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th style={thStyle} onClick={() => toggleSort('name')}>Name {sortIcon('name')}</th>
                  <th style={thStyle} onClick={() => toggleSort('theme')}>Themes {sortIcon('theme')}</th>
                  <th>Links</th>
                  <th>Description</th>
                  <th style={thStyle} onClick={() => toggleSort('created')}>Created {sortIcon('created')}</th>
                  <th style={thStyle} onClick={() => toggleSort('updated')}>Updated {sortIcon('updated')}</th>
                  <th style={{ width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {sortedResources().map((res) => {
                  const themes = getThemesArray(res);
                  const links = res.links || [];
                  return (
                    <tr key={res.id} onClick={() => navigate(`/resources/${res.id}`)} style={{ cursor: 'pointer' }}>
                      <td style={{ fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{res.name}</td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.2rem', flexWrap: 'wrap' }}>
                          {themes.map((t, i) => (
                            <ThemePill key={i} name={t} color={getThemeColor(t)} size="small" />
                          ))}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          {links.map((link, i) => (
                            <span key={i} title={`${(LINK_ICONS[link.type] ? link.type : 'custom')}: ${link.url}`}
                              style={{ fontSize: '0.85rem', cursor: 'default' }}
                              onClick={(e) => { e.stopPropagation(); window.open(link.url, '_blank'); }}>
                              {LINK_ICONS[link.type] || '🔗'}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {res.description || '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{new Date(res.created_at).toLocaleDateString()}</td>
                      <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{new Date(res.updated_at).toLocaleDateString()}</td>
                      <td>
                        <button title="Share" onClick={(e) => { e.stopPropagation(); setShareTarget(res); }}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.9rem', opacity: 0.5, padding: '2px 6px' }}>👥</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : !showCreate && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>No resources yet. Click "+ New Resource" to get started.</p>
        </div>
      )}
      {shareTarget && (
        <ShareModal
          resourceType="resource"
          resourceId={shareTarget.id}
          acl={shareTarget.acl}
          onClose={() => setShareTarget(null)}
          onUpdated={() => loadData()}
        />
      )}
    </div>
  );
}
