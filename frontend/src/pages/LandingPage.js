import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { submitQuoteRequest } from '../services/api';
import { useT, LanguageToggle } from '../i18n';
import {
  ShieldCheckIcon,
  LockClosedIcon,
  CpuChipIcon,
  CircleStackIcon,
  WrenchScrewdriverIcon,
  BeakerIcon,
  FolderOpenIcon,
  FlagIcon,
  ArrowPathIcon,
  BoltIcon,
  CubeIcon,
  CodeBracketIcon,
  ClockIcon,
  SignalIcon,
  ArrowsPointingOutIcon,
  Cog6ToothIcon,
} from '@heroicons/react/24/outline';

/* ═══════════════════════════════════════════════════════════════════
   STATIC ASSETS (language-independent)
   ═══════════════════════════════════════════════════════════════════ */
const previewTabIds = [
  { id: 'dashboard', icon: '◈', src: '/assets/lab_dashboard.png' },
  { id: 'lab', icon: '⬢', src: '/assets/lab_inside_view.png' },
  { id: 'lab2', icon: '⬢', src: '/assets/lab_inside_agent_view.png' },
  { id: 'agent', icon: '⬢', src: '/assets/agent_templates.png' },
  { id: 'memories', icon: '⬢', src: '/assets/agent_memories.png' },
  { id: 'models', icon: '⌬', src: '/assets/dispatcher_feed.png' },
  { id: 'stats', icon: '▤', src: '/assets/dispatcher_stats.png' },
  { id: 'dispatch_live', icon: '◉', src: '/assets/dispatcher_live_zoom.png' },
  { id: 'live', icon: '◉', src: '/assets/live_view.png' },
  { id: 'live_attach', icon: '◉', src: '/assets/live_view_attachement.png' },
];

const coreCategoryIds = [
  { id: 'enterprise', Icon: ShieldCheckIcon, bullets: 3 },
  { id: 'data', Icon: LockClosedIcon, bullets: 3 },
  { id: 'agents', Icon: CpuChipIcon, bullets: 3 },
  { id: 'labs', Icon: BeakerIcon, bullets: 4 },
  { id: 'hardware', Icon: BoltIcon, bullets: 3 },
  { id: 'config', Icon: Cog6ToothIcon, bullets: 3 },
];

const featureIds = [
  { id: 'auth', Icon: ShieldCheckIcon },
  { id: 'private', Icon: LockClosedIcon },
  { id: 'models', Icon: CpuChipIcon },
  { id: 'memory', Icon: CircleStackIcon },
  { id: 'tools', Icon: WrenchScrewdriverIcon },
  { id: 'labs', Icon: BeakerIcon },
  { id: 'io', Icon: FolderOpenIcon },
  { id: 'strategy', Icon: FlagIcon },
  { id: 'antiloop', Icon: ArrowPathIcon },
  { id: 'dispatcher', Icon: BoltIcon },
  { id: 'sandbox', Icon: CubeIcon },
  { id: 'json', Icon: CodeBracketIcon },
  { id: 'schedule', Icon: ClockIcon },
  { id: 'bus', Icon: SignalIcon },
  { id: 'unlimited', Icon: ArrowsPointingOutIcon },
];

function PreviewScreenshot({ src, label }) {
  return (
    <div className="lpx-shot">
      <img src={src} alt={label} loading="lazy" />
    </div>
  );
}

