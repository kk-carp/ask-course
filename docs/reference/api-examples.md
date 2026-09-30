# 接口操作示例

[文档导航](../README.md)

命令在项目根目录执行，要求服务已启动。`p0_admin` 密码来自 `DEMO_PASSWORD`，示例使用本地默认值。联系方式示例需替换为真实值。完整契约见服务的 `/docs` 和 [schemas.py](../../backend/schemas.py)。

## 灌课程知识库


P0 只服务课程咨询，因此只用一个空间：`courses`。

内部试用前先按 [L0 内部运营](../operations/L0_OPERATIONS.md) 完成课程四板块、
真实售前映射和金标评测。正式环境应设置
`COURSE_CONTENT_VALIDATION_MODE=strict`，不完整或含占位内容的课程文档会被拒绝入库。

```powershell
# 登录（内部账号，由 seed 幂等写入）
curl.exe -c cookies.txt -b cookies.txt -X POST "http://127.0.0.1:8000/login" `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"p0_admin\",\"password\":\"demo1234\"}"

# 上传课程内容（Markdown / TXT / PDF / DOCX / PPTX）
curl.exe -c cookies.txt -b cookies.txt -X POST "http://127.0.0.1:8000/documents" `
  -F "space=courses" -F "course_id=43" -F "file=@课程详情.md"
```

> **注意**：官网接口有标题、副标题和简介，但不足以覆盖课程完整内容。首批 42 的详情正文是图片，43、99 的详情正文为空。
> 图片不能直接作为知识库正文，仍需文本化并经运营核对。
> 推荐优先做 4 个板块：**适用人群、课程目录、学习安排、结业证书**——
> 这是推荐规则唯一依赖文本的部分。详见[需求分析报告](../product/售前Agent助手_需求分析报告.html) R28。

## 提问（登录或游客均可）

```powershell
# 游客也可以直接问（P0 改造点：FDE 原本强制登录）
curl.exe -c cookies.txt -b cookies.txt -X POST "http://127.0.0.1:8000/ask" `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"这门课需要什么基础？\",\"course_id\":\"43\",\"channel\":\"internal_tool\"}"
```

命中时返回 `hit=true` + `sources`（来源只来自召回记录，模型无法篡改）。
游客响应还会返回 `conversation_id`；后续提问带回该 ID 可延续同一访客会话。`/ask/stream` 对游客保留 SSE 的 `meta`、`final`、`done` 事件，但当前一次返回完整答案。

内容问答未命中且没有相关课程候选时，尝试补充 `owner`。无有效联系方式时返回 `configured=false`；有相关课程候选时先引导选课。下面仅展示配置有效联系人后的部分响应字段：

```json
{
  "answer": "这个问题我暂时没有可靠依据回答，已为你转接对应课程顾问。",
  "hit": false,
  "sources": [],
  "owner": {
    "configured": true,
    "topic_key": "43",
    "topic_name": "经运营核实的课程名称",
    "name": "课程顾问",
    "contact": "https://work.weixin.qq.com/ca/your-real-contact"
  }
}
```

**这就是整个 P0 的核心动作**：把"扫码"从第一步变成最后一步。

## 维护课程 → 售前映射

映射复用 FDE 的 `topic_owners` 表，接口不变：

| 字段 | P0 语义 |
| --- | --- |
| `topic_key` | 课程 ID（与官网 `/course/:courseId` 对齐） |
| `topic_name` | 课程名称 |
| `keywords` | 课程别名，用于问题文本兜底匹配 |
| `name` | 售前人员姓名 |
| `contact` | 售前企微「联系我」活码链接 |

```powershell
# 查看
curl.exe -b cookies.txt "http://127.0.0.1:8000/topic_owners"
# 新增/修改（按 topic_key upsert）
curl.exe -b cookies.txt -X PUT "http://127.0.0.1:8000/topic_owners" `
  -H "Content-Type: application/json" `
  -d "{\"topic_key\":\"43\",\"topic_name\":\"经运营核实的课程名称\",\"keywords\":\"按运营资料填写\",\"name\":\"经核实的顾问\",\"contact\":\"https://work.weixin.qq.com/ca/replace-with-real-contact\"}"
```

示例联系方式只是格式说明，必须替换为可访问的真实链接；接口会拒绝占位值。启动不再生成占位映射。

## 官网问诊与灰度

官网脚本与发布步骤见[试运行准出](../operations/PILOT_LAUNCH.md)。只有白名单课程、通过课程资料门禁且命中灰度的访客能调用以下接口：

- `GET /widget/config?course_id=43`：返回是否显示入口，并签发受保护的访客 Cookie。
- `POST /consultations`：`{"course_id":"43"}`，可选 `known_profile`（已知字段可跳过）；返回 `id`、当前问题和 `next_field`。
- `POST /consultations/{id}/answers`：如 `{"field":"basis","value":"basic"}`，依次完成目标、基础、硬件和每周时间；结果为课程卡片或人工承接摘要。
- `GET /consultations/{id}`：仅原访客可恢复 24 小时内的问诊。
- `POST /purchase/{course_id}`：点击时重新核实课程在售状态，返回官网购买页 URL 并记录事件。
- 管理员 `GET/PUT /pilot/control`：比例只允许 `0`、`5`、`25`、`100`；设置 `0` 立即关闭入口。
