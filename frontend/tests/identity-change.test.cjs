const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const tick = () => new Promise(resolve => setTimeout(resolve, 30));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const data = value => new Response(JSON.stringify(value));
const config = (key, enabled = true) => ({enabled, history_enabled:true, identity_key:key, identity_kind:key === 'guest' ? 'guest' : 'customer', history_hours:2160});
async function until(predicate) {
  for (let i = 0; i < 60; i++) { if (predicate()) return; await tick(); }
  assert.fail('Expected widget state did not arrive');
}
async function fixture(t, {stored = {}, intercept, initial = config('A')} = {}) {
  const dom = new JSDOM('<body></body>', {url:'https://site.test/projects', runScripts:'outside-only', pretendToBeVisual:true});
  t.after(() => dom.window.close());
  const win = dom.window;
  win.matchMedia = () => ({matches:false, addListener(){}, removeListener(){}});
  win.ResizeObserver = class {observe(){} unobserve(){} disconnect(){}};
  const computedStyle = win.getComputedStyle.bind(win); win.getComputedStyle = element => computedStyle(element);
  win.TextDecoder = TextDecoder;
  for (const file of ['vendor/answer-libs.js', 'answer-format.js']) win.eval(fs.readFileSync(path.join(root, file), 'utf8'));
  for (const [key, value] of Object.entries(stored)) win.localStorage.setItem(key, value);
  const script = win.document.createElement('script'); script.src = 'https://site.test/agent/widget.js'; script.dataset.mode = 'site';
  Object.defineProperty(win.document, 'currentScript', {value:script});
  const state = {config:initial, items:[], calls:[]};
  win.fetch = async (url, options = {}) => {
    const pathname = new URL(url).pathname;
    const call = {pathname, options, payload:options.body ? JSON.parse(options.body) : undefined}; state.calls.push(call);
    const response = await intercept?.(call, state);
    if (response !== undefined) return response;
    if (pathname.endsWith('/widget/config')) return data(state.config);
    if (pathname.endsWith('/widget/events')) return new Response(null, {status:204});
    if (pathname.endsWith('/messages')) return data({items:[{question:'A 私密问题', result:{answer:'A 私密回答'}}], next_offset:null});
    if (pathname.endsWith('/widget/conversations') && options.method === 'POST') return data({id:'new-consultation'});
    if (pathname.endsWith('/widget/conversations')) return data({items:state.items, next_offset:null});
    if (pathname.endsWith('/ask/stream')) return new Response('event: final\ndata: '+JSON.stringify({answer:'回答', conversation_id:'new-consultation'})+'\n\n');
    throw new Error('Unexpected route '+pathname);
  };
  win.eval(fs.readFileSync(path.join(root, 'dist/widget.js'), 'utf8'));
  await until(() => win.ArborseekAgent);
  const host = win.document.querySelector('#arborseek-presales-agent'), shadow = host.shadowRoot;
  return {win, host, shadow, state};
}
async function open(view) { view.shadow.querySelector('.as-launch').click(); await tick(); }
async function submit(view, question = 'A 在途问题') {
  const input = view.shadow.querySelector('textarea'); input.value = question; input.dispatchEvent(new view.win.Event('input'));
  view.shadow.querySelector('form').dispatchEvent(new view.win.Event('submit', {bubbles:true, cancelable:true})); await tick();
}
const callsTo = (view, suffix) => view.state.calls.filter(call => call.pathname.endsWith(suffix));
function clean(view) {
  assert.doesNotMatch(view.shadow.textContent, /A 私密|A 在途|A 迟到/);
  assert.equal(view.shadow.querySelector('textarea').value, '');
  assert.equal(view.shadow.querySelectorAll('.as-user').length, 0);
  assert.equal(Object.keys(view.win.localStorage).filter(key => key.startsWith('arborseek-consultation')).length, 0);
}

