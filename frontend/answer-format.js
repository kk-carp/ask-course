/* 演示页与官网组件共用；模型输出只允许安全的 Markdown 排版。 */
(() => {
  const styles = `
    .answer-markdown { white-space: normal; overflow-wrap: anywhere; line-height: 1.7; }
    .answer-markdown > :first-child { margin-top: 0; }
    .answer-markdown > :last-child { margin-bottom: 0; }
    .answer-markdown p, .answer-markdown ul, .answer-markdown ol, .answer-markdown blockquote { margin: .6em 0; }
    .answer-markdown ul, .answer-markdown ol { padding-left: 1.6em; }
    .answer-markdown li + li { margin-top: .3em; }
    .answer-markdown h1, .answer-markdown h2, .answer-markdown h3,
    .answer-markdown h4, .answer-markdown h5, .answer-markdown h6 { font-size: 1.05em; margin: 1em 0 .4em; }
    .answer-markdown pre { white-space: pre; overflow-x: auto; padding: 10px; background: #edf4ea; border-radius: 8px; }
    .answer-markdown code { font-family: ui-monospace, monospace; font-size: .9em; }
    .answer-markdown blockquote { border-left: 3px solid #b4d0bc; padding-left: 12px; color: #51665a; }
    .answer-markdown table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
    .answer-markdown th, .answer-markdown td { border: 1px solid #d4e3d3; padding: 6px 10px; }
    .answer-markdown a { color: #1b4f43; text-decoration: underline; }
  `;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  function markdown(value) {
    const text = String(value ?? '');
    if (!globalThis.marked?.parse || !globalThis.DOMPurify?.sanitize) {
      return escape(text).replace(/\n/g, '<br>');
    }
    return DOMPurify.sanitize(marked.parse(text, {gfm: true, breaks: true, async: false}), {
      ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'a', 'ul', 'ol', 'li',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code', 'hr',
        'table', 'thead', 'tbody', 'tr', 'th', 'td'],
      ALLOWED_ATTR: ['href', 'title', 'start', 'colspan', 'rowspan'],
      ALLOWED_URI_REGEXP: /^(?:https?:\/\/|mailto:|#)/i,
      ALLOW_DATA_ATTR: false,
      ALLOW_ARIA_ATTR: false,
    });
  }

  function factSourceLabels(sources = []) {
    const groups = new Map();
    for (const source of sources || []) {
      if (!source || typeof source !== 'object') continue;
      const kind = source.status === 'official' ? '官网实时信息' : '课程文字资料';
      const date = String(source.updated_at || '').slice(0, 10);
      const key = JSON.stringify([kind, date]);
      if (!groups.has(key)) groups.set(key, {kind, date, sources: new Set(), pending: false});
      const group = groups.get(key);
      group.sources.add(String(source.source || ''));
      group.pending ||= ['unknown', 'conflict'].includes(source.status);
    }
    return [...groups.values()].map(group =>
      group.kind + (group.sources.size > 1 ? `（${group.sources.size}份）` : '')
      + (group.date ? ` · 更新于 ${group.date}` : '')
      + (group.pending ? ' · 含待核实信息' : '')
    );
  }

  globalThis.AnswerFormat = {markdown, factSourceLabels, styles};
  if (globalThis.document?.head) {
    const style = document.createElement('style');
    style.textContent = styles;
    document.head.append(style);
  }
})();
