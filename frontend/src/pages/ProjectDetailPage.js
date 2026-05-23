/**
 * Bob Manager — Full-page Project Detail view.
 * Shows all project info, linked workflows with execute capability.
 * Multi-theme with autocomplete, notes as array of {title,content},
 * editable links, theme rename dialog.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getProject, getProjects, getWorkflows, getServers, updateProject, deleteProject, updateWorkflow, executeWorkflow, getProjectThemes, renameProjectTheme, setThemeColor, getModules, createModule, updateModule, deleteModule, createStep, updateStep, deleteStep, createTask, updateTask, deleteTask, getProjectResources, getResources, linkResourceProject, unlinkResourceProject } from '../services/api';
import StatusBadge from '../components/common/StatusBadge';
import { IC } from '../components/common/Icons';
import wsService from '../services/websocket';

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

const TASK_STATUS_OPTIONS = [
  { value: 'not-started', label: 'Not Started', icon: '⚪' },
  { value: 'in-progress', label: 'In Progress', icon: '🟡' },
  { value: 'done', label: 'Done', icon: '🟢' },
  { value: 'blocked', label: 'Blocked', icon: '🔴' },
];

function getLinkMeta(type) {
  return LINK_TYPES.find((t) => t.value === type) || LINK_TYPES[LINK_TYPES.length - 1];
}

/* Normalize legacy data */
function getNotesArray(proj) {
  if (Array.isArray(proj.notes)) return proj.notes;
  if (typeof proj.notes === 'string' && proj.notes.trim()) return [{ title: '', content: proj.notes }];
  return [];
}
function getThemesArray(proj) {
  if (Array.isArray(proj.themes)) return proj.themes;
  if (typeof proj.themes === 'string' && proj.themes.trim()) return [proj.themes];
  if (typeof proj.theme === 'string' && proj.theme.trim()) return [proj.theme];
  return [];
}

