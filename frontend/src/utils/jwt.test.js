/**
 * U02 — JWT helpers.
 * Pure unit tests; no React, no axios, no DOM.
 */

import { decodeJwtPayload, getTokenExpiryMs, isTokenExpired } from './jwt';

// Helper: build a JWT-shaped string with the given payload (signature
// unused — we only care about decoding).
function makeJwt(payload) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = btoa(JSON.stringify(payload))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
  return `${header}.${body}.sig`;
}

describe('decodeJwtPayload', () => {
  test('decodes a well-formed token', () => {
    const tok = makeJwt({ sub: 'alice@example.com', role: 'admin', exp: 12345 });
    expect(decodeJwtPayload(tok)).toMatchObject({
      sub: 'alice@example.com',
      role: 'admin',
      exp: 12345,
    });
  });

  test('returns {} on null / empty / malformed input', () => {
    expect(decodeJwtPayload(null)).toEqual({});
    expect(decodeJwtPayload('')).toEqual({});
    expect(decodeJwtPayload('not.a.jwt')).toEqual({});
    expect(decodeJwtPayload('only-one-part')).toEqual({});
  });
});

describe('getTokenExpiryMs', () => {
  test('multiplies the JWT exp claim by 1000', () => {
    const tok = makeJwt({ sub: 'x', exp: 100 });
    expect(getTokenExpiryMs(tok)).toBe(100_000);
  });

  test('returns null when exp is missing or non-numeric', () => {
    expect(getTokenExpiryMs(makeJwt({ sub: 'x' }))).toBeNull();
    expect(getTokenExpiryMs(makeJwt({ sub: 'x', exp: 'soon' }))).toBeNull();
  });
});

describe('isTokenExpired', () => {
  const SECOND = 1000;

  test('past exp returns true', () => {
    const tok = makeJwt({ exp: Math.floor((Date.now() - 60 * SECOND) / 1000) });
    expect(isTokenExpired(tok)).toBe(true);
  });

  test('future exp returns false', () => {
    const tok = makeJwt({ exp: Math.floor((Date.now() + 60 * SECOND) / 1000) });
    expect(isTokenExpired(tok)).toBe(false);
  });

  test('missing exp returns true (fail-closed)', () => {
    const tok = makeJwt({ sub: 'no-exp' });
    expect(isTokenExpired(tok)).toBe(true);
  });

  test('null / empty token returns true', () => {
    expect(isTokenExpired(null)).toBe(true);
    expect(isTokenExpired('')).toBe(true);
  });

  test('respects skewMs — token a few seconds away is treated as expired', () => {
    const tok = makeJwt({ exp: Math.floor((Date.now() + 2 * SECOND) / 1000) });
    // Default 5s skew → 2s-from-expiry is treated as already expired.
    expect(isTokenExpired(tok)).toBe(true);
    // No skew → 2s-from-expiry is still valid.
    expect(isTokenExpired(tok, 0)).toBe(false);
  });
});
