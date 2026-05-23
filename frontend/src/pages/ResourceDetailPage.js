/**
 * Bob Manager — Full-page Resource Detail view.
 * Shows all resource info: themes, links, notes.
 * Linked projects with click-through navigation.
 * Link/unlink projects (like workflows).
 */

import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getResource, getProjects, updateResource, deleteResource, getProjectThemes, linkResourceProject, unlinkResourceProject, renameProjectTheme, setThemeColor, getResources } from '../services/api';
import { IC } from '../components/common/Icons';

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

export default function ResourceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [resource, setResource] = useState(null);
  const [linkedProjects, setLinkedProjects] = useState([]);
  const [allProjects, setAllProjects] = useState([]);
  const [allThemes, setAllThemes] = useState([]);
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState({});
  const [newLink, setNewLink] = useState({ type: 'website', url: '', label: '' });
  const [newNote, setNewNote] = useState({ title: '', content: '' });
  const [themeInput, setThemeInput] = useState('');
  const [showThemeSuggestions, setShowThemeSuggestions] = useState(false);
  const [linkingMode, setLinkingMode] = useState(false);
  const [manageModal, setManageModal] = useState(false);
  const [renameOld, setRenameOld] = useState('');
  const [renameNew, setRenameNew] = useState('');
  const [allResources, setAllResources] = useState([]);
  const themeInputRef = useRef(null);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try {
      const [rRes, pRes, tRes, resAll] = await Promise.all([
        getResource(id), getProjects(), getProjectThemes(), getResources(),
      ]);
      setResource(rRes.data);
      setLinkedProjects(rRes.data.projects || []);
      setAllProjects(pRes.data);
      setAllThemes(tRes.data);
      setAllResources(resAll.data);
    } catch (err) { console.error('Failed to load resource:', err); }
  }

  function getThemeColor(name) {
    const t = allThemes.find((th) => th.name === name);
    return t ? t.color : DEFAULT_THEME_COLOR;
  }

  function getThemesArray(r) {
    return Array.isArray(r.themes) ? r.themes : [];
  }
  function getNotesArray(r) {
    return Array.isArray(r.notes) ? r.notes : [];
  }

  function getUnlinkedProjects() {
    const linkedIds = new Set(linkedProjects.map((p) => p.id));
    return allProjects.filter((p) => !linkedIds.has(p.id));
  }

  /* Theme management (rename, color) */
  async function handleThemeRename() {
    if (!renameOld || !renameNew.trim()) return;
    try {
      const res = await renameProjectTheme(renameOld, renameNew);
      alert(`Renamed "${renameOld}" \u2192 "${renameNew}" across ${res.data.affected_projects} project(s).`);
      setRenameOld(''); setRenameNew('');
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleColorChange(themeName, color) {
    try {
      await setThemeColor(themeName, color);
      setAllThemes((prev) => prev.map((t) => t.name === themeName ? { ...t, color } : t));
    } catch (err) { console.error('Failed to update color:', err); }
  }

  function countUsagesWithTheme(themeName) {
    const projCount = allProjects.filter((p) => (Array.isArray(p.themes) ? p.themes : []).includes(themeName)).length;
    const resCount = allResources.filter((r) => (Array.isArray(r.themes) ? r.themes : []).includes(themeName)).length;
    return { projCount, resCount };
  }

  /* ── Edit support ── */
  function startEdit() {
    if (!resource) return;
    setIsEditing(true);
    setForm({
      name: resource.name,
      description: resource.description || '',
      links: resource.links || [],
      themes: getThemesArray(resource),
      notes: getNotesArray(resource),
    });
    setThemeInput('');
    setNewNote({ title: '', content: '' });
  }

  async function handleUpdate(e) {
    e.preventDefault();
    try {
      await updateResource(id, form);
      setIsEditing(false);
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleDeleteResource() {
    if (!window.confirm('Delete this resource?')) return;
    try { await deleteResource(id); navigate('/resources'); } catch (err) { alert('Failed to delete'); }
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
  function updateNote(index, field, value) {
    const notes = [...form.notes];
    notes[index] = { ...notes[index], [field]: value };
    setForm({ ...form, notes });
  }

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
    return allThemes.filter((t) => t.name.toLowerCase().includes(input) && !form.themes?.includes(t.name));
  }

  /* Project linkage */
  async function handleLinkProject(projectId) {
    try { await linkResourceProject(id, projectId); loadAll(); }
    catch (err) { alert('Failed to link project'); }
  }
  async function handleUnlinkProject(projectId) {
    try { await unlinkResourceProject(id, projectId); loadAll(); }
    catch (err) { alert('Failed to unlink project'); }
  }

  if (!resource) return <div className="card" style={{ padding: '2rem', textAlign: 'center' }}>Loading…</div>;

  const themes = getThemesArray(resource);
  const notes = getNotesArray(resource);
  const allLinks = resource.links || [];
  const unlinkedProjects = getUnlinkedProjects();

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <button className="btn btn-outline" style={{ padding: '0.3rem 0.6rem' }} onClick={() => navigate('/resources')}>← Back</button>
          <h1>{resource.name}</h1>
          {themes.map((t, i) => (
            <ThemePill key={i} name={t} color={getThemeColor(t)} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {!isEditing && <button className="btn btn-outline" onClick={() => setManageModal(true)}><IC.tag size={16} /> Manage Themes</button>}
          {!isEditing && <button className="btn btn-outline" onClick={startEdit}><IC.edit size={16} /> Edit</button>}
          <button className="btn btn-danger" onClick={handleDeleteResource}>Delete</button>
        </div>
      </div>

      {/* Manage Themes modal */}
      {manageModal && (
        <div className="card" style={{ marginBottom: '1rem', borderColor: 'var(--accent)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <h3 style={{ fontSize: '0.9rem', margin: 0 }}><IC.tag size={16} style={{ marginRight: '0.3rem' }} /> Manage Themes</h3>
            <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick={() => setManageModal(false)}><IC.close size={14} /> Close</button>
          </div>
          {allThemes.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem', display: 'block' }}>Theme Colors</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                {allThemes.map((t) => {
                  const usage = countUsagesWithTheme(t.name);
                  return (
                    <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.3rem 0.5rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)' }}>
                      <input type="color" value={t.color || DEFAULT_THEME_COLOR} onChange={(e) => handleColorChange(t.name, e.target.value)}
                        style={{ width: 28, height: 28, border: 'none', background: 'none', cursor: 'pointer', padding: 0 }} />
                      <ThemePill name={t.name} color={t.color} />
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                        {usage.projCount} project(s), {usage.resCount} resource(s)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem', display: 'block' }}>Rename Theme Globally</label>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>This will rename the theme across ALL projects and resources.</p>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div>
                <label>Current Name</label>
                <select value={renameOld} onChange={(e) => setRenameOld(e.target.value)} style={{ width: 180 }}>
                  <option value="">Select theme…</option>
                  {allThemes.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                </select>
              </div>
              <div>
                <label>New Name</label>
                <input value={renameNew} onChange={(e) => setRenameNew(e.target.value)} style={{ width: 180 }} placeholder="New name…" />
              </div>
              {renameOld && renameNew && (() => {
                const usage = countUsagesWithTheme(renameOld);
                return (
                  <span style={{ fontSize: '0.8rem', color: 'var(--warning)', maxWidth: 300 }}>
                    <IC.alertTriangle size={14} style={{ marginRight: '0.3rem' }} /> This will affect {usage.projCount} project(s) and {usage.resCount} resource(s)
                  </span>
                );
              })()}
              <button className="btn btn-primary" onClick={handleThemeRename} disabled={!renameOld || !renameNew.trim()}>Rename</button>
            </div>
          </div>
        </div>
      )}

      {isEditing ? (
        /* ── Edit mode ── */
        <div className="card">
          <form onSubmit={handleUpdate}>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Description</label>
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows="2" />
            </div>

            {/* Themes editor with autocomplete */}
            <div style={{ marginBottom: '0.75rem', position: 'relative' }}>
              <label>Themes</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginBottom: '0.4rem' }}>
                {(form.themes || []).map((t, i) => (
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
                  {showThemeSuggestions && filteredThemeSuggestions().length > 0 && (
                    <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', maxHeight: 150, overflowY: 'auto' }}>
                      {filteredThemeSuggestions().map((t) => (
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

            {/* Editable links */}
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

            {/* Notes editor */}
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Notes</label>
              {(form.notes || []).map((note, i) => (
                <div key={i} style={{ marginBottom: '0.5rem', padding: '0.5rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg-primary)' }}>
                  <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.3rem', alignItems: 'center' }}>
                    <input value={note.title} onChange={(e) => updateNote(i, 'title', e.target.value)} placeholder="Title (optional)" style={{ flex: 1, fontSize: '0.85rem', fontWeight: 600 }} />
                    <button type="button" onClick={() => removeNote(i)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer' }}>✕</button>
                  </div>
                  <textarea value={note.content} onChange={(e) => updateNote(i, 'content', e.target.value)} rows="2" style={{ fontSize: '0.85rem' }} />
                </div>
              ))}
              <div style={{ padding: '0.5rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
                <input value={newNote.title} onChange={(e) => setNewNote({ ...newNote, title: e.target.value })} placeholder="Title (optional)" style={{ marginBottom: '0.3rem', fontSize: '0.85rem' }} />
                <textarea value={newNote.content} onChange={(e) => setNewNote({ ...newNote, content: e.target.value })} placeholder="Note content…" rows="2" style={{ fontSize: '0.85rem' }} />
                <button type="button" className="btn btn-outline" style={{ marginTop: '0.3rem' }} onClick={addNote}>+ Add Note</button>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="submit" className="btn btn-primary">Save</button>
              <button type="button" className="btn btn-outline" onClick={() => setIsEditing(false)}>Cancel</button>
            </div>
          </form>
        </div>
      ) : (
        /* ── Read-only view ── */
        <>
          {/* Description & Links */}
          <div className="card">
            {resource.description && <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>{resource.description}</p>}
            {allLinks.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
                {allLinks.map((link, i) => {
                  const meta = getLinkMeta(link.type);
                  return (
                    <a key={i} href={link.url} target="_blank" rel="noreferrer" style={{
                      display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                      padding: '0.25rem 0.7rem', borderRadius: '9999px', fontSize: '0.85rem',
                      background: 'var(--bg-primary)', border: '1px solid var(--border)',
                      color: 'var(--accent)', textDecoration: 'none', transition: 'border-color 0.15s',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
                    onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
                    >
                      <span>{meta.icon}</span>
                      <span>{link.label || meta.label}</span>
                    </a>
                  );
                })}
              </div>
            )}
            <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              <span>Created: {new Date(resource.created_at).toLocaleDateString()}</span>
              <span>Updated: {new Date(resource.updated_at).toLocaleDateString()}</span>
            </div>
          </div>

          {/* Notes */}
          {notes.length > 0 && (
            <div className="card">
              <h3 style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.5rem' }}><IC.fileText size={14} style={{ marginRight: '0.3rem' }} /> Notes ({notes.length})</h3>
              {notes.map((note, i) => (
                <div key={i} style={{ marginBottom: i < notes.length - 1 ? '0.75rem' : 0, padding: '0.75rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)' }}>
                  {note.title && <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.3rem', color: 'var(--text-primary)' }}>{note.title}</div>}
                  <div style={{ fontSize: '0.85rem', whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{note.content}</div>
                </div>
              ))}
            </div>
          )}

          {/* ── Linked Projects ── */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600 }}>📁 Linked Projects ({linkedProjects.length})</h3>
              <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                onClick={() => setLinkingMode(!linkingMode)}>
                {linkingMode ? 'Done' : '+ Link Project'}
              </button>
            </div>

            {linkedProjects.map((proj) => (
              <div key={proj.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.4rem 0.5rem', marginBottom: '0.25rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
                  onClick={() => navigate(`/projects/${proj.id}`)}>
                  <span style={{ fontSize: '0.9rem' }}>📁</span>
                  <span style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--accent)' }}>{proj.name}</span>
                  {(proj.themes || []).map((t, i) => (
                    <ThemePill key={i} name={t} color={getThemeColor(t)} size="small" />
                  ))}
                </div>
                <button onClick={() => handleUnlinkProject(proj.id)}
                  style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.8rem' }}
                  title="Unlink">✕</button>
              </div>
            ))}

            {linkedProjects.length === 0 && !linkingMode && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No projects linked to this resource</p>
            )}

            {/* Link picker */}
            {linkingMode && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
                {unlinkedProjects.length === 0 ? (
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>All projects are linked.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                    {unlinkedProjects.map((proj) => (
                      <div key={proj.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.25rem 0.4rem', borderRadius: '4px' }}>
                        <span style={{ fontSize: '0.85rem' }}>{proj.name}</span>
                        <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
                          onClick={() => handleLinkProject(proj.id)}>+ Link</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
