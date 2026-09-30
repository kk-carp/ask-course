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

# 4. 启动
uvicorn backend.main:app --reload --reload-dir backend
```

启动时日志会打印三步进度。`GET http://127.0.0.1:8000/health` 返回
`{"api":true,"database":true,"embedding_loaded":true}` 即为就绪（首次会下载 BGE-M3）。

浏览器打开 `http://127.0.0.1:8000/` 是 **P0 内部演示页**（游客问答 + 登录灌库），不是官网挂件。
没有 `frontend/dist` 时，服务会直接托管 `frontend/index.html`。

## 先跑自检（不需要数据库 / 模型 / API Key）

```powershell
python scripts/smoke_kernel.py
```

它验证的是本项目最关键的一条假设——**从 FDE 搬来的内核，剥离用户/空间体系后依然完整可用**。


下一步：[L0 内部运营](../operations/L0_OPERATIONS.md) · [接口操作示例](../reference/api-examples.md)。默认账号和数据库口令仅用于本地演示，生产要求见[当前实现](../architecture/current-system.md)。
