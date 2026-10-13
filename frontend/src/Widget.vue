<script setup>
import { ref, computed, h, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
import { json, streamAsk, httpsUrl, courseUrl } from './api.js';
import UiIcon from './UiIcon.vue';
import { sessionTitle } from './session-title.js';
import { Button as AButton, Input as AInput, Popover as APopover, Dropdown as ADropdown, Menu as AMenu, Modal as AModal, ConfigProvider as AConfigProvider } from 'ant-design-vue';
import { StyleProvider } from 'ant-design-vue/es/_util/cssinjs';
const ATextarea = AInput.TextArea;
const menuItems = [{key: 'rename', label: '重命名', icon: () => h(UiIcon, {name: 'edit'})}, {key: 'delete', label: '删除', danger: true, icon: () => h(UiIcon, {name: 'delete'})}];

const props = defineProps(['api', 'config', 'preview', 'courseId', 'pageContext', 'siteMode', 'format', 'styleContainer', 'popupContainer', 'identityRefresh', 'onIdentityInvalid']);
let live = true;
const requests = new AbortController();
const current = () => live && !requests.signal.aborted;
async function requestJson(path, method = 'GET', payload) {
  const data = await json(props.api, path, method, payload, {signal:requests.signal});
  if (!current()) throw new DOMException('身份已变化', 'AbortError');
  return data;
}
function failure(cause) {
  if (!current()) return false;
  if (cause.status === 401) { props.onIdentityInvalid?.(); return false; }
  return cause.name !== 'AbortError';
}
const durable = !!props.config.history_enabled;
const privacyUrl = props.api('privacy');
const pageCourse = computed(() => props.pageContext ? props.pageContext.courseId : props.courseId);
const pageTitle = computed(() => pageCourse.value === props.config.course_id ? props.config.course_title : null);
const historyError = ref(''), historyLoading = ref(false), nextHistoryOffset = ref(null);
const getPopupContainer = () => props.popupContainer;
const open = ref(false), draft = ref(''), busy = ref(false), turns = ref([]);
const input = ref(), log = ref(), launcher = ref();
const logScrolled = ref(false), awayFromLatest = ref(false), copiedIndex = ref(-1), privacyOpen = ref(false);
let copyTimer = 0;
function onLogScroll() {
  const node = log.value;
  if (!node) return;
  logScrolled.value = node.scrollTop > 0;
  awayFromLatest.value = node.scrollHeight - node.scrollTop - node.clientHeight > 200;
}
async function copyAnswer(index) {
  const text = turns.value[index]?.answer || '';
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; }
  catch {
    const area = document.createElement('textarea');
    area.value = text; area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;left:0;top:0;opacity:0';
    props.popupContainer.append(area); area.focus(); area.select();
    try { copied = document.execCommand('copy'); } catch { copied = false; }
    area.remove();
  }
  if (!copied) return;
  copiedIndex.value = index; clearTimeout(copyTimer);
  copyTimer = setTimeout(() => { copiedIndex.value = -1; }, 1600);
}
const historyOpen = ref(false), sessions = ref([]);
const searchOpen = ref(false), search = ref(''), editingSession = ref(null), nameDraft = ref('');
const filteredSessions = computed(() => sessions.value.filter(session => session.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));
const renameValid = computed(() => !!nameDraft.value.trim() && [...nameDraft.value.trim()].length <= 40);
let sessionSequence = 1, activeSession = 1;
const baseKey = props.preview ? 'arborseek-preview-consultation' : 'arborseek-consultation';
const key = props.config.identity_key ? `${baseKey}:${props.config.identity_key}` : baseKey;
let conversationId, creationRequestId;
try { conversationId = localStorage.getItem(key) || undefined; } catch { /* 无持久存储仍可咨询 */ }
const prompts = props.config.default_prompts?.length ? props.config.default_prompts : ['推荐一门适合我的课程', '适合做保研或毕设吗', '我想找课程顾问'];
const event = name => props.preview || !current() ? Promise.resolve() : requestJson('widget/events', 'POST', {course_id: pageCourse.value, mode: props.siteMode ? 'site' : 'course', event_name: name}).catch(cause => { failure(cause); });
const newId = () => crypto.randomUUID();
function rememberId() {
  if (!current()) return;
  try { if (conversationId) localStorage.setItem(key, conversationId); else localStorage.removeItem(key); } catch { /* ignore */ }
}
async function refreshHistory(offset = 0) {
  historyLoading.value = true; historyError.value = '';
  try {
    const data = await requestJson(`widget/conversations?offset=${offset}`);
    sessions.value = offset ? [...sessions.value, ...data.items] : data.items;
    nextHistoryOffset.value = data.next_offset;
  } catch (cause) { if (failure(cause)) historyError.value = cause.message; }
  finally { if (current()) historyLoading.value = false; }
}
let previousOverflow = null;
function syncScroll() {
  const lock = open.value && matchMedia('(max-width: 600px)').matches;
  if (lock && previousOverflow === null) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  if (!lock && previousOverflow !== null) { document.body.style.overflow = previousOverflow; previousOverflow = null; }
}
watch(open, async value => {
  syncScroll(); await nextTick();
  if (!current()) return;
  if (value) { event('widget_open'); input.value?.focus({preventScroll: true}); }
  else launcher.value?.focus({preventScroll: true});
});
// Dock under the host site's quick-bar toggle so the launcher reads as part of that stack.
const LAUNCH_SIZE = 42, LAUNCH_GAP = 10;
const launchStyle = ref({});
let anchorFrame = 0, anchorObserver;
function anchorLauncher() {
  cancelAnimationFrame(anchorFrame);
  anchorFrame = requestAnimationFrame(() => {
    const toggle = document.querySelector('.utility-button.toggle-button');
    const rect = toggle?.getBoundingClientRect();
    if (!rect?.width || getComputedStyle(toggle).visibility === 'hidden') { launchStyle.value = {}; return; }
    const right = document.documentElement.clientWidth - rect.right + (rect.width - LAUNCH_SIZE) / 2;
    const top = Math.min(rect.bottom + LAUNCH_GAP, innerHeight - LAUNCH_SIZE - 8);
    launchStyle.value = {right: `${right}px`, top: `${top}px`, bottom: 'auto'};
  });
}
onMounted(async () => {
  window.addEventListener('resize', syncScroll); event('widget_impression');
  anchorLauncher(); window.addEventListener('resize', anchorLauncher); document.addEventListener('transitionend', anchorLauncher, true);
  anchorObserver = new MutationObserver(anchorLauncher);
  anchorObserver.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style']});
  if (durable && conversationId) await restoreSession({id: conversationId});
  if (durable && props.identityRefresh && current()) await refreshHistory();
});
function clearIdentityState() {
  live = false; requests.abort();
  try { localStorage.removeItem(key); localStorage.removeItem(baseKey); } catch { /* ignore */ }
  conversationId = undefined; creationRequestId = undefined; activeSession = ++sessionSequence;
  turns.value = []; sessions.value = []; draft.value = ''; busy.value = false;
  historyOpen.value = false; searchOpen.value = false; search.value = '';
  editingSession.value = null; nameDraft.value = ''; historyError.value = '';
  historyLoading.value = false; nextHistoryOffset.value = null;
  logScrolled.value = false; awayFromLatest.value = false; copiedIndex.value = -1; privacyOpen.value = false; clearTimeout(copyTimer);
}
defineExpose({clearIdentityState, selectedConversationId: () => conversationId});
onBeforeUnmount(() => {
  live = false; requests.abort(); clearTimeout(copyTimer); window.removeEventListener('resize', syncScroll); if (previousOverflow !== null) document.body.style.overflow = previousOverflow;
  cancelAnimationFrame(anchorFrame); anchorObserver?.disconnect(); window.removeEventListener('resize', anchorLauncher); document.removeEventListener('transitionend', anchorLauncher, true);
});
async function scrollAnswer() { await nextTick(); if (log.value) log.value.scrollTop = log.value.scrollHeight; onLogScroll(); }
function resizeInput() { /* Ant Design Vue 的 autoSize 负责输入框高度。 */ }
function keydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !matchMedia('(pointer: coarse)').matches) { e.preventDefault(); ask(); }
}
function saveCurrent() {
  if (durable) return;
  if (!turns.value.length) return;
  const index = sessions.value.findIndex(item => item.id === activeSession);
  const customTitle = index >= 0 ? sessions.value[index].customTitle : '';
  const saved = {id: activeSession, customTitle, title: customTitle || sessionTitle(turns.value, props.config.course_title), turns: turns.value, conversationId, draft: draft.value};
  if (index < 0) sessions.value.unshift(saved);
  else sessions.value[index] = saved;
}
function onHistoryOpen(value) {
  if (busy.value) return;
  if (value) { if (durable) refreshHistory(); else saveCurrent(); }
  historyOpen.value = value;
}
async function sessionAction(key, session) {
  if (key === 'rename') { historyError.value = ''; editingSession.value = session.id; nameDraft.value = session.title; }
  if (key === 'delete') {
    if (durable) {
      try { await requestJson(`widget/conversations/${session.id}`, 'DELETE'); }
      catch (cause) { if (failure(cause)) historyError.value = cause.message; return; }
    }
    sessions.value = sessions.value.filter(item => item.id !== session.id);
    if (session.id === activeSession) reset(false);
  }
}
async function renameSession() {
  if (!renameValid.value) return;
  const session = sessions.value.find(item => item.id === editingSession.value);
  if (durable && session) {
    try { await requestJson(`widget/conversations/${session.id}`, 'PATCH', {title: nameDraft.value.trim()}); }
    catch (cause) { if (failure(cause)) historyError.value = cause.message; return; }
  }
  if (session) { session.customTitle = nameDraft.value.trim(); session.title = session.customTitle; }
  editingSession.value = null; historyOpen.value = true;
}
async function restoreSession(session) {
  if (busy.value) return;
  if (durable) {
    busy.value = true; historyError.value = '';
    try {
      let offset = 0, records = [];
      do {
        const data = await requestJson(`widget/conversations/${session.id}/messages?offset=${offset}`);
        records.push(...data.items); offset = data.next_offset;
      } while (offset !== null && offset !== undefined);
      turns.value = records.map(item => ({question: item.question, result: item.result, answer: item.result.answer, requestId: item.request_id, parts: [], thinking: false}));
      activeSession = session.id; conversationId = session.id; draft.value = ''; historyOpen.value = false; rememberId();
      await scrollAnswer();
    } catch (cause) {
      if (!failure(cause)) return;
      historyError.value = cause.message;
      if (cause.status === 404) { conversationId = undefined; rememberId(); }
    } finally { if (current()) busy.value = false; }
    return;
  }
  saveCurrent();
  activeSession = session.id; turns.value = session.turns; draft.value = session.draft;
  conversationId = session.conversationId; historyOpen.value = false;
  try { if (conversationId) localStorage.setItem(key, conversationId); else localStorage.removeItem(key); } catch { /* ignore */ }
  nextTick(() => { resizeInput(); input.value?.focus(); scrollAnswer(); });
}
function reset(archive = true) {
  if (busy.value) return;
  if (archive) saveCurrent(); activeSession = ++sessionSequence; historyOpen.value = false;
  turns.value = []; draft.value = ''; conversationId = undefined;
  creationRequestId = undefined;
  try { localStorage.removeItem(key); } catch { /* ignore */ }
  nextTick(() => { resizeInput(); input.value?.focus(); });
}
async function ask(preset, retryTurn) {
  const question = (typeof preset === 'string' ? preset : draft.value).trim();
  if (!question || busy.value || !current()) return;
  privacyOpen.value = false; busy.value = true; draft.value = ''; nextTick(resizeInput);
  let turn;
  if (retryTurn) {
    // 重试更新原回答，避免重复问题与过期重试按钮。
    turn = retryTurn; Object.assign(turn, {answer: '', error: '', result: null, parts: [], thinking: true});
  } else {
    turns.value.push({question, answer: '', error: '', result: null, parts: [], thinking: true});
    turn = turns.value[turns.value.length - 1];
  }
  event('question'); scrollAnswer();
  try {
    if (durable && !conversationId) {
      creationRequestId ||= newId();
      const session = await requestJson('widget/conversations', 'POST', {request_id: creationRequestId});
      conversationId = session.id; activeSession = session.id; rememberId();
    }
    if (durable && !turn.requestId) turn.requestId = newId();
    const result = await streamAsk(props.api, {question, course_id: pageCourse.value, channel: props.preview ? 'internal_tool' : props.siteMode ? 'site_widget' : 'course_page', conversation_id: conversationId, request_id: turn.requestId}, part => {
      if (!current()) return;
      turn.parts[part.index - 1] = `${part.index}. ${part.question}\n${part.answer}`;
      turn.answer = turn.parts.filter(Boolean).join('\n\n'); turn.thinking = false; scrollAnswer();
    }, {signal:requests.signal});
    if (!current()) return;
    turn.result = result; turn.answer = result.answer || ''; turn.thinking = false;
    conversationId = result.conversation_id || conversationId;
    try { if (conversationId) localStorage.setItem(key, conversationId); } catch { /* ignore */ }
    if (['upstream_error', 'service_unavailable'].includes(result.error_type)) { turn.error = '服务暂时不可用，可重试本次提问。'; event('error'); }
    if (result.related_courses?.length) event('recommendation');
    if (showOwner(turn)) event('handoff');
  } catch (cause) { if (failure(cause)) {
    if (cause.discardAnswer) { turn.answer = ''; turn.parts = []; turn.result = null; }
    turn.error = cause.message || '暂时无法连接，请稍后重试。'; event('error');
  } }
  finally { if (current()) { busy.value = false; turn.thinking = false; await scrollAnswer(); if (current() && open.value) input.value?.focus({preventScroll: true}); } }
}
function showOwner(turn) {
  const result = turn.result;
  return result?.owner && (['advisor', 'commercial', 'multi_question'].includes(result.intent) || !result.related_courses?.length);
}
function evidence(turn) { return props.format.factSourceLabels(turn.result?.fact_sources); }
function ownerContact(turn) { return httpsUrl(turn.result.owner?.configured ? turn.result.owner.contact : props.config.fallback_contact); }
const imageUrl = value => { try { return /\.(png|jpe?g|webp|gif|svg)$/i.test(new URL(value).pathname); } catch { return false; } };
async function purchase(item, turn) {
  try {
    const result = await requestJson(`purchase/${encodeURIComponent(item.id)}`, 'POST');
    const url = httpsUrl(result.url);
    if (!url || new URL(url).hostname !== 'www.arborseek.com') throw new Error('购买地址无效');
    location.assign(url);
  } catch (cause) { if (failure(cause)) turn.actionError = cause.message; }
}
</script>

