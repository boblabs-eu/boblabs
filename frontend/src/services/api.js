/**
 * Bob Manager — API service layer.
 * Centralizes all HTTP calls to the control plane.
 */

import axios from 'axios';

import { handleUnauthorized } from '../context/AuthContext';

const API_BASE = process.env.REACT_APP_API_URL || '';

const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
});

// Inject JWT token if present
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('bob_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// U03 — global 401 interceptor. Pre-fix, an expired token surfaced as
// a page-level "Failed to load" error and the user had to manually
// hit the logout button before the login redirect kicked in. Now a
// 401 from anywhere triggers the auth context's logout, which clears
// the JWT and lets the route guards bounce to the login screen. The
// 401 still propagates back to the caller so per-page error UIs can
// render their own message if they want.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      handleUnauthorized();
    }
    return Promise.reject(error);
  },
);

// ─── Auth ──────────────────────────────────────────
export const getToken = (secret) => api.post('/auth/token', { secret });

// ─── Public (no auth) ──────────────────────────────
export const validateAccessToken = (token) => api.post('/public/validate-token', { token });
export const submitTrialRequest = (data) => api.post('/public/trial-request', data);
export const submitQuoteRequest = (data) => api.post('/public/quote-request', data);

// ─── Public Live (no auth) ────────────────────────
const pubApi = axios.create({ baseURL: `${API_BASE}/api/v1` });
export const getLiveLabs = () => pubApi.get('/public/live/labs');
export const getLiveLabDetail = (id) => pubApi.get(`/public/live/labs/${id}`);
export const getLiveLabMessages = (id, limit = 100) =>
  pubApi.get(`/public/live/labs/${id}/messages`, { params: { limit } });
export const getLiveLabResources = (id) => pubApi.get(`/public/live/labs/${id}/resources`);
export const getLiveServers = () => pubApi.get('/public/live/servers');
export const getLiveProviders = () => pubApi.get('/public/live/providers');
export const getPublicLiveModels = () => pubApi.get('/public/live/models');
export const getLiveMetrics = () => pubApi.get('/metrics');
export const getLiveResourceContent = (labId, rid) =>
  pubApi.get(`/public/live/labs/${labId}/resources/${rid}/content`);
export const getLiveResourceDownloadUrl = (labId, rid) =>
  `${API_BASE}/api/v1/public/live/labs/${labId}/resources/${rid}/download`;
export const getLiveOutputContent = (labId, path) =>
  pubApi.get(`/public/live/labs/${labId}/output-files/content`, { params: { path } });
export const getLiveOutputDownloadUrl = (labId, path) =>
  `${API_BASE}/api/v1/public/live/labs/${labId}/output-files/download?path=${encodeURIComponent(path)}`;
export const getLiveFileBlob = (url) =>
  pubApi.get(url.replace(`${API_BASE}/api/v1`, ''), { responseType: 'blob' });

// ─── Access Tokens (admin) ─────────────────────────
export const getAccessTokens = () => api.get('/access-tokens');
export const createAccessToken = (data) => api.post('/access-tokens', data);
export const revokeAccessToken = (id) => api.delete(`/access-tokens/${id}`);
export const getTrialRequests = () => api.get('/access-tokens/trial-requests');
export const updateTrialRequestStatus = (id, status) =>
  api.patch(`/access-tokens/trial-requests/${id}`, { status });

// ─── Quote Requests (admin) ────────────────────────
export const getQuoteRequests = () => api.get('/access-tokens/quote-requests');
export const updateQuoteRequestStatus = (id, status) =>
  api.patch(`/access-tokens/quote-requests/${id}`, { status });

// ─── Blog (public read) ───────────────────────────
export const getBlogPosts = (limit = 50, offset = 0) =>
  axios.get(`${API_BASE}/api/v1/public/blog`, { params: { limit, offset } });
export const getBlogPost = (id) =>
  axios.get(`${API_BASE}/api/v1/public/blog/${id}`);
export const getBlogPostBySlug = (slug) =>
  axios.get(`${API_BASE}/api/v1/public/blog/by-slug/${slug}`);

