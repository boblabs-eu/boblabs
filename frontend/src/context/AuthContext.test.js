/**
 * U02 — AuthContext bootstrap + auto-logout integration.
 * U03 — handleUnauthorized triggers logout.
 *
 * Uses @testing-library/react that ships with react-scripts.
 */

import React from 'react';
import { render, act, screen } from '@testing-library/react';

import { AuthProvider, useAuth, handleUnauthorized } from './AuthContext';

function makeJwt(payload) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = btoa(JSON.stringify(payload))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
  return `${header}.${body}.sig`;
}

function Probe() {
  const { isAuthenticated, token } = useAuth();
  return (
    <>
      <span data-testid="auth">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="token">{token || ''}</span>
    </>
  );
}

describe('AuthProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    jest.useRealTimers();
  });

  test('U02 — drops an already-expired token on bootstrap', () => {
    const past = makeJwt({ exp: Math.floor(Date.now() / 1000) - 60 });
    localStorage.setItem('bob_token', past);
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(localStorage.getItem('bob_token')).toBeNull();
  });

  test('U02 — keeps a future-exp token on bootstrap', () => {
    const future = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600 });
    localStorage.setItem('bob_token', future);
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId('auth').textContent).toBe('yes');
    expect(screen.getByTestId('token').textContent).toBe(future);
  });

  test('U02 — auto-logout fires when scheduled time elapses', () => {
    jest.useFakeTimers();
    // 30s lifetime, but the helper schedules at exp - 5000ms = 25 000 ms.
    const tok = makeJwt({ exp: Math.floor((Date.now() + 30_000) / 1000) });
    localStorage.setItem('bob_token', tok);
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId('auth').textContent).toBe('yes');

    act(() => {
      // Advance past the scheduled logout (30s exp - 5s skew = 25s).
      jest.advanceTimersByTime(26_000);
    });
    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(localStorage.getItem('bob_token')).toBeNull();
  });

  test('U03 — handleUnauthorized() triggers logout while provider is mounted', () => {
    const future = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600 });
    localStorage.setItem('bob_token', future);
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId('auth').textContent).toBe('yes');

    act(() => { handleUnauthorized(); });
    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(localStorage.getItem('bob_token')).toBeNull();
  });

  test('U03 — handleUnauthorized() outside the provider tree still wipes localStorage', () => {
    localStorage.setItem('bob_token', 'some-token');
    handleUnauthorized();
    expect(localStorage.getItem('bob_token')).toBeNull();
  });
});
