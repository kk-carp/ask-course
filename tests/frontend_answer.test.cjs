const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const paint = source.slice(source.indexOf('    function paintTurn('), source.indexOf('    async function readSse('));
const escapeHtml = text => String(text ?? '').replace(/[&<>"']/g, x => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[x]));

function render(payload) {
  const nodes = {'.meta-row': {}, '.a': {}};
  const context = {escapeHtml};
  vm.createContext(context);
  const helper = path.join(root, 'frontend/answer-format.js');
  if (fs.existsSync(helper)) {
    vm.runInContext(fs.readFileSync(path.join(root, 'frontend/vendor/answer-libs.js'), 'utf8'), context);
    // This harness has no browser DOM; sanitizer behavior is checked in DOM integration QA.
    context.DOMPurify = {sanitize: value => value};
    vm.runInContext(fs.readFileSync(helper, 'utf8'), context);
  }
  vm.runInContext(paint, context);
  context.paintTurn({querySelector: selector => nodes[selector]}, payload);
  return nodes['.a'].innerHTML;
}

test('answer renders Markdown rather than literal markers', () => {
  assert.match(render({answer: '**课程重点**'}), /<strong>课程重点<\/strong>/);
});

test('answer preserves Markdown lists, tables and code blocks', () => {
  const html = render({answer: '## 课程内容\n\n1. 导航\n2. 巡检\n\n| 方向 | 内容 |\n| --- | --- |\n| 机器人 | ROS2 |\n\n```python\nprint("hello")\n```'});
  for (const tag of ['h2', 'ol', 'li', 'table', 'th', 'td', 'pre', 'code']) {
    assert.match(html, new RegExp(`<${tag}(?:>| )`));
  }
});

test('repeated fact evidence displays one source label', () => {
  const fact = {source: 'docs/course-99.md', updated_at: '2026-09-09', status: 'provided'};
  const html = render({answer: '课程介绍', fact_sources: [fact, {...fact}, {...fact}]});
  assert.equal((html.match(/课程文字资料/g) || []).length, 1);
});

test('different documents with the same date are grouped with their count', () => {
  const html = render({answer: '回答', fact_sources: [
    {source: 'one.md', updated_at: '2026-09-09', status: 'provided'},
    {source: 'two.md', updated_at: '2026-09-09', status: 'conflict'},
    {source: 'two.md', updated_at: '2026-09-09', status: 'conflict'},
  ]});
  assert.match(html, /课程文字资料（2份）/);
  assert.match(html, /含待核实信息/);
  assert.equal((html.match(/更新于/g) || []).length, 1);
});

test('official evidence and separate update dates remain visible', () => {
  const html = render({answer: '回答', fact_sources: [
    {source: 'one.md', updated_at: '2026-09-09', status: 'provided'},
    {source: 'two.md', updated_at: '2026-09-10', status: 'provided'},
    {source: 'https://example.com/99', updated_at: '2026-09-10T12:00:00Z', status: 'official'},
    null,
  ]});
  assert.equal((html.match(/课程文字资料/g) || []).length, 2);
  assert.equal((html.match(/官网实时信息/g) || []).length, 1);
});

test('missing dates do not leave an empty update label', () => {
  assert.doesNotMatch(render({answer: '回答', fact_sources: [{source: 'one.md'}]}), /更新于/);
});

test('plain text fallback stays escaped if Markdown dependencies fail', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/answer-format.js'), 'utf8'), context);
  assert.equal(context.AnswerFormat.markdown('<img src=x onerror=alert(1)>\n第二行'),
    '&lt;img src=x onerror=alert(1)&gt;<br>第二行');
});