<template>
 <StyleProvider :container="styleContainer">
 <AConfigProvider :theme="{token: {colorPrimary: '#1268d8', borderRadius: 10, zIndexPopupBase: 2147483010}}" :get-popup-container="getPopupContainer">
  <AButton v-show="!open" ref="launcher" type="text" class="as-launch" :style="launchStyle" aria-label="问问探界，课程问答助手" title="问问探界 · 课程问答助手" :aria-expanded="open" aria-controls="arborseek-dialog" @click="open = true">
    <span class="as-launch-mark" aria-hidden="true"><UiIcon name="qa-bot" /></span>
  </AButton>
  <section v-show="open" id="arborseek-dialog" class="as-panel" :class="{open}" role="dialog" aria-label="探界 · 课程助手" @keydown.esc="historyOpen ? historyOpen = false : open = false">
    <header class="as-head" :class="{'is-scrolled': logScrolled}">
      <strong class="as-title">探界 · 课程助手</strong>
      <div class="as-head-actions">
        <APopover :open="historyOpen" trigger="click" placement="bottomRight" :arrow="false" overlay-class-name="as-history-popover" :get-popup-container="getPopupContainer" @open-change="onHistoryOpen">
          <AButton type="text" aria-label="对话历史" title="对话历史" :aria-expanded="historyOpen" aria-controls="arborseek-history" :disabled="busy"><UiIcon name="history" /></AButton>
          <template #content>
            <div id="arborseek-history" class="as-history" role="region" aria-label="对话历史">
              <div class="as-history-heading"><h2>对话历史</h2><AButton type="text" aria-label="搜索对话" @click="searchOpen = !searchOpen; search = ''"><UiIcon name="search" /></AButton></div>
              <AInput v-if="searchOpen" v-model:value="search" placeholder="搜索对话" aria-label="搜索对话内容" allow-clear class="as-history-search" />
              <div v-if="!filteredSessions.length" class="as-history-empty">{{ sessions.length ? '没有匹配的对话' : '还没有对话，开始一次咨询吧。' }}</div>
              <div v-for="session in filteredSessions" :key="session.id" class="as-history-item" :aria-current="session.id === activeSession ? 'true' : undefined">
                <AButton type="text" class="as-history-select" :title="session.title" @click="restoreSession(session)">{{ session.title }}</AButton>
                <ADropdown trigger="click" :get-popup-container="getPopupContainer" overlay-class-name="as-history-menu">
                  <AButton type="text" class="as-session-more" :aria-label="'管理对话：' + session.title"><UiIcon name="more" /></AButton>
                  <template #overlay><AMenu @click="({key}) => sessionAction(key, session)" :items="menuItems" /></template>
                </ADropdown>
              </div>
              <p v-if="historyLoading" class="as-history-note">正在加载…</p>
              <p v-if="historyError" class="as-error" role="alert">{{ historyError }}</p>
              <AButton v-if="durable && nextHistoryOffset !== null" :disabled="historyLoading" @click="refreshHistory(nextHistoryOffset)">加载更多</AButton>
              <p class="as-history-note">{{ durable ? `${config.identity_kind === 'customer' ? '本人对话' : '本浏览器游客对话'}保留 ${config.history_hours || 24} 小时，按消息活动时间计算。` : '仅保留本次页面访问的对话，刷新后清空。' }}</p>
            </div>
          </template>
        </APopover>
        <AButton type="text" aria-label="新会话" title="新会话" :disabled="busy" @click="reset()"><UiIcon name="new" /></AButton>
        <AButton type="text" aria-label="收起对话" title="收起对话" @click="open = false"><UiIcon name="collapse" /></AButton>
      </div>
    </header>
    <div ref="log" class="as-body" role="log" aria-live="polite" @scroll.passive="onLogScroll">
      <div v-if="!turns.length" class="as-welcome">
        <h2>说说你想学什么</h2>
        <p v-if="pageTitle" class="as-context">正在了解：{{ pageTitle }}</p>
        <p>告诉我你的方向和基础，我帮你找合适的课程。</p>
        <div class="as-prompts">
          <AButton type="text" v-for="prompt in prompts" :key="prompt" @click="ask(prompt)">{{ prompt }}</AButton>
        </div>
      </div>
      <template v-for="(turn, index) in turns" :key="index">
        <div class="as-user">{{ turn.question }}</div>
        <div v-if="turn.thinking || turn.answer" class="as-reply">
          <div v-if="turn.thinking" class="as-agent is-thinking" aria-busy="true"><span class="as-dots" aria-hidden="true"><span></span><span></span><span></span></span>正在理解问题并查询课程资料…</div>
          <div v-if="turn.answer" class="as-agent answer-markdown" v-html="format.markdown(turn.answer)"></div>
          <div v-if="turn.answer && !turn.thinking" class="as-answer-tools"><button type="button" class="as-copy" @click="copyAnswer(index)">{{ copiedIndex === index ? '已复制' : '复制' }}</button></div>
        </div>
        <template v-if="turn.result">
          <div v-if="(turn.result.related_courses || []).length" class="as-courses">
            <div v-for="item in (turn.result.related_courses || []).slice(0, 3)" :key="item.id" class="as-card as-course">
              <img v-if="httpsUrl(item.cover_url)" class="as-cover" :src="httpsUrl(item.cover_url)" alt="" loading="lazy">
              <span v-else class="as-cover as-cover-fallback" aria-hidden="true">{{ (item.title || '课').slice(0, 1) }}</span>
              <div class="as-course-copy">
                <strong>{{ item.title }}</strong>
                <p v-if="item.description" class="as-course-desc">{{ item.description }}</p>
                <p v-if="item.reason" class="as-course-reason">推荐理由：{{ item.reason }}</p>
              </div>
              <div v-if="courseUrl(item) || item.purchase_url" class="as-course-actions">
                <a v-if="courseUrl(item)" :href="courseUrl(item)" target="_blank" rel="noopener noreferrer">查看课程详情</a>
                <AButton v-if="item.purchase_url" type="primary" class="as-primary" @click="purchase(item, turn)">去官网购买页</AButton>
              </div>
            </div>
          </div>
          <div v-if="showOwner(turn)" class="as-card as-advisor">
            <strong>{{ turn.result.owner.configured ? (turn.result.owner.name || '课程顾问') : '暂未找到可用的课程顾问' }}</strong>
            <template v-if="ownerContact(turn)">
              <template v-if="imageUrl(ownerContact(turn)) && !turn.qrFailed">
                <img class="as-qr" :src="ownerContact(turn)" alt="课程顾问二维码" @error="turn.qrFailed = true">
                <p class="as-qr-note">扫码添加课程顾问</p>
              </template>
              <a v-else-if="!turn.qrFailed" :href="ownerContact(turn)" target="_blank" rel="noopener noreferrer">打开课程顾问联系方式</a>
              <a v-else-if="httpsUrl(config.fallback_contact)" :href="httpsUrl(config.fallback_contact)" target="_blank" rel="noopener noreferrer">二维码不可用，查看备用联系方式</a>
              <p v-else>联系方式暂不可用，请稍后重试。</p>
            </template>
            <p v-else>联系方式暂不可用，请稍后重试。</p>
          </div>
          <details v-if="turn.result.sources?.length || evidence(turn).length" class="as-evidence">
            <summary>查看回答依据</summary>
            <div class="as-sources">
              <div v-for="(source, sourceIndex) in turn.result.sources || []" :key="sourceIndex" class="as-source">{{ source.title || '课程资料' }}{{ source.snippet ? ' · ' + source.snippet : '' }}</div>
              <div v-for="label in evidence(turn)" :key="label" class="as-source">{{ label }}</div>
            </div>
          </details>
        </template>
        <p v-if="turn.actionError" class="as-error">{{ turn.actionError }}</p>
        <div v-if="turn.error" class="as-failure"><div class="as-error" role="alert">{{ turn.error }}</div><AButton class="as-retry" :disabled="busy" @click="ask(turn.question, turn)">重试本次提问</AButton></div>
      </template>
    </div>
    <div class="as-input">
      <button v-show="awayFromLatest" type="button" class="as-jump" aria-label="回到最新" @click="scrollAnswer"><UiIcon name="collapse" /></button>
      <p v-if="historyError && !historyOpen && editingSession === null" class="as-error" role="alert">{{ historyError }}</p>
      <form class="as-composer" @submit.prevent="ask()">
        <ATextarea ref="input" v-model:value="draft" :disabled="busy" :auto-size="{minRows:2,maxRows:5}" :maxlength="2000" :bordered="false" aria-label="咨询内容" placeholder="问问课程，或说说你想学什么…" @keydown="keydown" />
        <div class="as-composer-footer"><span class="as-key-hint">Enter 发送 · Shift + Enter 换行</span><AButton class="as-send" type="primary" html-type="submit" aria-label="发送消息" title="发送消息" :disabled="busy || !draft.trim()"><UiIcon name="send" /></AButton></div>
      </form>
      <div class="as-disclaimer">
        <span>内容由 AI 辅助生成，重要信息请与课程顾问确认。</span>
        <APopover :open="privacyOpen" trigger="click" placement="topRight" :arrow="false" overlay-class-name="as-privacy-popover" :get-popup-container="getPopupContainer" @open-change="value => privacyOpen = value">
          <AButton type="text" class="as-privacy">隐私说明</AButton>
          <template #content><p class="as-privacy-copy">咨询会保存必要记录，并发送必要上下文至模型服务商。请勿输入身份证、支付密码或内部资料。内容由 AI 辅助生成，重要信息请与课程顾问确认。</p></template>
        </APopover>
      </div>
    </div>
  </section>
  <AModal :open="editingSession !== null" title="重命名对话" :get-container="getPopupContainer" :z-index="2147483020" :width="340" :ok-button-props="{disabled:!renameValid}" ok-text="保存" cancel-text="取消" @ok="renameSession" @cancel="editingSession = null" destroy-on-close>
    <p v-if="historyError" class="as-error" role="alert">{{ historyError }}</p>
    <AInput v-model:value="nameDraft" aria-label="对话名称" placeholder="请输入对话名称" :maxlength="40" @press-enter="renameSession" />
  </AModal>
 </AConfigProvider>
 </StyleProvider>
</template>
