# 本项目接口操作示例

[文档导航](../README.md) · [游客历史协议](../integration/游客接入.md)

以下 PowerShell 7 示例要求助手服务已启动；命令只演示本项目接口，不调用官网发布、订单或支付 API。真实密码不写入文档或命令历史。完整请求模型见服务 `/docs`、[schemas.py](../../backend/schemas.py)和路由中的请求模型。

## 内部登录、上传与问答

先按[内部运营](../operations/L0_OPERATIONS.md)准备四板块课程正文和真实联系人。`p0_admin` 的初始密码来自 `DEMO_PASSWORD`；已有账号不会因修改配置自动重置密码。

```powershell
$taskApiBase = 'http://127.0.0.1:8000'
$taskAdminPassword = Read-Host '内部管理员密码' -MaskInput
$taskLoginBody = @{username='p0_admin'; password=$taskAdminPassword} | ConvertTo-Json
Invoke-RestMethod -Uri "$taskApiBase/login" -Method Post `
  -ContentType 'application/json' -Body $taskLoginBody -SessionVariable taskAdminSession
Remove-Variable taskAdminPassword, taskLoginBody

# Markdown / TXT / PDF / DOCX / PPTX；数字课程 ID 与官网一致
$taskUpload = @{space='courses'; course_id='43'; file=(Get-Item -LiteralPath '课程详情.md')}
Invoke-RestMethod -Uri "$taskApiBase/documents" -Method Post `
  -WebSession $taskAdminSession -Form $taskUpload

$taskAskBody = @{question='这门课需要什么基础？'; course_id='43'; channel='internal_tool'} | ConvertTo-Json
Invoke-RestMethod -Uri "$taskApiBase/ask" -Method Post -WebSession $taskAdminSession `
  -ContentType 'application/json' -Body $taskAskBody
```

`internal_tool` 是内部试用通道，不能用其结果证明站点门禁已经通过。命中来源由召回记录提供；未知或冲突项不能猜测。`hit=true` 对多问题仅代表至少一项有依据。

`/ask/stream` 使用 SSE：`progress` 为处理进度，`part` 为多问题逐项结果，`meta` 为元信息，`final` 为最终回答，`error` 为流内错误，`done` 为结束。并非 token 逐字流；不能只根据 HTTP 200 或收到 `done` 判断回答成功。

## 维护课程联系人

`topic_key` 为课程 ID，`topic_name` 为名称，`keywords` 为别名，`name` 和 `contact` 为真实顾问及 HTTPS 联系入口。只使用经业务核实的值，接口拒绝占位联系方式。

```powershell
Invoke-RestMethod -Uri "$taskApiBase/topic_owners" -WebSession $taskAdminSession

# 将以下说明值全部替换为已核实内容后再执行
$taskOwnerBody = @{
  topic_key='43'; topic_name='经核实的课程名称'; keywords='经核实的别名'
  name='经核实的顾问'; contact='替换为真实 HTTPS 联系入口'
} | ConvertTo-Json
Invoke-RestMethod -Uri "$taskApiBase/topic_owners" -Method Put -WebSession $taskAdminSession `
  -ContentType 'application/json' -Body $taskOwnerBody
```

官网课程售前码优先，配置映射和兜底作为补充。`owner.configured=false` 表示没有有效出口，不能显示“人工已接管”。启动只初始化课程空间和管理员，不生成占位顾问。

## 游客与官网客户接口

独立游客页面为 `/consult`；官网后续可接入时使用 `/agent/widget.js`，见[游客接入](../integration/游客接入.md)。站点问答和历史均需要原签名游客 Cookie 或已验证客户主体，不接受前端 userId 授权。

- `GET /widget/config?mode=site`：真实站点门禁、游客 Cookie 和身份分区。
- `/widget/conversations`：新建、分页、消息、改名、删除；完整示例及幂等规则见游客协议。
- `POST /ask/stream`：站点请求使用 `channel=site_widget`，携带咨询 ID 和本轮 UUID。
- `POST /widget/conversations/{id}/associate`：需要可信客户身份和原游客 Cookie；真实客户凭据尚未接入，默认校验关闭，不提供模拟登录示例。
- `/consultations` 及 `/consultations/{id}/answers`：保留结构化问诊接口，按当前所有者授权；公开组件主要使用统一问答流程。
- `POST /purchase/{course_id}`：重新校验课程资格与在售状态，返回官网购买页，不执行支付。
- 管理员 `GET/PUT /pilot/control`：只允许 `0`、`5`、`25`、`100`，`0` 关闭入口；开放前须通过[准出检查](../operations/PILOT_LAUNCH.md)。

生产带 Cookie 写请求还会检查来源；命令行需要按部署方式发送与服务 Host 一致的 Origin/Referer。不要为测试关闭来源保护或把内部管理员 Cookie 当成官网客户凭证。
