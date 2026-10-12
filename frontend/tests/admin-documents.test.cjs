const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const tick = () => new Promise(resolve => setTimeout(resolve, 20));
const root = path.resolve(__dirname, '..');
const json = (body, status=200) => new Response(JSON.stringify(body), {status});

async function mount(t, handler, user = {username:'maintainer', can_manage_documents:true}, catalogHandler) {
  // Use delivered artifacts so missing script copies and page wiring are caught.
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'dist/admin.html'), 'utf8'),
    {url:'https://agent.test/admin', runScripts:'outside-only'});
  t.after(() => dom.window.close());
  const win = dom.window, calls = [];
  win.confirm = () => true;
  win.fetch = async (url, options={}) => {
    calls.push({url, options});
    assert.equal(options.credentials, 'include');
    if (url === '/health') return json({});
    if (url === '/me') return json(user, user ? 200 : 401);
    if (url === '/logout') return json({});
    if (url === '/admin/courses') return catalogHandler ? catalogHandler() : json([
      {id:'42', title:'课程42名称', document_count:0}, {id:'43', title:'课程43名称', document_count:0},
      {id:'101', title:'新增机器人课程', document_count:0},
    ]);
    return handler(url, options);
  };
  for (const file of ['answer-format.js', 'admin-documents.js']) {
    win.eval(fs.readFileSync(path.join(root,'dist',file), 'utf8'));
  }
  win.eval([...win.document.scripts].find(script => !script.src).textContent);
  await tick();
  return {win, calls, doc:win.document};
}

test('admin opens document management, separates alerts and debugging, and hides panels after logout', async t => {
  const {doc} = await mount(t, url => {
    if (url === '/documents') return json([]);
    throw new Error('Unexpected request '+url);
  });
  assert.equal(doc.getElementById('documents-view').hidden, false);
  assert.equal(doc.getElementById('debug-view').hidden, true);
  doc.querySelector('[data-view="operations"]').click();
  assert.equal(doc.getElementById('operations-view').hidden, false);
  assert.equal(doc.getElementById('documents-view').hidden, true);
  doc.querySelector('[data-view="debug"]').click();
  assert.equal(doc.getElementById('debug-view').hidden, false);
  assert.equal(doc.getElementById('operations-view').hidden, true);
  doc.getElementById('logout').click(); await tick();
  for (const id of ['documents-view', 'operations-view', 'debug-view']) assert.equal(doc.getElementById(id).hidden, true);
  assert.equal(doc.getElementById('access-notice').hidden, false);
});

test('visitors cannot reveal management or debugging panels by changing navigation', async t => {
  const {doc, calls} = await mount(t, url => {throw new Error('Unexpected request '+url);}, null);
  for (const view of ['documents', 'operations', 'debug']) {
    doc.querySelector(`[data-view="${view}"]`).click();
    assert.equal(doc.getElementById(`${view}-view`).hidden, true);
  }
  assert.equal(doc.getElementById('access-notice').hidden, false);
  assert.ok(!calls.some(call => call.url === '/documents'));
});

test('login hides the form, clears the password, and logout returns to the login screen', async t => {
  const {doc, calls, win} = await mount(t, (url, options) => {
    if (url === '/login') {
      assert.deepEqual(JSON.parse(options.body), {username:'operator', password:'test-only-password'});
      return json({username:'operator', can_manage_documents:true});
    }
    if (url === '/documents') return json([]);
    throw new Error('Unexpected request '+url);
  }, null);
  assert.equal(doc.getElementById('admin-shell').hidden, true);
  assert.equal(doc.getElementById('login-form').hidden, false);
  doc.getElementById('username').value = 'operator';
  doc.getElementById('password').value = 'test-only-password';
  doc.getElementById('toggle-password').click();
  assert.equal(doc.getElementById('password').type, 'text');
  doc.getElementById('toggle-password').click();
  assert.equal(doc.getElementById('password').type, 'password');
  doc.getElementById('login-form').dispatchEvent(new win.Event('submit', {cancelable:true}));
  await tick();
  assert.equal(doc.getElementById('login-view').hidden, true);
  assert.equal(doc.getElementById('admin-shell').hidden, false);
  assert.equal(doc.getElementById('password').value, '');
  assert.match(doc.getElementById('who').textContent, /operator/);
  doc.getElementById('logout').click(); await tick();
  assert.equal(doc.getElementById('login-view').hidden, false);
  assert.equal(doc.getElementById('admin-shell').hidden, true);
  assert.equal(doc.getElementById('courses').querySelectorAll('[data-id]:not([data-id=""])').length, 0);
  assert.equal(calls.filter(call => call.url === '/login').length, 1);
});

