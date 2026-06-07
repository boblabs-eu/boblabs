/**
 * Bob Manager — Auth context.
 * Manages JWT token in localStorage and provides login/logout helpers.
 *
 * U02 — bootstrap purges an expired token so the UI doesn't render in
 * "authenticated" state until the first 401 round-trip. Login schedules
 * a setTimeout aligned to the JWT `exp` claim so the user is logged
 * out at the moment the token actually expires (not on next API call).
 *
 * U03 — the global 401 interceptor in services/api.js imports
 * `handleUnauthorized` from this file to trigger logout from anywhere
 * (no React tree access required).
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

import { getTokenExpiryMs, isTokenExpired } from '../utils/jwt';

const STORAGE_KEY = 'bob_token';

// U03 — single global handler so a 401 from any code path (axios
// response interceptor, fetch, websocket reconnect) can trigger
// logout without holding a ref to the React context. The provider
// registers/clears the callback in its lifecycle.
let _externalLogout = null;

export function handleUnauthorized() {
  if (_externalLogout) {
    _externalLogout();
  } else {
    // No provider mounted (e.g., the public LiveLab page) — still
    // wipe the stored token so a stale value doesn't survive in
    // localStorage.
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
  }
}

const AuthContext = createContext(null);

function readInitialToken() {
  try {
    const tok = localStorage.getItem(STORAGE_KEY);
    // U02 — refuse to start the app in an "authenticated" state with
    // an already-expired token. Drop it immediately.
    if (tok && isTokenExpired(tok)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return tok;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(readInitialToken);
  const expiryTimerRef = useRef(null);

  const clearExpiryTimer = useCallback(() => {
    if (expiryTimerRef.current) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  }, []);

  const logout = useCallback(() => {
    clearExpiryTimer();
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    setToken(null);
  }, [clearExpiryTimer]);

  const scheduleExpiry = useCallback((jwt) => {
    clearExpiryTimer();
    const expMs = getTokenExpiryMs(jwt);
    if (expMs === null) return;
    // U02 — fire the logout 5 seconds before the real exp so the next
    // user action doesn't race the token's death by a couple of ms.
    const ms = expMs - Date.now() - 5000;
    if (ms <= 0) {
      // Already expired (or within the skew) — log out now.
      logout();
      return;
    }
    // setTimeout's max int32 cap is ~24.8 days — JWTs are usually shorter
    // so this matters only for the longest-lived tokens; clamp to be safe.
    expiryTimerRef.current = setTimeout(logout, Math.min(ms, 0x7fffffff));
  }, [clearExpiryTimer, logout]);

  const login = useCallback((jwt) => {
    try { localStorage.setItem(STORAGE_KEY, jwt); } catch { /* ignore */ }
    setToken(jwt);
    scheduleExpiry(jwt);
  }, [scheduleExpiry]);

  // U02 — schedule expiry for the token we boot with (page refresh,
  // tab open) so the auto-logout fires even without a fresh login.
  useEffect(() => {
    if (token) scheduleExpiry(token);
    return clearExpiryTimer;
  }, [token, scheduleExpiry, clearExpiryTimer]);

  // U03 — register this provider's logout as the global 401 handler.
  useEffect(() => {
    _externalLogout = logout;
    return () => {
      if (_externalLogout === logout) _externalLogout = null;
    };
  }, [logout]);

  return (
    <AuthContext.Provider value={{ token, isAuthenticated: !!token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
