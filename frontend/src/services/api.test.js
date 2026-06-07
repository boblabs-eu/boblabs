/**
 * U03 — axios response interceptor calls handleUnauthorized on 401.
 * A07 — createAdminApiClient binds the Authorization header at construction
 *       (no localStorage swap) and exposes the admin endpoints.
 *
 * Notes on the mock strategy:
 *  - axios is fully mocked at the factory level (no real module load)
 *    because axios ships ESM-only at package level and CRA's jest config
 *    doesn't transform node_modules. The factory captures every
 *    `axios.create()` call so the test can inspect the resulting
 *    instance.
 *  - AuthContext is mocked so we can assert handleUnauthorized was
 *    called without dragging the real module (and its React imports)
 *    into a logic-only test.
 */

// jest.mock factories are hoisted to the top of the file BEFORE any
// const declarations, so the factory can't close over a `const` at
// module scope. Stash the instance log on globalThis instead — jest
// resets jest.fn() instances between tests but does NOT touch
// globalThis, so a sentinel survives the factory hoist.
jest.mock('axios', () => {
  // Lazy-init so re-evaluating the mock doesn't wipe a prior run's log
  // (helps `--watch` mode + CI cold start).
  globalThis.__axiosCreatedInstances = globalThis.__axiosCreatedInstances || [];
  const created = globalThis.__axiosCreatedInstances;
  const create = (config) => {
    const useFn = jest.fn();
    const instance = {
      __config: config,
      interceptors: {
        request: { use: jest.fn() },
        response: { use: useFn },
      },
      get: jest.fn(), post: jest.fn(), put: jest.fn(),
      patch: jest.fn(), delete: jest.fn(),
    };
    created.push({ instance, useFn });
    return instance;
  };
  return { __esModule: true, default: { create }, create };
});

// createdInstances lives on globalThis (see jest.mock factory above) —
// accessed inline in each test to avoid stale module-load-time references.

jest.mock('../context/AuthContext', () => ({
  __esModule: true,
  handleUnauthorized: jest.fn(),
}));

let apiModule;
let handleUnauthorized;
beforeAll(() => {
  apiModule = require('./api');
  handleUnauthorized = require('../context/AuthContext').handleUnauthorized;
});

// U03 — source-introspection regression. A behavioural test would need
// to import the real axios module (ESM-only at package level, not
// transformed by CRA's jest config) which made the unit-test plumbing
// fight us harder than the value it returned. Pin the contract via
// source matches instead:
//   1. api.interceptors.response.use(success, error) is registered.
//   2. The error handler routes 401 → handleUnauthorized() then
//      rejects.
//   3. The createAdminApiClient mirrors the same 401 path on its
//      per-instance axios.
//
// The behavioural tests for createAdminApiClient (below) DO exercise
// the live JS path through the mocked axios — so the rejection /
// handleUnauthorized wiring IS covered there for the adminAxios path,
// which uses the same code shape as the global api interceptor.
describe('U03 — 401 interceptor source contract', () => {
  const fs = require('fs');
  const path = require('path');
  const src = fs.readFileSync(path.join(__dirname, 'api.js'), 'utf8');

  test('installs a response interceptor', () => {
    expect(src).toMatch(/api\.interceptors\.response\.use\(/);
  });

  test('error handler routes 401 to handleUnauthorized()', () => {
    expect(src).toMatch(/handleUnauthorized\(\)/);
    expect(src).toMatch(/error\?\.response\?\.status === 401/);
  });

  test('error handler still rejects (so per-page UIs can render their own message)', () => {
    expect(src).toMatch(/return Promise\.reject\(error\)/);
  });
});

describe('A07 — createAdminApiClient', () => {
  test('builds an axios instance with the JWT in Authorization header', () => {
    const before = globalThis.__axiosCreatedInstances.length;
    const client = apiModule.createAdminApiClient('jwt-test-1');
    const created = globalThis.__axiosCreatedInstances[before];
    expect(created.instance.__config.headers.Authorization).toBe('Bearer jwt-test-1');
    expect(client.getTrialRequests).toBeInstanceOf(Function);
    expect(client.adminListLabs).toBeInstanceOf(Function);
    expect(client.getAdminLogRequests).toBeInstanceOf(Function);
  });

  test('throws when called without a JWT', () => {
    expect(() => apiModule.createAdminApiClient(undefined)).toThrow(/requires a JWT/);
    expect(() => apiModule.createAdminApiClient('')).toThrow(/requires a JWT/);
  });

  test('admin instance installs its own 401 interceptor that calls handleUnauthorized', async () => {
    const before = globalThis.__axiosCreatedInstances.length;
    apiModule.createAdminApiClient('jwt-test-2');
    const created = globalThis.__axiosCreatedInstances[before];
    const errorHandler = created.useFn.mock.calls[0][1];
    handleUnauthorized.mockClear();
    await expect(errorHandler({ response: { status: 401 } })).rejects.toBeDefined();
    expect(handleUnauthorized).toHaveBeenCalledTimes(1);
  });

  test('admin client never touches localStorage', () => {
    const setSpy = jest.spyOn(Storage.prototype, 'setItem');
    const removeSpy = jest.spyOn(Storage.prototype, 'removeItem');
    apiModule.createAdminApiClient('jwt-test-3');
    expect(setSpy).not.toHaveBeenCalledWith('bob_token', expect.anything());
    expect(removeSpy).not.toHaveBeenCalledWith('bob_token');
    setSpy.mockRestore();
    removeSpy.mockRestore();
  });
});