function CorePreview({ id }) {
  // Demonstration mock data is intentionally English-only (looks like UI snapshots).
  if (id === 'enterprise') {
    return (
      <div className="lpx-cp">
        <div className="lpx-cp-row"><span className="lpx-cp-k">role</span><span className="lpx-cp-v">admin</span><span className="lpx-cp-pill ok">active</span></div>
        <div className="lpx-cp-row"><span className="lpx-cp-k">role</span><span className="lpx-cp-v">analyst · team:research</span><span className="lpx-cp-pill ok">active</span></div>
        <div className="lpx-cp-row"><span className="lpx-cp-k">role</span><span className="lpx-cp-v">viewer · team:legal</span><span className="lpx-cp-pill warn">read-only</span></div>
        <div className="lpx-cp-row"><span className="lpx-cp-k">share</span><span className="lpx-cp-v">contract-analyzer → team:legal</span><span className="lpx-cp-pill ok">granted</span></div>
        <div className="lpx-cp-row"><span className="lpx-cp-k">audit</span><span className="lpx-cp-v">412 events · last 24h</span><span className="lpx-cp-pill">log</span></div>
      </div>
    );
  }
  if (id === 'data') {
    return (
      <div className="lpx-cp">
        <div className="lpx-cp-grid">
          <div className="lpx-cp-tile"><div className="lpx-cp-tile-h">PostgreSQL</div><div className="lpx-cp-tile-v">on-prem</div></div>
          <div className="lpx-cp-tile"><div className="lpx-cp-tile-h">RAG</div><div className="lpx-cp-tile-v">14 collections</div></div>
          <div className="lpx-cp-tile"><div className="lpx-cp-tile-h">LightRAG</div><div className="lpx-cp-tile-v">knowledge graph</div></div>
          <div className="lpx-cp-tile"><div className="lpx-cp-tile-h">Egress</div><div className="lpx-cp-tile-v lpx-cp-ok">0 bytes / 24h</div></div>
        </div>
        <div className="lpx-cp-note">All vectors · all chunks · all metadata stay on your hardware.</div>
      </div>
    );
  }
  if (id === 'agents') {
    return (
      <div className="lpx-cp">
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#22c55e' }} />researcher · qwen-72b <span className="lpx-cp-tools">rag · search · browser</span></div>
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#3b82f6' }} />analyst · gpt-5 <span className="lpx-cp-tools">python · db · rag</span></div>
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#a855f7' }} />trader · claude <span className="lpx-cp-tools">web3 · http · sandbox</span></div>
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#f59e0b' }} />ops · ollama:llama3 <span className="lpx-cp-tools">shell (allow-list) · ssh</span></div>
        <div className="lpx-cp-note">Memory: 12 sessions · 41 messages · 8 retrieved facts</div>
      </div>
    );
  }
  if (id === 'labs') {
    return (
      <div className="lpx-cp">
        <div className="lpx-cp-lab-head">⬢ research-pipeline</div>
        <div className="lpx-cp-lab-row"><span>orchestrator</span><span>plan → 3 steps</span></div>
        <div className="lpx-cp-lab-row"><span>agents</span><span>4 specialists</span></div>
        <div className="lpx-cp-lab-row"><span>resources</span><span>in/ filings.zip · out/ report.md</span></div>
        <div className="lpx-cp-lab-row"><span>strategy</span><span>"verify every claim against ≥2 sources"</span></div>
        <div className="lpx-cp-lab-row"><span>anti-loop</span><span className="lpx-cp-ok">enabled · 0 incidents</span></div>
      </div>
    );
  }
  if (id === 'hardware') {
    return (
      <div className="lpx-cp">
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#22c55e' }} />gpu-host-01 · 2× A100 · 84% <span className="lpx-cp-tools">qwen-72b · pixtral</span></div>
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#22c55e' }} />gpu-host-02 · 1× H100 · 41% <span className="lpx-cp-tools">flux.1 · sd3</span></div>
        <div className="lpx-cp-agent"><span className="lpx-mock-dot" style={{ background: '#3b82f6' }} />cpu-host-03 · auto-discovered 12s ago <span className="lpx-cp-tools">stt · embedder</span></div>
        <div className="lpx-cp-note">Dispatcher routes each job to the GPU with the right model loaded.</div>
      </div>
    );
  }
  return (
    <div className="lpx-cp">
      <pre className="lpx-cp-code">{`{
  "lab": "research-pipeline",
  "orchestrator": { "model": "gpt-5", "strategy": "verify every claim" },
  "agents": [
    { "name": "researcher", "model": "qwen-72b", "tools": ["rag","search"] },
    { "name": "analyst",    "model": "claude",   "tools": ["python","db"] }
  ],
  "anti_loop": true,
  "resources": { "in": ["filings.zip"], "out": ["report.md"] }
}`}</pre>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   LANDING PAGE — single dictionary-driven implementation
   ═══════════════════════════════════════════════════════════════════ */
export default function LandingPage({ forceLang }) {
  const { t, setLang } = useT();
  const [activeTab, setActiveTab] = useState('dashboard');
  const [activeCore, setActiveCore] = useState('enterprise');
  const [showQuoteModal, setShowQuoteModal] = useState(false);
  const [quotePlan, setQuotePlan] = useState('');
  const [quoteForm, setQuoteForm] = useState({ name: '', email: '', company: '', phone: '', description: '' });
  const [quoteSubmitted, setQuoteSubmitted] = useState(false);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');

  // Honor explicit URL-based locale (`/fr` route still works).
  useEffect(() => {
    if (forceLang) setLang(forceLang);
  }, [forceLang, setLang]);

  const openQuote = (plan) => {
    setQuotePlan(plan);
    setQuoteForm({ name: '', email: '', company: '', phone: '', description: '' });
    setQuoteSubmitted(false);
    setQuoteError('');
    setShowQuoteModal(true);
  };

  const handleQuoteSubmit = async (e) => {
    e.preventDefault();
    if (!quoteForm.name.trim() || !quoteForm.email.trim()) {
      setQuoteError(t('quote.error.required'));
      return;
    }
    setQuoteError('');
    setQuoteLoading(true);
    try {
      await submitQuoteRequest({ ...quoteForm, plan: quotePlan });
      setQuoteSubmitted(true);
    } catch {
      setQuoteError(t('quote.error.generic'));
    } finally {
      setQuoteLoading(false);
    }
  };

  const activeTabObj = previewTabIds.find(t0 => t0.id === activeTab) || previewTabIds[0];
  const activeCoreObj = coreCategoryIds.find(c => c.id === activeCore) || coreCategoryIds[0];
  const activeCoreLabel = t(`core.${activeCoreObj.id}.title`);

  return (
    <div className="lp">
      {/* ── Header ───────────────────────────── */}
      <header className="lp-header">
        <Link to="/" className="lp-brand">
          <span className="lp-brand-icon">◆</span> {t('nav.brand')}
        </Link>
        <nav className="lp-nav">
          <a href="#preview">{t('nav.product')}</a>
          <a href="#core">{t('nav.platform')}</a>
          <a href="#features">{t('nav.features')}</a>
          <a href="#deploy">{t('nav.deploy')}</a>
          <a href="#pricing">{t('nav.pricing')}</a>
          <Link to="/docs">{t('nav.docs')}</Link>
          <Link to="/blog">{t('nav.blog')}</Link>
          <Link to="/live" className="lp-live-link"><span className="lp-live-dot" />{t('nav.live')}</Link>
        </nav>
        <div className="lp-header-actions">
          <LanguageToggle />
          <Link to="/login" className="lp-btn-ghost">{t('nav.signin')}</Link>
          <Link to="/request-trial" className="lp-btn-primary-sm">{t('nav.requestTrial')}</Link>
        </div>
      </header>

      {/* ── Hero ─────────────────────────────── */}
      <section className="lp-hero lpx-hero">
        <div className="lp-hero-badge">{t('hero.badge')}</div>
        <h1>
          {t('hero.title.before')} <span className="lp-gradient-text">{t('hero.title.gradient')}</span><br />
          {t('hero.title.after')}
        </h1>
        <p className="lp-hero-sub">{t('hero.sub')}</p>
        <div className="lp-hero-actions">
          <Link to="/docs" className="lp-btn-primary">{t('hero.cta.start')}</Link>
          <a href="#preview" className="lp-btn-outline">{t('hero.cta.preview')}</a>
          <Link to="/live" className="lp-btn-outline"><span className="lp-live-dot" /> {t('hero.cta.live')}</Link>
        </div>
        <div className="lp-hero-proof">
          <span>{t('hero.proof.private')}</span>
          <span>{t('hero.proof.noMarkup')}</span>
          <span>{t('hero.proof.unlimited')}</span>
          <span>{t('hero.proof.deploy')}</span>
        </div>
      </section>

      {/* ── App Preview (tabbed) ──────────────── */}
      <section id="preview" className="lpx-section">
        <div className="lpx-overline">{t('preview.overline')}</div>
        <h2 className="lpx-title">{t('preview.title')}</h2>
        <p className="lpx-lead">{t('preview.lead')}</p>

        <div className="lpx-preview-shell">
          <div className="lpx-preview-tabs">
            {previewTabIds.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`lpx-preview-tab ${activeTab === tab.id ? 'is-active' : ''}`}
              >
                <span className="lpx-preview-tab-icon">{tab.icon}</span> {t(`preview.tab.${tab.id}`)}
              </button>
            ))}
          </div>
          <div className="lpx-preview-window">
            <div className="lpx-preview-chrome">
              <span className="lpx-chrome-dot" style={{ background: '#ef4444' }} />
              <span className="lpx-chrome-dot" style={{ background: '#f59e0b' }} />
              <span className="lpx-chrome-dot" style={{ background: '#22c55e' }} />
              <span className="lpx-chrome-url">bob-labs · {t(`preview.tab.${activeTabObj.id}`)}</span>
            </div>
            <div className="lpx-preview-body lpx-preview-body-shot">
              <PreviewScreenshot src={activeTabObj.src} label={t(`preview.tab.${activeTabObj.id}`)} />
            </div>
          </div>
        </div>
      </section>

      {/* ── Core Platform ─────────────────────── */}
      <section id="core" className="lpx-section lpx-section-alt">
        <div className="lpx-overline">{t('core.overline')}</div>
        <h2 className="lpx-title">{t('core.title.line1')}<br />{t('core.title.line2')}</h2>

        <div className="lpx-core">
          <div className="lpx-core-list">
            {coreCategoryIds.map(c => (
              <button
                key={c.id}
                onClick={() => setActiveCore(c.id)}
                className={`lpx-core-card ${activeCore === c.id ? 'is-active' : ''}`}
              >
                <div className="lpx-core-icon"><c.Icon /></div>
                <div className="lpx-core-text">
                  <div className="lpx-core-title">{t(`core.${c.id}.title`)}</div>
                  <div className="lpx-core-sub">{t(`core.${c.id}.sub`)}</div>
                </div>
              </button>
            ))}
          </div>

          <div className="lpx-core-panel">
            <div className="lpx-preview-chrome">
              <span className="lpx-chrome-dot" style={{ background: '#ef4444' }} />
              <span className="lpx-chrome-dot" style={{ background: '#f59e0b' }} />
              <span className="lpx-chrome-dot" style={{ background: '#22c55e' }} />
              <span className="lpx-chrome-url">{activeCoreLabel}</span>
            </div>
            <div className="lpx-core-body">
              <CorePreview id={activeCore} />
              <ul className="lpx-core-bullets">
                {Array.from({ length: activeCoreObj.bullets }, (_, i) => (
                  <li key={i}>{t(`core.${activeCoreObj.id}.b${i + 1}`)}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ── Comprehensive Features ─────────────── */}
      <section id="features" className="lpx-section">
        <div className="lpx-overline">{t('features.overline')}</div>
        <h2 className="lpx-title">{t('features.title')}</h2>
        <p className="lpx-lead">{t('features.lead')}</p>
        <div className="lpx-features-grid">
          {featureIds.map(f => (
            <div key={f.id} className="lpx-feature-card">
              <div className="lpx-feature-icon"><f.Icon /></div>
              <h3>{t(`feat.${f.id}.title`)}</h3>
              <p>{t(`feat.${f.id}.body`)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Deploy in 2 commands ──────────────── */}
      <section id="deploy" className="lpx-section lpx-section-alt">
        <div className="lpx-overline">{t('deploy.overline')}</div>
        <h2 className="lpx-title">{t('deploy.title.before')} <code>git clone</code> {t('deploy.title.after')}</h2>
        <p className="lpx-lead">{t('deploy.lead')}</p>

        <div className="lpx-deploy-grid">
          <div className="lpx-terminal">
            <div className="lpx-preview-chrome">
              <span className="lpx-chrome-dot" style={{ background: '#ef4444' }} />
              <span className="lpx-chrome-dot" style={{ background: '#f59e0b' }} />
              <span className="lpx-chrome-dot" style={{ background: '#22c55e' }} />
              <span className="lpx-chrome-url">your-server ~ $</span>
            </div>
            <pre className="lpx-terminal-body">{`$ git clone https://github.com/bob-labs/bob-manager
$ cd bob-manager && docker compose up -d

✔ control-plane    started
✔ bob-db           healthy
✔ bob-ui           listening on :3000
✔ rag-sidecar      ready
✔ sandbox-runtime  ready

🚀 Bob Labs is live at http://your-server:3000`}</pre>
          </div>
          <div className="lpx-deploy-copy">
            <h3>{t('deploy.copy.title')}</h3>
            <ul className="lpx-deploy-list">
              <li><strong>{t('deploy.copy.b1.strong')}</strong> {t('deploy.copy.b1.body')}</li>
              <li><strong>{t('deploy.copy.b2.strong')}</strong> {t('deploy.copy.b2.body')}</li>
              <li><strong>{t('deploy.copy.b3.strong')}</strong> {t('deploy.copy.b3.body')}</li>
              <li><strong>{t('deploy.copy.b4.strong')}</strong> {t('deploy.copy.b4.body')}</li>
            </ul>
            <div className="lp-hero-actions" style={{ marginTop: '1.5rem' }}>
              <Link to="/docs" className="lp-btn-primary">{t('deploy.cta.docs')}</Link>
              <a href="https://github.com/bob-labs/bob-manager" target="_blank" rel="noopener noreferrer" className="lp-btn-outline">{t('deploy.cta.github')}</a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Private vs Enterprise ─────────────── */}
      <section className="lpx-section">
        <div className="lpx-overline">{t('split.overline')}</div>
        <h2 className="lpx-title">{t('split.title')}</h2>
        <div className="lpx-split">
          <div className="lpx-split-card">
            <div className="lpx-split-h">{t('split.private.title')}</div>
            <ul>
              <li>{t('split.private.b1')}</li>
              <li>{t('split.private.b2')}</li>
              <li>{t('split.private.b3')}</li>
              <li>{t('split.private.b4')}</li>
            </ul>
          </div>
          <div className="lpx-split-card lpx-split-featured">
            <div className="lpx-split-h">{t('split.enterprise.title')}</div>
            <ul>
              <li>{t('split.enterprise.b1')}</li>
              <li>{t('split.enterprise.b2')}</li>
              <li>{t('split.enterprise.b3')}</li>
              <li>{t('split.enterprise.b4')}</li>
            </ul>
          </div>
        </div>
      </section>

      {/* ── Pricing ──────────────────────────── */}
      <section id="pricing" className="lpx-section lpx-section-alt">
        <div className="lpx-overline">{t('pricing.overline')}</div>
        <h2 className="lpx-title">{t('pricing.title')}</h2>
        <div className="lp-grid lp-grid-4">
          <div className="lp-price-card">
            <h3>{t('pricing.openSource.title')}</h3>
            <div className="lp-price">{t('pricing.openSource.price')}</div>
            <p>{t('pricing.openSource.body')}</p>
            <Link to="/docs" className="lp-btn-outline lp-btn-block">{t('pricing.openSource.cta')}</Link>
          </div>
          <div className="lp-price-card">
            <h3>{t('pricing.pilot.title')}</h3>
            <div className="lp-price">{t('pricing.custom')}</div>
            <p>{t('pricing.pilot.body')}</p>
            <button onClick={() => openQuote(t('plan.privatePilot'))} className="lp-btn-outline lp-btn-block">{t('pricing.cta.quote')}</button>
          </div>
          <div className="lp-price-card lp-price-card-featured">
            <h3>{t('pricing.production.title')}</h3>
            <div className="lp-price">{t('pricing.custom')}</div>
            <p>{t('pricing.production.body')}</p>
            <button onClick={() => openQuote(t('plan.production'))} className="lp-btn-primary lp-btn-block">{t('pricing.cta.quote')}</button>
          </div>
          <div className="lp-price-card">
            <h3>{t('pricing.support.title')}</h3>
            <div className="lp-price">{t('pricing.custom')}</div>
            <p>{t('pricing.support.body')}</p>
            <button onClick={() => openQuote(t('plan.enterpriseSupport'))} className="lp-btn-outline lp-btn-block">{t('pricing.cta.quote')}</button>
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────── */}
      <section className="lp-cta">
        <h2>{t('cta.title')}</h2>
        <p>{t('cta.body')}</p>
        <div className="lp-hero-actions">
          <Link to="/docs" className="lp-btn-primary">{t('cta.docs')}</Link>
          <Link to="/request-trial" className="lp-btn-outline">{t('cta.trial')}</Link>
        </div>
      </section>

      {/* ── Footer ───────────────────────────── */}
      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <div className="lp-footer-brand">
            <span className="lp-brand">
              <span className="lp-brand-icon">◆</span> {t('nav.brand')}
            </span>
            <p>{t('footer.tagline')}</p>
          </div>
          <nav className="lp-footer-links">
            <div>
              <h4>{t('footer.product.title')}</h4>
              <a href="#preview">{t('footer.product.tour')}</a>
              <a href="#core">{t('footer.product.core')}</a>
              <a href="#features">{t('footer.product.features')}</a>
              <a href="#pricing">{t('footer.product.pricing')}</a>
            </div>
            <div>
              <h4>{t('footer.resources.title')}</h4>
              <Link to="/docs">{t('footer.resources.docs')}</Link>
              <a href="https://github.com/bob-labs/bob-manager" target="_blank" rel="noopener noreferrer">{t('footer.resources.github')}</a>
              <Link to="/blog">{t('footer.resources.blog')}</Link>
            </div>
            <div>
              <h4>{t('footer.company.title')}</h4>
              <a href="mailto:support@boblabs.eu">{t('footer.company.contact')}</a>
              <Link to="/request-trial">{t('footer.company.trial')}</Link>
            </div>
          </nav>
        </div>
        <div className="lp-footer-bottom">
          <p>{t('footer.copyright', { year: new Date().getFullYear() })}</p>
        </div>
      </footer>

      {/* ── Quote Request Modal ──────────────── */}
      {showQuoteModal && (
        <div className="admin-modal-overlay" onClick={() => setShowQuoteModal(false)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
            {quoteSubmitted ? (
              <>
                <h2>{t('quote.success.title')}</h2>
                <p style={{ color: '#059669', margin: '1rem 0' }}>{t('quote.success.body')}</p>
                <button className="login-btn" onClick={() => setShowQuoteModal(false)}>{t('quote.close')}</button>
              </>
            ) : (
              <>
                <h2>{t('quote.title')} — {quotePlan}</h2>
                <p style={{ color: '#6b7280', margin: '0 0 1rem' }}>{t('quote.intro')}</p>
                <form onSubmit={handleQuoteSubmit}>
                  <input type="text" placeholder={t('quote.field.name')} className="login-input" required
                    value={quoteForm.name} onChange={(e) => setQuoteForm(f => ({ ...f, name: e.target.value }))} />
                  <input type="email" placeholder={t('quote.field.email')} className="login-input" required
                    value={quoteForm.email} onChange={(e) => setQuoteForm(f => ({ ...f, email: e.target.value }))} />
                  <input type="text" placeholder={t('quote.field.company')} className="login-input"
                    value={quoteForm.company} onChange={(e) => setQuoteForm(f => ({ ...f, company: e.target.value }))} />
                  <input type="tel" placeholder={t('quote.field.phone')} className="login-input"
                    value={quoteForm.phone} onChange={(e) => setQuoteForm(f => ({ ...f, phone: e.target.value }))} />
                  <textarea placeholder={t('quote.field.description')} className="login-input" rows={4}
                    style={{ resize: 'vertical' }}
                    value={quoteForm.description} onChange={(e) => setQuoteForm(f => ({ ...f, description: e.target.value }))} />
                  {quoteError && <p className="login-error">{quoteError}</p>}
                  <button type="submit" className="login-btn" disabled={quoteLoading} style={{ marginTop: '0.5rem' }}>
                    {quoteLoading ? t('quote.submit.loading') : t('quote.submit')}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
