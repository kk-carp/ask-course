const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const tick = () => new Promise(resolve => setTimeout(resolve, 30));
async function waitFor(f, selector) {
  for (let i = 0; i < 50; i++) {if (f.shadow.querySelector(selector)) return f.shadow.querySelector(selector); await tick();}
  assert.fail('Missing UI element: ' + selector);
}

async function fixture({preview = true, enabled = true, url, handler} = {}) {
  const dom = new JSDOM('<!doctype html><body></body>', {url: url || (preview ? 'https://site.test/' : 'https://site.test/course/43'), runScripts: 'outside-only', pretendToBeVisual: true});
  const win = dom.window, calls = [];
  win.matchMedia = query => ({matches: query.includes('max-width'), addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}});
  win.ResizeObserver = class {observe() {} unobserve() {} disconnect() {}};
  const getComputedStyle = win.getComputedStyle.bind(win);
  win.getComputedStyle = element => getComputedStyle(element);
  win.TextDecoder = TextDecoder;
  for (const file of ['vendor/answer-libs.js', 'answer-format.js']) win.eval(fs.readFileSync(path.join(root, file), 'utf8'));
  const script = win.document.createElement('script');
  script.src = 'https://site.test/agent/widget.js';
  if (preview) script.dataset.preview = 'true';
  else script.dataset.courseId = '43';
  Object.defineProperty(win.document, 'currentScript', {value: script});
  win.fetch = async (url, options = {}) => {
    calls.push({url, options});
    if (url.includes('widget/config')) return new Response(JSON.stringify({enabled, course_title: '四足机器人'}));
    if (url.includes('ask/stream')) return handler ? handler(url, options) : response();
    return new Response(null, {status: 204});
  };
  win.eval(fs.readFileSync(path.join(root, 'dist/widget.js'), 'utf8'));
  await tick();
  return {dom, win, calls, shadow: win.document.querySelector('#arborseek-presales-agent')?.shadowRoot};
}
function response() {
  const source = {source:'course.md', updated_at:'2026-09-09', status:'provided'};
  const result = {conversation_id:'conversation-1', answer:'**学习建议**\n\n| 方向 | 内容 |\n| --- | --- |\n| 机器人 | ROS2 |', fact_sources:[source, source], related_courses:[]};
  return new Response('event: part\ndata: '+JSON.stringify({index:1, question:'适合吗', answer:'**先学习基础**'})+'\n\nevent: final\ndata: '+JSON.stringify(result)+'\n\nevent: done\ndata: {}\n\n');
}
async function send(f, text) {
  const textarea = f.shadow.querySelector('textarea');
  textarea.value = text; textarea.dispatchEvent(new f.win.Event('input', {bubbles:true}));
  f.shadow.querySelector('form').dispatchEvent(new f.win.Event('submit', {bubbles:true,cancelable:true}));
  await tick();
}
test('Vue public page contains only a collapsed assistant, retains draft and restores page scrolling', async t => {
  const f = await fixture(); t.after(() => f.dom.window.close());
  assert.equal(f.shadow.querySelector('.as-panel').style.display, 'none');
  assert.equal(f.win.document.querySelector('main, header'), null);
  f.shadow.querySelector('.as-launch').click(); await tick();
  assert.equal(f.win.document.body.style.overflow, 'hidden');
  const input = f.shadow.querySelector('textarea'); input.value = '草稿'; input.dispatchEvent(new f.win.Event('input'));
  f.shadow.querySelector('[aria-label="收起对话"]').click(); await tick();
  assert.equal(f.win.document.body.style.overflow, '');
  f.shadow.querySelector('.as-launch').click(); await tick();
  assert.equal(input.value, '草稿');
});
test('Vue stream renders safe Markdown and deduplicated evidence; continuation and reset work', async t => {
  const f = await fixture(); t.after(() => f.dom.window.close());
  f.shadow.querySelector('.as-launch').click(); await tick();
  await send(f, '适合我吗');
  assert.ok(f.shadow.querySelector('.answer-markdown strong'));
  assert.ok(f.shadow.querySelector('.answer-markdown table'));
  assert.equal(f.shadow.querySelectorAll('.as-source').length, 1);
  assert.equal(f.shadow.querySelector('.as-evidence').open, false);
  assert.equal(f.shadow.querySelector('.as-welcome'), null);
  f.shadow.querySelector('[aria-label="收起对话"]').click(); await tick();
  f.shadow.querySelector('.as-launch').click(); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-user').length, 1);
  await send(f, '需要什么基础');
  const requests = f.calls.filter(call => call.url.includes('ask/stream')).map(call => JSON.parse(call.options.body));
  assert.equal(requests[0].channel, 'internal_tool');
  assert.equal(requests[1].conversation_id, 'conversation-1');
  f.shadow.querySelector('[aria-label="新会话"]').click(); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-user').length, 0);
  assert.ok(f.shadow.querySelector('.as-welcome'));
  assert.equal(f.win.localStorage.getItem('arborseek-preview-consultation'), null);
});
test('busy state prevents concurrent requests and retry replaces the failed turn', async t => {
  let resolve, attempt = 0;
  const f = await fixture({handler: () => {
    attempt++;
    if (attempt === 1) return new Promise(r => {resolve = r;});
    return response();
  }}); t.after(() => f.dom.window.close());
  f.shadow.querySelector('.as-launch').click(); await tick();
  await send(f, '课程介绍');
  assert.ok(f.shadow.querySelector('textarea').disabled);
  assert.ok(f.shadow.querySelector('[aria-label="新会话"]').disabled);
  await send(f, '重复请求'); assert.equal(attempt, 1);
  resolve(new Response(JSON.stringify({detail:'测试服务不可用'}), {status:503})); await tick();
  assert.match(f.shadow.querySelector('.as-error').textContent, /测试服务不可用/);
  assert.equal(f.shadow.querySelector('textarea').disabled, false);
  f.shadow.querySelector('.as-body > button').click(); await tick();
  assert.equal(attempt, 2);
  assert.equal(f.shadow.querySelectorAll('.as-user').length, 1);
  assert.equal(f.shadow.querySelector('.as-error'), null);
});
test('website pilot gate remains effective and production uses course_page', async t => {
  const disabled = await fixture({preview:false,enabled:false}); t.after(() => disabled.dom.window.close());
  assert.equal(disabled.shadow, undefined);
  const mismatch = await fixture({preview:false,url:'https://site.test/course/99'}); t.after(() => mismatch.dom.window.close());
  assert.equal(mismatch.shadow, undefined); assert.equal(mismatch.calls.length, 0);
  const f = await fixture({preview:false}); t.after(() => f.dom.window.close());
  f.shadow.querySelector('.as-launch').click(); await tick(); await send(f, '目录是什么');
  const payload = JSON.parse(f.calls.find(call => call.url.includes('ask/stream')).options.body);
  assert.equal(payload.channel, 'course_page'); assert.equal(payload.course_id, '43');
});
test('history restores an earlier session and continues with its conversation id', async t => {
  let sequence = 0;
  const f = await fixture({handler: () => new Response('event: final\ndata: ' + JSON.stringify({conversation_id: `session-${++sequence}`, answer: '回答'}) + '\n\n')});
  t.after(() => f.dom.window.close());
  f.shadow.querySelector('.as-launch').click(); await tick();
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  await waitFor(f, '.as-history-empty');
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  await send(f, '第一场咨询');
  f.shadow.querySelector('[aria-label="新会话"]').click(); await tick();
  await send(f, '第二场咨询');
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  await waitFor(f, '.as-history-item'); assert.equal(f.shadow.querySelectorAll('.as-history-item').length, 2);
  [...f.shadow.querySelectorAll('.as-history-item')].find(node => node.textContent.includes('第一场咨询')).querySelector('.as-history-select').click(); await tick();
  assert.equal(f.shadow.querySelector('.as-user').textContent, '第一场咨询');
  await send(f, '继续第一场');
  const requests = f.calls.filter(call => call.url.includes('ask/stream')).map(call => JSON.parse(call.options.body));
  assert.equal(requests[2].conversation_id, 'session-1');
  assert.equal(f.shadow.querySelectorAll('.as-head svg').length, 3);
});
test('Ant Design history supports summary, search, rename and deletion of the active session', async t => {
  const f = await fixture(); t.after(() => f.dom.window.close());
  f.shadow.querySelector('.as-launch').click(); await tick();
  await send(f, '四足机器人课程零基础可以学习吗？需要购买硬件吗？');
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await waitFor(f, '.as-history-item');
  assert.match(f.shadow.querySelector('.as-history-select').textContent, /四足机器人：学习基础与设备要求/);
  f.shadow.querySelector('.as-session-more').click(); await waitFor(f, '.ant-dropdown-menu-item');
  [...f.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node => node.textContent === '重命名').click();
  const input = await waitFor(f, '[aria-label="对话名称"]');
  input.value = '我的机器人学习计划'; input.dispatchEvent(new f.win.Event('input', {bubbles:true})); await tick();
  f.shadow.querySelector('.ant-modal-footer .ant-btn-primary').click(); await tick();
  assert.match(f.shadow.querySelector('.as-history-select').textContent, /我的机器人学习计划/);
  f.shadow.querySelector('[aria-label="搜索对话"]').click(); await tick();
  const search = f.shadow.querySelector('[aria-label="搜索对话内容"]');
  search.value = '不匹配'; search.dispatchEvent(new f.win.Event('input', {bubbles:true})); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-history-item').length, 0);
  search.value = ''; search.dispatchEvent(new f.win.Event('input', {bubbles:true})); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-history-item').length, 1);
  // 再保存当前会话不能覆盖用户名称。
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.match(f.shadow.querySelector('.as-history-select').textContent, /我的机器人学习计划/);
  f.shadow.querySelector('.as-session-more').click(); await tick();
  [...f.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node => node.textContent === '删除').click(); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-user').length, 0);
  assert.equal(f.win.localStorage.getItem('arborseek-preview-consultation'), null);
  f.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.equal(f.shadow.querySelectorAll('.as-history-item').length, 0);
});
test('stream parser handles CRLF, split UTF-8 bytes and missing final delimiter', async () => {
  const {streamAsk} = await import('../src/api.js');
  const originalFetch = global.fetch;
  const bytes = new TextEncoder().encode('event: part\r\ndata: {"index":1,"answer":"课程"}\r\n\r\nevent: final\r\ndata: {"answer":"完成"}');
  global.fetch = async () => new Response(new ReadableStream({start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close();
  }}));
  try {
    const parts = [], result = await streamAsk(path => path, {}, part => parts.push(part));
    assert.equal(parts[0].answer, '课程'); assert.equal(result.answer, '完成');
  } finally { global.fetch = originalFetch; }
});
