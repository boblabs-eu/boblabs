/**
 * Bob Manager — Sidebar navigation component.
 * Collapsible: full or icon-only mode. Professional SVG icons.
 */

import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';

/* ── Lucide-style SVG icons (stroke-based, 20×20) ── */
const Icon = ({ children }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    style={{ flexShrink: 0 }}>
    {children}
  </svg>
);

const icons = {
  dashboard: (
    <Icon>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </Icon>
  ),
  servers: (
    <Icon>
      <rect x="2" y="2" width="20" height="8" rx="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </Icon>
  ),
  metrics: (
    <Icon>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </Icon>
  ),
  mcp: (
    <Icon>
      <rect x="9" y="9" width="6" height="6" rx="1" />
      <line x1="12" y1="3" x2="12" y2="9" />
      <line x1="12" y1="15" x2="12" y2="21" />
      <line x1="3" y1="12" x2="9" y2="12" />
      <line x1="15" y1="12" x2="21" y2="12" />
    </Icon>
  ),
  workflows: (
    <Icon>
      <polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </Icon>
  ),
  commands: (
    <Icon>
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" y1="19" x2="20" y2="19" />
    </Icon>
  ),
  terminal: (
    <Icon>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <polyline points="6 10 10 14 6 18" />
      <line x1="14" y1="18" x2="18" y2="18" />
    </Icon>
  ),
  projects: (
    <Icon>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </Icon>
  ),
  resources: (
    <Icon>
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </Icon>
  ),
  rag: (
    <Icon>
      <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H8l-4 3V6z" />
      <circle cx="10" cy="11" r="1" />
      <circle cx="14" cy="11" r="1" />
      <circle cx="18" cy="11" r="1" />
    </Icon>
  ),
  logs: (
    <Icon>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </Icon>
  ),
  news: (
    <Icon>
      <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2" />
      <line x1="10" y1="6" x2="18" y2="6" />
      <line x1="10" y1="10" x2="18" y2="10" />
      <line x1="10" y1="14" x2="14" y2="14" />
    </Icon>
  ),
  web3: (
    <Icon>
      <path d="M11.767 19.089c4.924.868 6.14-6.025 1.216-6.894m-1.216 6.894L5.86 18.047m5.908 1.042l-.347 1.97m1.563-8.864c4.924.869 6.14-6.025 1.215-6.893m-1.215 6.893l-6.57-1.158m6.57 1.158l-.346 1.971M6.206 16.09l-1.97-.347m11.625-7.302l-6.57-1.157m0 0L9.637 5.314m-.347 1.97l-1.97-.348" />
    </Icon>
  ),
  settings: (
    <Icon>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </Icon>
  ),
  collapse: (
    <Icon>
      <polyline points="11 17 6 12 11 7" />
      <polyline points="18 17 13 12 18 7" />
    </Icon>
  ),
  expand: (
    <Icon>
      <polyline points="13 17 18 12 13 7" />
      <polyline points="6 17 11 12 6 7" />
    </Icon>
  ),
  orchestrator: (
    <Icon>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v4" />
      <path d="M12 18v4" />
      <path d="M4.93 4.93l2.83 2.83" />
      <path d="M16.24 16.24l2.83 2.83" />
      <path d="M2 12h4" />
      <path d="M18 12h4" />
      <path d="M4.93 19.07l2.83-2.83" />
      <path d="M16.24 7.76l2.83-2.83" />
    </Icon>
  ),
  chevronDown: (
    <Icon>
      <polyline points="6 9 12 15 18 9" />
    </Icon>
  ),
  chevronRight: (
    <Icon>
      <polyline points="9 18 15 12 9 6" />
    </Icon>
  ),
};

/* Core nav — what the public release foregrounds: the orchestrator + GPU servers.
   The old standalone /servers page was folded into /metrics (Metrics Servers) — Add Server
   and Remove now live in the expanded row of each server there. */
