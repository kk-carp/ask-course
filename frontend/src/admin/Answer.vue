<script setup>
import { computed, ref } from "vue";
import { Alert, Button, Tag } from "ant-design-vue";
import { courseUrl, httpsUrl } from "../api";
const props = defineProps({ answer: String, result: Object });
const result = computed(() => props.result || {});
const failedQr = ref(false),
  copyState = ref("复制咨询摘要"),
  purchaseError = ref("");
const format = window.AnswerFormat;
const ownerVisible = computed(
  () =>
    result.value.owner &&
    (["advisor", "commercial", "multi_question"].includes(
      result.value.intent,
    ) ||
      (result.value.hit === false && !result.value.related_courses?.length)),
);
const contact = computed(() => httpsUrl(result.value.owner?.contact));
const imageContact = computed(
  () =>
    contact.value &&
    /\.(png|jpe?g|webp|gif|svg|bmp)$/i.test(new URL(contact.value).pathname),
);
async function copy() {
  try {
    await navigator.clipboard.writeText(result.value.handoff_summary);
    copyState.value = "已复制";
  } catch {
    copyState.value = "复制失败，请手动选择摘要";
  }
}
async function buy(item) {
  purchaseError.value = "";
  try {
    const response = await fetch(
      `/courses/${encodeURIComponent(item.id)}/purchase`,
      { credentials: "include" },
    );
    if (!response.ok) throw new Error("课程购买入口暂不可用");
    const data = await response.json(),
      url = new URL(data.url);
    if (url.protocol !== "https:" || url.hostname !== "www.arborseek.com")
      throw new Error("课程购买地址无效");
    location.assign(url.href);
  } catch (cause) {
    purchaseError.value = cause.message;
  }
}
</script>
<template>
  <div class="answer-tags">
    <Tag v-if="result.hit === true" color="green">{{
      result.intent === "course_info" ? "官网课程信息" : "有资料依据"
    }}</Tag
    ><Tag v-else-if="result.related_courses?.length" color="green"
      >已匹配课程</Tag
    ><Tag v-if="result.intent === 'multi_question'">逐项回答</Tag
    ><Tag v-if="result.llm_called">已调用对话模型</Tag>
  </div>
  <div class="answer-markdown" v-html="format.markdown(answer)" />
  <div v-if="result.related_courses?.length" class="related-courses">
    <strong>相关官网课程</strong>
    <article
      v-for="item in result.related_courses.slice(0, 3)"
      :key="item.id"
      class="related-course"
    >
      <img
        v-if="httpsUrl(item.cover_url)"
        :src="httpsUrl(item.cover_url)"
        alt=""
        loading="lazy"
      />
      <div>
        <strong>{{ item.title }}</strong>
        <p v-if="item.description">{{ item.description }}</p>
        <p v-if="item.reason">推荐理由：{{ item.reason }}</p>
        <a
          v-if="courseUrl(item)"
          :href="courseUrl(item)"
          target="_blank"
          rel="noopener noreferrer"
          >查看官网课程详情</a
        ><Button v-if="item.purchase_url" type="link" @click="buy(item)"
          >去官网购买页</Button
        >
      </div>
    </article>
  </div>
  <Alert v-if="purchaseError" type="error" :message="purchaseError" />
  <details
    v-if="result.sources?.length || result.fact_sources?.length"
    class="answer-sources"
  >
    <summary>查看回答依据</summary>
    <div v-for="(source, index) in result.sources" :key="index">
      <strong>{{ source.title || "来源" }}</strong>
      <p>{{ source.snippet }}</p>
    </div>
    <p
      v-for="label in format.factSourceLabels(result.fact_sources)"
      :key="label"
    >
      {{ label }}
    </p>
  </details>
  <div v-if="ownerVisible" class="answer-handoff">
    <template v-if="result.owner.configured"
      ><strong>{{ result.owner.name || "课程顾问" }}</strong>
      <p>{{ result.owner.topic_name }}</p>
      <img
        v-if="imageContact && !failedQr"
        :src="contact"
        alt="企业微信二维码"
        width="168"
        height="168"
        @error="failedQr = true"
      /><a
        v-else-if="!imageContact && contact"
        :href="contact"
        target="_blank"
        rel="noopener noreferrer"
        >联系课程顾问</a
      ><a
        v-else-if="httpsUrl(result.fallback_contact)"
        :href="httpsUrl(result.fallback_contact)"
        target="_blank"
        rel="noopener noreferrer"
        >查看备用联系方式</a
      >
      <p v-else>联系方式暂不可用，请稍后重试。</p></template
    ><template v-else
      ><strong>课程顾问联系方式暂不可用</strong>
      <p>你可以先查看官网课程详情，或继续咨询已公开的课程信息。</p></template
    >
  </div>
  <div v-if="result.handoff_summary" class="answer-handoff">
    <Button size="small" @click="copy">{{ copyState }}</Button>
    <pre>{{ result.handoff_summary }}</pre>
  </div>
</template>
