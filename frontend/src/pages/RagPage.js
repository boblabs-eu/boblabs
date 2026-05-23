import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  getLabs,
  getRagCollections,
  createRagCollection,
  updateRagCollection,
  deleteRagCollection,
  getRagDocuments,
  uploadRagDocument,
  uploadRagDocumentFromUrl,
  deleteRagDocument,
  reingestRagDocument,
  reingestAllRagDocuments,
  getLabRagAccess,
  grantLabRagAccess,
  updateLabRagAccess,
  revokeLabRagAccess,
  searchRag,
  getAIModels,
} from '../services/api';
import ShareModal from '../components/common/ShareModal';

function HighlightText({ text, query }) {
  if (!query || !query.trim()) return <>{text}</>;
  const words = query.trim().split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (words.length === 0) return <>{text}</>;
  const regex = new RegExp(`(${words.join('|')})`, 'gi');
  const parts = text.split(regex);
  return <>{parts.map((part, i) =>
    regex.test(part)
      ? <mark key={i} style={{ background: '#ffe066', color: 'inherit', borderRadius: '2px', padding: '0 1px' }}>{part}</mark>
      : part
  )}</>;
}

const defaultCollectionForm = {
  name: '',
  display_name: '',
  description: '',
  embedding_model: 'all-MiniLM-L6-v2',
  default_chunk_size: 512,
  default_chunk_overlap: 64,
  default_splitter: 'recursive',
  rag_mode: 'vector',
  lightrag_model_id: '',
  lightrag_search_mode: 'hybrid',
};

const defaultDocumentUploadForm = {
  chunk_size: '',
  chunk_overlap: '',
  splitter: '',
  metadata: '{}',
};

const defaultWebpageUploadForm = {
  url: '',
  chunk_size: '',
  chunk_overlap: '',
  splitter: '',
  metadata: '{}',
};

const defaultSearchForm = {
  query: '',
  top_k: 5,
  score_threshold: 0.3,
  filter: '{}',
  mode: '',
};

const splitterOptions = ['recursive', 'sentence', 'paragraph', 'fixed', 'code'];
const embeddingModelOptions = [
  { value: 'all-MiniLM-L6-v2', label: 'all-MiniLM-L6-v2', dimension: 384 },
  { value: 'bge-base-en-v1.5', label: 'bge-base-en-v1.5', dimension: 768 },
  { value: 'bge-large-en-v1.5', label: 'bge-large-en-v1.5', dimension: 1024 },
];

const defaultExpandedSections = {
  createCollection: true,
  collectionSettings: true,
  documents: true,
  labAccess: true,
  searchPlayground: true,
};

