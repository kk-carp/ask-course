<script setup>
import { ref, computed, h, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
import { json, streamAsk, httpsUrl, courseUrl } from './api.js';
import UiIcon from './UiIcon.vue';
import { sessionTitle } from './session-title.js';
import { Button as AButton, Input as AInput, Popover as APopover, Dropdown as ADropdown, Menu as AMenu, Modal as AModal, ConfigProvider as AConfigProvider } from 'ant-design-vue';
import { StyleProvider } from 'ant-design-vue/es/_util/cssinjs';
const ATextarea = AInput.TextArea;
const menuItems = [{key: 'rename', label: '重命名', icon: () => h(UiIcon, {name: 'edit'})}, {key: 'delete', label: '删除', danger: true, icon: () => h(UiIcon, {name: 'delete'})}];

const props = defineProps(['api', 'config', 'preview', 'courseId', 'format', 'styleContainer', 'popupContainer']);
const getPopupContainer = () => props.popupContainer;
const open = ref(false), draft = ref(''), busy = ref(false), turns = ref([]);
const input = ref(), log = ref(), launcher = ref();
const historyOpen = ref(false), sessions = ref([]);
const searchOpen = ref(false), search = ref(''), editingSession = ref(null), nameDraft = ref('');
const filteredSessions = computed(() => sessions.value.filter(session => session.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));
const renameValid = computed(() => !!nameDraft.value.trim() && [...nameDraft.value.trim()].length <= 40);
let sessionSequence = 1, activeSession = 1;
const key = props.preview ? 'arborseek-preview-consultation' : 'arborseek-consultation';
let conversationId;
try { conversationId = localStorage.getItem(key) || undefined; } catch { /* 无持久存储仍可咨询 */ }
const prompts = props.config.default_prompts?.length ? props.config.default_prompts : ['推荐一门适合我的课程', '按我的基础帮我选课', '我想找课程顾问'];
const event = name => props.preview ? Promise.resolve() : json(props.api, 'widget/events', 'POST', {course_id: props.courseId, event_name: name}).catch(() => {});
let previousOverflow = null;
function syncScroll() {
  const lock = open.value && matchMedia('(max-width: 600px)').matches;
  if (lock && previousOverflow === null) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  if (!lock && previousOverflow !== null) { document.body.style.overflow = previousOverflow; previousOverflow = null; }
}
watch(open, async value => {
  syncScroll(); await nextTick();
  if (value) { event('widget_open'); input.value?.focus({preventScroll: true}); }
  else launcher.value?.focus({preventScroll: true});
});
onMounted(() => { window.addEventListener('resize', syncScroll); event('widget_impression'); });
onBeforeUnmount(() => { window.removeEventListener('resize', syncScroll); if (previousOverflow !== null) document.body.style.overflow = previousOverflow; });
async function scrollAnswer() { await nextTick(); if (log.value) log.value.scrollTop = log.value.scrollHeight; }
function resizeInput() { /* Ant Design Vue 的 autoSize 负责输入框高度。 */ }
function keydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !matchMedia('(pointer: coarse)').matches) { e.preventDefault(); ask(); }
}
function saveCurrent() {
  if (!turns.value.length) return;
  const index = sessions.value.findIndex(item => item.id === activeSession);
  const customTitle = index >= 0 ? sessions.value[index].customTitle : '';
  const saved = {id: activeSession, customTitle, title: customTitle || sessionTitle(turns.value, props.config.course_title), turns: turns.value, conversationId, draft: draft.value};
  if (index < 0) sessions.value.unshift(saved);
  else sessions.value[index] = saved;
}
function onHistoryOpen(value) {
  if (busy.value) return;
  if (value) saveCurrent();
  historyOpen.value = value;
}
function sessionAction(key, session) {
  if (key === 'rename') { editingSession.value = session.id; nameDraft.value = session.title; }
  if (key === 'delete') {
    sessions.value = sessions.value.filter(item => item.id !== session.id);
    if (session.id === activeSession) reset(false);
  }
}
function renameSession() {
  if (!renameValid.value) return;
  const session = sessions.value.find(item => item.id === editingSession.value);
  if (session) { session.customTitle = nameDraft.value.trim(); session.title = session.customTitle; }
  editingSession.value = null; historyOpen.value = true;
}
function restoreSession(session) {
  if (busy.value) return;
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
  try { localStorage.removeItem(key); } catch { /* ignore */ }
  nextTick(() => { resizeInput(); input.value?.focus(); });
}
async function ask(preset, retryTurn) {
  const question = (typeof preset === 'string' ? preset : draft.value).trim();
  if (!question || busy.value) return;
  busy.value = true; draft.value = ''; nextTick(resizeInput);
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
    const result = await streamAsk(props.api, {question, course_id: props.courseId, channel: props.preview ? 'internal_tool' : 'course_page', conversation_id: conversationId}, part => {
      turn.parts[part.index - 1] = `${part.index}. ${part.question}\n${part.answer}`;
      turn.answer = turn.parts.filter(Boolean).join('\n\n'); turn.thinking = false; scrollAnswer();
    });
    turn.result = result; turn.answer = result.answer || ''; turn.thinking = false;
    conversationId = result.conversation_id || conversationId;
    try { if (conversationId) localStorage.setItem(key, conversationId); } catch { /* ignore */ }
    if (['upstream_error', 'service_unavailable'].includes(result.error_type)) { turn.error = '服务暂时不可用，可重试本次提问。'; event('error'); }
    if (result.related_courses?.length) event('recommendation');
    if (showOwner(turn)) event('handoff');
  } catch (cause) { turn.error = cause.message || '暂时无法连接，请稍后重试。'; event('error'); }
  finally { busy.value = false; turn.thinking = false; await scrollAnswer(); if (open.value) input.value?.focus({preventScroll: true}); }
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
    const result = await json(props.api, `purchase/${encodeURIComponent(item.id)}`, 'POST');
    const url = httpsUrl(result.url);
    if (!url || new URL(url).hostname !== 'www.arborseek.com') throw new Error('购买地址无效');
    location.assign(url);
  } catch (cause) { turn.actionError = cause.message; }
}
async function copySummary(turn) {
  try { await navigator.clipboard.writeText(turn.result.handoff_summary); turn.copyStatus = '已复制'; }
  catch { turn.copyStatus = '复制失败，请手动选择摘要'; }
}
</script>

