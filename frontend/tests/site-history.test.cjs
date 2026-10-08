// The bundled widget is exercised through its HTTP boundary, including a reload.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const tick = () => new Promise(resolve => setTimeout(resolve, 40));
const root = path.resolve(__dirname, '..');

test('fullsite guest history restores after refresh, renames, deletes and updates SPA context', async t => {
  const records = new Map(), calls = [];
  const conversationId = '41c7c9b2-1acc-4e24-8543-c9e86267424a';
  async function mount(storedId) {
    const dom = new JSDOM('<body></body>', {url:'https://site.test/projects', runScripts:'outside-only', pretendToBeVisual:true});
    t.after(() => dom.window.close());
    const win = dom.window;
    win.matchMedia = () => ({matches:false, addListener(){}, removeListener(){}});
    win.ResizeObserver = class {observe(){} unobserve(){} disconnect(){}};
    const computedStyle = win.getComputedStyle.bind(win); win.getComputedStyle = element => computedStyle(element);
    win.TextDecoder = TextDecoder;
    for (const file of ['vendor/answer-libs.js','answer-format.js']) win.eval(fs.readFileSync(path.join(root,file),'utf8'));
    if (storedId) win.localStorage.setItem('arborseek-consultation', storedId);
    const script = win.document.createElement('script'); script.src = 'https://site.test/agent/widget.js'; script.dataset.mode = 'site';
    Object.defineProperty(win.document,'currentScript',{value:script});
    win.fetch = async (url, options={}) => {
      const pathname = new URL(url).pathname, payload = options.body ? JSON.parse(options.body) : null;
      calls.push({pathname, options, payload});
      const data = value => new Response(JSON.stringify(value));
      if (pathname.endsWith('/widget/config')) return data({enabled:true, history_enabled:true, history_hours:24});
      if (pathname.endsWith('/widget/events')) return new Response(null,{status:204});
      if (pathname.endsWith('/widget/conversations') && options.method === 'POST') {
        records.set(conversationId,{id:conversationId,title:'选课建议',items:[]}); return data({id:conversationId});
      }
      if (pathname.endsWith('/widget/conversations')) return data({items:[...records.values()],next_offset:null});
      if (pathname.endsWith('/messages')) return data({conversation:records.get(conversationId),items:records.get(conversationId).items,next_offset:null});
      if (pathname.endsWith('/' + conversationId) && options.method === 'PATCH') {records.get(conversationId).title = payload.title; return data({});}
      if (pathname.endsWith('/' + conversationId) && options.method === 'DELETE') {records.delete(conversationId); return new Response(null,{status:204});}
      if (pathname.endsWith('/ask/stream')) {
        const result = {answer:'**学习建议**',hit:true,conversation_id:conversationId};
        records.get(conversationId).items.push({question:payload.question,result,request_id:payload.request_id});
        return new Response('event: final\ndata: '+JSON.stringify(result)+'\n\n');
      }
      throw new Error('Unexpected route '+pathname);
    };
    win.eval(fs.readFileSync(path.join(root,'dist/widget.js'),'utf8')); await tick();
    const shadow = win.document.querySelector('#arborseek-presales-agent').shadowRoot;
    return {win,dom,shadow};
  }
  const first = await mount();
  first.shadow.querySelector('.as-launch').click(); await tick();
  first.win.ArborseekAgent.setPageContext({courseId:'43'});
  const textarea = first.shadow.querySelector('textarea'); textarea.value = '帮我选课'; textarea.dispatchEvent(new first.win.Event('input'));
  first.shadow.querySelector('form').dispatchEvent(new first.win.Event('submit',{bubbles:true,cancelable:true})); await tick();
  assert.equal(calls.find(call => call.pathname.endsWith('/ask/stream')).payload.channel,'site_widget');
  assert.equal(calls.find(call => call.pathname.endsWith('/ask/stream')).payload.course_id,'43');
  assert.match(calls.find(call => call.pathname.endsWith('/ask/stream')).payload.request_id,/^[0-9a-f-]{36}$/);
  const storedId = first.win.localStorage.getItem('arborseek-consultation'); first.dom.window.close();
  const refreshed = await mount(storedId);
  assert.equal(refreshed.shadow.querySelector('.as-user').textContent,'帮我选课');
  assert.equal(refreshed.shadow.querySelector('.answer-markdown strong').textContent,'学习建议');
  refreshed.shadow.querySelector('.as-launch').click(); await tick();
  refreshed.shadow.querySelector('[aria-label="对话历史"]').click(); await tick();
  assert.match(refreshed.shadow.querySelector('.as-history-note').textContent,/24 小时/);
  refreshed.shadow.querySelector('.as-session-more').click(); await tick();
  [...refreshed.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node=>node.textContent==='重命名').click(); await tick();
  const name = refreshed.shadow.querySelector('[aria-label="对话名称"]'); name.value='机器人入门'; name.dispatchEvent(new refreshed.win.Event('input',{bubbles:true})); await tick();
  refreshed.shadow.querySelector('.ant-modal-footer .ant-btn-primary').click(); await tick();
  assert.equal(records.get(conversationId).title,'机器人入门');
  refreshed.shadow.querySelector('.as-session-more').click(); await tick();
  [...refreshed.shadow.querySelectorAll('.ant-dropdown-menu-item')].find(node=>node.textContent==='删除').click(); await tick();
  assert.equal(records.size,0);
  assert.equal(refreshed.win.localStorage.getItem('arborseek-consultation'),null);
  assert.equal(refreshed.shadow.querySelectorAll('.as-user').length,0);
});
