// The host owns the token. Never store it in Widget state or send it cross-origin.
export function authHeaders(url) {
  if (typeof location === 'undefined') return {};
  let target;
  try { target = new URL(url, location.href); } catch { return {}; }
  if (target.origin !== location.origin || !target.pathname.startsWith('/agent/')) return {};
  const token = globalThis.ArborseekAgentAuth?.getCredential?.() || '';
  return token ? {Authorization: `Bearer ${token}`} : {};
}