// ─── Blog Tokens & Posts (admin) ──────────────────
export const getBlogTokens = () => api.get('/access-tokens/blog-tokens');
export const createBlogToken = (label) => api.post('/access-tokens/blog-tokens', { label });
export const revokeBlogToken = (id) => api.delete(`/access-tokens/blog-tokens/${id}`);
export const getBlogPostsAdmin = () => api.get('/access-tokens/blog-posts');
export const deleteBlogPost = (id) => api.delete(`/access-tokens/blog-posts/${id}`);

// ─── Consumer Apps (admin) ────────────────────────
// HMAC-authenticated private apps that drive bob-api over the internal channel.
// Creating a new app returns the HMAC secret once and only once.
export const getConsumerApps = () => api.get('/admin/consumer-apps');
export const createConsumerApp = (data) =>
  api.post('/admin/consumer-apps', data);
export const revokeConsumerApp = (id) =>
  api.delete(`/admin/consumer-apps/${id}`);
export const deleteConsumerApp = (id) =>
  api.delete(`/admin/consumer-apps/${id}/permanent`);

// ─── Servers ───────────────────────────────────────
export const getServers = () => api.get('/servers');
export const getServer = (id) => api.get(`/servers/${id}`);
export const createServer = (data) => api.post('/servers', data);
export const updateServer = (id, data) => api.put(`/servers/${id}`, data);
export const deleteServer = (id) => api.delete(`/servers/${id}`);

export const getServerMetrics = (id) => api.get(`/servers/${id}/metrics`);
export const getServerProcesses = (id) => api.get(`/servers/${id}/processes`);
export const getServerServices = (id) => api.get(`/servers/${id}/services`);
export const getServerCrontabs = (id) => api.get(`/servers/${id}/crontabs`);
export const getServerPorts = (id) => api.get(`/servers/${id}/ports`);
export const getServerFirewall = (id) => api.get(`/servers/${id}/firewall`);

// ─── Commands ──────────────────────────────────────
export const executeCommand = (serverId, command) =>
  api.post(`/commands/servers/${serverId}`, { command });

export const executeBatchCommand = (serverIds, command) =>
  api.post('/commands/batch', { server_ids: serverIds, command });

export const getCommandHistory = (serverId) =>
  api.get(`/commands/servers/${serverId}/history`);

// ─── Workflows ─────────────────────────────────────
export const getWorkflows = () => api.get('/workflows');
export const getWorkflow = (id) => api.get(`/workflows/${id}`);
export const createWorkflow = (data) => api.post('/workflows', data);
export const updateWorkflow = (id, data) => api.put(`/workflows/${id}`, data);
export const deleteWorkflow = (id) => api.delete(`/workflows/${id}`);
export const executeWorkflow = (id, serverIds) =>
  api.post(`/workflows/${id}/execute`, { server_ids: serverIds });
export const getWorkflowExecutions = (id) => api.get(`/workflows/${id}/executions`);

// ─── Projects ──────────────────────────────────────
export const getProjects = () => api.get('/projects');
export const getProject = (id) => api.get(`/projects/${id}`);
export const createProject = (data) => api.post('/projects', data);
export const updateProject = (id, data) => api.put(`/projects/${id}`, data);
export const deleteProject = (id) => api.delete(`/projects/${id}`);
export const getProjectThemes = () => api.get('/projects/themes');
export const renameProjectTheme = (oldName, newName) =>
  api.post('/projects/themes/rename', { old_name: oldName, new_name: newName });
export const setThemeColor = (themeName, color) =>
  api.put(`/projects/themes/${encodeURIComponent(themeName)}/color`, { color });

// ─── Modules ───────────────────────────────────────
export const getModules = (projectId) =>
  api.get(`/projects/${projectId}/modules`);
export const createModule = (projectId, data) =>
  api.post(`/projects/${projectId}/modules`, data);
export const updateModule = (projectId, moduleId, data) =>
  api.put(`/projects/${projectId}/modules/${moduleId}`, data);
export const deleteModule = (projectId, moduleId) =>
  api.delete(`/projects/${projectId}/modules/${moduleId}`);

// ─── Module Steps ──────────────────────────────────
export const getSteps = (projectId, moduleId) =>
  api.get(`/projects/${projectId}/modules/${moduleId}/steps`);