test('login network failure is visible and allows retry', async t => {
  const {doc, win} = await mount(t, () => {throw new Error('网络连接失败');}, null);
  doc.getElementById('login-form').dispatchEvent(new win.Event('submit', {cancelable:true}));
  await tick();
  assert.match(doc.getElementById('login-error').textContent, /网络连接失败/);
  assert.equal(doc.getElementById('login-submit').disabled, false);
  assert.equal(doc.getElementById('admin-shell').hidden, true);
});

test('dynamic courses support search, new course uploads, and document status filters', async t => {
  const {doc, win} = await mount(t, url => {
    if (url === '/documents') return json([
      {id:'one', title:'机器人课程正文', course_id:'101', status:'pending', chunk_count:2},
      {id:'two', title:'机器人参考资料', course_id:'101', status:'ready', chunk_count:2},
    ]);
    throw new Error('Unexpected request '+url);
  });
  assert.match(doc.getElementById('courses').textContent, /新增机器人课程/);
  assert.equal(doc.getElementById('upload-form').querySelector('button[type="submit"]').disabled, true);
  doc.getElementById('course-search').value = '101';
  doc.getElementById('course-search').dispatchEvent(new win.Event('input'));
  assert.equal(doc.querySelector('.course[data-id="42"]'), null);
  doc.querySelector('.course[data-id="101"]').click();
  assert.equal(doc.getElementById('upload-form').querySelector('button[type="submit"]').disabled, false);
  assert.match(doc.getElementById('upload-context').textContent, /新增机器人课程/);
  assert.match(doc.getElementById('document-counts').textContent, /共 2 份资料.*待审核 1.*已发布 1/);
  doc.getElementById('document-status').value = 'pending';
  doc.getElementById('document-status').dispatchEvent(new win.Event('change'));
  assert.equal(doc.querySelectorAll('.document-card').length, 1);
  assert.match(doc.getElementById('docs').textContent, /机器人课程正文/);
  doc.getElementById('document-search').value = '不存在';
  doc.getElementById('document-search').dispatchEvent(new win.Event('input'));
  assert.equal(doc.querySelectorAll('.document-card').length, 0);
  assert.match(doc.getElementById('docs').textContent, /没有符合筛选条件/);
});

test('expired document session returns to login without showing old material', async t => {
  let expired = false;
  const {doc} = await mount(t, url => {
    if (url === '/documents') return expired ? json({detail:'未登录'}, 401) : json([{id:'one', title:'旧资料', course_id:'42', status:'ready', chunk_count:2}]);
    throw new Error('Unexpected request '+url);
  });
  expired = true;
  doc.querySelector('[data-refresh]').click(); await tick();
  assert.equal(doc.getElementById('admin-shell').hidden, true);
  assert.equal(doc.getElementById('login-view').hidden, false);
  assert.doesNotMatch(doc.getElementById('docs').textContent, /旧资料/);
  assert.match(doc.getElementById('login-error').textContent, /登录已过期/);
});

test('late course catalog cannot repopulate an account that has logged out', async t => {
  let resolveCatalog;
  const {doc} = await mount(t, url => {
    if (url === '/documents') return json([]);
    throw new Error('Unexpected request '+url);
  }, {username:'maintainer', can_manage_documents:true}, () => new Promise(resolve => {resolveCatalog = resolve;}));
  doc.getElementById('logout').click(); await tick();
  resolveCatalog(json([{id:'999', title:'旧账号课程', document_count:1}])); await tick();
  assert.equal(doc.getElementById('admin-shell').hidden, true);
  assert.doesNotMatch(doc.getElementById('courses').textContent, /旧账号课程/);
});

test('course filtering, download, confirmation, offline then delete use the document APIs', async t => {
  let records = [
    {id:'one', title:'课程正文', course_id:'42', space_id:'courses', status:'ready', chunk_count:4},
    {id:'two', title:'其他课程', course_id:'43', space_id:'courses', status:'ready', chunk_count:2},
  ];
  const {win, doc, calls} = await mount(t, (url, options) => {
    if (url === '/documents') return json(records);
    if (url === '/documents/one/offline') { records[0].status = 'offline'; return json(records[0]); }
    if (url === '/documents/one' && options.method === 'DELETE') { records.shift(); return json({ok:true}); }
    throw new Error('Unexpected request '+url);
  });
  assert.equal(doc.getElementById('document-tools').hidden, false);
  assert.equal(doc.querySelectorAll('.document-card').length, 2);
  doc.querySelector('.course[data-id="42"]').click();
  assert.equal(doc.querySelectorAll('.document-card').length, 1);
  assert.equal(doc.querySelector('.document-card a').getAttribute('href'), '/documents/one/file');
  win.confirm = () => false;
  doc.querySelector('[data-action="offline"]').click(); await tick();
  assert.ok(!calls.some(call => call.options.method === 'POST'));
  win.confirm = () => true;
  doc.querySelector('[data-action="offline"]').click(); await tick();
  assert.match(doc.getElementById('docs').textContent, /已撤回/);
  assert.ok(doc.querySelector('.document-card a'), 'administrator can inspect withdrawn originals');
  doc.querySelector('[data-action="delete"]').click(); await tick();
  assert.match(doc.getElementById('docs').textContent, /暂无资料/);
  assert.equal(calls.find(call => call.url.endsWith('/offline')).options.method, 'POST');
  assert.equal(calls.find(call => call.url === '/documents/one').options.method, 'DELETE');
});

