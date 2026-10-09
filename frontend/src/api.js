export async function json(api, path, method = 'GET', payload, {signal} = {}) {
  const response = await fetch(api(path), {
    method, credentials: 'include', cache: 'no-store', signal,
    headers: payload ? {'Content-Type': 'application/json'} : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`), {status: response.status});
  }
  return response.status === 204 ? null : response.json();
}

export async function streamAsk(api, payload, onPart, {signal} = {}) {
  const response = await fetch(api('ask/stream'), {
    method: 'POST', credentials: 'include', signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : '咨询暂时不可用，请稍后重试。'), {status:response.status});
  }
  if (!response.body) throw new Error('回答未完成，请重试。');
  const reader = response.body.getReader();
  const cancelled = () => { if (signal?.aborted) throw new DOMException('身份已变化', 'AbortError'); };
  const abort = () => { reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, {once:true});
  const decoder = new TextDecoder();
  let buffer = '', result;
  function consume(block) {
    cancelled();
    const rows = block.split('\n');
    const name = rows.find(row => row.startsWith('event:'))?.slice(6).trim();
    const raw = rows.filter(row => row.startsWith('data:')).map(row => row.slice(5).trimStart()).join('\n');
    if (!raw) return;
    const data = JSON.parse(raw);
    if (name === 'part') onPart(data);
    if (name === 'final') result = data;
    if (name === 'error') throw Object.assign(new Error(data.detail || '咨询暂时不可用'), {status:data.status});
  }
  try {
    while (true) {
      cancelled();
      const {value, done} = await reader.read();
      cancelled();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      buffer = buffer.replace(/\r\n/g, '\n');
      let end;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, end)); buffer = buffer.slice(end + 2);
      }
      if (done) { if (buffer.trim()) consume(buffer); break; }
    }
  } finally { signal?.removeEventListener('abort', abort); await reader.cancel().catch(() => {}); reader.releaseLock(); }
  cancelled();
  if (!result) throw new Error('回答未完成，请重试。');
  return result;
}

export const httpsUrl = value => {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; }
  catch { return ''; }
};
export function courseUrl(item) {
  if (/^https:\/\/www\.arborseek\.com\/course\/\d+\/?$/.test(item.source_url || '')) return item.source_url;
  return /^\d+$/.test(String(item.id || '')) ? `https://www.arborseek.com/course/${item.id}` : '';
}