test('switch clears selected history, draft, dialogs and every old storage binding before revalidation', async t => {
  const pending = deferred(); let delay = false;
  const view = await fixture(t, {
    stored:{'arborseek-consultation:A':'old-A', 'arborseek-consultation:B':'old-B', 'arborseek-consultation':'legacy'},
    intercept:call => delay && call.pathname.endsWith('/widget/config') ? pending.promise : undefined,
  });
  await until(() => view.shadow.textContent.includes('A 私密回答')); await open(view);
  view.state.items = [{id:'old-A', title:'A 私密标题'}];
  view.shadow.querySelector('[aria-label="对话历史"]').click(); await until(() => view.shadow.querySelector('.as-session-more'));
  view.shadow.querySelector('.as-session-more').click(); await tick();
  [...view.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node => node.textContent === '重命名').click(); await tick();
  assert.ok(view.shadow.querySelector('[aria-label="对话名称"]'));
  delay = true; const switching = view.win.ArborseekAgent.identityChanged();
  assert.equal(view.host.hidden, true); assert.doesNotMatch(view.shadow.textContent, /A 私密|重命名对话/);
  assert.equal(Object.keys(view.win.localStorage).filter(key => key.startsWith('arborseek-consultation')).length, 0);
  view.state.items = [{id:'B-history', title:'B 本人历史'}]; pending.resolve(data(config('B'))); await switching; await tick();
  clean(view); assert.equal(callsTo(view, '/messages').length, 1); // No automatic restoration under B.
  await open(view); view.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.match(view.shadow.textContent, /B 本人历史/); assert.doesNotMatch(view.shadow.textContent, /A 私密/);
});

test('late history response cannot repopulate a new owner or restore browser selection', async t => {
  const pending = deferred();
  const view = await fixture(t, {stored:{'arborseek-consultation:A':'old-A'}, intercept:call => call.pathname.endsWith('/messages') ? pending.promise : undefined});
  await until(() => callsTo(view, '/messages').length);
  const old = callsTo(view, '/messages')[0]; view.state.config = config('B');
  await view.win.ArborseekAgent.identityChanged();
  assert.equal(old.options.signal.aborted, true);
  pending.resolve(data({items:[{question:'A 迟到问题', result:{answer:'A 迟到回答'}}], next_offset:null})); await tick();
  clean(view);
});

test('late conversation creation after logout never starts an ask or stores the old id', async t => {
  const pending = deferred();
  const view = await fixture(t, {intercept:call => call.pathname.endsWith('/widget/conversations') && call.options.method === 'POST' ? pending.promise : undefined});
  await open(view); await submit(view);
  const creation = callsTo(view, '/widget/conversations').find(call => call.options.method === 'POST');
  assert.ok(creation); view.state.config = config('guest'); await view.win.ArborseekAgent.identityChanged();
  assert.equal(creation.options.signal.aborted, true);
  pending.resolve(data({id:'A-late-id'})); await tick();
  assert.equal(callsTo(view, '/ask/stream').length, 0); clean(view);
});

for (const operation of ['list', 'rename', 'delete']) test(`late ${operation} response cannot revive old history or dialogs`, async t => {
  const pending = deferred(); let delay = false, oldCall;
  const view = await fixture(t, {intercept:call => {
    const match = operation === 'list' ? call.pathname.endsWith('/widget/conversations') && call.options.method === 'GET'
      : call.pathname.endsWith('/old-A') && call.options.method === (operation === 'rename' ? 'PATCH' : 'DELETE');
    if (delay && match && !oldCall) { oldCall = call; return pending.promise; }
  }});
  view.state.items = [{id:'old-A', title:'A 私密标题'}]; await open(view);
  if (operation === 'list') delay = true;
  view.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  if (operation !== 'list') {
    await until(() => view.shadow.querySelector('.as-session-more'));
    view.shadow.querySelector('.as-session-more').click(); await tick(); delay = true;
    [...view.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node => node.textContent === (operation === 'rename' ? '重命名' : '删除')).click(); await tick();
    if (operation === 'rename') { view.shadow.querySelector('.ant-modal-footer .ant-btn-primary').click(); await tick(); }
  }
  assert.ok(oldCall); view.state.config = config('B'); view.state.items = [];
  await view.win.ArborseekAgent.identityChanged(); assert.equal(oldCall.options.signal.aborted, true);
  pending.resolve(operation === 'delete' ? new Response(null, {status:204}) : data({items:[{id:'old-A', title:'A 迟到标题'}], next_offset:null})); await tick();
  clean(view); assert.equal(view.shadow.querySelector('[aria-label="对话名称"]'), null);
  await open(view); view.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.doesNotMatch(view.shadow.textContent, /A 私密|A 迟到/);
});

