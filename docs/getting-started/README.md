# 本地启动

[文档导航](../README.md) · [开发指南](../development/README.md)

前提：Python 3.11、Docker、Node.js 22.12+ 或 24。以下命令从项目根目录执行。已有数据库时跳过容器创建，核对 `.env` 的 `DATABASE_URL`；升级已有库前先备份，不替换现有配置。

```powershell
# 依赖
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend

# 配置：只在不存在时复制，随后填写 CHAT_API_KEY 和随机 SECRET_KEY
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# 本地示例数据库，需 pgvector；已有同名容器时不重复创建
# 若本机 5432 已占用，改映射端口并同步 DATABASE_URL
docker run -d --name p0-pg -p 5432:5432 `
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=arborseek_p0 pgvector/pgvector:pg16

# 确认数据库就绪后执行迁移，当前 head 为 0004
python -m alembic upgrade head
python -m alembic current

# 启动
python -m uvicorn backend.main:app --reload --reload-dir backend
```

首次启动加载 BGE-M3，可能下载模型。`GET /health` 返回 API、数据库和向量模型状态；`GET /ready` 在数据库可连且模型已加载时返回 200，否则为 503。健康检查不调用对话模型，不能证明模型网关可用。

## 页面入口

- `http://127.0.0.1:8000/`：内部问答预览，内存历史，刷新即清空；`/qa` 和 `/login` 的 GET 保留兼容预览。
- `http://127.0.0.1:8000/consult`：独立游客页面，真实签名 Cookie 与服务端历史，仍受审核、灰度和联系人门禁限制。默认未通过条件时无咨询入口，不为演示放宽门禁。
- `http://127.0.0.1:8000/admin`：内部登录、资料和联系人管理；内部账号不代表官网客户身份。
- `http://127.0.0.1:8000/docs`：本项目接口文档，与官网提供的 API 资料分开。

缺少前端构建时页面返回构建提示。修改源码后重新构建；Docker 镜像自动构建前端。官网当前未加载助手脚本，独立页面不会自动识别官网账号，保留 `WEBSITE_IDENTITY_ENABLED=false`。

## 无外部依赖自检

```powershell
python scripts/smoke_kernel.py
```

自检验证检索内核及售前规则的基础行为，不需要数据库、模型或 API Key，不代替真实课程问答和生产验收。

下一步：[内部运营](../operations/L0_OPERATIONS.md) · [接口示例](../reference/api-examples.md)。默认数据库口令和演示账号仅用于本地；生产部署见[部署手册](../operations/DEPLOYMENT.md)。
