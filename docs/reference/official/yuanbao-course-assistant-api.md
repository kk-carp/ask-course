# 源宝（元宝）与课程助手可调用接口清单

整理日期：2026-10-09。依据当前本地后端路由、工具白名单、控制器及课程前端调用代码整理；未对线上部署、配置开关和真实账号逐项联调。

本文中的“元宝”对应项目内的“源宝”（`yuanbao`）；“课程助手”主要指课程智能体“天小树”。课程任务页内的 AI 学习助手另列在第 4 节。

接口地址均相对于后端 API 域名。小程序路由直接以 `/miniapp` 开头，不额外添加 `/api`。

## 1. 能力概览

| 对象 | 模型实际可调用的工具 | 可查询范围 | 登录要求 | 模型与计费 |
| --- | --- | --- | --- | --- |
| 源宝 | `search_content`、`read_content`，共 2 个 | 星球文章、资讯、书刊、视频、星球、问答、动态、论文，共 8 类 | 必须登录，且源宝开关开启 | 平台配置的 DeepSeek 官方渠道；用户积分扣费为 0 |
| 课程助手“天小树” | 登录后 6 个；游客 2 个 | 公开课程、公开资讯；登录后增加本人课程、学习进度、课程推荐、课程订单、优惠券 | 公开查询支持游客；个人查询必须登录 | 平台配置的 DeepSeek 官方渠道；用户积分扣费为 0 |
| 课程任务页学习助手 | 前端固定工作流，当前没有注册业务查询工具 | 当前任务资料、用户附件、问答、总结、思维导图、测验、代码、笔记 | 必须登录 | 统一 AI 网关；校验账号模型权限并按积分规则计费 |

“模型可调用工具”与“客户端 HTTP 接口”是两层能力。客户端通过对话接口发问题，后端再选择、执行工具；会话创建、收藏、删除等接口由客户端调用，不代表模型拥有这些写操作权限。

## 2. 源宝

### 2.1 模型工具

这两个工具在后端内部执行，当前没有同名、可供外部直接调用的独立 HTTP 路由。

| 工具名 | 用途 | 参数 | 返回内容 |
| --- | --- | --- | --- |
| `search_content` | 按关键词和类型检索站内内容 | `keyword`：可选，最多 100 字；`kinds`：可选类型数组；`sort`：`latest` 或 `featured`，默认 `latest`；`limit`：默认 5，最多 5 | 候选内容及题录、摘要、来源类型、真实 ID；可用栏目 `available_kinds` |
| `read_content` | 按账号权益读取已定位的内容 | `sources`：1～3 项；每项必填 `kind`、正整数 `id`；书刊或视频可传 `section`，范围 1～10000 | 可读取的资料节选、读取范围、锁定状态及来源信息 |

`kinds` 可选值：

| 值 | 类型 | 实际读取范围与限制 |
| --- | --- | --- |
| `article` | 星球文章 | 公开摘要；有正文权限时读取最多 12000 字符正文节选 |
| `news` | 资讯 | 公开摘要、已发布资讯正文节选，正文最多 12000 字符 |
| `book` | 书刊 | 公开摘要、目录及指定章节；默认第 1 节，按权益返回正文或试读节选，锁定章节不返回正文 |
| `video` | 视频 | 简介、分集目录、时长和账号观看权限；可指定分集，目录最多展示 20 集；不读取字幕或视频画面 |
| `planet` | 星球 | 可分享、有效星球的公开介绍、加入方式、基础方案和成员数；不代替用户加入或购买 |
| `question` | 问答 | 有权限的问题正文，以及最多 3 条已发布回答的节选 |
| `thought` | 动态 | 公开摘要；有权限时读取正文节选 |
| `paper` | 论文 | 题录、摘要、站内解读或解读试读节选；**当前不下载、解析 PDF 原文** |

权限和数量规则：

