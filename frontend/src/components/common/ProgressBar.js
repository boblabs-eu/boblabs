/**
 * Bob Manager — Progress bar component.
 */

import React from 'react';

export default function ProgressBar({ value, color = 'blue', label }) {
  const colorClass =
    value > 90 ? 'red' : value > 70 ? 'yellow' : color;

  return (
    <div>
      {label && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{label}</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            {typeof value === 'number' ? `${value.toFixed(1)}%` : value}
          </span>
        </div>
      )}
      <div className="progress-bar">
        <div
          className={`progress-fill ${colorClass}`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}
