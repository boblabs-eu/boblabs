/**
 * Bob Manager — Projects list page (compact).
 * One-line per project with small link icons. Sorting by name, created, updated, theme.
 * Multi-theme support with autocomplete. Notes as array of {title, content}.
 * Theme rename across all projects. Editable links.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { getProjects, createProject, getProjectThemes, renameProjectTheme, setThemeColor } from '../services/api';
import ShareModal from '../components/common/ShareModal';
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

export default function ProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [shareTarget, setShareTarget] = useState(null);
  const [allThemes, setAllThemes] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [sortBy, setSortBy] = useState('name');
  const [sortDir, setSortDir] = useState('asc');
  const [form, setForm] = useState({ name: '', description: '', github_url: '', links: [], themes: [], notes: [], useful_commands: [] });
  const [newLink, setNewLink] = useState({ type: 'github', url: '', label: '' });
  const [newCmd, setNewCmd] = useState({ label: '', command: '' });
  const [newNote, setNewNote] = useState({ title: '', content: '' });
  const [themeInput, setThemeInput] = useState('');
  const [showThemeSuggestions, setShowThemeSuggestions] = useState(false);
  const [manageModal, setManageModal] = useState(false);
  const [renameOld, setRenameOld] = useState('');
  const [renameNew, setRenameNew] = useState('');
  const themeInputRef = useRef(null);

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    try {
      const [pRes, tRes] = await Promise.all([getProjects(), getProjectThemes()]);
      setProjects(pRes.data);
      setAllThemes(tRes.data);
    } catch (err) { console.error('Failed to load:', err); }
  }

  function getAllLinks(proj) {
    const links = [...(proj.links || [])];
    if (proj.github_url && !links.some((l) => l.url === proj.github_url)) {
      links.unshift({ type: 'github', url: proj.github_url, label: '' });
    }
    return links;
  }

  /* Migrate legacy string notes to array */
  function getNotesArray(proj) {
    if (Array.isArray(proj.notes)) return proj.notes;
    if (typeof proj.notes === 'string' && proj.notes.trim()) return [{ title: '', content: proj.notes }];
    return [];
  }

  /* Migrate legacy string theme to array */
  function getThemesArray(proj) {
    if (Array.isArray(proj.themes)) return proj.themes;
    if (typeof proj.themes === 'string' && proj.themes.trim()) return [proj.themes];
    // Legacy single theme field
    if (typeof proj.theme === 'string' && proj.theme.trim()) return [proj.theme];
    return [];
  }

  function sortedProjects() {
    const sorted = [...projects].sort((a, b) => {
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
      await createProject(form);
      setForm({ name: '', description: '', github_url: '', links: [], themes: [], notes: [], useful_commands: [] });
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
    setNewLink({ type: 'github', url: '', label: '' });
  }
  function removeLink(index) { setForm({ ...form, links: form.links.filter((_, i) => i !== index) }); }
  function updateLink(index, field, value) {
    const links = [...form.links];
    links[index] = { ...links[index], [field]: value };
    setForm({ ...form, links });
  }

  /* Command management */
  function addCommand() {
    if (newCmd.label && newCmd.command) {
      setForm({ ...form, useful_commands: [...form.useful_commands, { ...newCmd }] });
      setNewCmd({ label: '', command: '' });
    }
  }
  function removeCommand(index) { setForm({ ...form, useful_commands: form.useful_commands.filter((_, i) => i !== index) }); }

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

  /* Build a color map from allThemes [{name,color}] */
  function getThemeColor(name) {
    const t = allThemes.find((th) => th.name === name);
    return t ? t.color : DEFAULT_THEME_COLOR;
  }

  function filteredThemeSuggestions() {
    const input = themeInput.toLowerCase();
    return allThemes.filter((t) => t.name.toLowerCase().includes(input) && !form.themes.includes(t.name));
  }

  /* Theme rename */
  async function handleThemeRename() {
    if (!renameOld || !renameNew.trim()) return;
    try {
      const res = await renameProjectTheme(renameOld, renameNew);
      alert(`Renamed "${renameOld}" → "${renameNew}" across ${res.data.affected_projects} project(s).`);
      setRenameOld(''); setRenameNew('');
      loadData();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleColorChange(themeName, color) {
    try {
      await setThemeColor(themeName, color);
      setAllThemes((prev) => prev.map((t) => t.name === themeName ? { ...t, color } : t));
    } catch (err) { console.error('Failed to update color:', err); }
  }

  /* Render the shared create/edit links editor */
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
    );
  }

  const thStyle = { cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' };

  return (
    <div>
      <div className="page-header">
        <h1>Projects</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-outline" onClick={() => setManageModal(true)}><IC.tag size={16} /> Manage Themes</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? 'Cancel' : '+ New Project'}
          </button>
        </div>
      </div>

      {/* Manage Themes modal */}
      {manageModal && (
        <div className="card" style={{ marginBottom: '1rem', borderColor: 'var(--accent)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <h3 style={{ fontSize: '0.9rem', margin: 0 }}><IC.tag size={16} style={{ marginRight: '0.3rem' }} /> Manage Themes</h3>
            <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick={() => setManageModal(false)}><IC.close size={14} /> Close</button>
          </div>

          {/* Color picker per theme */}
          {allThemes.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem', display: 'block' }}>Theme Colors</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                {allThemes.map((t) => (
                  <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.3rem 0.5rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)' }}>
                    <input type="color" value={t.color || DEFAULT_THEME_COLOR} onChange={(e) => handleColorChange(t.name, e.target.value)}
                      style={{ width: 28, height: 28, border: 'none', background: 'none', cursor: 'pointer', padding: 0 }} />
                    <ThemePill name={t.name} color={t.color} />
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                      {projects.filter((p) => getThemesArray(p).includes(t.name)).length} project(s)
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Rename section */}
          <div>
            <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem', display: 'block' }}>Rename Theme Globally</label>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
              This will rename the theme across ALL projects that have it.
            </p>
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
              {renameOld && renameNew && (
                <span style={{ fontSize: '0.8rem', color: 'var(--warning)', maxWidth: 300 }}>
                  <IC.alertTriangle size={14} style={{ marginRight: '0.3rem' }} /> All projects with "{renameOld}" will be changed to "{renameNew}"
                  ({projects.filter((p) => getThemesArray(p).includes(renameOld)).length} project(s))
                </span>
              )}
              <button className="btn btn-primary" onClick={handleThemeRename} disabled={!renameOld || !renameNew.trim()}>Rename</button>
            </div>
          </div>
        </div>
      )}

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
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Useful Commands</label>
              {form.useful_commands.map((cmd, i) => (
                <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.25rem', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, minWidth: 80 }}>{cmd.label}:</span>
                  <code style={{ fontSize: '0.8rem', flex: 1, color: 'var(--text-secondary)' }}>{cmd.command}</code>
                  <button type="button" onClick={() => removeCommand(i)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer' }}>✕</button>
                </div>
              ))}
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                <input placeholder="Label" value={newCmd.label} onChange={(e) => setNewCmd({ ...newCmd, label: e.target.value })} style={{ width: 150 }} />
                <input placeholder="Command" value={newCmd.command} onChange={(e) => setNewCmd({ ...newCmd, command: e.target.value })} style={{ flex: 1 }} />
                <button type="button" className="btn btn-outline" onClick={addCommand}>+</button>
              </div>
            </div>
            <button type="submit" className="btn btn-primary">Create Project</button>
          </form>
        </div>
      )}

      {/* Compact project table */}
      {projects.length > 0 ? (
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
                {sortedProjects().map((proj) => {
                  const allLinks = getAllLinks(proj);
                  const themes = getThemesArray(proj);
                  return (
                    <tr key={proj.id} onClick={() => navigate(`/projects/${proj.id}`)} style={{ cursor: 'pointer' }}>
                      <td style={{ fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{proj.name}</td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.2rem', flexWrap: 'wrap' }}>
                          {themes.map((t, i) => (
                            <ThemePill key={i} name={t} color={getThemeColor(t)} size="small" />
                          ))}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          {allLinks.map((link, i) => (
                            <span key={i} title={`${(LINK_ICONS[link.type] ? link.type : 'custom')}: ${link.url}`}
                              style={{ fontSize: '0.85rem', cursor: 'default' }}
                              onClick={(e) => { e.stopPropagation(); window.open(link.url, '_blank'); }}>
                              {LINK_ICONS[link.type] || '🔗'}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {proj.description || '—'}
                      </td>
                      <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{new Date(proj.created_at).toLocaleDateString()}</td>
                      <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{new Date(proj.updated_at).toLocaleDateString()}</td>
                      <td>
                        <button title="Share" onClick={(e) => { e.stopPropagation(); setShareTarget(proj); }}
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
          <p style={{ color: 'var(--text-muted)' }}>No projects yet. Click "New Project" to get started.</p>
        </div>
      )}
      {shareTarget && (
        <ShareModal
          resourceType="project"
          resourceId={shareTarget.id}
          acl={shareTarget.acl}
          onClose={() => setShareTarget(null)}
          onUpdated={() => loadData()}
        />
      )}
    </div>
  );
}