- 书刊、论文、资讯、视频还受各栏目开关控制；实际可用类型以 `available_kinds` 为准。
- 星球内容受发布状态、星球有效状态、分享设置及账号成员权益限制；未获得正文权限时只使用公开摘要。书刊和论文沿用内容库权益、试读规则。
- 源宝本次请求按基础学员身份执行，保留真实账号 ID 和购买、成员权益，不因后台管理员身份扩大读取权限。
- 自动检索最多 2 轮、合计 4 次工具调用；本轮累计读取最多 6 项内容。每次回答推荐总数最多 5 项，混合类型也合计最多 5 项。
- 自动读取必须使用本轮已检索或历史已定位的真实类型及 ID；不接受模型猜测编号。
- 只有用户本轮明确索取原文或下载链接时，才返回资料中核对到的外链。普通推荐通过站内内容卡片打开详情。

### 2.2 客户端 HTTP 接口

统一前缀：`/miniapp/community/yuanbao`。以下全部要求登录，受 `community.yuanbao_enabled` 开关控制；关闭时返回 HTTP 403。

| 方法 | 相对路径 | 用途 | 主要参数 |
| --- | --- | --- | --- |
| GET | `/models` | 获取平台固定模型，兼容旧客户端 | 无；返回 `models` 和 `points_cost: 0` |
| GET | `/sources` | 搜索可选参考内容 | `keyword`、单个 `kind`（默认 `article`）、`page`（1～1000）；每页 8 项 |
| POST | `/sources/prepare` | 为本人会话设置或清空参考内容 | 必填 UUID `conversation_id`、`sources` 数组（0～3 项）；每项 `kind`、`id`，可选 `section` |
| GET | `/papers` | 查询已发布论文题录，兼容旧客户端 | `keyword`、`page`；每页 20 项 |
| POST | `/papers/prepare` | 为本人会话设置或清空参考论文，兼容旧客户端 | 必填 UUID `conversation_id`、`paper_ids`（0～3 个不重复正整数） |
| GET | `/conversations` | 查询本人的源宝会话 | `page`、`per_page`（默认 20，最多 50）、`keyword`、`favorites` |
| POST | `/conversations` | 新建源宝会话 | 必填 `title`，最多 100 字；返回 UUID `conversation_id` |
| POST | `/chat` | 提问，后端检索、读取并生成回复 | 必填 `message`，最多 10000 字；可选 UUID `conversation_id`，不传则创建会话 |
| GET | `/conversations/{conversationId}` | 查询本人会话与历史消息 | 可选 `before_id`；每次最多 30 条，返回 `has_more`、参考内容和消息来源 |
| PUT | `/conversations/{conversationId}/favorite` | 收藏或取消收藏本人会话 | 必填布尔值 `is_favorite` |
| DELETE | `/conversations/{conversationId}` | 删除本人源宝会话 | 路径参数为 UUID |

共 11 个 HTTP 路由。`/chat` 返回普通 JSON，**不是 SSE**。创建会话、准备参考内容及聊天分别配置了 `throttle:20,1`；同一会话处理消息或切换参考内容时使用锁，冲突返回 409。