export const createStep = (projectId, moduleId, data) =>
  api.post(`/projects/${projectId}/modules/${moduleId}/steps`, data);
export const updateStep = (projectId, moduleId, stepId, data) =>
  api.put(`/projects/${projectId}/modules/${moduleId}/steps/${stepId}`, data);
export const deleteStep = (projectId, moduleId, stepId) =>
  api.delete(`/projects/${projectId}/modules/${moduleId}/steps/${stepId}`);

// ─── Module Tasks ──────────────────────────────────
export const getTasks = (projectId, moduleId) =>
  api.get(`/projects/${projectId}/modules/${moduleId}/tasks`);
export const createTask = (projectId, moduleId, data) =>
  api.post(`/projects/${projectId}/modules/${moduleId}/tasks`, data);
export const updateTask = (projectId, moduleId, taskId, data) =>
  api.put(`/projects/${projectId}/modules/${moduleId}/tasks/${taskId}`, data);
export const deleteTask = (projectId, moduleId, taskId) =>
  api.delete(`/projects/${projectId}/modules/${moduleId}/tasks/${taskId}`);

// ─── Resources ─────────────────────────────────────
export const getResources = () => api.get('/resources');
export const getResource = (id) => api.get(`/resources/${id}`);
export const createResource = (data) => api.post('/resources', data);
export const updateResource = (id, data) => api.put(`/resources/${id}`, data);
export const deleteResource = (id) => api.delete(`/resources/${id}`);
export const getResourceProjects = (id) => api.get(`/resources/${id}/projects`);
export const linkResourceProject = (resourceId, projectId) =>
  api.post(`/resources/${resourceId}/projects`, { project_id: projectId });
export const unlinkResourceProject = (resourceId, projectId) =>
  api.delete(`/resources/${resourceId}/projects/${projectId}`);
export const getProjectResources = (projectId) =>
  api.get(`/projects/${projectId}/resources`);

// ─── Metrics ───────────────────────────────────────
export const getAllMetrics = () => api.get('/metrics');
// ─── News ──────────────────────────────────────
export const getNews = (category, limit = 50) => {
  const params = {};
  if (category) params.category = category;
  if (limit) params.limit = limit;
  return api.get('/news/', { params });
};
export const getNewsSources = () => api.get('/news/sources');

// ─── Web3 ──────────────────────────────────────
export const getCryptoPrices = () => api.get('/web3/prices');
export const getPortfolioValue = () => api.get('/web3/portfolio');
export const getWallets = () => api.get('/web3/wallets');
export const addWallet = (address, label = '') =>
  api.post('/web3/wallets', { address, label });
export const removeWallet = (id) => api.delete(`/web3/wallets/${id}`);
export const getWalletBalances = (id) => api.get(`/web3/wallets/${id}/balances`);
export const getWalletTransactions = (id, chain = 'ethereum') =>
  api.get(`/web3/wallets/${id}/transactions`, { params: { chain } });
export const getLabWeb3Access = (labId) => api.get(`/labs/${labId}/web3-access`);
export const getLabWeb3Candidates = (labId) => api.get(`/labs/${labId}/web3-access/candidates`);
export const grantLabWeb3Access = (labId, walletIds) => api.post(`/labs/${labId}/web3-access`, { wallet_ids: walletIds });
export const revokeLabWeb3Access = (labId, walletId) => api.delete(`/labs/${labId}/web3-access/${walletId}`);

// Server access (control_server tool)
export const getLabServerAccess = (labId) => api.get(`/labs/${labId}/server-access`);
export const getLabServerCandidates = (labId) => api.get(`/labs/${labId}/server-access/candidates`);
export const grantLabServerAccess = (labId, serverIds) => api.post(`/labs/${labId}/server-access`, { server_ids: serverIds });
export const revokeLabServerAccess = (labId, serverId) => api.delete(`/labs/${labId}/server-access/${serverId}`);

