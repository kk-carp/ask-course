import { createApp } from 'vue';
import Widget from './Widget.vue';
import styles from './widget.css?inline';

const script = document.currentScript || document.querySelector('script[type="module"][src$="/src/main.js"]');
async function bootstrap() {
  if (!script || document.querySelector('#arborseek-presales-agent')) return;
  const preview = script.dataset.preview === 'true' && ['/', '/qa', '/login'].includes(location.pathname);
  const pageCourse = location.pathname.match(/^\/course\/(\d+)\/?$/)?.[1];
  if (!preview && (!pageCourse || pageCourse !== script.dataset.courseId || !/^\d{1,12}$/.test(pageCourse))) return;
  const base = new URL(preview && script.type === 'module' ? '/' : './', script.src);
  const api = path => new URL(path, base).toString();
  const config = preview ? {enabled: true} : await request(api('widget/config?course_id=' + encodeURIComponent(pageCourse)));
  if (!config.enabled) return;
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
  const host = document.createElement('div'); host.id = 'arborseek-presales-agent';
  const shadow = host.attachShadow({mode: 'open'});
  const style = document.createElement('style'); style.textContent = styles + AnswerFormat.styles;
  const root = document.createElement('div');
  const popupContainer = document.createElement('div'); popupContainer.className = 'as-popup-root';
  shadow.append(style, root, popupContainer); document.body.append(host);
  createApp(Widget, {api, config, preview, courseId: pageCourse || null, format: AnswerFormat, styleContainer: shadow, popupContainer}).mount(root);
}
async function request(url) {
  const response = await fetch(url, {credentials: 'include'});
  if (!response.ok) throw new Error('组件暂不可用');
  return response.json();
}
bootstrap().catch(() => { /* 门禁关闭或配置不可用时不挂载官网入口。 */ });