聊天成功响应的核心字段：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "conversation_id": "服务端返回的会话 UUID",
    "content": "回答正文",
    "points_cost": 0,
    "sources": [],
    "manual_sources": [],
    "assistant_message_id": 123,
    "usage": {}
  }
}
```

调用示例（请求正文）：

```json
{
  "message": "推荐适合入门的机器人视频，并说明观看顺序"
}
```

手选资料不是聊天前置条件。需要指定内容时，先创建会话，再调用 `/sources/prepare`；`sources: []` 可清空选择。准备接口返回参考题录，不把内部读取正文直接返回给客户端。

### 2.3 当前边界

源宝可以解释使用步骤，但模型工具全部只读，不能代用户发布或修改文章、资讯、书刊、论文，也不能购买、支付、加入星球、关注或读取个人订单。此前 CLI 的上传、价格、PUT 修改接口属于独立的 AK/SK 内容管理能力，没有因此自动开放给源宝。

## 3. 课程助手“天小树”

前端入口为 `/ai/agent-demo`，后端对话入口为：

```http
POST /miniapp/ai/agent/chat
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer <当前用户 JWT 或 ts_ AI 凭证>
```

游客可省略 `Authorization`。`ts_` 凭证和 JWT 最终绑定同一 `members.id`，个人查询身份由服务端注入，工具参数不接受 `user_id`。

### 3.1 实际开放的 6 个模型工具

| 工具名 | 用途与主要返回数据 | 参数及默认值 | 游客 |
| --- | --- | --- | --- |
| `search_courses` | 搜索已上架、前台可见课程；返回标题、简介、封面、类型、价格、难度及真实链接 | `keyword`：可选，最多 100 字；`courseType`：`all/standard/open/training`，默认 `all`；`freeOnly`：布尔值，默认 `false`；`count`：默认 8，范围 1～12 | 可用 |
| `search_news` | 搜索已发布、审核通过且发布时间不晚于当前时间的站内资讯；返回题目、摘要、封面、发布时间及真实链接，当前不返回正文 | `keyword`：可选，最多 100 字；`startTime/endTime`：可选日期 `YYYY-MM-DD`，结束日包含当天；`limit`：默认 8，范围 1～12 | 可用 |
| `get_my_courses` | 查询本人已加入普通课程及公开课；普通课程返回进度、任务数、学习时长、加入时间、最近学习时间、有效期和证书状态 | `status`：`all/not_started/studying/completed/expired`，默认 `all`；`count`：默认 10，范围 1～20 | 登录后 |
| `get_recommend_courses` | 按本人已学和收藏分类推荐尚未加入的已上架课程，数量不足用热门课程补足 | `count`：默认 6，范围 1～10 | 登录后 |
| `get_recent_course_orders` | 查询本人课程订单、金额、状态和课程条目；不返回支付流水 | `status`：`all/pending/paid/cancelled/refunded`，默认 `all`；`limit`：默认 10，范围 1～20 | 登录后 |
| `get_my_coupons` | 查询本人优惠券名称、折扣、门槛、状态、有效期 | `status`：`all/available/unused/used/expired`，默认 `all`；`limit`：默认 10，范围 1～20 | 登录后 |

补充说明：

- 公开课返回的 `progress` 为 `null`，不能当作普通课程的精确百分比进度。
- `search_news` 不传日期时查询最新候选；只传一个日期边界时，另一边按最近 30 天开始日或今天补齐。“今天”的查询应将两端都设为当天。
- `get_my_coupons` 底层按当前用户查询 `UserCoupon`，当前没有额外的“仅课程券”筛选参数。
- 工具全部只读。课程助手不能支付、退款、取消订单、修改资料、领取优惠券，也不具备商城订单、商品、消费统计、账户余额或站内项目查询权限。

### 3.2 对话参数与流式返回

```json
{
  "message": "看看我正在学习的课程，再推荐两门机器人课程",
  "conversation_id": "course-assistant-demo-001"
}
```

- `message` 必填，最多 4000 字；兼容旧字段 `userInput`。
- `conversation_id` 可选，最多 64 字符，仅字母、数字、下划线和连字符；兼容 `sessionId`、`session_id`。不传则生成 UUID，后续沿用返回的 ID。
- 固定返回 SSE，无需传 `stream`。事件包括 `start`、`status`、`content`、`done`、`error`。
- `done` 返回 `conversation_id`、`model`、`provider`、`points_cost: 0`、`authenticated`、`tools_used`、`course_cards`、`news_cards`、`usage`。
- 运行中的错误通过 `type: error` 事件报告，客户端不能只看 HTTP 200 判断成功；建立 SSE 前的参数、开关等错误返回普通 JSON。底层部分认证响应还需检查业务码。
- `BUSINESS_AGENT_PUBLIC_ENABLED` 控制入口。专用限流默认登录用户每分钟 60 次、游客按 IP 每分钟 30 次，可通过配置调整；还受公共 API 中间件限制。
- 每轮工具调用数默认最多 4 次，配置允许范围 1～8。登录历史保存到 AI 会话表，来源 `business_agent`；游客上下文默认缓存 120 分钟。

### 3.3 外部 Tool HTTP API 与内置课程助手的区别

外部独立智能体可使用下列受保护接口，全部要求当前用户 JWT 或 `ts_` 凭证，底层查询不调用大模型，配置 `throttle:30,1`：

```http
GET /miniapp/ai/agent/tools
POST /miniapp/ai/agent/tools/{工具名}
```

GET 返回 OpenAI 兼容的 `data.tools` 和 `data.endpoints`。现有 POST 路由共 11 个：

| HTTP 工具名 | 能力 | 内置课程助手是否授权 |
| --- | --- | --- |
| `search_courses` | 公开课程查询 | 是 |
| `get_my_courses` | 本人课程与学习进度 | 是，需登录 |
| `get_recommend_courses` | 本人课程推荐 | 是，需登录 |
| `get_recent_course_orders` | 本人课程订单 | 是，需登录 |
| `get_my_coupons` | 本人优惠券 | 是，需登录 |
| `get_recent_orders` | 本人商城订单；`startTime/endTime` 可选，默认最近 30 天，`limit` 默认 10、最多 20 | 否 |
| `get_consume_stat` | 本人已支付且未退款的商城消费统计；必填 `startTime/endTime` | 否 |
| `get_recommend_goods` | 本人个性化商城商品推荐；`count` 默认 5、最多 10 | 否 |
| `get_my_favorites` | 本人课程、商品收藏；`type: all/course/product`，`limit` 默认 10、最多 20 | 否 |
| `get_my_account_overview` | 本人余额、天树点及订单、课程、收藏、优惠券数量；参数为空对象 | 否 |
| `search_site_resources` | 官网页面、已发布项目、成果、课程、资讯；必填 `query`，`limit` 默认 6、最多 10 | 否 |

**当前有一处接口映射缺口：**工具服务 Schema 包含 `search_news`，内置课程助手可直接在后端执行它，但 `BusinessAgentToolController` 和路由没有对应的 `POST /miniapp/ai/agent/tools/search_news`。因此 Schema 有 12 个工具，HTTP 映射只有 11 个；外部独立智能体不能按同名 URL 直接调用资讯工具。

外部 Tool 成功返回 `{"ok":true,"data":{...}}`；参数错误返回 422，业务查询异常返回 503。不要把更广的外部 Tool 清单当作内置课程助手的权限清单。

## 4. 补充：课程任务页 AI 学习助手

此功能与“天小树”有不同调用链：前端依次准备资料、读取资料、整理参考内容、生成答案、保存结果。当前没有供模型自由选择的课程、订单、星球等业务工具。

### 4.1 前端实际调用的基础接口

| 方法 | 路径 | 用途与参数 |
| --- | --- | --- |
| GET | `/miniapp/ai/chat/models` | 查询当前账号模型权限；前端筛选 `can_use`、对话类别和图片能力，保留完整逻辑模型 ID |
| POST | `/miniapp/ai/chat` | 资料解析与问答、总结、导图、测验、代码生成；主要传 `model`、`messages`、`stream: true`、`load_history: false`、`source: course_task`、`context: {type, course_id, task_id}` |
| GET | `/miniapp/course/detail/{courseId}/manage/plan/task/{taskId}/download` | 单文件任务获取有权限的签名下载地址，返回 `download_url`；沿用课程学习访问权限，可选 `expires`，默认 3600 秒 |
| POST | `/miniapp/pbtokenScope` | 上传聊天附件前申请存储上传凭证；前端提交 `key`，随后直传七牛 `https://up.qbox.me/` |