const coreNavItems = [
  { path: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
  /* The Console (formerly "Orchestrator") is the project's main object — kept the
     route slug as /orchestrator to avoid breaking deep-links and internal references
     (the lab-orchestrator role still uses that word inside Labs). The `featured`
     flag paints the icon accent + tints the row so it pops in the public nav. */
  { path: '/orchestrator', label: 'Console', icon: 'orchestrator', featured: true },
  { path: '/mcp', label: 'MCP', icon: 'mcp' },
  { path: '/metrics', label: 'Metrics Servers', icon: 'metrics' },
  { path: '/rag', label: 'RAG', icon: 'rag' },
  { path: '/logs', label: 'Logs', icon: 'logs' },
];

/* Internal dev tools — kept reachable by URL, tucked into a collapsible group. */
const devNavItems = [
  { path: '/workflows', label: 'Workflows', icon: 'workflows' },
  { path: '/commands', label: 'Commands', icon: 'commands' },
  { path: '/terminal', label: 'Terminal', icon: 'terminal' },
  { path: '/projects', label: 'Projects', icon: 'projects' },
  { path: '/resources', label: 'Resources', icon: 'resources' },
  { path: '/news', label: 'News', icon: 'news' },
  { path: '/web3', label: 'Web3', icon: 'web3' },
];

/* Accent themes — order matters: it's the swatch row order in the sidebar. */
const THEMES = [
  { key: 'blue', label: 'Blue', color: '#7c5cff' },
  { key: 'red', label: 'Red', color: '#ef4444' },
  { key: 'green', label: 'Green', color: '#10b981' },
  { key: 'grey', label: 'Grey', color: '#94a3b8' },
];

function ThemePicker() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || localStorage.getItem('bob_theme') || 'blue'
  );

  function pick(next) {
    setTheme(next);
    localStorage.setItem('bob_theme', next);
    document.documentElement.dataset.theme = next;
  }

  return (
    <div className="theme-picker">
      <span className="theme-picker-label">Theme</span>
      {THEMES.map((t) => (
        <button
          key={t.key}
          type="button"
          className={`theme-swatch ${theme === t.key ? 'active' : ''}`}
          style={{ '--swatch-color': t.color }}
          onClick={() => pick(t.key)}
          aria-label={`${t.label} theme`}
          aria-pressed={theme === t.key}
          title={t.label}
        />
      ))}
    </div>
  );
}

function NavItem({ item, collapsed }) {
  const featuredClass = item.featured ? 'featured' : '';
  return (
    <li>
      <NavLink
        to={item.path}
        className={({ isActive }) => [isActive ? 'active' : '', featuredClass].filter(Boolean).join(' ')}
        end={item.path === '/dashboard'}
        title={collapsed ? item.label : undefined}
      >
        <span className="nav-icon">{icons[item.icon]}</span>
        {!collapsed && <span className="nav-label">{item.label}</span>}
      </NavLink>
    </li>
  );
}

export default function Sidebar({ collapsed, onToggle }) {
  const [devOpen, setDevOpen] = useState(
    () => localStorage.getItem('sidebar_dev_open') === 'true'
  );

  function toggleDev() {
    setDevOpen((prev) => {
      localStorage.setItem('sidebar_dev_open', String(!prev));
      return !prev;
    });
  }

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <div className="sidebar-header">
        {!collapsed && (
          <>
            <h1>Bob Labs</h1>
            <span>Private AI operations</span>
          </>
        )}
        {collapsed && (
          <h1 style={{ fontSize: '1rem', textAlign: 'center' }}>BL</h1>
        )}
      </div>
      <ThemePicker />
      <ul className="sidebar-nav">
        {coreNavItems.map((item) => (
          <NavItem key={item.path} item={item} collapsed={collapsed} />
        ))}

        {/* Internal dev tools: collapsible group in full mode, plain icons in icon mode. */}
        {collapsed ? (
          <>
            <li className="sidebar-divider" aria-hidden="true" />
            {devNavItems.map((item) => (
              <NavItem key={item.path} item={item} collapsed={collapsed} />
            ))}
          </>
        ) : (
          <>
            <li>
              <button
                type="button"
                className="sidebar-section-header"
                onClick={toggleDev}
                aria-expanded={devOpen}
              >
                <span className="sidebar-section-chevron">
                  {devOpen ? icons.chevronDown : icons.chevronRight}
                </span>
                <span className="sidebar-section-label">Other (dev)</span>
              </button>
            </li>
            {devOpen &&
              devNavItems.map((item) => (
                <NavItem key={item.path} item={item} collapsed={collapsed} />
              ))}
          </>
        )}
      </ul>
      <div className="sidebar-toggle">
        <button onClick={onToggle} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? icons.expand : icons.collapse}
        </button>
      </div>
    </aside>
  );
}