const defaultDocumentOverride = {
  splitter: '',
  chunk_size: '',
  chunk_overlap: '',
};

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function StatusBadge({ status }) {
  const colors = {
    pending: { bg: 'rgba(251,191,36,0.15)', color: 'var(--warning)' },
    processing: { bg: 'rgba(59,130,246,0.15)', color: '#60a5fa' },
    ready: { bg: 'rgba(34,197,94,0.15)', color: 'var(--success)' },
    failed: { bg: 'rgba(239,68,68,0.15)', color: 'var(--error)' },
  };
  const theme = colors[status] || { bg: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' };
  return (
    <span className="badge" style={{ background: theme.bg, color: theme.color }}>
      {status}
    </span>
  );
}

function SourceBadge({ document }) {
  const sourceType = document.metadata?.source_type;
  if (sourceType === 'webpage') {
    return <span className="badge badge-info">Webpage</span>;
  }
  return <span className="badge" style={{ background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' }}>File</span>;
}

function SectionToggle({ expanded, onToggle }) {
  return (
    <button className="btn btn-outline rag-section-toggle" type="button" onClick={onToggle}>
      {expanded ? 'Collapse' : 'Expand'}
    </button>
  );
}

function UploadConfigFields({ form, setForm, selectedCollection }) {
  return (
    <>
      <div className="grid grid-3">
        <input
          type="number"
          min="64"
          max="4096"
          placeholder={`Chunk size (${selectedCollection.default_chunk_size})`}
          value={form.chunk_size}
          onChange={(event) => setForm((current) => ({ ...current, chunk_size: event.target.value }))}
        />
        <input
          type="number"
          min="0"
          max="512"
          placeholder={`Overlap (${selectedCollection.default_chunk_overlap})`}
          value={form.chunk_overlap}
          onChange={(event) => setForm((current) => ({ ...current, chunk_overlap: event.target.value }))}
        />
        <select
          value={form.splitter}
          onChange={(event) => setForm((current) => ({ ...current, splitter: event.target.value }))}
        >
          <option value="">Default splitter ({selectedCollection.default_splitter})</option>
          {splitterOptions.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </div>
      <textarea
        rows={2}
        value={form.metadata}
        onChange={(event) => setForm((current) => ({ ...current, metadata: event.target.value }))}
        placeholder='Metadata JSON, for example {"category":"engineering"}'
      />
    </>
  );
}

export default function RagPage() {
  const [collections, setCollections] = useState([]);
  const [shareTarget, setShareTarget] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [labs, setLabs] = useState([]);
  const [accessMap, setAccessMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingCollection, setSavingCollection] = useState(false);
  const [uploadingDocument, setUploadingDocument] = useState(false);
  const [uploadingWebpage, setUploadingWebpage] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [createForm, setCreateForm] = useState(defaultCollectionForm);
  const [collectionForm, setCollectionForm] = useState(defaultCollectionForm);
  const [documentUploadForm, setDocumentUploadForm] = useState(defaultDocumentUploadForm);
  const [webpageUploadForm, setWebpageUploadForm] = useState(defaultWebpageUploadForm);
  const [uploadFile, setUploadFile] = useState(null);
  const fileInputRef = useRef(null);
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState('');
  const [searchForm, setSearchForm] = useState(defaultSearchForm);
  const [searchResults, setSearchResults] = useState([]);
  const [expandedSections, setExpandedSections] = useState(defaultExpandedSections);
  const [documentOverrides, setDocumentOverrides] = useState({});
  const [aiModels, setAiModels] = useState([]);

  const selectedCollection = useMemo(
    () => collections.find((item) => item.id === selectedId) || null,
    [collections, selectedId],
  );

  useEffect(() => {
    loadInitialData();
  }, []);

  useEffect(() => {
    if (!selectedCollection) {
      setDocuments([]);
      setAccessMap({});
      setDocumentOverrides({});
      return;
    }
    setCollectionForm({
      name: selectedCollection.name,
      display_name: selectedCollection.display_name,
      description: selectedCollection.description || '',
      embedding_model: selectedCollection.embedding_model,
      default_chunk_size: selectedCollection.default_chunk_size,
      default_chunk_overlap: selectedCollection.default_chunk_overlap,
      default_splitter: selectedCollection.default_splitter,
      rag_mode: selectedCollection.rag_mode || 'vector',
      lightrag_model_id: selectedCollection.lightrag_model_id || '',
      lightrag_search_mode: selectedCollection.lightrag_search_mode || 'hybrid',
    });
    loadCollectionDetails(selectedCollection.id);
  }, [selectedCollection?.id]);

  useEffect(() => {
    setDocumentOverrides((current) => {
      const next = {};
      documents.forEach((document) => {
        next[document.id] = current[document.id] || defaultDocumentOverride;
      });
      return next;
    });
  }, [documents]);

  useEffect(() => {
    if (!selectedCollection) return undefined;
    const hasActiveIngest = documents.some((doc) => doc.status === 'pending' || doc.status === 'processing');
    if (!hasActiveIngest) return undefined;
    const timer = window.setInterval(() => {
      loadDocuments(selectedCollection.id);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedCollection?.id, documents]);

  async function loadInitialData() {
    setLoading(true);
    setError('');
    try {
      const [collectionsRes, labsRes] = await Promise.all([getRagCollections(), getLabs()]);
      const nextCollections = collectionsRes.data;
      setCollections(nextCollections);
      setLabs(labsRes.data || []);
      if (nextCollections.length > 0) {
        setSelectedId((current) => current || nextCollections[0].id);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load RAG data.');
    } finally {
      setLoading(false);
    }
    try {
      const modelsRes = await getAIModels();
      setAiModels(modelsRes.data || []);
    } catch (_) {
      // Models are optional — only needed for LightRAG collection creation
    }
  }

  async function loadCollectionDetails(collectionId) {
    await Promise.all([loadDocuments(collectionId), loadAccess(collectionId)]);
  }

  async function loadDocuments(collectionId) {
    try {
      const res = await getRagDocuments(collectionId);
      setDocuments(res.data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load documents.');
    }
  }

  async function loadAccess(collectionId) {
    try {
      const results = await Promise.all(
        labs.map(async (lab) => {
          const res = await getLabRagAccess(lab.id);
          const entry = (res.data || []).find((item) => item.collection_id === collectionId);
          return [lab.id, entry || null];
        }),
      );
      setAccessMap(Object.fromEntries(results));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load lab access.');
    }
  }

  async function refreshCollections(preferredId) {
    const res = await getRagCollections();
    const nextCollections = res.data || [];
    setCollections(nextCollections);
    if (nextCollections.length === 0) {
      setSelectedId(null);
      return;
    }
    if (preferredId) {
      const exists = nextCollections.some((item) => item.id === preferredId);
      setSelectedId(exists ? preferredId : nextCollections[0].id);
      return;
    }
    setSelectedId((current) => {
      if (current && nextCollections.some((item) => item.id === current)) return current;
      return nextCollections[0].id;
    });
  }

  async function handleCreateCollection(event) {
    event.preventDefault();
    setSavingCollection(true);
    setError('');
    setMessage('');
    try {
      const payload = {
        ...createForm,
        name: createForm.name.trim(),
        display_name: createForm.display_name.trim(),
      };
      const res = await createRagCollection(payload);
      setCreateForm(defaultCollectionForm);
      await refreshCollections(res.data.id);
      setMessage(`Collection '${res.data.display_name}' created.`);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create collection.');
    } finally {
      setSavingCollection(false);
    }
  }

  async function handleUpdateCollection(event) {
    event.preventDefault();
    if (!selectedCollection) return;
    setSavingCollection(true);
    setError('');
    setMessage('');
    try {
      const payload = {
        display_name: collectionForm.display_name.trim(),
        description: collectionForm.description,
      };
      if (selectedCollection.rag_mode === 'lightrag') {
        // LightRAG collections don't use chunk/splitter settings
      } else {
        payload.default_chunk_size = Number(collectionForm.default_chunk_size);
        payload.default_chunk_overlap = Number(collectionForm.default_chunk_overlap);
        payload.default_splitter = collectionForm.default_splitter;
      }
      await updateRagCollection(selectedCollection.id, payload);
      await refreshCollections(selectedCollection.id);
      setMessage('Collection settings updated.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to update collection.');
    } finally {
      setSavingCollection(false);
    }
  }

  async function handleDeleteCollection() {
    if (!selectedCollection) return;
    const confirmed = window.confirm(`Delete collection '${selectedCollection.display_name}' and all ingested chunks?`);
    if (!confirmed) return;
    setError('');
    setMessage('');
    try {
      await deleteRagCollection(selectedCollection.id);
      await refreshCollections();
      setDocuments([]);
      setSearchResults([]);
      setMessage('Collection deleted.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to delete collection.');
    }
  }

  async function handleUploadDocument(event) {
    event.preventDefault();
    if (!selectedCollection || !uploadFile) return;
    setUploadingDocument(true);
    setError('');
    setMessage('');
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      if (documentUploadForm.chunk_size) formData.append('chunk_size', documentUploadForm.chunk_size);
      if (documentUploadForm.chunk_overlap) formData.append('chunk_overlap', documentUploadForm.chunk_overlap);
      if (documentUploadForm.splitter) formData.append('splitter', documentUploadForm.splitter);
      if (documentUploadForm.metadata.trim()) formData.append('metadata', documentUploadForm.metadata.trim());
      await uploadRagDocument(selectedCollection.id, formData);
      setUploadFile(null);
      setDocumentUploadForm(defaultDocumentUploadForm);
      await loadDocuments(selectedCollection.id);
      await refreshCollections(selectedCollection.id);
      setMessage('Document upload queued for ingestion.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to upload document.');
    } finally {
      setUploadingDocument(false);
    }
  }

  async function handleUploadUrl(event) {
    event.preventDefault();
    if (!selectedCollection || !webpageUploadForm.url.trim()) return;
    setUploadingWebpage(true);
    setError('');
    setMessage('');
    try {
      const metadata = webpageUploadForm.metadata.trim() ? JSON.parse(webpageUploadForm.metadata) : {};
      await uploadRagDocumentFromUrl(selectedCollection.id, {
        url: webpageUploadForm.url.trim(),
        fetch_mode: 'browser',
        chunk_size: webpageUploadForm.chunk_size ? Number(webpageUploadForm.chunk_size) : null,
        chunk_overlap: webpageUploadForm.chunk_overlap ? Number(webpageUploadForm.chunk_overlap) : null,
        splitter: webpageUploadForm.splitter || null,
        metadata,
      });
      setWebpageUploadForm(defaultWebpageUploadForm);
      await loadDocuments(selectedCollection.id);
      await refreshCollections(selectedCollection.id);
      setMessage('Webpage queued for ingestion.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to ingest webpage URL.');
    } finally {
      setUploadingWebpage(false);
    }
  }

  function openUrlModal() {
    setUrlDraft(webpageUploadForm.url || '');
    setUrlModalOpen(true);
  }

  function confirmUrlModal() {
    const nextUrl = urlDraft.trim();
    if (!nextUrl) return;
    setWebpageUploadForm((current) => ({ ...current, url: nextUrl }));
    setUrlModalOpen(false);
    setUrlDraft('');
  }

  function closeUrlModal() {
    setUrlModalOpen(false);
    setUrlDraft('');
  }

  async function handleDeleteDocument(documentId) {
    if (!selectedCollection) return;
    try {
      await deleteRagDocument(selectedCollection.id, documentId);
      await loadDocuments(selectedCollection.id);
      await refreshCollections(selectedCollection.id);
      setMessage('Document deleted.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to delete document.');
    }
  }

  function handleDocumentOverrideChange(documentId, field, value) {
    setDocumentOverrides((current) => ({
      ...current,
      [documentId]: {
        ...(current[documentId] || defaultDocumentOverride),
        [field]: value,
      },
    }));
  }

  function getEffectiveReingestConfig(documentId) {
    const override = documentOverrides[documentId] || defaultDocumentOverride;
    return {
      splitter: override.splitter || collectionForm.default_splitter,
      chunk_size: override.chunk_size ? Number(override.chunk_size) : Number(collectionForm.default_chunk_size),
      chunk_overlap: override.chunk_overlap ? Number(override.chunk_overlap) : Number(collectionForm.default_chunk_overlap),
    };
  }

  function getBatchReingestConfig() {
    return {
      splitter: collectionForm.default_splitter,
      chunk_size: Number(collectionForm.default_chunk_size),
      chunk_overlap: Number(collectionForm.default_chunk_overlap),
    };
  }

  async function handleReingestDocument(documentId) {
    if (!selectedCollection) return;
    try {
      const effective = getEffectiveReingestConfig(documentId);
      await reingestRagDocument(selectedCollection.id, documentId, {
        chunk_size: effective.chunk_size,
        chunk_overlap: effective.chunk_overlap,
        splitter: effective.splitter,
      });
      await loadDocuments(selectedCollection.id);
      setMessage('Document queued for re-ingestion.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to re-ingest document.');
    }
  }

  async function handleReingestAllDocuments() {
    if (!selectedCollection || documents.length === 0) return;
    try {
      const effective = getBatchReingestConfig();
      const res = await reingestAllRagDocuments(selectedCollection.id, {
        chunk_size: effective.chunk_size,
        chunk_overlap: effective.chunk_overlap,
        splitter: effective.splitter,
      });
      await loadDocuments(selectedCollection.id);
      setMessage(`${res.data.queued} document(s) queued for re-ingestion.`);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to re-ingest all documents.');
    }
  }

  async function handleSearch(event) {
    event.preventDefault();
    if (!selectedCollection) return;
    setSearching(true);
    setError('');
    try {
      const payload = {
        collection: selectedCollection.name,
        query: searchForm.query,
        top_k: Number(searchForm.top_k),
        score_threshold: Number(searchForm.score_threshold),
        filter: searchForm.filter.trim() ? JSON.parse(searchForm.filter) : {},
        ...(searchForm.mode ? { mode: searchForm.mode } : {}),
      };
      const res = await searchRag(payload);
      setSearchResults(res.data.results || []);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to search collection.');
    } finally {
      setSearching(false);
    }
  }

  async function handleToggleAccess(labId, entry) {
    if (!selectedCollection) return;
    setError('');
    setMessage('');
    try {
      if (!entry) {
        await grantLabRagAccess(labId, {
          collection_id: selectedCollection.id,
          can_read: true,
          can_write: false,
        });
      } else {
        await revokeLabRagAccess(labId, selectedCollection.id);
      }
      await loadAccess(selectedCollection.id);
      setMessage('Lab access updated.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to update lab access.');
    }
  }

  async function handleUpdateAccessFlag(labId, entry, field, value) {
    if (!selectedCollection || !entry) return;
    try {
      await updateLabRagAccess(labId, selectedCollection.id, { [field]: value });
      await loadAccess(selectedCollection.id);
      setMessage('Permissions updated.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to update permissions.');
    }
  }

  function toggleSection(section) {
    setExpandedSections((current) => ({ ...current, [section]: !current[section] }));
  }

  function expandAllSections() {
    setExpandedSections({
      createCollection: true,
      collectionSettings: true,
      documents: true,
      labAccess: true,
      searchPlayground: true,
    });
  }

  function collapseAllSections() {
    setExpandedSections({
      createCollection: false,
      collectionSettings: false,
      documents: false,
      labAccess: false,
      searchPlayground: false,
    });
  }

  function renderReingestSummary(documentId) {
    const effective = getEffectiveReingestConfig(documentId);
    return `Will use ${effective.splitter} · ${effective.chunk_size}/${effective.chunk_overlap}`;
  }

  return (
    <div>
      <div className="page-header" style={{ marginBottom: '1rem' }}>
        <div>
          <h1>RAG Collections</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Manage semantic-search collections, documents, lab access, and search testing.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button className="btn btn-outline" type="button" onClick={expandAllSections}>Expand All</button>
          <button className="btn btn-outline" type="button" onClick={collapseAllSections}>Collapse All</button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderColor: 'rgba(239,68,68,0.4)', color: 'var(--error)' }}>
          {error}
        </div>
      )}
      {message && (
        <div className="card" style={{ borderColor: 'rgba(34,197,94,0.4)', color: 'var(--success)' }}>
          {message}
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: '320px minmax(0, 1fr)', alignItems: 'start' }}>
        <div className="card">
          <div className="card-header">
            <h2>Collections</h2>
          </div>

          <div className="rag-subsection" style={{ marginBottom: '1rem' }}>
            <div className="card-header" style={{ marginBottom: expandedSections.createCollection ? '1rem' : 0 }}>
              <h3>Create Collection</h3>
              <SectionToggle expanded={expandedSections.createCollection} onToggle={() => toggleSection('createCollection')} />
            </div>
            {expandedSections.createCollection && (
              <form onSubmit={handleCreateCollection} style={{ display: 'grid', gap: '0.65rem' }}>
                <input
                  value={createForm.name}
                  onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="internal_name"
                />
                <input
                  value={createForm.display_name}
                  onChange={(event) => setCreateForm((current) => ({ ...current, display_name: event.target.value }))}
                  placeholder="Display name"
                />
                <textarea
                  value={createForm.description}
                  onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))}
                  rows={3}
                  placeholder="Description"
                />
                <select
                  value={createForm.embedding_model}
                  onChange={(event) => setCreateForm((current) => ({ ...current, embedding_model: event.target.value }))}
                >
                  {embeddingModelOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label} ({option.dimension}d)
                    </option>
                  ))}
                </select>
                <div className="grid grid-2">
                  <input
                    type="number"
                    min="64"
                    max="4096"
                    value={createForm.default_chunk_size}
                    onChange={(event) => setCreateForm((current) => ({ ...current, default_chunk_size: event.target.value }))}
                    placeholder="Chunk size"
                  />
                  <input
                    type="number"
                    min="0"
                    max="512"
                    value={createForm.default_chunk_overlap}
                    onChange={(event) => setCreateForm((current) => ({ ...current, default_chunk_overlap: event.target.value }))}
                    placeholder="Overlap"
                  />
                </div>
                <select
                  value={createForm.default_splitter}
                  onChange={(event) => setCreateForm((current) => ({ ...current, default_splitter: event.target.value }))}
                >
                  {splitterOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
                <div style={{ display: 'grid', gap: '0.5rem' }}>
                  <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>RAG Mode</label>
                  <select
                    value={createForm.rag_mode}
                    onChange={(event) => setCreateForm((current) => ({ ...current, rag_mode: event.target.value }))}
                  >
                    <option value="vector">Vector (standard)</option>
                    <option value="lightrag">LightRAG (graph-enhanced)</option>
                  </select>
                </div>
                {createForm.rag_mode === 'lightrag' && (
                  <>
                    <div style={{ display: 'grid', gap: '0.5rem' }}>
                      <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>LLM Model (entity extraction)</label>
                      <select
                        value={createForm.lightrag_model_id}
                        onChange={(event) => setCreateForm((current) => ({ ...current, lightrag_model_id: event.target.value }))}
                      >
                        <option value="">Select a model...</option>
                        {aiModels.map((model) => (
                          <option key={model.id} value={model.id}>
                            {model.name} ({model.model_identifier})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div style={{ display: 'grid', gap: '0.5rem' }}>
                      <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Default Search Mode</label>
                      <select
                        value={createForm.lightrag_search_mode}
                        onChange={(event) => setCreateForm((current) => ({ ...current, lightrag_search_mode: event.target.value }))}
                      >
                        <option value="local">Local (vector only)</option>
                        <option value="global">Global (graph traversal)</option>
                        <option value="hybrid">Hybrid (recommended)</option>
                      </select>
                    </div>
                  </>
                )}
                <button className="btn btn-primary" type="submit" disabled={savingCollection || !createForm.name.trim() || !createForm.display_name.trim()}>
                  {savingCollection ? 'Saving...' : 'Create Collection'}
                </button>
              </form>
            )}
          </div>

          <div style={{ display: 'grid', gap: '0.75rem' }}>
            {loading && <div style={{ color: 'var(--text-muted)' }}>Loading collections...</div>}
            {!loading && collections.length === 0 && (
              <div style={{ color: 'var(--text-muted)' }}>No collections yet.</div>
            )}
            {collections.map((collection) => {
              const active = collection.id === selectedId;
              return (
                <button
                  key={collection.id}
                  type="button"
                  onClick={() => setSelectedId(collection.id)}
                  style={{
                    textAlign: 'left',
                    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                    background: active ? 'rgba(185,28,28,0.12)' : 'var(--bg-primary)',
                    color: 'var(--text-primary)',
                    borderRadius: 'var(--radius)',
                    padding: '0.85rem',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <strong>{collection.display_name}</strong>
                      {collection.rag_mode === 'lightrag' && (
                        <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: '4px', background: 'rgba(139,92,246,0.15)', color: '#a78bfa', fontWeight: 600 }}>LightRAG</span>
                      )}
                    </span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{collection.name}</span>
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.35rem' }}>
                    {collection.description || 'No description.'}
                  </div>
                  <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.6rem', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                    <span>{collection.document_count} docs</span>
                    <span>{collection.chunk_count} chunks</span>
                    <span>{formatBytes(collection.total_size_bytes)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'grid', gap: '1rem' }}>
          {!selectedCollection && (
            <div className="card">
              <h2>Select a collection</h2>
              <p style={{ color: 'var(--text-secondary)', marginTop: '0.4rem' }}>
                Choose a collection on the left to manage documents, permissions, and search.
              </p>
            </div>
          )}

          {selectedCollection && (
            <>
              <form className="card" onSubmit={handleUpdateCollection}>
                <div className="card-header">
                  <h2>Collection Settings</h2>
                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <SectionToggle expanded={expandedSections.collectionSettings} onToggle={() => toggleSection('collectionSettings')} />
                    <button className="btn btn-outline" type="button" onClick={() => setShareTarget(selectedCollection)}>👥 Share</button>
                    <button className="btn btn-danger" type="button" onClick={handleDeleteCollection}>Delete</button>
                  </div>
                </div>
                {expandedSections.collectionSettings && (
                <>
                <div className="grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.75rem' }}>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Internal name</label>
                    <input value={collectionForm.name} disabled />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Display name</label>
                    <input
                      value={collectionForm.display_name}
                      onChange={(event) => setCollectionForm((current) => ({ ...current, display_name: event.target.value }))}
                    />
                  </div>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Description</label>
                    <textarea
                      value={collectionForm.description}
                      rows={3}
                      onChange={(event) => setCollectionForm((current) => ({ ...current, description: event.target.value }))}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>RAG Mode</label>
                    <input value={selectedCollection.rag_mode === 'lightrag' ? 'LightRAG (graph-enhanced)' : 'Vector (standard)'} disabled />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Embedding</label>
                    <input value={`${selectedCollection.embedding_model} (${selectedCollection.embedding_dim}d)`} disabled />
                  </div>
                  {selectedCollection.rag_mode === 'lightrag' ? (
                    <>
                      <div>
                        <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>LLM Model (entity extraction)</label>
                        <input value={(() => { const m = aiModels.find(m => m.id === selectedCollection.lightrag_model_id); return m ? `${m.name} (${m.model_identifier})` : selectedCollection.lightrag_model_id || 'Not set'; })()} disabled />
                      </div>
                      <div>
                        <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Default Search Mode</label>
                        <input value={selectedCollection.lightrag_search_mode || 'hybrid'} disabled />
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Chunk size</label>
                        <input
                          type="number"
                          min="64"
                          max="4096"
                          value={collectionForm.default_chunk_size}
                          onChange={(event) => setCollectionForm((current) => ({ ...current, default_chunk_size: event.target.value }))}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Chunk overlap</label>
                        <input
                          type="number"
                          min="0"
                          max="512"
                          value={collectionForm.default_chunk_overlap}
                          onChange={(event) => setCollectionForm((current) => ({ ...current, default_chunk_overlap: event.target.value }))}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', marginBottom: '0.35rem', color: 'var(--text-muted)' }}>Splitter</label>
                        <select
                          value={collectionForm.default_splitter}
                          onChange={(event) => setCollectionForm((current) => ({ ...current, default_splitter: event.target.value }))}
                        >
                          {splitterOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </div>
                    </>
                  )}
                </div>
                <div style={{ marginTop: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                  <button className="btn btn-primary" type="submit" disabled={savingCollection}>
                    {savingCollection ? 'Saving...' : 'Save Settings'}
                  </button>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                    {selectedCollection.document_count} documents{selectedCollection.rag_mode !== 'lightrag' && <>, {selectedCollection.chunk_count} chunks</>}, {formatBytes(selectedCollection.total_size_bytes)}
                  </span>
                </div>
                </>
                )}
              </form>

              <div className="card">
                <div className="card-header">
                  <h2>Documents</h2>
                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <SectionToggle expanded={expandedSections.documents} onToggle={() => toggleSection('documents')} />
                    <button
                      className="btn btn-outline"
                      type="button"
                      onClick={handleReingestAllDocuments}
                      disabled={documents.length === 0}
                    >
                      Re-ingest All
                    </button>
                  </div>
                </div>
                {expandedSections.documents && (
                <>
                <div className="rag-upload-dual" style={{ marginBottom: '1rem' }}>
                  <form className="rag-upload-panel" onSubmit={handleUploadDocument}>
                    <div className="rag-upload-panel-header">
                      <h3>Documents</h3>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      style={{ display: 'none' }}
                      onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
                    />
                    <div className="rag-picker-stack">
                      <div className="rag-upload-picker">
                        <button
                          className="rag-upload-picker-button"
                          type="button"
                          onClick={() => fileInputRef.current?.click()}
                          aria-label="Choose file"
                        >
                          +
                        </button>
                        <div className="rag-upload-picker-label">
                          {uploadFile ? uploadFile.name : 'Choose a document to upload'}
                        </div>
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={!uploadFile || uploadingDocument}>
                        {uploadingDocument ? 'Uploading...' : 'Upload Document'}
                      </button>
                    </div>
                    {selectedCollection.rag_mode !== 'lightrag' && (
                    <UploadConfigFields
                      form={documentUploadForm}
                      setForm={setDocumentUploadForm}
                      selectedCollection={selectedCollection}
                    />
                    )}
                  </form>

                  <form className="rag-upload-panel" onSubmit={handleUploadUrl}>
                    <div className="rag-upload-panel-header">
                      <h3>Webpages</h3>
                    </div>
                    <div className="rag-picker-stack">
                      <div className="rag-upload-picker">
                        <button
                          className="rag-upload-picker-button"
                          type="button"
                          onClick={openUrlModal}
                          aria-label="Add a URL"
                        >
                          +
                        </button>
                        <div className="rag-upload-picker-label">
                          {webpageUploadForm.url || 'Add a URL'}
                        </div>
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={!webpageUploadForm.url.trim() || uploadingWebpage}>
                        {uploadingWebpage ? 'Fetching...' : 'Ingest Webpage URL'}
                      </button>
                    </div>
                    {selectedCollection.rag_mode !== 'lightrag' && (
                    <UploadConfigFields
                      form={webpageUploadForm}
                      setForm={setWebpageUploadForm}
                      selectedCollection={selectedCollection}
                    />
                    )}
                    <div className="rag-upload-helper">
                      Browser-rendered fetch is used first for webpage ingestion, then it falls back to direct HTTP extraction if rendering fails.
                    </div>
                  </form>
                </div>

                {selectedCollection.rag_mode !== 'lightrag' && (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                  Re-ingest all will use {getBatchReingestConfig().splitter} with {getBatchReingestConfig().chunk_size}/{getBatchReingestConfig().chunk_overlap}.
                </div>
                )}
                {selectedCollection.rag_mode === 'lightrag' && (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                  LightRAG handles chunking and entity extraction internally using the collection's LLM model via the load balancer.
                </div>
                )}

                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>File</th>
                        <th>Status</th>
                        {selectedCollection.rag_mode !== 'lightrag' && <th>Chunks</th>}
                        {selectedCollection.rag_mode !== 'lightrag' && <th>Config</th>}
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.length === 0 && (
                        <tr>
                          <td colSpan={selectedCollection.rag_mode === 'lightrag' ? 3 : 5} style={{ color: 'var(--text-muted)' }}>No documents in this collection.</td>
                        </tr>
                      )}
                      {documents.map((document) => (
                        <tr key={document.id}>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                              <span>{document.filename}</span>
                              <SourceBadge document={document} />
                            </div>
                            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{formatBytes(document.size_bytes)}</div>
                            {document.metadata?.source_url && (
                              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', overflowWrap: 'anywhere' }}>
                                {document.metadata.source_url}
                              </div>
                            )}
                          </td>
                          <td>
                            <StatusBadge status={document.status} />
                            {document.error_message && (
                              <div style={{ color: 'var(--error)', fontSize: '0.75rem', marginTop: '0.35rem' }}>{document.error_message}</div>
                            )}
                          </td>
                          {selectedCollection.rag_mode !== 'lightrag' && <td>{document.chunk_count}</td>}
                          {selectedCollection.rag_mode !== 'lightrag' && (
                          <td>
                            <div style={{ marginBottom: '0.35rem' }}>{document.splitter} {document.chunk_size}/{document.chunk_overlap}</div>
                            <div className="rag-inline-reingest-controls">
                              <select
                                value={(documentOverrides[document.id] || defaultDocumentOverride).splitter}
                                onChange={(event) => handleDocumentOverrideChange(document.id, 'splitter', event.target.value)}
                              >
                                <option value="">Collection default ({collectionForm.default_splitter})</option>
                                {splitterOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                              </select>
                              <input
                                type="number"
                                min="64"
                                max="4096"
                                placeholder={`${collectionForm.default_chunk_size}`}
                                value={(documentOverrides[document.id] || defaultDocumentOverride).chunk_size}
                                onChange={(event) => handleDocumentOverrideChange(document.id, 'chunk_size', event.target.value)}
                              />
                              <input
                                type="number"
                                min="0"
                                max="512"
                                placeholder={`${collectionForm.default_chunk_overlap}`}
                                value={(documentOverrides[document.id] || defaultDocumentOverride).chunk_overlap}
                                onChange={(event) => handleDocumentOverrideChange(document.id, 'chunk_overlap', event.target.value)}
                              />
                            </div>
                            <div className="rag-reingest-summary">{renderReingestSummary(document.id)}</div>
                          </td>
                          )}
                          <td>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                              <button className="btn btn-outline" type="button" onClick={() => handleReingestDocument(document.id)}>Re-ingest</button>
                              <button className="btn btn-outline" type="button" onClick={() => handleDeleteDocument(document.id)}>Delete</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
                )}
              </div>

              <div className="card">
                <div className="card-header">
                  <h2>Lab Access</h2>
                  <SectionToggle expanded={expandedSections.labAccess} onToggle={() => toggleSection('labAccess')} />
                </div>
                {expandedSections.labAccess && (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Lab</th>
                        <th>Linked</th>
                        <th>Read</th>
                        <th>Write</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {labs.length === 0 && (
                        <tr>
                          <td colSpan="5" style={{ color: 'var(--text-muted)' }}>No labs available.</td>
                        </tr>
                      )}
                      {labs.map((lab) => {
                        const entry = accessMap[lab.id];
                        return (
                          <tr key={lab.id}>
                            <td>
                              <div>{lab.name}</div>
                              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{lab.status}</div>
                            </td>
                            <td>{entry ? 'Yes' : 'No'}</td>
                            <td>
                              <input
                                type="checkbox"
                                checked={!!entry?.can_read}
                                disabled={!entry}
                                onChange={(event) => handleUpdateAccessFlag(lab.id, entry, 'can_read', event.target.checked)}
                              />
                            </td>
                            <td>
                              <input
                                type="checkbox"
                                checked={!!entry?.can_write}
                                disabled={!entry}
                                onChange={(event) => handleUpdateAccessFlag(lab.id, entry, 'can_write', event.target.checked)}
                              />
                            </td>
                            <td>
                              <button className="btn btn-outline" type="button" onClick={() => handleToggleAccess(lab.id, entry)}>
                                {entry ? 'Unlink' : 'Link'}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                )}
              </div>

              <div className="card">
                <div className="card-header">
                  <h2>Search Playground</h2>
                  <SectionToggle expanded={expandedSections.searchPlayground} onToggle={() => toggleSection('searchPlayground')} />
                </div>
                {expandedSections.searchPlayground && (
                <>
                <form onSubmit={handleSearch} style={{ display: 'grid', gap: '0.75rem' }}>
                  <textarea
                    rows={3}
                    value={searchForm.query}
                    onChange={(event) => setSearchForm((current) => ({ ...current, query: event.target.value }))}
                    placeholder="Ask a semantic question about this collection"
                  />
                  <div className="grid grid-3">
                    <input
                      type="number"
                      min="1"
                      max="20"
                      value={searchForm.top_k}
                      onChange={(event) => setSearchForm((current) => ({ ...current, top_k: event.target.value }))}
                    />
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      value={searchForm.score_threshold}
                      onChange={(event) => setSearchForm((current) => ({ ...current, score_threshold: event.target.value }))}
                    />
                    <button className="btn btn-primary" type="submit" disabled={searching || !searchForm.query.trim()}>
                      {searching ? 'Searching...' : 'Search'}
                    </button>
                  </div>
                  {selectedCollection?.rag_mode === 'lightrag' && (
                    <select
                      value={searchForm.mode}
                      onChange={(event) => setSearchForm((current) => ({ ...current, mode: event.target.value }))}
                      style={{ marginTop: '-0.25rem' }}
                    >
                      <option value="">Default (collection setting)</option>
                      <option value="local">Local (vector)</option>
                      <option value="global">Global (graph)</option>
                      <option value="hybrid">Hybrid</option>
                    </select>
                  )}
                  <textarea
                    rows={2}
                    value={searchForm.filter}
                    onChange={(event) => setSearchForm((current) => ({ ...current, filter: event.target.value }))}
                    placeholder='Optional metadata filter JSON, for example {"category":"ops"}'
                  />
                </form>

                <div style={{ marginTop: '1rem', display: 'grid', gap: '0.75rem' }}>
                  {searchResults.length === 0 && (
                    <div style={{ color: 'var(--text-muted)' }}>No results yet.</div>
                  )}
                  {searchResults.map((result, index) => (
                    <div key={`${result.document_id}-${result.chunk}-${index}`} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.9rem', background: 'var(--bg-primary)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <strong>{result.source}</strong>
                        {result.source === 'lightrag' ? (
                          <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: '4px', background: 'rgba(139,92,246,0.15)', color: '#a78bfa', fontWeight: 600 }}>
                            {result.metadata?.mode || 'hybrid'}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>score {result.score.toFixed(3)} · chunk {result.chunk}</span>
                        )}
                      </div>
                      <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}><HighlightText text={result.text} query={searchForm.query} /></div>
                      {result.metadata && Object.keys(result.metadata).length > 0 && result.source !== 'lightrag' && (
                        <pre style={{ marginTop: '0.6rem', color: 'var(--text-muted)', fontSize: '0.75rem', overflowX: 'auto' }}>
                          {JSON.stringify(result.metadata, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
                </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {urlModalOpen && (
        <div className="rag-modal-backdrop" role="dialog" aria-modal="true">
          <div className="rag-modal">
            <h3>Add Webpage URL</h3>
            <input
              type="url"
              placeholder="https://example.com/article"
              value={urlDraft}
              onChange={(event) => setUrlDraft(event.target.value)}
              autoFocus
            />
            <div className="rag-modal-actions">
              <button className="btn btn-outline" type="button" onClick={closeUrlModal}>Cancel</button>
              <button className="btn btn-primary" type="button" onClick={confirmUrlModal} disabled={!urlDraft.trim()}>OK</button>
            </div>
          </div>
        </div>
      )}
      {shareTarget && (
        <ShareModal
          resourceType="rag_collection"
          resourceId={shareTarget.id}
          acl={shareTarget.acl}
          onClose={() => setShareTarget(null)}
          onUpdated={() => loadInitialData()}
        />
      )}
    </div>
  );
}