资料处理范围：图片、PDF、文本和常见代码文件。PDF、文本先由浏览器下载读取；图像和整理后的正文再送模型，仍依赖有效下载地址、存储 CORS 和账号获授权的多模态能力。上传附件最多 4 个，截图单张最多 5 MB，其他上传文件单个最多 20 MB。

**下载地址接口有业务副作用：**已报名学员获取 `download` 类型任务的下载地址时，若完成条件为 `click_download` 或 `download_click`，后端会尝试完成该任务。它不能简单归类为无副作用的 GET 查询。

### 4.2 会话和结果保存接口

统一前缀：`/miniapp/task-ai`。全部要求登录，按当前账号隔离；这里的会话 `{id}` 是数字 ID，与源宝 UUID 不同。

| 方法 | 相对路径 | 用途与主要参数 |
| --- | --- | --- |
| GET | `/conversations` | 会话列表；必填 `course_id`、`task_id` |
| POST | `/conversations` | 创建会话；必填 `course_id`、`task_id`，可选 `title`（最多 128 字） |
| GET | `/conversations/{id}` | 本人会话详情 |
| PUT | `/conversations/{id}` | 修改本人会话标题；必填 `title`，最多 128 字 |
| DELETE | `/conversations/{id}` | 删除本人会话 |
| GET | `/conversations/{id}/messages` | 消息列表；`page`、`page_size` |
| POST | `/conversations/{id}/messages` | 保存单条或批量 `messages`；必填 `role: user/assistant`，可选 `content`、`attachments`、`thinking`、`thinking_duration_seconds`、`model` |
| POST | `/conversations/{id}/chat` | 已存在的独立流式聊天接口；必填 `model`、`content`，可选 `attachments`、`context`；当前课程聊天组件实际采用统一 `/miniapp/ai/chat` 生成后再保存消息 |

