# 开发指南

[文档导航](../README.md) · [当前实现](../architecture/current-system.md)

## 代码入口

- [main.py](../../backend/main.py)：启动、模型加载、中间件与路由挂载。
- `backend/routes/`：HTTP 请求、身份解析及响应适配。
- `backend/services/`：问答、意图分流、入库、课程目录和转人工流程。
- `backend/domain/`：课程内容校验、游客权限等领域规则。
- `backend/infra/`：解析、分块、向量检索、重排和模型调用。
- [schemas.py](../../backend/schemas.py)、[models.py](../../backend/models.py)、[config.py](../../backend/config.py)：接口契约、数据库模型及配置。
- [frontend/src/Widget.vue](../../frontend/src/Widget.vue)：Vue 3 单文件组件，包含右下角入口、对话、来源、课程推荐及转人工。
- [frontend/src/main.js](../../frontend/src/main.js)：组件挂载与官网配置门禁，使用 Shadow DOM 隔离样式。
- [frontend/src/api.js](../../frontend/src/api.js)：接口调用、SSE 解析和链接校验。
- [frontend/index.html](../../frontend/index.html)：仅展示咨询入口的开发预览。
- [frontend/admin.html](../../frontend/admin.html)：独立内部管理页，沿用原生 JavaScript，后端地址为 `/admin`，不嵌入官网。

项目只保留售前主链路及课程资料管理，路由挂载范围以 `backend/main.py` 为准。

## 本地检查

前端使用 Vue 3 + Vite + Ant Design Vue 4.2.6，与官网公开构建产物中的组件库版本一致（2026-10-08 核验）。按钮、输入框、历史浮层、操作菜单及重命名弹窗使用组件库；通过 StyleProvider 将组件样式注入 Shadow DOM，弹层同样挂载在组件内部。

历史展示由用户问题提炼的主题短句，支持搜索、重命名和删除；删除当前会话后回到新会话。`data-mode="site"` 模式使用 `/widget/conversations` 持久化本人历史，游客默认保留 24 小时；独立 `/consult` 复用该模式。内部 `data-preview="true"` 演示仍使用页面内存历史，刷新即清空。客户所有权、原子关联和默认关闭的验证适配器已实现，真实官网账号流程尚未接通，不调用内部账号历史接口代替。

Node.js 22.12+（或 24）环境中执行：

```powershell
cd frontend
npm ci
npm run build
npm test
```

FastAPI 托管 `frontend/dist`，每次修改源码后重新构建。Docker 镜像自动进行前端构建。开发热更新可运行 `npm run dev`，默认通过 Vite 将 API 转发到 `http://127.0.0.1:8000`。构建后的 `dist/widget.js` 为包含 Vue 运行时的独立 IIFE，官网无需安装 Vue，也无需改造现有框架。

启动后打开首页，点击右下角“问问探界”查看咨询面板。可验证快捷提问、Enter 发送、Shift + Enter 换行、收起再展开保留当前消息和草稿，以及顶部“新会话”重置对话；左侧“对话历史”可切换咨询。内部预览刷新后清空，正式站点模式按服务端归属与有效期恢复。手机宽度下展开为全屏，收起后恢复页面滚动；回答依据默认折叠。

首页脚本的 `data-preview="true"` 仅用于本项目演示路由，沿用内部演示的 `internal_tool` 问答通道。官网课程页使用课程 ID 配置和服务端灰度门禁；不能用内部预览绕过正式站点门禁。游客协议和迁移见[游客接入](../integration/游客接入.md)，客户对接限制见[身份归属](../integration/官网客户身份与历史归属.md)。

先完成[本地启动](../getting-started/README.md)的依赖安装，在项目根目录使用虚拟环境执行：

```powershell
python scripts/smoke_kernel.py
python -m pytest tests
```

`pytest.ini` 将测试临时数据统一放在 `.pytest_cache/tmp`，pytest 每次运行会重建该目录；不要再为每轮验证创建根目录 `.pytest-tmp-*`。不要同时运行使用同一临时目录的多个测试进程。`.pytest_cache` 与 `.ruff_cache` 是可重新生成的缓存，测试结束后可清理；它们不属于项目源码。

### PostgreSQL 集成检查

CI 的 `postgres-integration` 独立使用 `pgvector/pgvector:pg16`。本地运行时，将 `TEST_POSTGRES_URL` 设置为专用测试库的 SQLAlchemy 连接 URL（`postgresql+psycopg://...`），再执行：

```powershell
python -m pytest -q tests/integration
```

未设置该变量时仅跳过集成测试，现有单元测试照常运行。设置后数据库不可用会失败，不静默跳过。测试拒绝 public 中已有表的数据库，在专用库逐例创建和清理随机 schema；账号需要创建 schema 和安装 vector 扩展的权限。向量和模型由受控数据提供，无需官网凭证或模型额度。此检查证明数据库行为，不代表官网联调、实际模型质量或生产恢复验收。

依赖版本只在 `requirements-ci.txt` 维护一份；`requirements.txt` 引用它并增加本地模型依赖。修改引用关系时同步 Docker 的复制清单。

首次咨询和多问题性能回归：`python -m pytest tests/test_response_latency.py`。
用 `python scripts/benchmark_response_latency.py` 对比串行参考路径与最多三项并行的调度耗时；基准模拟每项 120 ms 上游等待，不连接数据库、官网或模型，不代表线上绝对耗时。真实请求按管理员 `/metrics` 的 `latency_ms` 和访问日志的 `duration_ms` 核验。

内核自检不需要数据库、模型或 API Key。资料门禁与联网金标评测见 [L0 手册](../operations/L0_OPERATIONS.md)，单元测试通过不能代替业务验收。

## 同步维护

接口变更同步接口契约和[接口示例](../reference/api-examples.md)；规则或路由变更同步[当前实现](../architecture/current-system.md)；内容准入规则变更同步 [L0 手册](../operations/L0_OPERATIONS.md)及[课程模板](../templates/课程内容模板.md)。

旧 FDE 批量搬运脚本已删除，避免重新引入学院专用模块或覆盖售前改造。

清理说明与已有数据库兼容策略见[售前代码边界](../architecture/presales-scope.md)。
