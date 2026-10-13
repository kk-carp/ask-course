# 部署、备份与回滚

一期部署单副本。先在预发布完成本文演练；提供部署文件不代表完成真实生产验收。

2026-10-13 交接基线为 Agent `9b5e5db`、官网 `c4d980a`，CI 已通过，正式部署由王胜利老师执行。官网仓库 `docs/presales-agent-handover.md` 统一整理本次部署、验收、回滚及待签收项；本页为 Agent 通用操作说明。当前无已签收的生产回退镜像，首次失败优先停用入口。真实课程、生产账号撤销、ARM64 容量及生产恢复仍待验收。

## 配置和发布

1. 复制 `.env.example` 为 `.env.deploy`。设置 `APP_ENV=prod`、随机 `SECRET_KEY`、非默认 `DEMO_PASSWORD`、模型网关凭证和真实兜底联系人。
   按 [隐私与告警配置](PRIVACY_AND_SAFETY.md) 填写真实运营主体、隐私联系方式和模型服务商并人工确认；设置独立监控凭证、模型单价及每日预算。缺少隐私确认或监控凭证时生产启动会拒绝。
   本次资源路线必须覆盖仓库默认大模型：`EMBED_MODEL=BAAI/bge-small-zh-v1.5`、`EMBED_REVISION=7999e1d3359715c523056ef9478215996d62a620`、`EMBEDDING_DIM=512`、`EMBED_DEVICE=cpu`、`EMBED_TOKEN_LIMIT=512`、`RETRIEVE_USE_RERANK=false`、`RETRIEVE_USE_HYBRID=true`，查询指令按本次交接配置填写；检索阈值经真实课程正文校准。本地 0.416 不能直接当正式验收结论。问答配置当前已授权 DeepSeek 官方账户，模型名及额度由发布环境实测。
   最终官网范围包含登录身份，受限联调时 Python 的 `WEBSITE_IDENTITY_ENABLED` 和官网构建期 `VITE_PRESALES_IDENTITY_ENABLED` 配套开启；身份命名空间使用稳定的 `arborseek-production`，不带入本地数据。正式公开前完成双账号及退出撤销验收。
2. 增加 `POSTGRES_PASSWORD`，将 `DATABASE_URL` 指向 Compose 内的 `postgres:5432/arborseek_p0`。数据库 URL 中的密码需要 URL 编码。不要沿用本机 `localhost` 数据库地址。
3. 首次发布先保持 `PILOT_PERCENT=0`，不开放入口。准备本地 `data` 和 `docs`：课程原始资料不在仓库和镜像中，需通过受控渠道交付；本地运行资料整理/入库工具。挂载的资料需与代码版本一起备份。
4. `docker compose --env-file .env.deploy config --quiet` 验证配置；`docker compose --env-file .env.deploy build` 构建镜像。
5. 记录当前 Git 提交，将镜像标记为对应版本，例如 `ask-course:<commit>`，设置 `AGENT_IMAGE`。先备份数据库及资料，在数据库副本验证迁移；正式升级时先停止旧 API，再启动数据库，使用新镜像运行一次迁移，最后启动 API：

   ```powershell
   docker compose --env-file .env.deploy stop api
   docker compose --env-file .env.deploy up -d postgres
   docker compose --env-file .env.deploy run --rm --no-deps api python -m alembic upgrade head
   docker compose --env-file .env.deploy up -d --no-build api monitor
   ```

   迁移前必须从 API 容器的实际 TCP 数据库连接执行 `SELECT 1`；可用 `scripts.recovery_drill.wait_for_postgres`。容器内默认 Socket 的 `pg_isready` 可能检测到初始化临时服务，不能单独作为放行依据。上方命令逐条成功后继续，不整段忽略错误。任一迁移步骤失败时停止发布，按备份与迁移恢复方案处理；不要继续启动新 API。
6. 开放入口前先把固定 revision 的完整模型预缓存到持久卷，验证离线启动；不能在公众请求到来时才首次下载。确认 `/ready` 返回 200，再运行准出检查和真实课程评测；`/ready` 不调用 DeepSeek 或 PHP 身份接口，二者需要实际验证。
7. 本地官网已完成同源 `/agent/` 联调；生产仍由负责人配置 HTTPS 网关。独立 `/consult` 可验证游客流程，正式官网使用同源代理 `/agent/` 并剥离前缀；两种方式均须关闭 SSE 缓冲和共享缓存，读取超时至少 180 秒。API 只绑定本机端口，数据库与内部管理入口不向公众代理。测试移动端和购买跳转，官网身份联动另行签收。

`requirements.txt` 固定已验证的直接依赖版本；CI 使用不加载模型的 `requirements-ci.txt`。镜像版本及模型缓存固定后再发布，避免每次现场重新安装。CI 的虚构资料回归测试不能代替真实模型验收。

## 数据库升级

数据库结构由 Alembic 版本化迁移管理。应用启动要求版本已到当前代码的 `head`，不代替发布前迁移。首次基线接管旧结构并保留业务数据。升级前先备份，在数据库副本运行 `python -m alembic upgrade head`，核对文档、分片、向量、会话及完整消息后再升级正式库。迁移由单一发布步骤执行，不让多个副本同时迁移。删除或数据转换须有独立恢复方案，不能只靠应用镜像回退。