export const getWeb3Settings = () => api.get('/web3/settings');
export const updateWeb3Settings = (data) => api.put('/web3/settings', data);
export const getPortfolioHistory = (walletId, hours = 24) => {
  const params = { hours };
  if (walletId) params.wallet_id = walletId;
  return api.get('/web3/portfolio/history', { params });
};
export const triggerSnapshot = () => api.post('/web3/portfolio/snapshot');

// ─── AI Orchestrator ───────────────────────────────
export const getOrchestratorSettings = () => api.get('/orchestrator/settings');
export const updateOrchestratorSettings = (data) => api.put('/orchestrator/settings', data);

export const getAIProviders = () => api.get('/orchestrator/providers');
export const getAIProviderTypes = () => api.get('/orchestrator/providers/types');
export const createAIProvider = (data) => api.post('/orchestrator/providers', data);
export const updateAIProvider = (id, data) => api.put(`/orchestrator/providers/${id}`, data);
export const deleteAIProvider = (id) => api.delete(`/orchestrator/providers/${id}`);
export const testAIProvider = (id) => api.post(`/orchestrator/providers/${id}/test`);

export const getAIModels = (providerId) => {
  const params = {};
  if (providerId) params.provider_id = providerId;
  return api.get('/orchestrator/models', { params });
};
export const getUniqueModels = () => api.get('/orchestrator/models/unique');
export const getLiveModels = () => api.get('/orchestrator/models/live');
export const syncAllModels = () => api.post('/orchestrator/models/sync');

export const getPipelines = () => api.get('/orchestrator/pipelines');
export const getBuiltinTools = () => api.get('/orchestrator/builtin-tools');

export const getLlmEvents = (params = {}) => api.get('/orchestrator/llm-events', { params });
export const getLlmEventDetail = (eventId) => api.get(`/orchestrator/llm-events/${eventId}`);
export const getLlmEventStats = (params = {}) => api.get('/orchestrator/llm-events/stats', { params });

export const getAIAgents = () => api.get('/orchestrator/agents');
export const createAIAgent = (data) => api.post('/orchestrator/agents', data);
export const updateAIAgent = (id, data) => api.put(`/orchestrator/agents/${id}`, data);
export const deleteAIAgent = (id) => api.delete(`/orchestrator/agents/${id}`);

export const getConversations = () => api.get('/orchestrator/conversations');
export const createConversation = (data = {}) => api.post('/orchestrator/conversations', data);
export const updateConversation = (id, data) => api.put(`/orchestrator/conversations/${id}`, data);
export const deleteConversation = (id) => api.delete(`/orchestrator/conversations/${id}`);
export const getMessages = (convId, limit = 200) =>
  api.get(`/orchestrator/conversations/${convId}/messages`, { params: { limit } });

export const getOrchestratorTasks = (convId) => {
  const params = {};
  if (convId) params.conversation_id = convId;
  return api.get('/orchestrator/tasks', { params });
};
export const getActivity = (convId, limit = 100) => {
  const params = { limit };
  if (convId) params.conversation_id = convId;
  return api.get('/orchestrator/activity', { params });
};

/**
 * Send a message and consume SSE streaming response.
 * @param {string} convId - Conversation UUID
 * @param {string} content - Message text
 * @param {function} onToken - Callback for each token chunk
 * @param {function} onDone - Callback when complete
 * @param {function} onError - Callback on error
 */
