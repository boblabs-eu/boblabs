/**
 * JWT helpers shared by AuthContext, services/api, and any future
 * client-side permission code. The old usePermission.js had a private
 * `decodeJwtPayload` that nothing in the app actually called — U01
 * removed the dead hook and centralized the primitive here.
 *
 * Nothing here verifies the JWT signature — that lives server-side.
 * These helpers are for UX decisions (is the token expired? when to
 * proactively log out?) where a wrong client-side guess costs at most
 * one extra 401 round-trip.
 */

export function decodeJwtPayload(token) {
  if (!token || typeof token !== 'string') return {};
  try {
    const b64 = token.split('.')[1];
    if (!b64) return {};
    const json = atob(b64.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return {};
  }
}

/**
 * Returns the JWT `exp` claim as a JS-millisecond timestamp,
 * or null if the claim is missing / non-numeric.
 */
export function getTokenExpiryMs(token) {
  const payload = decodeJwtPayload(token);
  const exp = payload && payload.exp;
  if (typeof exp !== 'number' || !Number.isFinite(exp)) return null;
  return exp * 1000;
}

/**
 * U02 — true when the token's `exp` claim is in the past (or missing).
 * Allows a small `skewMs` so a clock drift of a few seconds doesn't
 * log the user out one tick early.
 */
export function isTokenExpired(token, skewMs = 5000) {
  const expMs = getTokenExpiryMs(token);
  if (expMs === null) return true;
  return Date.now() >= (expMs - skewMs);
}
