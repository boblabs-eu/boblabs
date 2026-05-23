/**
 * Bob Manager — Workflows page.
 * Execute button shows "Running…" during execution. Shows execution outputs.
 * Can link workflow to a project.
 */

import React, { useState, useEffect } from 'react';
import { getWorkflows, getServers, getProjects, createWorkflow, updateWorkflow, deleteWorkflow, executeWorkflow, getWorkflowExecutions } from '../services/api';
import StatusBadge from '../components/common/StatusBadge';
import { IC } from '../components/common/Icons';
import { InfraRestrictedMessage, isInfraRestricted } from '../components/common/InfraRestricted';
import wsService from '../services/websocket';

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState([]);
  const [servers, setServers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingWfId, setEditingWfId] = useState(null);
  const [executingSet, setExecutingSet] = useState(new Set());
  const [executionOutputs, setExecutionOutputs] = useState({});
  const [expandedOutputs, setExpandedOutputs] = useState({});
  const [restricted, setRestricted] = useState(false);
  const [form, setForm] = useState({
    name: '',
    description: '',
    project_id: '',
    steps: [{ name: '', command: '' }],
  });
  const [selectedServers, setSelectedServers] = useState([]);

  useEffect(() => {
    loadData();

    const unsubStepStart = wsService.on('workflow.step.start', (data) => {
      addExecOutput(data.workflow_id, data.server_name || data.server_id, 'info',
        `▶ Step ${data.step_order}: ${data.step_name || 'running'}…`);
    });

    const unsubStepComplete = wsService.on('workflow.step.complete', (data) => {
      const status = data.exit_code === 0 ? '✅' : '❌';
      addExecOutput(data.workflow_id, data.server_name || data.server_id, data.exit_code === 0 ? 'stdout' : 'stderr',
        `${status} Step ${data.step_order}: exit ${data.exit_code}`);
      if (data.stdout) {
        data.stdout.split('\n').filter(Boolean).forEach((line) => {
          addExecOutput(data.workflow_id, data.server_name || data.server_id, 'stdout', line);
        });
      }
      if (data.stderr) {
        data.stderr.split('\n').filter(Boolean).forEach((line) => {
          addExecOutput(data.workflow_id, data.server_name || data.server_id, 'stderr', line);
        });
      }
    });

    const unsubExecComplete = wsService.on('workflow.execution.complete', (data) => {
      addExecOutput(data.workflow_id, data.server_name || data.server_id, 'info',
        `── Execution ${data.status} ──`);
      setExecutingSet((prev) => {
        const next = new Set(prev);
        next.delete(data.workflow_id);
        return next;
      });
    });

    return () => { unsubStepStart(); unsubStepComplete(); unsubExecComplete(); };
  }, []);

  function addExecOutput(workflowId, server, stream, line) {
    setExecutionOutputs((prev) => ({
      ...prev,
      [workflowId]: [...(prev[workflowId] || []), { server, stream, line, ts: Date.now() }],
    }));
  }

  async function loadData() {
    try {
      const [wfRes, srvRes, projRes] = await Promise.all([getWorkflows(), getServers(), getProjects()]);
      setWorkflows(wfRes.data);
      setServers(srvRes.data);
      setProjects(projRes.data);
    } catch (err) {
      if (isInfraRestricted(err)) { setRestricted(true); return; }
      console.error('Failed to load workflows:', err);
    }
  }

  if (restricted) return <InfraRestrictedMessage />;

  async function handleCreate(e) {
    e.preventDefault();
    try {
      const payload = {
        ...form,
        project_id: form.project_id || null,
      };
      await createWorkflow(payload);
      setForm({ name: '', description: '', project_id: '', steps: [{ name: '', command: '' }] });
      setShowCreate(false);
      loadData();
    } catch (err) {
      alert('Failed to create workflow: ' + (err.response?.data?.detail || err.message));
    }
  }

  async function handleExecute(workflowId) {
    if (selectedServers.length === 0) {
      alert('Select at least one server');
      return;
    }
    try {
      setExecutingSet((prev) => new Set(prev).add(workflowId));
      setExecutionOutputs((prev) => ({ ...prev, [workflowId]: [] }));
      setExpandedOutputs((prev) => ({ ...prev, [workflowId]: true }));
      const res = await executeWorkflow(workflowId, selectedServers);
      // Process REST response as well (fallback if WS events don't arrive)
      (res.data || []).forEach((exec) => {
        if (exec.status) {
          addExecOutput(workflowId, exec.server_id || '?', 'info', `Execution status: ${exec.status}`);
        }
        (exec.logs || []).forEach((log) => {
          if (log.stdout) {
            log.stdout.split('\n').filter(Boolean).forEach((line) => {
              addExecOutput(workflowId, exec.server_id || '?', 'stdout', line);
            });
          }
          if (log.stderr) {
            log.stderr.split('\n').filter(Boolean).forEach((line) => {
              addExecOutput(workflowId, exec.server_id || '?', 'stderr', line);
            });
          }
        });
      });
    } catch (err) {
      addExecOutput(workflowId, '-', 'stderr', `Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setExecutingSet((prev) => {
        const next = new Set(prev);
        next.delete(workflowId);
        return next;
      });
    }
  }

  async function handleDelete(id) {
    if (!window.confirm('Delete this workflow?')) return;
    try {
      await deleteWorkflow(id);
      loadData();
    } catch (err) {
      alert('Failed to delete workflow');
    }
  }

  function startEdit(wf) {
    setEditingWfId(wf.id);
    setShowCreate(false);
    setForm({
      name: wf.name,
      description: wf.description || '',
      project_id: wf.project_id || '',
      steps: wf.steps.map((s) => ({ name: s.name, command: s.command })),
    });
  }

  function cancelEdit() {
    setEditingWfId(null);
    setForm({ name: '', description: '', project_id: '', steps: [{ name: '', command: '' }] });
  }

  async function handleUpdate(e) {
    e.preventDefault();
    try {
      const payload = { ...form, project_id: form.project_id || null };
      await updateWorkflow(editingWfId, payload);
      cancelEdit();
      loadData();
    } catch (err) {
      alert('Failed to update workflow: ' + (err.response?.data?.detail || err.message));
    }
  }

  function addStep() {
    setForm({ ...form, steps: [...form.steps, { name: '', command: '' }] });
  }

  function updateStep(index, field, value) {
    const steps = [...form.steps];
    steps[index] = { ...steps[index], [field]: value };
    setForm({ ...form, steps });
  }

  function removeStep(index) {
    setForm({ ...form, steps: form.steps.filter((_, i) => i !== index) });
  }

  function toggleServer(id) {
    setSelectedServers((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  }

  function toggleOutput(wfId) {
    setExpandedOutputs((prev) => ({ ...prev, [wfId]: !prev[wfId] }));
  }

  function getProjectName(projectId) {
    const p = projects.find((pr) => pr.id === projectId);
    return p ? p.name : null;
  }

  return (
    <div>
      <div className="page-header">
        <h1>Workflows</h1>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? 'Cancel' : '+ Create Workflow'}
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <form onSubmit={handleCreate}>
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 180 }}>
                <label>Workflow Name</label>
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div style={{ flex: 2, minWidth: 250 }}>
                <label>Description</label>
                <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div style={{ minWidth: 180 }}>
                <label>Link to Project</label>
                <select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} style={{ width: '100%' }}>
                  <option value="">— None —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <h3 style={{ fontSize: '0.875rem', marginBottom: '0.5rem' }}>Steps</h3>
            {form.steps.map((step, i) => (
              <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem', alignItems: 'flex-end' }}>
                <div style={{ width: 200 }}>
                  <label>Step Name</label>
                  <input value={step.name} onChange={(e) => updateStep(i, 'name', e.target.value)} required />
                </div>
                <div style={{ flex: 1 }}>
                  <label>Command</label>
                  <input value={step.command} onChange={(e) => updateStep(i, 'command', e.target.value)} required />
                </div>
                {form.steps.length > 1 && (
                  <button type="button" className="btn btn-danger" style={{ padding: '0.4rem 0.6rem' }} onClick={() => removeStep(i)}>✕</button>
                )}
              </div>
            ))}
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
              <button type="button" className="btn btn-outline" onClick={addStep}>+ Add Step</button>
              <button type="submit" className="btn btn-primary">Create Workflow</button>
            </div>
          </form>
        </div>
      )}

      {/* Server selector for execution */}
      {workflows.length > 0 && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '0.875rem', marginBottom: '0.5rem' }}>Select Target Servers</h3>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {servers.map((s) => (
              <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.875rem' }}>
                <input
                  type="checkbox"
                  checked={selectedServers.includes(s.id)}
                  onChange={() => toggleServer(s.id)}
                  style={{ width: 'auto' }}
                />
                {s.name}
                <StatusBadge status={s.status} />
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Workflow list */}
      {workflows.map((wf) => {
        const isRunning = executingSet.has(wf.id);
        const outputs = executionOutputs[wf.id] || [];
        const showOutput = expandedOutputs[wf.id] ?? false;
        const projectName = getProjectName(wf.project_id);
        const isEditing = editingWfId === wf.id;

        return (
          <div className="card" key={wf.id} style={{ marginBottom: '1rem' }}>
            {isEditing ? (
              /* ── Inline edit form ── */
              <form onSubmit={handleUpdate}>
                <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 180 }}>
                    <label>Workflow Name</label>
                    <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                  </div>
                  <div style={{ flex: 2, minWidth: 250 }}>
                    <label>Description</label>
                    <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>
                  <div style={{ minWidth: 180 }}>
                    <label>Link to Project</label>
                    <select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} style={{ width: '100%' }}>
                      <option value="">— None —</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <h3 style={{ fontSize: '0.875rem', marginBottom: '0.5rem' }}>Steps</h3>
                {form.steps.map((step, i) => (
                  <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem', alignItems: 'flex-end' }}>
                    <div style={{ width: 200 }}>
                      <label>Step Name</label>
                      <input value={step.name} onChange={(e) => updateStep(i, 'name', e.target.value)} required />
                    </div>
                    <div style={{ flex: 1 }}>
                      <label>Command</label>
                      <input value={step.command} onChange={(e) => updateStep(i, 'command', e.target.value)} required />
                    </div>
                    {form.steps.length > 1 && (
                      <button type="button" className="btn btn-danger" style={{ padding: '0.4rem 0.6rem' }} onClick={() => removeStep(i)}>✕</button>
                    )}
                  </div>
                ))}
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                  <button type="button" className="btn btn-outline" onClick={addStep}>+ Add Step</button>
                  <button type="submit" className="btn btn-primary">Save Changes</button>
                  <button type="button" className="btn btn-outline" onClick={cancelEdit}>Cancel</button>
                </div>
              </form>
            ) : (
              /* ── Read-only view ── */
              <>
                <div className="card-header">
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <h2>{wf.name}</h2>
                      {projectName && (
                        <span style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', borderRadius: '9999px', background: 'rgba(99,102,241,0.15)', color: 'var(--accent)', fontWeight: 500 }}>
                          <IC.folder size={14} style={{ marginRight: '0.3rem' }} /> {projectName}
                        </span>
                      )}
                    </div>
                    {wf.description && <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{wf.description}</p>}
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button className="btn btn-outline" style={{ padding: '0.4rem 0.6rem' }} onClick={() => startEdit(wf)}><IC.edit size={14} /> Edit</button>
                    <button
                      className={isRunning ? 'btn btn-outline' : 'btn btn-primary'}
                      onClick={() => handleExecute(wf.id)}
                      disabled={isRunning}
                      style={isRunning ? { cursor: 'not-allowed', opacity: 0.7 } : {}}
                    >
                      {isRunning ? '⏳ Running…' : '▶ Execute'}
                    </button>
                    <button className="btn btn-danger" style={{ padding: '0.4rem 0.6rem' }} onClick={() => handleDelete(wf.id)}>Delete</button>
                  </div>
                </div>

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
              </>
            )}

            {/* Execution output */}
            {outputs.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <div
                  onClick={() => toggleOutput(wf.id)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', padding: '0.4rem 0', borderTop: '1px solid var(--border)' }}
                >
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    <IC.clipboard size={14} style={{ marginRight: '0.3rem' }} /> Execution Output ({outputs.length} lines)
                  </span>
                  <span style={{ color: 'var(--text-muted)' }}>{showOutput ? <IC.chevronDown size={14} /> : <IC.chevronRight size={14} />}</span>
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

      {workflows.length === 0 && !showCreate && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>No workflows created yet. Click "Create Workflow" to get started.</p>
        </div>
      )}
    </div>
  );
}
