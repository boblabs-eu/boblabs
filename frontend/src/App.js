/**
 * Bob Manager — Main App with routing.
 */

import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Sidebar from './components/common/Sidebar';
import DashboardPage from './pages/DashboardPage';
import MetricsPage from './pages/MetricsPage';
import WorkflowsPage from './pages/WorkflowsPage';
import CommandsPage from './pages/CommandsPage';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import ResourcesPage from './pages/ResourcesPage';
import ResourceDetailPage from './pages/ResourceDetailPage';
import RagPage from './pages/RagPage';
import LogsPage from './pages/LogsPage';
import TerminalPage from './pages/TerminalPage';
import NewsPage from './pages/NewsPage';
import Web3Page from './pages/Web3Page';
import OrchestratorPage from './pages/OrchestratorPage';
import LandingPage from './pages/LandingPage';
import DocsPage from './pages/DocsPage';
import LoginPage from './pages/LoginPage';
import TrialRequestPage from './pages/TrialRequestPage';
import BlogPage from './pages/BlogPage';
import AdminPage from './pages/AdminPage';
import LivePage from './pages/LivePage';
import { AuthProvider, useAuth } from './context/AuthContext';
import wsService from './services/websocket';

const PUBLIC_PATHS = ['/', '/fr', '/docs', '/login', '/request-trial', '/blog', '/admin', '/live'];

function isPublicPath(pathname) {
  if (PUBLIC_PATHS.includes(pathname)) return true;
  // /blog/<slug> — any subpath of /blog is public.
  if (pathname.startsWith('/blog/')) return true;
  return false;
}

function AppContent() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const isPublicPage = isPublicPath(location.pathname);

  useEffect(() => {
    // LivePage manages its own WS connection
    if (location.pathname === '/live') return undefined;
    if (isPublicPage || !isAuthenticated) {
      wsService.disconnect();
      return undefined;
    }
    wsService.connect();
    return () => wsService.disconnect();
  }, [isPublicPage, isAuthenticated]);

  if (isPublicPage) {
    return (
      <main className="marketing-shell">
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/fr" element={<LandingPage forceLang="fr" />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/request-trial" element={<TrialRequestPage />} />
          <Route path="/blog" element={<BlogPage />} />
          <Route path="/blog/:slug" element={<BlogPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/live" element={<LivePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="app-layout">
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />
      <main className="main-content" style={{ marginLeft: sidebarCollapsed ? 64 : 240 }}>
        <Routes>
          <Route path="/dashboard" element={<DashboardPage />} />
          {/* /servers was folded into /metrics (Metrics Servers) — keep redirect for stale bookmarks. */}
          <Route path="/servers" element={<Navigate to="/metrics" replace />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/commands" element={<CommandsPage />} />
          <Route path="/terminal" element={<TerminalPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/resources/:id" element={<ResourceDetailPage />} />
          <Route path="/rag" element={<RagPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/web3" element={<Web3Page />} />
          <Route path="/orchestrator" element={<OrchestratorPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </BrowserRouter>
  );
}
