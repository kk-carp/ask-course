<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
import {
  ConfigProvider,
  Layout,
  LayoutSider,
  LayoutHeader,
  LayoutContent,
  Menu,
  MenuItem,
  Button,
  Input,
  InputPassword,
  Select,
  Card,
  Tag,
  Badge,
  Avatar,
  Breadcrumb,
  BreadcrumbItem,
  Alert,
  Spin,
  Table,
  Empty,
  Modal,
  Form,
  FormItem,
  UploadDragger,
  CheckboxGroup,
  Checkbox,
  Textarea,
  Drawer,
} from "ant-design-vue";
import {
  BookOutlined,
  BellOutlined,
  CommentOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ReloadOutlined,
  PlusOutlined,
  SearchOutlined,
  InboxOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  FileTextOutlined,
} from "@ant-design/icons-vue";
import zhCN from "ant-design-vue/es/locale/zh_CN";
import {
  useAdmin,
  views,
  statusLabels,
  statusColors,
  alertLabels,
} from "./useAdmin";
import Answer from "./Answer.vue";

const a = useAdmin();
// A reactive facade unwraps the composable's refs for template bindings.
const s = reactive(a);
const collapsed = ref(false),
  mobile = ref(false),
  history = ref(null),
  log = ref(null);
const nav = [
  { key: "documents", icon: BookOutlined },
  { key: "operations", icon: BellOutlined },
  { key: "debug", icon: CommentOutlined },
];
const theme = {
  token: {
    colorPrimary: "#167767",
    colorInfo: "#167767",
    borderRadius: 6,
    fontFamily: '"Microsoft YaHei", "PingFang SC", system-ui, sans-serif',
    colorBgLayout: "#f3f5f8",
    colorInfoBg: "#f0f7f5",
    colorInfoBorder: "#d6e9e3",
  },
};
const columns = [
  { title: "资料名称", key: "title", width: 300 },
  { title: "所属课程", key: "course", width: 180 },
  { title: "状态", key: "status", width: 110 },
  { title: "片段数", dataIndex: "chunk_count", width: 90 },
  { title: "操作", key: "actions", width: 280 },
];
const statuses = [
  { value: "", label: "全部状态" },
  ...Object.entries(statusLabels).map(([value, label]) => ({ value, label })),
];
const actionNames = {
  publish: "审核并发布",
  review: "复核安全并留档",
  offline: "撤回资料",
  delete: "永久删除",
};
const reviewing = computed(() =>
  ["publish", "review"].includes(s.action?.type),
);
const reviewChecks = [
  { value: "public", label: "来源已公开且允许对外使用" },
  { value: "sensitive", label: "不含密钥、个人信息、内部报价或合同" },
  { value: "business", label: "价格、功能与合作信息已由负责人核对" },
  { value: "instructions", label: "不含要求模型忽略规则的嵌入指令" },
];
const healthItems = computed(() => [
  { key: "api", label: "接口服务" },
  { key: "database", label: "数据库" },
  { key: "embedding_loaded", label: "向量模型" },
]);
const courseName = (id) =>
  s.courses.find((item) => item.id === id)?.title ||
  (id ? `课程 ${id}` : "未标注课程");
const prompts = [
  "推荐一门适合我的课程",
  "适合做保研或毕设吗",
  "我想找课程顾问",
];
watch(
  () => s.me,
  () => {
    history.value = null;
  },
);
watch(
  () => s.turns.map((turn) => turn.answer + turn.pending + turn.error).join(""),
  async () => {
    await nextTick();
    log.value?.scrollTo?.({ top: log.value.scrollHeight });
  },
);
watch(
  () => s.view,
  (value) => {
    if (value === "operations" && !s.alerts) s.refreshAlerts();
  },
);
function changeView(key) {
  s.view = key;
  s.error = "";
  if (mobile.value) collapsed.value = true;
}
function openUpload() {
  s.file = null;
  s.replacement = "";
  s.uploadOpen = true;
}
</script>

