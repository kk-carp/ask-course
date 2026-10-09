# 官网售前 Agent 试运行准出与回滚

[文档导航](../README.md) · [当前实现](../architecture/current-system.md)

首批试运行课程页 ID 为 **42、43、99**。官网公开列表中的 26 门课已登记在 [`data/approved_courses.json`](../../data/approved_courses.json)：42、43、99 为 `recommendable`，其余为 `draft`。前三门可依据官网现有介绍进入选课推荐，但基础、硬件、投入时间及购买页尚未完成运营审核，因此推荐结果不附付款入口。当前 `PILOT_PERCENT=0`；官网组件仍按上线门禁关闭。

## 1. 运营交付

官网详情接口的文字快照保存在 `data/official_course_drafts/{id}.json`，审核清单逐门链接快照。可运行 `python scripts/collect_official_course_drafts.py <课程ID>` 更新单门快照；更新不会自动通过审核或写入知识库。91、93、94、95 有较长详情文字，其余多为图片或简短介绍；所有事实仍需按官网与运营资料复核。

1. `recommendable` 只允许展示与目标方向相关的官网课程名称和简介，不能声称已核实个体适配或提供付款入口。逐门核对官网在售状态及购买页，在审核清单填写适合人群、基础要求、学习目标、目标关键词、是否需要硬件、最低基础与每周最低投入。不能从课程标题猜测这些值。确认课程事实、课程正文、专属售前联系方式后，将 `review_checks` 的五项逐一改为 `true`，填写审核人与 ISO 日期，最后将 `status` 改为 `approved`。只有字段完整、五项审核通过且仍出现在官网公开列表的条目才可按适配条件筛选并生成购买入口。`purchase_url` 必须是已打开核验的对应 `https://www.arborseek.com/course/{id}`；`source_url` 仅是资料来源，不能代替购买页核验。价格不由审核清单人工维护，当前实现读取官网可核实价格与公开优惠，缓存最多一分钟；接口失败且缓存过期时明确说明暂不可读取，不由资料或模型猜价。最终金额以官网下单页面为准。
2. 将每门课四个最低内容板块（适合人群、目录、学习安排、结业证书）整理为可检索正文；在 `data/course_catalog.json` 登记正文路径、负责人、有效日期和 `active` 状态，并通过管理员 `POST /documents` 上传到课程知识库。上传表单必须带对应的数字 `course_id`，检索时按课程隔离；历史未标课程 ID 的文档不能回答课程详情页的问题。`COURSE_CONTENT_VALIDATION_MODE=strict`。
3. 用管理员 `PUT /topic_owners` 配置每门课真实售前联系人或二维码；设置真实备用联系方式 `HANDOFF_FALLBACK_CONTACT`。逐一打开官网详情中的售前二维码和备用链接核验。旧占位行在服务启动时清理，不会重新生成。
4. 依据真实内容将 `data/eval/pilot_gold.example.jsonl` 扩展为 `data/eval/pilot_gold.jsonl`，每门课至少覆盖适合人群、目录、安排、证书四类有来源回答，另外加入无匹配、错误课程 ID、购买与人工承接案例。不可直接复用旧课程别名的评测数据。

## 2. 官网接入

官网将 Agent 服务反向代理到**同源** `/agent/`，代理需剥离前缀；指定的 `/course/42`、`/course/43`、`/course/99` 页面在 `</body>` 前加入：

```html
<script defer src="/agent/widget.js" data-course-id="42"></script>
```

每页将 `data-course-id` 改为对应 ID。脚本使用 Shadow DOM 隔离样式，所有请求走同源 `/agent/`，不需要跨站 Cookie 或 CORS。官网应允许脚本、API 和课程二维码的 CSP 来源，并验证反向代理传递 Host、Origin、Cookie 与 HTTPS。未列入白名单、未命中稳定访客桶，或缺少审核课程、可检索正文、课程专属联系人及备用联系方式时不显示入口。先在预发布环境完成桌面与移动端测试，再发布脚本。

## 3. 自动检查与人工验收

```powershell
python scripts/check_pilot_readiness.py
python scripts/evaluate_l0.py --dataset data/eval/pilot_gold.jsonl --base-url https://预发布同源地址/agent
python scripts/evaluate_dialogue.py --base-url https://预发布同源地址/agent
python -m pytest -q
```

第一条检查审核清单、官网在售交集、课程正文、真实售前联系人、购买页和二维码可访问性；`--skip-http` 仅用于本地排查，不能作为上线准出。若尚未收到运营资料，检查应失败。第二条要求金标案例全数通过，重点复核事实依据与课程归属；第三条验证画像陈述和后续补充能否延续同一匿名会话。还要人工验证：方向明确时首轮展示课程、短回答承接上一问、课程事实有依据、完整问诊、基础/硬件/时间硬筛选、无匹配时明确告知、找顾问时归属正确课程、二维码加载失败后的备用联系入口、购买按钮到达正确官网页面、网络错误、手机与桌面布局。付款完成和订单对账不在本轮验收范围。

## 4. 灰度与回滚

管理员登录后用 `PUT /pilot/control` 提交 `{"percent":5}`，验收后依次改为 `25`、`100`。`GET /pilot/control` 查看当前值；`PUT /pilot/control` 提交 `{"percent":0}` 会立即阻断新入口、问诊和购买跳转，作用于所有共享数据库的实例。对购买页错误、售前人员错误或严重事实错误立即设置 0，排查修复后重新从 5% 开始。官网团队也可移除页面脚本作为第二道回滚。设置 0 时现有访客的问诊会暂停，恢复后 24 小时内可按原访客凭证继续。

管理员 `/metrics` 包含近 30 天的入口展示、入口打开、提问（含问诊回答）、推荐展示、购买页点击、人工承接和错误事件计数；`/metrics/funnel` 按课程、日期列出近 7 天事件，用于核对错误率和转化路径。事件不存问答正文；问诊进度保留 24 小时，事件保留 30 天。原问答指标与限流仍为进程内，试运行阶段应部署单副本；若扩容，先迁移到共享限流和统一指标。每个比例阶段至少观察 7 天，并人工检查所有严重案例为零，再继续扩大。