test('failures are visible, untrusted fields are text and failed mutation retains the record', async t => {
  const {doc} = await mount(t, url => url === '/documents' ? json([
    {id:'bad', title:'<img src=x onerror=alert(1)>', course_id:'42', space_id:'courses', status:'failed',
      error:'<script>bad()</script>', chunk_count:0},
  ]) : json({detail:'无文档管理权限'}, 403));
  assert.match(doc.getElementById('docs').textContent, /失败原因：<script>/);
  assert.equal(doc.querySelector('#docs img, #docs script'), null);
  doc.querySelector('[data-action="offline"]').click(); await tick();
  assert.equal(doc.getElementById('admin-err').textContent, '无文档管理权限');
  assert.equal(doc.querySelectorAll('.document-card').length, 1);
});

test('logout clears data and ignores a late list response', async t => {
  let resolveList;
  const {doc} = await mount(t, () => new Promise(resolve => { resolveList = resolve; }));
  doc.getElementById('logout').click(); await tick();
  resolveList(json([{id:'late',title:'内部原文',status:'ready',chunk_count:1}])); await tick();
  assert.equal(doc.getElementById('document-tools').hidden, true);
  assert.equal(doc.getElementById('docs').textContent, '');
});

test('network list error offers retry and successful retry loads documents', async t => {
  let attempts = 0;
  const {doc} = await mount(t, () => {
    if (++attempts === 1) throw new Error('网络中断');
    return json([{id:'retry',title:'重试成功',status:'ready',chunk_count:1}]);
  });
  assert.match(doc.getElementById('admin-err').textContent, /网络中断/);
  doc.querySelector('[data-refresh]').click(); await tick();
  assert.match(doc.getElementById('docs').textContent, /重试成功/);
  assert.equal(doc.getElementById('admin-err').hidden, true);
});

test('a pending mutation disables repeated actions until the server responds', async t => {
  let finish;
  const item = {id:'slow', title:'课程资料', status:'ready', chunk_count:1};
  const {doc, calls} = await mount(t, url => url === '/documents' ? json([item]) :
    new Promise(resolve => { finish = () => { item.status = 'offline'; resolve(json(item)); }; }));
  doc.querySelector('[data-action="offline"]').click();
  doc.querySelector('[data-action="offline"]').click();
  assert.equal(doc.querySelector('[data-action="offline"]').disabled, true);
  assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
  finish(); await tick();
  assert.equal(doc.querySelector('[data-action="delete"]').disabled, false);
});

test('upload network failure is reported and permits retry', async t => {
  const {win, doc} = await mount(t, (url, options) => {
    if (url === '/documents' && !options.method) return json([]);
    throw new Error('上传连接中断');
  });
  doc.querySelector('.course[data-id="42"]').click();
  Object.defineProperty(doc.getElementById('file'), 'files', {
    value:[new win.File(['course'], 'course.md', {type:'text/markdown'})],
  });
  doc.getElementById('upload-form').dispatchEvent(new win.Event('submit', {bubbles:true, cancelable:true}));
  await tick();
  assert.match(doc.getElementById('admin-err').textContent, /上传连接中断/);
  assert.equal(doc.querySelector('#upload-form button').disabled, false);
});

test('pending document requires a review note and explicit publication', async t => {
  const item = {id:'candidate', title:'新版正文', course_id:'42', space_id:'courses', status:'pending', chunk_count:2, supersedes_id:'old'};
  const {win, doc, calls} = await mount(t, (url, options) => {
    if (url === '/documents') return json([item]);
    assert.equal(url, '/documents/candidate/publish');
    assert.deepEqual(JSON.parse(options.body), {note:'课程负责人确认，适用于2026版', safety_checks:{public_source:true, no_sensitive_data:true, business_verified:true, no_embedded_instructions:true}});
    item.status = 'ready'; return json(item);
  });
  assert.match(doc.getElementById('docs').textContent, /待审核/);
  assert.ok(doc.querySelector('.document-card a'));
  win.prompt = () => '   ';
  doc.querySelector('[data-action="publish"]').click(); await tick();
  assert.ok(!calls.some(call => call.options.method === 'POST'));
  win.prompt = () => '课程负责人确认，适用于2026版';
  doc.querySelector('[data-action="publish"]').click(); await tick();
  assert.match(doc.getElementById('docs').textContent, /已发布/);
  assert.equal(doc.querySelector('[data-action="publish"]'), null);
});