<template>
  <ConfigProvider :locale="zhCN" :theme="theme">
    <section v-if="!s.me" id="login-view" class="admin-login">
      <div class="login-brand">
        <div class="brand-mark">探</div>
        <span>天树探界 · 课程助手</span>
      </div>
      <Card class="login-card" :bordered="false">
        <div class="login-symbol"><SafetyCertificateOutlined /></div>
        <h1>登录管理后台</h1>
        <p class="muted">维护课程知识，让每一次咨询有据可依。</p>
        <Spin v-if="s.checking" tip="正在确认登录状态…" class="login-loading" />
        <form v-else id="login-form" @submit.prevent="s.login">
          <label for="username">管理员账号</label>
          <Input
            id="username"
            v-model:value="s.credentials.username"
            size="large"
            autocomplete="username"
            placeholder="请输入账号"
            required
          />
          <label for="password">密码</label>
          <InputPassword
            id="password"
            v-model:value="s.credentials.password"
            size="large"
            autocomplete="current-password"
            placeholder="请输入密码"
            required
          />
          <Alert
            v-if="s.loginError"
            id="login-error"
            :message="s.loginError"
            type="error"
            show-icon
            role="alert"
          />
          <Button
            id="login-submit"
            type="primary"
            html-type="submit"
            size="large"
            block
            :loading="s.loginBusy"
            >登录后台</Button
          >
        </form>
        <div class="login-foot">仅限内部授权账号使用</div>
      </Card>
      <p class="login-copyright">天树探界 · 售前服务管理</p>
    </section>

    <Layout v-else id="admin-shell" class="admin-shell">
      <div
        v-if="mobile && !collapsed"
        class="nav-mask"
        @click="collapsed = true"
      />
      <LayoutSider
        v-show="!mobile || !collapsed"
        v-model:collapsed="collapsed"
        :width="224"
        :trigger="null"
        :collapsed-width="mobile ? 0 : 72"
        breakpoint="lg"
        class="admin-sidebar"
        @breakpoint="
          (value) => {
            mobile = value;
            collapsed = value;
          }
        "
      >
        <div class="sidebar-brand">
          <div class="brand-mark">探</div>
          <div v-if="!collapsed">
            <strong>天树探界</strong><small>课程助手管理后台</small>
          </div>
        </div>
        <div v-if="!collapsed" class="nav-caption">工作空间</div>
        <Menu
          theme="dark"
          mode="inline"
          :selected-keys="[s.view]"
          @click="({ key }) => changeView(key)"
        >
          <MenuItem v-for="item in nav" :key="item.key" :data-view="item.key"
            ><template #icon><component :is="item.icon" /></template
            >{{ views[item.key].title }}</MenuItem
          >
        </Menu>
        <div class="sidebar-footer">
          <SafetyCertificateOutlined /><span v-if="!collapsed"
            >内部运营工作台</span
          >
        </div>
      </LayoutSider>
      <Layout class="admin-main">
        <LayoutHeader class="admin-header">
          <div class="header-left">
            <Button
              type="text"
              :aria-label="collapsed ? '展开导航' : '收起导航'"
              @click="collapsed = !collapsed"
              ><MenuUnfoldOutlined v-if="collapsed" /><MenuFoldOutlined v-else
            /></Button>
            <Breadcrumb
              ><BreadcrumbItem>管理后台</BreadcrumbItem
              ><BreadcrumbItem>{{
                views[s.view].title
              }}</BreadcrumbItem></Breadcrumb
            >
          </div>
          <div class="header-right">
            <Badge
              :status="s.health?.api ? 'success' : 'warning'"
              :text="s.health?.api ? '接口正常' : '接口未就绪'"
              class="header-health"
            /><Avatar :size="30" class="user-avatar">{{
              s.me.username?.slice(0, 1)
            }}</Avatar
            ><span id="who">{{ s.me.username }}</span
            ><Button
              id="logout"
              type="text"
              :loading="s.logoutBusy"
              @click="s.logout"
              ><LogoutOutlined /><span class="logout-label"
                >退出登录</span
              ></Button
            >
          </div>
        </LayoutHeader>
        <LayoutContent class="admin-content">
          <header class="page-heading">
            <div>
              <h1>{{ views[s.view].title }}</h1>
              <p>{{ views[s.view].description }}</p>
            </div>
            <Tag>{{ s.canManage ? "资料管理员" : "内部账号" }}</Tag>
          </header>
          <Alert
            v-if="s.error"
            id="admin-err"
            :message="s.error"
            type="error"
            show-icon
            closable
            role="alert"
            @close="s.error = ''"
          />
          <Alert
            v-if="s.notice"
            :message="s.notice"
            type="success"
            show-icon
            closable
            @close="s.notice = ''"
          />
          <Card v-if="!s.canManage && s.view !== 'debug'"
            ><Empty description="当前账号没有资料管理权限，请联系管理员。"
          /></Card>
          <template v-else>
            <Card
              v-if="s.view !== 'operations'"
              class="scope-card"
              :bordered="false"
            >
              <div class="scope-row">
                <span class="field-label">课程范围</span>
                <Select
                  id="course-select"
                  :value="s.courseId"
                  show-search
                  :filter-option="
                    (input, option) =>
                      `${option.label} ${option.value}`
                        .toLowerCase()
                        .includes(input.toLowerCase())
                  "
                  :disabled="s.asking || s.uploading || s.mutationBusy"
                  :loading="s.coursesBusy"
                  :options="[
                    {
                      value: '',
                      label: s.view === 'debug' ? '自动匹配课程' : '全部课程',
                    },
                    ...s.courses.map((c) => ({
                      value: c.id,
                      label: `${c.title}（${c.id}）`,
                    })),
                  ]"
                  aria-label="选择课程"
                  @change="s.selectCourse"
                />
                <Button
                  v-if="s.canManage"
                  id="refresh-courses"
                  :loading="s.coursesBusy"
                  @click="s.refreshCourses"
                  ><ReloadOutlined />刷新课程</Button
                >
                <span class="scope-hint">{{
                  s.selectedCourse
                    ? `课程编号 ${s.courseId}`
                    : s.view === "documents"
                      ? `共 ${s.courses.length} 门课程`
                      : "根据问题自动选择相关课程"
                }}</span>
              </div>
              <Alert
                v-if="s.catalogError"
                :message="s.catalogError"
                type="error"
                show-icon
              />
            </Card>

            <section v-if="s.view === 'documents'" id="documents-view">
              <div id="document-counts" class="stat-grid">
                <Card :bordered="false"
                  ><span>资料总数</span
                  ><strong>{{ s.courseDocuments.length }}</strong
                  ><small>当前课程范围</small></Card
                ><Card :bordered="false"
                  ><span><Badge status="warning" />待审核</span
                  ><strong>{{ s.counts.pending }}</strong
                  ><small>审核后可参与回答</small></Card
                ><Card :bordered="false"
                  ><span><Badge status="success" />已发布</span
                  ><strong>{{ s.counts.ready }}</strong
                  ><small>可用于知识库检索</small></Card
                ><Card :bordered="false"
                  ><span><Badge status="default" />已撤回</span
                  ><strong>{{ s.counts.offline }}</strong
                  ><small>已停止用于回答</small></Card
                >
              </div>
              <Card class="documents-card" title="资料列表" :bordered="false">
                <template #extra
                  ><Button
                    id="open-upload"
                    type="primary"
                    :disabled="!s.courseId"
                    @click="openUpload"
                    ><PlusOutlined />上传资料</Button
                  ></template
                >
                <div class="table-toolbar">
                  <Input
                    id="document-search"
                    v-model:value="s.query"
                    placeholder="搜索资料名称"
                    allow-clear
                    aria-label="搜索资料名称"
                    ><template #prefix><SearchOutlined /></template></Input
                  ><Select
                    id="document-status"
                    v-model:value="s.status"
                    :options="statuses"
                    aria-label="筛选资料状态"
                  /><Button
                    data-refresh
                    :loading="s.docsBusy"
                    @click="s.refreshDocs"
                    ><ReloadOutlined />刷新</Button
                  ><span class="toolbar-count"
                    >共 {{ s.filteredDocuments.length }} 份资料</span
                  >
                </div>
                <Alert
                  class="document-tip"
                  type="info"
                  show-icon
                  :message="
                    s.courseId
                      ? '资料上传后进入待审核状态；下载核对原文后，再审核发布。'
                      : '请选择具体课程后上传资料；当前展示全部课程的资料。'
                  "
                />
                <Table
                  id="docs"
                  row-key="id"
                  :columns="columns"
                  :data-source="s.filteredDocuments"
                  :loading="s.docsBusy"
                  :scroll="{ x: 960 }"
                  :pagination="{
                    current: s.page,
                    pageSize: 10,
                    showSizeChanger: false,
                    hideOnSinglePage: true,
                  }"
                  @change="(pagination) => (s.page = pagination.current)"
                >
                  <template #emptyText
                    ><Empty
                      :description="
                        s.query || s.status
                          ? '没有符合筛选条件的资料，请调整筛选条件。'
                          : '暂无资料，请选择具体课程后上传。'
                      "
                  /></template>
                  <template #bodyCell="{ column, record }">
                    <template v-if="column.key === 'title'"
                      ><div class="document-name">
                        <FileTextOutlined /><strong>{{ record.title }}</strong>
                      </div>
                      <div v-if="record.error" class="document-error">
                        失败原因：{{ record.error }}
                      </div>
                      <small v-if="record.supersedes_id" class="muted"
                        >替换版本：{{ record.supersedes_id }}</small
                      ><Button
                        v-if="record.reviews?.length"
                        size="small"
                        type="link"
                        class="history-link"
                        @click="history = record"
                        >审核与撤回记录</Button
                      ></template
                    >
                    <template v-else-if="column.key === 'course'"
                      ><span>{{ courseName(record.course_id) }}</span
                      ><small class="cell-caption">{{
                        record.course_id || "—"
                      }}</small></template
                    >
                    <template v-else-if="column.key === 'status'"
                      ><Tag :color="statusColors[record.status]">{{
                        statusLabels[record.status] || record.status
                      }}</Tag></template
                    >
                    <template v-else-if="column.key === 'actions'"
                      ><div class="table-actions">
                        <a
                          :href="`/documents/${encodeURIComponent(record.id)}/file`"
                          download
                          >下载原文</a
                        ><Button
                          v-if="record.status === 'pending'"
                          type="link"
                          size="small"
                          data-action="publish"
                          :disabled="s.mutationBusy"
                          @click="s.startAction(record, 'publish')"
                          >审核发布</Button
                        ><Button
                          v-if="record.status === 'ready'"
                          type="link"
                          size="small"
                          data-action="review"
                          :disabled="s.mutationBusy"
                          @click="s.startAction(record, 'review')"
                          >安全复核</Button
                        ><Button
                          type="link"
                          size="small"
                          danger
                          :data-action="
                            record.status === 'offline' ? 'delete' : 'offline'
                          "
                          :disabled="s.mutationBusy"
                          @click="
                            s.startAction(
                              record,
                              record.status === 'offline'
                                ? 'delete'
                                : 'offline',
                            )
                          "
                          >{{
                            record.status === "offline" ? "永久删除" : "撤回"
                          }}</Button
                        >
                      </div></template
                    >
                  </template>
                </Table>
              </Card>
            </section>

            <section v-else-if="s.view === 'operations'" id="operations-view">
              <div class="health-grid">
                <Card
                  v-for="item in healthItems"
                  :key="item.key"
                  :bordered="false"
                  ><span class="muted">{{ item.label }}</span>
                  <div class="health-value">
                    <Badge
                      :status="s.health?.[item.key] ? 'success' : 'warning'"
                    />{{
                      !s.health
                        ? "正在检测"
                        : s.health[item.key]
                          ? "运行正常"
                          : "未就绪"
                    }}
                  </div></Card
                >
              </div>
              <Card title="运行告警" :bordered="false"
                ><template #extra
                  ><Button
                    id="refresh-alerts"
                    :loading="s.alertsBusy"
                    @click="
                      s.refreshAlerts();
                      s.refreshHealth();
                    "
                    ><ReloadOutlined />刷新状态</Button
                  ></template
                >
                <Alert
                  v-if="s.alertsError"
                  :message="s.alertsError"
                  type="error"
                  show-icon
                />
                <Spin :spinning="s.alertsBusy"
                  ><template v-if="s.alerts"
                    ><div class="metrics-summary">
                      <div>
                        <span>今日估算费用</span
                        ><strong>{{
                          s.alerts.estimated_cost ?? "暂无数据"
                        }}</strong
                        ><small>按配置货币，仅供参考</small>
                      </div>
                      <div>
                        <span>最近采集时间</span
                        ><strong class="updated-time">{{
                          s.alerts.updated_at
                            ? new Date(
                                s.alerts.updated_at * 1000,
                              ).toLocaleString("zh-CN")
                            : "尚未采集"
                        }}</strong>
                      </div>
                    </div>
                    <div class="alerts-list">
                      <Alert
                        v-for="(item, index) in s.alerts.alerts"
                        :key="index"
                        :type="
                          item.severity === 'critical' ? 'error' : 'warning'
                        "
                        show-icon
                        :message="alertLabels[item.code] || item.code"
                      />
                    </div>
                    <Empty
                      v-if="!s.alerts.alerts?.length"
                      description="当前没有触发告警" /></template
                  ><Empty v-else description="暂无告警数据，请刷新状态"
                /></Spin>
              </Card>
            </section>

            <Card
              v-else
              id="debug-view"
              class="debug-card"
              :bordered="false"
              title="咨询测试"
              ><template #extra><Tag color="cyan">内部调试</Tag></template>
              <div ref="log" class="chat-log" aria-live="polite">
                <div v-if="!s.turns.length" class="chat-empty">
                  <CommentOutlined />
                  <h2>从一个课程问题开始</h2>
                  <p>回答将使用当前课程范围内已发布的资料。</p>
                  <div class="prompt-list">
                    <Button
                      v-for="prompt in prompts"
                      :key="prompt"
                      @click="s.ask(prompt, true)"
                      >{{ prompt }}</Button
                    >
                  </div>
                </div>
                <article
                  v-for="(turn, index) in s.turns"
                  :key="index"
                  class="chat-turn"
                >
                  <div class="chat-question">{{ turn.question }}</div>
                  <div class="chat-answer">
                    <span class="answer-author">探界助手</span
                    ><Spin
                      v-if="turn.pending && !turn.answer"
                      size="small"
                    /><span v-if="turn.pending && !turn.answer" class="muted">{{
                      turn.progress
                    }}</span
                    ><Answer
                      v-if="turn.answer || turn.result"
                      :answer="turn.answer"
                      :result="turn.result"
                    /><Alert
                      v-if="turn.error"
                      :message="turn.error"
                      type="error"
                    /><Button
                      v-if="turn.error"
                      :disabled="s.asking"
                      @click="s.ask(turn.question)"
                      >重试本次提问</Button
                    >
                  </div>
                </article>
              </div>
              <form class="chat-composer" @submit.prevent="s.ask()">
                <Textarea
                  id="question"
                  v-model:value="s.question"
                  :auto-size="{ minRows: 2, maxRows: 6 }"
                  placeholder="输入课程问题，核对实际回答效果"
                  aria-label="咨询问题"
                  :disabled="s.asking"
                />
                <div>
                  <span class="muted"
                    >请核对回答和引用资料后再用于对外服务。</span
                  ><Button
                    id="send"
                    type="primary"
                    html-type="submit"
                    :loading="s.asking"
                    :disabled="!s.question.trim()"
                    >发送问题</Button
                  >
                </div>
              </form>
            </Card>
          </template>
          <footer class="content-footer">天树探界 · 课程助手管理后台</footer>
        </LayoutContent>
      </Layout>
    </Layout>

    <Modal
      v-if="s.me"
      v-model:open="s.uploadOpen"
      title="上传课程资料"
      :footer="null"
      :closable="!s.uploading"
      :mask-closable="!s.uploading"
      :keyboard="!s.uploading"
      :destroy-on-close="true"
    >
      <Alert v-if="s.error" :message="s.error" type="error" show-icon />
      <Form
        id="upload-form"
        layout="vertical"
        :model="{ file: s.file, replacement: s.replacement }"
        @finish="s.upload"
        ><FormItem label="所属课程"
          ><Input :value="s.selectedCourse?.title" disabled /></FormItem
        ><FormItem label="资料用途"
          ><Select
            id="replacement-target"
            v-model:value="s.replacement"
            :disabled="s.uploading"
            :options="[
              { value: '', label: '新增独立资料' },
              ...s.replacementOptions,
            ]" /></FormItem
        ><FormItem label="课程文件"
          ><UploadDragger
            :multiple="false"
            :disabled="s.uploading"
            accept=".md,.txt,.pdf,.docx,.pptx"
            :file-list="s.file ? [s.file] : []"
            :before-upload="
              (file) => {
                s.file = file;
                return false;
              }
            "
            @remove="s.file = null"
            ><p class="upload-icon"><InboxOutlined /></p>
            <p>点击或拖拽文件到此处</p>
            <p class="muted">支持 md、txt、pdf、docx、pptx</p></UploadDragger
          ></FormItem
        ><Alert
          type="info"
          show-icon
          message="上传后待审核，不会立即参与回答。替换资料时，旧版在新版发布前保持可用。"
        />
        <div class="modal-actions">
          <Button :disabled="s.uploading" @click="s.uploadOpen = false"
            >取消</Button
          ><Button
            type="primary"
            html-type="submit"
            :loading="s.uploading"
            :disabled="!s.file || !s.courseId"
            >上传待审核资料</Button
          >
        </div></Form
      >
    </Modal>
    <Modal
      :open="Boolean(s.action)"
      :title="actionNames[s.action?.type]"
      :ok-text="actionNames[s.action?.type]"
      :confirm-loading="s.mutationBusy"
      :ok-button-props="{
        danger: !reviewing,
        disabled: reviewing && (!s.reviewNote.trim() || s.checks.length !== 4),
        'data-confirm-action': true,
      }"
      :cancel-button-props="{ disabled: s.mutationBusy }"
      :closable="!s.mutationBusy"
      :mask-closable="!s.mutationBusy"
      :keyboard="!s.mutationBusy"
      @ok="s.confirmAction"
      @cancel="s.action = null"
    >
      <template v-if="s.action"
        ><p class="action-document">{{ s.action.item.title }}</p>
        <Alert
          v-if="s.error"
          :message="s.error"
          type="error"
          show-icon /><template v-if="reviewing"
          ><p>请先下载核对原文，逐项确认以下内容：</p>
          <CheckboxGroup
            v-model:value="s.checks"
            :disabled="s.mutationBusy"
            class="review-checks"
            ><Checkbox
              v-for="check in reviewChecks"
              :key="check.value"
              :value="check.value"
              >{{ check.label }}</Checkbox
            ></CheckboxGroup
          ><label for="review-note" class="review-label">审核依据（必填）</label
          ><Textarea
            id="review-note"
            v-model:value="s.reviewNote"
            :disabled="s.mutationBusy"
            :rows="3"
            placeholder="例如：课程负责人确认记录、适用范围" /><Alert
            v-if="s.action.type === 'publish' && s.action.item.supersedes_id"
            type="warning"
            message="发布新版时，旧版将同时撤回。" /></template
        ><Alert
          v-else
          type="warning"
          show-icon
          :message="
            s.action.type === 'delete'
              ? '永久删除后，原文和检索片段均无法恢复。'
              : '撤回后不再参与回答，正在生成且依赖该资料的回答也将停止。撤回后不能重新发布。'
          "
      /></template>
    </Modal>
    <Drawer
      :open="Boolean(history)"
      title="审核与撤回记录"
      :width="mobile ? '100%' : 460"
      @close="history = null"
      ><h3>{{ history?.title }}</h3>
      <Empty v-if="!history?.reviews?.length" description="暂无记录" />
      <div
        v-for="(item, index) in history?.reviews"
        :key="index"
        class="review-record"
      >
        <Tag>{{
          {
            publish: "审核发布",
            review: "安全复核",
            withdraw: "主动撤回",
            superseded: "被新版替换",
          }[item.action] || item.action
        }}</Tag>
        <p>{{ item.note }}</p>
        <small class="muted">{{ item.actor_id }} · {{ item.created_at }}</small>
      </div></Drawer
    >
  </ConfigProvider>
</template>
