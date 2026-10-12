const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const tick = () => new Promise((resolve) => setTimeout(resolve, 40));
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status });
async function until(predicate) {
  for (let i = 0; i < 80; i++) {
    if (predicate()) return;
    await tick();
  }
  assert.fail("Expected UI state did not arrive");
}
async function mount(
  t,
  handler,
  user = { username: "maintainer", can_manage_documents: true },
  catalogHandler,
) {
  const dom = new JSDOM(
    fs.readFileSync(path.join(root, "dist/admin.html"), "utf8"),
    {
      url: "https://agent.test/admin",
      runScripts: "outside-only",
      pretendToBeVisual: true,
    },
  );
  t.after(() => dom.window.close());
  const win = dom.window,
    doc = win.document,
    calls = [];
  win.matchMedia = () => ({
    matches: false,
    addListener() {},
    removeListener() {},
  });
  win.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  const computed = win.getComputedStyle.bind(win);
  win.getComputedStyle = (element) => computed(element);
  win.TextDecoder = TextDecoder;
  win.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    assert.equal(options.credentials, "include");
    if (url === "/health")
      return json({ api: true, database: true, embedding_loaded: true });
    if (url === "/me") return json(user, user ? 200 : 401);
    if (url === "/logout") return json({});
    if (url === "/admin/courses")
      return catalogHandler
        ? catalogHandler()
        : json([
            { id: "42", title: "课程42名称" },
            { id: "43", title: "课程43名称" },
            { id: "101", title: "新增机器人课程" },
          ]);
    return handler(url, options);
  };
  for (const file of ["vendor/answer-libs.js", "answer-format.js", "admin.js"])
    win.eval(fs.readFileSync(path.join(root, "dist", file), "utf8"));
  await until(() => doc.querySelector(user ? "#admin-shell" : "#login-form"));
  await tick();
  return { win, doc, calls };
}
async function input(v, selector, text) {
  const el = v.doc.querySelector(selector);
  el.value = text;
  el.dispatchEvent(new v.win.Event("input", { bubbles: true }));
  await tick();
}
async function select(v, id, label) {
  v.doc
    .querySelector(id)
    .closest(".ant-select")
    .querySelector(".ant-select-selector")
    .dispatchEvent(new v.win.MouseEvent("mousedown", { bubbles: true }));
  await tick();
  const option = [...v.doc.querySelectorAll(".ant-select-item-option")].find(
    (el) => el.textContent === label,
  );
  assert.ok(option, "option " + label);
  option.click();
  await tick();
}
async function confirm(v) {
  v.doc.querySelector("[data-confirm-action]").click();
  await tick();
}

