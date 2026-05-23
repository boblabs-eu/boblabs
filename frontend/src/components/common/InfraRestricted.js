/**
 * Bob Manager — InfraRestricted wrapper.
 * Shows a friendly message when a user gets a 403 infra_restricted error.
 */

import React, { useState, useEffect } from 'react';

const INFRA_MESSAGE =
  'Curious? Deploy Bob Labs on your own infrastructure to explore server management, workflows, and terminal access.';

/**
 * Wraps an infra page. Catches 403 infra_restricted from the initial data load
 * and shows a friendly message instead.
 *
 * Usage:
 *   <InfraRestricted loadFn={() => getServers()}>
 *     <ServersPageContent data={...} />
 *   </InfraRestricted>
 *
 * Or simply use the `infraRestricted` state:
 *   const [restricted, setRestricted] = useState(false);
 *   ... catch 403 → setRestricted(true)
 *   if (restricted) return <InfraRestrictedMessage />;
 */
export function InfraRestrictedMessage() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      padding: '2rem',
      textAlign: 'center',
    }}>
      <div style={{
        fontSize: '3rem',
        marginBottom: '1rem',
      }}>
        🔒
      </div>
      <h2 style={{
        fontSize: '1.5rem',
        fontWeight: 600,
        color: '#1e1b4b',
        marginBottom: '1rem',
      }}>
        Infrastructure Access Required
      </h2>
      <p style={{
        fontSize: '1rem',
        color: '#6b7280',
        maxWidth: '500px',
        lineHeight: 1.6,
      }}>
        {INFRA_MESSAGE}
      </p>
    </div>
  );
}

/**
 * Helper: returns true if an axios error is a 403 infra_restricted.
 */
export function isInfraRestricted(error) {
  return (
    error?.response?.status === 403 &&
    error?.response?.data?.detail === 'infra_restricted'
  );
}

export default InfraRestrictedMessage;
