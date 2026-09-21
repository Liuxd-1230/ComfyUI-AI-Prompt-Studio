// Shared, short-lived frontend registry cache.
// Multiple APS nodes are often restored together; coalesce identical requests instead
// of making one profiles/supplements request per node.
import { api } from "../../scripts/api.js";

const entries = new Map();
// 每次写操作失效都给该路径换一个代号：在途请求带着旧代号回来时，
// 它的响应已经是「写之前」的状态，不能再回写缓存（否则会把新状态盖掉 TTL 时长）。
const generations = new Map();

export async function cachedJson(path, { ttlMs = 15000, force = false } = {}) {
  const now = Date.now();
  const generation = generations.get(path) || 0;
  const current = entries.get(path);
  if (!force && current?.value !== undefined && current.expiresAt > now) return current.value;
  if (!force && current?.promise) return current.promise;

  const promise = api.fetchApi(path).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if ((generations.get(path) || 0) === generation) {
      entries.set(path, { value: payload, expiresAt: Date.now() + ttlMs, promise: null });
    }
    return payload;
  }).catch((error) => {
    if ((generations.get(path) || 0) === generation) entries.delete(path);
    throw error;
  });
  entries.set(path, { value: current?.value, expiresAt: current?.expiresAt || 0, promise });
  return promise;
}

export function invalidateCachedJson(pathPrefix = "") {
  for (const path of new Set([...entries.keys(), ...generations.keys()])) {
    if (pathPrefix && !path.startsWith(pathPrefix)) continue;
    generations.set(path, (generations.get(path) || 0) + 1);
    entries.delete(path);
  }
  globalThis.dispatchEvent?.(new CustomEvent("aps-registry-invalidated", {
    detail: { pathPrefix },
  }));
}