test("Vue admin navigation separates documents, alerts and debugging; logout removes private content", async (t) => {
  const v = await mount(t, (url) =>
    url === "/metrics/alerts"
      ? json({ alerts: [], estimated_cost: 0 })
      : json([]),
  );
  assert.ok(v.doc.querySelector("#documents-view"));
  v.doc.querySelector('[data-view="operations"]').click();
  await tick();
  assert.ok(v.doc.querySelector("#operations-view"));
  assert.equal(v.doc.querySelector("#documents-view"), null);
  v.doc.querySelector('[data-view="debug"]').click();
  await tick();
  assert.ok(v.doc.querySelector("#debug-view"));
  v.doc.querySelector("#logout").click();
  await tick();
  assert.ok(v.doc.querySelector("#login-form"));
  assert.equal(v.doc.querySelector("#admin-shell"), null);
});
test("visitors and non-manager accounts cannot see document controls or fetch documents", async (t) => {
  const visitor = await mount(
    t,
    () => {
      throw Error("unexpected");
    },
    null,
  );
  assert.equal(visitor.doc.querySelector("#admin-shell"), null);
  const member = await mount(
    t,
    () => {
      throw Error("unexpected");
    },
    { username: "member", can_manage_documents: false },
  );
  assert.equal(member.doc.querySelector("#documents-view"), null);
  assert.ok(!member.calls.some((c) => c.url === "/documents"));
  member.doc.querySelector('[data-view="debug"]').click();
  await tick();
  assert.ok(member.doc.querySelector("#debug-view"));
});
test("login sends credentials, clears password and logout returns to login", async (t) => {
  const v = await mount(
    t,
    (url, options) => {
      if (url === "/login") {
        assert.deepEqual(JSON.parse(options.body), {
          username: "operator",
          password: "test-password",
        });
        return json({ username: "operator", can_manage_documents: true });
      }
      return json([]);
    },
    null,
  );
  await input(v, "#username", "operator");
  await input(v, "#password", "test-password");
  v.doc
    .querySelector("#login-form")
    .dispatchEvent(
      new v.win.Event("submit", { bubbles: true, cancelable: true }),
    );
  await until(() => v.doc.querySelector("#who"));
  assert.match(v.doc.querySelector("#who").textContent, /operator/);
  assert.equal(v.doc.querySelector("#login-form"), null);
  v.doc.querySelector("#logout").click();
  await tick();
  assert.equal(v.doc.querySelector("#password").value, "");
});
test("login network failure is visible and permits retry", async (t) => {
  const v = await mount(
    t,
    () => {
      throw Error("网络连接失败");
    },
    null,
  );
  v.doc
    .querySelector("#login-form")
    .dispatchEvent(
      new v.win.Event("submit", { bubbles: true, cancelable: true }),
    );
  await tick();
  assert.match(v.doc.querySelector("#login-error").textContent, /网络连接失败/);
  assert.equal(v.doc.querySelector("#login-submit").disabled, false);
});
test("dynamic course selection, document name and status filtering", async (t) => {
  const v = await mount(t, () =>
    json([
      {
        id: "one",
        title: "机器人正文",
        course_id: "101",
        status: "pending",
        chunk_count: 2,
      },
      {
        id: "two",
        title: "机器人参考",
        course_id: "101",
        status: "ready",
        chunk_count: 3,
      },
      {
        id: "three",
        title: "课程42资料",
        course_id: "42",
        status: "ready",
        chunk_count: 1,
      },
    ]),
  );
  assert.equal(v.doc.querySelector("#open-upload").disabled, true);
  await select(v, "#course-select", "新增机器人课程（101）");
  assert.equal(v.doc.querySelector("#open-upload").disabled, false);
  assert.equal(v.doc.querySelectorAll("tbody tr[data-row-key]").length, 2);
  await select(v, "#document-status", "待审核");
  assert.equal(v.doc.querySelectorAll("tbody tr[data-row-key]").length, 1);
  await input(v, "#document-search", "不存在");
  assert.match(v.doc.querySelector("#docs").textContent, /没有符合筛选条件/);
});
test("document session expiry clears data and returns to login", async (t) => {
  let expired = false;
  const v = await mount(t, () =>
    expired
      ? json({ detail: "未登录" }, 401)
      : json([{ id: "one", title: "旧资料", status: "ready" }]),
  );
  expired = true;
  v.doc.querySelector("[data-refresh]").click();
  await tick();
  assert.ok(v.doc.querySelector("#login-form"));
  assert.doesNotMatch(v.doc.body.textContent, /旧资料/);
  assert.match(v.doc.body.textContent, /登录已过期/);
});
test("late document and catalog responses cannot restore an account after logout", async (t) => {
  let finishDocs, finishCatalog;
  const v = await mount(
    t,
    () => new Promise((r) => (finishDocs = r)),
    undefined,
    () => new Promise((r) => (finishCatalog = r)),
  );
  v.doc.querySelector("#logout").click();
  await tick();
  finishDocs(json([{ id: "old", title: "内部旧资料", status: "ready" }]));
  finishCatalog(json([{ id: "999", title: "旧账号课程" }]));
  await tick();
  assert.equal(v.doc.querySelector("#admin-shell"), null);
  assert.doesNotMatch(v.doc.body.textContent, /内部旧资料|旧账号课程/);
});
test("download, cancelled withdrawal, confirmed withdrawal and permanent deletion use correct APIs", async (t) => {
  let items = [
    {
      id: "one",
      title: "课程正文",
      course_id: "42",
      status: "ready",
      chunk_count: 4,
    },
  ];
  const v = await mount(t, (url, options) => {
    if (url === "/documents") return json(items);
    if (url.endsWith("/offline")) {
      items[0].status = "offline";
      return json(items[0]);
    }
    if (options.method === "DELETE") {
      items = [];
      return json({});
    }
    throw Error(url);
  });
  assert.equal(
    v.doc.querySelector("#docs a").getAttribute("href"),
    "/documents/one/file",
  );
  v.doc.querySelector('[data-action="offline"]').click();
  await tick();
  v.doc.querySelector(".ant-modal-close").click();
  await tick();
  assert.ok(!v.calls.some((c) => c.options.method === "POST"));
  v.doc.querySelector('[data-action="offline"]').click();
  await tick();
  await confirm(v);
  await until(() => v.doc.querySelector('[data-action="delete"]'));
  v.doc.querySelector('[data-action="delete"]').click();
  await tick();
  await confirm(v);
  assert.match(v.doc.querySelector("#docs").textContent, /暂无资料/);
  assert.equal(
    v.calls.find((c) => c.url.endsWith("/offline")).options.method,
    "POST",
  );
  assert.ok(
    v.calls.some(
      (c) => c.url === "/documents/one" && c.options.method === "DELETE",
    ),
  );
});
test("untrusted document fields are text and failed mutation retains data", async (t) => {
  const v = await mount(t, (url) =>
    url === "/documents"
      ? json([
          {
            id: "bad",
            title: "<img src=x onerror=alert(1)>",
            status: "failed",
            error: "<script>bad()</script>",
          },
        ])
      : json({ detail: "无文档管理权限" }, 403),
  );
  assert.equal(v.doc.querySelector("#docs img, #docs script"), null);
  assert.match(v.doc.querySelector("#docs").textContent, /失败原因：<script>/);
  v.doc.querySelector('[data-action="offline"]').click();
  await tick();
  await confirm(v);
  assert.match(v.doc.querySelector("#admin-err").textContent, /无文档管理权限/);
  assert.equal(v.doc.querySelectorAll("tbody tr[data-row-key]").length, 1);
});
test("failed list loads can be retried", async (t) => {
  let attempts = 0;
  const v = await mount(t, () => {
    if (++attempts === 1) throw Error("网络中断");
    return json([{ id: "retry", title: "重试成功", status: "ready" }]);
  });
  assert.match(v.doc.body.textContent, /网络中断/);
  v.doc.querySelector("[data-refresh]").click();
  await tick();
  assert.match(v.doc.querySelector("#docs").textContent, /重试成功/);
  assert.equal(v.doc.querySelector("#admin-err"), null);
});
test("publication requires all safety checks and a review note", async (t) => {
  const item = {
    id: "candidate",
    title: "新版正文",
    course_id: "42",
    status: "pending",
    supersedes_id: "old",
  };
  const v = await mount(t, (url, options) => {
    if (url === "/documents") return json([item]);
    assert.equal(url, "/documents/candidate/publish");
    assert.deepEqual(JSON.parse(options.body), {
      note: "负责人已核对",
      safety_checks: {
        public_source: true,
        no_sensitive_data: true,
        business_verified: true,
        no_embedded_instructions: true,
      },
    });
    item.status = "ready";
    return json(item);
  });
  v.doc.querySelector('[data-action="publish"]').click();
  await tick();
  assert.equal(v.doc.querySelector("[data-confirm-action]").disabled, true);
  await input(v, "#review-note", "负责人已核对");
  assert.equal(v.doc.querySelector("[data-confirm-action]").disabled, true);
  for (const checkbox of v.doc.querySelectorAll(".review-checks input")) {
    checkbox.click();
    await tick();
  }
  assert.equal(v.doc.querySelector("[data-confirm-action]").disabled, false);
  await confirm(v);
  await until(() => v.doc.querySelector('[data-action="review"]'));
  assert.equal(v.doc.querySelector('[data-action="publish"]'), null);
});
test("a pending mutation cannot be submitted twice", async (t) => {
  let finish;
  const item = { id: "slow", title: "课程资料", status: "ready" };
  const v = await mount(t, (url) =>
    url === "/documents"
      ? json([item])
      : new Promise(
          (r) =>
            (finish = () => {
              item.status = "offline";
              r(json(item));
            }),
        ),
  );
  v.doc.querySelector('[data-action="offline"]').click();
  await tick();
  v.doc.querySelector("[data-confirm-action]").click();
  v.doc.querySelector("[data-confirm-action]").click();
  await tick();
  assert.equal(v.calls.filter((c) => c.options.method === "POST").length, 1);
  finish();
  await until(() => v.doc.querySelector('[data-action="delete"]'));
});
test("upload failure remains visible and permits retry", async (t) => {
  const v = await mount(t, (url, options) => {
    if (!options.method || options.method === "GET") return json([]);
    throw Error("上传连接中断");
  });
  await select(v, "#course-select", "课程42名称（42）");
  v.doc.querySelector("#open-upload").click();
  await tick();
  const file = v.doc.querySelector('input[type="file"]');
  Object.defineProperty(file, "files", {
    value: [new v.win.File(["course"], "course.md", { type: "text/markdown" })],
  });
  file.dispatchEvent(new v.win.Event("change", { bubbles: true }));
  await tick();
  v.doc
    .querySelector("#upload-form")
    .dispatchEvent(
      new v.win.Event("submit", { bubbles: true, cancelable: true }),
    );
  await until(() => v.doc.body.textContent.includes("上传连接中断"));
  assert.match(v.doc.body.textContent, /上传连接中断/);
  assert.equal(
    v.doc.querySelector('#upload-form button[type="submit"]').disabled,
    false,
  );
});
test("debug renders sanitized Markdown and does not retain a stream after logout", async (t) => {
  const v = await mount(t, (url) =>
    url === "/documents"
      ? json([])
      : new Response(
          "event: final\ndata: " +
            JSON.stringify({
              answer: "**课程重点** <img src=x onerror=alert(1)>",
              hit: true,
            }) +
            "\n\n",
        ),
  );
  v.doc.querySelector('[data-view="debug"]').click();
  await tick();
  await input(v, "#question", "课程内容");
  v.doc
    .querySelector(".chat-composer")
    .dispatchEvent(
      new v.win.Event("submit", { bubbles: true, cancelable: true }),
    );
  await until(() => v.doc.querySelector(".answer-markdown strong"));
  assert.equal(v.doc.querySelector(".answer-markdown img"), null);
  assert.equal(
    v.doc.querySelector(".answer-markdown strong").textContent,
    "课程重点",
  );
  v.doc.querySelector("#logout").click();
  await tick();
  assert.doesNotMatch(v.doc.body.textContent, /课程重点/);
});