test('identity change cancels an active stream and ignores a reader that delivers a late final anyway', async t => {
  const pending = deferred(); let cancellations = 0, reads = 0;
  const reader = {read:() => ++reads === 1 ? pending.promise : Promise.resolve({done:true}), cancel:async () => { cancellations++; }, releaseLock(){}};
  const view = await fixture(t, {intercept:call => call.pathname.endsWith('/ask/stream') ? {ok:true, body:{getReader:() => reader}} : undefined});
  await open(view); await submit(view); await until(() => reads === 1);
  view.state.config = config('B'); await view.win.ArborseekAgent.identityChanged();
  assert.equal(callsTo(view, '/ask/stream')[0].options.signal.aborted, true); assert.ok(cancellations);
  pending.resolve({done:false, value:new TextEncoder().encode('event: final\ndata: {"answer":"A 迟到回答","conversation_id":"A-late-id"}\n\n')}); await tick();
  clean(view);
});

test('rapid switches abort old config requests and only the newest owner can mount', async t => {
  const old = deferred(), newest = deferred(); let delay = false, count = 0;
  const view = await fixture(t, {intercept:call => delay && call.pathname.endsWith('/widget/config') ? (++count === 1 ? old.promise : newest.promise) : undefined});
  await open(view);
  const input = view.shadow.querySelector('textarea'); input.value = 'A 私密草稿'; input.dispatchEvent(new view.win.Event('input'));
  delay = true; const first = view.win.ArborseekAgent.identityChanged(); const second = view.win.ArborseekAgent.identityChanged();
  const configs = callsTo(view, '/widget/config'); assert.equal(configs.at(-2).options.signal.aborted, true);
  newest.resolve(data(config('guest'))); await second;
  old.resolve(data(config('B'))); await first; await tick();
  clean(view); await open(view); view.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.match(view.shadow.textContent, /本浏览器游客对话/);
  assert.equal(callsTo(view, '/widget/config').length, 3);
});

for (const streamError of [false, true]) test(`401 ${streamError ? 'stream event' : 'HTTP response'} clears old content and stays closed if verification fails`, async t => {
  let invalid = false;
  const view = await fixture(t, {
    stored:{'arborseek-consultation:A':'old-A'},
    intercept:call => {
      if (invalid && call.pathname.endsWith('/widget/config')) return new Response('{}', {status:401});
      if (call.pathname.endsWith('/ask/stream')) {
        invalid = true;
        return streamError ? new Response('event: error\ndata: {"status":401,"detail":"expired"}\n\n') : new Response('{}', {status:401});
      }
    },
  });
  await until(() => view.shadow.textContent.includes('A 私密回答')); await open(view); await submit(view);
  await until(() => view.host.hidden);
  assert.doesNotMatch(view.shadow.textContent, /A 私密|A 在途/);
  assert.equal(view.win.localStorage.getItem('arborseek-consultation:A'), null);
  await assert.rejects(view.win.ArborseekAgent.identityChanged()); assert.equal(view.host.hidden, true);
});

test('cross-tab and focus notifications revalidate on the server and ignore event-supplied identities', async t => {
  const view = await fixture(t, {stored:{'arborseek-consultation:A':'old-A'}});
  await until(() => view.shadow.textContent.includes('A 私密回答'));
  view.state.config = config('B');
  view.win.dispatchEvent(new view.win.StorageEvent('storage', {key:'arborseek-identity-revision', newValue:'notice-only'}));
  await until(() => !view.host.hidden && !view.shadow.textContent.includes('A 私密回答'));
  assert.equal(view.win.localStorage.getItem('arborseek-identity-revision'), null); // No broadcast loop.
  clean(view);
  view.win.dispatchEvent(new view.win.CustomEvent('arborseek:identity-changed', {detail:{identity_key:'forged', customer_id:'forged', token:'never-use'}}));
  await until(() => !view.host.hidden); await tick();
  await submit(view, 'B 问题'); await until(() => callsTo(view, '/ask/stream').length);
  assert.equal(view.win.localStorage.getItem('arborseek-consultation:B'), 'new-consultation');
  assert.equal(view.win.localStorage.getItem('arborseek-consultation:forged'), null);
  assert.ok(view.state.calls.every(call => !call.options.headers?.Authorization));
  view.state.config = config('guest'); view.win.dispatchEvent(new view.win.Event('focus'));
  await until(() => !view.host.hidden && !view.shadow.textContent.includes('B 问题')); clean(view);
});

test('identity notification can enable an initially gated widget without showing old content', async t => {
  const view = await fixture(t, {initial:config('guest', false)});
  assert.equal(view.host.hidden, true); assert.equal(view.shadow.querySelector('.as-launch'), null);
  view.state.config = config('A'); await view.win.ArborseekAgent.identityChanged();
  assert.equal(view.host.hidden, false); clean(view);
});
