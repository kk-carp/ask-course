/* 官网同源接入：<script defer src="/agent/widget.js" data-course-id="43"></script>
   反向代理应去掉 /agent 前缀；未列入白名单或未命中灰度时不渲染。
   跨页续聊依赖访客 cookie + localStorage 中的 conversation_id。 */
(() => {
  const script = document.currentScript;
  if (!script) return;
  const pageCourseId = location.pathname.match(/^\/course\/(\d+)\/?$/)?.[1];
  if (!pageCourseId || script.dataset.courseId !== pageCourseId) return;
  const courseId = pageCourseId;
  if (!courseId || !/^\d{1,12}$/.test(courseId)) return;
  const base = new URL("./", script.src);
  const api = (path) => new URL(path.replace(/^\//, ""), base).toString();
  const key = "arborseek-consultation";
  const DEFAULT_PROMPTS = [
    "推荐一门适合我的课程",
    "按我的基础帮我选课",
    "我想找课程顾问",
  ];
  let config;
  let conversationId;
  let panel;
  let body;
  let inputArea;
  let shadow;

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const clear = (node) => node.replaceChildren();
  const validHttp = (value) => {
    try { return new URL(value).protocol === "https:"; }
    catch (_) { return false; }
  };
  const isImage = (value) => {
    try { return /\.(png|jpe?g|webp|gif|svg)$/i.test(new URL(value).pathname); }
    catch (_) { return false; }
  };
  const detailUrl = (item) => {
    if (item.source_url && /^https:\/\/www\.arborseek\.com\/course\/\d+\/?$/.test(item.source_url)) {
      return item.source_url;
    }
    if (item.id && /^\d+$/.test(item.id)) return `https://www.arborseek.com/course/${item.id}`;
    return "";
  };
  async function json(path, method = "GET", payload) {
    const response = await fetch(api(path), {
      method, credentials: "include",
      headers: payload ? { "Content-Type": "application/json" } : {},
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `请求失败（${response.status}）`);
    return response.status === 204 ? null : response.json();
  }
  const event = (name) => json("widget/events", "POST", { course_id: courseId, event_name: name }).catch(() => {});
  async function streamAsk(payload, onPart) {
    const response = await fetch(api("ask/stream"), {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "咨询暂时不可用");
    const reader = response.body.getReader(); const decoder = new TextDecoder();
    let buffer = "", result;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n"); buffer = blocks.pop() || "";
      for (const block of blocks) {
        const name = block.split("\n").find(x => x.startsWith("event:"))?.slice(6).trim();
        const raw = block.split("\n").filter(x => x.startsWith("data:")).map(x => x.slice(5)).join("\n");
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (name === "part") onPart(data);
        if (name === "final") result = data;
        if (name === "error") throw new Error(data.detail || "咨询暂时不可用");
      }
    }
    if (!result) throw new Error("回答未完成，请重试。");
    return result;
  }
  function line(text, className) {
    const node = el("div", text, className);
    body.append(node);
    body.scrollTop = body.scrollHeight;
    return node;
  }
  function error(message) {
    line(message || "暂时无法连接，请稍后重试。", "as-error");
    event("error");
  }
  function button(text, action, className = "") {
    const node = el("button", text, className);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }
  async function purchase(id) {
    try {
      const result = await json(`purchase/${encodeURIComponent(id)}`, "POST");
      if (!validHttp(result.url) || new URL(result.url).hostname !== "www.arborseek.com") throw new Error("购买地址无效");
      location.assign(result.url);
    } catch (cause) { error(cause.message); }
  }
  function contactLink(parent, contact, label) {
    if (!validHttp(contact)) return;
    const link = el("a", label);
    link.href = contact;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    parent.append(link);
  }
  function courseCard(item) {
    const card = line("", "as-card");
    const href = detailUrl(item);
    if (item.cover_url && validHttp(item.cover_url)) {
      const image = el("img");
      image.alt = "";
      image.loading = "lazy";
      image.src = item.cover_url;
      card.append(image);
    }
    card.append(el("strong", item.title || ""));
    if (item.description) card.append(el("p", item.description));
    if (item.reason) card.append(el("p", `推荐依据：${item.reason}`));
    for (const text of item.requirements || []) card.append(el("small", text));
    for (const text of item.pending || []) card.append(el("small", `需确认：${text}`));
    if (href) contactLink(card, href, "查看官网课程详情");
    if (item.purchase_url) card.append(button("去官网购买页", () => purchase(item.id), "as-primary"));
    return card;
  }
  function handoff(owner, summary) {
    event("handoff");
    const card = line("", "as-card");
    card.append(el("strong", owner?.configured ? (owner.name || "课程顾问") : "暂未找到可用的课程顾问"));
    if (owner?.configured && validHttp(owner.contact)) {
      if (isImage(owner.contact)) {
        const image = el("img");
        image.alt = "课程顾问二维码";
        image.src = owner.contact;
        image.addEventListener("error", () => {
          image.remove();
          contactLink(card, config.fallback_contact, "二维码不可用，查看备用联系方式");
        });
        card.append(image);
      } else contactLink(card, owner.contact, "打开课程顾问联系方式");
    } else if (config.fallback_contact) {
      contactLink(card, config.fallback_contact, "查看备用联系方式");
    } else card.append(el("p", "联系方式暂不可用，请稍后重试。"));
    if (summary) {
      const copy = button("复制咨询摘要", async () => {
        try { await navigator.clipboard.writeText(summary); copy.textContent = "已复制"; }
        catch (_) { copy.textContent = "复制失败，请手动选择摘要"; }
      });
      card.append(copy, el("pre", summary));
    }
  }
  async function askQuestion(form, preset) {
    const input = form.querySelector("textarea");
    const question = (preset || input.value).trim();
    if (!question) return;
    input.value = "";
    line(question, "as-user");
    clear(inputArea);
    event("question");
    const pending = line("正在理解问题并查询课程资料…", "as-agent");
    const parts = [];
    try {
      const result = await streamAsk({ question, course_id: courseId, channel: "course_page", conversation_id: conversationId }, (part) => {
        parts[part.index - 1] = `${part.index}. ${part.question}\n${part.answer}`;
        pending.textContent = parts.filter(Boolean).join("\n\n");
      });
      if (["upstream_error", "service_unavailable"].includes(result.error_type)) event("error");
      conversationId = result.conversation_id || conversationId;
      try { localStorage.setItem(key, conversationId); } catch (_) { /* 当前会话仍可继续 */ }
      if (result.related_courses?.length) event("recommendation");
      pending.textContent = result.answer;
      for (const item of (result.related_courses || []).slice(0, 3)) courseCard(item);
      const matched = result.related_courses?.length;
      const forceHandoff = ["advisor", "commercial", "multi_question"].includes(result.intent);
      if (result.owner && (forceHandoff || !matched)) {
        handoff(result.owner, result.handoff_summary);
      }
      for (const source of result.sources || []) line(`依据：${source.title}${source.snippet ? " · " + source.snippet : ""}`, "as-source");
      for (const source of result.fact_sources || []) line(`资料来源：${source.status === "official" ? "官网实时信息" : "课程文字资料"} · 更新于 ${source.updated_at.slice(0, 10)}`, "as-source");
    } catch (cause) {
      if (!parts.length) pending.remove();
      error(cause.message);
      body.append(button("重试本次提问", () => askQuestion(form, question)));
    }
    inputArea.append(form);
  }
  function showHome() {
    clear(body); clear(inputArea);
    line(`正在了解「${config.course_title}」？可以直接提问，也可以点下面的默认问题。`, "as-agent");
    const prompts = el("div", undefined, "as-prompts");
    const form = el("form");
    const input = el("textarea"); input.placeholder = "直接询问课程内容、适用人群或购买方式";
    const send = el("button", "提问", "as-primary"); send.type = "submit";
    form.append(input, send);
    form.addEventListener("submit", (e) => { e.preventDefault(); askQuestion(form); });
    const openers = (config.default_prompts && config.default_prompts.length)
      ? config.default_prompts
      : DEFAULT_PROMPTS;
    for (const text of openers) {
      prompts.append(button(text, () => {
        conversationId = undefined;
        try { localStorage.removeItem(key); } catch (_) { /* ignore */ }
        askQuestion(form, text);
      }));
    }
    inputArea.append(prompts, form);
  }
  function mount() {
    const host = el("div"); host.id = "arborseek-presales-agent";
    document.body.append(host);
    shadow = host.attachShadow({ mode: "open" });
    const style = el("style");
    style.textContent = `
      :host { all: initial; font-family: system-ui, "PingFang SC", sans-serif; color: #17372e; }
      * { box-sizing: border-box; } button, textarea, input, select { font: inherit; }
      button { cursor: pointer; border: 1px solid #b4d0bc; border-radius: 10px; background: white; color: #174637; padding: 8px 12px; }
      button:focus-visible, textarea:focus-visible, select:focus-visible, input:focus-visible { outline: 3px solid #b6d35a; }
      button:disabled { opacity: .5; } .as-primary { background: #1b4f43; border-color: #1b4f43; color: white; }
      .as-launch { position: fixed; z-index: 2147483000; right: 20px; bottom: 20px; background: #1b4f43; color: white; box-shadow: 0 8px 26px #123b2c44; }
      .as-panel { position: fixed; z-index: 2147483000; right: 20px; bottom: 74px; width: min(390px, calc(100vw - 24px)); height: min(620px, calc(100dvh - 100px)); background: #f6faf4; border: 1px solid #bad2bf; border-radius: 16px; display: none; box-shadow: 0 18px 50px #123b2c33; overflow: hidden; }
      .as-panel.open { display: flex; flex-direction: column; } .as-head { padding: 12px 14px; background: #1b4f43; color: white; display: flex; align-items: center; justify-content: space-between; }
      .as-head button { background: transparent; color: white; border: 0; } .as-body { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
      .as-agent, .as-card, .as-source { background: white; border: 1px solid #d4e3d3; border-radius: 12px; padding: 10px 12px; white-space: pre-wrap; }
      .as-user { align-self: flex-end; background: #dff0df; border-radius: 12px; padding: 10px 12px; white-space: pre-wrap; }
      .as-error { color: #a63820; } .as-card { display: grid; gap: 8px; } .as-card img { width: 72px; height: 72px; object-fit: cover; border-radius: 8px; }
      .as-card p { margin: 0; } .as-card small { color: #51665a; } .as-card pre { white-space: pre-wrap; font: 12px/1.5 system-ui; background: #edf4ea; padding: 8px; }
      .as-card a { color: #1b4f43; } .as-input { padding: 12px; border-top: 1px solid #d4e3d3; display: grid; gap: 8px; }
      .as-prompts { display: grid; gap: 8px; } .as-prompts button { text-align: left; }
      .as-input form { display: grid; gap: 8px; } textarea, select, input { width: 100%; border: 1px solid #bad2bf; border-radius: 9px; background: white; padding: 8px; }
      textarea { min-height: 64px; resize: vertical; }
    `;
    const launch = button("课程咨询", () => {
      const opening = !panel.classList.contains("open");
      panel.classList.toggle("open", opening);
      launch.setAttribute("aria-expanded", String(opening));
      if (opening) { event("widget_open"); if (!body.childElementCount) showHome(); }
    }, "as-launch");
    launch.setAttribute("aria-expanded", "false");
    panel = el("section", undefined, "as-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "课程咨询");
    const head = el("div", undefined, "as-head");
    head.append(el("strong", "天树探界 · 课程咨询"), button("关闭", () => { panel.classList.remove("open"); launch.setAttribute("aria-expanded", "false"); }));
    body = el("div", undefined, "as-body"); inputArea = el("div", undefined, "as-input");
    panel.append(head, body, inputArea); shadow.append(style, launch, panel);
  }
  json(`widget/config?course_id=${encodeURIComponent(courseId)}`).then((result) => {
    config = result;
    try { conversationId = localStorage.getItem(key) || undefined; } catch (_) { /* 使用当前会话 */ }
    if (result.enabled) { mount(); event("widget_impression"); }
  }).catch(() => {});
})();