test('replacement upload preserves selected course and old document until publication', async t => {
  const old = {id:'old',title:'旧版正文',course_id:'42',status:'ready',chunk_count:3};
  const items = [old];
  const v = await mount(t, (url, options) => {
    if (url === '/documents' && options.method === 'POST') {
      assert.equal(options.body.get('course_id'), '42');
      assert.equal(options.body.get('supersedes_id'), 'old');
      assert.equal(options.body.get('space'), 'courses');
      assert.equal(options.body.get('file').name, 'new.md');
      items.push({id:'new',title:'新版正文',course_id:'42',status:'pending',supersedes_id:'old'});
      return json(items[1]);
    }
    return json(items);
  });
  await select(v, '#course-select', '课程42名称（42）');
  v.doc.querySelector('#open-upload').click(); await tick();
  await select(v, '#replacement-target', '替换：旧版正文');
  const input = v.doc.querySelector('input[type="file"]');
  Object.defineProperty(input, 'files', {value:[new v.win.File(['new content'], 'new.md')]});
  input.dispatchEvent(new v.win.Event('change', {bubbles:true})); await tick();
  v.doc.querySelector('#upload-form').dispatchEvent(new v.win.Event('submit', {bubbles:true,cancelable:true}));
  await until(() => v.doc.querySelectorAll('tbody tr[data-row-key]').length === 2);
  assert.equal(old.status,'ready');
  assert.match(v.doc.body.textContent, /审核发布后才会参与回答/);
});

