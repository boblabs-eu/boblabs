import React, { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useT, LanguageToggle } from '../i18n';

function CodeBlock({ className, children }) {
  const [copied, setCopied] = useState(false);
  const text = String(children).replace(/\n$/, '');
  const lang = (className || '').replace('language-', '') || '';
  const onCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    });
  };
  return (
    <div className="docs-code-wrap">
      {lang && <span className="docs-code-lang">{lang}</span>}
      <button type="button" className="docs-code-copy" onClick={onCopy}>
        {copied ? '✓ Copied' : '⧉ Copy'}
      </button>
      <pre className="docs-code-block">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

const docTree = [
  {
    id: 'start',
    title: 'Get Started',
    children: [
      { id: 'QUICK_LAUNCH', title: 'Quick Launch', file: 'QUICK_LAUNCH.md' },
      { id: 'GENERAL_OVERVIEW', title: 'General Overview', file: 'GENERAL_OVERVIEW.md' },
      { id: 'README', title: 'Project README', file: 'README.md' },
      { id: 'INSTALL_PROD', title: 'Production Install', file: 'INSTALL_PROD.md' },
      { id: 'CONFIGURATION', title: 'Configuration', file: 'CONFIGURATION.md' },
    ],
  },
  {
    id: 'architecture',
    title: 'Architecture',
    children: [
      { id: 'ARCHITECTURE', title: 'System Architecture', file: 'ARCHITECTURE.md' },
      { id: 'ORCHESTRATOR', title: 'AI Orchestrator', file: 'ORCHESTRATOR.md' },
      { id: 'DISPATCHER_AND_MODEL_ROUTING', title: 'Dispatcher & Model Routing', file: 'DISPATCHER_AND_MODEL_ROUTING.md' },
      { id: 'AGENT', title: 'Host Agent', file: 'AGENT.md' },
      { id: 'GPU_SERVICES', title: 'GPU Services', file: 'GPU_SERVICES.md' },
    ],
  },
  {
    id: 'labs',
    title: 'Labs & Agents',
    children: [
      { id: 'LABS', title: 'Labs Architecture', file: 'LABS.md' },
      { id: 'AGENTS_AND_ORCHESTRATION', title: 'Agents & Orchestration', file: 'AGENTS_AND_ORCHESTRATION.md' },
      { id: 'HERMES', title: 'Hermes Agent Backend', file: 'HERMES.md' },
      { id: 'CLAUDE_CLI', title: 'Claude CLI Provider', file: 'CLAUDE_CLI.md' },
      { id: 'PROMPT_STRUCTURE', title: 'Prompt Structure', file: 'PROMPT_STRUCTURE.md' },
      { id: 'CONVERSATIONS', title: 'Conversations', file: 'CONVERSATIONS.md' },
      { id: 'PROJECTS_AND_RESOURCES', title: 'Projects & Resources', file: 'PROJECTS_AND_RESOURCES.md' },
      { id: 'ANTI_LOOP', title: 'Anti-Loop System', file: 'ANTI_LOOP.md' },
    ],
  },
  {
    id: 'execution',
    title: 'Execution & Tools',
    children: [
      { id: 'TOOLS_AND_SANDBOX', title: 'Tools & Sandbox', file: 'TOOLS_AND_SANDBOX.md' },
      { id: 'SCHEDULING_AND_CRON', title: 'Scheduling & Cron', file: 'SCHEDULING_AND_CRON.md' },
      { id: 'WEB3_TOOL', title: 'Web3 Tool', file: 'WEB3_TOOL.md' },
    ],
  },
  {
    id: 'data',
    title: 'Knowledge & Data',
    children: [
      { id: 'RAG', title: 'RAG & Vector Search', file: 'RAG.md' },
      { id: 'LIGHTRAG', title: 'LightRAG (Knowledge Graph)', file: 'LIGHTRAG.md' },
    ],
  },
  {
    id: 'media',
    title: 'Media & GPU Pipelines',
    children: [
      { id: 'VIDEO_GENERATION', title: 'Video Generation', file: 'VIDEO_GENERATION.md' },
      { id: 'INSTALL_LTX_VIDEO', title: 'Install LTX Video', file: 'INSTALL_LTX_VIDEO.md' },
      { id: 'INSTALL_WAN_VIDEO', title: 'Install WAN Video', file: 'INSTALL_WAN_VIDEO.md' },
      { id: 'MUSIC_PIPELINES', title: 'Music Pipelines', file: 'MUSIC_PIPELINES.md' },
    ],
  },
  {
    id: 'enterprise',
    title: 'Enterprise',
    children: [
      { id: 'ACCESS_CONTROL', title: 'Access Control', file: 'ACCESS_CONTROL.md' },
      { id: 'API_REFERENCE', title: 'API Reference', file: 'API_REFERENCE.md' },
      { id: 'COMMERCIALIZATION', title: 'Commercialization', file: 'COMMERCIALIZATION.md' },
    ],
  },
  {
    id: 'web3',
    title: 'Web3',
    children: [
      { id: 'WEB3', title: 'Web3 Overview', file: 'WEB3.md' },
      { id: 'WEB3_LABS', title: 'Web3 Labs', file: 'WEB3_LABS.md' },
    ],
  },
];

const defaultDoc = 'QUICK_LAUNCH';

// Flat list for prev/next navigation
const flatDocs = docTree.flatMap((s) =>
  s.children.map((c) => ({ ...c, sectionTitle: s.title }))
);

export default function DocsPage() {
  const { t } = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeDoc = searchParams.get('doc') || defaultDoc;
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedSections, setExpandedSections] = useState(() =>
    docTree.map((s) => s.id)
  );
  const [headings, setHeadings] = useState([]);
  const [activeHeading, setActiveHeading] = useState('');

  const flatIndex = flatDocs.findIndex((d) => d.id === activeDoc);
  const currentDoc = flatDocs[flatIndex] || flatDocs[0];
  const prevDoc = flatIndex > 0 ? flatDocs[flatIndex - 1] : null;
  const nextDoc = flatIndex >= 0 && flatIndex < flatDocs.length - 1 ? flatDocs[flatIndex + 1] : null;

  const selectDoc = useCallback(
    (docId) => {
      setSearchParams({ doc: docId });
      window.scrollTo(0, 0);
    },
    [setSearchParams]
  );

  const toggleSection = (sectionId) => {
    setExpandedSections((prev) =>
      prev.includes(sectionId)
        ? prev.filter((id) => id !== sectionId)
        : [...prev, sectionId]
    );
  };

  useEffect(() => {
    const entry = docTree
      .flatMap((s) => s.children)
      .find((d) => d.id === activeDoc);
    if (!entry) return;

    setLoading(true);
    fetch(`/docs-md/${entry.file}`)
      .then((res) => {
        if (!res.ok) throw new Error('Not found');
        return res.text();
      })
      .then((md) => {
        setContent(md);
        // Extract headings for right-side TOC
        const matches = [...md.matchAll(/^(#{2,3})\s+(.+)$/gm)];
        setHeadings(
          matches.map((m) => ({
            level: m[1].length,
            text: m[2].replace(/[`*]/g, ''),
            id: m[2]
              .replace(/[`*]/g, '')
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, '-')
              .replace(/(^-|-$)/g, ''),
          }))
        );
      })
      .catch(() => setContent('# Document not found\n\nThe requested document could not be loaded.'))
      .finally(() => setLoading(false));
  }, [activeDoc]);

  // Scroll-spy for right-side TOC
  useEffect(() => {
    if (!headings.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveHeading(visible[0].target.id);
      },
      { rootMargin: '-80px 0px -70% 0px' }
    );
    headings.forEach((h) => {
      const el = document.getElementById(h.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [headings, content]);

  return (
    <div className="docs-layout">
      {/* ── Top bar with breadcrumb ───────── */}
      <header className="docs-topbar">
        <Link to="/" className="docs-topbar-brand">
          <span className="lp-brand-icon">◆</span> Bob Labs
        </Link>
        <span className="docs-topbar-divider" />
        <div className="docs-breadcrumb">
          <span>Docs</span>
          <span className="docs-breadcrumb-sep">/</span>
          <span>{currentDoc.sectionTitle}</span>
          <span className="docs-breadcrumb-sep">/</span>
          <span className="docs-breadcrumb-current">{currentDoc.title}</span>
        </div>
        <div className="docs-topbar-spacer" />
        <LanguageToggle />
        <a
          href="https://github.com/boblabs-eu/boblabs"
          target="_blank"
          rel="noreferrer"
          className="docs-topbar-link"
        >
          GitHub ↗
        </a>
        <Link to="/" className="docs-topbar-link">Home</Link>
      </header>

      {/* ── Left sidebar ─────────────────── */}
      <aside className="docs-sidebar">
        <nav className="docs-sidebar-nav">
          {docTree.map((section) => (
            <div key={section.id} className="docs-nav-section">
              <button
                className="docs-nav-section-btn"
                onClick={() => toggleSection(section.id)}
              >
                <span className={`docs-nav-arrow ${expandedSections.includes(section.id) ? 'open' : ''}`}>›</span>
                {section.title}
              </button>
              {expandedSections.includes(section.id) && (
                <div className="docs-nav-children">
                  {section.children.map((child) => (
                    <button
                      key={child.id}
                      className={`docs-nav-item ${activeDoc === child.id ? 'active' : ''}`}
                      onClick={() => selectDoc(child.id)}
                    >
                      {child.title}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>
        <div className="docs-sidebar-footer">
          <Link to="/">← Back to Home</Link>
        </div>
      </aside>

      {/* ── Main content ─────────────────── */}
      <main className="docs-main">
        {loading ? (
          <div className="docs-loading">{t('docs.loading')}</div>
        ) : (
          <article className="docs-content">
            <span className="docs-eyebrow">{currentDoc.sectionTitle}</span>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1 className="docs-h1">{children}</h1>,
                h2: ({ children }) => {
                  const id = String(children)
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-')
                    .replace(/(^-|-$)/g, '');
                  return <h2 id={id} className="docs-h2">{children}</h2>;
                },
                h3: ({ children }) => {
                  const id = String(children)
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-')
                    .replace(/(^-|-$)/g, '');
                  return <h3 id={id} className="docs-h3">{children}</h3>;
                },
                table: ({ children }) => (
                  <div className="docs-table-wrap">
                    <table>{children}</table>
                  </div>
                ),
                pre: ({ children }) => {
                  // react-markdown v10 no longer passes an `inline` flag to `code`.
                  // Route block code structurally via `pre` (children is the default-
                  // rendered <code class="language-…">), preserving the copy button +
                  // language label. Inline code stays a plain <code>, styled by CSS.
                  const codeEl = Array.isArray(children) ? children[0] : children;
                  const props = (codeEl && codeEl.props) || {};
                  return <CodeBlock className={props.className}>{props.children}</CodeBlock>;
                },
              }}
            >
              {content}
            </ReactMarkdown>

            {(prevDoc || nextDoc) && (
              <div className="docs-pager">
                {prevDoc ? (
                  <button
                    type="button"
                    onClick={() => selectDoc(prevDoc.id)}
                    className="docs-pager-link prev"
                  >
                    <span className="docs-pager-label">← Previous</span>
                    <span className="docs-pager-title">{prevDoc.title}</span>
                  </button>
                ) : <span />}
                {nextDoc ? (
                  <button
                    type="button"
                    onClick={() => selectDoc(nextDoc.id)}
                    className="docs-pager-link next"
                  >
                    <span className="docs-pager-label">Next →</span>
                    <span className="docs-pager-title">{nextDoc.title}</span>
                  </button>
                ) : <span />}
              </div>
            )}
          </article>
        )}
      </main>

      {/* ── Right TOC ────────────────────── */}
      {headings.length > 0 && (
        <aside className="docs-toc">
          <div className="docs-toc-title">On this page</div>
          <nav>
            {headings.map((h) => (
              <a
                key={h.id}
                href={`#${h.id}`}
                className={`docs-toc-link ${h.level === 3 ? 'docs-toc-sub' : ''} ${activeHeading === h.id ? 'active' : ''}`}
              >
                {h.text}
              </a>
            ))}
          </nav>
        </aside>
      )}
    </div>
  );
}
