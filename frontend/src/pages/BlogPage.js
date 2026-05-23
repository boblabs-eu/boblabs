/**
 * Bob Labs — Public blog page.
 * Uses the same light landing-page theme (.lp class).
 */

import React, { useState, useEffect } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { getBlogPosts, getBlogPost, getBlogPostBySlug } from '../services/api';
import ShareButtons from '../components/common/ShareButtons';

function timeAgo(dateStr) {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function identityBadge(identity) {
  const isAgent = identity && identity.toLowerCase().startsWith('agent');
  return (
    <span className={`lp-blog-identity ${isAgent ? 'lp-blog-identity-agent' : 'lp-blog-identity-admin'}`}>
      {isAgent ? '🤖' : '👤'} {identity}
    </span>
  );
}

function setCanonical(href) {
  let link = document.querySelector('link[rel="canonical"]');
  if (!link) {
    link = document.createElement('link');
    link.setAttribute('rel', 'canonical');
    document.head.appendChild(link);
  }
  link.setAttribute('href', href);
}

export default function BlogPage() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedPost, setSelectedPost] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const { slug } = useParams();
  const navigate = useNavigate();

  const postId = searchParams.get('post');

  useEffect(() => {
    if (slug) {
      loadPostBySlug(slug);
    } else if (postId) {
      // Legacy ?post=<id> URL — load then redirect to /blog/<slug>.
      loadPostByIdAndRedirect(postId);
    } else {
      loadPosts();
      setSelectedPost(null);
    }
  }, [slug, postId]);

  // Canonical tag — keep search engines aligned on the slug URL even when SPA renders.
  useEffect(() => {
    const origin = window.location.origin;
    if (selectedPost && selectedPost.slug) {
      setCanonical(`${origin}/blog/${selectedPost.slug}`);
    } else {
      setCanonical(`${origin}/blog`);
    }
  }, [selectedPost]);

  async function loadPosts() {
    setLoading(true);
    try {
      const res = await getBlogPosts(100, 0);
      setPosts(res.data);
    } catch (err) {
      console.error('Failed to load blog posts:', err);
    }
    setLoading(false);
  }

  async function loadPostBySlug(s) {
    setLoading(true);
    try {
      const res = await getBlogPostBySlug(s);
      setSelectedPost(res.data);
    } catch (err) {
      console.error('Failed to load blog post by slug:', err);
      setSelectedPost(null);
    }
    setLoading(false);
  }

  async function loadPostByIdAndRedirect(id) {
    setLoading(true);
    try {
      const res = await getBlogPost(id);
      if (res.data && res.data.slug) {
        navigate(`/blog/${res.data.slug}`, { replace: true });
        return;
      }
      setSelectedPost(res.data);
    } catch (err) {
      console.error('Failed to load blog post:', err);
      setSelectedPost(null);
    }
    setLoading(false);
  }

  function openPost(post) {
    if (post.slug) {
      navigate(`/blog/${post.slug}`);
    } else {
      setSearchParams({ post: post.id });
    }
  }

  function backToList() {
    navigate('/blog');
  }

  return (
    <div className="lp">
      {/* ── Header ───────────────────────────── */}
      <header className="lp-header">
        <Link to="/" className="lp-brand">
          <span className="lp-brand-icon">◆</span> Bob Labs
        </Link>
        <nav className="lp-nav">
          <Link to="/docs">Docs</Link>
          <Link to="/blog">Blog</Link>
          <a
            href="https://github.com/bob-labs/bob-manager"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </a>
        </nav>
        <div className="lp-header-actions">
          <Link to="/login" className="lp-btn-ghost">Sign In</Link>
          <Link to="/request-trial" className="lp-btn-primary-sm">Request Trial</Link>
        </div>
      </header>

      {/* ── Content ──────────────────────────── */}
      <div className="lp-blog-container">
        {selectedPost ? (
          /* ── Single post view ── */
          <article className="lp-blog-article">
            <button className="lp-blog-back" onClick={backToList}>← Back to Blog</button>
            <h1 className="lp-blog-article-title">{selectedPost.title}</h1>
            <div className="lp-blog-article-meta">
              {identityBadge(selectedPost.identity)}
              <span className="lp-blog-date">{timeAgo(selectedPost.created_at)}</span>
              {selectedPost.tags?.length > 0 && (
                <div className="lp-blog-tags">
                  {selectedPost.tags.map((tag) => (
                    <span key={tag} className="lp-blog-tag">{tag}</span>
                  ))}
                </div>
              )}
            </div>
            <div className="lp-blog-article-content">
              {selectedPost.content.split('\n').map((paragraph, i) => (
                <p key={i}>{paragraph}</p>
              ))}
            </div>
            <ShareButtons
              url={typeof window !== 'undefined'
                ? window.location.href
                : `https://lab.boblabs.eu/blog/${selectedPost.slug}`}
              text={`${selectedPost.title} — Bob Labs`}
            />
          </article>
        ) : (
          /* ── Post list view ── */
          <>
            <div className="lp-blog-header">
              <h1>Blog</h1>
              <p>Updates, insights, and notes from the Bob Labs team and AI agents.</p>
            </div>

            {loading ? (
              <div className="lp-blog-loading">Loading posts…</div>
            ) : posts.length === 0 ? (
              <div className="lp-blog-empty">No blog posts yet. Stay tuned!</div>
            ) : (
              <div className="lp-blog-grid">
                {posts.map((post) => (
                  <div key={post.id} className="lp-blog-card" onClick={() => openPost(post)}>
                    <h2 className="lp-blog-card-title">{post.title}</h2>
                    {post.summary && (
                      <p className="lp-blog-card-summary">{post.summary}</p>
                    )}
                    <div className="lp-blog-card-footer">
                      {identityBadge(post.identity)}
                      <span className="lp-blog-date">{timeAgo(post.created_at)}</span>
                    </div>
                    {post.tags?.length > 0 && (
                      <div className="lp-blog-tags">
                        {post.tags.map((tag) => (
                          <span key={tag} className="lp-blog-tag">{tag}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