test('pagination shows all documents and resets when filtering', async t => {
  const v = await mount(t, () => json(Array.from({length:12}, (_,i) => ({id:String(i),title:`资料-${i}`,status:'ready'}))));
  assert.equal(v.doc.querySelectorAll('tbody tr[data-row-key]').length, 10);
  v.doc.querySelector('.ant-pagination-item-2').click(); await tick();
  assert.equal(v.doc.querySelectorAll('tbody tr[data-row-key]').length, 2);
  await input(v, '#document-search', '资料-0');
  assert.equal(v.doc.querySelectorAll('tbody tr[data-row-key]').length, 1);
  assert.match(v.doc.querySelector('#docs').textContent,/资料-0/);
});

test('debug streams deltas and cancels late output when logout changes identity', async t => {
  let controller, cancelled = false;
  const v = await mount(t, url => url === '/documents' ? json([]) : new Response(new ReadableStream({start(value){controller=value;},cancel(){cancelled=true;}})));
  v.doc.querySelector('[data-view="debug"]').click(); await tick();
  await input(v,'#question','测试流式输出');
  v.doc.querySelector('.chat-composer').dispatchEvent(new v.win.Event('submit',{bubbles:true,cancelable:true})); await tick();
  controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"内部流式回答"}\n\n'));
  await until(() => v.doc.body.textContent.includes('内部流式回答'));
  v.doc.querySelector('#logout').click(); await tick();
  assert.equal(cancelled,true);
  assert.doesNotMatch(v.doc.body.textContent,/内部流式回答|测试流式输出/);
  assert.ok(v.doc.querySelector('#login-form'));
});