当前 `head` 为 `0005`，增加空索引维度配置保护；目标维度取执行时 `EMBEDDING_DIM`，版本号相同不保证列类型相同。非空索引禁止转换或降级，降级目标固定为基线 1024 维，详见[本地启动](../getting-started/README.md)。`0004` 增加资料继承指针、审核记录和待审核内容去重索引。新上传只进入待审核；升级前已有的 `ready` 资料保持可用，不伪造历史审核记录，应由课程负责人逐份复核。数据库中有待审核资料或审核记录时拒绝降回 `0003`，避免丢失审核证据；`0003` 在客户数据存在时也拒绝降级。必须先停止旧 API、备份数据库与原文件、在副本验证 `python -m alembic upgrade head`，再部署新代码。不能回滚到会自动发布上传资料的旧应用；发生故障先关闭入口，保留兼容版本或恢复已验证的联合备份。撤回与生成竞争已在独立 PostgreSQL 测试库验证，生产恢复演练仍需另行签收。

## 备份与恢复演练

以下以 PowerShell 为例。备份文件包含会话与联系方式，仅保存在受控存储，不提交代码仓库。

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$taskDbContainer = docker compose --env-file .env.deploy ps -q postgres
docker exec $taskDbContainer pg_dump -U postgres -d arborseek_p0 -Fc -f /tmp/arborseek-backup.dump
docker cp "${taskDbContainer}:/tmp/arborseek-backup.dump" backups/arborseek-backup.dump
```

另行备份 `data/uploads`、课程事实/正文/审核目录，以及部署配置；数据库中的文件路径需要对应文件才能恢复。

恢复演练使用独立空库，不覆盖原库：

```powershell
docker exec $taskDbContainer createdb -U postgres arborseek_restore_check
docker exec $taskDbContainer pg_restore -U postgres -d arborseek_restore_check --exit-on-error /tmp/arborseek-backup.dump
docker exec $taskDbContainer psql -U postgres -d arborseek_restore_check -c "SELECT count(*) FROM documents; SELECT count(*) FROM chunks;"
```

将副本应用临时连接到恢复库，验证资料问答、会话、二维码和购买入口。记录备份时间、恢复耗时及数量比对；每天备份，保留最近 7 天及发布前备份。

## 回滚和容量验收

发现错误购买页、错误顾问或严重事实错误时，先把 `/pilot/control` 设置为 0，确认独立页和已接入的官网入口隐藏；官网接入后同时保留撤下注入脚本的回滚方式。

保留上一版本镜像、不可变 SHA256 ID、配置及匹配资料。目标必须实际兼容当前 `0005`/512维结构及官网身份归属，具备资料审核、隐私及监控保护，不能回退到自动发布资料或仅支持1024维的旧应用。

当前 Dockerfile 的 `agent.schema` 标签仍为 `0004`，`scripts/rollback_release.py` 也只核对该旧标签及安全标记，不能据此证明 `0005`/512维兼容；本次不将该脚本视作可直接用于生产的一键回滚。先在独立恢复库与对应文件上验证目标镜像；由负责人关闭入口、停止 API/monitor，使用经签收的不可变镜像及匹配配置切换服务，核验 `/ready`、灰度0和核心流程后，将 `.env.deploy` 中 `AGENT_IMAGE` 持久化。失败保持 API 停止；不降级数据库、不自动开放。首次没有已签收目标时，只撤下Agent并恢复官网原功能。完整命令和记录模板见官网仓库的交接文档。

API 故障时单独执行 `docker compose --env-file .env.deploy run --rm --no-deps api python -m backend.scripts.emergency_stop` 关闭共享入口。随后停止 API 或在网关关闭路由，才能阻断已在处理的请求；灰度开关只拒绝新请求。不要执行 `down -v`，它会删除数据库。

发布前运行 `python scripts/recovery_drill.py`，验证虚构资料的数据库/文件联合恢复、全部表行数/内容哈希、会话与审核记录、停用状态保留及危险降级拒绝。该脚本不证明真实生产恢复或镜像回滚已通过，以本次生成的报告为准。预发布镜像演练另行记录当前/目标镜像 ID、数据备份路径、恢复耗时、实际问答案例及签收人。

受控环境从单路、两路实际官网问答开始记录容量；是否增加到更高并发由负责人根据整机和原业务余量决定。观察错误率、P50/P95、首个答案及总耗时，同时确认健康检查不被慢咨询阻塞。先据实记录容量，再确定流量比例。共享限流和多副本不在本次单副本试运行范围。

CPU 部署支持 `EMBED_CPU_THREADS=2` 控制推理线程竞争，本次小模型路线关闭重排。现有 Compose 没有资源上限，负责人需依据 ARM64 实测为 API/数据库确定预算，保留官网后端余量；先验证1/2并发，资源允许后才扩大。`scripts/load_test.py` 使用内部问答通道，不能代替带官网身份和Cookie的SSE链路验收。阶段耗时通过管理员 `/metrics` 的 `latency_ms` 查看；优化前固定样本和版本，按证据定位瓶颈。过往少量采样或数据库计数不作为当前生产容量与恢复签收结果，需在受控环境验证完整文件恢复、实际问答及镜像回退。
