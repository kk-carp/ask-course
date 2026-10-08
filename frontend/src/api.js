export async function json(api, path, method = 'GET', payload) {
  const response = await fetch(api(path), {
    method, credentials: 'include',
    headers: payload ? {'Content-Type': 'application/json'} : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`), {status: response.status});
  }
  return response.status === 204 ? null : response.json();
}

export async function streamAsk(api, payload, onPart) {
  const response = await fetch(api('ask/stream'), {
    method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '咨询暂时不可用，请稍后重试。');
  }
  if (!response.body) throw new Error('回答未完成，请重试。');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', result;
  function consume(block) {
    const rows = block.split('\n');
    const name = rows.find(row => row.startsWith('event:'))?.slice(6).trim();
    const raw = rows.filter(row => row.startsWith('data:')).map(row => row.slice(5).trimStart()).join('\n');
    if (!raw) return;
    const data = JSON.parse(raw);
    if (name === 'part') onPart(data);
    if (name === 'final') result = data;
    if (name === 'error') throw new Error(data.detail || '咨询暂时不可用');
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      buffer = buffer.replace(/\r\n/g, '\n');
      let end;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, end)); buffer = buffer.slice(end + 2);
      }
      if (done) { if (buffer.trim()) consume(buffer); break; }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
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
