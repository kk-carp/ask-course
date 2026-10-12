import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { json, streamAsk } from "../api";

export const statusLabels = {
  pending: "待审核",
  ready: "已发布",
  offline: "已撤回",
  failed: "入库失败",
  processing: "处理中",
};
export const statusColors = {
  pending: "orange",
  ready: "green",
  offline: "default",
  failed: "red",
  processing: "blue",
};
export const views = {
  documents: {
    title: "课程资料",
    description: "维护课程知识库，审核并发布可用于回答的资料。",
  },
  operations: {
    title: "运行告警",
    description: "查看服务状态、运行告警与当日费用估算。",
  },
  debug: {
    title: "问答调试",
    description: "模拟学员咨询，检查回答内容与资料来源。",
  },
};
export const alertLabels = {
  service_unavailable: "服务不可用",
  metrics_unavailable: "指标采集失败",
  collector_stale_or_not_started: "监控未启动或已失联",
  http_error_rate: "接口错误过多",
  model_error_rate: "模型故障过多",
  model_timeout: "模型超时",
  request_latency_p95: "回答耗时过长",
  abnormal_rate_limited_calls: "异常限流调用增多",
  cost_monitor_not_configured: "模型单价或预算未配置",
  model_usage_missing_cost_incomplete: "模型未返回完整用量，费用可能漏计",
  daily_cost_budget: "已达到当日费用预算",
  process_restarted_sampling_gap: "服务重启，用量可能存在采样缺口",
};

