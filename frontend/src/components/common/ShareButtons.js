/**
 * Reusable share-action row for blog posts and public pages.
 * X / Bluesky / LinkedIn / Copy link. No external dependency.
 */

import React, { useCallback, useState } from 'react';
import './ShareButtons.css';

function buildShareLinks(url, text) {
  const u = encodeURIComponent(url);
  const t = encodeURIComponent(text);
  return {
    x: `https://twitter.com/intent/tweet?text=${t}&url=${u}`,
    bluesky: `https://bsky.app/intent/compose?text=${encodeURIComponent(`${text}\n${url}`)}`,
    linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
  };
}

export default function ShareButtons({ url, text, className }) {
  const [copied, setCopied] = useState(false);

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard might be denied — silent no-op */
    }
  }, [url]);

  if (!url) return null;
  const links = buildShareLinks(url, text || '');

  return (
    <div className={`share-buttons ${className || ''}`.trim()}>
      <a className="share-btn share-x" href={links.x} target="_blank" rel="noreferrer noopener">
        Share on X
      </a>
      <a className="share-btn share-bluesky" href={links.bluesky} target="_blank" rel="noreferrer noopener">
        Bluesky
      </a>
      <a className="share-btn share-linkedin" href={links.linkedin} target="_blank" rel="noreferrer noopener">
        LinkedIn
      </a>
      <button type="button" className="share-btn share-copy" onClick={onCopy}>
        {copied ? 'Copied ✓' : 'Copy link'}
      </button>
    </div>
  );
}
