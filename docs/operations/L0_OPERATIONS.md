# L0 内部可运营手册

[文档导航](../README.md) · [接口操作示例](../reference/api-examples.md)

本手册定义验收目标，不代表已经通过验收。命令从项目根目录执行。

L0 的目标不是对外上线，而是让售前用真实课程内容完成内部试用，并证明：

1. 常规问题能基于课程正文回答；
2. 没有依据时不调用模型硬答；
3. 未命中能交给真实售前；
4. 同一套金标集可以重复评测。

## 1. 准备课程内容

每门在售课程至少包含以下四个二级标题：

- `## 适用人群`
- `## 课程目录`
- `## 学习安排`
- `## 结业证书`

正文不能包含 `TODO`、`TBD`、`待补`、`待确认`、`占位` 等标记，有效文本不能少于 120 字。参考 [课程内容模板](../templates/课程内容模板.md)。

建立 `data/course_catalog.json`，格式参照 `data/course_catalog.example.json`。`course_id` 必须与官网课程详情页 ID 一致，`content_file` 指向评审通过的 Markdown 正文。

本地迁移历史语料可暂用：

```dotenv
COURSE_CONTENT_VALIDATION_MODE=warn
```

准备内部验收或生产环境时必须改为：

```dotenv
COURSE_CONTENT_VALIDATION_MODE=strict
```

严格模式下，四板块不全、文本过短或仍有占位内容的课程文档会入库失败，并返回可处理的原因。

## 2. 准备真实售前映射

复制 `data/course_owners.example.json` 为不入库的真实配置文件，替换全部示例值。联系方式必须是可以实际访问的 HTTPS 链接；`placeholder://`、`example.com` 和 `replace-with-*` 会被拒绝。

先离线校验：

```powershell
python scripts/import_course_owners.py path\to\course_owners.json --check
```

数据库启动后导入：

```powershell
python scripts/import_course_owners.py path\to\course_owners.json --apply
```

同时在 `.env` 配置真实兜底联系人：

```dotenv
HANDOFF_FALLBACK_NAME=通用课程顾问
HANDOFF_FALLBACK_CONTACT=https://实际可访问的企微活码地址
```

服务不会再把占位联系方式当作已配置出口返回给用户。

## 3. 执行 L0 资料门禁

```powershell
python scripts/check_l0_readiness.py `
  --catalog data\course_catalog.json `
  --owners path\to\course_owners.json
```

门禁逐门检查：

- 在售课程内容文件存在；
- 四个最低板块齐全；
- 没有占位文本；
- 内容负责人和生效日期已登记；
- 每门在售课程都有真实售前映射；
- 没有只配置售前、却不在当前在售目录中的异常课程。

任何失败项都必须处理后再入库。该门禁不需要数据库、模型或 API Key。

## 4. 入库与内部试用

按[本地启动](../getting-started/README.md)启动数据库和服务，使用内部账号上传通过门禁的课程正文。上传后检查 `/documents`，确保状态为 `ready` 且没有重复文档。

内部试用统一使用 `channel=internal_tool`，覆盖：

- 适用人群、先修基础；
- 目录和学习安排；
- 证书和结业条件；
- 价格让利、退款、发票等不得机器承诺的问题；
- 课程范围之外的问题；
- 明确指定课程和没有指定课程两种路由。

## 5. 执行金标评测

服务启动且真实内容、映射已经入库后运行：

```powershell
python scripts/evaluate_l0.py `
  --dataset data\eval\pilot_gold.jsonl `
  --base-url http://127.0.0.1:8000
```

旧别名金标集已移除。根据 `data/eval/pilot_gold.example.jsonl`，为 42、43、99 中每门实际试运行课程用真实资料建立案例。评测检查命中状态、来源、未命中是否调用模型、售前路由和禁用承诺。新增课程时同步新增对应的四板块问答、拒答和转人工用例。

L0 准出要求：

- 金标集全部通过；
- 价格、退款、证书、开课时间等严重错误为 0；
- 未命中不调用模型，且一定存在真实承接出口；
- 售前完成一轮试用并确认内容口径和维护责任人。

## 当前业务数据缺口

仓库中的 `backend/seed/course_owners.py` 仍是演示种子，现有课程正文也只是少量样例。代码已经会识别并拒绝这些占位出口，但无法代替业务运营补齐真实课程目录、正文、内容负责人和企微活码。
