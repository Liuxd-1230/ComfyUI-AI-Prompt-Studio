// Shared, short-lived frontend registry cache.
// Multiple APS nodes are often restored together; coalesce identical requests instead
// of making one profiles/supplements request per node.
import { api } from "../../scripts/api.js";

const entries = new Map();

export async function cachedJson(path, { ttlMs = 15000, force = false } = {}) {
  const now = Date.now();
  const current = entries.get(path);
  if (!force && current?.value !== undefined && current.expiresAt > now) return current.value;
  if (!force && current?.promise) return current.promise;

  const promise = api.fetchApi(path).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    entries.set(path, { value: payload, expiresAt: Date.now() + ttlMs, promise: null });
    return payload;
  }).catch((error) => {
    entries.delete(path);
    throw error;
  });
  entries.set(path, { value: current?.value, expiresAt: current?.expiresAt || 0, promise });
  return promise;
}

export function invalidateCachedJson(pathPrefix = "") {
  for (const path of entries.keys()) {
    if (!pathPrefix || path.startsWith(pathPrefix)) entries.delete(path);
  }
  globalThis.dispatchEvent?.(new CustomEvent("aps-registry-invalidated", {
    detail: { pathPrefix },
  }));
}