总结、思维导图、测验、代码、笔记均有相同的 5 类 CRUD 接口：

| 资源 | 列表及新建路径 | 详情、修改、删除路径 |
| --- | --- | --- |
| 总结 | `/summaries` | `/summaries/{id}` |
| 思维导图 | `/mindmaps` | `/mindmaps/{id}` |
| 测验 | `/quizzes` | `/quizzes/{id}` |
| 代码 | `/codes` | `/codes/{id}` |
| 笔记 | `/notes` | `/notes/{id}` |

- 列表：GET，必填 `course_id`、`task_id`。
- 新建：POST，必填 `course_id`、`task_id`、字符串 `content`，可选 `title`（最多 128 字）。
- 详情：GET `/{id}`；修改：PUT `/{id}`，支持 `title`、`content`；删除：DELETE `/{id}`。
- 当前通用结果保存控制器不写入前端传来的 `model`，不要把该字段当成已持久化的模型记录。

这类接口保存的是本人学习数据，不是修改课程原文、资讯、星球文章或书刊论文的管理接口。

## 5. 核对依据

- [小程序路由](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/routes/miniapp.php)：对话、Tool HTTP、源宝和任务 AI 路由。
- [源宝控制器](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Http/Controllers/API/MiniApp/YuanbaoController.php)、[源宝对话服务](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Services/YuanbaoDialogueService.php)、[源宝内容服务](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Services/YuanbaoContentService.php)：模型工具、8 类内容、会话和读取范围。
- [课程助手服务](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Services/BusinessAgent/BusinessAgentService.php)、[工具服务](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Services/BusinessAgent/BusinessAgentToolService.php)、[外部 Tool 控制器](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Http/Controllers/API/BusinessAgentToolController.php)：内置白名单、工具参数与 HTTP 映射。
- [任务 AI 控制器](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Http/Controllers/API/TaskAiController.php)、[课程任务下载控制器](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/app/Http/Controllers/API/CourseManageController.php)：保存契约及任务完成副作用。
- [课程助手前端](/Users/shengli/Documents/mulu/Project/gitlab/tstj_edu_web/src/views/BusinessAgentDemo.vue)、[学习助手工作流](/Users/shengli/Documents/mulu/Project/gitlab/tstj_edu_web/src/composables/useTaskAiWorkflow.js)、[学习助手聊天组件](/Users/shengli/Documents/mulu/Project/gitlab/tstj_edu_web/src/components/task/TaskAiChat.vue)：实际调用链。

已有 `BUSINESS_AGENT_TOOL_API.md` 中仍有“内置助手不调用资讯”及商城消费 SSE 示例等旧描述；本清单以当前源码中的 6 个课程助手工具白名单为准。