<template>
 <StyleProvider :container="styleContainer">
 <AConfigProvider :theme="{token: {colorPrimary: '#1890ff', borderRadius: 10, zIndexPopupBase: 2147483010}}" :get-popup-container="getPopupContainer">
  <AButton v-show="!open" ref="launcher" type="text" class="as-launch" :aria-expanded="open" aria-controls="arborseek-dialog" @click="open = true">
    <span class="as-launch-mark">探</span><span>问问探界</span>
  </AButton>
  <section v-show="open" id="arborseek-dialog" class="as-panel" :class="{open}" role="dialog" aria-label="探界 · 课程助手" @keydown.esc="historyOpen ? historyOpen = false : open = false">
    <header class="as-head">
      <APopover :open="historyOpen" trigger="click" placement="bottomLeft" :arrow="false" overlay-class-name="as-history-popover" :get-popup-container="getPopupContainer" @open-change="onHistoryOpen">
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
            <p class="as-history-note">仅保留本次页面访问的对话，刷新后清空。</p>
          </div>
        </template>
      </APopover>
      <strong class="as-title">探界 · 课程助手</strong>
      <div class="as-head-actions">
        <AButton type="text" aria-label="新会话" title="新会话" :disabled="busy" @click="reset()"><UiIcon name="new" /></AButton>
        <AButton type="text" aria-label="收起对话" title="收起对话" @click="open = false"><UiIcon name="collapse" /></AButton>
      </div>
    </header>
    <div ref="log" class="as-body" role="log" aria-live="polite">
      <div v-if="!turns.length" class="as-welcome">
        <div class="as-emblem" aria-hidden="true">探</div>
        <h2>你好，想从哪里开始？</h2><p>聊聊你的学习目标，一起找到合适的课程。</p>
        <div v-if="config.course_title" class="as-context">正在了解：{{ config.course_title }}</div>
        <div class="as-prompts">
          <AButton type="text" v-for="(prompt, index) in prompts" :key="prompt" @click="ask(prompt)">
            <span class="as-prompt-icon" aria-hidden="true">{{ ['✧', '⌘', '☏'][index % 3] }}</span><span>{{ prompt }}</span><span class="as-prompt-arrow" aria-hidden="true">↗</span>
          </AButton>
        </div>
      </div>
      <template v-for="(turn, index) in turns" :key="index">
        <div class="as-user">{{ turn.question }}</div>
        <div v-if="turn.thinking" class="as-agent is-thinking" aria-busy="true">正在理解问题并查询课程资料…</div>
        <div v-if="turn.answer" class="as-agent answer-markdown" v-html="format.markdown(turn.answer)"></div>
        <template v-if="turn.result">
          <div v-for="item in (turn.result.related_courses || []).slice(0, 3)" :key="item.id" class="as-card">
            <img v-if="httpsUrl(item.cover_url)" :src="httpsUrl(item.cover_url)" alt="" loading="lazy">
            <strong>{{ item.title }}</strong><p v-if="item.description">{{ item.description }}</p><p v-if="item.reason">推荐理由：{{ item.reason }}</p>
            <a v-if="courseUrl(item)" :href="courseUrl(item)" target="_blank" rel="noopener noreferrer">查看官网课程详情</a>
            <AButton v-if="item.purchase_url" class="as-primary" @click="purchase(item, turn)">去官网购买页</AButton>
          </div>
          <div v-if="showOwner(turn)" class="as-card">
            <strong>{{ turn.result.owner.configured ? (turn.result.owner.name || '课程顾问') : '暂未找到可用的课程顾问' }}</strong>
            <template v-if="ownerContact(turn)">
              <img v-if="imageUrl(ownerContact(turn)) && !turn.qrFailed" :src="ownerContact(turn)" alt="课程顾问二维码" @error="turn.qrFailed = true">
              <a v-else-if="!turn.qrFailed" :href="ownerContact(turn)" target="_blank" rel="noopener noreferrer">打开课程顾问联系方式</a>
              <a v-else-if="httpsUrl(config.fallback_contact)" :href="httpsUrl(config.fallback_contact)" target="_blank" rel="noopener noreferrer">二维码不可用，查看备用联系方式</a>
              <p v-else>联系方式暂不可用，请稍后重试。</p>
            </template>
            <p v-else>联系方式暂不可用，请稍后重试。</p>
            <template v-if="turn.result.handoff_summary"><AButton @click="copySummary(turn)">{{ turn.copyStatus || '复制咨询摘要' }}</AButton><pre>{{ turn.result.handoff_summary }}</pre></template>
          </div>
          <details v-if="turn.result.sources?.length || evidence(turn).length" class="as-evidence">
            <summary>查看回答依据</summary>
            <div v-for="(source, sourceIndex) in turn.result.sources || []" :key="sourceIndex" class="as-source">{{ source.title || '课程资料' }}{{ source.snippet ? ' · ' + source.snippet : '' }}</div>
            <div v-for="label in evidence(turn)" :key="label" class="as-source">{{ label }}</div>
          </details>
        </template>
        <p v-if="turn.actionError" class="as-error">{{ turn.actionError }}</p>
        <template v-if="turn.error"><div class="as-error" role="alert">{{ turn.error }}</div><AButton :disabled="busy" @click="ask(turn.question, turn)">重试本次提问</AButton></template>
      </template>
    </div>
    <div class="as-input">
      <form class="as-composer" @submit.prevent="ask()">
        <ATextarea ref="input" v-model:value="draft" :disabled="busy" :auto-size="{minRows:2,maxRows:5}" :maxlength="2000" :bordered="false" aria-label="咨询内容" placeholder="问问课程，或说说你想学什么…" @keydown="keydown" />
        <div class="as-composer-footer"><span class="as-key-hint">Enter 发送 · Shift + Enter 换行</span><AButton class="as-send" type="primary" html-type="submit" aria-label="发送消息" title="发送消息" :disabled="busy || !draft.trim()"><UiIcon name="send" /></AButton></div>
      </form>
      <p class="as-disclaimer">内容由 AI 辅助生成，重要信息请与课程顾问确认。</p>
    </div>
  </section>
  <AModal :open="editingSession !== null" title="重命名对话" :get-container="getPopupContainer" :z-index="2147483020" :width="340" :ok-button-props="{disabled:!renameValid}" ok-text="保存" cancel-text="取消" @ok="renameSession" @cancel="editingSession = null" destroy-on-close>
    <AInput v-model:value="nameDraft" aria-label="对话名称" placeholder="请输入对话名称" :maxlength="40" @press-enter="renameSession" />
  </AModal>
 </AConfigProvider>
 </StyleProvider>
</template>