export function useAdmin() {
  const me = ref(null),
    checking = ref(true),
    loginBusy = ref(false),
    logoutBusy = ref(false);
  const credentials = reactive({ username: "", password: "" });
  const loginError = ref(""),
    error = ref(""),
    notice = ref("");
  const view = ref("documents"),
    courses = ref([]),
    courseId = ref("");
  const documents = ref([]),
    query = ref(""),
    status = ref(""),
    page = ref(1);
  const docsBusy = ref(false),
    coursesBusy = ref(false),
    catalogError = ref("");
  const uploading = ref(false),
    mutationBusy = ref(false),
    file = ref(null),
    replacement = ref("");
  const uploadOpen = ref(false),
    action = ref(null),
    reviewNote = ref(""),
    checks = ref([]);
  const health = ref(null),
    alerts = ref(null),
    alertsBusy = ref(false),
    alertsError = ref("");
  const question = ref(""),
    turns = ref([]),
    asking = ref(false),
    conversationId = ref(null);
  let identity = 0,
    docsRevision = 0,
    catalogRevision = 0,
    controller,
    timer;
  const canManage = computed(() => Boolean(me.value?.can_manage_documents));
  const courseDocuments = computed(() =>
    documents.value.filter(
      (item) => !courseId.value || item.course_id === courseId.value,
    ),
  );
  const filteredDocuments = computed(() =>
    courseDocuments.value.filter(
      (item) =>
        (!status.value || item.status === status.value) &&
        String(item.title || "")
          .toLowerCase()
          .includes(query.value.trim().toLowerCase()),
    ),
  );
  const selectedCourse = computed(() =>
    courses.value.find((item) => item.id === courseId.value),
  );
  const replacementOptions = computed(() =>
    courseDocuments.value
      .filter(
        (item) => item.status === "ready" && item.course_id === courseId.value,
      )
      .map((item) => ({ value: item.id, label: `替换：${item.title}` })),
  );
  const counts = computed(() =>
    Object.fromEntries(
      Object.keys(statusLabels).map((key) => [
        key,
        courseDocuments.value.filter((item) => item.status === key).length,
      ]),
    ),
  );
  watch([courseId, query, status], () => {
    page.value = 1;
  });
  watch(courseId, () => {
    replacement.value = "";
    conversationId.value = null;
    turns.value = [];
  });

  function clearIdentity() {
    identity++;
    docsRevision++;
    catalogRevision++;
    controller?.abort();
    controller = null;
    me.value = null;
    courses.value = [];
    documents.value = [];
    turns.value = [];
    courseId.value = "";
    query.value = "";
    status.value = "";
    view.value = "documents";
    credentials.password = "";
    question.value = "";
    conversationId.value = null;
    uploadOpen.value = false;
    action.value = null;
    file.value = null;
    replacement.value = "";
    checks.value = [];
    reviewNote.value = "";
    alerts.value = null;
    alertsError.value = "";
    catalogError.value = "";
    error.value = "";
    notice.value = "";
    asking.value =
      uploading.value =
      mutationBusy.value =
      docsBusy.value =
      coursesBusy.value =
      alertsBusy.value =
        false;
  }
  function expire(revision) {
    if (revision !== identity) return;
    clearIdentity();
    loginError.value = "登录已过期，请重新登录。";
  }
  async function request(path, method = "GET", payload) {
    const revision = identity;
    try {
      return await json((value) => value, path, method, payload);
    } catch (cause) {
      if (cause.status === 401) expire(revision);
      throw cause;
    }
  }
  async function refreshDocs() {
    if (!canManage.value) return;
    const owner = identity,
      revision = ++docsRevision;
    docsBusy.value = true;
    error.value = "";
    try {
      const result = await request("/documents");
      if (owner === identity && revision === docsRevision)
        documents.value = result;
    } catch (cause) {
      if (owner === identity && revision === docsRevision)
        error.value = cause.message;
    } finally {
      if (owner === identity && revision === docsRevision)
        docsBusy.value = false;
    }
  }
  async function refreshCourses() {
    if (!canManage.value) return;
    const owner = identity,
      revision = ++catalogRevision;
    coursesBusy.value = true;
    catalogError.value = "";
    try {
      const result = await request("/admin/courses");
      if (owner !== identity || revision !== catalogRevision) return;
      courses.value = result.map((item) => ({ ...item, id: String(item.id) }));
      if (!courses.value.some((item) => item.id === courseId.value))
        courseId.value = "";
    } catch (cause) {
      if (owner === identity && revision === catalogRevision)
        catalogError.value = cause.message;
    } finally {
      if (owner === identity && revision === catalogRevision)
        coursesBusy.value = false;
    }
  }
  function loadManagement() {
    if (canManage.value) {
      refreshDocs();
      refreshCourses();
    }
  }
  async function login() {
    if (loginBusy.value) return;
    loginBusy.value = true;
    loginError.value = "";
    const owner = identity;
    try {
      const user = await json((value) => value, "/login", "POST", {
        username: credentials.username.trim(),
        password: credentials.password,
      });
      if (owner !== identity) return;
      clearIdentity();
      me.value = user;
      loadManagement();
    } catch (cause) {
      if (owner === identity)
        loginError.value =
          cause.status === 401
            ? "账号或密码错误，请重新输入。"
            : cause.status === 429
              ? "登录尝试过于频繁，请稍后重试。"
              : cause.message;
    } finally {
      loginBusy.value = false;
    }
  }
  async function logout() {
    if (logoutBusy.value) return;
    logoutBusy.value = true;
    try {
      await request("/logout", "POST");
      clearIdentity();
      loginError.value = "";
    } catch (cause) {
      if (me.value) error.value = cause.message;
    } finally {
      logoutBusy.value = false;
    }
  }
  function selectCourse(id) {
    if (!asking.value && !uploading.value && !mutationBusy.value)
      courseId.value = id;
  }
  function startAction(item, type) {
    action.value = { item, type };
    reviewNote.value = "";
    checks.value = [];
  }
  async function confirmAction() {
    if (!action.value || mutationBusy.value || !canManage.value) return;
    const { item, type } = action.value,
      reviewing = ["publish", "review"].includes(type);
    if (reviewing && (!reviewNote.value.trim() || checks.value.length !== 4))
      return;
    const owner = identity;
    mutationBusy.value = true;
    error.value = "";
    notice.value = "";
    try {
      await request(
        `/documents/${encodeURIComponent(item.id)}${type === "delete" ? "" : "/" + type}`,
        type === "delete" ? "DELETE" : "POST",
        reviewing
          ? {
              note: reviewNote.value.trim(),
              safety_checks: {
                public_source: true,
                no_sensitive_data: true,
                business_verified: true,
                no_embedded_instructions: true,
              },
            }
          : undefined,
      );
      if (owner !== identity) return;
      action.value = null;
      notice.value = {
        publish: "资料已发布。",
        review: "复核记录已保存。",
        offline: "资料已撤回。",
        delete: "资料已永久删除。",
      }[type];
      await refreshDocs();
    } catch (cause) {
      if (owner === identity) error.value = cause.message;
    } finally {
      if (owner === identity) mutationBusy.value = false;
    }
  }
  async function upload() {
    if (!canManage.value || uploading.value || !file.value || !courseId.value)
      return;
    const owner = identity,
      data = new FormData();
    data.append("space", "courses");
    data.append("course_id", courseId.value);
    data.append("file", file.value);
    if (replacement.value) data.append("supersedes_id", replacement.value);
    uploading.value = true;
    error.value = "";
    notice.value = "";
    try {
      const response = await fetch("/documents", {
        method: "POST",
        credentials: "include",
        body: data,
      });
      if (response.status === 401) expire(owner);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(
          typeof body.detail === "string" ? body.detail : "上传失败，请重试。",
        );
      }
      if (owner !== identity) return;
      file.value = null;
      replacement.value = "";
      uploadOpen.value = false;
      notice.value = "资料已上传，审核发布后才会参与回答。";
      await refreshDocs();
      refreshCourses();
    } catch (cause) {
      if (owner === identity) error.value = cause.message;
    } finally {
      if (owner === identity) uploading.value = false;
    }
  }
  async function refreshHealth() {
    try {
      health.value = await json((value) => value, "/health");
    } catch {
      health.value = { api: false, database: false, embedding_loaded: false };
    }
  }
  async function refreshAlerts() {
    if (!canManage.value || alertsBusy.value) return;
    const owner = identity;
    alertsBusy.value = true;
    alertsError.value = "";
    try {
      const result = await request("/metrics/alerts");
      if (owner === identity) alerts.value = result;
    } catch (cause) {
      if (owner === identity) alertsError.value = cause.message;
    } finally {
      if (owner === identity) alertsBusy.value = false;
    }
  }
  async function ask(text = question.value, fresh = false) {
    if (!me.value || asking.value || !text.trim()) return;
    if (fresh) conversationId.value = null;
    const owner = identity,
      active = new AbortController();
    controller = active;
    const turn = reactive({
      question: text.trim(),
      answer: "",
      result: null,
      error: "",
      progress: "正在检索课程知识库…",
      pending: true,
    });
    turns.value.push(turn);
    question.value = "";
    asking.value = true;
    const parts = [];
    try {
      const result = await streamAsk(
        (path) => "/" + path,
        {
          question: turn.question,
          channel: "internal_tool",
          course_id: courseId.value || null,
          conversation_id: conversationId.value,
        },
        (part) => {
          if (owner !== identity) return;
          parts[part.index - 1] =
            `${part.index}. ${part.question}\n${part.answer}`;
          turn.answer = parts.filter(Boolean).join("\n\n");
        },
        {
          signal: active.signal,
          onEvent: (name, data) => {
            if (owner !== identity) return;
            if (name === "delta") turn.answer += data.text || "";
            if (name === "meta") turn.result = { ...turn.result, ...data };
            if (name === "progress") turn.progress = data.message;
          },
        },
      );
      if (owner !== identity) return;
      turn.result = result;
      turn.answer = result.answer || turn.answer;
      conversationId.value = result.conversation_id || conversationId.value;
      if (["upstream_error", "service_unavailable"].includes(result.error_type))
        turn.error = "服务暂不可用，可重试本次提问。";
    } catch (cause) {
      if (cause.status === 401) expire(owner);
      if (owner === identity && !active.signal.aborted) {
        turn.error = cause.message;
        if (cause.discardAnswer) turn.answer = "";
      }
    } finally {
      if (owner === identity) {
        turn.pending = false;
        asking.value = false;
        controller = null;
      }
    }
  }
  onMounted(async () => {
    refreshHealth();
    timer = setInterval(refreshHealth, 15000);
    const owner = identity;
    try {
      const user = await json((value) => value, "/me");
      if (owner === identity) {
        me.value = user;
        loadManagement();
      }
    } catch (cause) {
      if (owner === identity && cause.status !== 401)
        loginError.value = "无法确认登录状态，请重新登录。";
    } finally {
      checking.value = false;
    }
  });
  onBeforeUnmount(() => {
    clearInterval(timer);
    clearIdentity();
  });
  return {
    me,
    checking,
    loginBusy,
    logoutBusy,
    credentials,
    loginError,
    error,
    notice,
    view,
    courses,
    courseId,
    documents,
    query,
    status,
    page,
    docsBusy,
    coursesBusy,
    catalogError,
    uploading,
    mutationBusy,
    file,
    replacement,
    uploadOpen,
    action,
    reviewNote,
    checks,
    health,
    alerts,
    alertsBusy,
    alertsError,
    question,
    turns,
    asking,
    canManage,
    courseDocuments,
    filteredDocuments,
    selectedCourse,
    replacementOptions,
    counts,
    refreshDocs,
    refreshCourses,
    login,
    logout,
    selectCourse,
    startAction,
    confirmAction,
    upload,
    refreshHealth,
    refreshAlerts,
    ask,
  };
}