export default function ProjectDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [allProjects, setAllProjects] = useState([]);
  const [allThemes, setAllThemes] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [servers, setServers] = useState([]);
  const [selectedServers, setSelectedServers] = useState([]);
  const [executingSet, setExecutingSet] = useState(new Set());
  const [executionOutputs, setExecutionOutputs] = useState({});
  const [expandedOutputs, setExpandedOutputs] = useState({});
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState({});
  const [newLink, setNewLink] = useState({ type: 'github', url: '', label: '' });
  const [newCmd, setNewCmd] = useState({ label: '', command: '' });
  const [newNote, setNewNote] = useState({ title: '', content: '' });
  const [themeInput, setThemeInput] = useState('');
  const [showThemeSuggestions, setShowThemeSuggestions] = useState(false);
  const [linkingMode, setLinkingMode] = useState(false);
  const [manageModal, setManageModal] = useState(false);
  const [renameOld, setRenameOld] = useState('');
  const [renameNew, setRenameNew] = useState('');
  const themeInputRef = useRef(null);

  /* Resource linkage state */
  const [linkedResources, setLinkedResources] = useState([]);
  const [allResources, setAllResources] = useState([]);
  const [resourceLinkingMode, setResourceLinkingMode] = useState(false);

  /* Module state */
  const [modules, setModules] = useState([]);
  const [expandedModuleId, setExpandedModuleId] = useState(null);
  const [newModuleName, setNewModuleName] = useState('');
  const [newModuleDesc, setNewModuleDesc] = useState('');
  const [editingModuleId, setEditingModuleId] = useState(null);
  const [editModule, setEditModule] = useState({ name: '', description: '' });
  const [newStepForm, setNewStepForm] = useState({});
  const [newTaskForm, setNewTaskForm] = useState({});
  const [editingStepId, setEditingStepId] = useState(null);
  const [editStep, setEditStep] = useState({});
  const [editingTaskId, setEditingTaskId] = useState(null);
  const [editTask, setEditTask] = useState({});

  useEffect(() => {
    loadAll();

    const unsubStepStart = wsService.on('workflow.step.start', (data) => {
      addExecOutput(data.workflow_id, data.server_name || data.server_id, 'info',
        `▶ Step ${data.step_order}: ${data.step_name || 'running'}…`);
    });
    const unsubStepComplete = wsService.on('workflow.step.complete', (data) => {
      const status = data.exit_code === 0 ? '✅' : '❌';
      addExecOutput(data.workflow_id, data.server_name || data.server_id, data.exit_code === 0 ? 'stdout' : 'stderr',
        `${status} Step ${data.step_order}: exit ${data.exit_code}`);
      if (data.stdout) data.stdout.split('\n').filter(Boolean).forEach((line) => addExecOutput(data.workflow_id, data.server_name || data.server_id, 'stdout', line));
      if (data.stderr) data.stderr.split('\n').filter(Boolean).forEach((line) => addExecOutput(data.workflow_id, data.server_name || data.server_id, 'stderr', line));
    });
    const unsubExecComplete = wsService.on('workflow.execution.complete', (data) => {
      addExecOutput(data.workflow_id, data.server_name || data.server_id, 'info', `── Execution ${data.status} ──`);
      setExecutingSet((prev) => { const next = new Set(prev); next.delete(data.workflow_id); return next; });
    });
    return () => { unsubStepStart(); unsubStepComplete(); unsubExecComplete(); };
  }, []);

  function addExecOutput(workflowId, server, stream, line) {
    setExecutionOutputs((prev) => ({
      ...prev,
      [workflowId]: [...(prev[workflowId] || []), { server, stream, line, ts: Date.now() }],
    }));
  }

  async function loadAll() {
    try {
      const [pRes, wfRes, srvRes, tRes, allPRes, modRes, resLinked, resAll] = await Promise.all([
        getProject(id), getWorkflows(), getServers(), getProjectThemes(), getProjects(), getModules(id), getProjectResources(id), getResources(),
      ]);
      setProject(pRes.data);
      setWorkflows(wfRes.data);
      setServers(srvRes.data);
      setAllThemes(tRes.data);
      setAllProjects(allPRes.data);
      setModules(modRes.data);
      setLinkedResources(resLinked.data);
      setAllResources(resAll.data);
    } catch (err) {
      console.error('Failed to load project:', err);
    }
  }

  function getAllLinks(proj) {
    const links = [...(proj.links || [])];
    if (proj.github_url && !links.some((l) => l.url === proj.github_url)) {
      links.unshift({ type: 'github', url: proj.github_url, label: '' });
    }
    return links;
  }

  function getProjectWorkflows() {
    return workflows.filter((wf) => wf.project_id === id);
  }

  function getUnlinkedWorkflows() {
    return workflows.filter((wf) => !wf.project_id);
  }

  function toggleServer(sid) {
    setSelectedServers((prev) => prev.includes(sid) ? prev.filter((s) => s !== sid) : [...prev, sid]);
  }

  async function handleExecute(workflowId) {
    if (selectedServers.length === 0) { alert('Select at least one server'); return; }
    try {
      setExecutingSet((prev) => new Set(prev).add(workflowId));
      setExecutionOutputs((prev) => ({ ...prev, [workflowId]: [] }));
      setExpandedOutputs((prev) => ({ ...prev, [workflowId]: true }));
      const res = await executeWorkflow(workflowId, selectedServers);
      (res.data || []).forEach((exec) => {
        if (exec.status) addExecOutput(workflowId, exec.server_id || '?', 'info', `Execution status: ${exec.status}`);
        (exec.logs || []).forEach((log) => {
          if (log.stdout) log.stdout.split('\n').filter(Boolean).forEach((line) => addExecOutput(workflowId, exec.server_id || '?', 'stdout', line));
          if (log.stderr) log.stderr.split('\n').filter(Boolean).forEach((line) => addExecOutput(workflowId, exec.server_id || '?', 'stderr', line));
        });
      });
    } catch (err) {
      addExecOutput(workflowId, '-', 'stderr', `Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setExecutingSet((prev) => { const next = new Set(prev); next.delete(workflowId); return next; });
    }
  }

  function toggleOutput(wfId) {
    setExpandedOutputs((prev) => ({ ...prev, [wfId]: !prev[wfId] }));
  }

  async function linkWorkflow(workflowId) {
    try { await updateWorkflow(workflowId, { project_id: id }); loadAll(); } catch (err) { alert('Failed to link workflow'); }
  }

  async function unlinkWorkflow(workflowId) {
    try { await updateWorkflow(workflowId, { project_id: null }); loadAll(); } catch (err) { alert('Failed to unlink workflow'); }
  }

  /* ── Edit support ── */
  function startEdit() {
    if (!project) return;
    setIsEditing(true);
    setForm({
      name: project.name,
      description: project.description || '',
      github_url: project.github_url || '',
      links: getAllLinks(project),
      themes: getThemesArray(project),
      notes: getNotesArray(project),
      useful_commands: project.useful_commands || [],
    });
    setThemeInput('');
    setNewNote({ title: '', content: '' });
  }

  async function handleUpdate(e) {
    e.preventDefault();
    try {
      await updateProject(id, form);
      setIsEditing(false);
      loadAll();
    } catch (err) {
      alert('Failed: ' + (err.response?.data?.detail || err.message));
    }
  }

  async function handleDeleteProject() {
    if (!window.confirm('Delete this project?')) return;
    try { await deleteProject(id); navigate('/projects'); } catch (err) { alert('Failed to delete'); }
  }

  /* Link management — editable inline */
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

  function filteredThemeSuggestions() {
    const input = themeInput.toLowerCase();
    return allThemes.filter((t) => t.name.toLowerCase().includes(input) && !form.themes?.includes(t.name));
  }

  function getThemeColor(name) {
    const t = allThemes.find((th) => th.name === name);
    return t ? t.color : DEFAULT_THEME_COLOR;
  }

  /* Theme rename */
  async function handleThemeRename() {
    if (!renameOld || !renameNew.trim()) return;
    try {
      const res = await renameProjectTheme(renameOld, renameNew);
      alert(`Renamed "${renameOld}" → "${renameNew}" across ${res.data.affected_projects} project(s).`);
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

  function countProjectsWithTheme(themeName) {
    return allProjects.filter((p) => getThemesArray(p).includes(themeName)).length;
  }

  /* ── Module CRUD ── */
  async function handleCreateModule() {
    if (!newModuleName.trim()) return;
    try {
      await createModule(id, { name: newModuleName.trim(), description: newModuleDesc.trim(), position: modules.length });
      setNewModuleName(''); setNewModuleDesc('');
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleUpdateModule(moduleId) {
    try {
      await updateModule(id, moduleId, editModule);
      setEditingModuleId(null);
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleDeleteModule(moduleId) {
    if (!window.confirm('Delete this module and all its steps/tasks?')) return;
    try { await deleteModule(id, moduleId); loadAll(); } catch (err) { alert('Failed to delete module'); }
  }

  /* ── Step CRUD ── */
  async function handleCreateStep(moduleId) {
    const f = newStepForm[moduleId];
    if (!f?.name?.trim()) return;
    const mod = modules.find((m) => m.id === moduleId);
    try {
      await createStep(id, moduleId, { name: f.name.trim(), description: f.description || '', step_order: (mod?.steps?.length || 0), status: 'not-started', included_task_ids: [] });
      setNewStepForm((prev) => ({ ...prev, [moduleId]: { name: '', description: '' } }));
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleUpdateStep(moduleId, stepId) {
    try {
      await updateStep(id, moduleId, stepId, editStep);
      setEditingStepId(null);
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleDeleteStep(moduleId, stepId) {
    try { await deleteStep(id, moduleId, stepId); loadAll(); } catch (err) { alert('Failed'); }
  }

  async function handleStepStatusToggle(moduleId, step) {
    const nextStatus = step.status === 'done' ? 'not-started' : 'done';
    try { await updateStep(id, moduleId, step.id, { status: nextStatus }); loadAll(); } catch (err) { console.error(err); }
  }

  async function handleIncludeTaskInStep(moduleId, stepId, taskId, currentIds) {
    const ids = currentIds.includes(taskId) ? currentIds.filter((i) => i !== taskId) : [...currentIds, taskId];
    try { await updateStep(id, moduleId, stepId, { included_task_ids: ids }); loadAll(); } catch (err) { console.error(err); }
  }

  /* ── Task CRUD ── */
  async function handleCreateTask(moduleId) {
    const f = newTaskForm[moduleId];
    if (!f?.name?.trim()) return;
    try {
      await createTask(id, moduleId, {
        name: f.name.trim(),
        description: f.description || '',
        status: 'not-started',
        deadline: f.deadline || null,
        dependencies: [],
      });
      setNewTaskForm((prev) => ({ ...prev, [moduleId]: { name: '', description: '', deadline: '' } }));
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleUpdateTask(moduleId, taskId) {
    try {
      const payload = { ...editTask };
      if (payload.deadline === '') payload.deadline = null;
      await updateTask(id, moduleId, taskId, payload);
      setEditingTaskId(null);
      loadAll();
    } catch (err) { alert('Failed: ' + (err.response?.data?.detail || err.message)); }
  }

  async function handleDeleteTask(moduleId, taskId) {
    try { await deleteTask(id, moduleId, taskId); loadAll(); } catch (err) { alert('Failed'); }
  }

  async function handleTaskStatusChange(moduleId, task, newStatus) {
    try { await updateTask(id, moduleId, task.id, { status: newStatus }); loadAll(); } catch (err) { console.error(err); }
  }

  async function handleToggleDependency(moduleId, task, depType, depId) {
    const deps = task.dependencies || [];
    const exists = deps.some((d) => d.type === depType && d.id === depId);
    const newDeps = exists ? deps.filter((d) => !(d.type === depType && d.id === depId)) : [...deps, { type: depType, id: depId }];
    try { await updateTask(id, moduleId, task.id, { dependencies: newDeps }); loadAll(); } catch (err) { console.error(err); }
  }

  function getStatusIcon(status) {
    const opt = TASK_STATUS_OPTIONS.find((o) => o.value === status);
    return opt ? opt.icon : '⚪';
  }

  if (!project) return <div className="card" style={{ padding: '2rem', textAlign: 'center' }}>Loading…</div>;

  const allLinks = getAllLinks(project);
  const themes = getThemesArray(project);
  const notes = getNotesArray(project);
  const linkedWfs = getProjectWorkflows();
  const unlinked = getUnlinkedWorkflows();
  const onlineServers = servers.filter((s) => s.status === 'online');

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <button className="btn btn-outline" style={{ padding: '0.3rem 0.6rem' }} onClick={() => navigate('/projects')}>← Back</button>
          <h1>{project.name}</h1>
          {themes.map((t, i) => (
            <ThemePill key={i} name={t} color={getThemeColor(t)} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {!isEditing && <button className="btn btn-outline" onClick={() => setManageModal(true)}><IC.tag size={16} /> Manage Themes</button>}
          {!isEditing && <button className="btn btn-outline" onClick={startEdit}><IC.edit size={16} /> Edit</button>}
          <button className="btn btn-danger" onClick={handleDeleteProject}>Delete</button>
        </div>
      </div>

      {/* Manage Themes modal */}
      {manageModal && (
        <div className="card" style={{ marginBottom: '1rem', borderColor: 'var(--accent)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <h3 style={{ fontSize: '0.9rem', margin: 0 }}><IC.tag size={16} style={{ marginRight: '0.3rem' }} /> Manage Themes</h3>
            <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick={() => setManageModal(false)}>✕ Close</button>
          </div>
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
                      {countProjectsWithTheme(t.name)} project(s)
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem', display: 'block' }}>Rename Theme Globally</label>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>This will rename the theme across ALL projects.</p>
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
                  <IC.alertTriangle size={14} style={{ marginRight: '0.3rem' }} /> This will affect {countProjectsWithTheme(renameOld)} project(s)
                </span>
              )}
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

            {/* Commands editor */}
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Useful Commands</label>
              {(form.useful_commands || []).map((cmd, i) => (
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
            {project.description && <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>{project.description}</p>}
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
              <span>Created: {new Date(project.created_at).toLocaleDateString()}</span>
              <span>Updated: {new Date(project.updated_at).toLocaleDateString()}</span>
            </div>
          </div>

          {/* Notes — array of {title, content} */}
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

          {/* Useful Commands */}
          {project.useful_commands?.length > 0 && (
            <div className="card">
              <h3 style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>💻 Useful Commands</h3>
              {project.useful_commands.map((cmd, i) => (
                <div key={i} style={{ fontSize: '0.85rem', fontFamily: 'monospace', padding: '0.3rem 0' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{cmd.label}: </span>
                  <code style={{ color: 'var(--accent)' }}>{cmd.command}</code>
                </div>
              ))}
            </div>
          )}

          {/* ── Modules Section ── */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600 }}><IC.box size={16} style={{ marginRight: '0.3rem' }} /> Modules ({modules.length})</h3>
            </div>

            {/* Create module inline */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 150 }}>
                <input value={newModuleName} onChange={(e) => setNewModuleName(e.target.value)} placeholder="Module name…"
                  onKeyDown={(e) => { if (e.key === 'Enter') handleCreateModule(); }} style={{ fontSize: '0.85rem' }} />
              </div>
              <div style={{ flex: 2, minWidth: 200 }}>
                <input value={newModuleDesc} onChange={(e) => setNewModuleDesc(e.target.value)} placeholder="Description (optional)" style={{ fontSize: '0.85rem' }} />
              </div>
              <button className="btn btn-primary" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }} onClick={handleCreateModule}>+ Add Module</button>
            </div>

            {/* Module list */}
            {modules.map((mod) => {
              const isExpanded = expandedModuleId === mod.id;
              const isEditingMod = editingModuleId === mod.id;
              const steps = [...(mod.steps || [])].sort((a, b) => a.step_order - b.step_order);
              const tasks = mod.tasks || [];
              const doneSteps = steps.filter((s) => s.status === 'done').length;
              const doneTasks = tasks.filter((t) => t.status === 'done').length;
              const sf = newStepForm[mod.id] || { name: '', description: '' };
              const tf = newTaskForm[mod.id] || { name: '', description: '', deadline: '' };

              return (
                <div key={mod.id} style={{ marginBottom: '0.5rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                  {/* Module header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.6rem 0.75rem', background: isExpanded ? 'var(--bg-primary)' : 'transparent', cursor: 'pointer' }}
                    onClick={() => setExpandedModuleId(isExpanded ? null : mod.id)}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{isExpanded ? '▼' : '▶'}</span>
                      {isEditingMod ? (
                        <div style={{ display: 'flex', gap: '0.4rem' }} onClick={(e) => e.stopPropagation()}>
                          <input value={editModule.name} onChange={(e) => setEditModule({ ...editModule, name: e.target.value })} style={{ fontSize: '0.85rem', width: 150 }} />
                          <input value={editModule.description} onChange={(e) => setEditModule({ ...editModule, description: e.target.value })} style={{ fontSize: '0.85rem', width: 250 }} placeholder="Description" />
                          <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => handleUpdateModule(mod.id)}>Save</button>
                          <button className="btn btn-outline" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => setEditingModuleId(null)}>Cancel</button>
                        </div>
                      ) : (
                        <>
                          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{mod.name}</span>
                          {mod.description && <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>— {mod.description}</span>}
                        </>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }} onClick={(e) => e.stopPropagation()}>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        {doneSteps}/{steps.length} steps · {doneTasks}/{tasks.length} tasks
                      </span>
                      {!isEditingMod && (
                        <>
                          <button onClick={() => { setEditingModuleId(mod.id); setEditModule({ name: mod.name, description: mod.description || '' }); }}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.8rem' }} title="Edit"><IC.edit size={14} /></button>
                          <button onClick={() => handleDeleteModule(mod.id)}
                            style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.8rem' }} title="Delete"><IC.trash size={14} /></button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Expanded content: Steps + Tasks */}
                  {isExpanded && (
                    <div style={{ padding: '0.75rem', borderTop: '1px solid var(--border)' }}>
                      {/* ── Steps (chronological to-do list) ── */}
                      <div style={{ marginBottom: '1rem' }}>
                        <h4 style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem' }}><IC.clipboard size={14} style={{ marginRight: '0.3rem' }} /> Steps ({steps.length})</h4>
                        {steps.map((step) => {
                          const isDone = step.status === 'done';
                          const isEditingS = editingStepId === step.id;
                          const includedTasks = tasks.filter((t) => (step.included_task_ids || []).includes(t.id));
                          return (
                            <div key={step.id} style={{ padding: '0.4rem 0.5rem', marginBottom: '0.25rem', background: isDone ? 'rgba(34,197,94,0.05)' : 'var(--bg-primary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                              {isEditingS ? (
                                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                  <input value={editStep.name || ''} onChange={(e) => setEditStep({ ...editStep, name: e.target.value })} style={{ fontSize: '0.85rem', flex: 1 }} />
                                  <input value={editStep.description || ''} onChange={(e) => setEditStep({ ...editStep, description: e.target.value })} placeholder="Description" style={{ fontSize: '0.85rem', flex: 1 }} />
                                  <select value={editStep.status || 'not-started'} onChange={(e) => setEditStep({ ...editStep, status: e.target.value })} style={{ fontSize: '0.8rem', width: 120 }}>
                                    {TASK_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.icon} {o.label}</option>)}
                                  </select>
                                  <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => handleUpdateStep(mod.id, step.id)}>Save</button>
                                  <button className="btn btn-outline" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => setEditingStepId(null)}>Cancel</button>
                                </div>
                              ) : (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                  <input type="checkbox" checked={isDone} onChange={() => handleStepStatusToggle(mod.id, step)} style={{ width: 'auto', cursor: 'pointer' }} />
                                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, minWidth: 20 }}>#{step.step_order + 1}</span>
                                  <span style={{ fontSize: '0.85rem', fontWeight: 500, textDecoration: isDone ? 'line-through' : 'none', color: isDone ? 'var(--text-muted)' : 'var(--text-primary)', flex: 1 }}>
                                    {step.name}
                                    {step.description && <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: '0.4rem', fontSize: '0.8rem' }}>— {step.description}</span>}
                                  </span>
                                  {includedTasks.length > 0 && (
                                    <span style={{ fontSize: '0.7rem', color: 'var(--accent)', background: 'rgba(59,130,246,0.1)', padding: '0.1rem 0.3rem', borderRadius: '4px' }}>
                                      {includedTasks.length} task(s)
                                    </span>
                                  )}
                                  <span style={{ fontSize: '0.75rem' }}>{getStatusIcon(step.status)}</span>
                                  <button onClick={() => { setEditingStepId(step.id); setEditStep({ name: step.name, description: step.description, status: step.status }); }}
                                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.75rem' }}><IC.edit size={12} /></button>
                                  <button onClick={() => handleDeleteStep(mod.id, step.id)}
                                    style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.75rem' }}>✕</button>
                                </div>
                              )}
                              {/* Include tasks in step */}
                              {!isEditingS && tasks.length > 0 && (
                                <div style={{ marginTop: '0.3rem', marginLeft: '1.8rem' }}>
                                  <details>
                                    <summary style={{ fontSize: '0.7rem', color: 'var(--text-muted)', cursor: 'pointer' }}>Include tasks…</summary>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.2rem' }}>
                                      {tasks.map((t) => {
                                        const included = (step.included_task_ids || []).includes(t.id);
                                        return (
                                          <label key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.75rem', cursor: 'pointer', padding: '0.1rem 0.3rem', borderRadius: '4px', background: included ? 'rgba(59,130,246,0.1)' : 'transparent' }}>
                                            <input type="checkbox" checked={included} onChange={() => handleIncludeTaskInStep(mod.id, step.id, t.id, step.included_task_ids || [])} style={{ width: 'auto' }} />
                                            {t.name}
                                          </label>
                                        );
                                      })}
                                    </div>
                                  </details>
                                </div>
                              )}
                            </div>
                          );
                        })}
                        {/* Add step */}
                        <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.3rem' }}>
                          <input value={sf.name} onChange={(e) => setNewStepForm((p) => ({ ...p, [mod.id]: { ...sf, name: e.target.value } }))} placeholder="Step name…"
                            onKeyDown={(e) => { if (e.key === 'Enter') handleCreateStep(mod.id); }} style={{ flex: 1, fontSize: '0.8rem' }} />
                          <input value={sf.description} onChange={(e) => setNewStepForm((p) => ({ ...p, [mod.id]: { ...sf, description: e.target.value } }))} placeholder="Description (optional)" style={{ flex: 1, fontSize: '0.8rem' }} />
                          <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem' }} onClick={() => handleCreateStep(mod.id)}>+ Step</button>
                        </div>
                      </div>

                      {/* ── Tasks (unorganized to-do with deadlines & dependencies) ── */}
                      <div>
                        <h4 style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.4rem' }}><IC.pin size={14} style={{ marginRight: '0.3rem' }} /> Tasks ({tasks.length})</h4>
                        {tasks.map((task) => {
                          const isEditingT = editingTaskId === task.id;
                          const deps = task.dependencies || [];
                          const depLabels = deps.map((d) => {
                            if (d.type === 'module') {
                              const m = modules.find((mm) => mm.id === d.id);
                              return `📦 ${m ? m.name : d.id.slice(0, 8)}`;
                            }
                            // Find in all module tasks
                            for (const mm of modules) {
                              const t = (mm.tasks || []).find((tt) => tt.id === d.id);
                              if (t) return `📌 ${t.name}`;
                            }
                            return `? ${d.id.slice(0, 8)}`;
                          });
                          return (
                            <div key={task.id} style={{ padding: '0.4rem 0.5rem', marginBottom: '0.25rem', background: task.status === 'done' ? 'rgba(34,197,94,0.05)' : task.status === 'blocked' ? 'rgba(239,68,68,0.05)' : 'var(--bg-primary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                              {isEditingT ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                                  <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                    <input value={editTask.name || ''} onChange={(e) => setEditTask({ ...editTask, name: e.target.value })} style={{ fontSize: '0.85rem', flex: 1 }} />
                                    <select value={editTask.status || 'not-started'} onChange={(e) => setEditTask({ ...editTask, status: e.target.value })} style={{ fontSize: '0.8rem', width: 130 }}>
                                      {TASK_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.icon} {o.label}</option>)}
                                    </select>
                                    <input type="date" value={editTask.deadline ? editTask.deadline.slice(0, 10) : ''} onChange={(e) => setEditTask({ ...editTask, deadline: e.target.value ? e.target.value + 'T00:00:00' : '' })} style={{ fontSize: '0.8rem', width: 140 }} />
                                  </div>
                                  <input value={editTask.description || ''} onChange={(e) => setEditTask({ ...editTask, description: e.target.value })} placeholder="Description" style={{ fontSize: '0.8rem' }} />
                                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                                    <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => handleUpdateTask(mod.id, task.id)}>Save</button>
                                    <button className="btn btn-outline" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => setEditingTaskId(null)}>Cancel</button>
                                  </div>
                                </div>
                              ) : (
                                <div>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <select value={task.status} onChange={(e) => handleTaskStatusChange(mod.id, task, e.target.value)}
                                      style={{ width: 'auto', fontSize: '0.75rem', padding: '0.1rem 0.2rem', border: '1px solid var(--border)', borderRadius: '4px', background: 'transparent', cursor: 'pointer' }}>
                                      {TASK_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.icon} {o.label}</option>)}
                                    </select>
                                    <span style={{ fontSize: '0.85rem', fontWeight: 500, textDecoration: task.status === 'done' ? 'line-through' : 'none', color: task.status === 'done' ? 'var(--text-muted)' : 'var(--text-primary)', flex: 1 }}>
                                      {task.name}
                                      {task.description && <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: '0.4rem', fontSize: '0.8rem' }}>— {task.description}</span>}
                                    </span>
                                    {task.deadline && (
                                      <span style={{ fontSize: '0.7rem', color: new Date(task.deadline) < new Date() && task.status !== 'done' ? 'var(--error)' : 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', padding: '0.1rem 0.3rem', borderRadius: '4px' }}>
                                        <IC.calendar size={12} style={{ marginRight: '0.2rem' }} /> {new Date(task.deadline).toLocaleDateString()}
                                      </span>
                                    )}
                                    <button onClick={() => { setEditingTaskId(task.id); setEditTask({ name: task.name, description: task.description, status: task.status, deadline: task.deadline || '' }); }}
                                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.75rem' }}><IC.edit size={12} /></button>
                                    <button onClick={() => handleDeleteTask(mod.id, task.id)}
                                      style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.75rem' }}>✕</button>
                                  </div>
                                  {deps.length > 0 && (
                                    <div style={{ marginTop: '0.2rem', marginLeft: '0.5rem', display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
                                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Depends on:</span>
                                      {depLabels.map((lbl, i) => (
                                        <span key={i} style={{ fontSize: '0.7rem', padding: '0.05rem 0.25rem', borderRadius: '4px', background: 'rgba(168,85,247,0.1)', color: 'var(--accent)' }}>{lbl}</span>
                                      ))}
                                    </div>
                                  )}
                                  {/* Dependencies picker */}
                                  <details style={{ marginTop: '0.2rem', marginLeft: '0.5rem' }}>
                                    <summary style={{ fontSize: '0.7rem', color: 'var(--text-muted)', cursor: 'pointer' }}>Manage dependencies…</summary>
                                    <div style={{ marginTop: '0.2rem', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                                      <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)' }}>Modules:</span>
                                      {modules.map((mm) => {
                                        const isDep = deps.some((d) => d.type === 'module' && d.id === mm.id);
                                        return (
                                          <label key={mm.id} style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.75rem', cursor: 'pointer' }}>
                                            <input type="checkbox" checked={isDep} onChange={() => handleToggleDependency(mod.id, task, 'module', mm.id)} style={{ width: 'auto' }} />
                                            📦 {mm.name}
                                          </label>
                                        );
                                      })}
                                      <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', marginTop: '0.2rem' }}>Tasks (this module):</span>
                                      {tasks.filter((t) => t.id !== task.id).map((t) => {
                                        const isDep = deps.some((d) => d.type === 'task' && d.id === t.id);
                                        return (
                                          <label key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.75rem', cursor: 'pointer' }}>
                                            <input type="checkbox" checked={isDep} onChange={() => handleToggleDependency(mod.id, task, 'task', t.id)} style={{ width: 'auto' }} />
                                            📌 {t.name}
                                          </label>
                                        );
                                      })}
                                      {/* Tasks from other modules */}
                                      {modules.filter((mm) => mm.id !== mod.id).map((mm) => (
                                        (mm.tasks || []).length > 0 && (
                                          <div key={mm.id}>
                                            <span style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', marginTop: '0.2rem' }}>Tasks ({mm.name}):</span>
                                            {(mm.tasks || []).map((t) => {
                                              const isDep = deps.some((d) => d.type === 'task' && d.id === t.id);
                                              return (
                                                <label key={t.id} style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.75rem', cursor: 'pointer' }}>
                                                  <input type="checkbox" checked={isDep} onChange={() => handleToggleDependency(mod.id, task, 'task', t.id)} style={{ width: 'auto' }} />
                                                  📌 {t.name}
                                                </label>
                                              );
                                            })}
                                          </div>
                                        )
                                      ))}
                                    </div>
                                  </details>
                                </div>
                              )}
                            </div>
                          );
                        })}
                        {/* Add task */}
                        <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.3rem', flexWrap: 'wrap' }}>
                          <input value={tf.name} onChange={(e) => setNewTaskForm((p) => ({ ...p, [mod.id]: { ...tf, name: e.target.value } }))} placeholder="Task name…"
                            onKeyDown={(e) => { if (e.key === 'Enter') handleCreateTask(mod.id); }} style={{ flex: 1, fontSize: '0.8rem', minWidth: 120 }} />
                          <input value={tf.description} onChange={(e) => setNewTaskForm((p) => ({ ...p, [mod.id]: { ...tf, description: e.target.value } }))} placeholder="Description" style={{ flex: 1, fontSize: '0.8rem', minWidth: 120 }} />
                          <input type="date" value={tf.deadline} onChange={(e) => setNewTaskForm((p) => ({ ...p, [mod.id]: { ...tf, deadline: e.target.value } }))} style={{ fontSize: '0.8rem', width: 140 }} />
                          <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem' }} onClick={() => handleCreateTask(mod.id)}>+ Task</button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {modules.length === 0 && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No modules yet. Add one above to organize steps and tasks.</p>
            )}
          </div>

          {/* ── Linked Resources Section ── */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600 }}><IC.box size={16} style={{ marginRight: '0.3rem' }} /> Linked Resources ({linkedResources.length})</h3>
              <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                onClick={() => setResourceLinkingMode(!resourceLinkingMode)}>
                {resourceLinkingMode ? 'Done' : '+ Link Resource'}
              </button>
            </div>

            {linkedResources.map((res) => (
              <div key={res.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.4rem 0.5rem', marginBottom: '0.25rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
                  onClick={() => navigate(`/resources/${res.id}`)}>
                  <span style={{ fontSize: '0.9rem' }}><IC.box size={16} /></span>
                  <span style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--accent)' }}>{res.name}</span>
                  {(res.themes || []).map((t, i) => (
                    <ThemePill key={i} name={t} color={getThemeColor(t)} size="small" />
                  ))}
                </div>
                <button onClick={() => { unlinkResourceProject(res.id, id).then(() => loadAll()); }}
                  style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.8rem' }}
                  title="Unlink">✕</button>
              </div>
            ))}

            {linkedResources.length === 0 && !resourceLinkingMode && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No resources linked to this project</p>
            )}

            {resourceLinkingMode && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
                {(() => {
                  const linkedIds = new Set(linkedResources.map((r) => r.id));
                  const unlinkedRes = allResources.filter((r) => !linkedIds.has(r.id));
                  return unlinkedRes.length === 0 ? (
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>All resources are linked.</p>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                      {unlinkedRes.map((res) => (
                        <div key={res.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.25rem 0.4rem', borderRadius: '4px' }}>
                          <span style={{ fontSize: '0.85rem' }}>{res.name}</span>
                          <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
                            onClick={() => { linkResourceProject(res.id, id).then(() => loadAll()); }}>+ Link</button>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}
          </div>

          {/* ── Workflows Section with Execute ── */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600 }}><IC.zap size={16} style={{ marginRight: '0.3rem' }} /> Workflows ({linkedWfs.length})</h3>
              <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                onClick={() => setLinkingMode(!linkingMode)}>
                {linkingMode ? 'Done' : '+ Link Workflow'}
              </button>
            </div>

            {/* Server selector for execution */}
            {linkedWfs.length > 0 && (
              <div style={{ marginBottom: '0.75rem', padding: '0.5rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Target Servers</span>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.25rem' }}>
                  {onlineServers.map((s) => (
                    <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.85rem' }}>
                      <input type="checkbox" checked={selectedServers.includes(s.id)} onChange={() => toggleServer(s.id)} style={{ width: 'auto' }} />
                      {s.name} <StatusBadge status={s.status} />
                    </label>
                  ))}
                  {onlineServers.length === 0 && <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No servers online</span>}
                </div>
              </div>
            )}

            {/* Linked workflows */}
            {linkedWfs.map((wf) => {
              const isRunning = executingSet.has(wf.id);
              const outputs = executionOutputs[wf.id] || [];
              const showOutput = expandedOutputs[wf.id] ?? false;
              return (
                <div key={wf.id} style={{ marginBottom: '0.75rem', padding: '0.75rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <div>
                      <span style={{ fontSize: '0.95rem', fontWeight: 600 }}>{wf.name}</span>
                      {wf.description && <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginLeft: '0.5rem' }}>— {wf.description}</span>}
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '0.5rem' }}>({wf.steps.length} steps)</span>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        className={isRunning ? 'btn btn-outline' : 'btn btn-primary'}
                        style={{ fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}
                        onClick={() => handleExecute(wf.id)}
                        disabled={isRunning}
                      >
                        {isRunning ? '⏳ Running…' : '▶ Execute'}
                      </button>
                      <button onClick={() => unlinkWorkflow(wf.id)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '0.8rem' }} title="Unlink">✕</button>
                    </div>
                  </div>
                  {/* Steps table */}
                  <div className="table-container">
                    <table>
                      <thead>
                        <tr><th>#</th><th>Step</th><th>Command</th><th>Timeout</th></tr>
                      </thead>
                      <tbody>
                        {wf.steps.map((step) => (
                          <tr key={step.id}>
                            <td>{step.step_order}</td>
                            <td style={{ fontWeight: 500 }}>{step.name}</td>
                            <td><code style={{ fontSize: '0.8rem' }}>{step.command}</code></td>
                            <td>{step.timeout_seconds}s</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* Execution output */}
                  {outputs.length > 0 && (
                    <div style={{ marginTop: '0.5rem' }}>
                      <div onClick={() => toggleOutput(wf.id)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '0.4rem 0', borderTop: '1px solid var(--border)' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}><IC.clipboard size={14} style={{ marginRight: '0.3rem' }} /> Output ({outputs.length} lines)</span>
                        <span style={{ color: 'var(--text-muted)' }}>{showOutput ? '▼' : '▶'}</span>
                      </div>
                      {showOutput && (
                        <div className="terminal" style={{ maxHeight: '300px', overflowY: 'auto' }}>
                          {outputs.map((o, i) => (
                            <div key={i} className={o.stream || 'stdout'}>
                              {o.server && <span style={{ color: '#fbbf24' }}>[{o.server}] </span>}
                              {o.line}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {linkedWfs.length === 0 && !linkingMode && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No workflows linked to this project</p>
            )}

            {/* Link picker */}
            {linkingMode && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius)' }}>
                {unlinked.length === 0 ? (
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>All workflows are linked to projects.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                    {unlinked.map((wf) => (
                      <div key={wf.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.25rem 0.4rem', borderRadius: '4px' }}>
                        <span style={{ fontSize: '0.85rem' }}>{wf.name} <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>({wf.steps.length} steps)</span></span>
                        <button className="btn btn-primary" style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }} onClick={() => linkWorkflow(wf.id)}>+ Add</button>
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
