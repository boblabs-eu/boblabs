/**
 * Bob Manager — Permission hook.
 * Decodes JWT to extract user email and role for client-side permission checks.
 */

import { useMemo } from 'react';
import { useAuth } from '../context/AuthContext';

function decodeJwtPayload(token) {
  try {
    const base64 = token.split('.')[1];
    const json = atob(base64.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return {};
  }
}

/**
 * Returns { email, role, isAdmin, canEdit, canView, canDelete, canManage }
 * for a given resource's ACL.
 */
export function usePermission(acl) {
  const { token } = useAuth();

  return useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : {};
    const email = payload.sub || '';
    const role = payload.role || '';
    const isAdmin = role === 'admin';

    if (!acl) {
      return { email, role, isAdmin, canView: isAdmin, canEdit: isAdmin, canDelete: isAdmin, canManage: isAdmin };
    }

    const isOwner = acl.owner === email;
    const isEditor = (acl.editors || []).includes(email);
    const isViewer = (acl.viewers || []).includes(email);

    return {
      email,
      role,
      isAdmin,
      canView: isAdmin || isOwner || isEditor || isViewer,
      canEdit: isAdmin || isOwner || isEditor,
      canDelete: isAdmin || isOwner,
      canManage: isAdmin || isOwner,
    };
  }, [token, acl]);
}

/**
 * Returns user info from JWT: { email, role, isAdmin }
 */
export function useCurrentUser() {
  const { token } = useAuth();
  return useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : {};
    return {
      email: payload.sub || '',
      role: payload.role || '',
      isAdmin: payload.role === 'admin',
    };
  }, [token]);
}
