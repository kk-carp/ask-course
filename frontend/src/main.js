import { createApp, reactive, nextTick } from 'vue';
import Widget from './Widget.vue';
import styles from './widget.css?inline';

const script = document.currentScript || document.querySelector('script[type="module"][src$="/src/main.js"]');
async function bootstrap() {
  if (!script || document.querySelector('#arborseek-presales-agent')) return;
  const preview = script.dataset.preview === 'true' && ['/', '/qa', '/login'].includes(location.pathname);
  const pageCourse = location.pathname.match(/^\/course\/(\d+)\/?$/)?.[1];
  const siteMode = script.dataset.mode === 'site';
  if (!preview && !siteMode && (!pageCourse || pageCourse !== script.dataset.courseId || !/^\d{1,12}$/.test(pageCourse))) return;
  const base = new URL(preview && script.type === 'module' ? '/' : './', script.src);
  const api = path => new URL(path, base).toString();
  const pageContext = reactive({courseId: pageCourse || null});
  const loadConfig = signal => preview ? Promise.resolve({enabled:true}) : request(api(`widget/config?${siteMode ? 'mode=site&' : ''}course_id=${encodeURIComponent(pageContext.courseId || '')}`), signal);
  let config = await loadConfig();
  if (!globalThis.AnswerFormat) {
    for (const path of ['vendor/answer-libs.js', 'answer-format.js']) {
      await new Promise((resolve, reject) => {
        const asset = document.createElement('script');
        asset.src = api(path); asset.onload = resolve; asset.onerror = reject;
        document.head.append(asset);
      });
    }
  }
  if (document.querySelector('#arborseek-presales-agent')) return;
  const host = document.createElement('div'); host.id = 'arborseek-presales-agent'; host.hidden = true;
  const shadow = host.attachShadow({mode: 'open'});
  const style = document.createElement('style'); style.textContent = styles + AnswerFormat.styles;
  let root = document.createElement('div');
  let popupContainer = document.createElement('div'); popupContainer.className = 'as-popup-root';
  shadow.append(style, root, popupContainer); document.body.append(host);
  let widgetApp, widget, revision = 0, configRequest, identityCheck;
  const mount = identityRefresh => {
    host.hidden = false;
    widgetApp = createApp(Widget, {api, config, preview, pageContext, siteMode, identityRefresh,
      onIdentityInvalid: () => identityChanged().catch(() => {}),
      courseId: pageCourse || null, format: AnswerFormat, styleContainer: shadow, popupContainer});
    widget = widgetApp.mount(root);
  };
  // Notification only: the website completes its own auth change first. No account
  // IDs, roles or credentials from an event grant access to history.
  async function identityChanged({broadcast = true} = {}) {
    const mine = ++revision;
    identityCheck?.abort();
    configRequest?.abort(); configRequest = new AbortController();
    widget?.clearIdentityState();
    const oldApp = widgetApp;
    // Ant Design inputs may have queued a nextTick update from the same input
    // event. Hide and detach immediately, then dispose after that update drains.
    const disposed = nextTick(() => oldApp?.unmount());
    widget = widgetApp = undefined;
    root.remove(); popupContainer.remove(); host.hidden = true;
    root = document.createElement('div'); popupContainer = document.createElement('div');
    popupContainer.className = 'as-popup-root'; shadow.append(root, popupContainer);
    const baseKey = preview ? 'arborseek-preview-consultation' : 'arborseek-consultation';
    try {
      const keys = Object.keys(localStorage).filter(key => key === baseKey || key.startsWith(`${baseKey}:`));
      for (const key of keys) localStorage.removeItem(key);
    } catch { /* Storage may be unavailable. */ }
    if (broadcast) {
      try { localStorage.setItem('arborseek-identity-revision', crypto.randomUUID()); } catch { /* ignore */ }
    }
    try {
      const next = await loadConfig(configRequest.signal);
      await disposed;
      if (mine !== revision) return;
      config = next;
      // An identity change starts with no selected consultation; history comes
      // from the newly verified owner, never from another owner's browser key.
      if (config.enabled) mount(true);
      return {enabled:!!config.enabled};
    } catch (cause) {
      if (mine === revision) throw cause; // Keep the old identity's view closed on failure.
    }
  }
  async function checkIdentity() {
    if (preview || document.hidden) return;
    const mine = revision;
    identityCheck?.abort();
    const check = identityCheck = new AbortController();
    try {
      const next = await loadConfig(check.signal);
      if (mine !== revision) return;
      if (next.identity_key !== config.identity_key || next.enabled !== config.enabled) await identityChanged();
    } catch {
      if (mine === revision && !check.signal.aborted) await identityChanged().catch(() => {});
    }
  }
  if (config.enabled) mount(false);
  const setPageContext = ({courseId} = {}) => {
    pageContext.courseId = /^\d{1,12}$/.test(String(courseId || '')) ? String(courseId) : null;
  };
  globalThis.ArborseekAgent = Object.freeze({setPageContext, identityChanged});
  window.addEventListener('popstate', () => setPageContext({courseId: location.pathname.match(/^\/course\/(\d+)\/?$/)?.[1]}));
  window.addEventListener('arborseek:identity-changed', () => identityChanged().catch(() => {}));
  window.addEventListener('storage', event => { if (event.key === 'arborseek-identity-revision') identityChanged({broadcast:false}).catch(() => {}); });
  window.addEventListener('focus', checkIdentity);
  document.addEventListener('visibilitychange', checkIdentity);
}
async function request(url, signal) {
  const response = await fetch(url, {credentials: 'include', cache: 'no-store', signal});
  if (!response.ok) throw new Error('组件暂不可用');
  return response.json();
}
bootstrap().catch(() => { /* 门禁关闭或配置不可用时不挂载官网入口。 */ });
