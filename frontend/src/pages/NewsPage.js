/**
 * Bob Manager — News feed page.
 * Displays news articles from RSS feeds, filterable by category.
 */

import React, { useState, useEffect } from 'react';
import { getNews } from '../services/api';
import { IC } from '../components/common/Icons';

const CATEGORIES = [
  { value: '', label: 'All News' },
  { value: 'geopolitics', label: 'Geopolitics' },
  { value: 'market', label: 'Market' },
  { value: 'global', label: 'Global' },
  { value: 'crypto', label: 'Crypto' },
];

const categoryColors = {
  geopolitics: { bg: 'rgba(239,68,68,0.12)', color: '#ef4444' },
  market: { bg: 'rgba(59,130,246,0.12)', color: '#3b82f6' },
  global: { bg: 'rgba(34,197,94,0.12)', color: '#22c55e' },
  crypto: { bg: 'rgba(251,191,36,0.12)', color: '#fbbf24' },
};

export default function NewsPage() {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState('');

  useEffect(() => {
    loadNews();
  }, [category]);

  async function loadNews() {
    setLoading(true);
    try {
      const res = await getNews(category || undefined, 80);
      setArticles(res.data);
    } catch (err) {
      console.error('Failed to load news:', err);
    }
    setLoading(false);
  }

  function timeAgo(dateStr) {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return dateStr;
      const diff = (Date.now() - date.getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch {
      return dateStr;
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1><IC.newspaper size={24} style={{ marginRight: '0.5rem' }} /> News Feed</h1>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              className={`btn ${category === cat.value ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setCategory(cat.value)}
              style={{ fontSize: '0.8rem', padding: '0.35rem 0.7rem' }}
            >
              {cat.label}
            </button>
          ))}
          <button className="btn btn-outline" onClick={loadNews} style={{ marginLeft: '0.5rem' }}>
            <IC.refresh size={16} />
          </button>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
          <IC.loader size={24} /> Loading news…
        </div>
      )}

      {!loading && articles.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>No articles found. Try a different category or check your connection.</p>
        </div>
      )}

      {!loading && articles.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {articles.map((article, i) => {
            const catStyle = categoryColors[article.category] || { bg: 'rgba(168,85,247,0.12)', color: '#a855f7' };
            return (
              <div
                key={i}
                className="card"
                style={{ padding: '0.75rem 1rem', cursor: 'pointer', transition: 'border-color 0.15s' }}
                onClick={() => window.open(article.link, '_blank')}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem', flexWrap: 'wrap' }}>
                      <span style={{
                        fontSize: '0.65rem',
                        padding: '0.1rem 0.4rem',
                        borderRadius: '9999px',
                        background: catStyle.bg,
                        color: catStyle.color,
                        fontWeight: 600,
                        textTransform: 'uppercase',
                      }}>
                        {article.category}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{article.source}</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{timeAgo(article.pub_date)}</span>
                    </div>
                    <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.25rem', lineHeight: 1.3 }}>
                      {article.title}
                    </h3>
                    {article.description && (
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.4, margin: 0 }}>
                        {article.description.slice(0, 200)}{article.description.length > 200 ? '…' : ''}
                      </p>
                    )}
                  </div>
                  <IC.externalLink size={16} style={{ color: 'var(--text-muted)', flexShrink: 0, marginTop: '0.2rem' }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
