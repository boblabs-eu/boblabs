/**
 * Bob Manager — Status badge component.
 */

import React from 'react';

const statusMap = {
  online: 'badge-online',
  offline: 'badge-offline',
  running: 'badge-online',
  success: 'badge-online',
  failed: 'badge-offline',
  pending: 'badge-warning',
  warning: 'badge-warning',
};

export default function StatusBadge({ status }) {
  const cls = statusMap[status] || 'badge-info';
  return <span className={`badge ${cls}`}>{status}</span>;
}