export const sendMessage = async (convId, content, onToken, onDone, onError, model, images, contextMode, onAudio, agentId, onToolEvent, tools) => {
  try {
    const body = { content };
    if (model) body.model = model;
    if (images && images.length) body.images = images;
    if (contextMode) body.context_mode = contextMode;
    if (agentId) body.agent_id = agentId;
    if (tools && tools.length) body.tools = tools;
    const response = await fetch(`${API_BASE}/api/v1/orchestrator/conversations/${convId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(localStorage.getItem('bob_token')
          ? { Authorization: `Bearer ${localStorage.getItem('bob_token')}` }
          : {}),
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.done) {
              onDone?.(data);
            } else if (data.tool_call || data.tool_result) {
              onToolEvent?.(data);
            } else if (data.audio || data.video) {
              onAudio?.(data);
              onToken?.(data.token || '');
            } else {
              onToken?.(data.token);
            }
          } catch { /* skip malformed */ }
        }
      }
    }
  } catch (err) {
    onError?.(err);
  }
};

// ─── Labs ──────────────────────────────────────────
export const getLabs = () => api.get('/labs');
export const createLab = (data) => api.post('/labs', data);
export const getLab = (id) => api.get(`/labs/${id}`);
export const updateLab = (id, data) => api.patch(`/labs/${id}`, data);
export const deleteLab = (id) => api.delete(`/labs/${id}`);
export const duplicateLab = (id) => api.post(`/labs/${id}/duplicate`);
export const exportLab = (id) => api.get(`/labs/${id}/export`);
export const importLab = (blueprint) => api.post('/labs/import', blueprint);
export const runLab = (id, { reset = false } = {}) => api.post(`/labs/${id}/run?reset=${reset}`);
export const resetLab = (id) => api.post(`/labs/${id}/reset`);
export const pauseLab = (id) => api.post(`/labs/${id}/pause`);
export const resumeLab = (id) => api.post(`/labs/${id}/resume`);
export const stopLab = (id) => api.post(`/labs/${id}/stop`);
export const injectLabMessage = (id, data) => api.post(`/labs/${id}/inject`, data);
export const getStrategyPrompt = (loopType) => api.get(`/labs/strategy-prompts/${loopType}`);
export const getLoopStrategies = () => api.get('/labs/strategies');

export const getLabAgents = (labId) => api.get(`/labs/${labId}/agents`);
export const getAgentLibrary = () => api.get('/labs/agents/library');
export const createLabAgent = (labId, data) => api.post(`/labs/${labId}/agents`, data);
export const updateLabAgent = (labId, agentId, data) => api.patch(`/labs/${labId}/agents/${agentId}`, data);
export const deleteLabAgent = (labId, agentId) => api.delete(`/labs/${labId}/agents/${agentId}`);

export const getLabTools = (labId) => api.get(`/labs/${labId}/tools`);
export const createLabTool = (labId, data) => api.post(`/labs/${labId}/tools`, data);
export const updateLabTool = (labId, toolId, data) => api.patch(`/labs/${labId}/tools/${toolId}`, data);
export const deleteLabTool = (labId, toolId) => api.delete(`/labs/${labId}/tools/${toolId}`);

export const getLabMessages = (labId, params = {}) => api.get(`/labs/${labId}/messages`, { params });
export const getLabMemories = (labId, params = {}) => api.get(`/labs/${labId}/memories`, { params });
export const toggleLabMemoryVisibility = (labId, memoryId, isHidden) => api.patch(`/labs/${labId}/memories/${memoryId}`, { is_hidden: isHidden });

// Lab Resources (file uploads)
export const getLabResources = (labId) => api.get(`/labs/${labId}/resources`);
export const uploadLabResource = (labId, file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post(`/labs/${labId}/resources`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const deleteLabResource = (labId, resourceId) => api.delete(`/labs/${labId}/resources/${resourceId}`);
export const getLabResourceUrl = (labId, resourceId) => `${API_BASE}/api/v1/labs/${labId}/resources/${resourceId}/download`;

// Lab Output Files (agent-generated)
export const getLabOutputFiles = (labId) => api.get(`/labs/${labId}/output-files`);
export const getLabOutputFileUrl = (labId, path) => `${API_BASE}/api/v1/labs/${labId}/output-files/download?path=${encodeURIComponent(path)}`;
export const getLabOutputFileContent = (labId, path) => api.get(`/labs/${labId}/output-files/content?path=${encodeURIComponent(path)}`);
export const getLabOutputFileHistory = (labId, path) => api.get(`/labs/${labId}/output-files/history?path=${encodeURIComponent(path)}`);
export const getLabResourceContent = (labId, resourceId) => api.get(`/labs/${labId}/resources/${resourceId}/content`);

// Tool Sets
export const getToolSets = () => api.get('/tool-sets');
export const createToolSet = (data) => api.post('/tool-sets', data);
export const updateToolSet = (id, data) => api.patch(`/tool-sets/${id}`, data);
export const deleteToolSet = (id) => api.delete(`/tool-sets/${id}`);
export const duplicateToolSet = (id) => api.post(`/tool-sets/${id}/duplicate`);

// Prompt Templates
export const getPromptTemplates = () => api.get('/prompt-templates');
export const createPromptTemplate = (data) => api.post('/prompt-templates', data);
export const updatePromptTemplate = (id, data) => api.patch(`/prompt-templates/${id}`, data);
export const deletePromptTemplate = (id) => api.delete(`/prompt-templates/${id}`);
export const duplicatePromptTemplate = (id) => api.post(`/prompt-templates/${id}/duplicate`);

// Library Agents
export const getLibraryAgents = () => api.get('/library-agents');
export const createLibraryAgent = (data) => api.post('/library-agents', data);
export const updateLibraryAgent = (id, data) => api.patch(`/library-agents/${id}`, data);
export const deleteLibraryAgent = (id) => api.delete(`/library-agents/${id}`);
export const duplicateLibraryAgent = (id) => api.post(`/library-agents/${id}/duplicate`);
export const getLibraryAgentLabs = (id) => api.get(`/library-agents/${id}/labs`);
export const getLibraryAgentStats = (id) => api.get(`/library-agents/${id}/stats`);

// Agent Instances (single-agent runnable labs spawned from a template)
export const getAgentInstances = () => api.get('/library-agents/instances');
export const getAgentInstancesForTemplate = (id) => api.get(`/library-agents/${id}/instances`);
export const createAgentInstance = (id, data = {}) => api.post(`/library-agents/${id}/instances`, data);
export const deleteAgentInstance = (labId) => api.delete(`/library-agents/instances/${labId}`);
export const runAgentInstance = (labId, { reset = false } = {}) =>
  api.post(`/library-agents/instances/${labId}/run?reset=${reset}`);
export const pauseAgentInstance = (labId) => api.post(`/library-agents/instances/${labId}/pause`);
export const resumeAgentInstance = (labId) => api.post(`/library-agents/instances/${labId}/resume`);
export const stopAgentInstance = (labId) => api.post(`/library-agents/instances/${labId}/stop`);
export const injectAgentInstance = (labId, message) =>
  api.post(`/library-agents/instances/${labId}/inject`, { message });

// CRON Jobs
export const getCronJobs = () => api.get('/cron-jobs');
export const createCronJob = (data) => api.post('/cron-jobs', data);
export const updateCronJob = (id, data) => api.patch(`/cron-jobs/${id}`, data);
export const deleteCronJob = (id) => api.delete(`/cron-jobs/${id}`);
export const duplicateCronJob = (id) => api.post(`/cron-jobs/${id}/duplicate`);
export const getCronJobLabs = (id) => api.get(`/cron-jobs/${id}/labs`);

// RAG
export const getRagCollections = () => api.get('/rag/collections');
export const getRagCollection = (id) => api.get(`/rag/collections/${id}`);
export const createRagCollection = (data) => api.post('/rag/collections', data);
export const updateRagCollection = (id, data) => api.patch(`/rag/collections/${id}`, data);
export const deleteRagCollection = (id) => api.delete(`/rag/collections/${id}`);

export const getRagDocuments = (collectionId) => api.get(`/rag/collections/${collectionId}/documents`);
export const uploadRagDocument = (collectionId, data) => api.post(`/rag/collections/${collectionId}/documents`, data, {
  headers: { 'Content-Type': 'multipart/form-data' },
});
export const uploadRagDocumentFromUrl = (collectionId, data) => api.post(`/rag/collections/${collectionId}/documents/from-url`, data);
export const deleteRagDocument = (collectionId, documentId) => api.delete(`/rag/collections/${collectionId}/documents/${documentId}`);
export const reingestRagDocument = (collectionId, documentId, data) => api.post(`/rag/collections/${collectionId}/documents/${documentId}/reingest`, data);
export const reingestAllRagDocuments = (collectionId, data) => api.post(`/rag/collections/${collectionId}/documents/reingest-all`, data);

export const getLabRagAccess = (labId) => api.get(`/labs/${labId}/rag-access`);
export const grantLabRagAccess = (labId, data) => api.post(`/labs/${labId}/rag-access`, data);
export const updateLabRagAccess = (labId, collectionId, data) => api.patch(`/labs/${labId}/rag-access/${collectionId}`, data);
export const revokeLabRagAccess = (labId, collectionId) => api.delete(`/labs/${labId}/rag-access/${collectionId}`);

export const searchRag = (data) => api.post('/rag/search', data);

// ACL
export const updateResourceAcl = (resourceType, resourceId, acl, isPublic = undefined) => {
  const payload = { resource_type: resourceType, resource_id: resourceId, acl };
  if (isPublic !== undefined) payload.is_public = isPublic;
  return api.patch('/access-tokens/acl', payload);
};

// Admin: labs visibility on /live
export const adminListLabs = () => api.get('/admin/labs');
export const adminSetLabVisibility = (labId, isPublic) =>
  api.patch(`/admin/labs/${labId}/visibility`, { is_public: isPublic });

// Admin
export const adminLogin = (password) => api.post('/public/admin-login', { password });
export const getInfraWhitelist = () => api.get('/access-tokens/platform/infra-access');
export const updateInfraWhitelist = (emails) => api.put('/access-tokens/platform/infra-access', { emails });

// Admin Logs (observability dashboard)
export const getAdminLogRequests = (params = {}) => api.get('/admin/logs/requests', { params });
export const getAdminLogFacets = (params = {}) => api.get('/admin/logs/facets', { params });
export const getAdminLogMetrics = (params = {}) => api.get('/admin/logs/metrics', { params });
export const getAdminLogLabLoops = (params = {}) => api.get('/admin/logs/lab-loops', { params });
export const getAdminLogTasks = (params = {}) => api.get('/admin/logs/tasks', { params });
export const getAdminLogLlmEvents = (params = {}) => api.get('/orchestrator/llm-events', { params });

// Tool Configs
export const getToolConfigs = () => api.get('/tool-configs');
export const getToolConfig = (toolType) => api.get(`/tool-configs/${toolType}`);
export const upsertToolConfig = (toolType, config) => api.put(`/tool-configs/${toolType}`, { config });
export const deleteToolConfig = (toolType) => api.delete(`/tool-configs/${toolType}`);

// File download helper (uses axios to include auth token)
export const downloadFile = async (url, filename) => {
  try {
    // Build relative path for axios (strip origin if present)
    let apiPath = url;
    try { apiPath = new URL(url).pathname + new URL(url).search; } catch {}
    // Remove the /api/v1 prefix since axios baseURL already includes it
    const prefix = '/api/v1';
    if (apiPath.startsWith(prefix)) apiPath = apiPath.slice(prefix.length);
    const res = await api.get(apiPath, { responseType: 'blob' });
    const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/octet-stream' });
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(blobUrl);
  } catch (e) { console.error('Download failed', e); }
};

// Get an authenticated blob URL for media preview
export const getAuthBlobUrl = async (url) => {
  try {
    let apiPath = url;
    try { apiPath = new URL(url).pathname + new URL(url).search; } catch {}
    const prefix = '/api/v1';
    if (apiPath.startsWith(prefix)) apiPath = apiPath.slice(prefix.length);
    const res = await api.get(apiPath, { responseType: 'blob' });
    return URL.createObjectURL(res.data);
  } catch (e) { console.error('Failed to get blob URL', e); return null; }
};

// ── Outreach approval queue ─────────────────────
export const listOutreachDrafts = (status = 'pending') =>
  api.get('/outreach/drafts', { params: { status_filter: status } });
export const getOutreachDraft = (labId, filename) =>
  api.get(`/outreach/drafts/${labId}/${encodeURIComponent(filename)}`);
export const editOutreachDraft = (labId, filename, data) =>
  api.patch(`/outreach/drafts/${labId}/${encodeURIComponent(filename)}`, data);
export const sendOutreachDraft = (labId, filename) =>
  api.post(`/outreach/drafts/${labId}/${encodeURIComponent(filename)}/send`);
export const rejectOutreachDraft = (labId, filename) =>
  api.post(`/outreach/drafts/${labId}/${encodeURIComponent(filename)}/reject`);


// ── Admin-API client (A07) ─────────────────────────────
// AdminPage authenticates with ADMIN_SECRET separately from the regular
// bob_token JWT. Pre-fix, AdminPage swapped localStorage's bob_token in
// and out around every admin call (`withAdminJwt`):
//   1) destructive if another concurrent request fired during the swap
//      window (Promise.all([loadX(), loadY()]) trampled the global);
//   2) confusing for users — the swap briefly put "admin" claims into
//      the LiveLab tab too if they had it open.
// The fix routes admin calls through a dedicated axios instance whose
// Authorization header is set at construction time and never touches
// localStorage. AdminPage calls `createAdminApiClient(jwt)` once after
// admin login and uses the returned methods for every admin request.
export function createAdminApiClient(jwt) {
  if (!jwt) throw new Error('createAdminApiClient requires a JWT');
  const adminAxios = axios.create({
    baseURL: `${API_BASE}/api/v1`,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${jwt}`,
    },
  });
  // Mirror the global 401 interceptor so a revoked admin JWT also
  // triggers handleUnauthorized().
  adminAxios.interceptors.response.use(
    (r) => r,
    (e) => {
      if (e?.response?.status === 401) handleUnauthorized();
      return Promise.reject(e);
    },
  );
  return {
    // Access tokens + requests
    getTrialRequests: () => adminAxios.get('/access-tokens/trial-requests'),
    updateTrialRequestStatus: (id, status) =>
      adminAxios.patch(`/access-tokens/trial-requests/${id}`, { status }),
    getAccessTokens: () => adminAxios.get('/access-tokens'),
    createAccessToken: (data) => adminAxios.post('/access-tokens', data),
    revokeAccessToken: (id) => adminAxios.delete(`/access-tokens/${id}`),
    // Quote requests
    getQuoteRequests: () => adminAxios.get('/access-tokens/quote-requests'),
    updateQuoteRequestStatus: (id, status) =>
      adminAxios.patch(`/access-tokens/quote-requests/${id}`, { status }),
    // Infra access whitelist
    getInfraWhitelist: () => adminAxios.get('/access-tokens/platform/infra-access'),
    updateInfraWhitelist: (emails) =>
      adminAxios.put('/access-tokens/platform/infra-access', { emails }),
    // Blog tokens + posts
    getBlogTokens: () => adminAxios.get('/access-tokens/blog-tokens'),
    createBlogToken: (label) => adminAxios.post('/access-tokens/blog-tokens', { label }),
    revokeBlogToken: (id) => adminAxios.delete(`/access-tokens/blog-tokens/${id}`),
    getBlogPostsAdmin: () => adminAxios.get('/access-tokens/blog-posts'),
    deleteBlogPost: (id) => adminAxios.delete(`/access-tokens/blog-posts/${id}`),
    // Consumer apps (HMAC)
    getConsumerApps: () => adminAxios.get('/admin/consumer-apps'),
    createConsumerApp: (data) => adminAxios.post('/admin/consumer-apps', data),
    revokeConsumerApp: (id) => adminAxios.delete(`/admin/consumer-apps/${id}`),
    deleteConsumerApp: (id) => adminAxios.delete(`/admin/consumer-apps/${id}/permanent`),
    // Lab visibility
    adminListLabs: () => adminAxios.get('/admin/labs'),
    adminSetLabVisibility: (labId, isPublic) =>
      adminAxios.patch(`/admin/labs/${labId}/visibility`, { is_public: isPublic }),
    // Admin logs (observability dashboard)
    getAdminLogRequests: (params = {}) => adminAxios.get('/admin/logs/requests', { params }),
    getAdminLogFacets: (params = {}) => adminAxios.get('/admin/logs/facets', { params }),
    getAdminLogMetrics: (params = {}) => adminAxios.get('/admin/logs/metrics', { params }),
    getAdminLogLabLoops: (params = {}) => adminAxios.get('/admin/logs/lab-loops', { params }),
    getAdminLogTasks: (params = {}) => adminAxios.get('/admin/logs/tasks', { params }),
    getAdminLogLlmEvents: (params = {}) => adminAxios.get('/orchestrator/llm-events', { params }),
  };
}

export default api;
