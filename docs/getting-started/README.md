# 本地启动

[文档导航](../README.md)

前提：已安装 Python 和 Docker。以下命令从项目根目录执行；已有数据库时跳过容器创建，并调整 `.env` 中的 `DATABASE_URL`。


```powershell
# 在项目根目录执行

# 1. 依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env：填 CHAT_API_KEY，改掉 SECRET_KEY

# 3. 数据库（需 pgvector 扩展）
docker run -d --name p0-pg -p 5432:5432 `
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=arborseek_p0 pgvector/pgvector:pg16

# 4. 数据库迁移（已有库先备份；独立发布步骤）
python -m alembic upgrade head

# 5. 启动
uvicorn backend.main:app --reload --reload-dir backend
```

启动时日志会打印三步进度。`GET http://127.0.0.1:8000/health` 返回
`{"api":true,"database":true,"embedding_loaded":true}` 即为就绪（首次会下载 BGE-M3）。

先在 `frontend/` 执行 `npm ci` 和 `npm run build`（需要 Node.js 22.12+ 或 24）。浏览器打开 `http://127.0.0.1:8000/` 仅显示右下角“问问探界”入口，点击展开 Vue 问答面板；该本地预览仍使用内部问答通道。
登录灌库和资料管理位于 `http://127.0.0.1:8000/admin`，与官网组件分离。缺少 `frontend/dist` 时首页返回构建提示；Docker 会自动构建。

## 先跑自检（不需要数据库 / 模型 / API Key）

```powershell
python scripts/smoke_kernel.py
```

它验证的是本项目最关键的一条假设——**从 FDE 搬来的内核，剥离用户/空间体系后依然完整可用**。


下一步：[L0 内部运营](../operations/L0_OPERATIONS.md) · [接口操作示例](../reference/api-examples.md)。默认账号和数据库口令仅用于本地演示，生产要求见[当前实现](../architecture/current-system.md)。
